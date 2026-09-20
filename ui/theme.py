"""Visual theme, banner and shared Rich styling for NIGHTFALL.

A restrained cybersecurity console aesthetic: green/cyan on black, clear
panels, no gimmicks. This should read as a legitimate security tool.

The banner is responsive: the full ASCII art is shown only when the terminal is
wide enough for it, a smaller art is used on medium terminals, and a compact
text logo is used on narrow screens (e.g. Termux on a phone), so it never wraps
into an unreadable mess.
"""
from __future__ import annotations

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

NIGHTFALL_THEME = Theme(
    {
        "nf.brand": "bold bright_green",
        "nf.accent": "bright_cyan",
        "nf.dim": "grey58",
        "nf.ok": "bold green",
        "nf.warn": "bold yellow",
        "nf.bad": "bold red",
        "nf.label": "bold cyan",
        "nf.value": "bright_white",
        "nf.panel": "green",
        "nf.rule": "green",
    }
)

# Full-size ASCII art (needs a wide terminal).
BANNER_FULL = r"""
███╗   ██╗██╗ ██████╗ ██╗  ██╗████████╗ █████╗ ██╗     ██╗
████╗  ██║██║██╔════╝ ██║  ██║╚══██╔══╝██╔══██╗██║     ██║
██╔██╗ ██║██║██║  ███╗███████║   ██║   ███████║██║     ██║
██║╚██╗██║██║██║   ██║██╔══██║   ██║   ██╔══██║██║     ██║
██║ ╚████║██║╚██████╔╝██║  ██║   ██║   ██║  ██║███████╗██║
╚═╝  ╚═══╝╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝
"""

# Medium ASCII art (fits ~40+ column terminals).
BANNER_MEDIUM = r"""
┌┐┌ ┬ ┌─┐ ┬ ┬ ┌┬┐ ┌─┐ ┌─┐ ┬  ┬
│││ │ │ ┬ ├─┤  │  ├┤  ├─┤ │  │
┘└┘ ┴ └─┘ ┴ ┴  ┴  └   ┴ ┴ ┴─┘┴─┘
"""


def _art_width(art: str) -> int:
    return max((len(line) for line in art.splitlines()), default=0)


_FULL_W = _art_width(BANNER_FULL)
_MEDIUM_W = _art_width(BANNER_MEDIUM)


def build_console() -> Console:
    return Console(theme=NIGHTFALL_THEME, highlight=False)


def _banner_renderable(width: int):
    """Pick the largest banner variant that fits the given terminal width."""
    inner = max(width - 6, 8)  # account for panel border + padding
    if inner >= _FULL_W:
        return Text(BANNER_FULL.strip("\n"), style="nf.brand")
    if inner >= _MEDIUM_W:
        return Text(BANNER_MEDIUM.strip("\n"), style="nf.brand")
    # Compact text logo — fits essentially any width.
    if inner >= 17:
        return Text("N I G H T F A L L", style="nf.brand")
    return Text("NIGHTFALL", style="nf.brand")


def startup_panel(console: Console | None = None) -> Panel:
    """Build the startup panel sized to the current terminal width."""
    width = console.width if console is not None else 80
    banner = _banner_renderable(width)
    subtitle = Text("// LOAD TESTER //", style="bold bright_cyan")
    mode = Text("[ AUTHORIZED TESTING MODE ]", style="nf.warn")
    tagline = Text("Legitimate HTTP performance testing console", style="nf.dim")

    parts = [Align.center(banner), Text(""), Align.center(subtitle), Text("")]
    # Drop the tagline on very narrow screens to save vertical space.
    parts.append(Align.center(mode))
    if width >= 46:
        parts.append(Align.center(tagline))

    return Panel(
        Group(*parts),
        border_style="nf.panel",
        title="[nf.accent]NIGHTFALL[/]",
        subtitle="[nf.dim]v1.0[/]",
        padding=(1, 2) if width >= 46 else (0, 1),
    )


AUTHORIZATION_NOTICE = (
    "This tool is intended ONLY for websites that you own or have explicit "
    "written authorization to test. Unauthorized load or stress testing of "
    "systems you do not control may be illegal and can cause real disruption. "
    "By continuing you confirm you are authorized to test the target below."
)
