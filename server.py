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

from flask import Flask, Response, jsonify, request, send_file

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
SDLC_PIPELINE_FILE = os.path.join(BASE, "sdlc_pipeline.json")
ACTIVE_FILE  = os.path.join(BASE, "active.json")

agent_running = False
agent_lock = threading.Lock()
AGENT_LOG_FILE = os.path.join(BASE, "agent_log.json")

# On startup, clear only mid-sprint states so a restarted server doesn't show
# a stale pulsing dot — but preserve done/failed/rejected so the panel persists.
_KEEP_STAGES = {"done", "failed", "rejected"}
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


@app.route("/")
def index():
    return send_file(os.path.join(BASE, "board.html"))


@app.route("/index.html")
def app_page():
    return send_file(os.path.join(BASE, "index.html"))


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


@app.route("/messenger.html")
def messenger_page():
    return send_file(os.path.join(BASE, "messenger.html"))


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

        css_after = bool(re.search(r'[a-zA-Z.#][^<{]*\{[^}]*\}', after))
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

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system="""You are a scrum assistant. Determine if this message describes a story idea — something a developer could build as a feature or improvement.

If YES: generate 2 distinct alternative phrasings as concise backlog titles (≤10 words each, action-oriented). Respond with JSON only (no markdown):
{"is_idea": true, "suggestions": ["<title 1>", "<title 2>"], "reply": "<one sentence acknowledging the idea>"}

If NO: respond with JSON only (no markdown):
{"is_idea": false, "reply": "<brief helpful response>"}""",
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
            return jsonify({
                "reply": result.get("reply", "Looks like a story idea."),
                "stories": result["suggestions"],
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

        with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
            backlog = json.load(f)
        items = backlog.get("items", [])

        all_stories = [i for i in items if not i.get("opportunity")]
        opportunities = [i for i in items if i.get("opportunity")]
        # Active stories first so they are never cut off by the slice limit
        active   = [i for i in all_stories if i.get("in_sprint") or i.get("status") == "pending"]
        inactive = [i for i in all_stories if i not in active]
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
            for i in all_stories + opportunities:
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

        with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
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
        story = (data or {}).get("story", "").strip()
        if not story:
            return jsonify({"reply": "No story provided."})

        with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
            backlog = json.load(f)
        new_item = {
            "id": str(int(time.time() * 1000)),
            "idea": story,
            "status": "pending",
            "in_sprint": False,
            "opportunity": True,
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
        with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
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
        with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
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


@app.route("/baseline/restore", methods=["POST"])
def baseline_restore():
    baseline_path = os.path.join(BASE, "index_baseline.html")
    index_path = os.path.join(BASE, "index.html")
    if not os.path.exists(baseline_path):
        return jsonify({"error": "index_baseline.html not found"}), 404
    import shutil
    shutil.copy2(baseline_path, index_path)
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


@app.route("/backlog", methods=["GET"])
def get_backlog():
    with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/backlog", methods=["POST"])
def save_backlog():
    data = request.get_json()
    with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return jsonify({"ok": True})


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

        system_prompt = (
            "You are a scrum story writer. Given a raw idea, write a user story and acceptance criteria.\n\n"
            "You have access to a read_file tool. Use it when the idea references existing code elements "
            "(colors, styles, components, data structures) and you need exact values to write accurate, "
            "testable acceptance criteria. For example: if the idea mentions matching a theme color, "
            "read index.html to find the actual hex value before writing the AC.\n\n"
            "After gathering any needed context, respond with JSON only (no markdown):\n"
            '{"story": "As a <role>, I want <goal> so that <benefit>.", "acceptance_criteria": ["<criterion 1>", "<criterion 2>", "<criterion 3>"]}\n'
            "Keep the story concise. Write 3-4 acceptance criteria as short, testable statements. "
            "Use exact values from the codebase when relevant."
        )

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
