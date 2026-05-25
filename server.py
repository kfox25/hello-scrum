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


@app.route("/system_wisdom.json")
def system_wisdom_json():
    path = os.path.join(BASE, "system_wisdom.json")
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
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return jsonify({"ok": True})


@app.route("/story_wisdom.json")
def story_wisdom_json():
    path = os.path.join(BASE, "story_wisdom.json")
    if os.path.exists(path):
        return send_file(path)
    return jsonify({"bullets": [], "synthesized_at": None, "item_count": 0})


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

        # Load wisdom layers for injection
        story_wisdom_bullets = []
        system_wisdom_bullets = []
        try:
            with open(os.path.join(BASE, "story_wisdom.json")) as f:
                sw = json.load(f)
            story_wisdom_bullets = [b.lstrip("•").strip() for b in sw.get("bullets", []) if b.strip()]
        except Exception:
            pass
        try:
            with open(os.path.join(BASE, "system_wisdom.json")) as f:
                sw = json.load(f)
            system_wisdom_bullets = [b.lstrip("•").strip() for b in sw.get("bullets", []) if b.strip()]
        except Exception:
            pass

        wisdom_parts = []
        if story_wisdom_bullets:
            wisdom_parts.append("STORY RULES:\n" + "\n".join(f"- {b}" for b in story_wisdom_bullets))
        if system_wisdom_bullets:
            wisdom_parts.append("CODING RULES:\n" + "\n".join(f"- {b}" for b in system_wisdom_bullets))
        wisdom_section = ("\n\n" + "\n\n".join(wisdom_parts)) if wisdom_parts else ""

        system_prompt = (
            "You are a scrum story writer. Given a raw idea, write a user story and acceptance criteria.\n"
            "Respond with JSON only (no markdown):\n"
            '{"story": "As a <role>, I want <goal> so that <benefit>.", "acceptance_criteria": ["<criterion 1>", "<criterion 2>", "<criterion 3>"]}\n'
            "Keep the story concise. Write 3-4 acceptance criteria as short, testable statements."
        )

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": idea + wisdom_section}],
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
