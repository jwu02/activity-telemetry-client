from __future__ import annotations

import ctypes
import logging
import os
import platform
import threading
import time
from ctypes import wintypes

from telemetry.config import Config
from telemetry.state import TelemetryState

_IS_DARWIN = platform.system() == "Darwin"
if _IS_DARWIN:
    from AppKit import NSWorkspace
    from Foundation import NSAutoreleasePool

# ctypes.windll exists only on Windows. Tests patch this module attribute
# on any platform; leave it None off-Windows so import never fails.
_WINDLL = ctypes.windll if platform.system() == "Windows" else None

logger = logging.getLogger(__name__)

# NSWorkspace.frontmostApplication().localizedName() can vary by locale,
# app version, or install source (e.g. VS Code reports "Code"). Bundle IDs
# are stable, so map known bundle IDs to the display names used in the
# app whitelist.
BUNDLE_ID_TO_APP_NAME: dict[str, str] = {
    "com.google.Chrome": "Google Chrome",
    "com.microsoft.VSCode": "Visual Studio Code",
    "com.mitchellh.ghostty": "Ghostty",
    "net.ankiweb.dtop": "Anki",
    "notion.id": "Notion",
    "md.obsidian": "Obsidian",
}

# Windows process-name → display-name mapping, equivalent to
# BUNDLE_ID_TO_APP_NAME on macOS.
PROCESS_NAME_TO_APP_NAME: dict[str, str] = {
    "chrome": "Google Chrome",
    "Code": "Visual Studio Code",
    "Ghostty": "Ghostty",
    "anki": "Anki",
    "Notion": "Notion",
    "Obsidian": "Obsidian",
}


def _basename_exe(exe_path: str) -> str:
    """Return the executable basename without extension, cross-platform.

    Windows paths use backslashes; os.path.basename is host-dependent, so
    normalize separators before splitting.
    """
    return exe_path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _get_window_process_id(user32, hwnd: int) -> int | None:
    """Return the process ID that owns the given window handle."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def _process_display_name_from_pid(kernel32, pid: int) -> str | None:
    """Return the mapped display name for a process, or None if unmapped."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_process:
        return None
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(size)):
            process_name = _basename_exe(buf.value)
            return PROCESS_NAME_TO_APP_NAME.get(process_name)
    finally:
        kernel32.CloseHandle(h_process)
    return None


def _frontmost_app_name_windows() -> str | None:
    """Return the frontmost application name on Windows using ctypes/Win32."""
    user32 = _WINDLL.user32
    kernel32 = _WINDLL.kernel32

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    # Prefer a mapped display name from the process executable path.
    pid = _get_window_process_id(user32, hwnd)
    if pid is not None:
        mapped = _process_display_name_from_pid(kernel32, pid)
        if mapped is not None:
            return mapped

    # Fallback: use window title (similar to localizedName on macOS).
    length = user32.GetWindowTextLengthW(hwnd) + 1
    buf = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buf, length)
    title = buf.value
    return title if title else None


class AppCollector:
    def __init__(
        self,
        state: TelemetryState,
        config: Config,
        poll_interval: float = 1.0,
        shutdown_event: threading.Event | None = None,
    ) -> None:
        self._state = state
        self._config = config
        self._poll_interval = poll_interval
        self._shutdown_event = shutdown_event
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        last_time = time.monotonic()
        try:
            while not self._stop_event.is_set():
                frontmost = self._frontmost_app_name()
                now = time.monotonic()
                elapsed = now - last_time
                self._record(frontmost, elapsed)
                last_time = now
                time.sleep(self._poll_interval)
        except Exception:
            logger.exception("App collector crashed")
            if self._shutdown_event is not None:
                self._shutdown_event.set()

    def _frontmost_app_name(self) -> str | None:
        if _IS_DARWIN:
            return self._frontmost_app_name_darwin()
        return _frontmost_app_name_windows()

    def _frontmost_app_name_darwin(self) -> str | None:
        # NSWorkspace/AppKit calls from a background thread need an
        # autorelease pool, otherwise returned Objective-C objects can be
        # released before PyObjC bridges their values (e.g. localizedName
        # or bundleIdentifier returning None for some apps).
        pool = NSAutoreleasePool.alloc().init()
        try:
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                logger.debug("NSWorkspace returned no frontmost application")
                return None
            bundle_id = app.bundleIdentifier()
            localized_name = app.localizedName()
            if bundle_id and bundle_id in BUNDLE_ID_TO_APP_NAME:
                mapped_name = BUNDLE_ID_TO_APP_NAME[bundle_id]
                logger.debug(
                    "Mapped frontmost app bundle ID %r (localizedName=%r) -> %r",
                    bundle_id,
                    localized_name,
                    mapped_name,
                )
                return mapped_name
            logger.debug(
                "Using frontmost app localizedName=%r (bundle ID=%r)",
                localized_name,
                bundle_id,
            )
            return localized_name
        finally:
            pool.drain()

    def _record(self, frontmost_name: str | None, seconds: float | None = None) -> None:
        if seconds is None:
            seconds = self._poll_interval
        if frontmost_name and frontmost_name in self._config.app_whitelist:
            self._state.add_app_time(frontmost_name, seconds)
