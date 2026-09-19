"""Visual theme, banner and shared Rich styling for NIGHTFALL.

A restrained cybersecurity console aesthetic: green/cyan on black, clear
panels, no gimmicks. This should read as a legitimate security tool.
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

BANNER = r"""
    ███╗   ██╗██╗ ██████╗ ██╗  ██╗████████╗ █████╗ ██╗     ██╗
    ████╗  ██║██║██╔════╝ ██║  ██║╚══██╔══╝██╔══██╗██║     ██║
    ██╔██╗ ██║██║██║  ███╗███████║   ██║   ███████║██║     ██║
    ██║╚██╗██║██║██║   ██║██╔══██║   ██║   ██╔══██║██║     ██║
    ██║ ╚████║██║╚██████╔╝██║  ██║   ██║   ██║  ██║███████╗██║
    ╚═╝  ╚═══╝╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝
"""


def build_console() -> Console:
    return Console(theme=NIGHTFALL_THEME, highlight=False)


def startup_panel() -> Panel:
    banner = Text(BANNER, style="nf.brand")
    subtitle = Text("LOAD TESTER", style="bold bright_cyan")
    mode = Text("[ AUTHORIZED TESTING MODE ]", style="nf.warn")
    tagline = Text(
        "Legitimate HTTP performance testing console", style="nf.dim"
    )
    group = Group(
        Align.center(banner),
        Align.center(subtitle),
        Text(""),
        Align.center(mode),
        Align.center(tagline),
    )
    return Panel(
        group,
        border_style="nf.panel",
        title="[nf.accent]NIGHTFALL[/]",
        subtitle="[nf.dim]v1.0[/]",
        padding=(1, 2),
    )


AUTHORIZATION_NOTICE = (
    "This tool is intended ONLY for websites that you own or have explicit "
    "written authorization to test. Unauthorized load or stress testing of "
    "systems you do not control may be illegal and can cause real disruption. "
    "By continuing you confirm you are authorized to test the target below."
)
