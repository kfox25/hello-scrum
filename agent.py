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
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SDLC_PIPELINE_FILE = "sdlc_pipeline.json"
ACTIVE_FILE  = "active.json"
LOG_FILE     = "agent_log.json"
INDEX_FILE   = "index.html"
VERSION_FILE = "version.json"
TEST_SCRIPT  = "test.py"
REPO_URL     = "https://kfox25.github.io/hello-scrum"
RETRO_FILE             = "retrospective.json"
CODING_WISDOM_FILE     = "coding_wisdom.json"
AC_WISDOM_FILE         = "ac_wisdom.json"
SPRINT_RESULT_FILE     = "sprint_result.json"
WORKSPACE_CONTEXT_FILE = "workspace_context.json"

_log_lines = []
_retro_active_stage = None
_suppress_log_writes = False

def log(msg=""):
    try:
        print(msg, flush=True)
    except OSError:
        pass  # stdout pipe closed (e.g. SSE client disconnected) — continue silently
    _log_lines.append(str(msg))
    if not _suppress_log_writes:
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
    if not _suppress_log_writes:
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

SCOPE DISCIPLINE — this is critical:
- Your "replace" MUST contain everything that is in your "find". Never use a patch to delete existing code as a side effect. If you are inserting new content, your replace = (everything from find) + (your new addition). If the find contains 5 lines, the replace must contain those same 5 lines plus any new lines you are adding.
- Make patches as small as possible. Find the single line closest to your insertion point and use that as the anchor — do not grab large blocks.
- If the story does not ask you to remove something, do not remove it. Ever.
- Before finalising each patch, ask yourself: "Does my replace contain every character from my find?" If no, rewrite the patch.

SCOPE EXAMPLE — burned into memory:
WRONG (this will be rejected — .other-rule was deleted as a side effect):
  find:    "  .h1 { color: red; }\n  .other-rule { display: flex; }"
  replace: "  .h1 { color: red; text-shadow: 0 0 10px #00ff9950; }"
RIGHT (single-line anchor, nothing deleted):
  find:    "  .h1 { color: red; }"
  replace: "  .h1 { color: red; text-shadow: 0 0 10px #00ff9950; }"

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

CODING_WISDOM_PROMPT = """Update these coding directives for an AI agent using new sprint findings. Incorporate new patterns, drop outdated ones. Output only directives warranted by the findings — up to 8 bullets, ≤12 words each, plain text, imperative voice, specific to HTML/CSS/JS patching. Start each with •

Exclude: accessibility/WCAG concerns, sprint process advice, steps enforced by the pipeline (tests, code review, deploy). Only include actionable coding mechanics.

[Current directives and new findings appended at runtime]"""

AC_WISDOM_PROMPT = """Update these AC-writing directives for a scrum story writer using new outcomes. Extract principles about WHAT MAKES AC GOOD — specificity, testability, verifiability. Do NOT copy AC content as directives. Incorporate new patterns, drop outdated ones. Output only directives warranted by the outcomes — up to 8 bullets, ≤12 words each, plain text, imperative voice. Start each with •

Exclude: story-specific implementation details, WCAG/accessibility concerns, anything requiring external tools to verify.

[Current directives and new story outcomes appended at runtime]"""

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


# ── Slow mode ────────────────────────────────────────────────────────────────

SLOW_MODE_FILE = "slow_mode.json"
SLOW_MODE_PAUSE = 3  # seconds to pause between stages

def slow_mode_enabled():
    try:
        with open(SLOW_MODE_FILE, encoding="utf-8") as f:
            return json.load(f).get("enabled", False)
    except Exception:
        return False

def slow_pause(stage_name):
    if not slow_mode_enabled():
        return
    log(f"[slow mode] pausing at {stage_name}…")
    for _ in range(SLOW_MODE_PAUSE):
        if not slow_mode_enabled():
            log("[slow mode] toggled off — continuing")
            return
        import time as _time
        _time.sleep(1)


# ── Active status ─────────────────────────────────────────────────────────────

_CARRY_FORWARD_KEYS = {"story", "acceptance_criteria", "change_summary", "test_pass_count", "test_total"}

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
        for key in _CARRY_FORWARD_KEYS:
            if key in existing and key not in extra:
                extra[key] = existing[key]
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


def _write_retro_active(stage):
    global _retro_active_stage
    _retro_active_stage = stage
    try:
        with open(ACTIVE_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        existing = {}
    stage_times = existing.get("stage_times", {}) if existing.get("item_id") == "__retro__" else {}
    started     = existing.get("started", datetime.now().timestamp()) if existing.get("item_id") == "__retro__" else datetime.now().timestamp()
    stage_times[stage] = datetime.now().timestamp()
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        json.dump({"item_id": "__retro__", "stage": stage, "started": started, "stage_times": stage_times}, f)


# ── Backlog ───────────────────────────────────────────────────────────────────

def load_backlog():
    with open(SDLC_PIPELINE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_backlog(data):
    with open(SDLC_PIPELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_next_item(backlog, sprint_only=False):
    for item in backlog["items"]:
        if item.get("status") == "pending":
            if sprint_only and not item.get("in_sprint"):
                continue
            return item
    return None


# ── App files ─────────────────────────────────────────────────────────────────

def read_app_files():
    with open(INDEX_FILE, encoding="utf-8-sig") as f:
        index_html = f.read()
    with open(VERSION_FILE, encoding="utf-8-sig") as f:
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

def call_agent(idea, story, acceptance_criteria, index_html, version_json, timestamp, retro_context=None, scope_creep_feedback=None, functional_design=None, nfr_requirements=None):
    context_parts = []
    workspace_ctx = load_workspace_context()
    if workspace_ctx:
        context_parts.append(workspace_ctx)
    if functional_design:
        fd = functional_design
        lines = ["FUNCTIONAL DESIGN (pre-approved — follow this plan):"]
        if fd.get("implementation_approach"):
            lines.append(f"Approach: {fd['implementation_approach']}")
        if fd.get("elements_to_add"):
            lines.append("Add: " + "; ".join(fd["elements_to_add"]))
        if fd.get("elements_to_modify"):
            lines.append("Modify: " + "; ".join(fd["elements_to_modify"]))
        if fd.get("existing_elements_touched"):
            lines.append("Existing elements touched: " + ", ".join(fd["existing_elements_touched"]))
        context_parts.append("\n".join(lines))
    if nfr_requirements:
        answers = nfr_requirements.get("answers", {})
        if answers:
            lines = ["NFR REQUIREMENTS (confirmed — apply to your implementation):"]
            for val in answers.values():
                lines.append(f"- {val}")
            context_parts.append("\n".join(lines))
    wisdom = load_wisdom()
    if wisdom:
        context_parts.append("CODING WISDOM:\n" + "\n".join(f"- {b}" for b in wisdom))
    if retro_context:
        context_parts.append("SPRINT WISDOM:\n" + retro_context)
    if scope_creep_feedback:
        context_parts.append(
            "SCOPE CREEP REJECTION — YOUR PREVIOUS PATCHES WERE REJECTED:\n"
            f"{scope_creep_feedback}\n\n"
            "Fix your patches:\n"
            "1. Each 'find' must be ONE LINE ONLY — the single line you are inserting after or modifying.\n"
            "2. Never include any CSS rule or JS block in 'find' that you are not directly changing.\n"
            "3. 'replace' must contain EVERY character from 'find' plus your new addition."
        )
    context_section = ("\n\n" + "\n\n".join(context_parts)) if context_parts else ""

    version_json = strip_changelog_for_prompt(version_json)

    ac_str = "\n".join(f"- {c}" for c in acceptance_criteria) if acceptance_criteria else "(none)"

    prompt = f"""Deploy timestamp: {timestamp}
Live URL: {REPO_URL}
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

    # Extract the LAST code-fenced JSON block (agent may think aloud between multiple blocks)
    blocks = re.findall(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
    if blocks:
        text = blocks[-1].strip()
    elif not text.startswith("{"):
        pass  # fall through to rfind below

    # Parse only the first complete JSON object — raw_decode stops at the end of
    # the first object and ignores any trailing content (prose, second JSON block, etc.)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in agent response")
    decoder = json.JSONDecoder()
    data, _ = decoder.raw_decode(text, start)

    with open(INDEX_FILE, encoding="utf-8-sig") as f:
        content = f.read()

    pre_patch_lf = len(content.replace('\r\n', '\n'))

    # Validate all patches before applying any — catch scope creep before touching the file.
    # Two guards:
    # 1. find block must be small (forces minimal anchors, prevents grabbing large multi-rule blocks)
    # 2. replace must have >= lines as find (prevents deletions within the allowed block)
    _MAX_FIND_LINES = 3
    for patch in data.get("patches", []):
        f_lines = patch["find"].splitlines()
        r_lines = patch["replace"].splitlines()
        if len(f_lines) > _MAX_FIND_LINES:
            raise ValueError(
                f"Scope creep guard: find block is {len(f_lines)} lines (max {_MAX_FIND_LINES}). "
                f"Use a minimal single-line anchor. "
                f"Target: {repr(patch['find'][:80])}"
            )
        if len(r_lines) < len(f_lines):
            net = len(f_lines) - len(r_lines)
            raise ValueError(
                f"Scope creep guard: replace has {net} fewer line(s) than find "
                f"(find={len(f_lines)}, replace={len(r_lines)}). "
                f"Target: {repr(patch['find'][:80])}"
            )

    for patch in data.get("patches", []):
        content = apply_patch(content, patch["find"], patch["replace"])

    # Guard 2: patched file must not be smaller than pre-patch file minus tolerance.
    # Compares against the file as it was before patching (not HEAD) so the check works
    # correctly whether starting from baseline or any other state.
    patched_lf = len(content.replace('\r\n', '\n'))
    if patched_lf < pre_patch_lf - 50:
        raise ValueError(
            f"Scope creep guard: patched file ({patched_lf} chars LF) is "
            f"{pre_patch_lf - patched_lf} chars smaller than pre-patch ({pre_patch_lf} chars LF). "
            f"Patches deleted content outside the story scope."
        )

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
    if not message.content:
        raise ValueError("Empty response from Hermes code review")
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]
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
    if not message.content:
        raise ValueError("Empty response from Hermes AC check")
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]
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


def rollback(snapshot=None):
    if snapshot is not None:
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            f.write(snapshot)
    else:
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


def _sprint_coding_wisdom_bullets(findings):
    """Generate coding wisdom bullets from this sprint's retro findings only. No file I/O."""
    if not findings:
        return []
    new_text = "\n".join(f"[{f['type']}] {f['text']}" for f in findings)
    prompt = (
        "Extract coding directives from these sprint findings. "
        "Output only directives warranted by the findings — up to 6 bullets, ≤12 words each, "
        "plain text, imperative voice, specific to HTML/CSS/JS patching. Start each with •\n\n"
        "Exclude: accessibility/WCAG concerns, sprint process advice.\n\n"
        f"Sprint findings:\n{new_text}"
    )
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return [ln.strip() for ln in msg.content[0].text.strip().splitlines() if ln.strip().startswith("•")]
    except Exception:
        return []


def _sprint_ac_wisdom_bullets(sprint_items):
    """Generate AC wisdom bullets from this sprint's story outcomes only. No file I/O."""
    outcomes = []
    for i in sprint_items:
        if i.get("status") in ("done", "failed", "rejected"):
            entry = {"idea": i.get("idea", "")[:80], "ac": i.get("acceptance_criteria", []), "status": i.get("status")}
            reason = i.get("ac_check_reason") or i.get("code_review_reason") or ""
            if reason and i.get("status") != "done":
                entry["rejected_for"] = reason[:120]
            outcomes.append(entry)
    if not outcomes:
        return []
    prompt = (
        "Extract AC-writing directives from these sprint story outcomes. "
        "Extract principles about WHAT MAKES AC GOOD — specificity, testability, verifiability. "
        "Output only directives warranted by the outcomes — up to 6 bullets, ≤12 words each, "
        "plain text, imperative voice. Start each with •\n\n"
        "Exclude: story-specific implementation details, WCAG/accessibility concerns.\n\n"
        f"Story outcomes:\n{json.dumps(outcomes, indent=2)}"
    )
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return [ln.strip() for ln in msg.content[0].text.strip().splitlines() if ln.strip().startswith("•")]
    except Exception:
        return []


def load_wisdom():
    """Return list of stripped bullet strings from coding_wisdom.json, or empty list."""
    try:
        with open(CODING_WISDOM_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [b.lstrip("•").strip() for b in data.get("bullets", []) if b.strip()]
    except Exception:
        return []


def load_workspace_context():
    """Return a compact workspace context string for injection into the agent prompt, or None."""
    try:
        with open(WORKSPACE_CONTEXT_FILE, encoding="utf-8") as f:
            ws = json.load(f)
        dm = ws.get("data_model", {})
        fields   = ", ".join(dm.get("item_fields", []))
        statuses = " | ".join(dm.get("status_values", []))
        sources  = " | ".join(dm.get("source_values", []))
        pipeline = " → ".join(ws.get("pipeline_stages", []))
        field_types = dm.get("field_types", {})
        complex_types = {k: v for k, v in field_types.items() if v.startswith("Array") or v.startswith("object")}
        lines = [
            "WORKSPACE CONTEXT (from last inception run):",
            f"Data store: sdlc_pipeline.json — item fields: {fields}",
            f"Status values: {statuses}",
            f"Source values: {sources}",
            f"Agent pipeline: {pipeline}",
            "Read data via fetch('/sdlc_pipeline.json') — never localStorage.",
        ]
        if complex_types:
            lines.append("Field types (complex fields — use exact access patterns):")
            for k, v in complex_types.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)
    except Exception:
        return None


def run_retro(processed_items, retro=None):
    """Persist retro to retrospective.json and synthesize wisdom.
    Accepts a pre-generated retro dict to avoid a redundant API call."""
    if not processed_items:
        return
    if retro is None:
        retro = _call_retro_api(processed_items)

    clear_log()
    _write_retro_active('retro')
    log("=== RETROSPECTIVE ===")
    log(f"Retro: {retro.get('summary', '')}")
    log(f"Findings: {len(retro.get('findings', []))} item(s) written to retrospective.json")

    _write_retro_active('sprint_coding_wisdom')
    log("Synthesizing sprint coding wisdom...")
    sprint_coding = _sprint_coding_wisdom_bullets(retro.get("findings", []))
    log(f"Sprint coding wisdom: {len(sprint_coding)} bullet(s)")

    _write_retro_active('sprint_ac_wisdom')
    log("Synthesizing sprint AC wisdom...")
    sprint_ac = _sprint_ac_wisdom_bullets(processed_items)
    log(f"Sprint AC wisdom: {len(sprint_ac)} bullet(s)")

    retro["sprint_coding_wisdom"] = sprint_coding
    retro["sprint_ac_wisdom"]     = sprint_ac

    try:
        with open(RETRO_FILE, encoding="utf-8") as f:
            store = json.load(f)
    except Exception:
        store = {"retros": []}

    store.setdefault("retros", []).insert(0, retro)

    with open(RETRO_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)

    log("=== WISDOM ===")
    _write_retro_active('coding_wisdom')
    synthesize_coding_wisdom(processed_items)
    _write_retro_active('retro_done')


def synthesize_ac_wisdom(sprint_items=None):
    """Update AC-writing directives incrementally from this sprint's outcomes, or bootstrap from history."""
    if _retro_active_stage and _retro_active_stage not in ('retro_done', 'ac_wisdom'):
        _write_retro_active('ac_wisdom')
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


# ── Sprint result (for decoupled retro) ──────────────────────────────────────

def _append_sprint_result(item_id):
    """Append a processed item ID to sprint_result.json."""
    try:
        try:
            with open(SPRINT_RESULT_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"item_ids": []}
        data.setdefault("item_ids", []).append(str(item_id))
        with open(SPRINT_RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_one(sprint_only=False, processed=None, sprint_wisdom=None):
    backlog = load_backlog()
    nfr_requirements = backlog.get("sprint_nfr")
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
        item["retro_context"] = sprint_wisdom

    slow_pause("story")
    write_active(item, "code", tokens_in=tokens_in, tokens_out=tokens_out)
    with open(INDEX_FILE, encoding="utf-8-sig") as _f:
        _index_snapshot = _f.read()

    result = None
    scope_creep_feedback = None
    for _attempt in range(1, 4):  # up to 3 attempts
        if _attempt > 1:
            log(f"Retrying (attempt {_attempt}/3) with scope discipline feedback...")
        write_active(item, "story",
            story=item.get("story", ""),
            acceptance_criteria=item.get("acceptance_criteria", []),
            retro_context=sprint_wisdom)
        log("Calling agent...")
        try:
            response, t_in, t_out = call_agent(
                item.get("idea", item.get("story", "")),
                item.get("story", ""),
                item.get("acceptance_criteria", []),
                index_html, version_json, timestamp,
                retro_context=sprint_wisdom,
                scope_creep_feedback=scope_creep_feedback,
                functional_design=item.get("functional_design"),
                nfr_requirements=nfr_requirements,
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
            break  # patches applied successfully — exit retry loop
        except Exception as e:
            err_str = str(e)
            is_scope_creep = err_str.startswith("Scope creep guard")
            if is_scope_creep and _attempt < 3:
                scope_creep_feedback = err_str
                log(f"Attempt {_attempt} rejected: {err_str}")
                continue
            if is_scope_creep:
                log(f"Rejected (all {_attempt} attempt(s)): {err_str}")
                item["error"] = err_str
            else:
                log(f"Parse error: {e}")
                log(f"Raw response preview: {response[:300]}")
                item["error"] = f"Parse error: {e} | Response preview: {response[:200]}"
            item["status"] = "failed"
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

    slow_pause("code")
    log("Running tests...")
    write_active(item, "test", tokens_in=tokens_in, tokens_out=tokens_out,
        stage_detail="Running test suite…",
        change_summary=result.get("summary", ""))
    passed, stdout, stderr = run_tests()
    log(stdout.strip())
    test_results = parse_test_results(stdout)
    test_pass_count = sum(1 for t in test_results if t["status"] == "pass")
    test_total = len(test_results)

    if not passed:
        log("TESTS FAILED — rolling back")
        if stderr:
            log(stderr.strip())
        rollback(_index_snapshot)
        item["status"] = "failed"
        item["diff"] = diff
        item["test_results"] = test_results
        ad = write_active(item, "failed", failed_at="test", error="Tests failed — see activity stream", tokens_in=tokens_in, tokens_out=tokens_out)
        item["started"] = ad.get("started"); item["stage_times"] = ad.get("stage_times", {})
        item["tokens_in"] = tokens_in; item["tokens_out"] = tokens_out
        save_backlog(backlog)
        return False

    slow_pause("test")
    log("Hermes — code review...")
    write_active(item, "code_review", tokens_in=tokens_in, tokens_out=tokens_out,
        stage_detail=f"Tests: {test_pass_count}/{test_total} passed · Hermes reviewing…",
        test_pass_count=test_pass_count, test_total=test_total)
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
        rollback(_index_snapshot)
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

    slow_pause("code_review")
    log("Hermes — AC check...")
    write_active(item, "ac_check", tokens_in=tokens_in, tokens_out=tokens_out,
        stage_detail="Code review approved · Checking AC…")
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
        rollback(_index_snapshot)
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

    slow_pause("ac_check")
    log("Pushing to GitHub...")
    write_active(item, "deploy", hermes_verdict="approve", tokens_in=tokens_in, tokens_out=tokens_out,
        stage_detail="All checks passed · Deploying…")
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

    ad = write_active(item, "done", hermes_verdict=hermes_verdict, tokens_in=tokens_in, tokens_out=tokens_out,
        stage_detail=result.get("summary", ""))
    item["started"]     = ad.get("started")
    item["stage_times"] = ad.get("stage_times", {})
    item["tokens_in"]   = tokens_in
    item["tokens_out"]  = tokens_out
    log(f"\nDeployed: {timestamp}")
    log(f"Live at : {REPO_URL}")
    save_backlog(backlog)
    return True


def main():
    if "--synthesize" in sys.argv:
        synthesize_coding_wisdom()
        return

    if "--run-retro" in sys.argv:
        # Runs in a clean subprocess after sprint exits — no SSE pipe dependency.
        try:
            with open(SPRINT_RESULT_FILE, encoding="utf-8") as f:
                result = json.load(f)
            item_ids = set(str(x) for x in result.get("item_ids", []))
            if item_ids:
                backlog = load_backlog()
                processed = [i for i in backlog["items"] if str(i["id"]) in item_ids]
                if processed:
                    log("=== RETROSPECTIVE ===")
                    run_retro(processed)
                    log("=== SPRINT COMPLETE ===")
        except Exception as e:
            log(f"Retro error: {e}")
        finally:
            try:
                os.remove(SPRINT_RESULT_FILE)
            except Exception:
                pass
        return

    sprint_mode = "--sprint" in sys.argv
    loop_mode = "--loop" in sys.argv
    print("\nAI Scrum Agent")
    print(f"Mode: {'sprint' if sprint_mode else 'loop' if loop_mode else 'single story'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if sprint_mode or loop_mode:
        # Clear any stale sprint result from a previous run
        try:
            os.remove(SPRINT_RESULT_FILE)
        except Exception:
            pass

        processed = []
        sprint_wisdom = None  # story 1: CODING WISDOM only; SPRINT WISDOM loads after first item
        while True:
            prev_len = len(processed)
            run_one(sprint_only=sprint_mode, processed=processed, sprint_wisdom=sprint_wisdom)
            item_was_processed = len(processed) > prev_len
            if item_was_processed:
                _append_sprint_result(processed[-1]["id"])
                backlog = load_backlog()
                more_items = get_next_item(backlog, sprint_only=sprint_mode) is not None
                if more_items:
                    log("\nGenerating sprint wisdom...")
                    try:
                        sprint_wisdom, _ = generate_sprint_wisdom(processed)
                        if sprint_wisdom:
                            backlog = load_backlog()
                            last_id = processed[-1]["id"]
                            for bi in backlog["items"]:
                                if bi["id"] == last_id:
                                    bi["sprint_wisdom"] = sprint_wisdom
                                    break
                            save_backlog(backlog)
                    except Exception as e:
                        log(f"Sprint wisdom error: {e}")
                        sprint_wisdom = None
                else:
                    break
            if not item_was_processed:
                break

        # Run retro inline — eliminates subprocess startup delay for the last-story→retro transition.
        try:
            with open(SPRINT_RESULT_FILE, encoding="utf-8") as f:
                result = json.load(f)
            item_ids = set(str(x) for x in result.get("item_ids", []))
            if item_ids:
                backlog = load_backlog()
                sprint_items = [i for i in backlog["items"] if str(i["id"]) in item_ids]
                if sprint_items:
                    run_retro(sprint_items)
                    log("=== SPRINT COMPLETE ===")
        except Exception as e:
            log(f"Retro error: {e}")
        finally:
            try:
                os.remove(SPRINT_RESULT_FILE)
            except Exception:
                pass
    else:
        run_one(sprint_only=True)


if __name__ == "__main__":
    main()
