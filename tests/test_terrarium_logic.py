import json
import unittest
from datetime import datetime, timedelta

from raspberry.mqtt_controller import TerrariumMQTTController
from raspberry.service import MOXA_READ_TOPIC, SUBSCRIPTIONS, TerrariumMQTTService
from raspberry.serial_bridge import SerialBridge
from raspberry.status_dashboard import StatusStore
from raspberry.terrarium_logic import TerrariumLogic


class TerrariumLogicTests(unittest.TestCase):
    @staticmethod
    def rainy_profile_settings():
        return {
            "schedule": {"sunrise": "05:45", "sunset": "18:15"},
            "seasons": {
                "rainy": {
                    "active": True,
                    "day": {
                        "temperature": {"min_c": 23.5, "max_c": 27.0, "target_c": 25.0},
                        "humidity": {"min_percent": 80.0, "max_percent": 98.0, "target_percent": 90.0},
                    },
                    "night": {
                        "temperature": {"min_c": 20.0, "max_c": 22.8, "target_c": 20.0},
                        "humidity": {"min_percent": 80.0, "max_percent": 99.0, "target_percent": 90.0},
                    },
                    "rainstorm": {
                        "enabled": True,
                        "chance_percent": 5,
                        "duration_minutes": 1,
                        "cooldown_minutes": 30,
                        "pre_light_lead_minutes": 5,
                        "post_rain_mist_minutes": 10,
                    },
                },
            },
            "fan_control": {
                "fan_levels_percent": {"off": 0, "low": 30, "medium": 50, "high": 80, "max": 100},
            },
            "safety": {"temperature_too_low_c": 18.0, "temperature_too_high_c": 30.5},
        }

    def test_safe_mode_when_leak_detected(self):
        logic = TerrariumLogic()
        payload = {"di0": True, "di2": True, "alarm": False}

        actions = logic.evaluate_moxa_state(payload)

        self.assertEqual(actions["mistmaker"], "OFF")
        self.assertEqual(actions["beregening"], "OFF")
        self.assertEqual(actions["do15"], "OFF")
        self.assertEqual(actions["do12"], "OFF")
        self.assertTrue(actions["alarm"])

    def test_ro_valve_opens_only_when_di0_is_active(self):
        logic = TerrariumLogic()

        active = logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": False})
        inactive = logic.evaluate_moxa_state({"di0": False, "di1": True, "di2": False})

        self.assertEqual(active["do15"], "ON")
        self.assertEqual(inactive["do15"], "OFF")

    def test_ro_valve_defaults_closed_until_moxa_state_is_known(self):
        logic = TerrariumLogic()

        actions = logic.evaluate_moxa_outputs()

        self.assertEqual(actions["do15"], "OFF")
        self.assertEqual(actions["do12"], "OFF")

    def test_aquarium_refill_pump_follows_di1_and_leak_interlock(self):
        logic = TerrariumLogic()

        active = logic.evaluate_moxa_state({"di1": True, "di2": False})
        inactive = logic.evaluate_moxa_state({"di1": False, "di2": False})
        leak = logic.evaluate_moxa_state({"di1": True, "di2": True})

        self.assertEqual(active["do12"], "ON")
        self.assertEqual(inactive["do12"], "OFF")
        self.assertEqual(leak["do12"], "OFF")

    def test_waterfall_and_orchid_dripper_follow_json_cycles(self):
        logic = TerrariumLogic({
            "waterfall": {
                "enabled": False,
                "auto_mode": True,
                "cycle_minutes": 90,
                "duration_seconds": 45,
            },
            "orchid_dripper": {
                "enabled": True,
                "auto_mode": True,
                "cycle_minutes": 90,
                "duration_seconds": 45,
            },
        })
        logic.evaluate_moxa_state({"di2": False, "alarm": False})

        pump_status = logic.scheduled_pump_status(now=0, moxa_online=True)
        running_status = logic.scheduled_pump_status(now=5401, moxa_online=True)
        before = logic.evaluate_scheduled_pump_outputs(now=0, moxa_online=True)
        due = logic.evaluate_scheduled_pump_outputs(now=5400, moxa_online=True)
        last_active_second = logic.evaluate_scheduled_pump_outputs(now=5444, moxa_online=True)
        expired = logic.evaluate_scheduled_pump_outputs(now=5445, moxa_online=True)

        self.assertEqual(before, {"do10": "OFF", "do11": "OFF"})
        self.assertFalse(pump_status["do10"]["enabled"])
        self.assertTrue(pump_status["do11"]["enabled"])
        self.assertEqual(pump_status["do11"]["cycle_minutes"], 90)
        self.assertEqual(pump_status["do11"]["duration_seconds"], 45)
        self.assertEqual(pump_status["do11"]["next_run_seconds"], 5400)
        self.assertEqual(running_status["do11"]["remaining_run_seconds"], 44)
        self.assertEqual(due, {"do10": "OFF", "do11": "ON"})
        self.assertEqual(last_active_second["do11"], "ON")
        self.assertEqual(expired["do11"], "OFF")

    def test_scheduled_pumps_fail_off_when_moxa_is_offline_or_leaking(self):
        logic = TerrariumLogic({
            "orchid_dripper": {
                "enabled": True,
                "auto_mode": True,
                "cycle_minutes": 90,
                "duration_seconds": 45,
            },
        })

        offline = logic.evaluate_scheduled_pump_outputs(now=5400, moxa_online=False)
        logic.evaluate_moxa_state({"di2": True, "alarm": True})
        leak = logic.evaluate_scheduled_pump_outputs(now=5400, moxa_online=True)

        self.assertEqual(offline["do11"], "OFF")
        self.assertEqual(leak["do11"], "OFF")

    def test_auxiliary_pumps_follow_json_enable_cycle_and_duration(self):
        logic = TerrariumLogic({
            "waterfall": {
                "enabled": False,
                "auto_mode": True,
                "cycle_minutes": 90,
                "duration_seconds": 45,
            },
            "orchid_dripper": {
                "enabled": True,
                "auto_mode": True,
                "cycle_minutes": 90,
                "duration_seconds": 45,
            },
        })
        logic.evaluate_moxa_state({"di2": False, "alarm": False})

        before_first_cycle = logic.evaluate_scheduled_pump_outputs(now=0, moxa_online=True)
        just_before = logic.evaluate_scheduled_pump_outputs(now=5399, moxa_online=True)
        cycle_start = logic.evaluate_scheduled_pump_outputs(now=5400, moxa_online=True)
        last_active_second = logic.evaluate_scheduled_pump_outputs(now=5444, moxa_online=True)
        cycle_end = logic.evaluate_scheduled_pump_outputs(now=5445, moxa_online=True)

        self.assertEqual(before_first_cycle, {"do10": "OFF", "do11": "OFF"})
        self.assertEqual(just_before["do11"], "OFF")
        self.assertEqual(cycle_start["do11"], "ON")
        self.assertEqual(last_active_second["do11"], "ON")
        self.assertEqual(cycle_end["do11"], "OFF")
        self.assertEqual(cycle_start["do10"], "OFF")

    def test_auxiliary_pumps_fail_off_without_online_safe_moxa(self):
        logic = TerrariumLogic({
            "orchid_dripper": {
                "enabled": True,
                "auto_mode": True,
                "cycle_minutes": 90,
                "duration_seconds": 45,
            },
        })

        offline = logic.evaluate_scheduled_pump_outputs(now=5400, moxa_online=False)
        logic.evaluate_moxa_state({"di2": True, "alarm": True})
        leak = logic.evaluate_scheduled_pump_outputs(now=5400, moxa_online=True)

        self.assertEqual(offline["do11"], "OFF")
        self.assertEqual(leak["do11"], "OFF")

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

    def test_middle_fans_are_off_at_night_but_daytime_fan_control_remains(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        logic.update_sensor_state({"temperature_top": 21.5, "humidity_top": 95.0})

        night = logic.evaluate_fan_command(
            now=0,
            climate_time=datetime(2026, 9, 18, 21, 0),
        )
        logic.update_sensor_state({"temperature_top": 25.0, "humidity_top": 90.0})
        day = logic.evaluate_fan_command(
            now=0,
            climate_time=datetime(2026, 9, 18, 12, 0),
        )

        self.assertEqual(
            [night["channels"][f"fan{number}"] for number in range(2, 6)],
            [0, 0, 0, 0],
        )
        self.assertEqual(night["channels"]["fan1"], 30)
        self.assertEqual(night["channels"]["fan6"], 0)
        self.assertEqual(day["channels"]["fan2"], 30)
        self.assertEqual(day["channels"]["fan3"], 50)
        self.assertEqual(day["channels"]["fan4"], 0)
        self.assertEqual(day["channels"]["fan5"], 0)

    def test_temperature_range_cascades_middle_fans_in_four_levels(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        logic.evaluate_moxa_state({"di2": False, "alarm": False})
        expected = [
            (23.4, [0, 0, 0, 0]),
            (23.5, [30, 0, 0, 0]),
            (24.7, [30, 50, 0, 0]),
            (25.9, [30, 50, 80, 0]),
            (27.0, [30, 50, 80, 100]),
        ]

        for temperature, expected_levels in expected:
            with self.subTest(temperature=temperature):
                logic.update_sensor_state({"temperature_top": temperature, "humidity_top": 90})
                command = logic.evaluate_fan_command(
                    now=0,
                    climate_time=datetime(2026, 9, 18, 12, 0),
                )
                self.assertEqual(
                    [command["channels"][f"fan{number}"] for number in range(2, 6)],
                    expected_levels,
                )
                self.assertEqual(command["channels"]["fan1"], 100 if temperature >= 27.0 else 30)
                self.assertEqual(command["channels"]["fan6"], 100 if temperature >= 27.0 else 0)

    def test_humidity_max_forces_full_fans_unless_cold_or_night(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        logic.update_sensor_state({"temperature_top": 24.0, "humidity_top": 99})

        humid_day = logic.evaluate_fan_command(
            now=0,
            climate_time=datetime(2026, 9, 18, 12, 0),
        )
        cold_day = logic.evaluate_fan_command(
            now=0,
            climate_time=datetime(2026, 9, 18, 12, 0),
        )
        logic.update_sensor_state({"temperature_top": 20.0, "humidity_top": 99})
        cold_day = logic.evaluate_fan_command(
            now=0,
            climate_time=datetime(2026, 9, 18, 12, 0),
        )
        night = logic.evaluate_fan_command(
            now=0,
            climate_time=datetime(2026, 9, 18, 22, 0),
        )

        self.assertEqual([humid_day["channels"][f"fan{n}"] for n in range(2, 6)], [100] * 4)
        self.assertEqual(humid_day["channels"]["fan1"], 100)
        self.assertEqual(humid_day["channels"]["fan6"], 100)
        self.assertEqual([cold_day["channels"][f"fan{n}"] for n in range(2, 6)], [0] * 4)
        self.assertEqual(cold_day["channels"]["fan1"], 30)
        self.assertEqual(cold_day["channels"]["fan6"], 0)
        self.assertEqual([night["channels"][f"fan{n}"] for n in range(2, 6)], [0] * 4)
        self.assertEqual(night["channels"]["fan1"], 100)
        self.assertEqual(night["channels"]["fan6"], 100)

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

    def test_lighting_schedule_uses_json_sunrise_and_sunset(self):
        settings = self.rainy_profile_settings()
        settings["schedule"] = {"sunrise": "06:00", "sunset": "18:00"}
        logic = TerrariumLogic(settings)

        before_sunrise = logic.evaluate_light_command("05:59")
        sunrise = logic.evaluate_light_command("06:00")
        after_sunset = logic.evaluate_light_command("18:20")

        self.assertEqual(before_sunrise["brightness"], 0)
        self.assertEqual(sunrise["leds"]["led2"], 20)
        self.assertEqual(after_sunset["brightness"], 0)

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
                    "active": True,
                    "day": {"humidity": {"min_percent": 82, "target_percent": 90}},
                    "night": {"humidity": {"min_percent": 82, "target_percent": 94}},
                    "rainstorm": {
                        "chance_percent": 100,
                        "duration_minutes": 1,
                        "cooldown_minutes": 30,
                    },
                },
            },
        })

        storm = logic.evaluate_rainstorm(
            season="rainy", now=1000, random_value=0.0, humidity=82, minimum_humidity=82
        )
        self.assertTrue(storm["active"])
        self.assertEqual(storm["do4"], "ON")
        self.assertEqual(storm["do5"], "OFF")
        self.assertFalse(logic.evaluate_rainstorm(
            season="dry", now=1001, random_value=0.0, humidity=82, minimum_humidity=82
        )["active"])

    def test_rain_requires_minimum_humidity_and_stops_after_one_minute(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        logic.update_sensor_state({"humidity_left": 80, "humidity_top": 80, "humidity_right": 80})
        logic.evaluate_moxa_state({"di2": False, "alarm": False})
        start = datetime(2026, 9, 18, 12, 0)

        rain = logic.evaluate_moxa_outputs(now=start, random_value=0.04)
        still_raining = logic.evaluate_moxa_outputs(now=start + timedelta(seconds=59), random_value=0.99)
        stopped = logic.evaluate_moxa_outputs(now=start + timedelta(seconds=60), random_value=0.99)

        self.assertEqual(rain["do4"], "ON")
        self.assertEqual(rain["do5"], "OFF")
        self.assertEqual(still_raining["do4"], "ON")
        self.assertEqual(stopped["do4"], "OFF")

        above_minimum = TerrariumLogic(self.rainy_profile_settings())
        above_minimum.update_sensor_state({"humidity_left": 81, "humidity_top": 81, "humidity_right": 81})
        above_minimum.evaluate_moxa_state({"di2": False, "alarm": False})
        no_rain = above_minimum.evaluate_moxa_outputs(now=start, random_value=0.0)
        self.assertEqual(no_rain["do4"], "OFF")

    def test_scheduled_pre_light_rain_is_followed_by_ten_minutes_mist(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        logic.update_sensor_state({"humidity_left": 80, "humidity_top": 80, "humidity_right": 80})
        logic.evaluate_moxa_state({"di2": False, "alarm": False})
        start = datetime(2026, 9, 18, 5, 40)

        scheduled_rain = logic.evaluate_moxa_outputs(now=start, random_value=0.99)
        post_rain_mist = logic.evaluate_moxa_outputs(now=start + timedelta(seconds=61), random_value=0.99)
        mist_finished = logic.evaluate_moxa_outputs(now=start + timedelta(seconds=661), random_value=0.99)

        self.assertEqual(scheduled_rain["do4"], "ON")
        self.assertEqual(scheduled_rain["do5"], "OFF")
        self.assertEqual(post_rain_mist["do4"], "OFF")
        self.assertEqual(post_rain_mist["do5"], "ON")
        self.assertEqual(mist_finished["do5"], "OFF")

        dusk = TerrariumLogic(self.rainy_profile_settings())
        dusk.update_sensor_state({"humidity_left": 80, "humidity_top": 80, "humidity_right": 80})
        dusk.evaluate_moxa_state({"di2": False, "alarm": False})
        pre_sunset_rain = dusk.evaluate_moxa_outputs(
            now=datetime(2026, 9, 18, 18, 10), random_value=0.99
        )
        self.assertEqual(pre_sunset_rain["do4"], "ON")

    def test_pre_light_rain_respects_cooldown_after_random_rain(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        logic.update_sensor_state({"humidity_left": 80, "humidity_top": 80, "humidity_right": 80})
        logic.evaluate_moxa_state({"di2": False, "alarm": False})

        random_rain = logic.evaluate_moxa_outputs(
            now=datetime(2026, 9, 18, 5, 39), random_value=0.04
        )
        pre_light_window = logic.evaluate_moxa_outputs(
            now=datetime(2026, 9, 18, 5, 40), random_value=0.0
        )

        self.assertEqual(random_rain["do4"], "ON")
        self.assertEqual(pre_light_window["do4"], "OFF")
        self.assertNotIn("2026-09-18:sunrise", logic.scheduled_rain_events)

    def test_random_rain_is_not_followed_by_mist(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        logic.update_sensor_state({"humidity_left": 80, "humidity_top": 80, "humidity_right": 80})
        start = datetime(2026, 9, 18, 12, 0)

        logic.evaluate_moxa_outputs(now=start, random_value=0.04)
        after_rain = logic.evaluate_moxa_outputs(now=start + timedelta(seconds=61), random_value=0.99)

        self.assertEqual(after_rain["do5"], "OFF")

    def test_humidity_target_and_temperature_target_control_fans_and_heater(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        now = datetime(2026, 9, 18, 12, 0)
        logic.update_sensor_state({"temperature_top": 25.0, "humidity_top": 90.0})

        middle_cascade = logic.evaluate_fan_command(climate_time=now)
        self.assertEqual(middle_cascade["level"], 50)

        logic.update_sensor_state({"temperature_top": 27.1, "humidity_top": 96.0})
        above_maximum = logic.evaluate_fan_command(climate_time=now)
        self.assertEqual(above_maximum["level"], 100)
        self.assertEqual(logic.evaluate_moxa_outputs(now=now, random_value=0.99)["do5"], "OFF")

        logic.update_sensor_state({"temperature_top": 24.0, "humidity_top": 90.0})
        self.assertEqual(logic.evaluate_heater_command(climate_time=now)["do6"], "ON")

        logic.update_sensor_state({"temperature_top": 19.0, "humidity_top": 90.0})
        low_temperature_fans = logic.evaluate_fan_command(climate_time=now)
        self.assertEqual(low_temperature_fans["level"], 30)
        self.assertEqual(logic.evaluate_heater_command(climate_time=now)["do6"], "ON")

    def test_rainstorm_is_blocked_by_leak(self):
        logic = TerrariumLogic()
        logic.evaluate_moxa_state({"di0": True, "di1": True, "di2": True})

        storm = logic.evaluate_rainstorm(now=1000, random_value=0.0)

        self.assertFalse(storm["active"])
        self.assertEqual(storm["reason"], "safety_block")

    def test_random_rain_does_not_start_post_rain_mist(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        logic.update_sensor_state({"humidity_left": 80, "humidity_top": 80, "humidity_right": 80})
        logic.evaluate_moxa_state({"di2": False, "alarm": False})
        logic.evaluate_moxa_state({"di0": False, "di1": True, "di2": False})

        rain = logic.evaluate_moxa_outputs(
            now=datetime(2026, 9, 18, 12, 0), random_value=0.04
        )
        after_rain = logic.evaluate_moxa_outputs(
            now=datetime(2026, 9, 18, 12, 1, 1), random_value=0.99
        )

        self.assertEqual(rain["do4"], "ON")
        self.assertEqual(rain["do5"], "OFF")
        self.assertEqual(after_rain["do5"], "OFF")

    def test_high_humidity_ventilation_suppresses_post_rain_mist(self):
        logic = TerrariumLogic(self.rainy_profile_settings())
        start = datetime(2026, 9, 18, 5, 40)
        logic.update_sensor_state({"humidity_left": 80, "humidity_top": 80, "humidity_right": 80})
        logic.evaluate_moxa_state({"di2": False, "alarm": False})
        logic.evaluate_moxa_outputs(now=start, random_value=0.99)

        logic.update_sensor_state({"humidity_left": 96, "humidity_top": 96, "humidity_right": 96})
        post_rain = logic.evaluate_moxa_outputs(now=start + timedelta(seconds=61), random_value=0.99)
        fans = logic.evaluate_fan_command(climate_time=start + timedelta(seconds=61))

        self.assertEqual(post_rain["do5"], "OFF")
        self.assertEqual(fans["level"], 30)
        self.assertEqual(
            [fans["channels"][f"fan{number}"] for number in range(2, 6)],
            [0, 0, 0, 0],
        )

    def test_soil_reading_alone_does_not_start_rain_pump(self):
        logic = TerrariumLogic({"seasons": {"rainy": {"rainstorm": {"enabled": False}}}})
        logic.update_sensor_state({"soil_left": 20})
        logic.evaluate_moxa_state({"di1": False, "di2": False})

        outputs = logic.evaluate_moxa_outputs()

        self.assertEqual(outputs["do4"], "OFF")
        self.assertEqual(outputs["do12"], "OFF")

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
        midday = datetime(2026, 9, 18, 12, 0)
        self.assertEqual(logic.evaluate_fan_command(climate_time=midday)["level"], 50)

        logic.update_settings({
            "fan_control": {
                "fan_levels_percent": {"medium": 45},
            },
        })
        self.assertEqual(logic.evaluate_fan_command(climate_time=midday)["level"], 45)

    def test_no_heartbeat_sets_alarm(self):
        logic = TerrariumLogic()
        logic.last_heartbeat = 9999999999

        actions = logic.evaluate_esp32_health(now=1700000000)

        self.assertTrue(actions["alarm"])
        self.assertEqual(actions["status"], "offline")

    def test_esp32_status_heartbeat_uses_receive_time_when_payload_has_no_timestamp(self):
        controller = TerrariumMQTTController(broker="example.local")

        health = controller.handle_message(
            "esp32/status",
            json.dumps({"device": "esp32_sensor_node", "status": "online"}),
        )

        self.assertEqual(health["status"], "online")
        self.assertIsNotNone(controller.logic.last_heartbeat)
        self.assertLessEqual(
            abs(int(datetime.now().timestamp()) - controller.logic.last_heartbeat),
            1,
        )

    def test_sensor_and_heartbeat_timeouts_load_from_settings(self):
        logic = TerrariumLogic({
            "safety": {
                "sensor_stale_timeout_sec": 360,
                "no_heartbeat_timeout_sec": 960,
            },
        })

        self.assertEqual(logic.sensor_stale_timeout_seconds, 360)
        self.assertEqual(logic.heartbeat_timeout_seconds, 960)

    def test_aquarium_temperature_target_loads_from_settings(self):
        logic = TerrariumLogic({"aquarium": {"temperature_target_c": 25.0}})

        targets = logic._active_climate_targets(datetime(2026, 9, 18, 12, 0))

        self.assertEqual(targets["aquarium_temperature_target"], 25.0)

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
        self.assertEqual(published[2][1]["do12"], "OFF")
        self.assertEqual(published[2][1]["do15"], "OFF")
        self.assertEqual(published[2][1]["do10"], "OFF")
        self.assertEqual(published[2][1]["do11"], "OFF")

    def test_mqtt_controller_maps_sensor_and_safety_messages(self):
        controller = TerrariumMQTTController(broker="example.local")
        controller.logic.rainstorm["enabled"] = False
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
        moxa_commands = [payload for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(moxa_commands[-1]["do15"], "ON")
        controller.handle_message("esp32/sensors", json.dumps({"temperature_top": 25, "humidity_top": 70}))
        moxa_commands = [payload for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(moxa_commands[-1]["do5"], "OFF")

        controller.handle_message("moxa/status", json.dumps({"di0": False, "di1": True, "di2": False}))
        moxa_commands = [payload for topic, payload in published if topic == "moxa/cmd/output"]
        self.assertEqual(moxa_commands[-1]["do15"], "OFF")

        controller.handle_message("moxa/status", json.dumps({"di2": True, "alarm": False}))
        self.assertTrue(any(topic == "moxa/cmd/output" for topic, _ in published))

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
        self.assertEqual(published[-1][1]["level"], 45)
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
        self.assertEqual(published[-1][1]["do10"], "ON")

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
        esp32_status = service.status.snapshot()["esp32"]
        self.assertIn("last_sensor_seen", esp32_status)
        client.on_message(client, None, type("Message", (), {
            "topic": "esp32/fans/status",
            "payload": b'{"channels":{"fan1":30,"fan2":0,"fan3":0,"fan4":0,"fan5":0,"fan6":0}}',
        })())
        self.assertEqual(
            service.status.snapshot()["esp32"]["fan_output"]["channels"]["fan1"],
            30,
        )
        client.on_message(client, None, type("Message", (), {
            "topic": "moxa/status",
            "payload": b'{"di0": true, "di1": false, "di2": false}',
        })())
        client.on_message(client, None, type("Message", (), {
            "topic": "esp32/status",
            "payload": b'{"device":"esp32_sensor_node","status":"online"}',
        })())
        esp32_status = service.status.snapshot()["esp32"]
        self.assertIn("last_status_seen", esp32_status)
        moxa_status = service.status.snapshot()["moxa"]
        self.assertEqual(moxa_status["status"], "online")
        self.assertTrue(moxa_status["inputs"]["di0"])
        client.on_message(client, None, type("Message", (), {
            "topic": "ioThinx_4510/read/lastwill",
            "payload": b"",
        })())
        self.assertEqual(service.status.snapshot()["moxa"]["status"], "offline")
        self.assertEqual(client.published[0][0], "esp32/cmd/fans")
        service._publish("moxa/cmd/output", {"do5": "ON"})
        self.assertIn(
            ("ioThinx_4510/write/DO@DO-05/doStatus", '{"value": 1}'),
            client.published,
        )
        serial_frames = []
        service.serial_bridge = type(
            "FakeSerialBridge",
            (),
            {
                "send": lambda _self, topic, payload: serial_frames.append((topic, payload)) or True,
                "stop": lambda _self: None,
            },
        )()
        service._publish("esp32/cmd/fans", {"level": 30})
        self.assertEqual(serial_frames, [("esp32/cmd/fans", {"level": 30})])
        service.stop()

    def test_serial_bridge_decodes_frames_and_ignores_console_output(self):
        messages = []
        bridge = SerialBridge(lambda _client, _userdata, message: messages.append(message))

        bridge.handle_line("boot log text")
        bridge.handle_line('@{"t":"esp32/sensors","p":{"temperature_top":24.5}}')

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].topic, "esp32/sensors")
        self.assertEqual(messages[0].payload, b'{"temperature_top": 24.5}')

    def test_service_publishes_scheduled_orchid_dripper_output(self):
        class FakeClient:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload):
                self.published.append((topic, payload))
                return type("PublishResult", (), {"rc": 0})()

            def disconnect(self):
                return None

        client = FakeClient()
        service = TerrariumMQTTService(
            "example.local",
            settings={
                "orchid_dripper": {
                    "enabled": True,
                    "auto_mode": True,
                    "cycle_minutes": 90,
                    "duration_seconds": 45,
                },
            },
            client_factory=lambda: client,
        )
        service.status.update("moxa", {"status": "online"})
        service.controller.logic.evaluate_moxa_state({"di2": False, "alarm": False})

        service._publish_scheduled_pumps(now=0)
        service._publish_scheduled_pumps(now=5400)

        output_payloads = [
            json.loads(payload)
            for topic, payload in client.published
            if topic == "moxa/cmd/output"
        ]
        self.assertEqual(output_payloads[-1], {"do11": "ON"})
        service.stop()

    def test_periodic_climate_tick_turns_rain_off_after_one_minute(self):
        class FakeClient:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload):
                self.published.append((topic, payload))
                return type("PublishResult", (), {"rc": 0})()

            def disconnect(self):
                return None

        client = FakeClient()
        service = TerrariumMQTTService(
            "example.local",
            settings=self.rainy_profile_settings(),
            client_factory=lambda: client,
        )
        service.status.update("moxa", {"status": "online"})
        service.status.update("esp32", {
            "status": "online",
            "last_sensor_seen": int(datetime.now().timestamp()),
        })
        service.controller.logic.update_sensor_state({
            "humidity_left": 80,
            "humidity_top": 80,
            "humidity_right": 80,
        })
        service.controller.logic.evaluate_moxa_state({"di2": False, "alarm": False})
        start = datetime.now()
        service.controller.logic.evaluate_moxa_outputs(now=start, random_value=0.0)

        service._publish_timed_climate_outputs(now=start)
        service._publish_timed_climate_outputs(now=start + timedelta(seconds=61))

        rain_states = [
            json.loads(payload).get("do4")
            for topic, payload in client.published
            if topic == "moxa/cmd/output"
        ]
        self.assertEqual(rain_states, ["ON", "OFF"])
        service.stop()

    def test_service_starts_and_stops_pump_scheduler_on_mqtt_connect(self):
        class FakeClient:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload):
                self.published.append((topic, payload))
                return type("PublishResult", (), {"rc": 0})()

            def subscribe(self, _topic):
                return None

            def disconnect(self):
                return None

        client = FakeClient()
        service = TerrariumMQTTService(
            "example.local",
            settings={
                "orchid_dripper": {
                    "enabled": True,
                    "auto_mode": True,
                    "cycle_minutes": 90,
                    "duration_seconds": 45,
                },
            },
            client_factory=lambda: client,
        )
        service.status.update("moxa", {"status": "online"})
        service.controller.logic.evaluate_moxa_state({"di2": False, "alarm": False})

        service._on_connect(client, None, {}, 0)
        dashboard = service.status.snapshot()
        self.assertEqual(dashboard["climate"]["season"], "rainy")
        self.assertEqual(dashboard["climate"]["aquarium_temperature_target"], 25.0)
        self.assertEqual(dashboard["pump_schedule"]["do11"]["cycle_minutes"], 90)
        self.assertEqual(dashboard["pump_schedule"]["do11"]["duration_seconds"], 45)
        self.assertIn("ESP32 heartbeat timeout", dashboard["alarms"]["messages"])
        scheduler = service._pump_scheduler_thread
        service.stop()

        self.assertIsNotNone(scheduler)
        self.assertFalse(scheduler.is_alive())

    def test_service_uses_separate_sensor_and_heartbeat_timeouts(self):
        class FakeClient:
            def publish(self, _topic, _payload):
                return type("PublishResult", (), {"rc": 0})()

            def disconnect(self):
                return None

        service = TerrariumMQTTService(
            "example.local",
            settings={"safety": {"sensor_stale_timeout_sec": 360, "no_heartbeat_timeout_sec": 960}},
            client_factory=FakeClient,
        )
        service.status.update("mqtt", {"status": "connected"})
        service.status.update("moxa", {"status": "online"})
        service.status.update("esp32", {
            "status": "online",
            "last_seen": 1000,
            "last_status_seen": 1000,
            "last_sensor_seen": 1000,
        })

        service._refresh_dashboard_status(now=1361)
        stale_status = service.status.snapshot()
        self.assertEqual(stale_status["esp32"]["status"], "online")
        self.assertIn("ESP32 sensor data stale", stale_status["alarms"]["messages"])

        service._refresh_dashboard_status(now=1961)
        offline_status = service.status.snapshot()
        self.assertEqual(offline_status["esp32"]["status"], "offline")
        self.assertIn("ESP32 heartbeat timeout", offline_status["alarms"]["messages"])

    def test_fresh_sensors_do_not_mask_stale_status_heartbeat(self):
        service = TerrariumMQTTService(
            "example.local",
            settings={"safety": {"no_heartbeat_timeout_sec": 960}},
            client_factory=lambda: type("FakeClient", (), {"publish": lambda *_args: None, "disconnect": lambda *_args: None})(),
        )
        service.status.update("mqtt", {"status": "connected"})
        service.status.update("moxa", {"status": "online"})
        service.status.update("esp32", {
            "status": "online",
            "last_seen": 2000,
            "last_sensor_seen": 2000,
            "last_status_seen": 1000,
            "sensors": {"temperature_top": 24.0},
        })

        service._refresh_dashboard_status(now=2001)

        snapshot = service.status.snapshot()
        self.assertEqual(snapshot["esp32"]["status"], "offline")
        self.assertIn("ESP32 heartbeat timeout", snapshot["alarms"]["messages"])

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
            store._database.close()


if __name__ == "__main__":
    unittest.main()
