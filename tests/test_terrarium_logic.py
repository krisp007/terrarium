import json
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from raspberry.mqtt_controller import TerrariumMQTTController
from raspberry.service import MOXA_READ_TOPIC, SUBSCRIPTIONS, TerrariumMQTTService
from raspberry.status_dashboard import StatusStore
from raspberry.terrarium_logic import TerrariumLogic


class TerrariumLogicTests(unittest.TestCase):
    def setUp(self):
        # Keep service tests from writing fake readings into the real history DB.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = f"{directory.name}/history.db"
        patcher = patch(
            "raspberry.service.StatusStore", lambda: StatusStore(path)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_mqtt_controller_reads_broker_from_environment(self):
        with patch.dict("os.environ", {"TERRARIUM_MQTT_BROKER": "192.168.24.51"}):
            controller = TerrariumMQTTController()

        self.assertEqual(controller.broker, "192.168.24.51")

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
        self.assertEqual(command["channels"]["fan1"], 30)
        self.assertEqual(command["channels"]["fan6"], 0)

        alternate = logic.evaluate_fan_command(now=60)
        self.assertEqual(alternate["channels"]["fan1"], 0)
        self.assertEqual(alternate["channels"]["fan6"], 30)

    def test_all_regular_fans_respect_minimum_airflow(self):
        logic = TerrariumLogic()
        logic.update_sensor_state({"temperature_top": 20.0})

        command = logic.evaluate_fan_command(now=0)

        self.assertEqual(command["level"], 30)

    def test_manual_fan_override_blocks_minimum_airflow_until_auto(self):
        logic = TerrariumLogic()
        logic.set_fan_override({f"fan{number}": 0 for number in range(1, 7)})

        manual = logic.evaluate_fan_command(now=0)

        self.assertEqual(manual["mode"], "manual")
        self.assertEqual(manual["minimum_airflow"]["enabled"], True)
        self.assertEqual(manual["channels"], {f"fan{number}": 0 for number in range(1, 7)})

        logic.clear_fan_override()
        automatic = logic.evaluate_fan_command(now=0)
        self.assertEqual(automatic["mode"], "auto")
        self.assertEqual(automatic["channels"]["fan1"], 30)

    def test_manual_led_override_blocks_scheduled_brightness_until_auto(self):
        logic = TerrariumLogic()
        logic.set_led_override("led1", 0)

        manual = logic.evaluate_light_command("12:00", season="rainy")

        self.assertEqual(manual["leds"]["led1"], 0)
        self.assertEqual(manual["leds"]["led2"], 80)

        logic.clear_led_override("led1")
        automatic = logic.evaluate_light_command("12:00", season="rainy")
        self.assertEqual(automatic["leds"]["led1"], 80)

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
                    "low": 30,
                    "medium": 50,
                    "high": 80,
                    "max": 100,
                },
            },
        })
        logic.update_sensor_state({"temperature_top": 25})
        self.assertEqual(logic.evaluate_fan_command()["level"], 50)

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
        controller = TerrariumMQTTController(
            broker="example.local",
            settings={"safety": {"float_overrides": {"di0": None, "di1": None}}},
        )
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

        controller.handle_message("moxa/status", json.dumps({"di0": True, "di1": True, "di2": False}))
        controller.handle_message("esp32/sensors", json.dumps({"temperature_top": 25, "humidity_top": 70}))
        moxa_commands = [payload for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(moxa_commands[-1]["do5"], "ON")

        controller.handle_message("moxa/status", json.dumps({"di0": False, "di1": True, "di2": False}))
        moxa_commands = [payload for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(moxa_commands[-1]["do5"], "OFF")
        self.assertTrue(moxa_commands[-1]["alarm"])

        controller.handle_message("moxa/status", json.dumps({"di2": True, "alarm": False}))
        self.assertTrue(any(topic == "moxa/cmd/output" for topic, _ in published))

    def test_scheduled_lighting_turns_outputs_off_without_sensor_updates(self):
        controller = TerrariumMQTTController(broker="example.local")
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))

        controller.publish_scheduled_lights(datetime(2026, 10, 16, 19, 24))

        lights = next(payload for topic, payload in published if topic == "esp32/cmd/lights")
        self.assertEqual(lights["state"], "off")
        self.assertEqual(lights["brightness"], 0)
        moxa_lights = next(payload for topic, payload in published if topic == "moxa/cmd/output")
        self.assertEqual(
            {moxa_lights[f"do{output}"] for output in range(4)},
            {"OFF"},
        )

    def test_moxa_status_update_only_changes_climate_outputs(self):
        controller = TerrariumMQTTController()
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))
        controller.logic.update_sensor_state({"temperature_top": 17.0})

        controller.handle_message(
            "moxa/status",
            json.dumps({"di0": True, "di1": True, "di2": False}),
        )

        moxa_commands = [
            payload for topic, payload in published if topic == "moxa/cmd/output"
        ]
        self.assertEqual(len(moxa_commands), 1)
        self.assertEqual(moxa_commands[0]["do6"], "ON")
        self.assertFalse(any(f"do{output}" in moxa_commands[0] for output in range(4)))

    def test_sensor_update_publishes_lighting_and_climate_outputs_separately(self):
        controller = TerrariumMQTTController()
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))
        controller.logic.update_sensor_state({"temperature_top": 17.0})

        controller.handle_message(
            "esp32/sensors",
            json.dumps({"temperature_top": 17.0}),
        )

        moxa_commands = [
            payload for topic, payload in published if topic == "moxa/cmd/output"
        ]
        self.assertEqual(len(moxa_commands), 2)
        self.assertEqual(
            {key for key in moxa_commands[0] if key.startswith("do")},
            {"do0", "do1", "do2", "do3"},
        )
        self.assertEqual(
            {key for key in moxa_commands[1] if key.startswith("do")},
            {"do4", "do5", "do6", "do15"},
        )

    def test_ro_valve_fills_between_min_and_max_floats(self):
        logic = TerrariumLogic()
        logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False, "di3": False, "di4": False})
        self.assertEqual(logic.evaluate_ro_command()["do15"], "ON")

        logic.moxa_state["di3"] = True
        self.assertEqual(logic.evaluate_ro_command()["do15"], "ON")

        logic.moxa_state["di4"] = True
        self.assertEqual(logic.evaluate_ro_command()["do15"], "OFF")

        logic.moxa_state["di3"] = False
        logic.moxa_state["di4"] = False
        self.assertEqual(logic.evaluate_ro_command()["do15"], "ON")

        logic.moxa_state["di2"] = True
        self.assertEqual(logic.evaluate_ro_command()["do15"], "OFF")

    def test_unwired_reservoir_floats_default_to_ok(self):
        logic = TerrariumLogic()
        logic.evaluate_moxa_state({"di2": False, "di3": True, "di4": False})

        outputs = logic.evaluate_moxa_outputs(now=0)

        self.assertFalse(outputs["alarm"])

    def test_irrigation_does_not_run_without_humidity_readings(self):
        logic = TerrariumLogic()
        logic.rainstorm["enabled"] = False
        logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
        logic.update_sensor_state({"soil_left": 60})

        command = logic.evaluate_moxa_outputs(now=0)

        self.assertEqual(command["do4"], "OFF")
        self.assertEqual(command["reason"], "sensor_control")

    def test_irrigation_starts_below_82_percent_average_air_humidity(self):
        logic = TerrariumLogic()
        logic.rainstorm["enabled"] = False
        logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
        logic.update_sensor_state({"humidity_top": 80, "humidity_bottom": 82})

        command = logic.evaluate_moxa_outputs(now=0)

        self.assertEqual(command["do4"], "ON")
        self.assertEqual(command["reason"], "sensor_control")

    def test_irrigation_stops_at_90_percent_average_air_humidity(self):
        logic = TerrariumLogic()
        logic.rainstorm["enabled"] = False
        logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
        logic.update_sensor_state({"humidity_top": 70})
        logic.evaluate_moxa_outputs(now=0)
        logic.update_sensor_state({"humidity_top": 90})

        command = logic.evaluate_moxa_outputs(now=1)

        self.assertEqual(command["do4"], "OFF")

    def test_morning_irrigation_runs_for_25_seconds_before_sunrise(self):
        logic = TerrariumLogic({"schedule": {"sunrise": "06:00"}})
        logic.rainstorm["enabled"] = False
        logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
        logic.update_sensor_state({"humidity_top": 95})
        morning = datetime(2026, 10, 16, 5, 59, 35)

        start = logic.evaluate_moxa_outputs(now=morning.timestamp())
        during = logic.evaluate_moxa_outputs(now=morning.timestamp() + 24)
        after = logic.evaluate_moxa_outputs(now=morning.timestamp() + 25)

        self.assertEqual(start["do4"], "ON")
        self.assertEqual(during["do4"], "ON")
        self.assertEqual(after["do4"], "OFF")

    def test_morning_mistmaker_runs_for_20_minutes_after_irrigation(self):
        logic = TerrariumLogic({"schedule": {"sunrise": "06:00"}})
        logic.rainstorm["enabled"] = False
        logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
        logic.update_sensor_state({"humidity_top": 95})
        morning = datetime(2026, 10, 16, 5, 59, 35)
        logic.evaluate_irrigation_command(now=morning.timestamp())
        sunrise = morning.timestamp() + 25

        self.assertIsNone(logic.evaluate_scheduled_morning_mistmaker(now=sunrise - 1))
        self.assertEqual(logic.evaluate_scheduled_morning_mistmaker(now=sunrise), "ON")
        self.assertEqual(logic.evaluate_moxa_outputs(now=sunrise)["do5"], "ON")
        self.assertEqual(
            logic.evaluate_scheduled_morning_mistmaker(now=sunrise + 19 * 60 + 59),
            "ON",
        )
        self.assertEqual(
            logic.evaluate_scheduled_morning_mistmaker(now=sunrise + 20 * 60),
            "OFF",
        )
        self.assertEqual(logic.evaluate_moxa_outputs(now=sunrise + 20 * 60)["do5"], "OFF")
        self.assertIsNone(
            logic.evaluate_scheduled_morning_mistmaker(now=sunrise + 20 * 60 + 1)
        )

    def test_morning_mistmaker_is_blocked_by_low_reservoir_or_leak(self):
        for moxa_status in (
            {"di0": False, "di1": True, "di2": False},
            {"di0": True, "di1": True, "di2": True},
        ):
            with self.subTest(moxa_status=moxa_status):
                logic = TerrariumLogic({
                    "schedule": {"sunrise": "06:00"},
                    "safety": {"float_overrides": {"di0": None}},
                })
                logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
                morning = datetime(2026, 10, 16, 5, 59, 35)
                logic.evaluate_irrigation_command(now=morning.timestamp())
                safety_actions = logic.evaluate_moxa_state(moxa_status)
                self.assertEqual(safety_actions["do5"], "OFF")
                self.assertEqual(safety_actions["do5"], "OFF")
                scheduled_action = logic.evaluate_scheduled_morning_mistmaker(
                    now=morning.timestamp() + 25
                )
                self.assertEqual(scheduled_action, "OFF" if not moxa_status["di2"] else None)

    def test_healthy_moxa_status_does_not_activate_irrigation_outputs(self):
        logic = TerrariumLogic()

        actions = logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})

        self.assertNotIn("do4", actions)
        self.assertNotIn("do5", actions)

    def test_scheduled_irrigation_publishes_only_output_changes(self):
        controller = TerrariumMQTTController(broker="example.local")
        controller.logic.rainstorm["enabled"] = False
        controller.logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
        controller.logic.update_sensor_state({"humidity_top": 70})
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))
        start = datetime(2026, 10, 16, 12, 0)

        controller.publish_scheduled_irrigation(start)
        controller.publish_scheduled_irrigation(start.replace(second=1))
        controller.publish_scheduled_irrigation(start.replace(second=26))

        commands = [payload["do4"] for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(commands, ["ON", "OFF"])

    def test_scheduled_morning_mistmaker_publishes_on_then_off(self):
        controller = TerrariumMQTTController(
            broker="example.local",
            settings={"schedule": {"sunrise": "06:00"}},
        )
        controller.logic.rainstorm["enabled"] = False
        controller.logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
        controller.logic.update_sensor_state({"humidity_top": 95})
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))
        morning = datetime(2026, 10, 16, 5, 59, 35)

        controller.publish_scheduled_irrigation(morning)
        controller.publish_scheduled_irrigation(morning.replace(hour=6, minute=0))
        controller.publish_scheduled_irrigation(morning.replace(hour=6, minute=20))

        mistmaker_commands = [
            payload["do5"]
            for topic, payload in published
            if topic == "moxa/cmd/output" and "do5" in payload
        ]
        self.assertEqual(mistmaker_commands, ["ON", "OFF"])

    def test_mist_and_irrigation_follow_frequency_and_duration_settings(self):
        logic = TerrariumLogic({
            "mistmaker": {"max_runtime_minutes": 1, "pause_minutes": 1},
            "irrigation": {"cycle_minutes": 1, "duration_seconds": 30},
        })
        logic.rainstorm["enabled"] = False
        logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False, "di3": True, "di4": False})
        logic.update_sensor_state({"humidity_top": 70, "soil_left": 20})

        start = logic.evaluate_moxa_outputs(now=0)
        self.assertEqual(start["do5"], "ON")
        self.assertEqual(start["do4"], "ON")

        mid = logic.evaluate_moxa_outputs(now=31)
        self.assertEqual(mid["do4"], "OFF")
        self.assertEqual(mid["do5"], "ON")

        later = logic.evaluate_moxa_outputs(now=61)
        self.assertEqual(later["do4"], "ON")
        self.assertEqual(later["do5"], "OFF")

    def test_mqtt_controller_publishes_manual_actor_overrides(self):
        controller = TerrariumMQTTController(broker="example.local")
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))

        controller.apply_override({
            "actor_type": "Fan",
            "actor_name": "fan-2",
            "state": True,
            "intensity": 45,
        })
        self.assertEqual(published[-1][0], "esp32/cmd/fans")
        self.assertEqual(published[-1][1]["level"], 30)
        self.assertEqual(published[-1][1]["channels"]["fan2"], 45)

        controller.apply_override({
            "actor_type": "LED",
            "actor_name": "led-3",
            "state": True,
            "intensity": 70,
        })
        light_commands = [payload for topic, payload in published if topic == "esp32/cmd/lights"]
        self.assertEqual(light_commands[-1]["leds"]["led3"], 70)
        self.assertTrue(any(topic == "moxa/cmd/output" for topic, _ in published))

        controller.apply_override({
            "actor_type": "Pump",
            "actor_name": "waterfall",
            "state": True,
        })
        self.assertEqual(published[-1][0], "moxa/cmd/output")
        self.assertEqual(published[-1][1]["do7"], "ON")

    def test_ro_override_controls_do15_and_auto_restores_it(self):
        controller = TerrariumMQTTController(broker="example.local")
        published = []
        controller.publish = lambda topic, payload: published.append((topic, payload))

        controller.apply_override({
            "actor_type": "Pump",
            "actor_name": "ro",
            "state": True,
            "duration_minutes": 30,
        })
        self.assertEqual(published[-1][0], "moxa/cmd/output")
        self.assertEqual(published[-1][1]["do15"], "ON")
        self.assertIn("do15", controller.manual_output_overrides)

        result = controller.apply_override({
            "mode": "auto",
            "actor_type": "Pump",
            "actor_name": "ro",
        })
        self.assertEqual(result["status"], "auto")
        self.assertNotIn("do15", controller.manual_output_overrides)

    def test_mist_maker_override_is_capped_to_protect_the_pump(self):
        controller = TerrariumMQTTController(broker="example.local")
        controller.publish = lambda topic, payload: None

        before = time.time()
        controller.apply_override({
            "actor_type": "Mist Maker",
            "actor_name": "mistmaker",
            "state": True,
            "duration_minutes": 30,
        })

        expires_at = controller.manual_output_overrides["do5"]["expires_at"]
        self.assertLessEqual(expires_at - before, 10 * 60 + 1)

    def test_rain_pump_override_is_capped_to_protect_the_pump(self):
        controller = TerrariumMQTTController(broker="example.local")
        controller.publish = lambda topic, payload: None

        before = time.time()
        controller.apply_override({
            "actor_type": "Pump",
            "actor_name": "irrigation",
            "state": True,
            "duration_minutes": 45,
        })

        expires_at = controller.manual_output_overrides["do4"]["expires_at"]
        self.assertLessEqual(expires_at - before, 10 * 60 + 1)

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

    def test_moxa_lights_follow_day_and_night_schedule(self):
        logic = TerrariumLogic()

        night = logic.evaluate_moxa_light_outputs("23:00")
        self.assertEqual(
            {night[f"do{output}"] for output in range(4)},
            {"OFF"},
        )

        day = logic.evaluate_moxa_light_outputs("12:00")
        self.assertEqual(
            {day[f"do{output}"] for output in range(4)},
            {"ON"},
        )

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

            def connect_async(self, broker, port, keepalive):
                self.on_connect(self, None, {}, 0)

            def loop_forever(self, retry_first_connection):
                self.retry_first_connection = retry_first_connection
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
        self.assertTrue(client.retry_first_connection)
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

    def test_light_schedule_runs_periodically_without_sensor_messages(self):
        from threading import Thread

        class FakeClient:
            pass

        service = TerrariumMQTTService(
            "example.local",
            status_port=0,
            client_factory=FakeClient,
        )
        scheduled = []
        service.controller.publish_scheduled_lights = lambda: scheduled.append(True)

        with patch("raspberry.service.LIGHT_SCHEDULE_INTERVAL_SECONDS", 0.01):
            schedule_thread = Thread(target=service._run_light_schedule)
            schedule_thread.start()
            time.sleep(0.05)
            service._light_schedule_stop.set()
            schedule_thread.join(timeout=1)

        self.assertFalse(schedule_thread.is_alive())
        self.assertGreaterEqual(len(scheduled), 1)

    def test_irrigation_schedule_runs_periodically_without_sensor_messages(self):
        from threading import Thread

        class FakeClient:
            pass

        service = TerrariumMQTTService(
            "example.local",
            status_port=0,
            client_factory=FakeClient,
        )
        scheduled = []
        service.controller.publish_scheduled_irrigation = lambda: scheduled.append(True)

        with patch("raspberry.service.IRRIGATION_SCHEDULE_INTERVAL_SECONDS", 0.01):
            schedule_thread = Thread(target=service._run_irrigation_schedule)
            schedule_thread.start()
            time.sleep(0.05)
            service._light_schedule_stop.set()
            schedule_thread.join(timeout=1)

        self.assertFalse(schedule_thread.is_alive())
        self.assertGreaterEqual(len(scheduled), 1)

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
