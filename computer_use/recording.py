"""
Thin wrapper around cua-driver start_recording / stop_recording.
Also saves a metadata JSON file beside the trajectory.
"""
import json
import time
from pathlib import Path
from contextlib import contextmanager

from computer_use import driver
from computer_use.logger import log

_RECORDINGS_DIR = Path(__file__).parent.parent / "recordings"
_RECORDINGS_DIR.mkdir(exist_ok=True)

_current: dict | None = None


def start(task_name: str) -> Path:
    global _current
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = _RECORDINGS_DIR / task_name / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        driver.call("start_recording", {"output_dir": str(out_dir)})
    except Exception as e:
        log.warning(f"Recording not available (cua-driver missing?): {e}")

    _current = {"task": task_name, "start_ts": ts, "dir": str(out_dir), "actions": []}
    log.info(f"Recording started → {out_dir}")
    return out_dir


def log_action(action: str, detail: str = ""):
    if _current is not None:
        _current["actions"].append({"t": time.strftime("%H:%M:%S"), "action": action, "detail": detail})


def stop(status: str = "ok", result: str = ""):
    global _current
    try:
        driver.call("stop_recording", {})
    except Exception:
        pass

    if _current:
        _current["end_ts"]  = time.strftime("%Y%m%d_%H%M%S")
        _current["status"]  = status
        _current["result"]  = result
        meta_path = Path(_current["dir"]) / "meta.json"
        meta_path.write_text(json.dumps(_current, indent=2), encoding="utf-8")
        log.info(f"Recording saved → {meta_path}")
    _current = None


@contextmanager
def session(task_name: str):
    out_dir = start(task_name)
    status, result = "ok", ""
    try:
        yield out_dir
    except Exception as e:
        status, result = "error", str(e)
        raise
    finally:
        stop(status, result)
