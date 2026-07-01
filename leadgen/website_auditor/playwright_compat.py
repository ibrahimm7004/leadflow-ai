from __future__ import annotations

import asyncio
import sys


def ensure_windows_playwright_loop() -> None:
    """Use a Windows event loop that supports subprocesses before Playwright starts."""
    if not sys.platform.startswith("win"):
        return

    policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    loop_cls = getattr(asyncio, "ProactorEventLoop", None)
    if policy_cls is None or loop_cls is None:
        return

    if not isinstance(asyncio.get_event_loop_policy(), policy_cls):
        asyncio.set_event_loop_policy(policy_cls())

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(loop_cls())
        return

    if loop.is_closed() or not isinstance(loop, loop_cls):
        asyncio.set_event_loop(loop_cls())
