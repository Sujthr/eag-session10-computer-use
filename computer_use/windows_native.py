"""
Native Windows driver — fallback when cua-driver is not installed.

Uses win32api / win32gui / ctypes.SendInput for input synthesis and
Windows UI Automation (via comtypes) for AX tree reading.
Exposes the same method signatures as driver.py so layers above are unchanged.
"""
import ctypes
import ctypes.wintypes
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import win32api
import win32clipboard
import win32con
import win32gui
import win32process

from computer_use.logger import log

# ─────────────────────────────────────────────────────────────────────────────
# Virtual key table  (cua-driver key name → Windows VK code)
# ─────────────────────────────────────────────────────────────────────────────
_VK: dict[str, int] = {
    # Digits (top row)
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    # Numpad (Calculator prefers these)
    "KP_0": 0x60, "KP_1": 0x61, "KP_2": 0x62, "KP_3": 0x63, "KP_4": 0x64,
    "KP_5": 0x65, "KP_6": 0x66, "KP_7": 0x67, "KP_8": 0x68, "KP_9": 0x69,
    # Arithmetic operators (numpad)
    "+": 0x6B,   # VK_ADD
    "-": 0x6D,   # VK_SUBTRACT
    "*": 0x6A,   # VK_MULTIPLY
    "/": 0x6F,   # VK_DIVIDE
    ".": 0x6E,   # VK_DECIMAL
    # Special
    "Return": 0x0D,   "Enter": 0x0D,
    "Escape": 0x1B,   "Esc":   0x1B,
    "BackSpace": 0x08, "Delete": 0x2E,
    "Tab": 0x09,
    "space": 0x20, "Space": 0x20,
    # Arrows
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
    "ArrowLeft": 0x25, "ArrowUp": 0x26, "ArrowRight": 0x27, "ArrowDown": 0x28,
    # Modifier
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12,
    # Misc
    "F5": 0x74,
}

# Characters that require Shift on US keyboard
_SHIFT_CHARS: dict[str, int] = {
    "!": ord("1"), "@": ord("2"), "#": ord("3"), "$": ord("4"),
    "%": ord("5"), "^": ord("6"), "&": ord("7"), "=": 0xBB,   # VK_OEM_PLUS
}

# ─────────────────────────────────────────────────────────────────────────────
# SendInput helpers
# ─────────────────────────────────────────────────────────────────────────────
KEYEVENTF_KEYUP   = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD    = 1

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 28)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_u", _INPUT_UNION)]

_user32 = ctypes.windll.user32


def _vk_down(vk: int):
    inp = _INPUT(type=INPUT_KEYBOARD, _u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)))
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

def _vk_up(vk: int):
    inp = _INPUT(type=INPUT_KEYBOARD, _u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)))
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

def _vk_tap(vk: int, delay: float = 0.03):
    _vk_down(vk)
    time.sleep(delay)
    _vk_up(vk)
    time.sleep(delay)


def send_key(key_name: str, delay: float = 0.05):
    """Send a single key by cua-driver key name."""
    vk = _VK.get(key_name)
    if vk is None:
        # Try treating key_name as a single character
        if len(key_name) == 1:
            vk = ord(key_name.upper())
        else:
            log.warning(f"[native] Unknown key: {key_name!r}")
            return
    _vk_tap(vk, delay)


def send_hotkey(keys: list[str], delay: float = 0.05):
    """Hold modifiers, tap the final key, release modifiers."""
    modifiers = [k for k in keys[:-1] if k.lower() in ("ctrl", "shift", "alt", "win")]
    main_key  = keys[-1]

    mod_vks = [_VK[m.lower()] for m in modifiers if m.lower() in _VK]
    for vk in mod_vks:
        _vk_down(vk)
    time.sleep(delay)
    send_key(main_key)
    time.sleep(delay)
    for vk in reversed(mod_vks):
        _vk_up(vk)
    time.sleep(delay)


# ─────────────────────────────────────────────────────────────────────────────
# Window management helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hwnd_for_pid(pid: int) -> int | None:
    """Return the first visible top-level window handle for a PID."""
    result: list[int] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        _, w_pid = win32process.GetWindowThreadProcessId(hwnd)
        if w_pid == pid:
            result.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


# Known title substrings for common apps
_TITLE_HINTS: dict[str, str] = {
    "calc": "Calculator",
    "notepad": "Notepad",
    "code": "Visual Studio Code",
}


def _hwnd_by_title(title_contains: str) -> int | None:
    """Find a visible window whose title contains the given substring."""
    result: list[int] = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title_contains.lower() in title.lower():
                result.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


# PID -> hwnd cache updated after successful bring_to_front
_pid_hwnd: dict[int, int] = {}


def _force_foreground(hwnd: int) -> bool:
    """
    Reliably bring hwnd to the foreground even when Windows blocks it.

    Windows prevents SetForegroundWindow from succeeding unless the calling
    process already owns the foreground input queue.  The fix: temporarily
    attach our thread's input queue to the current foreground thread's queue
    (AttachThreadInput), call SetForegroundWindow, then detach.
    """
    import ctypes
    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # Restore the window first (unminimise if needed)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    time.sleep(0.05)

    fg_hwnd = user32.GetForegroundWindow()
    fg_tid  = win32process.GetWindowThreadProcessId(fg_hwnd)[0] if fg_hwnd else 0
    our_tid = kernel32.GetCurrentThreadId()

    attached = False
    if fg_tid and fg_tid != our_tid:
        attached = bool(user32.AttachThreadInput(our_tid, fg_tid, True))

    try:
        user32.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        log.debug(f"[native] _force_foreground SetForegroundWindow: {e}")
    finally:
        if attached:
            user32.AttachThreadInput(our_tid, fg_tid, False)

    time.sleep(0.1)
    return win32gui.GetForegroundWindow() == hwnd


def bring_window_to_front(pid: int, title_hint: str = "", retries: int = 4, wait: float = 0.4):
    """
    Bring a window to the foreground.
    For UWP apps (like Windows 11 Calculator) the launcher PID != window PID,
    so we also try matching by window title.
    Uses _force_foreground to bypass Windows' foreground-lock.
    """
    # Try cached hwnd first (fast path)
    cached = _pid_hwnd.get(pid)
    if cached and win32gui.IsWindow(cached):
        try:
            _force_foreground(cached)
            return cached
        except Exception:
            del _pid_hwnd[pid]

    for attempt in range(retries):
        hwnd = _hwnd_for_pid(pid)

        # UWP fallback: find by window title
        if hwnd is None and title_hint:
            hwnd = _hwnd_by_title(title_hint)

        if hwnd is None:
            # Generic title search for well-known apps
            for key, title in _TITLE_HINTS.items():
                hwnd = _hwnd_by_title(title)
                if hwnd:
                    break

        if hwnd:
            _force_foreground(hwnd)
            _pid_hwnd[pid] = hwnd
            log.debug(f"[native] Foregrounded hwnd={hwnd:#010x} title={win32gui.GetWindowText(hwnd)!r}")
            return hwnd

        time.sleep(wait)

    log.debug(f"[native] Could not foreground window for pid={pid}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# App launcher
# ─────────────────────────────────────────────────────────────────────────────

_BUNDLE_ALIASES = {
    "Microsoft.WindowsCalculator_8wekyb3d8bbwe": "calc.exe",
    "calc.exe": "calc.exe",
    "chrome": "chrome.exe",
    "chrome.exe": "chrome.exe",
    "code": "code.exe",
    "code.exe": "code.exe",
    "com.microsoft.VSCode": "code.exe",
    "notepad": "notepad.exe",
    "notepad.exe": "notepad.exe",
}


def launch(bundle_id: str, args: list[str] | None = None, **_kwargs) -> int:
    exe = _BUNDLE_ALIASES.get(bundle_id, bundle_id)
    cmd = [exe] + (args or [])
    log.info(f"[native] Launching {cmd}")
    try:
        proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        time.sleep(0.6)
        log.info(f"[native] Launched {exe}  pid={proc.pid}")
        return proc.pid
    except FileNotFoundError:
        raise RuntimeError(f"Cannot launch {exe!r} — not found on PATH") from None


# ─────────────────────────────────────────────────────────────────────────────
# Clipboard helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_clipboard_text() -> str:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return str(data).strip()
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.1)
    return ""


def set_clipboard_text(text: str):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic window state (mirrors cua-driver get_window_state response)
# ─────────────────────────────────────────────────────────────────────────────

def get_window_state(pid: int, **_) -> dict:
    """
    Return a synthetic AX-tree dict shaped like cua-driver's get_window_state.
    Tree content is tailored to the window title so Layer 2b gets useful context.
    """
    hwnd = _hwnd_for_pid(pid)
    if hwnd is None:
        return {"element_count": 0, "markdown": ""}

    title = win32gui.GetWindowText(hwnd)
    tl = title.lower()

    if "calculator" in tl:
        markdown = (
            f"# Window: {title}\n"
            f"[element_index 0] Display: (shows current calculated value)\n"
            f"[element_index 1] Button: C (Clear all)\n"
            f"[element_index 2] Button: = (Equals / compute result)\n"
        )
    elif any(x in tl for x in ("notepad", "untitled", ".txt", "meeting_notes", "email_draft", "expense")):
        markdown = (
            f"# Window: {title}\n"
            f"[element_index 0] TextArea: main text editing area — type all content here\n"
        )
    elif any(x in tl for x in ("mail", "outlook", "message", "compose")):
        markdown = (
            f"# Window: {title}\n"
            f"[element_index 0] Field: To — recipient email address\n"
            f"[element_index 1] Field: Subject — email subject line\n"
            f"[element_index 2] TextArea: Body — email message body\n"
        )
    elif any(x in tl for x in ("word", "document", "wordpad")):
        markdown = (
            f"# Window: {title}\n"
            f"[element_index 0] DocumentArea: main document editing area\n"
        )
    else:
        markdown = (
            f"# Window: {title}\n"
            f"[element_index 0] ContentArea: main interactive area of this window\n"
        )

    lines = [l for l in markdown.splitlines() if "[element_index" in l]
    return {
        "element_count": len(lines),
        "markdown":      markdown,
        "window_title":  title,
        "hwnd":          hwnd,
    }


def close_app(pid: int, title_hint: str = "") -> None:
    """
    Terminate an application cleanly.

    Uses taskkill /F so no save-dialog can block the close.  The caller is
    responsible for ensuring any file content has been saved before calling this.
    """
    import subprocess
    result = subprocess.run(
        ["taskkill", "/F", "/PID", str(pid)],
        capture_output=True,
    )
    if result.returncode == 0:
        log.info(f"[close_app] pid={pid} terminated")
    else:
        # pid might be the launcher; try title-based close as fallback
        err = result.stderr.decode("utf-8", errors="replace").strip()
        log.warning(f"[close_app] taskkill pid={pid} failed ({err}), trying title")
        if title_hint:
            subprocess.run(
                ["taskkill", "/F", "/FI", f"WINDOWTITLE eq *{title_hint}*"],
                capture_output=True,
            )
            log.info(f"[close_app] closed by title hint {title_hint!r}")
