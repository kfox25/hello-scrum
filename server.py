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
            matches = [
                i for i in backlog.get("items", [])
                if any(kw in (i.get("idea") or i.get("title") or "").lower() for kw in keywords)
            ]
            if not matches:
                return jsonify({"reply": f"No stories found matching <em>{query_str}</em>.", "stories": None})
            lines = []
            for item in matches:
                title = item.get("idea") or item.get("title") or "(untitled)"
                status = item.get("status", "pending")
                in_sprint = item.get("in_sprint", False)
                if status == "done":
                    label = "✓ completed"
                    color = "#00ff99"
                elif status == "failed":
                    label = "✗ failed"
                    color = "#ff4444"
                elif status == "rejected":
                    label = "✗ rejected"
                    color = "#ff4444"
                elif in_sprint:
                    label = "⟳ in sprint"
                    color = "#ffcc00"
                else:
                    label = "· in backlog"
                    color = "#888"
                lines.append(f'<span style="color:{color}">{label}</span> — {title}')
            return jsonify({"reply": "<br>".join(lines), "stories": None})

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
        }
        backlog.setdefault("items", []).insert(0, new_item)
        with open(BACKLOG_FILE, "w") as f:
            json.dump(backlog, f, indent=2)
        return jsonify({"reply": f"Added to top of backlog: <em>{story}</em>"})

    except Exception as e:
        return jsonify({"reply": f"Server error: {e}"}), 500


@app.route("/retrospective.json")
def retrospective_json():
    path = os.path.join(BASE, "retrospective.json")
    if os.path.exists(path):
        return send_file(path)
    return jsonify({"retros": []})


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

    def generate():
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
                yield f"data: {json.dumps(line.rstrip())}\n\n"
            proc.wait()
        finally:
            agent_running = False
            yield f"data: {json.dumps('__done__')}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    print("Sprint Board running at http://localhost:5000")
    app.run(debug=False, port=5000, threaded=True)
