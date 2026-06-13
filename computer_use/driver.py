"""
cua-driver wrapper with automatic Windows-native fallback.

Priority:
  1. cua-driver v0.5+ (if binary found; daemon must be running)
  2. windows_native.py  (pywin32 + ctypes — always available on Windows)

cua-driver CLI contract (v0.5):
  JSON is piped via stdin:   echo '{"pid":N}' | cua-driver call <tool>
  Positional JSON is unreliable on Windows (PowerShell quote-stripping).

window_id tracking:
  Several tools (bring_to_front, get_window_state) require both pid AND
  window_id.  After launch_app we query list_windows to discover the actual
  window and cache (pid → window_id) in _WIN_IDS.
"""
import json
import os
import shutil
import subprocess
import time
from typing import Any

from computer_use.logger import log

# ─────────────────────────────────────────────────────────────────────────────
_CUA_KNOWN = r"C:\Users\DELL\AppData\Local\Programs\Cua\cua-driver\bin\cua-driver.exe"
CUA_BINARY           = "cua-driver"   # resolved by _resolve_cua_binary()
_DAEMON_STARTUP_WAIT = 1.5
_CALL_TIMEOUT        = 60            # seconds — longer for launch_app

_cua_available: bool | None = None

# pid → window_id cache populated after launch_app / list_windows
_WIN_IDS: dict[int, int] = {}
_WIN_HINTS: dict[int, str] = {}   # pid → title hint for re-discovery

# Known bundle → window title substring for discovery after launch
_BUNDLE_TITLE_HINTS: dict[str, str] = {
    "Microsoft.WindowsCalculator_8wekyb3d8bbwe": "Calculator",
    "calc.exe": "Calculator",
    "notepad.exe": "Notepad",
    "code.exe": "Visual Studio Code",
    "com.microsoft.VSCode": "Visual Studio Code",
    "chrome.exe": "Chrome",
    "chrome": "Chrome",
}


# ─────────────────────────────────────────────────────────────────────────────
# Binary discovery
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_cua_binary() -> str | None:
    # 1. Already on PATH
    found = shutil.which("cua-driver")
    if found:
        return found
    # 2. Known install location (handles fresh installs before PATH refresh)
    if os.path.isfile(_CUA_KNOWN):
        return _CUA_KNOWN
    # 3. Scan User PATH from registry
    try:
        reg = subprocess.run(
            ["reg", "query", r"HKCU\Environment", "/v", "PATH"],
            capture_output=True, text=True
        )
        for line in reg.stdout.splitlines():
            if "PATH" in line and "REG_" in line:
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    for seg in parts[2].strip().split(";"):
                        candidate = shutil.which("cua-driver", path=seg.strip())
                        if candidate:
                            return candidate
    except Exception:
        pass
    return None


def _check_cua() -> bool:
    global _cua_available, CUA_BINARY
    if _cua_available is None:
        resolved = _resolve_cua_binary()
        if resolved:
            CUA_BINARY = resolved
            _cua_available = True
            log.info(f"cua-driver found: {resolved}")
        else:
            _cua_available = False
            log.warning("cua-driver not found — using Windows-native fallback")
    return _cua_available


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class CuaNotInstalledError(RuntimeError):
    pass

class DriverError(RuntimeError):
    pass

class PreconditionError(RuntimeError):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Core call — JSON via stdin pipe (reliable on Windows)
# ─────────────────────────────────────────────────────────────────────────────

def call(tool: str, args: dict[str, Any], timeout: int = _CALL_TIMEOUT) -> dict[str, Any]:
    if not _check_cua():
        raise DriverError("cua-driver not available")

    payload = json.dumps(args)
    log.debug(f"[cua] {tool}  {payload[:100]}")

    # Use binary I/O then decode as UTF-8 — cua-driver output may contain
    # Unicode (emoji in window titles etc.) that cp1252 cannot handle.
    result = subprocess.run(
        [CUA_BINARY, "call", tool],
        input=payload.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
    )

    raw = result.stdout.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace").strip() or raw
        raise DriverError(f"{tool} failed: {err}")

    if not raw:
        return {}

    try:
        response = json.loads(raw)
    except json.JSONDecodeError:
        # Some tools return a plain text success line (e.g. press_key)
        return {"message": raw}

    if isinstance(response, dict) and response.get("error"):
        raise DriverError(f"{tool} error: {response['error']}")

    return response if isinstance(response, dict) else {"result": response}


# ─────────────────────────────────────────────────────────────────────────────
# Daemon management
# ─────────────────────────────────────────────────────────────────────────────

def ensure_daemon() -> bool:
    if not _check_cua():
        log.info("Using Windows-native driver (no daemon needed)")
        return True

    result = subprocess.run([CUA_BINARY, "status"], capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        log.debug("cua-driver daemon already running")
        return True

    log.info("Starting cua-driver daemon…")
    subprocess.Popen(
        [CUA_BINARY, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(_DAEMON_STARTUP_WAIT)

    check = subprocess.run([CUA_BINARY, "status"], capture_output=True, timeout=5)
    if check.returncode != 0:
        raise DriverError("cua-driver daemon failed to start")

    log.success("cua-driver daemon started")
    return True


def shutdown_daemon():
    if _check_cua():
        try:
            subprocess.run([CUA_BINARY, "shutdown"], timeout=5)
            log.info("cua-driver daemon stopped")
        except Exception as e:
            log.warning(f"shutdown error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Window ID helpers
# ─────────────────────────────────────────────────────────────────────────────

def list_windows() -> list[dict]:
    """Return all top-level windows from the daemon."""
    resp = call("list_windows", {})
    return resp.get("_legacy_windows", resp.get("windows", []))


def _refresh_window_id(pid: int) -> int | None:
    """
    Force-refresh the window_id for a pid by querying list_windows.
    Uses stored title hint as fallback (handles UWP PID mismatch).
    """
    _WIN_IDS.pop(pid, None)
    title_hint = _WIN_HINTS.get(pid, "")
    found = _discover_window(pid, title_hint, wait=2.0)
    if found:
        actual_pid, wid = found
        _WIN_IDS[pid]        = wid
        _WIN_IDS[actual_pid] = wid
        return wid
    return None


def _discover_window(pid: int, title_hint: str = "", wait: float = 2.0) -> tuple[int, int] | None:
    """
    Find the actual (pid, window_id) for a launched app.
    UWP launchers spawn a child process; we match by title or pid.
    Returns None if not found within `wait` seconds.
    """
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            windows = list_windows()
        except Exception:
            time.sleep(0.3)
            continue

        for w in windows:
            w_pid = w.get("pid", 0)
            w_id  = w.get("window_id", 0)
            title = w.get("title", "")

            # Match by exact pid
            if w_pid == pid and w_id:
                return w_pid, w_id

            # Match by title hint (handles UWP PID mismatch)
            if title_hint and title_hint.lower() in title.lower() and w_id:
                return w_pid, w_id

        time.sleep(0.3)

    return None


def _get_window_id(pid: int, title_hint: str = "") -> int | None:
    """Return cached window_id for pid, or discover it."""
    if pid in _WIN_IDS:
        return _WIN_IDS[pid]
    found = _discover_window(pid, title_hint)
    if found:
        actual_pid, wid = found
        _WIN_IDS[pid]        = wid
        _WIN_IDS[actual_pid] = wid
        return wid
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Typed public helpers
# ─────────────────────────────────────────────────────────────────────────────

def launch_app(
    bundle_id: str,
    *,
    electron_debugging_port: int | None = None,
    args: list[str] | None = None,
    title_hint: str = "",
) -> int:
    if _check_cua():
        payload: dict = {"bundle_id": bundle_id}
        if electron_debugging_port:
            payload["electron_debugging_port"] = electron_debugging_port
        if args:
            payload["args"] = args
        resp = call("launch_app", payload, timeout=45)
        pid = resp.get("pid", 0)
        # Eagerly discover window_id in background
        if pid:
            hint = title_hint or _BUNDLE_TITLE_HINTS.get(bundle_id, bundle_id.split(".")[-1])
            _WIN_HINTS[pid] = hint
            found = _discover_window(pid, hint, wait=5.0)
            if found:
                actual_pid, wid = found
                _WIN_IDS[pid]        = wid
                _WIN_IDS[actual_pid] = wid
                _WIN_HINTS[actual_pid] = hint
                pid = actual_pid   # use real window pid
    else:
        from computer_use import windows_native as nat
        pid = nat.launch(bundle_id, args=args)

    log.info(f"Launched {bundle_id!r}  pid={pid}")
    return pid


def list_apps() -> list[dict]:
    if _check_cua():
        return call("list_apps", {}).get("apps", [])
    return []


def bring_to_front(pid: int, title_hint: str = ""):
    if _check_cua():
        wid = _get_window_id(pid, title_hint)
        if wid is None:
            log.warning(f"bring_to_front: no window_id for pid={pid}, skipping")
            return
        try:
            call("bring_to_front", {"pid": pid, "window_id": wid})
        except DriverError as e:
            # Windows foreground-lock — non-fatal, press_key still works
            log.debug(f"bring_to_front: {e}")
    else:
        from computer_use import windows_native as nat
        nat.bring_window_to_front(pid, title_hint=title_hint)
    log.debug(f"bring_to_front pid={pid}")


def get_window_state(pid: int, window_id: int = 0) -> dict:
    if _check_cua():
        wid = window_id or _WIN_IDS.get(pid, 0)
        if wid == 0:
            # Try to discover
            found = _discover_window(pid, wait=1.0)
            if found:
                _, wid = found
                _WIN_IDS[pid] = wid
        if wid == 0:
            log.warning(f"get_window_state: no window_id for pid={pid}")
            return {"element_count": 0, "markdown": ""}
        try:
            resp = call("get_window_state", {"pid": pid, "window_id": wid})
        except DriverError as e:
            if "No window with window_id" in str(e) or "Invalid window handle" in str(e):
                # UWP window recreated — refresh and retry once
                new_wid = _refresh_window_id(pid)
                if new_wid:
                    log.debug(f"get_window_state: refreshed window_id {wid}→{new_wid}")
                    try:
                        resp = call("get_window_state", {"pid": pid, "window_id": new_wid})
                    except DriverError as e2:
                        log.warning(f"get_window_state retry failed: {e2}")
                        return {"element_count": 0, "markdown": ""}
                else:
                    log.warning(f"get_window_state: window not found for pid={pid}")
                    return {"element_count": 0, "markdown": ""}
            else:
                log.warning(f"get_window_state failed: {e}")
                return {"element_count": 0, "markdown": ""}
    else:
        from computer_use import windows_native as nat
        resp = nat.get_window_state(pid)

    # Normalise key: v0.5+ uses 'tree_markdown', older used 'markdown'
    if "tree_markdown" in resp and "markdown" not in resp:
        resp["markdown"] = resp["tree_markdown"]

    n = resp.get("element_count", 0)
    log.debug(f"get_window_state pid={pid}  elements={n}")
    return resp


def click(pid: int, element_index: int):
    log.info(f"  click  element={element_index}")
    if _check_cua():
        wid = _WIN_IDS.get(pid, 0)
        args: dict = {"pid": pid, "element_index": element_index}
        if wid:
            args["window_id"] = wid
        try:
            call("click", args)
        except DriverError as e:
            if "No window with window_id" in str(e) or "Invalid window handle" in str(e) or "not in cache" in str(e):
                new_wid = _refresh_window_id(pid)
                if new_wid:
                    log.debug(f"click: refreshed window_id, retrying element={element_index}")
                    call("get_window_state", {"pid": pid, "window_id": new_wid})
                    args["window_id"] = new_wid
                    call("click", args)
                else:
                    raise
            else:
                raise
    else:
        log.warning("[native] click by element_index not supported; ignoring")


def type_text(pid: int, element_index: int, text: str):
    log.info(f"  type_text  element={element_index}  text={text!r}")
    if _check_cua():
        wid = _WIN_IDS.get(pid, 0)
        args: dict = {"pid": pid, "element_index": element_index, "text": text}
        if wid:
            args["window_id"] = wid
        call("type_text", args)
    else:
        from computer_use import windows_native as nat
        nat.bring_window_to_front(pid)
        for ch in text:
            _native_type_char(ch)


def _native_type_char(ch: str):
    import ctypes
    from computer_use import windows_native as nat
    vk = nat._VK.get(ch)
    if vk is not None:
        nat._vk_tap(vk)
    else:
        inp = nat._INPUT(type=nat.INPUT_KEYBOARD,
                         _u=nat._INPUT_UNION(ki=nat._KEYBDINPUT(
                             wVk=0, wScan=ord(ch), dwFlags=nat.KEYEVENTF_UNICODE,
                             time=0, dwExtraInfo=None)))
        nat._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(nat._INPUT))
        time.sleep(0.02)
        inp._u.ki.dwFlags |= nat.KEYEVENTF_KEYUP
        nat._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(nat._INPUT))
        time.sleep(0.02)


def press_key(pid: int, key: str):
    log.info(f"  press_key  key={key!r}")
    if _check_cua():
        wid = _WIN_IDS.get(pid, 0)
        args: dict = {"pid": pid, "key": key}
        if wid:
            args["window_id"] = wid
        call("press_key", args)
    else:
        from computer_use import windows_native as nat
        nat.send_key(key)


def hotkey(pid: int, keys: list[str]):
    combo = "+".join(keys)
    log.info(f"  hotkey  {combo}")
    if _check_cua():
        wid = _WIN_IDS.get(pid, 0)
        args: dict = {"pid": pid, "keys": keys}
        if wid:
            args["window_id"] = wid
        call("hotkey", args)
    else:
        from computer_use import windows_native as nat
        nat.send_hotkey(keys)


def take_screenshot(pid: int) -> bytes:
    if _check_cua():
        import base64
        wid = _WIN_IDS.get(pid, 0)
        args: dict = {"pid": pid}
        if wid:
            args["window_id"] = wid
        resp = call("get_window_state", args)   # get_window_state includes screenshot
        b64  = resp.get("screenshot_png_b64", "")
        if b64:
            log.debug("Screenshot captured via cua-driver")
            return base64.b64decode(b64)
    return _native_screenshot(pid)


def _native_screenshot(pid: int) -> bytes:
    import io
    from PIL import ImageGrab
    from computer_use import windows_native as nat
    nat.bring_window_to_front(pid)
    time.sleep(0.2)
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    log.debug("Screenshot captured via PIL")
    return buf.getvalue()


def click_at(pid: int, x: int, y: int):
    log.info(f"  click_at  ({x}, {y})")
    if _check_cua():
        call("click_at", {"pid": pid, "x": x, "y": y})
    else:
        import ctypes
        ctypes.windll.user32.SetCursorPos(x, y)
        time.sleep(0.05)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


def page(pid: int, action: str, **kwargs) -> dict:
    log.info(f"  page  action={action!r}  {kwargs}")
    if _check_cua():
        wid = _WIN_IDS.get(pid, 0)
        args: dict = {"pid": pid, "action": action, **kwargs}
        if wid:
            args["window_id"] = wid
        return call("page", args)
    log.warning("[native] page/CDP not available without cua-driver")
    return {}


def kill_app(pid: int):
    if _check_cua():
        call("kill_app", {"pid": pid})
    else:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    log.info(f"Killed pid={pid}")
