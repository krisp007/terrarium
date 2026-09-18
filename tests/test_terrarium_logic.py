import json
import unittest
from datetime import datetime

from raspberry.mqtt_controller import TerrariumMQTTController
from raspberry.service import MOXA_READ_TOPIC, SUBSCRIPTIONS, TerrariumMQTTService
from raspberry.status_dashboard import StatusStore
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

        command = logic.evaluate_fan_command(now=0)

        self.assertGreater(command["level"], 0)
        self.assertEqual(command["mode"], "auto")
        self.assertEqual(command["channels"]["fan1"], 25)
        self.assertEqual(command["channels"]["fan6"], 0)

        alternate = logic.evaluate_fan_command(now=60)
        self.assertEqual(alternate["channels"]["fan1"], 0)
        self.assertEqual(alternate["channels"]["fan6"], 25)

    def test_heater_turns_on_below_minimum_temperature(self):
        logic = TerrariumLogic({"safety": {"temperature_too_low_c": 18.0}})
        logic.update_sensor_state({"temperature_top": 17.5})

        command = logic.evaluate_heater_command()

        self.assertEqual(command["do6"], "ON")
        self.assertEqual(command["reason"], "temperature_too_low")

    def test_heater_stays_off_at_normal_temperature(self):
        logic = TerrariumLogic()
        logic.update_sensor_state({"temperature_top": 24.0})

        command = logic.evaluate_heater_command()

        self.assertEqual(command["do6"], "OFF")

    def test_heater_is_forced_off_by_leak_alarm(self):
        logic = TerrariumLogic()
        logic.update_sensor_state({"temperature_top": 17.0})
        logic.evaluate_moxa_state({"di2": True})

        command = logic.evaluate_moxa_outputs()

        self.assertEqual(command["do6"], "OFF")

    def test_random_rainstorm_runs_only_in_rainy_season(self):
        logic = TerrariumLogic({
            "seasons": {
                "rainy": {
                    "rainstorm": {
                        "chance_percent": 100,
                        "duration_minutes": 2,
                        "cooldown_minutes": 30,
                    },
                },
            },
        })

        storm = logic.evaluate_rainstorm(season="rainy", now=1000, random_value=0.0)
        self.assertTrue(storm["active"])
        self.assertEqual(storm["do4"], "ON")
        self.assertEqual(storm["do5"], "ON")
        self.assertEqual(logic.evaluate_rainstorm(season="dry", now=1001, random_value=0.0)["active"], False)

    def test_rainstorm_is_blocked_by_leak_or_empty_reservoir(self):
        logic = TerrariumLogic()
        logic.evaluate_moxa_state({"di0": False, "di1": True, "di2": False})

        storm = logic.evaluate_rainstorm(now=1000, random_value=0.0)

        self.assertFalse(storm["active"])
        self.assertEqual(storm["reason"], "safety_block")

    def test_fan_levels_follow_editable_settings(self):
        logic = TerrariumLogic({
            "fan_control": {
                "temp_thresholds_c": {
                    "low": 20,
                    "medium": 23,
                    "high": 26,
                    "max_safe": 29,
                },
                "fan_levels_percent": {
                    "off": 5,
                    "low": 15,
                    "medium": 30,
                    "high": 60,
                    "max": 90,
                },
            },
        })
        logic.update_sensor_state({"temperature_top": 25})
        self.assertEqual(logic.evaluate_fan_command()["level"], 30)

        logic.update_settings({
            "fan_control": {
                "fan_levels_percent": {"medium": 45},
            },
        })
        self.assertEqual(logic.evaluate_fan_command()["level"], 45)

    def test_no_heartbeat_sets_alarm(self):
        logic = TerrariumLogic()
        logic.last_heartbeat = 9999999999

        actions = logic.evaluate_esp32_health(now=1700000000)

        self.assertTrue(actions["alarm"])
        self.assertEqual(actions["status"], "offline")

    def test_startup_state_uses_current_time_and_safe_outputs(self):
        controller = TerrariumMQTTController(broker="example.local")
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))

        controller.publish_current_state(datetime(2026, 9, 18, 17, 0))

        topics = [topic for topic, _ in published]
        self.assertEqual(topics, ["esp32/cmd/fans", "esp32/cmd/lights", "moxa/cmd/output"])
        lights = published[1][1]
        self.assertEqual(lights["brightness"], 80)
        self.assertTrue(published[2][1]["alarm"])

    def test_mqtt_controller_maps_sensor_and_safety_messages(self):
        controller = TerrariumMQTTController(broker="example.local")
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))

        controller.handle_message("esp32/sensors", json.dumps({
            "temperature_top": 30,
            "humidity_top": 60,
        }))

        self.assertTrue(any(topic == "esp32/cmd/fans" for topic, _ in published))
        self.assertTrue(any(topic == "esp32/cmd/lights" for topic, _ in published))
        self.assertTrue(any(topic == "moxa/cmd/output" for topic, _ in published))

        moxa_commands = [payload for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(moxa_commands[-1]["reason"], "moxa_status_unknown")

        controller.handle_message("moxa/status", json.dumps({
            "di0": True,
            "di1": True,
            "di2": False,
        }))

        controller.handle_message("esp32/sensors", json.dumps({
            "temperature_top": 25,
            "humidity_top": 70,
        }))
        moxa_commands = [payload for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(moxa_commands[-1]["do5"], "ON")

        controller.handle_message("moxa/status", json.dumps({
            "di0": False,
            "di1": True,
            "di2": False,
        }))
        moxa_commands = [payload for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(moxa_commands[-1]["do5"], "OFF")
        self.assertTrue(moxa_commands[-1]["alarm"])

        controller.handle_message("moxa/status", json.dumps({
            "di2": True,
            "alarm": False,
        }))

        self.assertTrue(any(topic == "moxa/cmd/output" for topic, _ in published))

    def test_rainforest_transition_steps(self):
        logic = TerrariumLogic()

        dawn = logic.evaluate_light_transition("05:50", season="rainy")
        self.assertEqual(dawn["led2"], 20)

        morning = logic.evaluate_light_transition("06:10", season="rainy")
        self.assertEqual(morning["led1"], 20)
        self.assertEqual(morning["led2"], 40)
        self.assertEqual(morning["led3"], 40)
        self.assertEqual(morning["led4"], 20)

        full_day = logic.evaluate_light_transition("12:00", season="rainy")
        self.assertEqual(full_day["led1"], 80)
        self.assertEqual(full_day["led2"], 80)
        self.assertEqual(full_day["led3"], 80)
        self.assertEqual(full_day["led4"], 80)

        dry_day = logic.evaluate_light_transition("12:00", season="dry")
        self.assertEqual(dry_day["led1"], 100)
        self.assertEqual(dry_day["led2"], 100)
        self.assertEqual(dry_day["led3"], 100)
        self.assertEqual(dry_day["led4"], 100)

    def test_light_command_follows_day_and_night_schedule(self):
        logic = TerrariumLogic()

        night = logic.evaluate_light_command("23:00")
        self.assertEqual(night["state"], "off")
        self.assertEqual(night["brightness"], 0)

        day = logic.evaluate_light_command("12:00", season="rainy")
        self.assertEqual(day["state"], "on")
        self.assertEqual(day["brightness"], 80)

        dawn = logic.evaluate_light_command("05:50", season="rainy")
        self.assertEqual(dawn["leds"]["led3"], 20)

        dusk = logic.evaluate_light_command("18:25", season="rainy")
        self.assertEqual(dusk["state"], "on")
        self.assertLess(dusk["brightness"], 80)

    def test_mqtt_service_subscribes_and_dispatches(self):
        class FakeClient:
            def __init__(self):
                self.subscribed = []
                self.published = []
                self.on_connect = None
                self.on_message = None

            def subscribe(self, topic):
                self.subscribed.append(topic)

            def publish(self, topic, payload):
                self.published.append((topic, payload))

            def connect(self, broker, port, keepalive):
                self.on_connect(self, None, {}, 0)

            def loop_forever(self):
                return None

            def disconnect(self):
                return None

        client = FakeClient()
        service = TerrariumMQTTService(
            "example.local",
            status_port=0,
            client_factory=lambda: client,
        )
        service.run()

        self.assertEqual(client.subscribed, [*SUBSCRIPTIONS, MOXA_READ_TOPIC])
        client.on_message(client, None, type("Message", (), {
            "topic": "esp32/sensors",
            "payload": b'{"temperature_top": 30}',
        })())
        self.assertEqual(client.published[0][0], "esp32/cmd/fans")
        service._publish("moxa/cmd/output", {"do5": "ON"})
        self.assertIn(
            ("ioThinx_4510/write/DO@DO-05/doStatus", '{"value": 1}'),
            client.published,
        )
        service.stop()

    def test_status_store_returns_copy_of_system_status(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            store = StatusStore(f"{directory}/history.db")
            store.record("esp32_sensors", {"temperature_top": 24.5}, topic="esp32/sensors")
            history = store.history()

            self.assertEqual(history[0]["source"], "esp32_sensors")
            self.assertEqual(history[0]["values"]["temperature_top"], 24.5)

            store.update("moxa", {"status": "online"})
            snapshot = store.snapshot()
            self.assertEqual(snapshot["moxa"]["status"], "online")
            snapshot["moxa"]["status"] = "changed"
            self.assertEqual(store.snapshot()["moxa"]["status"], "online")


if __name__ == "__main__":
    unittest.main()
