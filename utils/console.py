"""Terminal output helpers.

The pipeline is demonstrated via an unedited screen recording, so output needs
to be readable at a glance: clear step headers, one obvious symbol per line,
and a final verdict that cannot be misread.

Colour is disabled automatically when stdout is not a TTY, or when NO_COLOR is
set (https://no-color.org/).
"""

from __future__ import annotations

import os
import sys

_COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")

_RESET = "\033[0m" if _COLOR else ""
_BOLD = "\033[1m" if _COLOR else ""
_DIM = "\033[2m" if _COLOR else ""
_GREEN = "\033[32m" if _COLOR else ""
_RED = "\033[31m" if _COLOR else ""
_YELLOW = "\033[33m" if _COLOR else ""
_CYAN = "\033[36m" if _COLOR else ""

WIDTH = 62


def banner(title: str, subtitle: str = "") -> None:
    line = "=" * WIDTH
    print(f"\n{_BOLD}{_CYAN}{line}{_RESET}")
    print(f"{_BOLD}{_CYAN}   {title}{_RESET}")
    if subtitle:
        print(f"{_BOLD}{_CYAN}   {subtitle}{_RESET}")
    print(f"{_BOLD}{_CYAN}{line}{_RESET}")


def step(index: int, total: int, title: str) -> None:
    print(f"\n{_BOLD}[{index}/{total}] {title}{_RESET}")


def ok(message: str) -> None:
    print(f"  {_GREEN}✓{_RESET} {message}")


def fail(message: str) -> None:
    print(f"  {_RED}✗{_RESET} {message}")


def warn(message: str) -> None:
    print(f"  {_YELLOW}!{_RESET} {message}")


def info(message: str) -> None:
    print(f"  {_DIM}·{_RESET} {message}")


def working(message: str) -> None:
    print(f"  {_CYAN}⟳{_RESET} {message}")


def detail(label: str, value: str) -> None:
    print(f"    {_DIM}{label:<18}{_RESET} {value}")


def hash_block(label: str, digest: str) -> None:
    print(f"    {_DIM}{label}{_RESET}")
    print(f"    {_BOLD}{digest}{_RESET}")


def verdict(passed: bool, text: str) -> None:
    colour = _GREEN if passed else _RED
    line = "=" * WIDTH
    print(f"\n{_BOLD}{colour}{line}{_RESET}")
    print(f"{_BOLD}{colour}{text.center(WIDTH)}{_RESET}")
    print(f"{_BOLD}{colour}{line}{_RESET}\n")


def truncate(text: str, limit: int = 68) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
