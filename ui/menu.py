"""Interactive main menu and configuration screens (spec sections 2-8, 21)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from core.engine import TestReport
from core.models import (
    DEFAULT_USER_AGENT,
    MAX_CONCURRENCY,
    LoadConfig,
    Method,
    TargetConfig,
    TestConfig,
    parse_target,
)
from core.models import DEFAULT_RPS, validate_proxy
from export import export_all
from ui.theme import AUTHORIZATION_NOTICE

# Presets (spec section 21): (users, duration, rps, ramp_up)
PROFILES = {
    "1": ("Smoke Test", dict(users=5, duration=30, rps=5, ramp_up=5)),
    "2": ("Light Load", dict(users=25, duration=60, rps=25, ramp_up=10)),
    "3": ("Moderate Load", dict(users=50, duration=120, rps=50, ramp_up=20)),
    "4": ("Heavy Load", dict(users=100, duration=120, rps=100, ramp_up=30)),
}


class MenuState:
    """Holds configuration and the most recent report between menu actions."""

    def __init__(self, results_dir: Path) -> None:
        self.results_dir = results_dir
        self.target: Optional[TargetConfig] = None
        self.load = LoadConfig()
        self.last_report: Optional[TestReport] = None
        self.last_export_stamp: Optional[str] = None

    def config(self) -> Optional[TestConfig]:
        if self.target is None:
            return None
        return TestConfig(target=self.target, load=self.load)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def render_main_menu(console: Console, state: MenuState) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="left")
    items = [
        ("1", "Configure Target"),
        ("2", "Configure Load"),
        ("3", "Configure Test Duration"),
        ("4", "Configure Ramp-Up"),
        ("5", "Configure Request Method"),
        ("6", "Configure Headers"),
        ("7", "Run Load Test"),
        ("8", "Live Traffic Monitor (run + watch)"),
        ("9", "View Last Test Results"),
        ("10", "Export Results"),
        ("0", "Exit"),
    ]
    for key, label in items:
        table.add_row(Text.assemble((f"[{key}] ", "nf.label"), (label, "nf.value")))

    console.print(
        Panel(
            table,
            title="[nf.accent]NIGHTFALL CONTROL[/]",
            border_style="nf.panel",
            padding=(1, 3),
        )
    )
    _render_status_line(console, state)


def _render_status_line(console: Console, state: MenuState) -> None:
    tgt = state.target.url if state.target else "[not set]"
    l = state.load
    summary = Text.assemble(
        ("target: ", "nf.dim"), (tgt, "nf.accent"), ("   ", ""),
        ("users: ", "nf.dim"), (str(l.users), "nf.value"), ("   ", ""),
        ("duration: ", "nf.dim"), (f"{l.duration}s", "nf.value"), ("   ", ""),
        ("ramp: ", "nf.dim"), (f"{l.ramp_up}s", "nf.value"), ("   ", ""),
        ("rps: ", "nf.dim"), (str(l.rps or "unlimited"), "nf.value"), ("   ", ""),
        ("method: ", "nf.dim"), (l.method.value, "nf.value"), ("   ", ""),
        ("proxy: ", "nf.dim"), (_redact_proxy(l.proxy) if l.proxy else "none", "nf.value"),
    )
    console.print(Panel(summary, border_style="nf.dim", padding=(0, 1)))


def _redact_proxy(proxy: str) -> str:
    """Hide any credentials embedded in a proxy URL before display."""
    from urllib.parse import urlparse, urlunparse

    try:
        p = urlparse(proxy)
        if p.username or p.password:
            host = p.hostname or ""
            netloc = f"***@{host}" + (f":{p.port}" if p.port else "")
            return urlunparse((p.scheme, netloc, p.path, "", "", ""))
    except ValueError:
        return "(set)"
    return proxy


# ---------------------------------------------------------------------------
# Configuration screens
# ---------------------------------------------------------------------------
def configure_target(console: Console, state: MenuState) -> None:
    console.print(Panel("[nf.label]CONFIGURE TARGET[/]", border_style="nf.panel"))
    current = state.target.url if state.target else "https://example.com"
    while True:
        raw = Prompt.ask("[nf.accent]Target URL[/]", default=current)
        try:
            target = parse_target(raw)
        except ValueError as exc:
            console.print(f"[nf.bad]Invalid URL:[/] {exc}")
            if not Confirm.ask("Try again?", default=True):
                return
            continue
        state.target = target
        table = Table.grid(padding=(0, 2))
        table.add_column(style="nf.label")
        table.add_column(style="nf.value")
        for label, value in target.summary_lines():
            table.add_row(label, value)
        console.print(Panel(table, title="[nf.accent]TARGET[/]", border_style="nf.panel"))
        _configure_proxy(console, state)
        return


def _configure_proxy(console: Console, state: MenuState) -> None:
    """Optional: route through a single explicit proxy the tester controls."""
    console.print(
        "[nf.dim]Optional: route through a single proxy you supply and are "
        "authorized to use (e.g. your corporate egress). NIGHTFALL never "
        "fetches, harvests or rotates proxies.[/]"
    )
    current = state.load.proxy or ""
    raw = Prompt.ask(
        "[nf.accent]Proxy URL[/] (blank for none)", default=current, show_default=bool(current)
    )
    raw = raw.strip()
    if not raw:
        state.load.proxy = None
        console.print("[nf.dim](no proxy — requests sent directly)[/]")
        return
    try:
        state.load.proxy = validate_proxy(raw)
        console.print(f"[nf.ok]Proxy set:[/] {_redact_proxy(state.load.proxy)}")
    except ValueError as exc:
        console.print(f"[nf.bad]Invalid proxy:[/] {exc}")
        state.load.proxy = None


def configure_load(console: Console, state: MenuState) -> None:
    console.print(Panel("[nf.label]CONFIGURE LOAD[/]", border_style="nf.panel"))
    console.print(
        "[nf.dim]Choose a preset profile, or [5] for custom. Presets are fully "
        "configurable and must only be run against authorized systems.[/]"
    )
    table = Table.grid(padding=(0, 2))
    for key, (name, cfg) in PROFILES.items():
        table.add_row(
            Text(f"[{key}]", style="nf.label"),
            Text(name, style="nf.value"),
            Text(
                f"users={cfg['users']} duration={cfg['duration']}s rps={cfg['rps']}",
                style="nf.dim",
            ),
        )
    table.add_row(Text("[5]", style="nf.label"), Text("Custom", style="nf.value"), Text("", style="nf.dim"))
    console.print(table)

    choice = Prompt.ask("[nf.accent]Profile[/]", choices=["1", "2", "3", "4", "5"], default="5")
    if choice in PROFILES:
        name, cfg = PROFILES[choice]
        state.load.users = cfg["users"]
        state.load.duration = cfg["duration"]
        state.load.rps = cfg["rps"]
        state.load.ramp_up = cfg["ramp_up"]
        console.print(f"[nf.ok]Applied preset:[/] {name}")
    else:
        _configure_custom_load(console, state)

    notes = state.load.clamp()
    for note in notes:
        console.print(f"[nf.warn]{note}[/]")


def _configure_custom_load(console: Console, state: MenuState) -> None:
    l = state.load
    l.users = IntPrompt.ask(
        f"[nf.accent]Concurrent users[/] (max {MAX_CONCURRENCY})", default=l.users
    )
    unlimited = Confirm.ask("Requests per user unlimited (until duration)?", default=True)
    if unlimited:
        l.requests_per_user = 0
    else:
        l.requests_per_user = IntPrompt.ask("[nf.accent]Requests per user[/]", default=l.requests_per_user or 100)
    l.duration = IntPrompt.ask("[nf.accent]Duration (seconds)[/]", default=l.duration)
    l.ramp_up = IntPrompt.ask("[nf.accent]Ramp-up (seconds)[/]", default=l.ramp_up)
    rps_unlimited = Confirm.ask("Unlimited RPS (no rate limit)?", default=(l.rps == 0))
    if rps_unlimited:
        l.rps = 0
    else:
        l.rps = IntPrompt.ask("[nf.accent]RPS limit (aggregate)[/]", default=l.rps or DEFAULT_RPS)
    l.connect_timeout = float(
        IntPrompt.ask("[nf.accent]Connection timeout (seconds)[/]", default=int(l.connect_timeout))
    )
    l.request_timeout = float(
        IntPrompt.ask("[nf.accent]Request timeout (seconds)[/]", default=int(l.request_timeout))
    )


def configure_duration(console: Console, state: MenuState) -> None:
    console.print(Panel("[nf.label]CONFIGURE TEST DURATION[/]", border_style="nf.panel"))
    state.load.duration = IntPrompt.ask("[nf.accent]Duration (seconds)[/]", default=state.load.duration)
    for note in state.load.clamp():
        console.print(f"[nf.warn]{note}[/]")


def configure_ramp_up(console: Console, state: MenuState) -> None:
    console.print(Panel("[nf.label]CONFIGURE RAMP-UP[/]", border_style="nf.panel"))
    console.print(
        "[nf.dim]Ramp-up gradually introduces users so traffic is not all sent at "
        "once. e.g. 100 users over 20s ≈ 25 users at 5s, 50 at 10s, 100 at 20s.[/]"
    )
    state.load.ramp_up = IntPrompt.ask("[nf.accent]Ramp-up (seconds)[/]", default=state.load.ramp_up)
    for note in state.load.clamp():
        console.print(f"[nf.warn]{note}[/]")


def configure_method(console: Console, state: MenuState) -> None:
    console.print(Panel("[nf.label]CONFIGURE REQUEST METHOD[/]", border_style="nf.panel"))
    choice = Prompt.ask(
        "[nf.accent]Method[/]",
        choices=[m.value for m in Method],
        default=state.load.method.value,
    )
    state.load.method = Method.from_str(choice)
    if state.load.method is Method.POST:
        console.print("[nf.dim]Enter a JSON body. Submit an empty line to finish.[/]")
        console.print('[nf.dim]Example: {"test": true}[/]')
        lines: list[str] = []
        while True:
            line = console.input("[nf.accent]> [/]")
            if line == "":
                break
            lines.append(line)
        body = "\n".join(lines).strip()
        if body:
            try:
                json.loads(body)
            except json.JSONDecodeError as exc:
                console.print(f"[nf.warn]Warning: body is not valid JSON ({exc}). Stored as-is.[/]")
            state.load.body = body
            state.load.headers.setdefault("Content-Type", "application/json")
            console.print("[nf.ok]POST body set. Content-Type: application/json[/]")
        else:
            state.load.body = None
            console.print("[nf.dim]No body set.[/]")


def configure_headers(console: Console, state: MenuState) -> None:
    console.print(Panel("[nf.label]CONFIGURE HEADERS[/]", border_style="nf.panel"))
    console.print(
        "[nf.dim]Add optional custom headers as 'Name: Value'. Submit an empty "
        "line to finish. NIGHTFALL does not spoof identities or bypass security.[/]"
    )
    if not state.load.headers:
        if Confirm.ask(f"Add default User-Agent '{DEFAULT_USER_AGENT}'?", default=True):
            state.load.headers["User-Agent"] = DEFAULT_USER_AGENT
    _show_headers(console, state)
    while True:
        line = console.input("[nf.accent]header (Name: Value, blank to finish)> [/]")
        if line.strip() == "":
            break
        if ":" not in line:
            console.print("[nf.bad]Invalid format. Use 'Name: Value'.[/]")
            continue
        name, _, value = line.partition(":")
        name, value = name.strip(), value.strip()
        if not name:
            console.print("[nf.bad]Header name cannot be empty.[/]")
            continue
        state.load.headers[name] = value
        console.print(f"[nf.ok]Set[/] {name}: {value}")
    _show_headers(console, state)


def _show_headers(console: Console, state: MenuState) -> None:
    if not state.load.headers:
        console.print("[nf.dim](no custom headers)[/]")
        return
    table = Table.grid(padding=(0, 2))
    table.add_column(style="nf.label")
    table.add_column(style="nf.value")
    for name, value in state.load.headers.items():
        table.add_row(name, value)
    console.print(Panel(table, title="[nf.accent]HEADERS[/]", border_style="nf.panel"))


# ---------------------------------------------------------------------------
# Authorization confirmation (spec section 3)
# ---------------------------------------------------------------------------
def confirm_authorization(console: Console, config: TestConfig, assume_yes: bool = False) -> bool:
    l = config.load
    body = Text()
    body.append("WARNING\n\n", style="nf.bad")
    body.append(AUTHORIZATION_NOTICE + "\n\n", style="nf.warn")
    body.append("Target:\n", style="nf.label")
    body.append(f"{config.target.url}\n\n", style="nf.value")
    body.append("Maximum concurrent clients:\n", style="nf.label")
    body.append(f"{l.users}\n\n", style="nf.value")
    body.append("Duration:\n", style="nf.label")
    body.append(f"{l.duration} seconds\n\n", style="nf.value")
    body.append("Ramp-up:\n", style="nf.label")
    body.append(f"{l.ramp_up} seconds\n\n", style="nf.value")
    body.append("RPS limit:\n", style="nf.label")
    body.append(f"{l.rps or 'unlimited'}\n\n", style="nf.value")
    if l.proxy:
        body.append("Proxy:\n", style="nf.label")
        body.append(f"{_redact_proxy(l.proxy)}\n\n", style="nf.value")
    body.append("Type:\n", style="nf.label")
    body.append(f"HTTP load test ({l.method.value})\n", style="nf.value")
    console.print(Panel(body, title="[nf.bad]AUTHORIZATION REQUIRED[/]", border_style="nf.bad", padding=(1, 2)))

    if assume_yes:
        console.print("[nf.warn]--yes supplied: authorization affirmed non-interactively.[/]")
        return True

    answer = console.input("[nf.bad]Continue? [Y/N]: [/]").strip().lower()
    return answer == "y"


# ---------------------------------------------------------------------------
# Results display (spec section 19)
# ---------------------------------------------------------------------------
def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:.0f} ms"


def render_report(console: Console, report: TestReport) -> None:
    lat = report.latency
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="nf.label")
    grid.add_column(style="nf.value", justify="right")
    grid.add_row("Target", report.target)
    grid.add_row("Method", report.method)
    grid.add_row("Duration", f"{report.duration_actual:.1f}s (configured {report.duration_configured}s)")
    grid.add_row("Concurrent users", f"{report.configured_users} (peak active {report.peak_active_users})")
    grid.add_row("", "")
    grid.add_row("Total requests", f"{report.total_requests:,}")
    grid.add_row("Successful", f"{report.successful_requests:,}")
    grid.add_row("Failed", f"{report.failed_requests:,}")
    grid.add_row("Success rate", f"{report.success_rate:.2f}%")
    grid.add_row("", "")
    grid.add_row("Avg RPS", f"{report.average_rps:.1f}")
    grid.add_row("Peak RPS", f"{report.peak_requests_per_second:.1f}")
    grid.add_row("", "")
    grid.add_row("P50", _fmt_ms(lat["p50_ms"]))
    grid.add_row("P95", _fmt_ms(lat["p95_ms"]))
    grid.add_row("P99", _fmt_ms(lat["p99_ms"]))
    grid.add_row("Max", _fmt_ms(lat["max_ms"]))
    console.print(Panel(grid, title="[nf.ok]TEST COMPLETE[/]", border_style="nf.ok", padding=(1, 2)))

    if report.observations:
        obs = Text()
        for line in report.observations:
            obs.append(f"• {line}\n", style="nf.value")
        console.print(Panel(obs, title="[nf.accent]OBSERVATIONS[/]", border_style="nf.panel", padding=(1, 2)))


def export_results(console: Console, state: MenuState) -> None:
    if state.last_report is None:
        console.print("[nf.warn]No test results to export yet. Run a test first.[/]")
        return
    paths = export_all(state.last_report, state.results_dir)
    table = Table.grid(padding=(0, 2))
    table.add_column(style="nf.label")
    table.add_column(style="nf.value")
    for fmt, path in paths.items():
        table.add_row(fmt.upper(), str(path))
    console.print(Panel(table, title="[nf.ok]EXPORTED[/]", border_style="nf.ok"))
    console.print(
        "[nf.dim]Exports exclude Authorization headers, cookies and request "
        "bodies. Sensitive data is never written to disk.[/]"
    )
