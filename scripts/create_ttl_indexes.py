"""One-off: create TTL indexes on the existing Atlas collections.

Run from the repository root:  python scripts/create_ttl_indexes.py
Requires MONGO_URI (and optionally ACTIVITY_DB_NAME) in .env.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import MongoClient

from telemetry.config import load_config


def main() -> None:
    cfg = load_config()
    client = MongoClient(cfg.mongo_uri)
    try:
        existing = set(client[cfg.db_name].list_collection_names())
        for name in (cfg.collection_name, cfg.heatmap_collection_name):
            if name not in existing:
                raise SystemExit(
                    f"Collection {name!r} not found in database {cfg.db_name!r}; "
                    "refusing to create TTL index on an empty collection."
                )

        for name, ttl in (
            (cfg.collection_name, cfg.collection_ttl_seconds),
            (cfg.heatmap_collection_name, cfg.heatmap_ttl_seconds),
        ):
            index_name = client[cfg.db_name][name].create_index(
                "createdAt", expireAfterSeconds=ttl
            )
            print(f"Created TTL index on {name}: {index_name}")

        print("Verification (TTL indexes):")
        for name in (cfg.collection_name, cfg.heatmap_collection_name):
            for idx in client[cfg.db_name][name].list_indexes():
                if "expireAfterSeconds" in idx:
                    print(
                        f"  {name}: name={idx['name']} "
                        f"expireAfterSeconds={idx['expireAfterSeconds']}"
                    )
    finally:
        client.close()


if __name__ == "__main__":
    main()
