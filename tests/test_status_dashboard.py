import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from raspberry.status_dashboard import DashboardHandler, StatusStore


class StatusDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = StatusStore(f"{self.temporary_directory.name}/history.db")
        handler = type(
            "TestDashboardHandler",
            (DashboardHandler,),
            {
                "store": self.store,
                "override_callback": None,
                "settings_callback": staticmethod(
                    lambda: {"schedule": {"sunrise": "06:00"}}
                ),
                "update_settings_callback": staticmethod(lambda payload: payload),
            },
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join()
        self.temporary_directory.cleanup()

    def test_root_serves_temperature_and_humidity_monitor(self):
        with urlopen(self.base_url) as response:
            page = response.read().decode("utf-8")

        self.assertIn("Air temperature", page)
        self.assertIn("Humidity", page)
        self.assertIn("Temperature left", page)
        self.assertIn("Temperature right", page)
        self.assertIn("Temperature middle/top", page)
        self.assertIn("Soil moisture left", page)
        self.assertIn("/api/status", page)
        self.assertIn("Moxa", page)
        self.assertIn("/api/history", page)
        self.assertIn("Manual control", page)
        self.assertIn("RO on", page)
        self.assertIn("RO off", page)
        self.assertIn("RO auto", page)
        self.assertIn("Climate settings (JSON)", page)
        self.assertIn("/api/settings", page)

    def test_settings_api_reads_and_saves_json(self):
        settings = {"schedule": {"sunrise": "06:00"}}

        with urlopen(f"{self.base_url}/api/settings") as response:
            self.assertEqual(json.load(response), settings)

        updated = {"schedule": {"sunrise": "06:30"}}
        request = Request(
            f"{self.base_url}/api/settings",
            data=json.dumps(updated).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(request) as response:
            self.assertEqual(json.load(response), updated)

    def test_status_api_remains_available_for_the_pc_ui(self):
        self.store.update("esp32", {"sensors": {"temperature_top": 24.5}})

        with urlopen(f"{self.base_url}/api/status") as response:
            status = json.load(response)

        self.assertEqual(status["esp32"]["sensors"]["temperature_top"], 24.5)

    def test_history_page_serves_temperature_chart_and_forecast(self):
        with urlopen(f"{self.base_url}/history") as response:
            page = response.read().decode("utf-8")

        self.assertIn("Temperature history", page)
        self.assertIn("Aquarium water", page)
        self.assertIn("30-minute air trend", page)
        self.assertIn("/api/temperature-history?range=${period}", page)
        self.assertIn("24 hours", page)
        self.assertIn("Week", page)
        self.assertIn("Month", page)
        self.assertIn("Year", page)
        self.assertIn("Humidity left", page)
        self.assertIn("Humidity right", page)
        self.assertIn("Humidity middle/top", page)
        self.assertIn("const minimumTemperature=15", page)
        self.assertIn("const maximumTemperature=35", page)
        self.assertIn('id="tooltip"', page)
        self.assertIn('id="crosshair"', page)
        self.assertIn("svg.onmousemove", page)
        self.assertIn("const xGrid=", page)

    def test_temperature_history_returns_requested_period_in_chart_buckets(self):
        now = time.time()
        self.store.record(
            "esp32_sensors",
            {
                "temperature_top": 24.0,
                "temperature_left": 26.0,
                "humidity_top": 92.0,
                "humidity_left": 88.0,
                "aquarium_temp": 23.5,
            },
            "esp32/sensors",
            timestamp=now - 60,
        )

        with urlopen(f"{self.base_url}/api/temperature-history?range=24h") as response:
            rows = json.load(response)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["air_temperature"], 25.0)
        self.assertEqual(rows[0]["aquarium_temperature"], 23.5)
        self.assertEqual(rows[0]["humidity_middle"], 92.0)
        self.assertEqual(rows[0]["humidity_left"], 88.0)

    def test_repeated_state_is_not_written_twice(self):
        values = {"do6": "OFF", "alarm": False}

        self.assertTrue(self.store.record_state_change("command", values, "moxa/cmd/output"))
        self.assertFalse(self.store.record_state_change("command", values, "moxa/cmd/output"))

        self.assertEqual(len(self.store.history(source="command")), 1)

    def test_expired_sensor_readings_are_rolled_up_before_deletion(self):
        now = 2_000_000_000
        old_timestamp = now - StatusStore.RAW_SENSOR_RETENTION_SECONDS - 1
        self.store.record(
            "esp32_sensors",
            {"temperature_top": 24.5, "humidity_top": 90.0},
            "esp32/sensors",
            timestamp=old_timestamp,
        )

        self.store._database.execute(
            "CREATE TABLE cloud_sync (name TEXT PRIMARY KEY, last_history_id INTEGER NOT NULL)"
        )
        self.store._database.execute(
            "INSERT INTO cloud_sync(name, last_history_id) VALUES ('cosmos', 1)"
        )
        self.store._database.commit()
        self.store.cleanup(now)

        self.assertEqual(self.store.history(source="esp32_sensors"), [])
        row = self.store._database.execute(
            "SELECT sample_count, minimum, maximum, average FROM sensor_rollups "
            "WHERE bucket_seconds = 300 AND sensor_name = 'temperature_top'"
        ).fetchone()
        self.assertEqual(row, (1, 24.5, 24.5, 24.5))

    def test_unsynced_sensor_readings_are_not_removed(self):
        now = 2_000_000_000
        self.store.record(
            "esp32_sensors",
            {"temperature_top": 24.5},
            "esp32/sensors",
            timestamp=now - StatusStore.RAW_SENSOR_RETENTION_SECONDS - 1,
        )

        self.store.cleanup(now)

        self.assertEqual(len(self.store.history(source="esp32_sensors")), 1)


if __name__ == "__main__":
    unittest.main()