"""Offline-first synchronisation of the Pi history database to Cosmos DB."""

from __future__ import annotations

import os
import json
import sqlite3
import time
import argparse
from datetime import datetime, timezone
from typing import Any, Callable, Optional


class CosmosHistorySync:
    """Upload local history records and resume from the last confirmed record."""

    def __init__(
        self,
        database_path: str = "terrarium_history.db",
        client: Any = None,
        endpoint: Optional[str] = None,
        key: Optional[str] = None,
        database_name: Optional[str] = None,
        device_id: Optional[str] = None,
        client_factory: Optional[Callable[[str, str], Any]] = None,
    ) -> None:
        self.database_path = database_path
        self.device_id = device_id or os.getenv("COSMOS_DEVICE_ID", "terrarium-pi")
        self.database_name = database_name or os.getenv("COSMOS_DATABASE", "db-terrarium")
        self.endpoint = endpoint or os.getenv("COSMOS_URL")
        self.key = key or os.getenv("COSMOS_KEY")
        self._client = client
        self._client_factory = client_factory

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.endpoint or not self.key:
            raise RuntimeError("COSMOS_URL and COSMOS_KEY are required for cloud sync")
        if self._client_factory is None:
            from azure.cosmos import CosmosClient

            self._client_factory = CosmosClient
        self._client = self._client_factory(self.endpoint, self.key)
        return self._client

    def _prepare_database(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS cloud_sync ("
            "name TEXT PRIMARY KEY, last_history_id INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT OR IGNORE INTO cloud_sync(name, last_history_id) VALUES ('cosmos', 0)"
        )
        connection.commit()

    @staticmethod
    def _container_name(source: str) -> str:
        if source.startswith("esp32_"):
            return "sensor_readings"
        if source.startswith("alert"):
            return "alerts"
        return "device_status"

    def sync_once(self, limit: Optional[int] = None, latest: bool = False) -> int:
        """Upload records since the checkpoint or a bounded latest batch."""
        safe_limit = None if limit is None else max(1, min(int(limit), 1000))
        connection = sqlite3.connect(self.database_path)
        try:
            self._prepare_database(connection)
            last_id = connection.execute(
                "SELECT last_history_id FROM cloud_sync WHERE name = 'cosmos'"
            ).fetchone()[0]
            if latest:
                latest_limit = safe_limit or 100
                rows = connection.execute(
                    "SELECT id, timestamp, source, topic, values_json FROM history "
                    "ORDER BY id DESC LIMIT ?",
                    (latest_limit,),
                ).fetchall()
                rows.reverse()
            else:
                query = (
                    "SELECT id, timestamp, source, topic, values_json FROM history "
                    "WHERE id > ? ORDER BY id"
                )
                parameters: tuple[Any, ...] = (last_id,)
                if safe_limit is not None:
                    query += " LIMIT ?"
                    parameters += (safe_limit,)
                rows = connection.execute(query, parameters).fetchall()
            if not rows:
                return 0

            database = self._get_client().get_database_client(self.database_name)
            confirmed = 0
            for history_id, timestamp, source, topic, values_json in rows:
                document = {
                    "id": f"history-{history_id}",
                    "deviceId": self.device_id,
                    "timestamp": timestamp,
                    "timestampIso": datetime.fromtimestamp(
                        timestamp, tz=timezone.utc
                    ).isoformat(),
                    "source": source,
                    "topic": topic,
                    "values": json.loads(values_json),
                    "syncedAt": time.time(),
                }
                container = database.get_container_client(self._container_name(source))
                container.upsert_item(document)
                connection.execute(
                    "UPDATE cloud_sync SET last_history_id = ? WHERE name = 'cosmos'",
                    (history_id,),
                )
                connection.commit()
                confirmed += 1
            return confirmed
        finally:
            connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync local terrarium history to Cosmos DB")
    parser.add_argument(
        "--database",
        default=os.getenv("TERRARIUM_HISTORY_DB", "terrarium_history.db"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum records; defaults to all records from the checkpoint",
    )
    parser.add_argument(
        "--from-checkpoint",
        action="store_true",
        help="resume from the last confirmed record instead of selecting the newest records",
    )
    args = parser.parse_args()
    uploaded = CosmosHistorySync(database_path=args.database).sync_once(
        args.limit,
        latest=not args.from_checkpoint,
    )
    print(f"Uploaded {uploaded} history record(s) to Cosmos DB")


if __name__ == "__main__":
    main()