"""Cross-platform, non-blocking single-key reader for live test controls.

Works on Linux / macOS / Termux (termios + a background thread) and Windows
(msvcrt). When stdin is not an interactive TTY (e.g. CI, piped input) the
listener degrades gracefully to a no-op so automated runs never block.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from typing import Optional

IS_WINDOWS = sys.platform.startswith("win")


class KeyboardListener:
    """Reads single keypresses on a background thread into an asyncio queue."""

    def __init__(self) -> None:
        self._queue: "asyncio.Queue[str]" = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.enabled = sys.stdin is not None and sys.stdin.isatty()

    def start(self) -> None:
        if not self.enabled:
            return
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    async def get(self, timeout: float) -> Optional[str]:
        if not self.enabled:
            await asyncio.sleep(timeout)
            return None
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def _emit(self, ch: str) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, ch)

    def _reader(self) -> None:
        if IS_WINDOWS:
            self._reader_windows()
        else:
            self._reader_posix()

    def _reader_windows(self) -> None:  # pragma: no cover - windows only
        import msvcrt
        import time

        while not self._stop.is_set():
            if msvcrt.kbhit():
                try:
                    ch = msvcrt.getwch()
                except Exception:
                    break
                if ch:
                    self._emit(ch)
            else:
                time.sleep(0.03)

    def _reader_posix(self) -> None:
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        try:
            old = termios.tcgetattr(fd)
        except Exception:
            return
        try:
            tty.setcbreak(fd)
            while not self._stop.is_set():
                r, _, _ = select.select([fd], [], [], 0.1)
                if r:
                    try:
                        ch = sys.stdin.read(1)
                    except Exception:
                        break
                    if ch:
                        self._emit(ch)
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass
