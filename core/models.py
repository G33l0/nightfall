"""Data models and configuration objects for NIGHTFALL.

All configuration and result structures live here as dataclasses so the
engine, UI and export layers share a single, typed source of truth.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse, urlunparse

# ---------------------------------------------------------------------------
# Application-level safety limits (see spec sections 6 and 29).
# ---------------------------------------------------------------------------
MAX_CONCURRENCY: int = 999999          # hard ceiling on simulated users
MAX_DURATION: int = 7 * 24 * 60 * 60    # 24h/7days ceiling to avoid runaway tests

# Conservative defaults (spec section 6).
DEFAULT_USERS: int = 1000
DEFAULT_DURATION: int = 30000
DEFAULT_RAMP_UP: int = 1000
DEFAULT_RPS: int = 1000
DEFAULT_CONNECT_TIMEOUT: float = 10.0
DEFAULT_REQUEST_TIMEOUT: float = 30.0

DEFAULT_USER_AGENT: str = "ALIEN-NIGHTFALL-LOADTEST/1.0"


class Method(str, Enum):
    """Supported HTTP request methods."""

    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"

    @classmethod
    def from_str(cls, value: str) -> "Method":
        try:
            return cls(value.strip().upper())
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(
                f"Unsupported method '{value}'. Choose one of: "
                + ", ".join(m.value for m in cls)
            ) from exc


class ErrorKind(str, Enum):
    """Normalised categories for request-level failures."""

    CONNECT_TIMEOUT = "Connection timeout"
    READ_TIMEOUT = "Read timeout"
    DNS_FAILURE = "DNS failure"
    CONNECTION_REFUSED = "Connection refused"
    CONNECTION_RESET = "Connection reset"
    SSL_ERROR = "SSL error"
    SERVER_DISCONNECTED = "Server disconnected"
    CLIENT_ERROR = "Client error (4xx)"
    SERVER_ERROR = "Server error (5xx)"
    OTHER = "Other error"


@dataclass(slots=True)
class TargetConfig:
    """A validated HTTP(S) target."""

    url: str
    scheme: str
    host: str
    port: int
    path: str

    @property
    def display_url(self) -> str:
        return self.url

    def summary_lines(self) -> list[tuple[str, str]]:
        return [
            ("Protocol", self.scheme.upper()),
            ("Host", self.host),
            ("Port", str(self.port)),
            ("Path", self.path or "/"),
        ]


@dataclass(slots=True)
class LoadConfig:
    """Everything that shapes traffic generation."""

    users: int = DEFAULT_USERS
    duration: int = DEFAULT_DURATION
    ramp_up: int = DEFAULT_RAMP_UP
    rps: int = DEFAULT_RPS                    # 0 == unlimited
    requests_per_user: int = 0               # 0 == unlimited (until duration)
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    method: Method = Method.GET
    body: Optional[str] = None               # JSON string for POST
    headers: dict[str, str] = field(default_factory=dict)

    def clamp(self) -> list[str]:
        """Enforce safety limits, returning a list of human-readable notes."""
        notes: list[str] = []
        if self.users < 1:
            self.users = 1
            notes.append("Concurrent users raised to the minimum of 1.")
        if self.users > MAX_CONCURRENCY:
            notes.append(
                f"Concurrent users reduced to the safety maximum of {MAX_CONCURRENCY}."
            )
            self.users = MAX_CONCURRENCY
        if self.duration < 1:
            self.duration = 1
            notes.append("Duration raised to the minimum of 1 second.")
        if self.duration > MAX_DURATION:
            self.duration = MAX_DURATION
            notes.append(f"Duration capped at {MAX_DURATION} seconds.")
        if self.ramp_up < 0:
            self.ramp_up = 0
            notes.append("Ramp-up cannot be negative; set to 0.")
        if self.ramp_up > self.duration:
            self.ramp_up = self.duration
            notes.append("Ramp-up capped at the test duration.")
        if self.rps < 0:
            self.rps = 0
            notes.append("RPS limit cannot be negative; set to 0 (unlimited).")
        if self.requests_per_user < 0:
            self.requests_per_user = 0
        return notes


@dataclass(slots=True)
class TestConfig:
    """The full description of a single load test."""

    target: TargetConfig
    load: LoadConfig


@dataclass(slots=True)
class RequestResult:
    """The outcome of a single HTTP request."""

    timestamp: float
    status: int                 # HTTP status, or 0 when the request failed
    latency_ms: float
    bytes_received: int
    success: bool
    error: Optional[ErrorKind] = None
    exception_name: Optional[str] = None


# ---------------------------------------------------------------------------
# URL validation / parsing (spec section 4).
# ---------------------------------------------------------------------------
_DEFAULT_PORTS = {"http": 80, "https": 443}


def parse_target(raw: str) -> TargetConfig:
    """Validate and normalise a target URL.

    Raises ValueError with a clear message when the URL is malformed or uses
    an unsupported scheme. Localhost / IP / port targets are permitted (they
    are common and legitimate for testing systems you own).
    """
    if not raw or not raw.strip():
        raise ValueError("Target URL cannot be empty.")

    candidate = raw.strip()
    if "://" not in candidate:
        # Be forgiving: assume https for bare hosts.
        candidate = "https://" + candidate

    parsed = urlparse(candidate)

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(
            f"Unsupported scheme '{parsed.scheme}'. Only http and https are allowed."
        )

    host = parsed.hostname
    if not host:
        raise ValueError("Could not determine a hostname from the URL.")

    try:
        port = parsed.port if parsed.port is not None else _DEFAULT_PORTS[scheme]
    except ValueError as exc:
        raise ValueError("Invalid port number in URL.") from exc

    if not (0 < port < 65536):
        raise ValueError(f"Port {port} is out of the valid range (1-65535).")

    path = parsed.path or "/"
    normalised = urlunparse(
        (scheme, parsed.netloc, path, parsed.params, parsed.query, "")
    )

    return TargetConfig(
        url=normalised,
        scheme=scheme,
        host=host,
        port=port,
        path=path,
    )
