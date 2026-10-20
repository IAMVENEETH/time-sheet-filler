"""
Local web UI for the HRStop timesheet filler.

    python3 app.py          # opens http://127.0.0.1:8765

Write rough notes and let Gemini draft the entries, or paste entries (JSON or
the plain-text format). Preview, dry run, then save as drafts. It only ever
runs fill_timesheet.py, which never clicks "Submit for Approval".

Everything personal lives in ~/.timesheet-filler/ (see config.py). The server
only listens on 127.0.0.1, so nobody else on the network can reach it.
"""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime

from flask import Flask, abort, jsonify, request, send_from_directory

import ai
import config
from parse_updates import ParseError, parse

HERE = config.HERE
PORT = int(os.environ.get("TIMESHEET_PORT", 8765))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

app = Flask(__name__, static_folder=str(HERE / "static"), static_url_path="/static")

# One job at a time - there's one browser session and one HRStop login.
_lock = threading.Lock()
_job = {"kind": None, "status": "idle", "log": [], "started": None,
        "returncode": None, "dates": [], "save": False, "proc": None}


@app.before_request
def local_only():
    # Blocks DNS-rebinding and other websites posting to this local server.
    if request.host not in ALLOWED_HOSTS:
        abort(403)
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] not in ALLOWED_HOSTS:
            abort(403)
        if not request.is_json:
            abort(415)


def _env():
    return {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}


def _public_job():
    j = {k: v for k, v in _job.items() if k != "proc"}
    j["session_expired"] = any("Session expired" in line for line in _job["log"])
    if _job["dates"] and _job["status"] != "running":
        prefix = "saved" if _job["save"] else "preview"
        j["screenshots"] = []
        for d in _job["dates"]:
            f = config.SHOTS_DIR / f"{prefix}_{d}.png"
            if f.exists() and f.stat().st_mtime >= (_job["started"] or 0):
                j["screenshots"].append({"date": d, "file": f.name})
    return j


def _pump(proc):
    for line in proc.stdout:
        _job["log"].append(line.rstrip("\n"))
    proc.wait()
    with _lock:
        _job["returncode"] = proc.returncode
        _job["status"] = "done" if proc.returncode == 0 else "failed"
        _job["proc"] = None


def _start(kind, cmd, dates=(), save=False, stdin=False):
    with _lock:
        if _job["status"] == "running":
            return False
        proc = subprocess.Popen(
            cmd, cwd=HERE, text=True, encoding="utf-8", errors="replace", bufsize=1,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL, env=_env(),
        )
        _job.update(kind=kind, status="running", log=[], started=time.time(),
                    returncode=None, dates=list(dates), save=save, proc=proc)
    threading.Thread(target=_pump, args=(proc,), daemon=True).start()
    return True


def _busy():
    return jsonify(ok=False, error="Another run is still in progress."), 409


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html", max_age=0)


@app.get("/shots/<name>")
def shots(name):
    if not re.fullmatch(r"(preview|saved)_\d{8}\.png", name):
        abort(404)
    return send_from_directory(config.SHOTS_DIR, name, max_age=0)


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------
def _public_settings(cfg):
    key = cfg.get("gemini_api_key") or ""
    out = {k: v for k, v in cfg.items() if k != "gemini_api_key"}
    out["has_key"] = bool(key)
    out["key_hint"] = f"…{key[-4:]}" if len(key) > 8 else ""
    out["default_rules"] = config.DEFAULT_RULES
    out["data_dir"] = str(config.DATA_DIR)
    return out


@app.get("/api/settings")
def get_settings():
    return jsonify(_public_settings(config.load()))


@app.post("/api/settings")
def post_settings():
    body = request.get_json()
    updates = {k: body[k] for k in ("name", "hrstop_url", "project", "gemini_model", "rules")
               if isinstance(body.get(k), str)}
    if isinstance(body.get("gemini_api_key"), str) and body["gemini_api_key"].strip():
        updates["gemini_api_key"] = body["gemini_api_key"].strip()
    if body.get("clear_key"):
        updates["gemini_api_key"] = ""
    if "target_hours" in body:
        try:
            hours = float(body["target_hours"])
            if not 0 < hours <= 24:
                raise ValueError
            updates["target_hours"] = hours
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Target hours must be between 0 and 24."), 400
    if "hrstop_url" in updates:
        url = updates["hrstop_url"].strip().rstrip("/")
        if not re.fullmatch(r"https://[\w.-]+(:\d+)?", url):
            return jsonify(ok=False, error="HRStop URL should look like https://yourcompany.hrstop.com"), 400
        updates["hrstop_url"] = url
    return jsonify(ok=True, settings=_public_settings(config.save(updates)))


@app.post("/api/models")
def api_models():
    key = (request.get_json().get("key") or "").strip() or config.load().get("gemini_api_key")
    try:
        models = ai.list_models(key)
    except ai.AIError as e:
        return jsonify(ok=False, error=str(e)), 400
    if not models:
        return jsonify(ok=False, error="This key has no Gemini text models available."), 400
    return jsonify(ok=True, models=models)


@app.post("/api/projects")
def api_projects():
    if _job["status"] == "running":
        return _busy()
    try:
        out = subprocess.run(
            [sys.executable, "fill_timesheet.py", "--list-projects", "--headless"],
            cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env=_env(),
        )
    except subprocess.TimeoutExpired:
        return jsonify(ok=False, error="HRStop took too long to load. Try again."), 504
    text = out.stdout + out.stderr
    m = re.search(r"^PROJECTS_JSON (.*)$", text, re.M)
    if m:
        return jsonify(ok=True, projects=json.loads(m.group(1)))
    if "Session expired" in text:
        return jsonify(ok=False, error="Log in to HRStop first (button at the top).",
                       session_expired=True), 400
    return jsonify(ok=False, error="Couldn't read projects from HRStop:\n" + text[-800:]), 500


# --------------------------------------------------------------------------
# generate / parse / run
# --------------------------------------------------------------------------
@app.post("/api/generate")
def api_generate():
    body = request.get_json()
    try:
        dates = sorted({datetime.strptime(d, "%Y-%m-%d").date() for d in body.get("dates", [])})
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Bad date."), 400
    cfg = config.load()
    try:
        text, warnings = ai.generate(cfg, dates, body.get("notes") or "", config.target_minutes(cfg))
    except ai.AIError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, text=text, warnings=warnings)


@app.post("/api/parse")
def api_parse():
    try:
        _entries, warnings, summary = parse(request.get_json().get("text", ""))
    except ParseError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, warnings=warnings, **summary)


@app.post("/api/run")
def api_run():
    body = request.get_json()
    if not config.load().get("project"):
        return jsonify(ok=False, error="Choose your HRStop project in Settings first."), 400
    try:
        entries, _w, _s = parse(body.get("text", ""))
    except ParseError as e:
        return jsonify(ok=False, error=str(e)), 400

    wanted = body.get("dates") or list(entries)
    entries = {d: entries[d] for d in wanted if d in entries}
    if not entries:
        return jsonify(ok=False, error="No days selected."), 400
    for rows in entries.values():
        for r in rows:
            r.pop("site_category", None)

    config.ensure_dirs()
    path = config.RUNS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    save = bool(body.get("save"))
    cmd = [sys.executable, "fill_timesheet.py", "--entries", str(path)]
    if save:
        cmd.append("--save")
    if body.get("headless"):
        cmd.append("--headless")

    if not _start("save" if save else "dry-run", cmd, dates=sorted(entries), save=save):
        return _busy()
    return jsonify(ok=True)


@app.post("/api/login")
def api_login():
    if not _start("login", [sys.executable, "save_login.py"], stdin=True):
        return _busy()
    return jsonify(ok=True)


@app.post("/api/login/done")
def api_login_done():
    proc = _job["proc"]
    if _job["kind"] != "login" or proc is None:
        return jsonify(ok=False, error="No login window is open."), 400
    proc.stdin.write("\n")   # save_login.py waits for Enter, then saves the session
    proc.stdin.flush()
    return jsonify(ok=True)


@app.post("/api/stop")
def api_stop():
    proc = _job["proc"]
    if proc is not None:
        proc.terminate()
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    cfg = config.load()
    auth = config.AUTH_FILE
    return jsonify(
        job=_public_job(),
        login_saved_at=auth.stat().st_mtime if auth.exists() else None,
        setup={"has_key": bool(cfg.get("gemini_api_key")), "project": cfg.get("project"),
               "target_minutes": config.target_minutes(cfg)},
    )


# --------------------------------------------------------------------------
def _port_in_use():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    open_browser = "--no-browser" not in sys.argv
    if _port_in_use():
        print(f"Already running on {url}")
        if open_browser:
            webbrowser.open(url)
        sys.exit(0)
    config.ensure_dirs()
    print(f"Timesheet Filler on {url}  (close this window or press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
