import json
import unittest

from raspberry.mqtt_controller import TerrariumMQTTController
from raspberry.terrarium_logic import TerrariumLogic


class TerrariumLogicTests(unittest.TestCase):
    def test_safe_mode_when_leak_detected(self):
        logic = TerrariumLogic()
        payload = {"di2": True, "alarm": False}

        actions = logic.evaluate_moxa_state(payload)

        self.assertEqual(actions["mistmaker"], "OFF")
        self.assertEqual(actions["beregening"], "OFF")
        self.assertTrue(actions["alarm"])

    def test_fan_level_increases_with_temperature(self):
        logic = TerrariumLogic()

        logic.update_sensor_state({
            "temperature_top": 28.0,
            "temperature_left": 27.5,
            "temperature_right": 23.0,
        })

        command = logic.evaluate_fan_command()

        self.assertGreater(command["level"], 0)
        self.assertEqual(command["mode"], "auto")

    def test_no_heartbeat_sets_alarm(self):
        logic = TerrariumLogic()
        logic.last_heartbeat = 9999999999

        actions = logic.evaluate_esp32_health(now=1700000000)

        self.assertTrue(actions["alarm"])
        self.assertEqual(actions["status"], "offline")

    def test_mqtt_controller_maps_sensor_and_safety_messages(self):
        controller = TerrariumMQTTController(broker="example.local")
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))

        controller.handle_message("esp32/sensors", json.dumps({
            "temperature_top": 30,
            "humidity_top": 60,
        }))

        self.assertTrue(any(topic == "esp32/cmd/fans" for topic, _ in published))

        controller.handle_message("moxa/status", json.dumps({
            "di2": True,
            "alarm": False,
        }))

        self.assertTrue(any(topic == "moxa/cmd/output" for topic, _ in published))


if __name__ == "__main__":
    unittest.main()
