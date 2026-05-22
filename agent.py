"""
AI Scrum Agent
Pulls the top backlog idea, implements it, tests it, and deploys it.

Usage:
  python agent.py          # run one story
  python agent.py --loop   # run until backlog is empty
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

BACKLOG_FILE = "backlog.json"
INDEX_FILE = "index.html"
VERSION_FILE = "version.json"
TEST_SCRIPT = "test.py"
REPO_URL = "https://kfox25.github.io/hello-scrum"

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


# ── Backlog ───────────────────────────────────────────────────────────────────

def load_backlog():
    with open(BACKLOG_FILE) as f:
        return json.load(f)


def save_backlog(data):
    with open(BACKLOG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_next_item(backlog):
    for item in backlog["items"]:
        if item["status"] == "pending":
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


# ── Agent ─────────────────────────────────────────────────────────────────────

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
        max_tokens=4096,
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

def run_one():
    backlog = load_backlog()
    item = get_next_item(backlog)

    if not item:
        print("Backlog empty — nothing to do.")
        return False

    print(f"\n{'=' * 50}")
    print(f"  ITEM [{item['id']}]: {item['idea']}")
    print(f"{'=' * 50}")

    index_html, version_json = read_app_files()
    timestamp = get_ct_timestamp()

    print(f"Timestamp : {timestamp}")
    print("Calling agent...")

    try:
        response = call_agent(item["idea"], index_html, version_json, timestamp)
    except Exception as e:
        print(f"Agent error: {e}")
        item["status"] = "failed"
        save_backlog(backlog)
        return False

    print("Applying changes...")
    try:
        result = apply_changes(response)
    except Exception as e:
        print(f"Parse error: {e}")
        print(f"Raw response preview: {response[:300]}")
        item["status"] = "failed"
        save_backlog(backlog)
        return False

    print(f"Story   : {result['story']}")
    print(f"Summary : {result['summary']}")

    diff = capture_diff()

    print("Running tests...")
    passed, stdout, stderr = run_tests()
    print(stdout.strip())
    test_results = parse_test_results(stdout)

    if not passed:
        print("TESTS FAILED — rolling back")
        if stderr:
            print(stderr.strip())
        rollback()
        item["status"] = "failed"
        item["story"] = result.get("story", "")
        item["acceptance_criteria"] = result.get("acceptance_criteria", [])
        item["diff"] = diff
        item["test_results"] = test_results
        save_backlog(backlog)
        return False

    item["status"] = "done"
    item["story"] = result["story"]
    item["acceptance_criteria"] = result.get("acceptance_criteria", [])
    item["summary"] = result["summary"]
    item["diff"] = diff
    item["test_results"] = test_results
    item["deployed"] = timestamp
    save_backlog(backlog)  # save BEFORE git push so backlog.json is included

    print("Pushing to GitHub...")
    try:
        git_push(result["summary"])
    except Exception as e:
        print(f"Push failed: {e}")
        rollback()
        item["status"] = "failed"
        save_backlog(backlog)
        return False

    print(f"\nDeployed: {timestamp}")
    print(f"Live at : {REPO_URL}")
    return True


def main():
    loop_mode = "--loop" in sys.argv
    print("\nAI Scrum Agent")
    print(f"Mode: {'loop' if loop_mode else 'single story'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if loop_mode:
        while run_one():
            pass
    else:
        run_one()


if __name__ == "__main__":
    main()
