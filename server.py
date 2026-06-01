"""
Sprint Board Server
Serves board.html, handles backlog writes, and streams agent output.

Usage:
  pip install flask
  python server.py
  open http://localhost:5000
"""

import json
import os
import queue
import re
import subprocess
import threading
import time
from datetime import datetime

import anthropic
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, Response, jsonify, request, send_file

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
SDLC_PIPELINE_FILE = os.path.join(BASE, "sdlc_pipeline.json")
ACTIVE_FILE  = os.path.join(BASE, "active.json")
INDEX_FILE   = "index.html"

agent_running = False
agent_lock = threading.Lock()
AGENT_LOG_FILE = os.path.join(BASE, "agent_log.json")

FUNCTIONAL_DESIGN_PROMPT = """You are an AI-DLC Functional Design assistant for Hello Scrum. Given a user story and acceptance criteria, produce a concrete implementation plan for patching index.html.

Return JSON only (no markdown):
{
  "implementation_approach": "one sentence describing the overall approach",
  "elements_to_add": ["HTML/CSS/JS element or block to add — be specific about tag, id, class"],
  "elements_to_modify": ["existing element to modify — name its id or class and what changes"],
  "existing_elements_touched": ["id or class of each existing element affected"],
  "risks": ["potential issue or edge case to watch for"]
}

Rules:
- implementation_approach: 1 sentence, max 20 words
- 2-4 items per array, each max 15 words
- elements_to_add: describe new HTML structure, CSS rules, or JS functions
- elements_to_modify: name the exact id/class from index.html that will change
- existing_elements_touched: list of ids/classes — used to prevent scope creep
- risks: things that could go wrong or cause Hermes to reject"""

INCEPTION_REVERSE_ENGINEER_PROMPT = """You are an AI-DLC Reverse Engineering assistant. Analyze this codebase summary and produce a concise architectural overview.

Return JSON only (no markdown). Keep all strings short — one sentence max per field.
{
  "architecture_summary": "one sentence describing what this system is",
  "components": [
    {"name": "short name", "file": "filename", "role": "one sentence role"}
  ],
  "key_endpoints": [
    {"method": "GET", "path": "/path", "purpose": "short purpose"}
  ],
  "business_transactions": ["Run a sprint", "Add a story to backlog"],
  "technical_patterns": ["SSE streaming", "JSON file as data store"]
}

Rules:
- architecture_summary: 1 sentence only
- components: 4-5 most important, role is max 10 words
- key_endpoints: 8 most important only, purpose is max 8 words
- business_transactions: 4-6 items, each 3-5 words
- technical_patterns: 3-5 items, each 3-5 words"""

INCEPTION_CLARIFY_PROMPT = """You are an AI-DLC Requirements Analysis assistant. Given a high-level intent, perform a structured requirements analysis.

First, assess the intent: classify its type (Feature/Enhancement/New Project/Refactor/Bug Fix), scope (Small/Medium/Large), and complexity (Simple/Moderate/Complex).

Then generate 4-6 targeted questions to fully clarify requirements before elaboration. Use these categories as appropriate:
- Users: primary users, personas, or stakeholders
- Functional: specific outcomes, features, or behaviours that define success
- Non-Functional: performance, scale, security, or reliability needs
- Constraints: dependencies, existing context, or boundaries of scope

Where useful, include 3-4 mutually exclusive options (A, B, C) the human can choose from. Leave options empty [] when a free-form answer is more appropriate.

Return JSON only (no markdown):
{
  "assessment": {"type": "Feature", "scope": "Medium", "complexity": "Moderate"},
  "questions": [
    {"id": 1, "category": "Users", "question": "Who are the primary users?", "options": ["A: End users / consumers", "B: Internal team / developers", "C: Both"]},
    {"id": 2, "category": "Functional", "question": "What does success look like for this feature?", "options": []}
  ]
}"""

INCEPTION_ELABORATE_PROMPT = """You are an AI-DLC Inception assistant. Given a high-level intent and clarifying answers, decompose into one Unit with 2-3 Stories and 1-2 suggested Bolts (sprint groupings). Return JSON only (no markdown):
{"unit": {"name": "Short Feature Name", "domain": "Bounded Context Label"}, "stories": [{"story": "As a <role>, I want <goal> so that <benefit>.", "idea": "One-line implementation instruction for the agent", "acceptance_criteria": ["testable criterion 1", "testable criterion 2", "testable criterion 3"]}, {"story": "As a <role>, I want <goal> so that <benefit>.", "idea": "One-line implementation instruction for the agent", "acceptance_criteria": ["testable criterion 1", "testable criterion 2"]}], "bolts": [{"name": "Bolt 1", "story_indices": [0, 1], "rationale": "Why these stories run together in one sprint"}, {"name": "Bolt 2", "story_indices": [2], "rationale": "Why this runs as a separate sprint"}], "nfrs": ["NFR 1", "NFR 2"], "risks": ["Risk 1", "Risk 2"]}

Rules:
- unit.name: 2-4 word feature name
- unit.domain: DDD bounded context label (e.g. "Sprint Performance", "Developer Experience", "Backlog Management")
- stories: 2-3 user stories; each has a human-readable story, a short agent-facing idea, and 2-4 testable AC
- bolts: 1-2 suggested sprint groupings; story_indices is a 0-based array referencing the stories array; a bolt runs its stories sequentially
- nfrs: 2-3 non-functional requirements for the whole unit
- risks: 2-3 risks for the whole unit"""

STORY_ELABORATION_PROMPT = """You are a scrum story writer. Given a raw idea, write a user story and acceptance criteria.

You have access to a read_file tool. Use it when the idea references existing code elements (colors, styles, components, data structures) and you need exact values to write accurate, testable acceptance criteria. For example: if the idea mentions matching a theme color, read index.html to find the actual hex value before writing the AC.

After gathering any needed context, respond with JSON only (no markdown):
{"story": "As a <role>, I want <goal> so that <benefit>.", "acceptance_criteria": ["<criterion 1>", "<criterion 2>", "<criterion 3>"]}
Keep the story concise. Write 3-4 acceptance criteria as short, testable statements. Use exact values from the codebase when relevant."""

# On startup, clear only mid-sprint states so a restarted server doesn't show
# a stale pulsing dot — but preserve done/failed/rejected so the panel persists.
_KEEP_STAGES = {"done", "failed", "rejected", "retro_done"}
try:
    with open(ACTIVE_FILE, encoding="utf-8") as _f:
        _s = json.load(_f).get("stage")
    if _s not in _KEEP_STAGES:
        with open(ACTIVE_FILE, "w", encoding="utf-8") as _f:
            json.dump({"item_id": None, "stage": None}, _f)
except Exception:
    with open(ACTIVE_FILE, "w", encoding="utf-8") as _f:
        json.dump({"item_id": None, "stage": None}, _f)


@app.route("/shared.css")
def shared_css():
    return send_file(os.path.join(BASE, "shared.css"))


@app.route("/shared.js")
def shared_js():
    return send_file(os.path.join(BASE, "shared.js"))


@app.route("/")
def index():
    return send_file(os.path.join(BASE, "board.html"))


@app.route("/index.html")
def app_page():
    return send_file(os.path.join(BASE, "index.html"))


@app.route("/prompts.html")
def prompts_page():
    return send_file(os.path.join(BASE, "prompts.html"))


@app.route("/prompts", methods=["GET"])
def get_prompts():
    import re
    with open(os.path.join(BASE, "agent.py"), encoding="utf-8") as f:
        agent_src = f.read()
    with open(os.path.join(BASE, "server.py"), encoding="utf-8") as f:
        server_src = f.read()

    entries = [
        ("SYSTEM_PROMPT",              "Worker Agent",              agent_src),
        ("RETRO_SYSTEM_PROMPT",        "Retrospective",             agent_src),
        ("CODE_REVIEW_SYSTEM_PROMPT",  "Hermes — Code Review",      agent_src),
        ("AC_CHECK_SYSTEM_PROMPT",     "Hermes — AC Check",         agent_src),
        ("STORY_ELABORATION_PROMPT",   "Story Elaboration",         server_src),
        ("CODING_WISDOM_PROMPT",       "Coding Wisdom Synthesis",   agent_src),
        ("AC_WISDOM_PROMPT",           "AC Wisdom Synthesis",       agent_src),
    ]

    result = []
    for name, label, src in entries:
        m = re.search(rf'^{name}\s*=\s*"""(.*?)"""', src, re.DOTALL | re.MULTILINE)
        result.append({"id": name, "label": label, "text": m.group(1).strip() if m else ""})
    return jsonify({"prompts": result})


@app.route("/audit.html")
def audit():
    return send_file(os.path.join(BASE, "audit.html"))


@app.route("/sdlc_pipeline.json")
def sdlc_pipeline_json():
    return send_file(SDLC_PIPELINE_FILE)


@app.route("/version.json")
def version_json_route():
    return send_file(os.path.join(BASE, "version.json"))


@app.route("/active.json")
def active_json():
    active_file = os.path.join(BASE, "active.json")
    if os.path.exists(active_file):
        return send_file(active_file)
    return jsonify({"item_id": None, "stage": None})


@app.route("/active.html")
def active_page():
    return send_file(os.path.join(BASE, "active.html"))


@app.route("/workflow.html")
def workflow_page():
    return send_file(os.path.join(BASE, "workflow.html"))


@app.route("/retro.html")
def retro_page():
    return send_file(os.path.join(BASE, "retro.html"))


@app.route("/intake.html")
def messenger_page():
    return send_file(os.path.join(BASE, "intake.html"))


@app.route("/notes.html")
def notes_page():
    return send_file(os.path.join(BASE, "notes.html"))


@app.route("/scrumai.html")
def scrumai_page():
    return send_file(os.path.join(BASE, "scrumai.html"))


@app.route("/chad.html")
def chad_page():
    return send_file(os.path.join(BASE, "chad.html"))


@app.route("/health.html")
def health_page():
    return send_file(os.path.join(BASE, "health.html"))


@app.route("/inception.html")
def inception_page():
    return send_file(os.path.join(BASE, "inception.html"))


@app.route("/construction.html")
def construction_page():
    return send_file(os.path.join(BASE, "construction.html"))


@app.route("/operations.html")
def operations_page():
    return send_file(os.path.join(BASE, "operations.html"))


@app.route("/hello-scrum.html")
def hello_scrum_page():
    return send_file(os.path.join(BASE, "hello-scrum.html"))


@app.route("/hello-scrum-aidlc.html")
def hello_scrum_aidlc_page():
    return send_file(os.path.join(BASE, "hello-scrum-aidlc.html"))


@app.route("/jeff.html")
def jeff_page():
    return send_file(os.path.join(BASE, "jeff.html"))


@app.route("/ai-dlc.html")
def ai_dlc_page():
    return send_file(os.path.join(BASE, "ai-dlc.html"))


@app.route("/health/diagnostics")
def health_diagnostics():
    out = {}

    # ── 1. Configuration integrity ────────────────────────────────────────────
    config = {}
    try:
        with open(os.path.join(BASE, "agent.py"), encoding="utf-8") as f:
            src = f.read()
        for const in ["CODING_WISDOM_FILE", "AC_WISDOM_FILE", "RETRO_FILE"]:
            m = re.search(rf'{const}\s*=\s*"([^"]+)"', src)
            val = m.group(1) if m else None
            exists = os.path.exists(os.path.join(BASE, val)) if val else False
            config[const] = {"value": val, "exists": exists}
    except Exception as e:
        config["error"] = str(e)
    out["config"] = config

    # ── 2. CSS checks on index.html ───────────────────────────────────────────
    css_checks = []
    try:
        with open(os.path.join(BASE, "index.html"), encoding="utf-8") as f:
            html = f.read()
        sm = re.search(r'<style>([\s\S]*?)</style>', html)
        style = sm.group(1) if sm else ""
        after = html[html.find('</style>') + 8:] if '</style>' in html else ""

        def chk(name, ok, detail=None):
            css_checks.append({"name": name, "pass": ok, "detail": detail})

        after_no_script = re.sub(r'<script[\s\S]*?</script>', '', after)
        css_after = bool(re.search(r'[a-zA-Z.#][^<{]*\{[^}]*\}', after_no_script))
        chk("No CSS outside style block", not css_after,
            "CSS found after </style>" if css_after else None)

        dup_h1 = len(re.findall(r'(?<![.\-\w])h1\s*[,{]', style))
        chk("No duplicate h1 rules", dup_h1 <= 1,
            f"{dup_h1} h1 rules found" if dup_h1 > 1 else None)

        dup_body = len(re.findall(r'\bbody\s*\{', style))
        chk("No duplicate body rules", dup_body <= 1,
            f"{dup_body} body rules found" if dup_body > 1 else None)

        has_webkit = '-webkit-text-fill-color' in style
        chk("-webkit-text-fill-color absent", not has_webkit,
            "Found -webkit-text-fill-color" if has_webkit else None)

        has_rgb   = bool(re.search(r'color:\s*rgb', style))
        has_hex   = bool(re.search(r'color:\s*#', style))
        chk("Single color format (hex only)", not (has_rgb and has_hex),
            "Mixed rgb() and hex found" if (has_rgb and has_hex) else None)
    except Exception as e:
        css_checks.append({"name": "CSS parse error", "pass": False, "detail": str(e)})
    out["css_checks"] = css_checks

    # ── 3. Data flow ──────────────────────────────────────────────────────────
    data_flow = {}
    try:
        with open(os.path.join(BASE, "sdlc_pipeline.json"), encoding="utf-8") as f:
            backlog = json.load(f)
        items = backlog.get("items", [])
        started = [i["started"] for i in items if i.get("started")]
        last_sprint_ts = max(started) if started else None

        with open(os.path.join(BASE, "retrospective.json"), encoding="utf-8") as f:
            retro_data = json.load(f)
        retros = retro_data.get("retros", [])
        last_retro_str = retros[0]["sprint_date"] if retros else None

        with open(os.path.join(BASE, "coding_wisdom.json"), encoding="utf-8") as f:
            sys_w = json.load(f)
        with open(os.path.join(BASE, "ac_wisdom.json"), encoding="utf-8") as f:
            story_w = json.load(f)

        sys_at   = sys_w.get("synthesized_at")
        story_at = story_w.get("synthesized_at")

        wisdom_stale = False
        if last_retro_str and sys_at:
            try:
                wisdom_stale = (
                    datetime.strptime(sys_at, "%Y-%m-%d %H:%M:%S") <
                    datetime.strptime(last_retro_str, "%Y-%m-%d %H:%M:%S")
                )
            except Exception:
                pass

        # Sprints processed since last retro
        sprints_since_retro = 0
        if last_retro_str:
            try:
                retro_ts = datetime.strptime(last_retro_str, "%Y-%m-%d %H:%M:%S").timestamp()
                sprints_since_retro = sum(
                    1 for i in items
                    if i.get("started", 0) > retro_ts
                    and i.get("status") in ("done", "failed")
                )
            except Exception:
                pass

        data_flow = {
            "last_sprint_ts":     last_sprint_ts,
            "last_retro_date":    last_retro_str,
            "coding_wisdom_at":   sys_at,
            "ac_wisdom_at":       story_at,
            "wisdom_stale":       wisdom_stale,
            "retro_count":        len(retros),
            "sprints_since_retro": sprints_since_retro,
        }
    except Exception as e:
        data_flow["error"] = str(e)
    out["data_flow"] = data_flow

    # ── 4. Wisdom quality ─────────────────────────────────────────────────────
    hex_re     = re.compile(r'#[0-9a-fA-F]{3,6}\b')
    ver_re     = re.compile(r'v\d+\.\d+')
    specific   = ['index.html', '.hero', '.tagline', 'hello scrum', 'board.html']
    wisdom_q   = {}
    for key, fname in [("coding", "coding_wisdom.json"), ("ac", "ac_wisdom.json")]:
        try:
            with open(os.path.join(BASE, fname), encoding="utf-8") as f:
                wd = json.load(f)
            bullets = wd.get("bullets", [])
            flagged = []
            for b in bullets:
                reasons = []
                if hex_re.search(b):      reasons.append("hex code")
                if ver_re.search(b):      reasons.append("version number")
                if len(b.split()) < 5:    reasons.append("too short")
                if any(s in b.lower() for s in specific): reasons.append("story-specific")
                if reasons:
                    flagged.append({"bullet": b, "reasons": reasons})
            wisdom_q[key] = {
                "bullets": bullets,
                "count": len(bullets),
                "flagged": flagged,
                "synthesized_at": wd.get("synthesized_at"),
                "finding_count": wd.get("finding_count") or wd.get("item_count"),
            }
        except Exception as e:
            wisdom_q[key] = {"error": str(e)}
    out["wisdom_quality"] = wisdom_q

    # ── 5. Rejection patterns ─────────────────────────────────────────────────
    pattern_map = {
        "CSS placement":      ["outside style", "style block", "style tag", "closing brace", "outside the style"],
        "Duplicate rules":    ["duplicate", "redundant", "conflicting rule", "layering"],
        "Selector issues":    ["selector", "webkit-text-fill", "specificity", "not target"],
        "Scope creep":        ["unrelated", "scope", "refactor", "restructur", "extensive"],
        "WCAG/accessibility": ["wcag", "contrast", "accessibility", "viewport", "layout shift"],
        "Encoding issues":    ["encoding", "unicode", "charmap", "codec"],
        "Version/timestamp":  ["version", "timestamp", "deployment", "separate commit"],
    }
    try:
        failure_texts = [
            f["text"].lower()
            for r in retro_data.get("retros", [])
            for f in r.get("findings", [])
            if f["type"] == "failure_pattern"
        ]
        rejection_patterns = {}
        for label, kws in pattern_map.items():
            count = sum(1 for t in failure_texts if any(kw in t for kw in kws))
            if count:
                rejection_patterns[label] = count
        out["rejection_patterns"] = dict(
            sorted(rejection_patterns.items(), key=lambda x: x[1], reverse=True)
        )
    except Exception as e:
        out["rejection_patterns"] = {"error": str(e)}

    # ── 6. Hermes consistency ─────────────────────────────────────────────────
    try:
        reviewed = [i for i in items if i.get("hermes_verdict")]
        approved = [i for i in reviewed if i["hermes_verdict"] == "approve"]
        rejected = [i for i in reviewed if i["hermes_verdict"] == "reject"]

        # Group rejection reasons by keyword bucket
        reason_buckets = {}
        for i in rejected:
            reason = (i.get("code_review_reason") or i.get("ac_check_reason") or i.get("hermes_reason") or "").lower()
            for label, kws in pattern_map.items():
                if any(kw in reason for kw in kws):
                    reason_buckets[label] = reason_buckets.get(label, 0) + 1
                    break

        # Find ideas rejected more than once (recurring failures on same topic)
        idea_failures = {}
        for i in rejected:
            key = i.get("idea", "")[:40].lower()
            idea_failures[key] = idea_failures.get(key, 0) + 1
        recurring = {k: v for k, v in idea_failures.items() if v > 1}

        out["hermes"] = {
            "total_reviewed": len(reviewed),
            "approved": len(approved),
            "rejected": len(rejected),
            "approve_rate": round(len(approved) / len(reviewed) * 100) if reviewed else 0,
            "rejection_buckets": reason_buckets,
            "recurring_failures": recurring,
        }
    except Exception as e:
        out["hermes"] = {"error": str(e)}

    # ── 7. Sprint trend (last 20) ─────────────────────────────────────────────
    try:
        processed = [i for i in items if i.get("started") and i.get("status") in ("done", "failed")]
        processed.sort(key=lambda x: x["started"])
        out["sprint_trend"] = [
            {"idea": i.get("idea", "")[:45], "status": i["status"], "started": i["started"]}
            for i in processed[-20:]
        ]
    except Exception:
        out["sprint_trend"] = []

    return jsonify(out)


@app.route("/messenger/send", methods=["POST"])
def messenger_send():
    try:
        data = request.get_json()
        message = (data or {}).get("message", "").strip()
        if not message:
            return jsonify({"reply": "Empty message.", "stories": None})

        # Build compact app state snapshot for query answering
        try:
            with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
                backlog = json.load(f)
            items = backlog.get("items", [])
            in_sprint  = [i for i in items if i.get("in_sprint") and i.get("status") == "pending"]
            pending    = [i for i in items if not i.get("in_sprint") and not i.get("opportunity") and i.get("status") == "pending"]
            opps       = [i for i in items if i.get("opportunity") and i.get("status") == "pending"]
            done_items = [i for i in items if i.get("status") == "done"]
            failed     = [i for i in items if i.get("status") == "failed"]

            sprint_lines = "\n".join(f"  - {i.get('idea','')}" for i in in_sprint) or "  (none)"
            recent_done  = "\n".join(f"  - {i.get('idea','')}" for i in done_items[-5:]) or "  (none)"

            with open(os.path.join(BASE, "version.json"), encoding="utf-8") as f:
                version_data = json.load(f)

            app_state = f"""CURRENT APP STATE:
Sprint ({len(in_sprint)} in progress):
{sprint_lines}
Story Backlog: {len(pending)} pending
Opportunity Backlog: {len(opps)} ideas
Total shipped: {len(done_items)} stories | Failed: {len(failed)}
Current version: {version_data.get('version','?')} — last deployed: {version_data.get('deployed','?')}
Recently shipped:
{recent_done}"""
        except Exception:
            app_state = "APP STATE: unavailable"

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=f"""You are the hello-scrum app assistant embedded in a team messenger.

{app_state}

Classify the user message and respond with JSON only (no markdown):

If it describes a story idea (something a developer could build):
{{"is_idea": true, "suggestions": ["<title 1>", "<title 2>"], "reply": "<one sentence acknowledging>"}}
If it asks a question about the app, sprint, backlog, or team progress:
{{"is_query": true, "reply": "<concise conversational answer using the app state above>"}}

Otherwise:
{{"reply": "<brief helpful response>"}}""",
            messages=[{"role": "user", "content": message}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.rsplit("```", 1)[0].strip()
        print(f"[messenger] model response: {text}", flush=True)
        try:
            result = json.loads(text)
        except Exception as parse_err:
            print(f"[messenger] JSON parse error: {parse_err}", flush=True)
            return jsonify({"reply": text, "stories": None})

        if result.get("is_idea") and result.get("suggestions"):
            sliced = result["suggestions"][:2]
            return jsonify({
                "reply": result.get("reply", "Looks like a story idea."),
                "stories": sliced,
                "original": message,
            })

        return jsonify({"reply": result.get("reply", ""), "stories": None})

    except Exception as e:
        return jsonify({"reply": f"Server error: {e}", "stories": None}), 500


@app.route("/messenger/meeting", methods=["POST"])
def messenger_meeting():
    try:
        data = request.get_json()
        transcript = (data or {}).get("transcript", "").strip()
        if not transcript:
            return jsonify({"error": "No transcript provided"}), 400

        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        items = backlog.get("items", [])

        all_stories = [i for i in items if not i.get("opportunity")]
        opportunities = [i for i in items if i.get("opportunity")]
        # Active stories always included; done/failed capped at 15 most recent to avoid
        # old test runs poisoning the messenger search
        active   = [i for i in all_stories if i.get("in_sprint") or i.get("status") == "pending"]
        inactive = sorted(
            [i for i in all_stories if i not in active],
            key=lambda x: x.get("started") or 0, reverse=True
        )[:5]
        ordered  = active + inactive
        stories_context = "\n".join(
            f"- [{i['id']}] {i.get('idea', '')}"
            + (" [IN SPRINT]" if i.get("in_sprint") else "")
            + (" [DONE]"      if i.get("status") == "done"   else "")
            + (" [FAILED]"    if i.get("status") == "failed" else "")
            + (f" (AC: {'; '.join(i['acceptance_criteria'][:2])})" if i.get("acceptance_criteria") else "")
            for i in ordered[:60]
        ) or "(none)"
        # Include opportunities separately so the model knows they already exist
        opps_context = "\n".join(
            f"- [{i['id']}] {i.get('idea', '')} [OPPORTUNITY]"
            for i in opportunities[:20]
        ) or "(none)"

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system="""You are a scrum assistant analyzing a meeting transcript against a product backlog.

Step 1 — Extract every distinct topic, feature, bug, or idea mentioned in the transcript.
Step 2 — For EACH extracted topic, scan the ENTIRE backlog list for any story that covers it, even loosely. Done and failed stories count — a [DONE] story means the feature already shipped.
Step 3 — Report results.

Respond with JSON only (no markdown):
{
  "alignments": [
    {"id": "<id>", "idea": "<story title>", "changes": "<what from discussion relates>", "needs_update": false},
    {"id": "<id>", "idea": "<story title>", "changes": "<what changed>", "needs_update": true, "proposed_idea": "<new title if changed, else omit>", "proposed_ac": ["<criterion>"]}
  ],
  "new_stories": ["<concise title ≤10 words>"]
}

Rules:
- Scan ALL backlog stories for each topic before declaring it a new story
- [DONE] stories are valid alignments — they show a feature is already shipped
- Only add to new_stories when NO existing story (including done ones) covers the topic
- Never put the same topic in both alignments and new_stories — if it matched a story, it goes in alignments only
- Only set needs_update: true when discussion clearly changes or adds requirements
- CRITICAL: alignment ids must be exact ids from the backlog list above — never invent or guess an id
- If no real backlog story matches a topic, put it in new_stories, not alignments
- Both arrays may be empty""",
            messages=[{"role": "user", "content": f"TRANSCRIPT:\n{transcript}\n\nFULL BACKLOG:\n{stories_context}\n\nOPPORTUNITY BACKLOG (already captured, not yet started):\n{opps_context}"}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)

        # Normalize: model sometimes returns 'updates' key instead of 'alignments'
        if "alignments" not in result and "updates" in result:
            result["alignments"] = result.pop("updates")

        # Normalize each alignment: 'summary' → 'changes', ensure needs_update bool
        for a in result.get("alignments", []):
            if "changes" not in a and "summary" in a:
                a["changes"] = a.pop("summary")
            a.setdefault("needs_update", False)

        # Drop hallucinated alignments whose IDs don't exist in the backlog
        valid_ids = {str(i["id"]) for i in items}
        result["alignments"] = [a for a in result.get("alignments", []) if str(a.get("id", "")) in valid_ids]

        # Enrich alignments with live status/in_sprint from backlog
        item_map = {str(i["id"]): i for i in items}
        for a in result.get("alignments", []):
            live = item_map.get(str(a.get("id", "")))
            if live:
                a["status"]      = live.get("status", "pending")
                a["in_sprint"]   = live.get("in_sprint", False)
                a["opportunity"] = bool(live.get("opportunity"))

        # Safety net: rescue any new_story that actually matches a backlog or opportunity story
        stop_words = {"a","an","the","in","on","at","to","for","of","and","or","is","it","be","that","this","with","as","from"}
        aligned_ids = {str(a.get("id","")) for a in result.get("alignments", [])}

        def kw(text):
            return {w.lower() for w in re.findall(r'\w+', text) if w.lower() not in stop_words}

        rescued, remaining = [], []
        for ns in result.get("new_stories", []):
            ns_kw = kw(ns)
            best_score, best_item, best_is_opp = 0.0, None, False
            for i in active + inactive + opportunities:
                story_kw = kw(i.get("idea", ""))
                union = ns_kw | story_kw
                if not union:
                    continue
                score = len(ns_kw & story_kw) / len(union)
                if score > best_score:
                    best_score, best_item = score, i
                    best_is_opp = bool(i.get("opportunity"))
            if best_item and str(best_item["id"]) in aligned_ids:
                continue  # already aligned — drop duplicate from new_stories silently
            if best_score >= 0.25 and best_item:
                rescued.append({
                    "id": best_item["id"],
                    "idea": best_item.get("idea", ""),
                    "changes": "Already captured as an opportunity." if best_is_opp else f'Mentioned as potential new story: "{ns}"',
                    "needs_update": False,
                    "status": best_item.get("status", "pending"),
                    "in_sprint": best_item.get("in_sprint", False),
                    "opportunity": best_is_opp,
                })
                aligned_ids.add(str(best_item["id"]))
            else:
                remaining.append(ns)

        result["alignments"] = result.get("alignments", []) + rescued
        result["new_stories"] = remaining

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/messenger/apply-update", methods=["POST"])
def apply_story_update():
    try:
        data = request.get_json()
        story_id      = (data or {}).get("id", "").strip()
        proposed_ac   = (data or {}).get("proposed_ac", [])
        proposed_idea = (data or {}).get("proposed_idea", "").strip()
        changes       = (data or {}).get("changes", "")

        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        item = next((i for i in backlog.get("items", []) if i["id"] == story_id), None)
        if not item:
            return jsonify({"error": "Story not found"}), 404
        if item.get("in_sprint") or item.get("status") != "pending":
            return jsonify({"error": "Story is in sprint or already processed"}), 400

        if proposed_idea and proposed_idea != item.get("idea"):
            item["idea"] = proposed_idea
        if proposed_ac:
            item["acceptance_criteria"] = proposed_ac
        if changes:
            item["meeting_update"] = changes
        with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(backlog, f, indent=2)
        return jsonify({"ok": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/messenger/choose", methods=["POST"])
def messenger_choose():
    try:
        data = request.get_json()
        story  = (data or {}).get("story", "").strip()
        source = (data or {}).get("source", "watercooler")
        if not story:
            return jsonify({"reply": "No story provided."})

        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        new_item = {
            "id": str(int(time.time() * 1000)),
            "idea": story,
            "status": "pending",
            "in_sprint": False,
            "opportunity": True,
            "source": source,
        }
        backlog.setdefault("items", []).insert(0, new_item)
        with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(backlog, f, indent=2)
        return jsonify({"reply": f"Added to opportunity backlog: <em>{story}</em>"})

    except Exception as e:
        return jsonify({"reply": f"Server error: {e}"}), 500


@app.route("/retrospective.json")
def retrospective_json():
    path = os.path.join(BASE, "retrospective.json")
    if os.path.exists(path):
        return send_file(path)
    return jsonify({"retros": []})


@app.route("/coding_wisdom.json")
def coding_wisdom_json():
    path = os.path.join(BASE, "coding_wisdom.json")
    if os.path.exists(path):
        return send_file(path)
    return jsonify({"bullets": [], "synthesized_at": None, "finding_count": 0})


@app.route("/docs/<name>")
def serve_doc(name):
    import re as _re
    if not _re.match(r'^[\w\-]+\.md$', name):
        return "Not found", 404
    path = os.path.join(BASE, "docs", name)
    if not os.path.exists(path):
        return "Not found", 404
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    escaped = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{name}</title>
<style>
body{{font-family:monospace;background:#0d0d0d;color:#ccc;padding:3rem 2rem 3rem 10rem;max-width:860px;line-height:1.7}}
h1{{color:#00ff99;font-size:1.6rem;margin-bottom:0.25rem}}
h2{{color:#00ff99;font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #222;padding-bottom:0.3rem}}
h3{{color:#88cc99;font-size:0.95rem;margin-top:1.25rem}}
a{{color:#4488ff}}
pre{{background:#111;border:1px solid #222;border-radius:4px;padding:1rem;overflow-x:auto;white-space:pre-wrap}}
code{{background:#111;border-radius:3px;padding:0.1rem 0.35rem;font-size:0.88rem}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #333;padding:0.4rem 0.75rem;text-align:left}}
th{{background:#1a1a1a;color:#00ff99}}
hr{{border:none;border-top:1px solid #222;margin:2rem 0}}
blockquote{{border-left:3px solid #333;margin:0;padding-left:1rem;color:#888}}
</style></head><body>
<a href="/workflow.html" style="font-size:0.78rem;color:#555;text-decoration:none">← Workflow</a>
<pre style="white-space:pre-wrap;border:none;background:none;padding:0;margin-top:1.5rem">{escaped}</pre>
</body></html>"""
    return html


@app.route("/notes.json")
def notes_json():
    path = os.path.join(BASE, "notes.json")
    if os.path.exists(path):
        return send_file(path)
    return jsonify([])


@app.route("/notes", methods=["POST"])
def save_notes():
    data = request.get_json()
    path = os.path.join(BASE, "notes.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return jsonify({"ok": True})


@app.route("/ac_wisdom.json")
def ac_wisdom_json():
    path = os.path.join(BASE, "ac_wisdom.json")
    if os.path.exists(path):
        return send_file(path)
    return jsonify({"bullets": [], "synthesized_at": None, "item_count": 0})


@app.route("/<path:filename>.html")
def serve_html(filename):
    safe = os.path.join(BASE, filename + ".html")
    if os.path.isfile(safe):
        return send_file(safe)
    return "Not found", 404


@app.route("/health/impediments")
def health_impediments():
    impediments = []
    try:
        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        items = backlog.get("items", [])

        # 1. Hermes reject rate
        reviewed = [i for i in items if i.get("hermes_verdict")]
        if len(reviewed) >= 5:
            approved = sum(1 for i in reviewed if i["hermes_verdict"] == "approve")
            rate = round(approved / len(reviewed) * 100)
            if rate < 70:
                pattern_map = {
                    "CSS placement":   ["outside style", "style block", "style tag"],
                    "Duplicate rules": ["duplicate", "redundant", "conflicting"],
                    "Scope creep":     ["unrelated", "scope", "refactor"],
                    "WCAG":            ["wcag", "contrast", "accessibility"],
                    "Version/timestamp": ["version", "timestamp"],
                }
                rejected = [i for i in reviewed if i["hermes_verdict"] == "reject"]
                buckets = {}
                for i in rejected:
                    reason = (i.get("code_review_reason") or i.get("ac_check_reason") or "").lower()
                    for label, kws in pattern_map.items():
                        if any(kw in reason for kw in kws):
                            buckets[label] = buckets.get(label, 0) + 1
                            break
                top = max(buckets, key=buckets.get) if buckets else None
                detail = f"{rate}% approve rate ({approved}/{len(reviewed)} reviewed)"
                if top:
                    detail += f" — {top} is the leading cause"
                impediments.append({
                    "severity": "critical" if rate < 50 else "warning",
                    "label": "High rejection rate",
                    "detail": detail,
                })

        # 2. Recurring failures
        failed_items = [i for i in items if i.get("status") in ("failed",) or i.get("hermes_verdict") == "reject"]
        idea_fails = {}
        for i in failed_items:
            key = i.get("idea", "")[:45].lower()
            idea_fails[key] = idea_fails.get(key, 0) + 1
        for idea, count in sorted(((k, v) for k, v in idea_fails.items() if v > 1), key=lambda x: x[1], reverse=True)[:3]:
            impediments.append({
                "severity": "warning",
                "label": "Recurring failure",
                "detail": f'"{idea}" failed {count}× — rewrite the story or AC',
            })

        # 3. Retro never run (no entries at all)
        try:
            with open(os.path.join(BASE, "retrospective.json"), encoding="utf-8") as f:
                retro_data = json.load(f)
            retros = retro_data.get("retros", [])
            processed_count = sum(1 for i in items if i.get("status") in ("done", "failed"))
            if not retros and processed_count >= 3:
                impediments.append({
                    "severity": "warning",
                    "label": "No retro data",
                    "detail": f"{processed_count} stories processed but no retrospective findings recorded",
                })
        except Exception:
            pass

        # 4. File size
        try:
            kb = round(os.path.getsize(os.path.join(BASE, "index.html")) / 1024, 1)
            if kb >= 16:
                impediments.append({"severity": "critical", "label": "File size critical", "detail": f"index.html is {kb}KB — consider baseline restore before next sprint"})
            elif kb >= 8:
                impediments.append({"severity": "warning", "label": "File size warning", "detail": f"index.html is {kb}KB — approaching 24KB budget"})
        except Exception:
            pass

        # 5. Sprint backlog empty
        sprint_pending = [i for i in items if i.get("in_sprint") and i.get("status") == "pending"]
        if not sprint_pending:
            impediments.append({
                "severity": "warning",
                "label": "Sprint backlog empty",
                "detail": "No stories queued — move items to sprint to enable pipeline runs",
            })

        # 6. Opportunity pipeline dry
        opp_items = [i for i in items if i.get("opportunity")]
        if not opp_items:
            impediments.append({
                "severity": "warning",
                "label": "Opportunity pipeline dry",
                "detail": "No ideas in opportunity backlog — nothing feeding the pipeline",
            })

        # 7. Wisdom quality degraded
        try:
            _hex_re = re.compile(r'#[0-9a-fA-F]{3,6}\b')
            _ver_re = re.compile(r'v\d+\.\d+')
            _specific = ['index.html', '.hero', '.tagline', 'hello scrum', 'board.html']
            with open(os.path.join(BASE, "coding_wisdom.json"), encoding="utf-8") as f:
                _cw = json.load(f)
            _bullets = _cw.get("bullets", [])
            if _bullets:
                _flagged = sum(
                    1 for b in _bullets
                    if _hex_re.search(b) or _ver_re.search(b) or any(s in b.lower() for s in _specific)
                )
                if _flagged >= 3 or _flagged / len(_bullets) > 0.5:
                    impediments.append({
                        "severity": "warning",
                        "label": "Wisdom quality degraded",
                        "detail": f"{_flagged}/{len(_bullets)} coding wisdom bullets contain story-specific or version-locked content",
                    })
        except Exception:
            pass

        # 8. Patch / pipeline failure rate (failures not caused by Hermes rejection)
        processed_all = [i for i in items if i.get("status") in ("done", "failed")]
        if len(processed_all) >= 5:
            pipeline_fails = [
                i for i in processed_all
                if i.get("status") == "failed" and i.get("hermes_verdict") != "reject"
            ]
            pfail_rate = round(len(pipeline_fails) / len(processed_all) * 100)
            if pfail_rate >= 20:
                impediments.append({
                    "severity": "critical" if pfail_rate >= 40 else "warning",
                    "label": "Pipeline failure rate",
                    "detail": f"{pfail_rate}% of stories failed in code/test/deploy stages — likely patch or test errors",
                })

        # 9. Cycle time regression (recent 5 vs prior 5 done stories)
        try:
            done_sorted = sorted(
                [i for i in items if i.get("status") == "done" and i.get("started") and i.get("stage_times")],
                key=lambda x: x["started"],
            )
            if len(done_sorted) >= 10:
                def _cycle(i):
                    end = i["stage_times"].get("done") or i["stage_times"].get("deploy")
                    return (end - i["started"]) if end and end > i["started"] else None
                recent_c = [c for c in (_cycle(i) for i in done_sorted[-5:]) if c]
                prior_c  = [c for c in (_cycle(i) for i in done_sorted[-10:-5]) if c]
                if recent_c and prior_c:
                    recent_avg = sum(recent_c) / len(recent_c)
                    prior_avg  = sum(prior_c)  / len(prior_c)
                    if prior_avg > 0 and recent_avg > prior_avg * 1.5:
                        pct = round((recent_avg / prior_avg - 1) * 100)
                        impediments.append({
                            "severity": "warning",
                            "label": "Cycle time regression",
                            "detail": f"Recent 5 stories avg {round(recent_avg)}s vs prior 5 avg {round(prior_avg)}s ({pct}% slower)",
                        })
        except Exception:
            pass

    except Exception as e:
        impediments.append({"severity": "critical", "label": "Data error", "detail": str(e)[:100]})

    impediments.sort(key=lambda x: {"critical": 0, "warning": 1}.get(x["severity"], 2))
    return jsonify({"impediments": impediments, "clear": len(impediments) == 0})


@app.route("/health/velocity")
def health_velocity():
    try:
        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        items = backlog.get("items", [])

        processed = sorted(
            [i for i in items if i.get("status") in ("done", "failed")
             and i.get("started") and i.get("stage_times")],
            key=lambda x: x["started"],
        )

        cycle_times, tokens_list = [], []
        for i in processed:
            if i["status"] == "done":
                end = i["stage_times"].get("done") or i["stage_times"].get("deploy")
                if end and end > i["started"]:
                    cycle_times.append(end - i["started"])
                t = (i.get("tokens_in") or 0) + (i.get("tokens_out") or 0)
                if t:
                    tokens_list.append(t)

        avg_cycle  = round(sum(cycle_times[-10:])  / len(cycle_times[-10:]))  if cycle_times  else None
        avg_tokens = round(sum(tokens_list[-10:]) / len(tokens_list[-10:])) if tokens_list else None

        # Group into sprint runs — gap > 10 min = new sprint
        GAP, sprints, current = 600, [], []
        for i in processed:
            if current and i["started"] - current[-1]["started"] > GAP:
                sprints.append(current)
                current = []
            current.append(i)
        if current:
            sprints.append(current)

        sprint_summaries = []
        for run in sprints[-5:]:
            done_items = [i for i in run if i["status"] == "done"]
            run_cycles = []
            for i in done_items:
                end = i["stage_times"].get("done") or i["stage_times"].get("deploy")
                if end and end > i["started"]:
                    run_cycles.append(end - i["started"])
            sprint_summaries.append({
                "date":        datetime.fromtimestamp(run[0]["started"]).strftime("%m/%d"),
                "stories":     len(run),
                "done":        len(done_items),
                "pass_rate":   round(len(done_items) / len(run) * 100) if run else 0,
                "avg_cycle_s": round(sum(run_cycles) / len(run_cycles)) if run_cycles else None,
            })

        cutoff = time.time() - 30 * 86400
        recent = [i for i in processed if i["started"] >= cutoff]
        recent_done = sum(1 for i in recent if i["status"] == "done")

        return jsonify({
            "avg_cycle_s":    avg_cycle,
            "avg_tokens":     avg_tokens,
            "total_done":     sum(1 for i in processed if i["status"] == "done"),
            "total_processed": len(processed),
            "pass_rate_30d":  round(recent_done / len(recent) * 100) if recent else None,
            "sprint_count":   len(sprints),
            "recent_sprints": sprint_summaries,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health/readiness")
def health_readiness():
    import urllib.request as _url
    checks = []

    # 1. API key
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    key_ok = bool(key and key.startswith("sk-ant-"))
    checks.append({
        "name": "Anthropic API key",
        "pass": key_ok,
        "detail": "Set" if key_ok else ("Set but unexpected format" if key else "Not set — ANTHROPIC_API_KEY missing"),
    })

    # 2. Required files
    required = [
        "agent.py", "index.html", "sdlc_pipeline.json", "version.json", "test.py",
        "shared.css", "coding_wisdom.json", "ac_wisdom.json", "index_baseline.html",
    ]
    missing = [f for f in required if not os.path.exists(os.path.join(BASE, f))]
    checks.append({
        "name": "Required files",
        "pass": not missing,
        "detail": "All present" if not missing else f"Missing: {', '.join(missing)}",
    })

    # 3. Git remote reachable
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=BASE,
        )
        git_ok = result.returncode == 0
        checks.append({
            "name": "Git remote (GitHub)",
            "pass": git_ok,
            "detail": "Reachable" if git_ok else (result.stderr.strip()[:80] or "Unreachable"),
        })
    except subprocess.TimeoutExpired:
        checks.append({"name": "Git remote (GitHub)", "pass": False, "detail": "Timeout after 10s"})
    except Exception as e:
        checks.append({"name": "Git remote (GitHub)", "pass": False, "detail": str(e)[:80]})

    # 4. GitHub Pages live
    try:
        resp = _url.urlopen("https://kfox25.github.io/hello-scrum", timeout=8)
        pages_ok = resp.status == 200
        checks.append({
            "name": "GitHub Pages live",
            "pass": pages_ok,
            "detail": f"HTTP {resp.status}" if pages_ok else f"HTTP {resp.status} — not live",
        })
    except Exception as e:
        checks.append({"name": "GitHub Pages live", "pass": False, "detail": str(e)[:80]})

    return jsonify({"checks": checks, "ready": all(c["pass"] for c in checks)})


@app.route("/health")
def health():
    index_path = os.path.join(BASE, "index.html")
    try:
        size = os.path.getsize(index_path)
        with open(index_path, encoding="utf-8") as f:
            lines = sum(1 for _ in f)
        tokens_est = size // 4
        if size < 8_000:
            status = "healthy"
        elif size < 16_000:
            status = "warning"
        else:
            status = "critical"
        return jsonify({
            "bytes": size,
            "kb": round(size / 1024, 1),
            "lines": lines,
            "tokens_est": tokens_est,
            "status": status,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health/score", methods=["GET"])
def health_score():
    """Composite health status for the nav indicator."""
    def lvl(s): return {"healthy": 0, "warning": 1, "critical": 2}.get(s, 0)

    file_kb, file_status = None, "healthy"
    hermes_rate, hermes_status = None, "healthy"
    cycle_pct, cycle_status = None, "healthy"
    velocity_bps, velocity_status = None, "healthy"
    css_drift, css_status = None, "healthy"
    wisdom_flagged, wisdom_total, wisdom_status = None, None, "healthy"
    overall = 0

    try:
        # ── File size ──────────────────────────────────────────────────────────
        size = os.path.getsize(os.path.join(BASE, "index.html"))
        file_kb = round(size / 1024, 1)
        file_status = "critical" if size >= 16_000 else "warning" if size >= 8_000 else "healthy"
        overall = max(overall, lvl(file_status))

        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            items = json.load(f).get("items", [])

        # ── Hermes approve rate ────────────────────────────────────────────────
        reviewed = [i for i in items if i.get("hermes_verdict")]
        if len(reviewed) >= 5:
            hermes_rate = round(sum(1 for i in reviewed if i["hermes_verdict"] == "approve") / len(reviewed) * 100)
            hermes_status = "critical" if hermes_rate < 40 else "warning" if hermes_rate < 70 else "healthy"
            overall = max(overall, lvl(hermes_status))

        # ── Cycle time regression ──────────────────────────────────────────────
        done_sorted = sorted(
            [i for i in items if i.get("status") == "done" and i.get("started") and i.get("stage_times")],
            key=lambda x: x["started"],
        )
        if len(done_sorted) >= 10:
            def _cycle(i):
                end = i["stage_times"].get("done") or i["stage_times"].get("deploy")
                return (end - i["started"]) if end and end > i["started"] else None
            recent_c = [c for c in (_cycle(i) for i in done_sorted[-5:]) if c]
            prior_c  = [c for c in (_cycle(i) for i in done_sorted[-10:-5]) if c]
            if recent_c and prior_c:
                recent_avg = sum(recent_c) / len(recent_c)
                prior_avg  = sum(prior_c)  / len(prior_c)
                if prior_avg > 0 and recent_avg > prior_avg * 1.5:
                    cycle_pct = round((recent_avg / prior_avg - 1) * 100)
                    cycle_status = "warning"
                    overall = max(overall, lvl(cycle_status))

        # ── File size velocity (bytes/story since last baseline restore) ───────
        try:
            baseline_size = os.path.getsize(os.path.join(BASE, "index_baseline.html"))
            growth = size - baseline_size
            git_log = subprocess.run(
                ["git", "log", "--format=%at", "--grep=Restore to baseline", "-1"],
                capture_output=True, text=True, cwd=BASE, timeout=5,
            )
            restore_ts = float(git_log.stdout.strip()) if git_log.stdout.strip() else 0
            done_since = [i for i in items if i.get("status") == "done" and i.get("started", 0) > restore_ts]
            count = max(len(done_since), 1)
            velocity_bps = round(growth / count)
            velocity_status = "critical" if velocity_bps > 800 else "warning" if velocity_bps > 400 else "healthy"
            overall = max(overall, lvl(velocity_status))
        except Exception:
            pass

        # ── CSS drift (duplicate rules in index.html) ──────────────────────────
        try:
            with open(os.path.join(BASE, "index.html"), encoding="utf-8") as f:
                html = f.read()
            sm = re.search(r'<style>([\s\S]*?)</style>', html)
            style = sm.group(1) if sm else ""
            dup_h1   = len(re.findall(r'(?<![.\-\w])h1\s*[,{]', style))
            dup_body = len(re.findall(r'\bbody\s*\{', style))
            css_drift = (dup_h1 > 1) or (dup_body > 1)
            if css_drift:
                css_status = "warning"
                overall = max(overall, lvl(css_status))
        except Exception:
            pass

        # ── Wisdom quality ─────────────────────────────────────────────────────
        try:
            _hex_re   = re.compile(r'#[0-9a-fA-F]{3,6}\b')
            _ver_re   = re.compile(r'v\d+\.\d+')
            _specific = ['index.html', '.hero', '.tagline', 'hello scrum', 'board.html']
            all_bullets, flagged = [], 0
            for fname in ["coding_wisdom.json", "ac_wisdom.json"]:
                with open(os.path.join(BASE, fname), encoding="utf-8") as f:
                    bullets = json.load(f).get("bullets", [])
                all_bullets.extend(bullets)
                for b in bullets:
                    if (_hex_re.search(b) or _ver_re.search(b) or
                            any(s in b.lower() for s in _specific)):
                        flagged += 1
            wisdom_total   = len(all_bullets)
            wisdom_flagged = flagged
            if wisdom_total >= 4 and flagged / wisdom_total > 0.5:
                wisdom_status = "warning"
                overall = max(overall, lvl(wisdom_status))
        except Exception:
            pass

    except Exception:
        pass

    return jsonify({
        "status": ["healthy", "warning", "critical"][overall],
        "file_kb": file_kb,       "file_status": file_status,
        "hermes_rate": hermes_rate, "hermes_status": hermes_status,
        "cycle_pct": cycle_pct,   "cycle_status": cycle_status,
        "velocity_bps": velocity_bps, "velocity_status": velocity_status,
        "css_drift": css_drift,   "css_status": css_status,
        "wisdom_flagged": wisdom_flagged, "wisdom_total": wisdom_total, "wisdom_status": wisdom_status,
    })


@app.route("/baseline/status", methods=["GET"])
def baseline_status():
    import hashlib
    def md5(path):
        try:
            return hashlib.md5(open(path, "rb").read()).hexdigest()
        except Exception:
            return None
    baseline_path = os.path.join(BASE, "index_baseline.html")
    index_path    = os.path.join(BASE, "index.html")
    at_baseline   = md5(index_path) == md5(baseline_path)
    return jsonify({"at_baseline": at_baseline})


@app.route("/baseline/restore", methods=["POST"])
def baseline_restore():
    baseline_path = os.path.join(BASE, "index_baseline.html")
    index_path = os.path.join(BASE, "index.html")
    if not os.path.exists(baseline_path):
        return jsonify({"error": "index_baseline.html not found"}), 404
    import shutil
    shutil.copy2(baseline_path, index_path)
    try:
        subprocess.run(["git", "add", "index.html"], cwd=BASE, check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=BASE)
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-m", "Restore to baseline for sprint testing"], cwd=BASE, check=True)
    except Exception as e:
        return jsonify({"error": f"File restored but git commit failed: {e}"}), 500
    return jsonify({"ok": True})


@app.route("/baseline/save", methods=["POST"])
def baseline_save():
    baseline_path = os.path.join(BASE, "index_baseline.html")
    index_path = os.path.join(BASE, "index.html")
    if not os.path.exists(index_path):
        return jsonify({"error": "index.html not found"}), 404
    import shutil
    shutil.copy2(index_path, baseline_path)
    return jsonify({"ok": True})


@app.route("/active/clear", methods=["POST"])
def clear_active():
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        json.dump({"item_id": None, "stage": None}, f)
    return jsonify({"ok": True})


@app.route("/sprint/backlog", methods=["GET"])
def sprint_backlog():
    with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
        data = json.load(f)
    items = [
        {"id": i["id"], "idea": i.get("idea", ""), "status": i.get("status", "pending")}
        for i in data.get("items", [])
        if i.get("in_sprint")
    ]
    return jsonify({"items": items})


@app.route("/sprint/item/<item_id>", methods=["GET"])
def sprint_item(item_id):
    with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
        data = json.load(f)
    for item in data.get("items", []):
        if item.get("id") == item_id:
            return jsonify(item)
    return jsonify({"error": "not found"}), 404


@app.route("/sprint/retro", methods=["GET"])
def sprint_retro():
    retro_file = os.path.join(BASE, "retrospective.json")
    try:
        with open(retro_file, encoding="utf-8") as f:
            data = json.load(f)
        retros = data.get("retros", [])
        if not retros:
            return jsonify({})

        # Return empty if the retro predates the current sprint.
        # Compare retro file mtime against the earliest item start time —
        # if any sprint item started after the retro was written, the retro is stale.
        retro_mtime = os.path.getmtime(retro_file)
        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            pipeline = json.load(f)
        sprint_items = [i for i in pipeline.get("items", []) if i.get("in_sprint")]
        started_times = [i["started"] for i in sprint_items if i.get("started")]
        if sprint_items and (not started_times or min(started_times) > retro_mtime):
            return jsonify({})

        return jsonify(retros[0])
    except Exception:
        return jsonify({})


SLOW_MODE_FILE = os.path.join(BASE, "slow_mode.json")

def _read_slow_mode():
    try:
        with open(SLOW_MODE_FILE, encoding="utf-8") as f:
            return json.load(f).get("enabled", False)
    except Exception:
        return False

def _write_slow_mode(enabled):
    with open(SLOW_MODE_FILE, "w", encoding="utf-8") as f:
        json.dump({"enabled": enabled}, f)

@app.route("/slow-mode", methods=["GET"])
def slow_mode_status():
    return jsonify({"enabled": _read_slow_mode()})

@app.route("/slow-mode/toggle", methods=["POST"])
def slow_mode_toggle():
    enabled = not _read_slow_mode()
    _write_slow_mode(enabled)
    return jsonify({"enabled": enabled})

@app.route("/slow-mode/set", methods=["POST"])
def slow_mode_set():
    data = request.get_json()
    enabled = bool((data or {}).get("enabled", False))
    _write_slow_mode(enabled)
    return jsonify({"enabled": enabled})


@app.route("/backlog", methods=["GET"])
def get_backlog():
    with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
        return jsonify(json.load(f))


@app.route("/backlog", methods=["POST"])
def save_backlog():
    data = request.get_json()
    with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return jsonify({"ok": True})


@app.route("/construction/design", methods=["POST"])
def construction_design():
    try:
        data      = request.get_json()
        story     = (data or {}).get("story", "").strip()
        ac        = (data or {}).get("acceptance_criteria", [])
        item_id   = (data or {}).get("item_id", "")
        if not story:
            return jsonify({"error": "No story provided"}), 400

        with open(os.path.join(BASE, INDEX_FILE), encoding="utf-8-sig") as f:
            index_html = f.read()

        ws_ctx = ""
        try:
            with open(os.path.join(BASE, "workspace_context.json"), encoding="utf-8") as f:
                ws = json.load(f)
            dm = ws.get("data_model", {})
            ft = {k: v for k, v in dm.get('field_types', {}).items() if v.startswith('Array') or v == 'object'}
            ft_line = ('\nField types: ' + '; '.join(f'{k}: {v}' for k, v in ft.items())) if ft else ''
            ws_ctx = (
                f"\nData store fields: {', '.join(dm.get('item_fields', []))}\n"
                f"Status values: {' | '.join(dm.get('status_values', []))}\n"
                f"Pipeline: {' → '.join(ws.get('pipeline_stages', []))}"
                f"{ft_line}"
            )
        except Exception:
            pass

        ac_str = "\n".join(f"- {c}" for c in ac) if ac else "(none)"
        user_msg = (
            f"Story: {story}\n\n"
            f"Acceptance criteria:\n{ac_str}\n"
            f"{ws_ctx}\n\n"
            f"index.html (current):\n{index_html[:8000]}"
        )

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=FUNCTIONAL_DESIGN_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        start = text.find("{")
        if start == -1:
            raise ValueError("No JSON in response")
        result, _ = json.JSONDecoder().raw_decode(text, start)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/construction/approve-design", methods=["POST"])
def construction_approve_design():
    try:
        data    = request.get_json()
        item_id = (data or {}).get("item_id", "")
        design  = (data or {}).get("design", {})
        if not item_id:
            return jsonify({"error": "No item_id"}), 400

        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        item = next((i for i in backlog.get("items", []) if i["id"] == item_id), None)
        if not item:
            return jsonify({"error": "Item not found"}), 404

        item["functional_design"] = design
        with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(backlog, f, indent=2)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/construction/clear-design", methods=["POST"])
def construction_clear_design():
    try:
        data    = request.get_json()
        item_id = (data or {}).get("item_id", "")
        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        item = next((i for i in backlog.get("items", []) if i["id"] == item_id), None)
        if item:
            item.pop("functional_design", None)
            with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
                json.dump(backlog, f, indent=2)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inception/add-stories-to-sprint", methods=["POST"])
def inception_add_stories_to_sprint():
    try:
        data = request.get_json()
        stories = (data or {}).get("stories", [])
        if not stories:
            return jsonify({"error": "No stories provided"}), 400
        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        added = []
        new_items = []
        for s in stories:
            story = s.get("story", "").strip()
            ac    = s.get("acceptance_criteria", [])
            if not story:
                continue
            item_id = re.sub(r"[^a-z0-9]+", "-", story.lower())[:48].strip("-") or str(int(time.time() * 1000))
            new_items.append({
                "id": item_id,
                "idea": story,
                "story": story,
                "acceptance_criteria": ac,
                "status": "pending",
                "in_sprint": True,
                "source": "inception",
            })
            added.append(item_id)
        backlog.setdefault("items", [])[:0] = new_items
        with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(backlog, f, indent=2)
        return jsonify({"ok": True, "count": len(added), "ids": added})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/backlog/mark-pending", methods=["POST"])
def mark_pending():
    try:
        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        count = 0
        for item in backlog.get("items", []):
            if item.get("in_sprint") and item.get("status") in ("done", "failed"):
                item["status"] = "pending"
                count += 1
        with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(backlog, f, indent=2)
        return jsonify({"ok": True, "count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inception/add-to-sprint", methods=["POST"])
def inception_add_to_sprint():
    try:
        data = request.get_json()
        intent = (data or {}).get("intent", "").strip()
        story  = (data or {}).get("story", "").strip()
        ac     = (data or {}).get("acceptance_criteria", [])
        if not story:
            return jsonify({"error": "No story provided"}), 400

        item_id = re.sub(r"[^a-z0-9]+", "-", intent.lower())[:48].strip("-") or str(int(time.time() * 1000))

        new_item = {
            "id": item_id,
            "idea": intent,
            "story": story,
            "acceptance_criteria": ac,
            "status": "pending",
            "in_sprint": True,
            "source": "inception",
        }

        with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
            backlog = json.load(f)
        backlog.setdefault("items", []).insert(0, new_item)
        with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(backlog, f, indent=2)

        return jsonify({"ok": True, "id": item_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inception/workspace", methods=["GET"])
def inception_workspace():
    try:
        import glob as _glob
        py_files   = [f for f in os.listdir(BASE) if f.endswith('.py')]
        js_files   = [f for f in os.listdir(BASE) if f.endswith('.js')]
        html_files = [f for f in os.listdir(BASE) if f.endswith('.html')]

        key_file_map = {
            'server.py':           'Flask API server (30+ routes)',
            'agent.py':            'Claude coding agent pipeline',
            'sdlc_pipeline.json':  'Sprint backlog and item store',
            'index.html':          'Test fixture app the agent modifies',
            'index_baseline.html': 'Baseline reset state for index.html',
        }
        key_files = [
            {'file': f, 'purpose': p}
            for f, p in key_file_map.items()
            if os.path.exists(os.path.join(BASE, f))
        ]

        def infer_field_type(samples):
            non_null = [s for s in samples if s is not None and s != '']
            if not non_null:
                return None
            sample = non_null[0]
            if isinstance(sample, list):
                inner = next((x for s in non_null if isinstance(s, list) for x in s), None)
                if inner is None:
                    return 'Array'
                if isinstance(inner, dict):
                    key_enums = {}
                    for lst in non_null:
                        for obj in (lst if isinstance(lst, list) else []):
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    key_enums.setdefault(k, set()).add(str(v) if not isinstance(v, str) else v)
                    parts = []
                    for k, vals in key_enums.items():
                        if len(vals) <= 5:
                            parts.append(f'{k}: {"|".join(sorted(f\'"{v}"\' for v in vals))}')
                        else:
                            parts.append(f'{k}: string')
                    return 'Array<{' + ', '.join(parts) + '}>'
                elif isinstance(inner, str):
                    return 'Array<string>'
                else:
                    return f'Array<{type(inner).__name__}>'
            elif isinstance(sample, bool):
                return 'boolean'
            elif isinstance(sample, (int, float)):
                return 'number'
            elif isinstance(sample, str):
                distinct = sorted(set(str(s) for s in non_null))
                return '|'.join(f'"{d}"' for d in distinct) if len(distinct) <= 6 else 'string'
            elif isinstance(sample, dict):
                return 'object'
            return type(sample).__name__

        data_model = {}
        item_count = 0
        try:
            with open(SDLC_PIPELINE_FILE, encoding='utf-8-sig') as f:
                pipeline = json.load(f)
            items = pipeline.get('items', [])
            item_count = len(items)
            if items:
                fields   = list(items[0].keys())
                statuses = sorted(set(i.get('status', '') for i in items if i.get('status')))
                sources  = sorted(set(i.get('source', '') for i in items if i.get('source')))
                sample_items = items[:50]
                field_types = {}
                for field in fields:
                    inferred = infer_field_type([i.get(field) for i in sample_items])
                    if inferred:
                        field_types[field] = inferred
                data_model = {
                    'item_fields':   fields,
                    'status_values': statuses,
                    'source_values': sources,
                    'field_types':   field_types,
                }
        except Exception:
            pass

        workspace = {
            'project_type':    'brownfield',
            'languages':       ['Python', 'JavaScript', 'HTML'],
            'file_counts':     {'python': len(py_files), 'javascript': len(js_files), 'html': len(html_files)},
            'key_files':       key_files,
            'item_count':      item_count,
            'data_model':      data_model,
            'pipeline_stages': ['pull', 'story', 'code', 'test', 'code_review', 'ac_check', 'deploy', 'done'],
            'agent_model':     'claude-sonnet-4-6',
            'reviewer_model':  'claude-haiku-4-5-20251001',
        }
        with open(os.path.join(BASE, 'workspace_context.json'), 'w', encoding='utf-8') as _wf:
            json.dump(workspace, _wf, indent=2)
        return jsonify(workspace)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/inception/reverse-engineer", methods=["POST"])
def inception_reverse_engineer():
    try:
        data      = request.get_json()
        workspace = (data or {}).get("workspace", {})

        # Check cache — if reverse_engineering.json exists and item_count matches, return it
        re_file = os.path.join(BASE, "reverse_engineering.json")
        if workspace.get("item_count") and os.path.exists(re_file):
            try:
                with open(re_file, encoding="utf-8") as f:
                    cached = json.load(f)
                if cached.get("item_count") == workspace.get("item_count"):
                    cached["cached"] = True
                    return jsonify(cached)
            except Exception:
                pass

        # Extract routes from server.py
        routes = []
        try:
            with open(os.path.join(BASE, "server.py"), encoding="utf-8") as f:
                srv = f.read()
            for m in re.finditer(
                r'@app\.route\("([^"]+)"(?:,\s*methods=\[([^\]]+)\])?\)\s*\ndef (\w+)',
                srv
            ):
                path, methods, fn = m.group(1), m.group(2), m.group(3)
                method = methods.replace('"','').replace("'","").strip() if methods else "GET"
                routes.append({"method": method, "path": path, "fn": fn})
        except Exception:
            pass

        # Extract info from agent.py
        agent_info = {"model": "claude-sonnet-4-6", "reviewer": "claude-haiku-4-5-20251001", "system_prompt_summary": ""}
        try:
            with open(os.path.join(BASE, "agent.py"), encoding="utf-8") as f:
                agt = f.read()
            sm = re.search(r'model="([^"]+)"', agt)
            if sm:
                agent_info["model"] = sm.group(1)
            # Extract first 3 lines of SYSTEM_PROMPT for context
            sp = re.search(r'SYSTEM_PROMPT\s*=\s*"""(.*?)"""', agt, re.DOTALL)
            if sp:
                first_lines = [l.strip() for l in sp.group(1).strip().splitlines()[:3] if l.strip()]
                agent_info["system_prompt_summary"] = " | ".join(first_lines)
        except Exception:
            pass

        # Build file inventory from html files
        html_files = sorted([f for f in os.listdir(BASE) if f.endswith('.html') and not f.startswith('index_')])
        py_files   = sorted([f for f in os.listdir(BASE) if f.endswith('.py')])
        file_inventory = (
            "Python: " + ", ".join(py_files) + "\n" +
            "HTML: " + ", ".join(html_files[:15])
        )

        # Build compact codebase summary for the LLM
        dm = workspace.get("data_model", {})
        route_lines = "\n".join(
            f"  {r['method']:6} {r['path']}" for r in routes[:30]
        )
        summary = f"""Project: Hello Scrum (brownfield Python/JS/HTML)
Files: {workspace.get('file_counts', {}).get('python', 0)} Python, {workspace.get('file_counts', {}).get('javascript', 0)} JS, {workspace.get('file_counts', {}).get('html', 0)} HTML

File inventory:
{file_inventory}

Key files:
  server.py     — Flask API server with {len(routes)} routes
  agent.py      — Claude coding agent (model: {agent_info.get('model','')})
  board.html    — Kanban sprint board (drag-and-drop)
  index.html    — Test fixture app the agent modifies
  sdlc_pipeline.json — Data store ({workspace.get('item_count', 0)} items)

Agent system prompt (first lines): {agent_info.get('system_prompt_summary', '')}

Data model (sdlc_pipeline.json items):
  fields:  {', '.join(dm.get('item_fields', []))}
  status:  {' | '.join(dm.get('status_values', []))}
  source:  {' | '.join(dm.get('source_values', []))}

Agent pipeline: {' → '.join(workspace.get('pipeline_stages', []))}

All API routes:
{route_lines}"""

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1800,
            system=INCEPTION_REVERSE_ENGINEER_PROMPT,
            messages=[{"role": "user", "content": summary}],
        )
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        start = text.find("{")
        if start == -1:
            raise ValueError("No JSON object in reverse engineering response")
        result, _ = json.JSONDecoder().raw_decode(text, start)
        # Build code_structure server-side — more reliable than asking Haiku
        known = {
            "server.py":              ("Flask API server — all routes, sprint start, inception endpoints", "server"),
            "agent.py":               ("Claude coding agent — pull/story/code/test/review/deploy pipeline", "agent"),
            "board.html":             ("Kanban sprint board — drag-and-drop, start sprint, mark pending", "frontend"),
            "index.html":             ("Test fixture app modified by the agent each sprint", "frontend"),
            "index_baseline.html":    ("Baseline reset state for index.html", "frontend"),
            "intake.html":            ("Team Chat + Watercooler — idea capture and intake", "frontend"),
            "inception.html":         ("AI-DLC inception flow — intent to stories to sprint", "frontend"),
            "active.html":            ("Live sprint view — current story, stage, streaming log", "frontend"),
            "retro.html":             ("Sprint retrospective — findings and wisdom display", "frontend"),
            "health.html":            ("System health dashboard — score, impediments, velocity", "frontend"),
            "audit.html":             ("Audit log — story diffs and agent decisions", "frontend"),
            "prompts.html":           ("Prompt viewer — all agent and inception prompts", "frontend"),
            "sdlc_pipeline.json":     ("Sprint backlog and item store — single source of truth", "data"),
            "workspace_context.json": ("Workspace snapshot saved by inception for agent injection", "data"),
            "reverse_engineering.json": ("Cached reverse engineering artifacts from last inception run", "data"),
            "coding_wisdom.json":     ("Synthesized coding directives from retrospectives", "data"),
            "ac_wisdom.json":         ("Synthesized AC-writing directives from retrospectives", "data"),
            "shared.js":              ("Nav injection, phase nav, health indicator", "config"),
            "shared.css":             ("Global styles — dark theme, layout, components", "config"),
        }
        code_structure = []
        for f in py_files + html_files:
            if f in known:
                purpose, ftype = known[f]
                code_structure.append({"file": f, "purpose": purpose, "type": ftype})
        result["code_structure"] = code_structure

        # Override business transactions and key endpoints server-side
        result["business_transactions"] = [
            "Run inception — intent to stories",
            "Start sprint — agent executes stories",
            "Review retrospective findings",
            "Add idea via Team Chat or Watercooler",
            "Check system health and impediments",
            "Restore baseline before sprint",
            "View sprint leaderboard",
        ]
        result["key_endpoints"] = [
            {"method": "POST", "path": "/sprint/start",                    "purpose": "Launch sprint — agent runs all in-sprint stories"},
            {"method": "GET",  "path": "/backlog",                         "purpose": "Fetch full pipeline including backlog and sprint items"},
            {"method": "POST", "path": "/inception/elaborate",             "purpose": "Generate unit, stories, bolts from intent + Q&A"},
            {"method": "POST", "path": "/inception/add-stories-to-sprint", "purpose": "Add inception stories to sprint"},
            {"method": "POST", "path": "/inception/workspace",             "purpose": "Scan codebase and save workspace_context.json"},
            {"method": "POST", "path": "/inception/reverse-engineer",      "purpose": "Analyze codebase and produce architectural artifacts"},
            {"method": "POST", "path": "/baseline/restore",                "purpose": "Reset index.html to baseline and commit"},
            {"method": "POST", "path": "/backlog/mark-pending",            "purpose": "Reset in-sprint done/failed items to pending"},
            {"method": "GET",  "path": "/active.json",                     "purpose": "Current sprint item, stage, and progress"},
            {"method": "GET",  "path": "/health/score",                    "purpose": "Composite health score for nav indicator"},
        ]

        result["business_dictionary"] = {
            "Bolt":          "A suggested sprint grouping from inception — one Bolt = one Sprint run",
            "Hermes":        "The AI reviewer (Haiku) that runs code_review and ac_check gates after each story",
            "Inception":     "The AI-DLC process that decomposes an intent into Unit, Stories, Bolts via inception.html",
            "Unit":          "An Epic — a bounded context grouping of related stories produced by inception",
            "Sprint":        "A sequential batch of stories executed by the agent in one run",
            "Story":         "A user story with acceptance criteria that the agent implements as patches to index.html",
            "Idea":          "The raw instruction text for a story — mirrors story text for inception items",
            "Opportunity":   "An idea in the opportunity backlog — not yet elaborated into a story",
            "in_sprint":     "Boolean — true means the item is queued for the current sprint run",
            "sprint_number": "Integer identifying which sprint batch an item ran in — used by the leaderboard",
            "source":        "Origin of an item: 'inception', 'team_chat', or 'watercooler'",
            "Retro":         "Retrospective — runs automatically after each sprint, produces findings and wisdom",
            "Wisdom":        "Synthesized coding/AC directives from past retros — injected into future agent prompts",
            "Workspace":     "The codebase snapshot saved by inception for downstream context injection",
        }

        result["item_count"] = workspace.get("item_count")
        result["cached"] = False

        with open(re_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inception/reverse-engineer/clear", methods=["POST"])
def inception_reverse_engineer_clear():
    try:
        re_file = os.path.join(BASE, "reverse_engineering.json")
        if os.path.exists(re_file):
            os.remove(re_file)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inception/clarify", methods=["POST"])
def inception_clarify():
    try:
        data = request.get_json()
        intent    = (data or {}).get("intent", "").strip()
        workspace = (data or {}).get("workspace", {})
        if not intent:
            return jsonify({"error": "No intent provided"}), 400

        re_ctx = (data or {}).get("reverse_engineering", {})
        ws_lines = []
        if re_ctx and re_ctx.get("architecture_summary"):
            dm = workspace.get("data_model", {})
            txns = re_ctx.get("business_transactions", [])
            patterns = re_ctx.get("technical_patterns", [])
            biz_dict = re_ctx.get("business_dictionary", {})
            dict_lines = "; ".join(f"{k}={v}" for k, v in list(biz_dict.items())[:8]) if biz_dict else ""
            ws_lines = [
                "\n\nCODEBASE CONTEXT (from Reverse Engineering — use to generate grounded questions):",
                f"Architecture: {re_ctx['architecture_summary']}",
                f"Business transactions: {', '.join(txns)}",
                f"Technical patterns: {', '.join(patterns)}",
                *([ f"Business dictionary: {dict_lines}" ] if dict_lines else []),
                f"Data store: sdlc_pipeline.json — fields: {', '.join(dm.get('item_fields', []))}",
                f"Status values: {' | '.join(dm.get('status_values', []))}",
                f"Source values: {' | '.join(dm.get('source_values', []))}",
                f"Agent pipeline: {' → '.join(workspace.get('pipeline_stages', []))}",
                "Agent modifies index.html — not a separate backend or database.",
            ]
        elif workspace:
            dm = workspace.get("data_model", {})
            ws_lines = [
                "\n\nCODEBASE CONTEXT:",
                f"Project type: {workspace.get('project_type', 'brownfield')} — existing Python/JS/HTML application",
                f"Item fields in sdlc_pipeline.json: {', '.join(dm.get('item_fields', []))}",
                f"Status values: {' | '.join(dm.get('status_values', []))}",
                f"Source values: {' | '.join(dm.get('source_values', []))}",
                f"Agent pipeline: {' → '.join(workspace.get('pipeline_stages', []))}",
                "Agent modifies index.html — not a separate backend or database.",
            ]
        user_msg = intent + "\n".join(ws_lines)

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=INCEPTION_CLARIFY_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        start, end = text.find("{"), text.rfind("}") + 1
        return jsonify(json.loads(text[start:end]))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inception/elaborate", methods=["POST"])
def inception_elaborate():
    try:
        data = request.get_json()
        intent    = (data or {}).get("intent", "").strip()
        qna       = (data or {}).get("qna", [])
        workspace = (data or {}).get("workspace", {})
        if not intent:
            return jsonify({"error": "No intent provided"}), 400

        qna_section = ""
        if qna:
            qna_section = "\n\nCLARIFICATION:\n" + "\n".join(
                f"Q: {item['q']}\nA: {item['a']}" for item in qna if item.get("a", "").strip()
            )

        re_ctx     = (data or {}).get("reverse_engineering", {})
        ws_section = ""
        def _field_types_line(dm):
            ft = {k: v for k, v in dm.get('field_types', {}).items() if v.startswith('Array') or v == 'object'}
            return ('Field types (complex — use exact access patterns): ' + '; '.join(f'{k}: {v}' for k, v in ft.items()) + '\n') if ft else ''

        if re_ctx and re_ctx.get("architecture_summary"):
            dm = workspace.get("data_model", {}) if workspace else {}
            txns = re_ctx.get("business_transactions", [])
            comps = re_ctx.get("components", [])
            biz_dict_elab = re_ctx.get("business_dictionary", {})
            dict_str = "; ".join(f"{k}={v}" for k, v in list(biz_dict_elab.items())[:8]) if biz_dict_elab else ""
            comp_lines = "\n".join(f"  - {c['name']} ({c['file']}): {c['role']}" for c in comps)
            dict_line = f"Business dictionary: {dict_str}\n" if dict_str else ""
            ws_section = (
                "\n\nCODEBASE CONTEXT (from Reverse Engineering):\n"
                f"Architecture: {re_ctx['architecture_summary']}\n"
                f"Components:\n{comp_lines}\n"
                f"Business transactions: {', '.join(txns)}\n"
                f"{dict_line}"
                f"Data store: sdlc_pipeline.json — fields: {', '.join(dm.get('item_fields', []))}\n"
                f"Status values: {' | '.join(dm.get('status_values', []))}\n"
                f"Source values: {' | '.join(dm.get('source_values', []))}\n"
                f"{_field_types_line(dm)}"
                f"Agent pipeline: {' → '.join(workspace.get('pipeline_stages', []) if workspace else [])}\n"
                "The agent implements stories by patching index.html. "
                "Stories must reference the actual data model and existing file structure."
            )
        elif workspace:
            dm = workspace.get("data_model", {})
            ws_section = (
                "\n\nCODEBASE CONTEXT:\n"
                f"Project: brownfield Python/JS/HTML app\n"
                f"Data store: sdlc_pipeline.json — items have fields: {', '.join(dm.get('item_fields', []))}\n"
                f"Status values: {' | '.join(dm.get('status_values', []))}\n"
                f"Source values: {' | '.join(dm.get('source_values', []))}\n"
                f"{_field_types_line(dm)}"
                f"Agent pipeline: {' → '.join(workspace.get('pipeline_stages', []))}\n"
                "The agent implements stories by patching index.html. "
                "Stories must reference the actual data model and existing file structure."
            )

        ac_wisdom_bullets = []
        try:
            with open(os.path.join(BASE, "ac_wisdom.json"), encoding="utf-8") as f:
                ac_wisdom_bullets = [b.lstrip("•").strip() for b in json.load(f).get("bullets", []) if b.strip()]
        except Exception:
            pass
        wisdom_section = ("\n\nAC WISDOM:\n" + "\n".join(f"- {b}" for b in ac_wisdom_bullets)) if ac_wisdom_bullets else ""

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=INCEPTION_ELABORATE_PROMPT,
            messages=[{"role": "user", "content": intent + qna_section + ws_section + wisdom_section}],
        )
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        start, end = text.find("{"), text.rfind("}") + 1
        return jsonify(json.loads(text[start:end]))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/backlog/elaborate", methods=["POST"])
def elaborate_story():
    try:
        data = request.get_json()
        idea = (data or {}).get("idea", "").strip()
        if not idea:
            return jsonify({"error": "No idea provided"}), 400

        # Load wisdom layers for injection
        ac_wisdom_bullets = []
        coding_wisdom_bullets = []
        try:
            with open(os.path.join(BASE, "ac_wisdom.json"), encoding="utf-8") as f:
                sw = json.load(f)
            ac_wisdom_bullets = [b.lstrip("•").strip() for b in sw.get("bullets", []) if b.strip()]
        except Exception:
            pass
        try:
            with open(os.path.join(BASE, "coding_wisdom.json"), encoding="utf-8") as f:
                sw = json.load(f)
            coding_wisdom_bullets = [b.lstrip("•").strip() for b in sw.get("bullets", []) if b.strip()]
        except Exception:
            pass

        wisdom_parts = []
        if ac_wisdom_bullets:
            wisdom_parts.append("AC WISDOM:\n" + "\n".join(f"- {b}" for b in ac_wisdom_bullets))
        if coding_wisdom_bullets:
            wisdom_parts.append("CODING WISDOM:\n" + "\n".join(f"- {b}" for b in coding_wisdom_bullets))
        wisdom_section = ("\n\n" + "\n\n".join(wisdom_parts)) if wisdom_parts else ""

        system_prompt = STORY_ELABORATION_PROMPT

        tools = [
            {
                "name": "read_file",
                "description": "Read a file from the project directory to get context for writing accurate acceptance criteria.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "The filename to read (e.g., 'index.html', 'version.json', 'shared.css'). Must be a file in the project root.",
                        }
                    },
                    "required": ["filename"],
                },
            }
        ]

        client = anthropic.Anthropic()
        messages = [{"role": "user", "content": idea + wisdom_section}]

        for _ in range(3):  # max 3 turns
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use" and block.name == "read_file":
                        filename = os.path.basename(block.input.get("filename", ""))
                        safe_path = os.path.join(BASE, filename)
                        if filename and os.path.isfile(safe_path):
                            with open(safe_path, encoding="utf-8") as f:
                                content = f.read()
                            print(f"[elaborate] read_file: {filename} ({len(content)} chars)", flush=True)
                        else:
                            content = f"File not found: {filename}"
                            print(f"[elaborate] read_file: {filename} — not found", flush=True)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content,
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                text_block = next((b for b in response.content if hasattr(b, "text")), None)
                if text_block:
                    text = text_block.text.strip()
                    if text.startswith("```"):
                        text = text.split("\n", 1)[-1]
                        text = text.rsplit("```", 1)[0].strip()
                    # extract JSON object even if Haiku adds surrounding text
                    start = text.find("{")
                    end   = text.rfind("}") + 1
                    if start != -1 and end > start:
                        text = text[start:end]
                    result = json.loads(text)
                    return jsonify(result)
                break

        return jsonify({"error": "Elaborate loop did not produce a result"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/agent-log")
def get_agent_log():
    try:
        with open(AGENT_LOG_FILE, encoding="utf-8") as f:
            return jsonify({"lines": json.load(f)})
    except Exception:
        return jsonify({"lines": []})


@app.route("/sprint/status")
def sprint_status():
    return jsonify({"running": agent_running})


@app.route("/sprint/start", methods=["POST"])
def start_sprint():
    global agent_running

    with agent_lock:
        if agent_running:
            return jsonify({"error": "Agent already running"}), 409
        agent_running = True

    line_queue = queue.Queue()

    def _reader():
        global agent_running
        try:
            with open(AGENT_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass
        try:
            with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
                _bl = json.load(f)
            _snum = _bl.get("sprint_number", 1)
            for _item in _bl.get("items", []):
                if _item.get("in_sprint") and _item.get("status") == "pending":
                    _item["sprint_number"] = _snum
            with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
                json.dump(_bl, f, indent=2)
        except Exception as _e:
            print(f"[sprint stamp error] {_e}", flush=True)
        try:
            proc = subprocess.Popen(
                ["python", "agent.py", "--sprint"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=BASE,
                env=os.environ.copy(),
            )
            for line in proc.stdout:
                line_queue.put(line.rstrip())
            proc.wait()
        except Exception as e:
            line_queue.put(f"[server error] {e}")
        finally:
            agent_running = False
            line_queue.put(None)  # sentinel — SSE stream can close now
            try:
                with open(SDLC_PIPELINE_FILE, encoding="utf-8-sig") as f:
                    _bl = json.load(f)
                _bl["sprint_number"] = _bl.get("sprint_number", 1) + 1
                with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
                    json.dump(_bl, f, indent=2)
            except Exception as _e:
                print(f"[sprint increment error] {_e}", flush=True)
            # Run retro in a separate daemon thread so SSE closes immediately
            sprint_result = os.path.join(BASE, "sprint_result.json")
            if os.path.exists(sprint_result):
                def _run_retro():
                    try:
                        subprocess.run(
                            ["python", "agent.py", "--run-retro"],
                            cwd=BASE,
                            env=os.environ.copy(),
                            timeout=120,
                        )
                    except Exception as e:
                        print(f"[retro error] {e}", flush=True)
                threading.Thread(target=_run_retro, daemon=True).start()

    threading.Thread(target=_reader, daemon=True).start()

    def generate():
        try:
            while True:
                try:
                    line = line_queue.get(timeout=30)
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    continue
                if line is None:
                    yield f"data: {json.dumps('__done__')}\n\n"
                    break
                yield f"data: {json.dumps(line)}\n\n"
        except GeneratorExit:
            pass  # client disconnected; _reader thread keeps draining so pipe never deadlocks

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    print("Sprint Board running at http://localhost:5000")
    app.run(debug=False, port=5000, threaded=True)
