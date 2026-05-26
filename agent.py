"""
AI Scrum Agent
Pulls the top backlog idea, implements it, tests it, and deploys it.

Usage:
  python agent.py          # run one story
  python agent.py --loop   # run until backlog is empty
  python agent.py --sprint # run all sprint items sequentially
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SDLC_PIPELINE_FILE = "sdlc_pipeline.json"
ACTIVE_FILE  = "active.json"
LOG_FILE     = "agent_log.json"
INDEX_FILE   = "index.html"
VERSION_FILE = "version.json"
TEST_SCRIPT  = "test.py"
REPO_URL     = "https://kfox25.github.io/hello-scrum"
RETRO_FILE         = "retrospective.json"
CODING_WISDOM_FILE = "coding_wisdom.json"
AC_WISDOM_FILE     = "ac_wisdom.json"

_log_lines = []

def log(msg=""):
    print(msg, flush=True)
    _log_lines.append(str(msg))
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(_log_lines, f)
    except Exception:
        pass

def log_lines(lines):
    for line in lines:
        print(line)
    sys.stdout.flush()
    _log_lines.extend(lines)
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(_log_lines, f)
    except Exception:
        pass

def clear_log():
    global _log_lines
    _log_lines = []
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    except Exception:
        pass

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    timeout=180.0,
)

SYSTEM_PROMPT = """You are an AI developer working on the hello-scrum web app.

Your job:
1. Read the provided idea, user story, and acceptance criteria
2. Implement the story using patches to index.html
3. Return an updated version_json — the boilerplate (version badge, popover, meta, counters, changelog HTML) is auto-updated by the deploy pipeline, NOT by you

Rules:
- Only modify index.html and version.json
- Bump the patch version (e.g. 0.1.0 -> 0.1.1) in version_json
- The changelog you receive contains only the most recent entry. Return version_json with ONLY that entry plus your new one — the pipeline merges it with the full history
- DO NOT patch: the version badge, version popover, meta/last-deployed line, features counter, streak counter, or changelog HTML entries — the pipeline handles those
- patches must contain ONLY the story-specific change (new elements, CSS additions, etc.)
- Each patch "find" must be a verbatim unique substring copied directly from the provided file
- NEVER use "</style>" as a patch "find" — it is not a unique anchor
- To MODIFY an existing CSS property: find the exact current declaration line (e.g. "      color: #00ff99;") and replace only that line with the new value — do NOT add a new rule
- To ADD new CSS: find a unique nearby line inside the style block as your anchor and insert alongside it — never insert after </style>
- Keep the page clean and minimal

Respond with ONLY valid JSON — no markdown, no code blocks, no extra text:
{
  "patches": [
    {"find": "exact unique text copied from index.html", "replace": "replacement text"}
  ],
  "version_json": { <full updated version.json object> },
  "summary": "Short commit message describing what changed"
}"""

RETRO_SYSTEM_PROMPT = """You are a Scrum retrospective facilitator analyzing sprint results for an AI coding agent.

Identify patterns across the sprint items and produce actionable findings.

Finding types:
- failure_pattern: a recurring reason items failed (e.g. patch errors, test failures, Hermes rejections)
- success_pattern: something that worked well this sprint
- improvement: a concrete suggestion to reduce failures or improve quality
- observation: a neutral noteworthy fact about this sprint

Respond with ONLY valid JSON — no markdown, no extra text:
{
  "findings": [
    {"type": "failure_pattern|success_pattern|improvement|observation", "text": "..."}
  ],
  "summary": "One sentence describing the overall sprint health"
}

Include 2-5 findings total. Be specific and actionable."""

CODE_REVIEW_SYSTEM_PROMPT = """You are Hermes, performing a code review for the hello-scrum web app.

Review the diff for technical correctness only. Approve unless you find a concrete defect:
- Syntax errors, broken HTML/CSS, or JavaScript that will throw at runtime
- A selector or property that cannot work as written
- Scope creep — changes to files or elements not related to the feature

Do NOT reject for any of the following — these are not code defects:
- Color choices, contrast ratios, or aesthetic opinions
- Whether a design decision looks good or matches your preference
- Accessibility concerns that require external tools (contrast checkers, Lighthouse, axe)
- Anything subjective about visual design

NOTE: version.json and deployment timestamp changes always accompany feature changes — do NOT reject for including them.
Do NOT evaluate whether the change satisfies business requirements — that is a separate check.

Respond with ONLY valid JSON — no markdown, no extra text:
{"verdict": "approve", "reason": "one sentence"}
or
{"verdict": "reject", "reason": "one sentence describing the specific code defect"}"""

AC_CHECK_SYSTEM_PROMPT = """You are Hermes, performing an acceptance criteria check for the hello-scrum web app.

Assume the code is technically correct. Evaluate only whether the implementation satisfies
the original idea and each acceptance criterion listed.

Only evaluate criteria that can be verified by reading the diff and source files directly.
If a criterion requires external tools (Lighthouse, axe, Chrome DevTools, contrast checkers,
Playwright, or any tool not present in the diff) treat it as satisfied if the implementation
intent is correct.

Respond with ONLY valid JSON — no markdown, no extra text:
{"verdict": "approve", "reason": "one sentence"}
or
{"verdict": "reject", "reason": "one sentence identifying which criterion was not met"}"""


# ── Active status ─────────────────────────────────────────────────────────────

def write_active(item, stage, **extra):
    now = datetime.now().timestamp()
    try:
        with open(ACTIVE_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        existing = {}
    if existing.get("item_id") == item["id"]:
        stage_times = existing.get("stage_times", {})
        started     = existing.get("started", now)
    else:
        stage_times = {}
        started     = now
    stage_times[stage] = now
    data = {
        "item_id": item["id"],
        "idea": item["idea"],
        "stage": stage,
        "started": started,
        "stage_times": stage_times,
    }
    data.update(extra)
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def clear_active():
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        json.dump({"item_id": None, "stage": None}, f)


# ── Backlog ───────────────────────────────────────────────────────────────────

def load_backlog():
    with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_backlog(data):
    with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_next_item(backlog, sprint_only=False):
    for item in backlog["items"]:
        if item["status"] == "pending":
            if sprint_only and not item.get("in_sprint"):
                continue
            return item
    return None


# ── App files ─────────────────────────────────────────────────────────────────

def read_app_files():
    with open(INDEX_FILE, encoding="utf-8") as f:
        index_html = f.read()
    with open(VERSION_FILE, encoding="utf-8") as f:
        version_json = f.read()
    return index_html, version_json


def strip_changelog_for_prompt(version_json_str):
    """Send only current version metadata to agent — never the full changelog."""
    data = json.loads(version_json_str)
    last = data.get("changelog", [])[-1:]
    return json.dumps({
        "version": data.get("version", "0.1.0"),
        "deployed": data.get("deployed", ""),
        "status": data.get("status", ""),
        "changelog": last,
    }, indent=2)


def get_ct_timestamp():
    ct = datetime.now(ZoneInfo("America/Chicago"))
    return ct.strftime("%Y-%m-%d %H:%M:%S CT")


# ── Worker agent ──────────────────────────────────────────────────────────────

def call_agent(idea, story, acceptance_criteria, index_html, version_json, timestamp, retro_context=None):
    context_parts = []
    wisdom = load_wisdom()
    if wisdom:
        context_parts.append("CODING WISDOM:\n" + "\n".join(f"- {b}" for b in wisdom))
    if retro_context:
        context_parts.append("SPRINT WISDOM:\n" + retro_context)
    context_section = ("\n\n" + "\n\n".join(context_parts)) if context_parts else ""

    version_json = strip_changelog_for_prompt(version_json)

    ac_str = "\n".join(f"- {c}" for c in acceptance_criteria) if acceptance_criteria else "(none)"

    prompt = f"""Deploy timestamp: {timestamp}
Idea: {idea}

Story: {story or '(none)'}

Acceptance criteria:
{ac_str}

index.html:
{index_html}

version.json:
{version_json}{context_section}

Implement. Return JSON only."""

    full_text = ""
    line_buffer = ""

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            full_text += chunk
            line_buffer += chunk
            while "\n" in line_buffer:
                line, line_buffer = line_buffer.split("\n", 1)
                log(line)
        final_msg = stream.get_final_message()

    if line_buffer.strip():
        log(line_buffer)

    return full_text, final_msg.usage.input_tokens, final_msg.usage.output_tokens


def auto_update_html(content, version_json_data, timestamp):
    """Update version badge, popover, meta, and counters."""
    changelog = version_json_data.get("changelog", [])
    if not changelog:
        return content
    latest      = changelog[-1]
    raw_ver     = latest.get("version", version_json_data.get("version", "0.1.0"))
    new_ver     = raw_ver if raw_ver.startswith("v") else "v" + raw_ver
    date_str    = timestamp[:10]
    change_text = latest.get("change", "")

    # Version badge
    content = re.sub(r'(id="version-badge"[^>]*>)v[\d.]+', rf'\g<1>{new_ver}', content)
    # Popover version
    content = re.sub(r'(<div class="vp-version">)v[\d.]+', rf'\g<1>{new_ver}', content)
    # Popover date
    content = re.sub(r'(<div class="vp-date">)[\d-]+', rf'\g<1>{date_str}', content)
    # Popover change text
    content = re.sub(r'(<div class="vp-change">)[^<]*', lambda m2: m2.group(1) + change_text, content)
    # Last deployed meta
    content = re.sub(r'(Last deployed: )[\d\- :]+ CT', rf'\g<1>{timestamp}', content)
    # Features counter and streak (use total deployed count)
    count = len([e for e in changelog if e.get("version", "0") != "0.1.0"]) + 1
    content = re.sub(r'(<div class="count">)\d+', rf'\g<1>{count}', content)
    content = re.sub(r'(&#128293; )\d+', rf'\g<1>{count}', content)
    return content


STYLE_PLACEHOLDER = "/* [existing-styles] */"

def apply_patch(content, find, replace):
    if STYLE_PLACEHOLDER in find:
        # Remove placeholder and any stray </style> tags; remainder is new CSS to inject
        new_css = replace.replace(STYLE_PLACEHOLDER, "").replace("</style>", "").strip()
        if new_css:
            return content.replace("</style>", "\n" + new_css + "\n</style>", 1)
        return content
    if find in content:
        return content.replace(find, replace, 1)
    # Fallback: allow any leading whitespace per line
    lines = find.splitlines()
    pattern = r"[ \t]*" + r"[\r\n]+[ \t]*".join(re.escape(l.lstrip()) for l in lines)
    m = re.search(pattern, content)
    if m:
        return content[:m.start()] + replace + content[m.end():]
    raise ValueError(f"Patch target not found in index.html: {repr(find[:80])}")


def apply_changes(response_text, timestamp):
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])

    data = json.loads(text)

    with open(INDEX_FILE, encoding="utf-8") as f:
        content = f.read()

    for patch in data.get("patches", []):
        content = apply_patch(content, patch["find"], patch["replace"])

    content = auto_update_html(content, data["version_json"], timestamp)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    # Merge agent's new changelog entry into the real full changelog
    with open(VERSION_FILE, encoding="utf-8") as f:
        real = json.load(f)
    agent_vj = data["version_json"]
    new_entries = [e for e in agent_vj.get("changelog", [])
                   if e.get("version") != real.get("version")]
    real["version"] = agent_vj.get("version", real["version"])
    real["deployed"] = timestamp
    real["changelog"].extend(new_entries)
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(real, f, indent=2)

    return data


# ── Hermes reviewer ───────────────────────────────────────────────────────────

def call_code_review(idea, story, diff):
    prompt = f"""Idea: {idea}

Story: {story}

Diff:
{diff[:12000]}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=CODE_REVIEW_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    return json.loads(text), message.usage.input_tokens, message.usage.output_tokens


def call_ac_check(idea, story, acceptance_criteria, diff, test_results):
    prompt = f"""Idea: {idea}

Story: {story}

Acceptance criteria:
{json.dumps(acceptance_criteria, indent=2)}

Diff:
{diff[:12000]}

Test results:
{json.dumps(test_results, indent=2)}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=AC_CHECK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    return json.loads(text), message.usage.input_tokens, message.usage.output_tokens


# ── Tests + deploy ────────────────────────────────────────────────────────────

def run_tests():
    result = subprocess.run(
        ["python", TEST_SCRIPT],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    return result.returncode == 0, result.stdout, result.stderr


def parse_test_results(stdout):
    results = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("PASS"):
            results.append({"status": "pass", "message": line[4:].strip()})
        elif line.startswith("FAIL"):
            results.append({"status": "fail", "message": line[4:].strip()})
    return results


def capture_diff():
    result = subprocess.run(
        ["git", "diff", INDEX_FILE, VERSION_FILE],
        capture_output=True, text=True,
    )
    return result.stdout


def git_push(summary):
    subprocess.run(["git", "add", INDEX_FILE, VERSION_FILE, SDLC_PIPELINE_FILE], check=True)
    subprocess.run(["git", "commit", "-m", summary], check=True)
    subprocess.run(["git", "push"], check=True)


def rollback():
    subprocess.run(["git", "checkout", "--", INDEX_FILE, VERSION_FILE])


# ── Retrospective ─────────────────────────────────────────────────────────────

def _call_retro_api(processed_items):
    """Call Haiku and return retro dict. No file I/O."""
    sprint_data = [
        {
            "idea":               i.get("idea"),
            "status":             i.get("status"),
            "story":              i.get("story", ""),
            "error":              i.get("error", ""),
            "hermes_verdict":     i.get("hermes_verdict", ""),
            "code_review_reason": i.get("code_review_reason", ""),
            "ac_check_reason":    i.get("ac_check_reason", ""),
            "test_results":       i.get("test_results", []),
        }
        for i in processed_items
    ]
    prompt = f"""Sprint items processed: {len(processed_items)}
Items done:   {sum(1 for i in processed_items if i.get('status') == 'done')}
Items failed: {sum(1 for i in processed_items if i.get('status') == 'failed')}

Results:
{json.dumps(sprint_data, indent=2)}

Analyze this sprint and return findings JSON."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=RETRO_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    retro = json.loads(text)
    retro["sprint_date"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    retro["items_analyzed"] = len(processed_items)
    retro["items_done"]     = sum(1 for i in processed_items if i.get("status") == "done")
    retro["items_failed"]   = sum(1 for i in processed_items if i.get("status") == "failed")
    return retro


def _retro_to_sprint_wisdom(retro):
    """Extract sprint wisdom string from a retro dict."""
    findings = retro.get("findings", [])
    if not findings:
        return None
    short = {"failure_pattern": "fail", "success_pattern": "ok", "observation": "note"}
    lines = [f"[{short[f['type']]}] {f['text']}" for f in findings if f["type"] in short]
    return "\n".join(lines) if lines else None


def generate_sprint_wisdom(processed_items):
    """Generate in-memory retro for mid-sprint feedback. Returns (wisdom_str, retro_dict).
    No file I/O, no wisdom synthesis."""
    if not processed_items:
        return None, None
    retro = _call_retro_api(processed_items)
    log(f"Sprint wisdom: {retro.get('summary', '')}")
    return _retro_to_sprint_wisdom(retro), retro


def load_wisdom():
    """Return list of stripped bullet strings from coding_wisdom.json, or empty list."""
    try:
        with open(CODING_WISDOM_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [b.lstrip("•").strip() for b in data.get("bullets", []) if b.strip()]
    except Exception:
        return []


def run_retro(processed_items, retro=None):
    """Persist retro to retrospective.json and synthesize wisdom.
    Accepts a pre-generated retro dict to avoid a redundant API call."""
    if not processed_items:
        return
    if retro is None:
        retro = _call_retro_api(processed_items)

    try:
        with open(RETRO_FILE, encoding="utf-8") as f:
            store = json.load(f)
    except Exception:
        store = {"retros": []}

    store.setdefault("retros", []).insert(0, retro)

    with open(RETRO_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)

    log(f"\nRetro: {retro.get('summary', '')}")
    log(f"Findings: {len(retro.get('findings', []))} item(s) written to retrospective.json")

    synthesize_coding_wisdom(processed_items)


def synthesize_ac_wisdom(sprint_items=None):
    """Update AC-writing directives incrementally from this sprint's outcomes, or bootstrap from history."""
    existing_bullets = []
    try:
        with open(AC_WISDOM_FILE, encoding="utf-8") as f:
            sw = json.load(f)
        existing_bullets = [b.lstrip("•").strip() for b in sw.get("bullets", []) if b.strip()]
    except Exception:
        pass

    try:
        with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
            backlog = json.load(f)
    except Exception:
        return

    all_completed = [i for i in backlog.get("items", [])
                     if i.get("status") in ("done", "failed", "rejected")]
    total_count = len(all_completed)
    if total_count < 3:
        return

    def to_entry(i):
        entry = {"idea": i.get("idea", "")[:80], "ac": i.get("acceptance_criteria", []), "status": i.get("status")}
        reason = i.get("ac_check_reason") or i.get("code_review_reason") or i.get("error", "")
        if reason and i.get("status") != "done":
            entry["rejected_for"] = reason[:120]
        return entry

    if existing_bullets and sprint_items:
        new_outcomes = [to_entry(i) for i in sprint_items
                        if i.get("status") in ("done", "failed", "rejected")]
        if not new_outcomes:
            return
        prompt = (
            "Update these AC-writing directives for a scrum story writer using new outcomes. "
            "Extract principles about WHAT MAKES AC GOOD — specificity, testability, verifiability. "
            "Do NOT copy AC content as directives. Incorporate new patterns, drop outdated ones. "
            "Output only directives warranted by the outcomes — up to 8 bullets, ≤12 words each, "
            "plain text, imperative voice. Start each with •\n\n"
            "Exclude: story-specific implementation details, WCAG/accessibility concerns, "
            "anything requiring external tools to verify.\n\n"
            "Current directives:\n" + "\n".join(f"• {b}" for b in existing_bullets) + "\n\n"
            "New story outcomes:\n" + json.dumps(new_outcomes, indent=2)
        )
    else:
        data = [to_entry(i) for i in all_completed[-50:]]
        prompt = (
            "Distill AC-writing directives for a scrum story writer from these outcomes. "
            "Extract principles about WHAT MAKES AC GOOD — specificity, testability, verifiability. "
            "Do NOT copy AC content as directives. "
            "Output only directives warranted by the outcomes — up to 8 bullets, ≤12 words each, "
            "plain text, imperative voice, specific to AI-implemented HTML/CSS/JS stories. "
            "Start each with •\n\n"
            "Exclude: story-specific implementation details, WCAG/accessibility concerns, "
            "anything requiring external tools to verify.\n\n"
            "Story outcomes:\n" + json.dumps(data, indent=2)
        )

    log("Synthesizing AC wisdom...")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    bullets = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("•")]

    with open(AC_WISDOM_FILE, "w", encoding="utf-8") as f:
        json.dump({"bullets": bullets, "synthesized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "item_count": total_count}, f, indent=2)
    log(f"AC wisdom: {len(bullets)} bullet(s) written to ac_wisdom.json")


def synthesize_coding_wisdom(processed_items=None):
    """Update coding directives incrementally from this sprint's findings, or bootstrap from history."""
    existing_bullets = []
    try:
        with open(CODING_WISDOM_FILE, encoding="utf-8") as f:
            data = json.load(f)
        existing_bullets = [b.lstrip("•").strip() for b in data.get("bullets", []) if b.strip()]
    except Exception:
        pass

    try:
        with open(RETRO_FILE, encoding="utf-8") as f:
            store = json.load(f)
    except Exception:
        synthesize_ac_wisdom(processed_items)
        return

    retros = store.get("retros", [])
    if not retros:
        synthesize_ac_wisdom(processed_items)
        return

    latest_findings = retros[0].get("findings", [])

    if existing_bullets and latest_findings:
        new_text = "\n".join(f"[{f['type']}] {f['text']}" for f in latest_findings)
        prompt = (
            "Update these coding directives for an AI agent using new sprint findings. "
            "Incorporate new patterns, drop outdated ones. "
            "Output only directives warranted by the findings — up to 8 bullets, ≤12 words each, "
            "plain text, imperative voice, specific to HTML/CSS/JS patching. Start each with •\n\n"
            "Exclude: accessibility/WCAG concerns, sprint process advice, steps enforced by the pipeline "
            "(tests, code review, deploy). Only include actionable coding mechanics.\n\n"
            "Current directives:\n" + "\n".join(f"• {b}" for b in existing_bullets) + "\n\n"
            "New findings:\n" + new_text
        )
    else:
        seen = set()
        all_findings = []
        for r in retros:
            for fnd in r.get("findings", []):
                key = f"{fnd['type']}:{fnd['text']}"
                if key not in seen:
                    seen.add(key)
                    all_findings.append(f"[{fnd['type']}] {fnd['text']}")
        if not all_findings:
            synthesize_ac_wisdom(processed_items)
            return
        prompt = (
            "Distill these sprint findings into coding directives for an AI agent. "
            "Output only directives warranted by the findings — up to 8 bullets, ≤12 words each, "
            "plain text (no markdown/bold), imperative voice, specific to HTML/CSS/JS patching. "
            "Start each line with •\n\n"
            "Exclude: accessibility/WCAG concerns, sprint process advice, steps enforced by the pipeline "
            "(tests, code review, deploy). Only include actionable coding mechanics.\n\n"
            "Findings:\n" + "\n".join(all_findings)
        )

    log("Synthesizing wisdom...")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    bullets = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("•")]

    seen = set()
    total_findings = sum(
        1 for r in retros for fnd in r.get("findings", [])
        if not seen.add(f"{fnd['type']}:{fnd['text']}")  # type: ignore[func-returns-value]
    )
    with open(CODING_WISDOM_FILE, "w", encoding="utf-8") as f:
        json.dump({"bullets": bullets, "synthesized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "finding_count": total_findings}, f, indent=2)
    log(f"Coding wisdom: {len(bullets)} bullet(s) written to coding_wisdom.json")
    synthesize_ac_wisdom(processed_items)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_one(sprint_only=False, processed=None, sprint_wisdom=None):
    backlog = load_backlog()
    item = get_next_item(backlog, sprint_only=sprint_only)

    if not item:
        print("No items to process.")
        return False

    if processed is not None:
        processed.append(item)

    tokens_in = 0
    tokens_out = 0

    clear_log()
    log(f"\n{'=' * 50}")
    log(f"  ITEM [{item['id']}]: {item['idea']}")
    log(f"{'=' * 50}")

    write_active(item, "pull")

    index_html, version_json = read_app_files()
    timestamp = get_ct_timestamp()

    log(f"Timestamp : {timestamp}")
    if sprint_wisdom:
        log("=== SPRINT WISDOM ===")
        for line in sprint_wisdom.splitlines():
            log(f"  {line}")
        log("")
    log("Calling agent...")
    write_active(item, "story", retro_context=sprint_wisdom)

    if sprint_wisdom:
        item["retro_context"] = sprint_wisdom

    try:
        response, t_in, t_out = call_agent(
            item["idea"],
            item.get("story", ""),
            item.get("acceptance_criteria", []),
            index_html, version_json, timestamp,
            retro_context=sprint_wisdom,
        )
        tokens_in += t_in
        tokens_out += t_out
    except Exception as e:
        log(f"Agent error: {e}")
        item["status"] = "failed"
        item["error"] = f"Agent error: {e}"
        ad = write_active(item, "failed", failed_at="story", error=str(e)[:160])
        item["started"] = ad.get("started"); item["stage_times"] = ad.get("stage_times", {})
        save_backlog(backlog)
        return False

    log("Applying changes...")
    write_active(item, "code", tokens_in=tokens_in, tokens_out=tokens_out)
    try:
        result = apply_changes(response, timestamp)
    except Exception as e:
        log(f"Parse error: {e}")
        log(f"Raw response preview: {response[:300]}")
        item["status"] = "failed"
        item["error"] = f"Parse error: {e} | Response preview: {response[:200]}"
        ad = write_active(item, "failed", failed_at="code", error=str(e)[:160], tokens_in=tokens_in, tokens_out=tokens_out)
        item["started"] = ad.get("started"); item["stage_times"] = ad.get("stage_times", {})
        item["tokens_in"] = tokens_in; item["tokens_out"] = tokens_out
        save_backlog(backlog)
        return False

    log("=== USER STORY ===")
    log(item.get('story', ''))
    log("")
    log("Acceptance Criteria:")
    for i, ac in enumerate(item.get("acceptance_criteria", []), 1):
        log(f"  {i}. {ac}")
    log("")
    log(f"Summary : {result['summary']}")

    diff = capture_diff()
    if diff:
        log_lines([l for l in diff.splitlines() if l])

    log("Running tests...")
    write_active(item, "test", tokens_in=tokens_in, tokens_out=tokens_out)
    passed, stdout, stderr = run_tests()
    log(stdout.strip())
    test_results = parse_test_results(stdout)

    if not passed:
        log("TESTS FAILED — rolling back")
        if stderr:
            log(stderr.strip())
        rollback()
        item["status"] = "failed"
        item["diff"] = diff
        item["test_results"] = test_results
        ad = write_active(item, "failed", failed_at="test", error="Tests failed — see activity stream", tokens_in=tokens_in, tokens_out=tokens_out)
        item["started"] = ad.get("started"); item["stage_times"] = ad.get("stage_times", {})
        item["tokens_in"] = tokens_in; item["tokens_out"] = tokens_out
        save_backlog(backlog)
        return False

    log("Hermes — code review...")
    write_active(item, "code_review", tokens_in=tokens_in, tokens_out=tokens_out)
    try:
        cr_verdict, t_in, t_out = call_code_review(item["idea"], item.get("story", ""), diff)
        tokens_in += t_in
        tokens_out += t_out
        code_review_verdict = cr_verdict.get("verdict", "approve")
        code_review_reason  = cr_verdict.get("reason", "")
    except Exception as e:
        log(f"Code review error (defaulting to approve): {e}")
        code_review_verdict = "approve"
        code_review_reason  = "Code review failed — defaulting to approve"

    log(f"Code review: {code_review_verdict.upper()} — {code_review_reason}")

    if code_review_verdict == "reject":
        rollback()
        item["status"] = "failed"
        item["diff"] = diff
        item["test_results"] = test_results
        item["code_review_verdict"] = code_review_verdict
        item["code_review_reason"]  = code_review_reason
        item["hermes_verdict"] = code_review_verdict
        item["hermes_reason"]  = code_review_reason
        ad = write_active(item, "rejected", rejected_at="code_review", hermes_verdict="reject", hermes_reason=code_review_reason, tokens_in=tokens_in, tokens_out=tokens_out)
        item["started"] = ad.get("started"); item["stage_times"] = ad.get("stage_times", {})
        item["tokens_in"] = tokens_in; item["tokens_out"] = tokens_out
        save_backlog(backlog)
        return False

    log("Hermes — AC check...")
    write_active(item, "ac_check", tokens_in=tokens_in, tokens_out=tokens_out)
    try:
        ac_verdict, t_in, t_out = call_ac_check(
            item["idea"],
            item.get("story", ""),
            item.get("acceptance_criteria", []),
            diff,
            test_results,
        )
        tokens_in += t_in
        tokens_out += t_out
        ac_check_verdict = ac_verdict.get("verdict", "approve")
        ac_check_reason  = ac_verdict.get("reason", "")
    except Exception as e:
        log(f"AC check error (defaulting to approve): {e}")
        ac_check_verdict = "approve"
        ac_check_reason  = "AC check failed — defaulting to approve"

    log(f"AC check: {ac_check_verdict.upper()} — {ac_check_reason}")
    log(f"Tokens : ↑{tokens_in:,} in  ↓{tokens_out:,} out")

    if ac_check_verdict == "reject":
        rollback()
        item["status"] = "failed"
        item["diff"] = diff
        item["test_results"] = test_results
        item["code_review_verdict"] = code_review_verdict
        item["code_review_reason"]  = code_review_reason
        item["ac_check_verdict"] = ac_check_verdict
        item["ac_check_reason"]  = ac_check_reason
        item["hermes_verdict"] = ac_check_verdict
        item["hermes_reason"]  = ac_check_reason
        ad = write_active(item, "rejected", rejected_at="ac_check", hermes_verdict="reject", hermes_reason=ac_check_reason, tokens_in=tokens_in, tokens_out=tokens_out)
        item["started"] = ad.get("started"); item["stage_times"] = ad.get("stage_times", {})
        item["tokens_in"] = tokens_in; item["tokens_out"] = tokens_out
        save_backlog(backlog)
        return False

    hermes_verdict = "approve"

    log("Pushing to GitHub...")
    write_active(item, "deploy", hermes_verdict="approve", tokens_in=tokens_in, tokens_out=tokens_out)
    item["status"] = "done"
    item["summary"] = result["summary"]
    item["diff"] = diff
    item["test_results"] = test_results
    item["deployed"] = timestamp
    item["code_review_verdict"] = code_review_verdict
    item["code_review_reason"]  = code_review_reason
    item["ac_check_verdict"] = ac_check_verdict
    item["ac_check_reason"]  = ac_check_reason
    item["hermes_verdict"] = hermes_verdict
    save_backlog(backlog)

    try:
        git_push(result["summary"])
    except Exception as e:
        log(f"Push failed: {e}")
        rollback()
        item["status"] = "failed"
        ad = write_active(item, "failed", failed_at="deploy", error=f"Push failed: {str(e)[:120]}", tokens_in=tokens_in, tokens_out=tokens_out)
        item["started"] = ad.get("started"); item["stage_times"] = ad.get("stage_times", {})
        item["tokens_in"] = tokens_in; item["tokens_out"] = tokens_out
        save_backlog(backlog)
        return False

    ad = write_active(item, "done", hermes_verdict=hermes_verdict, tokens_in=tokens_in, tokens_out=tokens_out)
    item["started"]     = ad.get("started")
    item["stage_times"] = ad.get("stage_times", {})
    item["tokens_in"]   = tokens_in
    item["tokens_out"]  = tokens_out
    save_backlog(backlog)
    log(f"\nDeployed: {timestamp}")
    log(f"Live at : {REPO_URL}")
    return True


def main():
    if "--synthesize" in sys.argv:
        synthesize_coding_wisdom()
        return

    sprint_mode = "--sprint" in sys.argv
    loop_mode = "--loop" in sys.argv
    print("\nAI Scrum Agent")
    print(f"Mode: {'sprint' if sprint_mode else 'loop' if loop_mode else 'single story'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if sprint_mode or loop_mode:
        processed = []
        sprint_wisdom = None  # story 1: CODING WISDOM only; SPRINT WISDOM loads after first item
        while True:
            prev_len = len(processed)
            success = run_one(sprint_only=sprint_mode, processed=processed, sprint_wisdom=sprint_wisdom)
            item_was_processed = len(processed) > prev_len
            if item_was_processed:
                backlog = load_backlog()
                more_items = get_next_item(backlog, sprint_only=sprint_mode) is not None
                if more_items:
                    log("\nGenerating sprint wisdom...")
                    try:
                        sprint_wisdom, _ = generate_sprint_wisdom(processed)
                    except Exception as e:
                        log(f"Sprint wisdom error: {e}")
                        sprint_wisdom = None
                else:
                    log("\nRunning final retrospective...")
                    try:
                        run_retro(processed)
                    except Exception as e:
                        log(f"Retro error: {e}")
                    break
            if not item_was_processed:
                break
    else:
        run_one()


if __name__ == "__main__":
    main()
