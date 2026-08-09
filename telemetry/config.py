import os
import sys
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    mongo_uri: str
    db_name: str
    collection_name: str
    flush_interval_seconds: int
    mouse_dpi: int
    app_whitelist: set[str]


APP_WHITELIST = {
    "Anki",
    "Notion",
    "Obsidian",
    "Valorant",
    "Google Chrome",
    "Visual Studio Code",
    "Ghostty",
}


def _require_positive_int(raw: str | None, default: int, name: str) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(
            f"{name} must be a positive integer, got {raw!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    if value <= 0:
        print(
            f"{name} must be a positive integer, got {value}",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def load_config(dotenv_path: str | None = None) -> Config:
    load_dotenv(dotenv_path=dotenv_path)
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("Missing MONGO_URI in environment", file=sys.stderr)
        sys.exit(1)
    db_name = os.getenv("ACTIVITY_DB_NAME", "activity-telemetry")
    return Config(
        mongo_uri=mongo_uri,
        db_name=db_name,
        collection_name="telemetry",
        flush_interval_seconds=_require_positive_int(
            os.getenv("FLUSH_INTERVAL_SECONDS"), 60, "FLUSH_INTERVAL_SECONDS"
        ),
        mouse_dpi=_require_positive_int(
            os.getenv("MOUSE_DPI"), 72, "MOUSE_DPI"
        ),
        app_whitelist=set(APP_WHITELIST),
    )
