"""
FastAPI web dashboard — live log SSE, task runner, recordings viewer.
"""
import asyncio
import json
import os
import queue
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from computer_use import config, driver
from computer_use.logger import log, subscribe, unsubscribe
from computer_use.tasks import task_calculator, task_vscode, task_browser_game, task_notepad, task_email_draft, task_multiapp

# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR    = BASE_DIR / "static"
RECORDINGS    = Path(__file__).parent.parent / "recordings"

app = FastAPI(title="Desktop Agent Dashboard", version="1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Active task state
_task_state: dict = {
    "running": False,
    "task":    "",
    "status":  "idle",
    "result":  None,
}
_task_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Pages
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request":        request,
        "providers":      config.PROVIDER_ORDER,
        "gemini_count":   len(config.GEMINI_KEYS),
        "dashboard_port": config.DASHBOARD_PORT,
    })


# ─────────────────────────────────────────────────────────────────────────────
# API — status
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    daemon_ok = False
    try:
        import shutil
        daemon_ok = bool(shutil.which("cua-driver"))
    except Exception:
        pass

    return {
        "daemon":    daemon_ok,
        "providers": config.PROVIDER_ORDER,
        "gemini_keys": len(config.GEMINI_KEYS),
        "task":      _task_state.copy(),
    }


@app.get("/api/providers")
async def api_providers():
    providers = []
    for name in ["gemini", "groq", "cerebras", "nvidia", "github", "openrouter", "openai"]:
        active = name in config.PROVIDER_ORDER
        paid   = name == "openai"
        providers.append({
            "name":   name,
            "active": active,
            "paid":   paid,
            "label":  name.capitalize(),
        })
    return providers


# ─────────────────────────────────────────────────────────────────────────────
# API — run tasks
# ─────────────────────────────────────────────────────────────────────────────

def _run_in_thread(fn, kwargs: dict):
    with _task_lock:
        _task_state["running"] = True
        _task_state["status"]  = "running"
        _task_state["result"]  = None
    try:
        result = fn(**kwargs)
        with _task_lock:
            _task_state["result"] = result
            _task_state["status"] = "done"
    except Exception as e:
        log.error(f"Task error: {e}")
        with _task_lock:
            _task_state["result"] = {"error": str(e)}
            _task_state["status"] = "error"
    finally:
        with _task_lock:
            _task_state["running"] = False


@app.post("/api/run/calculator")
async def run_calculator(body: dict = {}):
    if _task_state["running"]:
        return JSONResponse({"error": "A task is already running"}, status_code=409)
    expression = body.get("expression", "127 * 43 - 58")
    with _task_lock:
        _task_state["task"] = "calculator"
    t = threading.Thread(
        target=_run_in_thread,
        args=(task_calculator.run, {"expression": expression}),
        daemon=True,
    )
    t.start()
    return {"started": True, "task": "calculator", "expression": expression}


@app.post("/api/run/vscode")
async def run_vscode():
    if _task_state["running"]:
        return JSONResponse({"error": "A task is already running"}, status_code=409)
    with _task_lock:
        _task_state["task"] = "vscode"
    t = threading.Thread(
        target=_run_in_thread,
        args=(task_vscode.run, {}),
        daemon=True,
    )
    t.start()
    return {"started": True, "task": "vscode"}


@app.post("/api/run/browser_game")
async def run_browser_game(body: dict = {}):
    if _task_state["running"]:
        return JSONResponse({"error": "A task is already running"}, status_code=409)
    moves = body.get("moves", 5)
    with _task_lock:
        _task_state["task"] = "browser_game"
    t = threading.Thread(
        target=_run_in_thread,
        args=(task_browser_game.run, {"moves": moves}),
        daemon=True,
    )
    t.start()
    return {"started": True, "task": "browser_game", "moves": moves}


@app.post("/api/run/notepad")
async def run_notepad():
    if _task_state["running"]:
        return JSONResponse({"error": "A task is already running"}, status_code=409)
    with _task_lock:
        _task_state["task"] = "notepad"
    t = threading.Thread(
        target=_run_in_thread,
        args=(task_notepad.run, {}),
        daemon=True,
    )
    t.start()
    return {"started": True, "task": "notepad"}


@app.post("/api/run/email_draft")
async def run_email_draft():
    if _task_state["running"]:
        return JSONResponse({"error": "A task is already running"}, status_code=409)
    with _task_lock:
        _task_state["task"] = "email_draft"
    t = threading.Thread(
        target=_run_in_thread,
        args=(task_email_draft.run, {}),
        daemon=True,
    )
    t.start()
    return {"started": True, "task": "email_draft"}


@app.post("/api/run/multiapp")
async def run_multiapp():
    if _task_state["running"]:
        return JSONResponse({"error": "A task is already running"}, status_code=409)
    with _task_lock:
        _task_state["task"] = "multiapp"
    t = threading.Thread(
        target=_run_in_thread,
        args=(task_multiapp.run, {}),
        daemon=True,
    )
    t.start()
    return {"started": True, "task": "multiapp"}


@app.get("/api/task/result")
async def task_result():
    return _task_state.copy()


@app.post("/api/reset")
async def api_reset():
    """Reset stuck task state (e.g. after a crash mid-task)."""
    with _task_lock:
        _task_state["running"] = False
        _task_state["status"]  = "idle"
        _task_state["result"]  = None
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# SSE — live log stream
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/logs/stream")
async def log_stream(request: Request):
    q = subscribe()

    async def event_generator():
        # Send a keep-alive comment immediately
        yield ": connected\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = q.get_nowait()
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.05)
        finally:
            unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# API — recordings
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/recordings")
async def list_recordings():
    results = []
    if not RECORDINGS.exists():
        return results
    for task_dir in sorted(RECORDINGS.iterdir()):
        if not task_dir.is_dir():
            continue
        for run_dir in sorted(task_dir.iterdir(), reverse=True):
            meta_file = run_dir / "meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    results.append(meta)
                except Exception:
                    pass
    return results
