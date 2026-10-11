import json
import sqlite3
import tempfile
import unittest

from raspberry.cosmos_sync import CosmosHistorySync


class FakeContainer:
    def __init__(self):
        self.items = []

    def upsert_item(self, item):
        self.items.append(item)


class FakeDatabase:
    def __init__(self):
        self.containers = {}

    def get_container_client(self, name):
        return self.containers.setdefault(name, FakeContainer())


class FakeClient:
    def __init__(self):
        self.database = FakeDatabase()

    def get_database_client(self, name):
        return self.database


class CosmosHistorySyncTests(unittest.TestCase):
    def test_sync_is_resumable_and_routes_history(self):
        with tempfile.NamedTemporaryFile() as database_file:
            connection = sqlite3.connect(database_file.name)
            connection.execute(
                "CREATE TABLE history (id INTEGER PRIMARY KEY, timestamp REAL, "
                "source TEXT, topic TEXT, values_json TEXT)"
            )
            connection.execute(
                "INSERT INTO history VALUES (1, 1000, 'esp32_sensors', 'esp32/sensors', ?)",
                (json.dumps({"temperature_top": 24.5}),),
            )
            connection.execute(
                "INSERT INTO history VALUES (2, 1001, 'moxa_read', 'moxa/status', ?)",
                (json.dumps({"value": 1}),),
            )
            connection.commit()
            connection.close()

            client = FakeClient()
            sync = CosmosHistorySync(database_file.name, client=client)

            self.assertEqual(sync.sync_once(), 2)
            self.assertEqual(sync.sync_once(), 0)
            self.assertEqual(
                client.database.containers["sensor_readings"].items[0]["id"],
                "history-1",
            )
            self.assertEqual(
                client.database.containers["device_status"].items[0]["id"],
                "history-2",
            )
            self.assertEqual(
                client.database.containers["sensor_readings"].items[0]["timestampIso"],
                "1970-01-01T00:16:40+00:00",
            )

    def test_latest_limit_skips_old_history(self):
        with tempfile.NamedTemporaryFile() as database_file:
            connection = sqlite3.connect(database_file.name)
            connection.execute(
                "CREATE TABLE history (id INTEGER PRIMARY KEY, timestamp REAL, "
                "source TEXT, topic TEXT, values_json TEXT)"
            )
            for history_id in range(1, 6):
                connection.execute(
                    "INSERT INTO history VALUES (?, ?, 'esp32_sensors', 'esp32/sensors', ?)",
                    (history_id, history_id, json.dumps({"value": history_id})),
                )
            connection.commit()
            connection.close()

            client = FakeClient()
            sync = CosmosHistorySync(database_file.name, client=client)

            self.assertEqual(sync.sync_once(limit=2, latest=True), 2)
            items = client.database.containers["sensor_readings"].items
            self.assertEqual([item["id"] for item in items], ["history-4", "history-5"])

    def test_checkpoint_sync_uploads_all_records_after_interruption(self):
        with tempfile.NamedTemporaryFile() as database_file:
            connection = sqlite3.connect(database_file.name)
            connection.execute(
                "CREATE TABLE history (id INTEGER PRIMARY KEY, timestamp REAL, "
                "source TEXT, topic TEXT, values_json TEXT)"
            )
            for history_id in range(1, 106):
                connection.execute(
                    "INSERT INTO history VALUES (?, ?, 'esp32_sensors', 'esp32/sensors', ?)",
                    (history_id, history_id, json.dumps({"value": history_id})),
                )
            connection.commit()
            connection.close()

            client = FakeClient()
            sync = CosmosHistorySync(database_file.name, client=client)

            self.assertEqual(sync.sync_once(), 105)
            self.assertEqual(len(client.database.containers["sensor_readings"].items), 105)


if __name__ == "__main__":
    unittest.main()