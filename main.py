"""
main.py — CLI entry point with Rich live dashboard.

Usage:
    python main.py                         # interactive launcher
    python main.py --task calculator       # run directly
    python main.py --task vscode
    python main.py --task browser_game
    python main.py --dashboard             # launch web dashboard only
"""
import argparse
import json
import os
import sys
import time
import threading
import webbrowser
from pathlib import Path

# ── Rich UI ────────────────────────────────────────────────────────────────────
from rich import print as rprint
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap project imports (after console so errors display nicely)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from computer_use import config, driver
    from computer_use.logger import log
    from computer_use.tasks import (
        task_calculator, task_vscode, task_browser_game,
        task_notepad, task_email_draft, task_multiapp,
    )
except ImportError as e:
    console.print(f"[red]Import error: {e}[/red]")
    sys.exit(1)

RECORDINGS = Path(__file__).parent / "recordings"


# ─────────────────────────────────────────────────────────────────────────────
# Rich helpers
# ─────────────────────────────────────────────────────────────────────────────

def _banner():
    lines = [
        "[bold cyan] ██████╗ ███████╗███████╗██╗  ██╗████████╗ ██████╗ ██████╗ ",
        " ██╔══██╗██╔════╝██╔════╝██║ ██╔╝╚══██╔══╝██╔═══██╗██╔══██╗",
        " ██║  ██║█████╗  ███████╗█████╔╝    ██║   ██║   ██║██████╔╝",
        " ██║  ██║██╔══╝  ╚════██║██╔═██╗    ██║   ██║   ██║██╔═══╝ ",
        " ██████╔╝███████╗███████║██║  ██╗   ██║   ╚██████╔╝██║     ",
        " ╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝[/bold cyan]",
        "",
        "[dim]  Computer-Use Agent  ·  Session 10  ·  Five-Layer Cascade[/dim]",
    ]
    console.print("\n".join(lines))
    console.print()


def _provider_table() -> Table:
    t = Table(title="API Providers", box=None, show_header=True, padding=(0, 2))
    t.add_column("Provider",  style="bold")
    t.add_column("Status",    justify="center")
    t.add_column("Tier")
    t.add_column("Model",     style="dim")

    provider_info = {
        "gemini":     ("free", config.GEMINI_MODEL),
        "groq":       ("free", config.GROQ_MODEL),
        "cerebras":   ("free", config.CEREBRAS_MODEL),
        "nvidia":     ("free", config.NVIDIA_MODEL),
        "github":     ("free", config.GITHUB_MODEL),
        "openrouter": ("free", config.OPENROUTER_MODEL),
        "openai":     ("PAID ⚠", config.OPENAI_MODEL),
    }

    for name, (tier, model) in provider_info.items():
        active = name in config.PROVIDER_ORDER
        status = "[green]● active[/green]" if active else "[dim]○ off[/dim]"
        tier_s = "[yellow]paid[/yellow]" if tier.startswith("PAID") else "[green]free[/green]"
        t.add_row(name, status, tier_s, model if active else "—")

    return t


def _recordings_table() -> Table:
    t = Table(title="Recent Recordings", box=None, show_header=True, padding=(0, 2))
    t.add_column("Task",    style="bold")
    t.add_column("Status",  justify="center")
    t.add_column("Actions", justify="right")
    t.add_column("Started", style="dim")

    if not RECORDINGS.exists():
        t.add_row("[dim]none[/dim]", "—", "—", "—")
        return t

    rows = []
    for task_dir in RECORDINGS.iterdir():
        if not task_dir.is_dir():
            continue
        for run_dir in sorted(task_dir.iterdir(), reverse=True)[:3]:
            meta = run_dir / "meta.json"
            if meta.exists():
                try:
                    m = json.loads(meta.read_text(encoding="utf-8"))
                    rows.append(m)
                except Exception:
                    pass

    if not rows:
        t.add_row("[dim]none[/dim]", "—", "—", "—")
        return t

    for m in rows[:8]:
        ok     = m.get("status") == "ok"
        status = "[green]✓ ok[/green]" if ok else "[red]✗ error[/red]"
        acts   = str(len(m.get("actions", [])))
        ts     = m.get("start_ts", "?")
        t.add_row(m.get("task", "?"), status, acts, ts)

    return t


def _run_task_with_spinner(name: str, fn, kwargs: dict) -> dict:
    """Run a task function with a Rich spinner, capturing the result."""
    result: dict = {}
    error: list  = []

    def _worker():
        try:
            result.update(fn(**kwargs))
        except Exception as e:
            error.append(str(e))

    t = threading.Thread(target=_worker, daemon=True)

    with Progress(
        SpinnerColumn(spinner_name="dots2"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(f"[cyan]Running {name}…", total=None)
        t.start()
        while t.is_alive():
            time.sleep(0.1)
        t.join()

    if error:
        console.print(f"[red]Task error: {error[0]}[/red]")
        return {"status": "error", "error": error[0]}

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard launcher
# ─────────────────────────────────────────────────────────────────────────────

def launch_dashboard(open_browser: bool = True):
    import uvicorn
    from dashboard.app import app as dash_app

    host = config.DASHBOARD_HOST
    port = config.DASHBOARD_PORT
    url  = f"http://{host}:{port}"

    console.print(Panel(
        f"[bold cyan]Dashboard starting at[/bold cyan]\n\n"
        f"  [link={url}]{url}[/link]\n\n"
        f"[dim]Press Ctrl+C to stop[/dim]",
        title="[bold]Web Dashboard[/bold]",
        border_style="cyan",
        padding=(1, 4),
    ))

    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        dash_app,
        host=host,
        port=port,
        log_level="info",   # show startup confirmation in logs
    )


# ─────────────────────────────────────────────────────────────────────────────
# Interactive launcher
# ─────────────────────────────────────────────────────────────────────────────

def interactive():
    _banner()

    # Provider status
    console.print(_provider_table())
    console.print(Rule(style="dim"))

    # Gemini key count
    n = len(config.GEMINI_KEYS)
    console.print(f"  Gemini keys loaded: [cyan]{n}[/cyan]  (round-robin rotation)")
    console.print()

    # Check daemon
    console.print("[dim]Checking cua-driver…[/dim]", end=" ")
    import shutil
    if shutil.which("cua-driver"):
        console.print("[green]found[/green]")
    else:
        console.print("[yellow]not found — tasks will fail with clear error[/yellow]")
    console.print()

    # Menu
    console.print(Panel(
        "[bold]Choose a task to run:[/bold]\n\n"
        "  [cyan][1][/cyan]  Calculator      [dim](Layer 2a — deterministic, zero vision)[/dim]\n"
        "  [cyan][2][/cyan]  VS Code         [dim](Electron CDP path)[/dim]\n"
        "  [cyan][3][/cyan]  Browser Game    [dim](Layer 3 vision — 2048)[/dim]\n"
        "  [cyan][4][/cyan]  Notepad         [dim](Layer 2b — meeting notes)[/dim]\n"
        "  [cyan][5][/cyan]  Email Draft     [dim](Layer 2b + LLM verification)[/dim]\n"
        "  [cyan][6][/cyan]  Multi-App       [dim](Layer 2a+2b — Calculator → Notepad)[/dim]\n"
        "  [cyan][a][/cyan]  Run all six\n"
        "  [cyan][d][/cyan]  Launch web dashboard\n"
        "  [cyan][q][/cyan]  Quit",
        title="[bold cyan]Desktop Agent — Session 10[/bold cyan]",
        border_style="cyan",
        padding=(1, 3),
    ))

    choice = console.input("[bold cyan]›[/bold cyan] ").strip().lower()

    if choice == "1":
        expr = console.input("  Expression [dim](default: 127 * 43 - 58)[/dim]: ").strip()
        if not expr:
            expr = "127 * 43 - 58"
        result = _run_task_with_spinner("calculator", task_calculator.run, {"expression": expr})
        console.print(Panel(
            f"[green]Expression:[/green]  {expr}\n"
            f"[green]Result:[/green]      [bold]{result.get('result', '?')}[/bold]\n"
            f"[green]Expected:[/green]    {result.get('expected', '?')}\n"
            f"[green]Layer:[/green]       {result.get('layer', '?')}",
            title="[bold green]✓ Calculator done[/bold green]",
            border_style="green",
        ))

    elif choice == "2":
        result = _run_task_with_spinner("vscode", task_vscode.run, {})
        console.print(Panel(
            f"[purple]File:[/purple]      {result.get('file', '?')}\n"
            f"[purple]Output:[/purple]    {result.get('output', '?')}\n"
            f"[purple]Layer:[/purple]     {result.get('layer', '?')}\n"
            f"[purple]Verified:[/purple]  {result.get('verified', '?')}",
            title="[bold]✓ VS Code done[/bold]",
            border_style="bright_magenta",
        ))

    elif choice == "3":
        moves = console.input("  Moves [dim](default: 5)[/dim]: ").strip()
        moves = int(moves) if moves.isdigit() else 5
        result = _run_task_with_spinner("browser_game", task_browser_game.run, {"moves": moves})
        console.print(Panel(
            f"[yellow]Moves made:[/yellow]  {result.get('moves_made', '?')}\n"
            f"[yellow]Layer:[/yellow]       {result.get('layer', '?')}",
            title="[bold]✓ Browser Game done[/bold]",
            border_style="yellow",
        ))

    elif choice == "4":
        result = _run_task_with_spinner("notepad", task_notepad.run, {})
        console.print(Panel(
            f"[blue]File:[/blue]      {result.get('file', '?')}\n"
            f"[blue]Chars:[/blue]     {result.get('chars', '?')}\n"
            f"[blue]Verified:[/blue]  {result.get('verified', '?')}\n"
            f"[blue]Layer:[/blue]     {result.get('layer', '?')}",
            title="[bold]✓ Notepad done[/bold]",
            border_style="blue",
        ))

    elif choice == "5":
        result = _run_task_with_spinner("email_draft", task_email_draft.run, {})
        missing = result.get('missing', [])
        console.print(Panel(
            f"[magenta]File:[/magenta]      {result.get('file', '?')}\n"
            f"[magenta]Chars:[/magenta]     {result.get('chars', '?')}\n"
            f"[magenta]Verified:[/magenta]  {result.get('verified', '?')}\n"
            f"[magenta]Missing:[/magenta]   {missing if missing else 'none'}\n"
            f"[magenta]Layer:[/magenta]     {result.get('layer', '?')}",
            title="[bold]✓ Email Draft done[/bold]",
            border_style="magenta",
        ))

    elif choice == "6":
        expr = console.input("  Expression [dim](default: 157 * 24)[/dim]: ").strip()
        if not expr:
            expr = "157 * 24"
        result = _run_task_with_spinner("multiapp", task_multiapp.run, {"expression": expr})
        console.print(Panel(
            f"[cyan]Expression:[/cyan]  {result.get('expression', '?')}\n"
            f"[cyan]Result:[/cyan]      [bold]{result.get('result', '?')}[/bold]\n"
            f"[cyan]File:[/cyan]        {result.get('file', '?')}\n"
            f"[cyan]Verified:[/cyan]    {result.get('verified', '?')}\n"
            f"[cyan]Layer:[/cyan]       {result.get('layer', '?')}",
            title="[bold]✓ Multi-App done[/bold]",
            border_style="cyan",
        ))

    elif choice == "a":
        all_tasks = [
            ("calculator",   task_calculator.run,   {"expression": "127 * 43 - 58"}),
            ("vscode",       task_vscode.run,        {}),
            ("browser_game", task_browser_game.run,  {"moves": 3}),
            ("notepad",      task_notepad.run,       {}),
            ("email_draft",  task_email_draft.run,   {}),
            ("multiapp",     task_multiapp.run,      {"expression": "157 * 24"}),
        ]
        for name, fn, kwargs in all_tasks:
            console.print(Rule(f"[bold]{name}[/bold]", style="dim"))
            r = _run_task_with_spinner(name, fn, kwargs)
            status = "[green]✓[/green]" if r.get("status") == "ok" else "[red]✗[/red]"
            console.print(f"  {status} {name}: {r}")
        console.print(Rule(style="dim"))
        console.print("[bold green]All six tasks complete.[/bold green]")
        console.print()
        console.print(_recordings_table())

    elif choice == "d":
        launch_dashboard()

    elif choice == "q":
        console.print("[dim]Bye.[/dim]")
        sys.exit(0)

    else:
        console.print("[yellow]Unknown option.[/yellow]")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Desktop Agent — Session 10 Computer-Use"
    )
    parser.add_argument(
        "--task",
        choices=["calculator", "vscode", "browser_game", "notepad", "email_draft", "multiapp", "all"],
        help="Run a specific task directly"
    )
    parser.add_argument("--expression", default="127 * 43 - 58")
    parser.add_argument("--moves", type=int, default=5)
    parser.add_argument("--dashboard", action="store_true",
                        help="Launch web dashboard")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open browser when launching dashboard")
    args = parser.parse_args()

    if args.dashboard:
        launch_dashboard(open_browser=not args.no_browser)

    elif args.task == "calculator":
        r = _run_task_with_spinner("calculator", task_calculator.run,
                                   {"expression": args.expression})
        print(json.dumps(r, indent=2))

    elif args.task == "vscode":
        r = _run_task_with_spinner("vscode", task_vscode.run, {})
        print(json.dumps(r, indent=2))

    elif args.task == "browser_game":
        r = _run_task_with_spinner("browser_game", task_browser_game.run,
                                   {"moves": args.moves})
        print(json.dumps(r, indent=2))

    elif args.task == "notepad":
        r = _run_task_with_spinner("notepad", task_notepad.run, {})
        print(json.dumps(r, indent=2))

    elif args.task == "email_draft":
        r = _run_task_with_spinner("email_draft", task_email_draft.run, {})
        print(json.dumps(r, indent=2))

    elif args.task == "multiapp":
        r = _run_task_with_spinner("multiapp", task_multiapp.run, {"expression": args.expression})
        print(json.dumps(r, indent=2))

    elif args.task == "all":
        for name, fn, kwargs in [
            ("calculator",   task_calculator.run,   {"expression": args.expression}),
            ("vscode",       task_vscode.run,        {}),
            ("browser_game", task_browser_game.run,  {"moves": args.moves}),
            ("notepad",      task_notepad.run,       {}),
            ("email_draft",  task_email_draft.run,   {}),
            ("multiapp",     task_multiapp.run,      {"expression": args.expression}),
        ]:
            r = _run_task_with_spinner(name, fn, kwargs)
            print(f"{name}: {json.dumps(r)}")

    else:
        interactive()
