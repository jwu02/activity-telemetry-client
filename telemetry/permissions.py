from __future__ import annotations

import logging
import platform
from typing import Callable

logger = logging.getLogger(__name__)


def _load_checkers() -> tuple[Callable[[], bool] | None, Callable[[], bool] | None]:
    """Return (input_monitoring_checker, accessibility_checker) for macOS."""
    if platform.system() != "Darwin":
        return None, None

    listen_checker: Callable[[], bool] | None = None
    try:
        import Quartz

        listen_checker = Quartz.CGPreflightListenEventAccess
    except Exception as exc:  # pragma: no cover - platform-specific import
        logger.debug("Unable to load Input Monitoring permission check: %s", exc)

    ax_checker: Callable[[], bool] | None = None
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        def ax_checker() -> bool:
            return AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: False})
    except Exception as exc:  # pragma: no cover - platform-specific import
        logger.debug("Unable to load Accessibility permission check: %s", exc)

    return listen_checker, ax_checker


_input_monitoring_checker, _accessibility_checker = _load_checkers()


def check_permissions() -> list[str]:
    """Return a list of missing required macOS permissions."""
    missing: list[str] = []
    if _input_monitoring_checker is not None and not _input_monitoring_checker():
        missing.append("Input Monitoring")
    if _accessibility_checker is not None and not _accessibility_checker():
        missing.append("Accessibility")
    return missing
