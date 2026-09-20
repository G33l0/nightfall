#!/usr/bin/env python3
"""NIGHTFALL // LOAD TESTER — entrypoint.

A terminal-based HTTP load / stress testing console for AUTHORIZED targets.

Only test systems that you own or have explicit written authorization to test.
This tool performs legitimate performance testing only. It does NOT implement
IP spoofing, proxy rotation, botnets, credential attacks, CAPTCHA/WAF/rate-limit
bypass, stealth/evasion, or any distributed-attack functionality.

Usage:
    python nightfall.py                       # interactive mode (default)
    python nightfall.py --url https://you.example.com --users 20 --duration 30
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from core.models import (
    LoadConfig,
    Method,
    TestConfig,
    parse_target,
    validate_proxy,
)
from ui import menu
from ui.runner import run_test
from ui.theme import build_console, startup_panel

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nightfall.py",
        description="NIGHTFALL // LOAD TESTER — authorized HTTP load testing console.",
        epilog="Only test systems you own or are explicitly authorized to test.",
    )
    p.add_argument("--url", help="Target URL. If omitted, interactive mode starts.")
    p.add_argument("--users", type=int, help="Concurrent simulated users.")
    p.add_argument("--duration", type=int, help="Test duration in seconds.")
    p.add_argument("--ramp-up", type=int, dest="ramp_up", help="Ramp-up period in seconds.")
    p.add_argument("--rps", type=int, help="Aggregate requests/sec limit (0 = unlimited).")
    p.add_argument("--method", choices=[m.value for m in Method], help="HTTP method.")
    p.add_argument("--body", help="Request body for POST (JSON string).")
    p.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME:VALUE",
        help="Custom header (repeatable).",
    )
    p.add_argument("--timeout", type=float, help="Request timeout in seconds.")
    p.add_argument(
        "--connect-timeout", type=float, dest="connect_timeout",
        help="Connection timeout in seconds.",
    )
    p.add_argument(
        "--proxy",
        metavar="URL",
        help=(
            "Route requests through a single explicit forward proxy you supply "
            "and are authorized to use (e.g. http://user:pass@host:port). "
            "NIGHTFALL never fetches, harvests or rotates proxies."
        ),
    )
    p.add_argument("--requests-per-user", type=int, dest="requests_per_user",
                   help="Requests per user (0 = unlimited).")
    p.add_argument(
        "--merge",
        nargs="+",
        metavar="REPORT.json",
        help=(
            "Horizontal scale: merge JSON reports from independent NIGHTFALL "
            "runs on hosts you own into one aggregate summary. No test is run. "
            "Combine with --export to write the merged report."
        ),
    )
    p.add_argument(
        "--export",
        nargs="?",
        const="all",
        choices=["all", "json", "csv", "txt"],
        help="Export results after the run (default: all).",
    )
    p.add_argument(
        "--yes", "-y", action="store_true",
        help="Affirm authorization non-interactively (skips the Y/N prompt).",
    )
    p.add_argument(
        "--no-live", action="store_true",
        help="Disable the live dashboard (useful for logs/CI).",
    )
    return p


def _load_from_args(args: argparse.Namespace) -> LoadConfig:
    load = LoadConfig()
    if args.users is not None:
        load.users = args.users
    if args.duration is not None:
        load.duration = args.duration
    if args.ramp_up is not None:
        load.ramp_up = args.ramp_up
    if args.rps is not None:
        load.rps = args.rps
    if args.requests_per_user is not None:
        load.requests_per_user = args.requests_per_user
    if args.method is not None:
        load.method = Method.from_str(args.method)
    if args.body is not None:
        load.body = args.body
        load.method = Method.POST if args.method is None else load.method
        load.headers.setdefault("Content-Type", "application/json")
    if args.timeout is not None:
        load.request_timeout = args.timeout
    if args.connect_timeout is not None:
        load.connect_timeout = args.connect_timeout
    for raw in args.header:
        if ":" in raw:
            name, _, value = raw.partition(":")
            load.headers[name.strip()] = value.strip()
    if getattr(args, "proxy", None):
        load.proxy = validate_proxy(args.proxy)
    return load


def _do_export(console, report, results_dir: Path, which: str) -> None:
    from export import export_csv, export_json, export_text
    from datetime import datetime

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    results_dir.mkdir(parents=True, exist_ok=True)
    base = results_dir / f"test_{stamp}"
    written: list[Path] = []
    if which in ("all", "json"):
        written.append(export_json(report, base.with_suffix(".json")))
    if which in ("all", "csv"):
        written.append(export_csv(report, base.with_suffix(".csv")))
    if which in ("all", "txt"):
        written.append(export_text(report, base.with_suffix(".txt")))
    for path in written:
        console.print(f"[nf.ok]Exported:[/] {path}")


async def run_cli(args: argparse.Namespace) -> int:
    console = build_console()
    console.print(startup_panel())

    try:
        target = parse_target(args.url)
    except ValueError as exc:
        console.print(f"[nf.bad]Invalid target URL:[/] {exc}")
        return 2

    try:
        load = _load_from_args(args)
    except ValueError as exc:
        console.print(f"[nf.bad]Invalid argument:[/] {exc}")
        return 2
    notes = load.clamp()
    for note in notes:
        console.print(f"[nf.warn]{note}[/]")

    config = TestConfig(target=target, load=load)

    if not menu.confirm_authorization(console, config, assume_yes=args.yes):
        console.print("[nf.warn]Authorization not confirmed. Aborting.[/]")
        return 1

    interactive = not args.no_live and sys.stdout.isatty()
    report = await run_test(config, console, interactive=interactive)
    menu.render_report(console, report)

    if args.export:
        _do_export(console, report, RESULTS_DIR, args.export)
    return 0


async def run_interactive() -> int:
    console = build_console()
    console.print(startup_panel())
    console.print(
        "[nf.warn]AUTHORIZED TESTING ONLY — only test systems you own or are "
        "explicitly authorized to test.[/]\n"
    )
    state = menu.MenuState(RESULTS_DIR)

    actions = {
        "1": menu.configure_target,
        "2": menu.configure_load,
        "3": menu.configure_duration,
        "4": menu.configure_ramp_up,
        "5": menu.configure_method,
        "6": menu.configure_headers,
    }

    while True:
        console.print()
        menu.render_main_menu(console, state)
        choice = console.input("[nf.accent]nightfall> [/]").strip()

        if choice == "0":
            console.print("[nf.dim]Exiting NIGHTFALL. Stay authorized.[/]")
            return 0
        if choice in actions:
            actions[choice](console, state)
        elif choice in ("7", "8"):
            await _menu_run_test(console, state, watch=(choice == "8"))
        elif choice == "9":
            if state.last_report is None:
                console.print("[nf.warn]No results yet. Run a test first.[/]")
            else:
                menu.render_report(console, state.last_report)
        elif choice == "10":
            menu.export_results(console, state)
        else:
            console.print("[nf.bad]Unknown option.[/]")


async def _menu_run_test(console, state: menu.MenuState, watch: bool) -> None:
    config = state.config()
    if config is None:
        console.print("[nf.warn]Set a target first (option 1).[/]")
        return
    for note in config.load.clamp():
        console.print(f"[nf.warn]{note}[/]")
    if not menu.confirm_authorization(console, config):
        console.print("[nf.warn]Authorization not confirmed. Test cancelled.[/]")
        return
    console.print("[nf.dim]Controls during test: [P]ause  [R]esume  [S]top[/]")
    report = await run_test(config, console, interactive=True)
    state.last_report = report
    menu.render_report(console, report)
    from rich.prompt import Confirm
    if Confirm.ask("Export results now?", default=False):
        menu.export_results(console, state)


def run_merge(args: argparse.Namespace) -> int:
    """Merge JSON reports from multiple nodes into one aggregate summary."""
    import json as _json
    from datetime import datetime

    from rich.panel import Panel
    from rich.table import Table

    from export.merge import load_reports, merge_reports

    console = build_console()
    console.print(startup_panel())

    paths = [Path(p) for p in args.merge]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        console.print(f"[nf.bad]Report file(s) not found:[/] {', '.join(missing)}")
        return 2
    try:
        reports = load_reports(paths)
        merged = merge_reports(reports)
    except (ValueError, _json.JSONDecodeError) as exc:
        console.print(f"[nf.bad]Could not merge reports:[/] {exc}")
        return 2

    lat = merged["latency"]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="nf.label")
    grid.add_column(style="nf.value", justify="right")
    grid.add_row("Nodes merged", str(merged["node_count"]))
    grid.add_row("Target(s)", ", ".join(merged["targets"]))
    grid.add_row("Configured users (sum)", f"{merged['configured_users_total']:,}")
    grid.add_row("Peak active users (sum)", f"{merged['peak_active_users_total']:,}")
    grid.add_row("", "")
    grid.add_row("Total requests", f"{merged['total_requests']:,}")
    grid.add_row("Successful", f"{merged['successful_requests']:,}")
    grid.add_row("Failed", f"{merged['failed_requests']:,}")
    grid.add_row("Success rate", f"{merged['success_rate']:.2f}%")
    grid.add_row("", "")
    grid.add_row("Aggregate avg RPS", f"{merged['aggregate_average_rps']:.1f}")
    grid.add_row("Peak RPS (sum, approx)", f"{merged['peak_requests_per_second_sum']:.1f}")
    grid.add_row("", "")
    grid.add_row("P50 (approx)", f"{lat['p50_ms']:.0f} ms")
    grid.add_row("P95 (approx)", f"{lat['p95_ms']:.0f} ms")
    grid.add_row("P99 (approx)", f"{lat['p99_ms']:.0f} ms")
    grid.add_row("Max", f"{lat['max_ms']:.0f} ms")
    console.print(Panel(grid, title="[nf.ok]MERGED REPORT (horizontal scale)[/]", border_style="nf.ok", padding=(1, 2)))

    obs = "\n".join(f"• {o}" for o in merged["observations"])
    console.print(Panel(obs, title="[nf.accent]OBSERVATIONS[/]", border_style="nf.panel", padding=(1, 2)))

    if args.export:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"merged_{stamp}.json"
        with out.open("w", encoding="utf-8") as fh:
            _json.dump(merged, fh, indent=2, ensure_ascii=False)
        console.print(f"[nf.ok]Merged report written:[/] {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.merge:
            return run_merge(args)
        if args.url:
            return asyncio.run(run_cli(args))
        return asyncio.run(run_interactive())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
