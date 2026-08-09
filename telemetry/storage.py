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
        self._heatmap_collection = self._client[config.db_name][
            config.heatmap_collection_name
        ]

    def flush(self, snapshot: dict[str, Any]) -> list[str] | None:
        now = datetime.now(timezone.utc)
        telemetry_doc = {
            "createdAt": now,
            "leftClicks": snapshot["leftClicks"],
            "rightClicks": snapshot["rightClicks"],
            "movementMeters": snapshot["movementMeters"],
            "keysPressed": snapshot["keysPressed"],
        }
        documents = [(self._collection, telemetry_doc)]
        heatmap = snapshot.get("keyboard_heatmap", {})
        if heatmap:
            heatmap_doc = {"createdAt": now, **heatmap}
            documents.append((self._heatmap_collection, heatmap_doc))
        inserted_ids: list[str] = []
        try:
            for collection, document in documents:
                result = collection.insert_one(document)
                inserted_ids.append(str(result.inserted_id))
        except Exception as exc:
            logger.exception("Failed to flush telemetry documents: %s", exc)
            return None
        logger.info("Flushed telemetry documents: %s", inserted_ids)
        return inserted_ids

    def close(self) -> None:
        self._client.close()
