"""
Logging configuration: loguru to file + console + in-memory broadcast queue
for the dashboard SSE stream.
"""
import sys
import queue
import threading
from pathlib import Path
from loguru import logger

# Force UTF-8 on Windows consoles that default to cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

# ── In-memory broadcast for SSE ───────────────────────────────────────────────
_subscribers: list[queue.Queue] = []
_lock = threading.Lock()

def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=500)
    with _lock:
        _subscribers.append(q)
    return q

def unsubscribe(q: queue.Queue):
    with _lock:
        _subscribers.discard(q) if hasattr(_subscribers, "discard") else None
        try:
            _subscribers.remove(q)
        except ValueError:
            pass

def _broadcast(message):
    # loguru passes a Message object; the actual record dict is at .record
    record = message.record
    msg = {
        "time":    record["time"].strftime("%H:%M:%S"),
        "level":   record["level"].name,
        "message": record["message"],
        "module":  record["module"],
    }
    with _lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

# ── Configure loguru ──────────────────────────────────────────────────────────
logger.remove()   # remove default handler

# Console — colour, no stack traces for INFO
logger.add(
    sys.stdout,
    colorize=True,
    format=(
        "<green>{time:HH:mm:ss}</green> "
        "<level>{level: <8}</level> "
        "<cyan>{module}</cyan>:<cyan>{function}</cyan>  "
        "<level>{message}</level>"
    ),
    level="DEBUG",
)

# Rotating file — full detail
logger.add(
    _LOG_DIR / "agent_{time:YYYY-MM-DD}.log",
    rotation="10 MB",
    retention="7 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {module}:{function}:{line} | {message}",
    level="DEBUG",
    encoding="utf-8",
)

# SSE broadcast sink
logger.add(_broadcast, level="DEBUG", format="{message}")

log = logger
