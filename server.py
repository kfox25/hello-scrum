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
import subprocess
import threading
import time

import anthropic

from flask import Flask, Response, jsonify, request, send_file

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
BACKLOG_FILE = os.path.join(BASE, "backlog.json")
ACTIVE_FILE  = os.path.join(BASE, "active.json")

agent_running = False
agent_lock = threading.Lock()
AGENT_LOG_FILE = os.path.join(BASE, "agent_log.json")

# On startup, clear only mid-sprint states so a restarted server doesn't show
# a stale pulsing dot — but preserve done/failed/rejected so the panel persists.
_KEEP_STAGES = {"done", "failed", "rejected"}
try:
    with open(ACTIVE_FILE) as _f:
        _s = json.load(_f).get("stage")
    if _s not in _KEEP_STAGES:
        with open(ACTIVE_FILE, "w") as _f:
            json.dump({"item_id": None, "stage": None}, _f)
except Exception:
    with open(ACTIVE_FILE, "w") as _f:
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


@app.route("/backlog.json")
def backlog_json():
    return send_file(BACKLOG_FILE)


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
            max_tokens=400,
            system="""You are a scrum assistant for a sprint board.

Classify the message into exactly one of three types and respond with JSON only (no markdown):

1. REQUIREMENT — describes a feature, user need, or problem to solve:
   {"type": "requirement", "stories": ["<title 1>", "<title 2>", "<title 3>"], "reply": "<one sentence intro>"}
   Generate 3 distinct backlog titles varying in scope or approach. Keep each short and actionable.

2. INQUIRY — asks about the status or existence of a specific story or feature:
   {"type": "inquiry", "query": "<2-4 keyword search terms>", "reply": null}

3. OTHER — greetings, chitchat, commands, anything else:
   {"type": "other", "reply": "<brief helpful response>"}""",
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

        msg_type = result.get("type")

        if msg_type == "requirement" and result.get("stories"):
            return jsonify({"reply": result.get("reply", "Here are 3 story options:"), "stories": result["stories"]})

        if msg_type == "inquiry" and result.get("query"):
            with open(BACKLOG_FILE) as f:
                backlog = json.load(f)
            raw_query = result["query"]
            if isinstance(raw_query, list):
                keywords = [str(k).lower() for k in raw_query]
                query_str = " ".join(keywords)
            else:
                query_str = str(raw_query)
                keywords = query_str.lower().split()
            stop_words = {"a","an","the","is","are","was","were","has","have","been","be","to","of","in","on","at","for","with","this","that","it","its","by","as","from","and","or","but","not","what","whats","status","story","did","does","get","about"}
            search_terms = [kw for kw in keywords if kw not in stop_words] or keywords
            matches = [
                i for i in backlog.get("items", [])
                if all(kw in (i.get("idea") or i.get("title") or "").lower() for kw in search_terms)
            ]
            if not matches:
                return jsonify({"reply": f"No stories found matching <em>{query_str}</em>.", "stories": None})
            lines = []
            for item in matches:
                title = item.get("idea") or item.get("title") or "(untitled)"
                status = item.get("status", "pending")
                in_sprint = item.get("in_sprint", False)

                if status == "done":
                    parts = [f'<span style="color:#00ff99">✓ completed</span> — <strong>{title}</strong>']
                    if item.get("summary"):
                        parts.append(f'<span style="color:#aaa">{item["summary"]}</span>')
                    if item.get("story"):
                        parts.append(f'<span style="color:#666;font-style:italic">{item["story"]}</span>')
                    if item.get("acceptance_criteria"):
                        criteria = "".join(f'<br>&nbsp;&nbsp;· {c}' for c in item["acceptance_criteria"])
                        parts.append(f'<span style="color:#555">Acceptance criteria:{criteria}</span>')
                    verdict = item.get("hermes_verdict", "")
                    hermes_color = "#00ff99" if verdict == "approve" else "#ff4444"
                    if verdict:
                        parts.append(f'<span style="color:{hermes_color}">Hermes: {verdict}</span>'
                                     + (f' — <span style="color:#777">{item["hermes_reason"]}</span>' if item.get("hermes_reason") else ""))
                    if item.get("test_results"):
                        passed = sum(1 for t in item["test_results"] if t.get("status") == "pass")
                        total  = len(item["test_results"])
                        parts.append(f'<span style="color:#555">Tests: {passed}/{total} passed</span>')
                    if item.get("deployed"):
                        parts.append(f'<span style="color:#444">Deployed: {item["deployed"]}</span>')
                    tok_in  = item.get("tokens_in", 0)
                    tok_out = item.get("tokens_out", 0)
                    if tok_in or tok_out:
                        parts.append(f'<span style="color:#333">Tokens: {tok_in} in / {tok_out} out</span>')
                    lines.append("<br>".join(parts))

                elif status in ("failed", "rejected"):
                    color = "#ff4444"
                    label = "✗ " + status
                    lines.append(f'<span style="color:{color}">{label}</span> — {title}')
                elif in_sprint:
                    lines.append(f'<span style="color:#ffcc00">⟳ in sprint</span> — {title}')
                else:
                    lines.append(f'<span style="color:#888">· in backlog</span> — {title}')

            return jsonify({"reply": "<br><br>".join(lines), "stories": None})

        return jsonify({"reply": result.get("reply", ""), "stories": None})

    except Exception as e:
        return jsonify({"reply": f"Server error: {e}", "stories": None}), 500


@app.route("/messenger/choose", methods=["POST"])
def messenger_choose():
    try:
        data = request.get_json()
        story = (data or {}).get("story", "").strip()
        if not story:
            return jsonify({"reply": "No story provided."})

        with open(BACKLOG_FILE) as f:
            backlog = json.load(f)
        new_item = {
            "id": str(int(time.time() * 1000)),
            "idea": story,
            "status": "pending",
            "in_sprint": False,
            "opportunity": True,
        }
        backlog.setdefault("items", []).insert(0, new_item)
        with open(BACKLOG_FILE, "w") as f:
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


@app.route("/retro/synthesize", methods=["POST"])
def retro_synthesize():
    path = os.path.join(BASE, "retrospective.json")
    if not os.path.exists(path):
        return jsonify({"bullets": []})
    with open(path) as f:
        data = json.load(f)
    retros = data.get("retros", [])
    if not retros:
        return jsonify({"bullets": []})

    seen = set()
    findings = []
    for r in retros:
        for fnd in r.get("findings", []):
            key = f"{fnd['type']}:{fnd['text']}"
            if key not in seen:
                seen.add(key)
                findings.append(f"[{fnd['type']}] {fnd['text']}")

    if not findings:
        return jsonify({"bullets": []})

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": (
            "You are distilling sprint retrospective findings into a concise injection prompt "
            "for an AI coding agent.\n\n"
            "The agent (Claude Sonnet) implements user stories as patches to an HTML/CSS/JS app. "
            "A reviewer (Claude Haiku) checks each change for code quality and AC compliance. "
            "Rejection triggers automatic rollback.\n\n"
            "Sprint findings:\n" + "\n".join(findings) + "\n\n"
            "Write 5-8 tight, actionable bullet points the agent should follow to maximize story "
            "success rate. Focus on patterns that prevent failures or reinforce what works. "
            "Each bullet must be concrete and specific — something the agent can directly apply "
            "when writing HTML/CSS/JS. Start each line with •"
        )}]
    )
    text = resp.content[0].text.strip()
    bullets = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("•")]
    return jsonify({"bullets": bullets})


@app.route("/active/clear", methods=["POST"])
def clear_active():
    with open(ACTIVE_FILE, "w") as f:
        json.dump({"item_id": None, "stage": None}, f)
    return jsonify({"ok": True})


@app.route("/backlog", methods=["GET"])
def get_backlog():
    with open(BACKLOG_FILE) as f:
        return jsonify(json.load(f))


@app.route("/backlog", methods=["POST"])
def save_backlog():
    data = request.get_json()
    with open(BACKLOG_FILE, "w") as f:
        json.dump(data, f, indent=2)
    return jsonify({"ok": True})


@app.route("/backlog/elaborate", methods=["POST"])
def elaborate_story():
    try:
        data = request.get_json()
        idea = (data or {}).get("idea", "").strip()
        if not idea:
            return jsonify({"error": "No idea provided"}), 400

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system="""You are a scrum story writer. Given a raw idea, write a user story and acceptance criteria.
Respond with JSON only (no markdown):
{"story": "As a <role>, I want <goal> so that <benefit>.", "acceptance_criteria": ["<criterion 1>", "<criterion 2>", "<criterion 3>"]}
Keep the story concise. Write 3-4 acceptance criteria as short, testable statements.""",
            messages=[{"role": "user", "content": idea}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.rsplit("```", 1)[0].strip()
        result = json.loads(text)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/agent-log")
def get_agent_log():
    try:
        with open(AGENT_LOG_FILE) as f:
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
            with open(AGENT_LOG_FILE, "w") as f:
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
            line_queue.put(None)  # sentinel — subprocess finished

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
