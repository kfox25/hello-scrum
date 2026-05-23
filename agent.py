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
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

BACKLOG_FILE = "backlog.json"
ACTIVE_FILE  = "active.json"
LOG_FILE     = "agent_log.json"
INDEX_FILE   = "index.html"
VERSION_FILE = "version.json"
TEST_SCRIPT  = "test.py"
REPO_URL     = "https://kfox25.github.io/hello-scrum"

_log_lines = []

def log(msg=""):
    print(msg)
    _log_lines.append(str(msg))
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(_log_lines, f)
    except Exception:
        pass

def log_lines(lines):
    for line in lines:
        print(line)
    _log_lines.extend(lines)
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(_log_lines, f)
    except Exception:
        pass

def clear_log():
    global _log_lines
    _log_lines = []
    try:
        with open(LOG_FILE, "w") as f:
            json.dump([], f)
    except Exception:
        pass

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are an AI developer working on the hello-scrum web app.

Your job:
1. Read the raw backlog idea
2. Write a user story with acceptance criteria
3. Implement the change in index.html and version.json

Rules:
- Only modify index.html and version.json
- Bump the patch version (e.g. 0.1.0 -> 0.1.1)
- Set the deployed timestamp to exactly the value provided — do not change it
- Add a changelog entry as the LAST item in the changelog array with exactly these fields: {"version": "<new version>", "date": "<YYYY-MM-DD>", "change": "<description>"}
- Keep the page structure intact: h1 title, version badge, meta lines, and the Audit button in the top right corner
- Changes must be clearly visible on the page
- Keep the page clean and minimal

Respond with ONLY valid JSON — no markdown, no code blocks, no extra text:
{
  "story": "As a user, I want...",
  "acceptance_criteria": ["criterion 1", "criterion 2"],
  "index_html": "<full updated index.html content>",
  "version_json": { <full updated version.json object> },
  "summary": "Short commit message describing what changed"
}"""

HERMES_SYSTEM_PROMPT = """You are Hermes, a QA reviewer for the hello-scrum web app.

Review the worker agent's implementation and decide if it genuinely delivers what was requested.

Respond with ONLY valid JSON — no markdown, no extra text:
{"verdict": "approve", "reason": "one sentence"}
or
{"verdict": "reject", "reason": "one sentence explaining what is wrong or missing"}

Approve if the diff clearly implements the idea and tests pass.
Reject if the implementation is unrelated to the idea, clearly wrong, or missing the point."""


# ── Active status ─────────────────────────────────────────────────────────────

def write_active(item, stage, **extra):
    data = {"item_id": item["id"], "idea": item["idea"], "stage": stage}
    data.update(extra)
    with open(ACTIVE_FILE, "w") as f:
        json.dump(data, f)


def clear_active():
    with open(ACTIVE_FILE, "w") as f:
        json.dump({"item_id": None, "stage": None}, f)


# ── Backlog ───────────────────────────────────────────────────────────────────

def load_backlog():
    with open(BACKLOG_FILE) as f:
        return json.load(f)


def save_backlog(data):
    with open(BACKLOG_FILE, "w") as f:
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
    with open(INDEX_FILE) as f:
        index_html = f.read()
    with open(VERSION_FILE) as f:
        version_json = f.read()
    return index_html, version_json


def get_ct_timestamp():
    ct = datetime.now(ZoneInfo("America/Chicago"))
    return ct.strftime("%Y-%m-%d %H:%M:%S CT")


# ── Worker agent ──────────────────────────────────────────────────────────────

def call_agent(idea, index_html, version_json, timestamp):
    prompt = f"""Deploy timestamp to use (exact): {timestamp}

Raw backlog idea: {idea}

Current index.html:
{index_html}

Current version.json:
{version_json}

Implement this idea. Return JSON only."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def apply_changes(response_text):
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])

    data = json.loads(text)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(data["index_html"])

    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data["version_json"], f, indent=2)

    return data


# ── Hermes reviewer ───────────────────────────────────────────────────────────

def call_hermes(idea, story, acceptance_criteria, diff, test_results):
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
        system=HERMES_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    return json.loads(text)


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
    subprocess.run(["git", "add", INDEX_FILE, VERSION_FILE, BACKLOG_FILE], check=True)
    subprocess.run(["git", "commit", "-m", summary], check=True)
    subprocess.run(["git", "push"], check=True)


def rollback():
    subprocess.run(["git", "checkout", "--", INDEX_FILE, VERSION_FILE])


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_one(sprint_only=False):
    backlog = load_backlog()
    item = get_next_item(backlog, sprint_only=sprint_only)

    if not item:
        print("No items to process.")
        return False

    clear_log()
    log(f"\n{'=' * 50}")
    log(f"  ITEM [{item['id']}]: {item['idea']}")
    log(f"{'=' * 50}")

    write_active(item, "pull")

    index_html, version_json = read_app_files()
    timestamp = get_ct_timestamp()

    log(f"Timestamp : {timestamp}")
    log("Calling agent...")
    write_active(item, "story")

    try:
        response = call_agent(item["idea"], index_html, version_json, timestamp)
    except Exception as e:
        log(f"Agent error: {e}")
        item["status"] = "failed"
        item["error"] = f"Agent error: {e}"
        save_backlog(backlog)
        clear_active()
        return False

    log("Applying changes...")
    write_active(item, "code")
    try:
        result = apply_changes(response)
    except Exception as e:
        log(f"Parse error: {e}")
        log(f"Raw response preview: {response[:300]}")
        item["status"] = "failed"
        item["error"] = f"Parse error: {e} | Response preview: {response[:200]}"
        save_backlog(backlog)
        clear_active()
        return False

    log(f"Story   : {result['story']}")
    log(f"Summary : {result['summary']}")

    diff = capture_diff()
    if diff:
        log_lines([l for l in diff.splitlines() if l])

    log("Running tests...")
    write_active(item, "test")
    passed, stdout, stderr = run_tests()
    log(stdout.strip())
    test_results = parse_test_results(stdout)

    if not passed:
        log("TESTS FAILED — rolling back")
        if stderr:
            log(stderr.strip())
        rollback()
        item["status"] = "failed"
        item["story"] = result.get("story", "")
        item["acceptance_criteria"] = result.get("acceptance_criteria", [])
        item["diff"] = diff
        item["test_results"] = test_results
        save_backlog(backlog)
        clear_active()
        return False

    log("Hermes reviewing...")
    write_active(item, "review")
    try:
        verdict = call_hermes(
            item["idea"],
            result["story"],
            result.get("acceptance_criteria", []),
            diff,
            test_results,
        )
        hermes_verdict = verdict.get("verdict", "approve")
        hermes_reason = verdict.get("reason", "")
    except Exception as e:
        log(f"Hermes error (defaulting to approve): {e}")
        hermes_verdict = "approve"
        hermes_reason = "Hermes review failed — defaulting to approve"

    log(f"Hermes: {hermes_verdict.upper()} — {hermes_reason}")

    if hermes_verdict == "reject":
        rollback()
        item["status"] = "failed"
        item["story"] = result.get("story", "")
        item["acceptance_criteria"] = result.get("acceptance_criteria", [])
        item["diff"] = diff
        item["test_results"] = test_results
        item["hermes_verdict"] = hermes_verdict
        item["hermes_reason"] = hermes_reason
        save_backlog(backlog)
        write_active(item, "rejected", hermes_verdict="reject", hermes_reason=hermes_reason)
        return False

    log("Pushing to GitHub...")
    write_active(item, "deploy", hermes_verdict="approve", hermes_reason=hermes_reason)
    item["status"] = "done"
    item["story"] = result["story"]
    item["acceptance_criteria"] = result.get("acceptance_criteria", [])
    item["summary"] = result["summary"]
    item["diff"] = diff
    item["test_results"] = test_results
    item["deployed"] = timestamp
    item["hermes_verdict"] = hermes_verdict
    item["hermes_reason"] = hermes_reason
    save_backlog(backlog)

    try:
        git_push(result["summary"])
    except Exception as e:
        log(f"Push failed: {e}")
        rollback()
        item["status"] = "failed"
        save_backlog(backlog)
        clear_active()
        return False

    clear_active()
    log(f"\nDeployed: {timestamp}")
    log(f"Live at : {REPO_URL}")
    return True


def main():
    sprint_mode = "--sprint" in sys.argv
    loop_mode = "--loop" in sys.argv
    print("\nAI Scrum Agent")
    print(f"Mode: {'sprint' if sprint_mode else 'loop' if loop_mode else 'single story'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if sprint_mode or loop_mode:
        while run_one(sprint_only=sprint_mode):
            pass
    else:
        run_one()


if __name__ == "__main__":
    main()
