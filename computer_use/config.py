"""
Central configuration loader.
Loads .env from local directory first, then falls back to the shared path.
"""
import os
import itertools
from pathlib import Path
from dotenv import load_dotenv

_SHARED_ENV = Path(r"D:\EAG\EAG\06JuneAssignment\cc33f915-5cf0-4ca5-b7ad-8d8e786736e8\.env")
_LOCAL_ENV  = Path(__file__).parent.parent / ".env"

def _load():
    if _LOCAL_ENV.exists():
        load_dotenv(_LOCAL_ENV, override=False)
    if _SHARED_ENV.exists():
        load_dotenv(_SHARED_ENV, override=False)

_load()

# ── Gemini ────────────────────────────────────────────────────────────────────
def _collect_gemini_keys() -> list[str]:
    keys = []
    for suffix in ["", "_1", "_2", "_3", "_4", "_5"]:
        v = os.getenv(f"GEMINI_API_KEY{suffix}", "").strip()
        if v and v not in keys:
            keys.append(v)
    return keys

GEMINI_KEYS   = _collect_gemini_keys()
GEMINI_MODEL  = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
_gemini_cycle = itertools.cycle(GEMINI_KEYS) if GEMINI_KEYS else iter([])

def next_gemini_key() -> str:
    """Round-robin Gemini key rotation."""
    if not GEMINI_KEYS:
        raise RuntimeError("No GEMINI_API_KEY configured")
    return next(_gemini_cycle)

# ── Free-tier fallbacks ───────────────────────────────────────────────────────
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL         = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

CEREBRAS_API_KEY   = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL     = os.getenv("CEREBRAS_MODEL", "llama3.1-8b")

NVIDIA_API_KEY     = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_MODEL       = os.getenv("NVIDIA_MODEL", "nvidia/llama-3.1-nemotron-nano-8b-v1")

GITHUB_TOKEN       = os.getenv("GITHUB_ACCESS_TOKEN", "")
GITHUB_MODEL       = os.getenv("GITHUB_MODEL", "openai/gpt-4.1-mini")

OPENROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY", "")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

# ── Paid last resort ──────────────────────────────────────────────────────────
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL       = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_HOST     = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT     = int(os.getenv("DASHBOARD_PORT", "8765"))

# ── Provider priority list ────────────────────────────────────────────────────
PROVIDER_ORDER = [
    p for p, key in [
        ("gemini",     GEMINI_KEYS),
        ("groq",       GROQ_API_KEY),
        ("cerebras",   CEREBRAS_API_KEY),
        ("nvidia",     NVIDIA_API_KEY),
        ("github",     GITHUB_TOKEN),
        ("openrouter", OPENROUTER_API_KEY),
        ("openai",     OPENAI_API_KEY),
    ]
    if key
]
