from __future__ import annotations

import logging
import threading
import time

from AppKit import NSWorkspace
from Foundation import NSAutoreleasePool

from telemetry.config import Config
from telemetry.state import TelemetryState

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
