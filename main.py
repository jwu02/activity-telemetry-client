from __future__ import annotations
import logging
import signal
import threading
from typing import Any

from telemetry.config import load_config
from telemetry.permissions import check_permissions
from telemetry.state import TelemetryState
from telemetry.storage import Storage
from telemetry.collectors.mouse import MouseCollector
from telemetry.collectors.keyboard import KeyboardCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("activity-telemetry")


class Runner:
    def __init__(self, missing_permissions: list[str] | None = None) -> None:
        self.missing_permissions = missing_permissions or []
        self.config = load_config()
        self.state = TelemetryState()
        self.storage = Storage(self.config)
        self.mouse = MouseCollector(self.state, self.config)
        self.keyboard = KeyboardCollector(self.state, self.config)
        self._shutdown = threading.Event()

    def _mouse_enabled(self) -> bool:
        return "Input Monitoring" not in self.missing_permissions

    def _keyboard_enabled(self) -> bool:
        return (
            "Accessibility" not in self.missing_permissions
            and "Input Monitoring" not in self.missing_permissions
        )

    def start(self) -> None:
        logger.info("Starting Activity Telemetry client")
        if self._mouse_enabled():
            self.mouse.start()
        else:
            logger.warning(
                "Input Monitoring permission missing; mouse tracking disabled"
            )
        if self._keyboard_enabled():
            self.keyboard.start()
        else:
            logger.warning(
                "Accessibility/Input Monitoring permission missing; keyboard tracking disabled"
            )

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

        try:
            while not self._shutdown.is_set():
                if self._shutdown.wait(self.config.flush_interval_seconds):
                    break
                self._flush_once()
        finally:
            self.stop()

    def _on_signal(self, signum: int, frame: Any) -> None:
        logger.info("Received signal %s, shutting down", signum)
        self._shutdown.set()

    def _flush_once(self) -> None:
        if not self.state.has_activity():
            return
        snapshot = self.state.snapshot()
        doc_id = self.storage.flush(snapshot)
        if doc_id is None:
            logger.error("Flush failed; counters will retry on next flush")
            return
        self.state.clear()

    def stop(self) -> None:
        logger.info("Stopping collectors")
        if self._mouse_enabled():
            self.mouse.stop()
        if self._keyboard_enabled():
            self.keyboard.stop()
        # Final flush
        if self.state.has_activity():
            snapshot = self.state.snapshot()
            doc_id = self.storage.flush(snapshot)
            if doc_id is None:
                logger.error("Final flush failed: %s", snapshot)
            else:
                self.state.clear()
        self.storage.close()
        logger.info("Shutdown complete")


def run() -> None:
    missing = check_permissions()
    if missing:
        logger.warning(
            "Missing macOS permissions: %s. "
            "Mouse/keyboard tracking will be disabled. "
            "Grant them in System Settings -> Privacy & Security for full telemetry.",
            ", ".join(missing),
        )
    runner = Runner(missing_permissions=missing)
    runner.start()


if __name__ == "__main__":
    run()
