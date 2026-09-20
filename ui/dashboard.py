"""The live traffic dashboard (spec sections 11-16).

Builds a Rich renderable each frame from a :class:`MetricsCollector`. The
:class:`Dashboard.build` method is pure (no side effects) so it can be driven
by ``rich.live.Live`` at a modest refresh rate without flooding the terminal.
"""
from __future__ import annotations



from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.metrics import MetricsCollector

_BLOCKS = " ▁▂▃▄▅▆▇█"


def _fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    return f"{ms:.0f} ms"


def _fmt_clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _sparkline(values: list[float], width: int = 40) -> str:
    if not values:
        return ""
    data = values[-width:]
    peak = max(data) or 1.0
    out = []
    for v in data:
        idx = int((v / peak) * (len(_BLOCKS) - 1))
        out.append(_BLOCKS[max(0, min(idx, len(_BLOCKS) - 1))])
    return "".join(out)


def _bar_graph(series: list[int], height: int = 8, width: int = 30) -> Text:
    """Vertical bar graph rendered with block characters."""
    text = Text()
    if not series:
        text.append("(collecting data...)", style="nf.dim")
        return text
    data = series[-width:]
    peak = max(data) or 1
    # Round the axis max up to a friendly number.
    axis_max = peak
    for row in range(height, 0, -1):
        threshold = axis_max * row / height
        label = f"{int(threshold):>4} |"
        text.append(label, style="nf.dim")
        for v in data:
            if v >= threshold:
                text.append("█ ", style="nf.accent")
            else:
                text.append("  ")
        text.append("\n")
    text.append("     +" + "-" * (len(data) * 2), style="nf.dim")
    text.append("\n      ", style="nf.dim")
    for i in range(len(data)):
        text.append(f"{(i + 1) % 10} ", style="nf.dim")
    return text


class Dashboard:
    """Renders live metrics for a running test."""

    def __init__(
        self,
        metrics: MetricsCollector,
        target_url: str,
        duration: int,
        console=None,
    ) -> None:
        self.m = metrics
        self.target_url = target_url
        self.duration = duration
        self._console = console

    def _term_width(self) -> int:
        if self._console is not None:
            try:
                return self._console.width
            except Exception:
                pass
        return 80

    def _graph_slots(self) -> int:
        """Number of bars/points a graph should draw for the current width."""
        width = self._term_width()
        # Two-column layout roughly halves the space available to each graph.
        avail = width // 2 if width >= 88 else width
        # Each bar uses 2 cells; leave room for the axis label and borders.
        return max(8, min(30, (avail - 12) // 2))

    # -- individual panels -------------------------------------------------
    def _summary_panel(self, status: str) -> Panel:
        m = self.m
        elapsed = m.elapsed()
        remaining = max(0.0, self.duration - elapsed)
        live = m.live_latency_stats()

        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="right", ratio=1)

        def row(label: str, value: str, style: str = "nf.value") -> None:
            grid.add_row(
                Text(label, style="nf.label"), Text(value, style=style)
            )

        row("ELAPSED", _fmt_clock(elapsed))
        row("REMAINING", _fmt_clock(remaining))
        row("ACTIVE USERS", f"{m.active_users}  (peak {m.peak_active_users})")
        row("TOTAL REQUESTS", f"{m.total:,}")
        row("REQUESTS/SEC", f"{m.current_rps():.1f}  (avg {m.average_rps():.1f})")
        row("SUCCESS", f"{m.success:,}", "nf.ok")
        row("FAILED", f"{m.failed:,}", "nf.bad" if m.failed else "nf.value")
        rate = m.success_rate()
        rate_style = "nf.ok" if rate >= 99 else "nf.warn" if rate >= 90 else "nf.bad"
        row("SUCCESS RATE", f"{rate:.2f}%", rate_style)
        grid.add_row("", "")
        row("AVG LATENCY", _fmt_ms(live.average))
        row("P50 LATENCY", _fmt_ms(live.p50))
        row("P95 LATENCY", _fmt_ms(live.p95))
        row("P99 LATENCY", _fmt_ms(live.p99))
        row("MAX LATENCY", _fmt_ms(live.maximum))

        header = Text.assemble(
            ("TARGET: ", "nf.label"), (self.target_url, "nf.value"), "\n",
            ("STATUS: ", "nf.label"),
            (status, "nf.ok" if status == "RUNNING" else "nf.warn"),
        )
        return Panel(
            Group(header, Text(""), grid),
            title="[nf.accent]NIGHTFALL // LIVE[/]",
            border_style="nf.panel",
            padding=(1, 2),
        )

    def _status_breakdown_panel(self) -> Panel:
        m = self.m
        total = sum(m.status_buckets.values()) or 1
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="left")
        table.add_column(justify="left")
        table.add_column(justify="right")
        palette = {
            "2xx": "nf.ok",
            "3xx": "nf.accent",
            "4xx": "nf.warn",
            "5xx": "nf.bad",
            "other": "nf.dim",
        }
        for bucket in ("2xx", "3xx", "4xx", "5xx"):
            count = m.status_buckets[bucket]
            pct = count / total * 100
            bar = "█" * max(0, int(pct / 4))
            table.add_row(
                Text(f"{bucket}:", style=palette[bucket]),
                Text(bar or "·", style=palette[bucket]),
                Text(f"{pct:5.1f}%  ({count:,})", style="nf.value"),
            )
        return Panel(table, title="[nf.accent]HTTP STATUS[/]", border_style="nf.panel")

    def _rps_graph_panel(self) -> Panel:
        slots = self._graph_slots()
        height = 8 if self._term_width() >= 60 else 5
        series = self.m.rps_series(width=slots)
        return Panel(
            _bar_graph(series, height=height, width=slots),
            title="[nf.accent]REQUESTS / SEC[/]",
            border_style="nf.panel",
        )

    def _latency_graph_panel(self) -> Panel:
        window = self.m.latency_window()
        spark_width = max(12, min(64, self._graph_slots() * 2))
        spark = _sparkline(window, width=spark_width)
        live = self.m.live_latency_stats()
        body = Text()
        body.append(spark or "(collecting data...)", style="nf.accent")
        body.append("\n\n")
        body.append(
            f"min {_fmt_ms(live.minimum)}   p50 {_fmt_ms(live.p50)}   "
            f"p95 {_fmt_ms(live.p95)}   max {_fmt_ms(live.maximum)}",
            style="nf.dim",
        )
        return Panel(body, title="[nf.accent]LATENCY (rolling)[/]", border_style="nf.panel")

    def _errors_panel(self) -> Panel:
        m = self.m
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left")
        table.add_column(justify="right")
        if not m.errors:
            table.add_row(Text("No errors recorded", style="nf.ok"), Text(""))
        else:
            for name, count in sorted(m.errors.items(), key=lambda kv: kv[1], reverse=True):
                table.add_row(Text(name, style="nf.warn"), Text(f"{count:,}", style="nf.bad"))
        return Panel(table, title="[nf.accent]ERROR MONITOR[/]", border_style="nf.panel")

    def _events_panel(self) -> Panel:
        m = self.m
        table = Table.grid(padding=(0, 1))
        for col in range(5):
            table.add_column(justify="left")
        if not m.recent_events:
            table.add_row(Text("(waiting for traffic...)", style="nf.dim"))
        else:
            for ev in list(m.recent_events)[-10:]:
                ok_style = "nf.ok" if ev.ok else "nf.bad"
                status = str(ev.status) if ev.status else "ERR"
                table.add_row(
                    Text(f"USER-{ev.user_id:03d}", style="nf.dim"),
                    Text(ev.method, style="nf.accent"),
                    Text(ev.path, style="nf.value"),
                    Text(status, style=ok_style),
                    Text(_fmt_ms(ev.latency_ms), style="nf.value"),
                )
        return Panel(table, title="[nf.accent]RECENT ACTIVITY[/]", border_style="nf.panel")

    def _controls_panel(self, paused: bool) -> Panel:
        state = "PAUSED" if paused else "RUNNING"
        controls = Text.assemble(
            ("[P]", "nf.label"), (" Pause   ", "nf.dim"),
            ("[R]", "nf.label"), (" Resume   ", "nf.dim"),
            ("[S]", "nf.label"), (" Stop   ", "nf.dim"),
            ("[D]", "nf.label"), (" Dashboard   ", "nf.dim"),
            ("  state: ", "nf.dim"),
            (state, "nf.warn" if paused else "nf.ok"),
        )
        return Panel(controls, border_style="nf.dim", padding=(0, 1))

    # -- top-level assembly ------------------------------------------------
    def build(self, status: str = "RUNNING", paused: bool = False) -> Group:
        summary = self._summary_panel(status)
        events = self._events_panel()
        rps = self._rps_graph_panel()
        latency = self._latency_graph_panel()
        codes = self._status_breakdown_panel()
        errors = self._errors_panel()
        controls = self._controls_panel(paused)

        # Two side-by-side columns need room; otherwise stack everything in a
        # single column so nothing is truncated on narrow screens (e.g. Termux).
        # Table.grid reliably places two column groups side by side (Columns
        # leaves the second group blank for large renderables).
        if self._term_width() >= 88:
            left = Group(summary, events)
            right = Group(rps, latency, codes, errors)
            grid = Table.grid(expand=True, padding=(0, 1))
            grid.add_column(ratio=1)
            grid.add_column(ratio=1)
            grid.add_row(left, right)
            body: object = grid
        else:
            body = Group(summary, rps, latency, codes, errors, events)
        return Group(body, controls)
