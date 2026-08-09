from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
from pymongo import MongoClient
from telemetry.config import Config

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, config: Config, _client: MongoClient | None = None) -> None:
        self._config = config
        self._client = _client or MongoClient(config.mongo_uri)
        self._collection = self._client[config.db_name][config.collection_name]

    def flush(self, snapshot: dict[str, Any]) -> str | None:
        document = {
            "createdAt": datetime.now(timezone.utc),
            "mouse": snapshot["mouse"],
            "keys": snapshot["keys"],
            "apps": snapshot["apps"],
        }
        try:
            result = self._collection.insert_one(document)
            logger.info("Flushed telemetry document %s", result.inserted_id)
            return str(result.inserted_id)
        except Exception as exc:
            logger.exception("Failed to flush telemetry: %s", exc)
            return None

    def close(self) -> None:
        self._client.close()
