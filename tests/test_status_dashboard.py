import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

from raspberry.status_dashboard import DashboardHandler, StatusStore


class StatusDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = StatusStore(f"{self.temporary_directory.name}/history.db")
        handler = type(
            "TestDashboardHandler",
            (DashboardHandler,),
            {"store": self.store, "override_callback": None},
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
        self.assertIn("/api/status", page)
        self.assertNotIn("Moxa", page)
        self.assertNotIn("/api/history", page)

    def test_status_api_remains_available_for_the_pc_ui(self):
        self.store.update("esp32", {"sensors": {"temperature_top": 24.5}})

        with urlopen(f"{self.base_url}/api/status") as response:
            status = json.load(response)

        self.assertEqual(status["esp32"]["sensors"]["temperature_top"], 24.5)


if __name__ == "__main__":
    unittest.main()