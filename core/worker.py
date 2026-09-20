"""A single simulated user (worker coroutine).

Each worker: waits for its ramp-up delay, then repeatedly issues requests
(subject to the shared rate limiter and concurrency semaphore), records the
outcome of each request, honours pause/resume/stop control flags, and exits
cleanly when the test duration expires or a stop is requested.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import aiohttp

from .limiter import RateLimiter
from .metrics import MetricsCollector
from .models import ErrorKind, LoadConfig, RequestResult, TargetConfig


def classify_exception(exc: BaseException) -> tuple[ErrorKind, str]:
    """Map an aiohttp/OS exception onto a normalised :class:`ErrorKind`."""
    name = type(exc).__name__

    if isinstance(exc, asyncio.TimeoutError):
        return ErrorKind.READ_TIMEOUT, name
    if isinstance(exc, aiohttp.ServerTimeoutError):
        return ErrorKind.READ_TIMEOUT, name
    if isinstance(exc, aiohttp.ServerDisconnectedError):
        return ErrorKind.SERVER_DISCONNECTED, name
    if isinstance(exc, aiohttp.ClientConnectorCertificateError):
        return ErrorKind.SSL_ERROR, name
    if isinstance(exc, aiohttp.ClientConnectorSSLError):
        return ErrorKind.SSL_ERROR, name

    # Proxy-specific failures (a proxy is configured but unreachable / erroring).
    if isinstance(exc, getattr(aiohttp, "ClientProxyConnectionError", ())):
        return ErrorKind.CONNECTION_REFUSED, name
    if isinstance(exc, getattr(aiohttp, "ClientHttpProxyError", ())):
        return ErrorKind.OTHER, name

    # DNS failures surface as ClientConnectorError wrapping a gaierror.
    if isinstance(exc, aiohttp.ClientConnectorError):
        os_err = getattr(exc, "os_error", None)
        os_name = type(os_err).__name__ if os_err else ""
        errno = getattr(os_err, "errno", None)
        if os_name == "gaierror":
            return ErrorKind.DNS_FAILURE, name
        if errno == 111:  # ECONNREFUSED
            return ErrorKind.CONNECTION_REFUSED, name
        if errno == 104:  # ECONNRESET
            return ErrorKind.CONNECTION_RESET, name
        return ErrorKind.CONNECTION_REFUSED, name

    import ssl
    if isinstance(exc, ssl.SSLError):
        return ErrorKind.SSL_ERROR, name

    if isinstance(exc, aiohttp.ClientOSError):
        errno = getattr(exc, "errno", None)
        if errno == 104:
            return ErrorKind.CONNECTION_RESET, name
        if errno == 111:
            return ErrorKind.CONNECTION_REFUSED, name
        return ErrorKind.CONNECTION_RESET, name

    if isinstance(exc, aiohttp.ClientPayloadError):
        return ErrorKind.CONNECTION_RESET, name

    return ErrorKind.OTHER, name


class Control:
    """Shared, awaitable control state for pause / resume / stop."""

    def __init__(self) -> None:
        self._resume = asyncio.Event()
        self._resume.set()
        self.stopped = False
        self.paused = False

    def pause(self) -> None:
        self.paused = True
        self._resume.clear()

    def resume(self) -> None:
        self.paused = False
        self._resume.set()

    def stop(self) -> None:
        self.stopped = True
        self._resume.set()  # unblock anyone waiting so they can exit

    async def wait_if_paused(self) -> None:
        if not self._resume.is_set():
            await self._resume.wait()


class Worker:
    """One simulated user."""

    def __init__(
        self,
        user_id: int,
        session: aiohttp.ClientSession,
        target: TargetConfig,
        load: LoadConfig,
        limiter: RateLimiter,
        semaphore: asyncio.Semaphore,
        metrics: MetricsCollector,
        control: Control,
        deadline: float,
        ramp_delay: float,
    ) -> None:
        self.user_id = user_id
        self._session = session
        self._target = target
        self._load = load
        self._limiter = limiter
        self._semaphore = semaphore
        self._metrics = metrics
        self._control = control
        self._deadline = deadline
        self._ramp_delay = ramp_delay
        self._started = False

    async def run(self) -> None:
        # Staggered ramp-up: wait for this worker's slice, but never past the
        # deadline and always responsive to an early stop.
        try:
            await self._sleep_until(min(time.monotonic() + self._ramp_delay, self._deadline))
        except asyncio.CancelledError:
            return

        if self._control.stopped or time.monotonic() >= self._deadline:
            return

        self._metrics.user_started()
        self._started = True
        sent = 0
        try:
            while not self._control.stopped and time.monotonic() < self._deadline:
                await self._control.wait_if_paused()
                if self._control.stopped or time.monotonic() >= self._deadline:
                    break

                limit = self._load.requests_per_user
                if limit and sent >= limit:
                    # This user has done its share; idle until the test ends.
                    await self._sleep_until(self._deadline)
                    break

                await self._limiter.acquire()
                if self._control.stopped or time.monotonic() >= self._deadline:
                    break

                await self._do_request()
                sent += 1
        except asyncio.CancelledError:
            raise
        finally:
            if self._started:
                self._metrics.user_finished()

    async def _sleep_until(self, when: float) -> None:
        remaining = when - time.monotonic()
        while remaining > 0 and not self._control.stopped:
            await asyncio.sleep(min(remaining, 0.25))
            remaining = when - time.monotonic()

    async def _do_request(self) -> None:
        method = self._load.method.value
        data: Optional[bytes] = None
        if method == "POST" and self._load.body is not None:
            data = self._load.body.encode("utf-8")

        start = time.perf_counter()
        result: RequestResult
        try:
            async with self._semaphore:
                async with self._session.request(
                    method,
                    self._target.url,
                    data=data,
                    headers=self._load.headers or None,
                    proxy=self._load.proxy,
                ) as resp:
                    # Drain the body so latency reflects a full response, but do
                    # not retain it (we never store response bodies — spec 14).
                    body = await resp.read()
                    latency = (time.perf_counter() - start) * 1000.0
                    status = resp.status
                    error: Optional[ErrorKind] = None
                    success = 200 <= status < 400
                    if 400 <= status < 500:
                        error = ErrorKind.CLIENT_ERROR
                    elif status >= 500:
                        error = ErrorKind.SERVER_ERROR
                    result = RequestResult(
                        timestamp=time.time(),
                        status=status,
                        latency_ms=latency,
                        bytes_received=len(body),
                        success=success,
                        error=error,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - we normalise every failure
            latency = (time.perf_counter() - start) * 1000.0
            kind, name = classify_exception(exc)
            result = RequestResult(
                timestamp=time.time(),
                status=0,
                latency_ms=latency,
                bytes_received=0,
                success=False,
                error=kind,
                exception_name=name,
            )

        self._metrics.record(self.user_id, result)
