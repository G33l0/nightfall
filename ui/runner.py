"""Drives a single test run: engine + live dashboard + keyboard controls.

Used by both interactive and CLI modes. Handles pause/resume/stop keys and
SIGINT for graceful shutdown, and refreshes the dashboard 4-10x/sec.
"""
from __future__ import annotations

import asyncio
import signal
from typing import Optional

from rich.console import Console
from rich.live import Live

from core.engine import LoadTestEngine, TestReport
from core.models import TestConfig
from ui.dashboard import Dashboard
from ui.keyboard import KeyboardListener

REFRESH_HZ = 8  # frames per second (within the 4-10 range from spec 11)


async def run_test(
    config: TestConfig,
    console: Console,
    interactive: bool = True,
) -> TestReport:
    """Execute a load test, rendering the live dashboard, and return its report."""
    engine = LoadTestEngine(config)
    dashboard = Dashboard(
        engine.metrics, config.target.url, config.load.duration, console=console
    )
    keys = KeyboardListener()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        engine.stop()
        stop_event.set()

    # Graceful Ctrl-C -> stop the test rather than kill the process.
    installed_signals: list[int] = []
    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _request_stop)
            installed_signals.append(sig)
        except (NotImplementedError, ValueError):  # pragma: no cover - windows
            pass

    keys.start()

    async def input_pump() -> None:
        """Poll for control keys while the test runs."""
        while not engine.finished and not stop_event.is_set():
            ch = await keys.get(timeout=0.1)
            if ch is None:
                continue
            c = ch.lower()
            if c == "p":
                engine.pause()
            elif c == "r":
                engine.resume()
            elif c in ("s", "\x03", "q"):  # stop / Ctrl-C / quit
                _request_stop()
                return

    live: Optional[Live] = None
    if interactive:
        live = Live(
            dashboard.build(status="STARTING"),
            console=console,
            refresh_per_second=REFRESH_HZ,
            screen=False,
            transient=False,
        )

    async def on_tick() -> None:
        if live is not None:
            status = "PAUSED" if engine.is_paused else "RUNNING"
            live.update(dashboard.build(status=status, paused=engine.is_paused))

    pump_task = asyncio.create_task(input_pump())
    try:
        if live is not None:
            with live:
                report = await engine.run(on_tick=on_tick)
                live.update(dashboard.build(status="COMPLETE", paused=False))
        else:
            report = await engine.run(on_tick=None)
    finally:
        keys.stop()
        pump_task.cancel()
        try:
            await pump_task
        except (asyncio.CancelledError, Exception):
            pass
        for sig in installed_signals:
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, ValueError):
                pass

    return report
