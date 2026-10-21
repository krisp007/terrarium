"""Pi-side terrarium control logic.

This module contains the core rules used by the Raspberry Pi to translate
MQTT status messages from the ESP32 and Moxa into safety actions and fan
control commands.
"""

from __future__ import annotations

import random
import time
from copy import deepcopy
from datetime import date, datetime, time as datetime_time
from typing import Callable, Dict, Optional


DEFAULT_FAN_THRESHOLDS = {
    "low": 22.0,
    "medium": 24.5,
    "high": 27.0,
    "max_safe": 30.0,
}
DEFAULT_FAN_LEVELS = {
    "off": 0,
    "low": 30,
    "medium": 50,
    "high": 80,
    "max": 100,
}
DEFAULT_HEATER_THRESHOLDS = {
    "temperature_too_low_c": 18.0,
    "temperature_too_high_c": 30.5,
}
DEFAULT_RAINSTORM = {
    "enabled": True,
    "chance_percent": 5.0,
    "duration_minutes": 2,
    "cooldown_minutes": 30,
}
DEFAULT_MISTMAKER_SETTINGS = {
    "enabled": True,
    "auto_mode": True,
    "max_runtime_minutes": 10,
    "pause_minutes": 8,
    "morning_after_irrigation_minutes": 20,
}
DEFAULT_IRRIGATION_SETTINGS = {
    "enabled": True,
    "auto_mode": True,
    "cycle_minutes": 20,
    "duration_seconds": 25,
    "max_runtime_minutes": 10,
    "humidity_on_percent": 82.0,
    "humidity_off_percent": 90.0,
}
# Reservoir floats without wiring yet; assume filled until the hardware is connected.
DEFAULT_FLOAT_OVERRIDES: Dict[str, bool] = {
    "mist_reservoir": True,
    "irrigation_reservoir": True,
}


class TerrariumLogic:
    """Evaluate safety and climate rules for the terrarium."""

    def __init__(self, settings: Optional[Dict[str, object]] = None) -> None:
        self.sensor_state: Dict[str, float] = {}
        self.moxa_state: Optional[Dict[str, object]] = None
        self.last_heartbeat: Optional[int] = None
        self.heartbeat_timeout_seconds = 180
        self.sensor_schema: Dict[str, object] = {
            "temperature_prefixes": ["temperature"],
            "humidity_prefixes": ["humidity_"],
            "labels": {},
        }
        self.io_inputs: Dict[str, str] = {
            "mist_reservoir": "di0",
            "irrigation_reservoir": "di1",
            "leak": "di2",
            "ro_minimum": "di3",
            "ro_maximum": "di4",
        }
        self.io_outputs: Dict[str, str] = {
            "led1": "do0",
            "led2": "do1",
            "led3": "do2",
            "led4": "do3",
            "irrigation": "do4",
            "mistmaker": "do5",
            "heater": "do6",
            "waterfall": "do7",
            "ro_fill": "do15",
        }
        self.seasons: Dict[str, object] = {"rainy": {"active": True}}
        self.mistmaker_on_humidity = 82.0
        self.mistmaker_off_humidity = 90.0
        self.irrigation_on_humidity = 82.0
        self.irrigation_off_humidity = 90.0
        self.schedule = {"sunrise": "05:45", "sunset": "18:15"}
        self.lighting_settings: Dict[str, object] = {
            "enabled": True,
            "dawn_dusk_transition_minutes": 20,
            "day_brightness_by_season": {"rainy": 80, "dry": 100},
            "transition_steps": [
                {"minutes_from_start": 0, "leds": {"led2": 20}},
                {"minutes_from_start": 5, "leds": {"led2": 20, "led3": 20}},
                {"minutes_from_start": 10, "leds": {"led1": 20, "led2": 40, "led3": 40, "led4": 20}},
                {"minutes_from_start": 15, "leds": {"led1": 40, "led2": 60, "led3": 60, "led4": 40}},
                {"minutes_from_start": 20, "leds": {"led1": 80, "led2": 80, "led3": 80, "led4": 80}},
            ],
        }
        self.fan_thresholds: Dict[str, float] = dict(DEFAULT_FAN_THRESHOLDS)
        self.fan_levels: Dict[str, int] = dict(DEFAULT_FAN_LEVELS)
        self.heater_thresholds: Dict[str, float] = dict(DEFAULT_HEATER_THRESHOLDS)
        self.rainstorm: Dict[str, object] = dict(DEFAULT_RAINSTORM)
        self.rainstorm_until = 0.0
        self.rainstorm_cooldown_until = 0.0
        self.random_source: Callable[[], float] = random.random
        self.minimum_airflow_percent = 30
        self.minimum_airflow_interval_seconds = 60
        self.minimum_airflow_enabled = True
        self.minimum_airflow_fans = (1, 6)
        self.manual_fan_overrides: Dict[str, Dict[str, object]] = {}
        self.manual_led_overrides: Dict[str, Dict[str, object]] = {}
        self.mistmaker_settings: Dict[str, object] = dict(DEFAULT_MISTMAKER_SETTINGS)
        self.irrigation_settings: Dict[str, object] = dict(DEFAULT_IRRIGATION_SETTINGS)
        self.float_overrides: Dict[str, bool] = dict(DEFAULT_FLOAT_OVERRIDES)
        self.mistmaker_run_until = 0.0
        self.mistmaker_pause_until = 0.0
        self.irrigation_run_until = 0.0
        self.irrigation_next_cycle = 0.0
        self.irrigation_morning_run_until = 0.0
        self.irrigation_morning_date: Optional[date] = None
        self.mistmaker_morning_start_at = 0.0
        self.mistmaker_morning_run_until = 0.0
        self.ro_filling = False
        if settings is not None:
            self.update_settings(settings)

    @staticmethod
    def validate_settings(settings: Dict[str, object]) -> None:
        """Reject malformed editable settings before persisting or applying them."""
        if not isinstance(settings, dict):
            raise ValueError("settings must be a JSON object")

        object_sections = (
            "schedule",
            "seasons",
            "sensors",
            "io_mapping",
            "fan_control",
            "lighting",
            "mistmaker",
            "irrigation",
            "safety",
        )
        for section in object_sections:
            value = settings.get(section)
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"{section} must be an object")

        io_mapping = settings.get("io_mapping", {})
        if isinstance(io_mapping, dict):
            for direction, maximum in (("inputs", 31), ("outputs", 15)):
                mapping = io_mapping.get(direction, {})
                if mapping is not None and not isinstance(mapping, dict):
                    raise ValueError(f"io_mapping.{direction} must be an object")
                if isinstance(mapping, dict) and any(
                    not isinstance(value, str)
                    or not value.startswith("di" if direction == "inputs" else "do")
                    or not value[2:].isdigit()
                    or not 0 <= int(value[2:]) <= maximum
                    for value in mapping.values()
                ):
                    raise ValueError(f"io_mapping.{direction} contains an invalid channel")
            valid_roles = {
                "inputs": {
                    "mist_reservoir",
                    "irrigation_reservoir",
                    "leak",
                    "ro_minimum",
                    "ro_maximum",
                },
                "outputs": {
                    "led1",
                    "led2",
                    "led3",
                    "led4",
                    "irrigation",
                    "mistmaker",
                    "heater",
                    "waterfall",
                    "ro_fill",
                },
            }
            for direction, roles in valid_roles.items():
                mapping = io_mapping.get(direction, {})
                if isinstance(mapping, dict) and set(mapping) - roles:
                    raise ValueError(f"io_mapping.{direction} contains an unknown role")
                defaults = (
                    {
                        "mist_reservoir": "di0",
                        "irrigation_reservoir": "di1",
                        "leak": "di2",
                        "ro_minimum": "di3",
                        "ro_maximum": "di4",
                    }
                    if direction == "inputs"
                    else {
                        "led1": "do0",
                        "led2": "do1",
                        "led3": "do2",
                        "led4": "do3",
                        "irrigation": "do4",
                        "mistmaker": "do5",
                        "heater": "do6",
                        "waterfall": "do7",
                        "ro_fill": "do15",
                    }
                )
                merged = {**defaults, **mapping} if isinstance(mapping, dict) else defaults
                if len(set(merged.values())) != len(merged):
                    raise ValueError(f"io_mapping.{direction} channels must be unique")

        sensors = settings.get("sensors", {})
        if isinstance(sensors, dict):
            for key in ("temperature_prefixes", "humidity_prefixes"):
                value = sensors.get(key)
                if value is not None and (
                    not isinstance(value, list)
                    or any(not isinstance(prefix, str) or not prefix for prefix in value)
                ):
                    raise ValueError(f"sensors.{key} must be a list of non-empty strings")
            labels = sensors.get("labels")
            if labels is not None and (
                not isinstance(labels, dict)
                or any(
                    not isinstance(name, str) or not isinstance(label, str)
                    for name, label in labels.items()
                )
            ):
                raise ValueError("sensors.labels must map sensor names to labels")

        schedule = settings.get("schedule", {})
        if isinstance(schedule, dict):
            for key in ("sunrise", "sunset"):
                value = schedule.get(key)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(f"schedule.{key} must be HH:MM")
                    try:
                        datetime.strptime(value, "%H:%M")
                    except ValueError as error:
                        raise ValueError(f"schedule.{key} must be HH:MM") from error

        fan_control = settings.get("fan_control", {})
        if isinstance(fan_control, dict):
            airflow = fan_control.get("minimum_airflow", {})
            if airflow is not None and not isinstance(airflow, dict):
                raise ValueError("fan_control.minimum_airflow must be an object")
            if isinstance(airflow, dict):
                enabled = airflow.get("enabled")
                if enabled is not None and not isinstance(enabled, bool):
                    raise ValueError("fan_control.minimum_airflow.enabled must be a boolean")
                for key in ("percent", "alternate_seconds"):
                    value = airflow.get(key)
                    if value is not None and (
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or (key == "percent" and not 0 <= value <= 100)
                        or (key == "alternate_seconds" and value < 1)
                    ):
                        raise ValueError(f"fan_control.minimum_airflow.{key} is invalid")
                fans = airflow.get("fans")
                if fans is not None and (
                    not isinstance(fans, list)
                    or len(fans) != 2
                    or any(type(fan) is not int or not 1 <= fan <= 6 for fan in fans)
                    or len(set(fans)) != len(fans)
                ):
                    raise ValueError("fan_control.minimum_airflow.fans must contain two distinct fan numbers 1-6")
            for group in ("temp_thresholds_c", "fan_levels_percent"):
                value = fan_control.get(group)
                if value is not None and not isinstance(value, dict):
                    raise ValueError(f"fan_control.{group} must be an object")
                if isinstance(value, dict) and any(
                    not isinstance(number, (int, float))
                    or isinstance(number, bool)
                    or (group == "fan_levels_percent" and not 0 <= number <= 100)
                    for number in value.values()
                ):
                    raise ValueError(f"fan_control.{group} contains an invalid number")
            thresholds = fan_control.get("temp_thresholds_c", {})
            if isinstance(thresholds, dict):
                configured_thresholds = [
                    thresholds[key]
                    for key in ("low", "medium", "high", "max_safe")
                    if key in thresholds
                ]
                if configured_thresholds != sorted(configured_thresholds):
                    raise ValueError("fan_control.temp_thresholds_c must be in ascending order")

        for section, keys in (
            ("mistmaker", ("enabled", "auto_mode")),
            ("irrigation", ("enabled", "auto_mode")),
        ):
            values = settings.get(section, {})
            if isinstance(values, dict):
                for key in keys:
                    if key in values and not isinstance(values[key], bool):
                        raise ValueError(f"{section}.{key} must be a boolean")

        safety = settings.get("safety", {})
        if isinstance(safety, dict):
            for key in ("temperature_too_low_c", "temperature_too_high_c"):
                value = safety.get(key)
                if value is not None and (
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                ):
                    raise ValueError(f"safety.{key} must be a number")
            overrides = safety.get("float_overrides")
            if overrides is not None and (
                not isinstance(overrides, dict)
                or any(value is not None and not isinstance(value, bool) for value in overrides.values())
            ):
                raise ValueError("safety.float_overrides must contain booleans or null")

        seasons = settings.get("seasons", {})
        if isinstance(seasons, dict):
            for name, season in seasons.items():
                if not isinstance(season, dict):
                    raise ValueError(f"seasons.{name} must be an object")
                if "active" in season and not isinstance(season["active"], bool):
                    raise ValueError(f"seasons.{name}.active must be a boolean")
                rainstorm = season.get("rainstorm")
                if rainstorm is not None and not isinstance(rainstorm, dict):
                    raise ValueError(f"seasons.{name}.rainstorm must be an object")

        for section, key in (
            ("safety", "no_heartbeat_timeout_sec"),
            ("mistmaker", "max_runtime_minutes"),
            ("mistmaker", "pause_minutes"),
            ("mistmaker", "morning_after_irrigation_minutes"),
            ("mistmaker", "humidity_on_percent"),
            ("mistmaker", "humidity_off_percent"),
            ("irrigation", "cycle_minutes"),
            ("irrigation", "duration_seconds"),
            ("irrigation", "max_runtime_minutes"),
            ("irrigation", "humidity_on_percent"),
            ("irrigation", "humidity_off_percent"),
        ):
            values = settings.get(section, {})
            if isinstance(values, dict) and key in values:
                value = values[key]
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or value < 0
                ):
                    raise ValueError(f"{section}.{key} must be a non-negative number")

        lighting = settings.get("lighting", {})
        if isinstance(lighting, dict):
            if "enabled" in lighting and not isinstance(lighting["enabled"], bool):
                raise ValueError("lighting.enabled must be a boolean")
            transition_minutes = lighting.get("dawn_dusk_transition_minutes")
            if transition_minutes is not None and (
                not isinstance(transition_minutes, (int, float))
                or isinstance(transition_minutes, bool)
                or transition_minutes < 0
            ):
                raise ValueError("lighting.dawn_dusk_transition_minutes must be non-negative")
            brightness = lighting.get("day_brightness_by_season")
            if brightness is not None and (
                not isinstance(brightness, dict)
                or any(
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not 0 <= value <= 100
                    for value in brightness.values()
                )
            ):
                raise ValueError("lighting.day_brightness_by_season must contain percentages")
            steps = lighting.get("transition_steps")
            if steps is not None and (
                not isinstance(steps, list)
                or any(
                    not isinstance(step, dict)
                    or not isinstance(step.get("leds", {}), dict)
                    or not isinstance(step.get("minutes_from_start"), (int, float))
                    or step.get("minutes_from_start") < 0
                    or any(
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or not 0 <= value <= 100
                        for value in step.get("leds", {}).values()
                    )
                    for step in steps
                )
            ):
                raise ValueError("lighting.transition_steps must contain steps with a start time and LED object")

    def update_settings(self, settings: Dict[str, object]) -> None:
        """Apply editable settings without changing the rule engine."""
        self.validate_settings(settings)
        io_mapping = settings.get("io_mapping", {})
        if isinstance(io_mapping, dict):
            for direction, current in (
                ("inputs", self.io_inputs),
                ("outputs", self.io_outputs),
            ):
                configured = io_mapping.get(direction, {})
                if isinstance(configured, dict):
                    merged = {**current, **configured}
                    if len(set(merged.values())) != len(merged):
                        raise ValueError(f"io_mapping.{direction} channels must be unique")

        schedule = settings.get("schedule", {})
        if isinstance(schedule, dict):
            for key in ("sunrise", "sunset"):
                value = schedule.get(key)
                if isinstance(value, str):
                    try:
                        datetime.strptime(value, "%H:%M")
                    except ValueError:
                        continue
                    self.schedule[key] = value

        fan_control = settings.get("fan_control", {})
        if isinstance(fan_control, dict):
            thresholds = fan_control.get("temp_thresholds_c", {})
            levels = fan_control.get("fan_levels_percent", {})
            airflow = fan_control.get("minimum_airflow", {})
            if isinstance(thresholds, dict):
                for key in DEFAULT_FAN_THRESHOLDS:
                    value = thresholds.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        self.fan_thresholds[key] = float(value)
            if isinstance(levels, dict):
                for key in DEFAULT_FAN_LEVELS:
                    value = levels.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        self.fan_levels[key] = int(value)
            if isinstance(airflow, dict):
                enabled = airflow.get("enabled")
                percent = airflow.get("percent")
                interval = airflow.get("alternate_seconds")
                fans = airflow.get("fans")
                if isinstance(enabled, bool):
                    self.minimum_airflow_enabled = enabled
                if isinstance(percent, (int, float)) and not isinstance(percent, bool):
                    self.minimum_airflow_percent = int(percent)
                if isinstance(interval, (int, float)) and not isinstance(interval, bool) and interval > 0:
                    self.minimum_airflow_interval_seconds = int(interval)
                if isinstance(fans, list) and len(fans) == 2:
                    self.minimum_airflow_fans = (int(fans[0]), int(fans[1]))

        safety = settings.get("safety", {})
        if isinstance(safety, dict):
            heartbeat_timeout = safety.get("no_heartbeat_timeout_sec")
            if isinstance(heartbeat_timeout, (int, float)) and not isinstance(heartbeat_timeout, bool):
                self.heartbeat_timeout_seconds = int(heartbeat_timeout)
            for key in DEFAULT_HEATER_THRESHOLDS:
                value = safety.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.heater_thresholds[key] = float(value)
            float_overrides = safety.get("float_overrides")
            if isinstance(float_overrides, dict):
                for key, value in float_overrides.items():
                    if isinstance(value, bool):
                        self.float_overrides[key] = value
                    elif value is None:
                        self.float_overrides.pop(key, None)
                        for role, channel in self.io_inputs.items():
                            if key == channel:
                                self.float_overrides.pop(role, None)

        mistmaker_settings = settings.get("mistmaker", {})
        if isinstance(mistmaker_settings, dict):
            for key in ("enabled", "auto_mode"):
                value = mistmaker_settings.get(key)
                if isinstance(value, bool):
                    self.mistmaker_settings[key] = value
            for key in (
                "max_runtime_minutes",
                "pause_minutes",
                "morning_after_irrigation_minutes",
                "humidity_on_percent",
                "humidity_off_percent",
            ):
                value = mistmaker_settings.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.mistmaker_settings[key] = value
            if "humidity_on_percent" in mistmaker_settings:
                self.mistmaker_on_humidity = float(self.mistmaker_settings["humidity_on_percent"])
            if "humidity_off_percent" in mistmaker_settings:
                self.mistmaker_off_humidity = float(self.mistmaker_settings["humidity_off_percent"])

        irrigation_settings = settings.get("irrigation", {})
        if isinstance(irrigation_settings, dict):
            for key in ("enabled", "auto_mode"):
                value = irrigation_settings.get(key)
                if isinstance(value, bool):
                    self.irrigation_settings[key] = value
            for key in ("cycle_minutes", "duration_seconds", "max_runtime_minutes"):
                value = irrigation_settings.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.irrigation_settings[key] = value
            for key, attribute in (
                ("humidity_on_percent", "irrigation_on_humidity"),
                ("humidity_off_percent", "irrigation_off_humidity"),
            ):
                value = irrigation_settings.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    setattr(self, attribute, float(value))

        seasons = settings.get("seasons", {})
        if isinstance(seasons, dict):
            rainy = seasons.get("rainy", {})
            if isinstance(rainy, dict):
                rainstorm = rainy.get("rainstorm", {})
                if isinstance(rainstorm, dict):
                    for key, default in DEFAULT_RAINSTORM.items():
                        value = rainstorm.get(key)
                        if isinstance(value, bool) and isinstance(default, bool):
                            self.rainstorm[key] = value
                        elif isinstance(value, (int, float)) and not isinstance(value, bool):
                            self.rainstorm[key] = value

        lighting_settings = settings.get("lighting", {})
        if isinstance(lighting_settings, dict):
            for key in ("enabled", "dawn_dusk_transition_minutes", "day_brightness_by_season", "transition_steps"):
                value = lighting_settings.get(key)
                if value is not None:
                    self.lighting_settings[key] = value

        sensors = settings.get("sensors", {})
        if isinstance(sensors, dict):
            for key in ("temperature_prefixes", "humidity_prefixes", "labels"):
                value = sensors.get(key)
                if isinstance(value, list):
                    self.sensor_schema[key] = list(value)

        io_mapping = settings.get("io_mapping", {})
        if isinstance(io_mapping, dict):
            inputs = io_mapping.get("inputs")
            outputs = io_mapping.get("outputs")
            if isinstance(inputs, dict):
                self.io_inputs.update(inputs)
            if isinstance(outputs, dict):
                self.io_outputs.update(outputs)

        seasons = settings.get("seasons", {})
        if isinstance(seasons, dict) and seasons:
            self.seasons = dict(seasons)

    def replace_settings(self, settings: Dict[str, object]) -> None:
        """Replace the editable profile while retaining current sensor/runtime state."""
        self.validate_settings(settings)
        defaults = type(self)()
        for attribute in (
            "heartbeat_timeout_seconds",
            "sensor_schema",
            "io_inputs",
            "io_outputs",
            "seasons",
            "mistmaker_on_humidity",
            "mistmaker_off_humidity",
            "irrigation_on_humidity",
            "irrigation_off_humidity",
            "schedule",
            "lighting_settings",
            "fan_thresholds",
            "fan_levels",
            "heater_thresholds",
            "rainstorm",
            "minimum_airflow_percent",
            "minimum_airflow_interval_seconds",
            "minimum_airflow_enabled",
            "minimum_airflow_fans",
            "mistmaker_settings",
            "irrigation_settings",
            "float_overrides",
        ):
            setattr(self, attribute, deepcopy(getattr(defaults, attribute)))
        self.update_settings(settings)

    def output_key(self, role: str) -> str:
        """Return the configured Moxa output channel for an actuator role."""
        return self.io_outputs[role]

    def _input_value(self, role: str) -> Optional[bool]:
        channel = self.io_inputs[role]
        if channel in self.float_overrides:
            return self.float_overrides[channel]
        if role in self.float_overrides:
            return self.float_overrides[role]
        return self._di_value(channel)

    def active_season(self) -> str:
        """Return the first season enabled in the active JSON profile."""
        for name, settings in self.seasons.items():
            if isinstance(settings, dict) and settings.get("active") is True:
                return name
        return "rainy"

    def _sensor_prefixes(self, kind: str) -> tuple[str, ...]:
        prefixes = self.sensor_schema.get(f"{kind}_prefixes", [])
        if isinstance(prefixes, list):
            return tuple(prefix for prefix in prefixes if isinstance(prefix, str))
        return ()

    def _has_sensor_kind(self, sensor_name: str, kind: str) -> bool:
        return sensor_name.startswith(self._sensor_prefixes(kind))

    def update_sensor_state(self, payload: Dict[str, object]) -> Dict[str, object]:
        """Store the latest sensor measurements."""
        for key, value in payload.items():
            if isinstance(value, (int, float)):
                self.sensor_state[key] = float(value)
        return dict(self.sensor_state)

    def _di_value(self, key: str) -> Optional[bool]:
        """Read a Moxa digital input, applying overrides for floats not wired yet."""
        if key in self.float_overrides:
            return self.float_overrides[key]
        if self.moxa_state is None:
            return None
        return self.moxa_state.get(key)

    def _safety_alarm(self, state: Optional[Dict[str, object]] = None) -> bool:
        source = self.moxa_state if state is None else state
        return (
            (source is not None and source.get(self.io_inputs["leak"]) is True)
            or (source is not None and source.get("alarm") is True)
        )

    def evaluate_ro_command(self) -> Dict[str, object]:
        """Fill the RO reservoir via DO15 using hysteresis between the min/max floats."""
        output = self.output_key("ro_fill")
        if self.moxa_state is None:
            self.ro_filling = False
            return {output: "OFF", "reason": "moxa_status_unknown"}

        if self._safety_alarm():
            self.ro_filling = False
            return {output: "OFF", "reason": "leak_detected"}

        level_above_min = self._input_value("ro_minimum")
        level_at_max = self._input_value("ro_maximum")

        if level_at_max is True:
            self.ro_filling = False
        elif level_above_min is False:
            self.ro_filling = True

        return {
            output: "ON" if self.ro_filling else "OFF",
            "reason": "filling" if self.ro_filling else "idle",
        }

    def evaluate_moxa_state(self, payload: Dict[str, object]) -> Dict[str, object]:
        """Apply safety rules from the Moxa digital inputs."""
        self.moxa_state = dict(payload)
        if self._safety_alarm(payload):
            self.mistmaker_run_until = 0.0
            self.mistmaker_morning_start_at = 0.0
            self.mistmaker_morning_run_until = 0.0
            self.irrigation_run_until = 0.0
            self.irrigation_morning_run_until = 0.0
            self.ro_filling = False
            return {
                "mistmaker": "OFF",
                "beregening": "OFF",
                self.output_key("irrigation"): "OFF",
                self.output_key("mistmaker"): "OFF",
                self.output_key("heater"): "OFF",
                self.output_key("ro_fill"): "OFF",
                "alarm": True,
                "reason": "leak_detected",
            }

        mist_reservoir_ok = self._input_value("mist_reservoir") is not False
        irrigation_reservoir_ok = self._input_value("irrigation_reservoir") is not False
        reservoir_alarm = not mist_reservoir_ok or not irrigation_reservoir_ok
        actions: Dict[str, object] = {
            self.output_key("heater"): self.evaluate_heater_command()["state"],
            self.output_key("ro_fill"): self.evaluate_ro_command()[self.output_key("ro_fill")],
            "alarm": reservoir_alarm,
            "reason": "reservoir_low" if reservoir_alarm else "normal",
        }
        if not mist_reservoir_ok:
            actions.update({"mistmaker": "OFF", self.output_key("mistmaker"): "OFF"})
        if not irrigation_reservoir_ok:
            actions.update({"beregening": "OFF", self.output_key("irrigation"): "OFF"})
        return actions

    def _evaluate_mist_cycle(self, humidity: Optional[float], reservoir_ok: bool, rainstorm_active: bool, now: float) -> tuple[str, str]:
        """Run the mistmaker for max_runtime_minutes, then pause for pause_minutes."""
        if not reservoir_ok or not self.mistmaker_settings.get("enabled", True):
            self.mistmaker_run_until = 0.0
            return "OFF", "reservoir_low" if not reservoir_ok else "disabled"
        if rainstorm_active:
            return "ON", "rainstorm"
        if humidity is not None and humidity >= self.mistmaker_off_humidity:
            self.mistmaker_run_until = 0.0
            return "OFF", "humidity_ok"
        if now < self.mistmaker_run_until:
            return "ON", "cycle_running"
        if now >= self.mistmaker_pause_until and (humidity is None or humidity < self.mistmaker_on_humidity):
            runtime = max(0.0, float(self.mistmaker_settings.get("max_runtime_minutes", 30))) * 60
            pause = max(0.0, float(self.mistmaker_settings.get("pause_minutes", 8))) * 60
            self.mistmaker_run_until = now + runtime
            self.mistmaker_pause_until = self.mistmaker_run_until + pause
            return "ON", "cycle_start"
        return "OFF", "cycle_pause"

    def _evaluate_irrigation_cycle(
        self,
        humidity: Optional[float],
        reservoir_ok: bool,
        rainstorm_active: bool,
        now: float,
        current_datetime: datetime,
    ) -> tuple[str, str]:
        """Run irrigation on low average humidity and once before daily sunrise."""
        if not reservoir_ok or not self.irrigation_settings.get("enabled", True):
            self.irrigation_run_until = 0.0
            self.irrigation_morning_run_until = 0.0
            return "OFF", "reservoir_low" if not reservoir_ok else "disabled"
        if rainstorm_active:
            return "ON", "rainstorm"

        sunrise = datetime.strptime(self.schedule["sunrise"], "%H:%M").time()
        sunrise_today = datetime.combine(current_datetime.date(), sunrise)
        duration = max(0.0, float(self.irrigation_settings.get("duration_seconds", 25)))
        morning_start = sunrise_today.timestamp() - duration
        if (
            self.irrigation_morning_date != current_datetime.date()
            and morning_start <= now < sunrise_today.timestamp()
        ):
            self.irrigation_morning_date = current_datetime.date()
            self.irrigation_morning_run_until = sunrise_today.timestamp()
            self.mistmaker_morning_start_at = sunrise_today.timestamp()
            morning_mist_minutes = max(
                0.0,
                float(self.mistmaker_settings.get("morning_after_irrigation_minutes", 20)),
            )
            self.mistmaker_morning_run_until = (
                sunrise_today.timestamp() + morning_mist_minutes * 60
            )
            cycle = max(0.0, float(self.irrigation_settings.get("cycle_minutes", 20))) * 60
            self.irrigation_next_cycle = now + cycle

        if now < self.irrigation_morning_run_until:
            return "ON", "morning_cycle"

        if humidity is not None and humidity >= self.irrigation_off_humidity:
            self.irrigation_run_until = 0.0
            return "OFF", "humidity_ok"
        if now < self.irrigation_run_until:
            return "ON", "cycle_running"
        if (
            humidity is not None
            and humidity < self.irrigation_on_humidity
            and now >= self.irrigation_next_cycle
        ):
            cycle = max(0.0, float(self.irrigation_settings.get("cycle_minutes", 20))) * 60
            self.irrigation_run_until = now + duration
            self.irrigation_next_cycle = now + cycle
            return "ON", "cycle_start"
        return "OFF", "cycle_wait"

    def evaluate_scheduled_morning_mistmaker(self, now: Optional[float] = None) -> Optional[str]:
        """Run DO5 after the scheduled morning irrigation, then resume RH control."""
        current_time = time.time() if now is None else now
        if self.mistmaker_morning_run_until <= 0:
            return None

        reservoir_ok = self._input_value("mist_reservoir") is not False
        safety_ok = (
            self.moxa_state is not None
            and not self._safety_alarm()
            and reservoir_ok
            and self.mistmaker_settings.get("enabled", True)
        )
        if not safety_ok:
            self.mistmaker_morning_start_at = 0.0
            self.mistmaker_morning_run_until = 0.0
            return "OFF"
        if current_time < self.mistmaker_morning_start_at:
            return None
        if current_time < self.mistmaker_morning_run_until:
            return "ON"

        self.mistmaker_morning_start_at = 0.0
        self.mistmaker_morning_run_until = 0.0
        humidity_values = [
            value for key, value in self.sensor_state.items()
            if self._has_sensor_kind(key, "humidity")
        ]
        humidity = sum(humidity_values) / len(humidity_values) if humidity_values else None
        rainstorm_active = current_time < self.rainstorm_until
        mistmaker, _reason = self._evaluate_mist_cycle(
            humidity,
            reservoir_ok,
            rainstorm_active,
            current_time,
        )
        return mistmaker

    def evaluate_irrigation_command(
        self,
        now: Optional[float] = None,
        rainstorm_active: Optional[bool] = None,
    ) -> str:
        """Evaluate only DO4, without advancing other actuator schedules."""
        current_time = time.time() if now is None else now
        if self.moxa_state is None or self._safety_alarm():
            self.irrigation_run_until = 0.0
            self.irrigation_morning_run_until = 0.0
            return "OFF"

        humidity_values = [
            value for key, value in self.sensor_state.items()
            if self._has_sensor_kind(key, "humidity")
        ]
        humidity = sum(humidity_values) / len(humidity_values) if humidity_values else None
        reservoir_ok = self._input_value("irrigation_reservoir") is not False
        active_rainstorm = (
            current_time < self.rainstorm_until
            if rainstorm_active is None
            else rainstorm_active
        )
        irrigation, _reason = self._evaluate_irrigation_cycle(
            humidity,
            reservoir_ok,
            active_rainstorm,
            current_time,
            datetime.fromtimestamp(current_time),
        )
        return irrigation

    def evaluate_moxa_outputs(self, now: Optional[float] = None) -> Dict[str, object]:
        """Translate the latest sensors to configured Moxa outputs."""
        current_time = time.time() if now is None else now
        humidity_values = [
            value for key, value in self.sensor_state.items()
            if self._has_sensor_kind(key, "humidity")
        ]
        if self.moxa_state is not None and self._safety_alarm():
            self.mistmaker_run_until = 0.0
            self.irrigation_run_until = 0.0
            self.irrigation_morning_run_until = 0.0
            self.mistmaker_morning_start_at = 0.0
            self.mistmaker_morning_run_until = 0.0
            self.ro_filling = False
            return {
                self.output_key("irrigation"): "OFF",
                self.output_key("mistmaker"): "OFF",
                self.output_key("heater"): "OFF",
                self.output_key("ro_fill"): "OFF",
                "mistmaker": "OFF",
                "beregening": "OFF",
                "alarm": True,
                "reason": "leak_detected",
            }

        if self.moxa_state is None:
            return {
                self.output_key("irrigation"): "OFF",
                self.output_key("mistmaker"): "OFF",
                self.output_key("heater"): self.evaluate_heater_command()["state"],
                self.output_key("ro_fill"): "OFF",
                "mistmaker": "OFF",
                "beregening": "OFF",
                "alarm": True,
                "reason": "moxa_status_unknown",
            }

        humidity = sum(humidity_values) / len(humidity_values) if humidity_values else None
        mist_reservoir_ok = self._input_value("mist_reservoir") is not False
        irrigation_reservoir_ok = self._input_value("irrigation_reservoir") is not False

        rainstorm = self.evaluate_rainstorm()
        mistmaker, _mist_reason = self._evaluate_mist_cycle(humidity, mist_reservoir_ok, rainstorm["active"], current_time)
        if (
            mist_reservoir_ok
            and self.mistmaker_settings.get("enabled", True)
            and self.mistmaker_morning_start_at <= current_time < self.mistmaker_morning_run_until
        ):
            mistmaker = "ON"
        irrigation = self.evaluate_irrigation_command(
            now=current_time,
            rainstorm_active=bool(rainstorm["active"]),
        )

        reservoir_alarm = not mist_reservoir_ok or not irrigation_reservoir_ok

        return {
            self.output_key("irrigation"): irrigation,
            self.output_key("mistmaker"): mistmaker,
            self.output_key("heater"): self.evaluate_heater_command()["state"],
            self.output_key("ro_fill"): self.evaluate_ro_command()[self.output_key("ro_fill")],
            "mistmaker": mistmaker,
            "beregening": irrigation,
            "alarm": reservoir_alarm,
            "reason": (
                "reservoir_low" if reservoir_alarm
                else "rainstorm" if rainstorm["active"]
                else "sensor_control"
            ),
        }

    def evaluate_rainstorm(
        self,
        season: Optional[str] = None,
        now: Optional[float] = None,
        random_value: Optional[float] = None,
    ) -> Dict[str, object]:
        """Start a random short rainstorm during the configured rainy season."""
        import time

        current_time = time.time() if now is None else now
        season = self.active_season() if season is None else season
        irrigation_output = self.output_key("irrigation")
        mistmaker_output = self.output_key("mistmaker")
        inactive = {
            "active": False,
            irrigation_output: "OFF",
            mistmaker_output: "OFF",
            "reason": "inactive",
        }
        if season != "rainy" or not self.rainstorm.get("enabled", False):
            return inactive
        if self.moxa_state is not None and (
            self._safety_alarm()
            or self.moxa_state.get(self.io_inputs["mist_reservoir"]) is False
            or self.moxa_state.get(self.io_inputs["irrigation_reservoir"]) is False
        ):
            return {**inactive, "reason": "safety_block"}
        if current_time < self.rainstorm_until:
            return {
                "active": True,
                irrigation_output: "ON",
                mistmaker_output: "ON",
                "reason": "rainstorm",
            }
        if current_time < self.rainstorm_cooldown_until:
            return {**inactive, "reason": "cooldown"}

        chance = float(self.rainstorm.get("chance_percent", 0.0)) / 100.0
        if (self.random_source() if random_value is None else random_value) >= chance:
            return inactive

        duration = max(1.0, float(self.rainstorm.get("duration_minutes", 2))) * 60
        cooldown = max(0.0, float(self.rainstorm.get("cooldown_minutes", 30))) * 60
        self.rainstorm_until = current_time + duration
        self.rainstorm_cooldown_until = self.rainstorm_until + cooldown
        return {
            "active": True,
            irrigation_output: "ON",
            mistmaker_output: "ON",
            "reason": "rainstorm",
        }

    def evaluate_heater_command(self) -> Dict[str, object]:
        """Switch the Moxa warmtelamp on only below the configured minimum."""
        temperatures = [
            value for key, value in self.sensor_state.items()
            if self._has_sensor_kind(key, "temperature")
        ]
        if not temperatures:
            return {
                "state": "OFF",
                self.output_key("heater"): "OFF",
                "reason": "no_temperature",
            }

        average_temperature = sum(temperatures) / len(temperatures)
        if average_temperature < self.heater_thresholds["temperature_too_low_c"]:
            state = "ON"
            reason = "temperature_too_low"
        elif average_temperature >= self.heater_thresholds["temperature_too_high_c"]:
            state = "OFF"
            reason = "temperature_too_high"
        else:
            state = "OFF"
            reason = "temperature_normal"

        if self.moxa_state is not None and self._safety_alarm():
            state = "OFF"
            reason = "safety_alarm"

        return {"state": state, self.output_key("heater"): state, "reason": reason}

    def evaluate_fan_command(self, now: Optional[float] = None) -> Dict[str, object]:
        """Compute a safe fan level from the current average temperature."""
        current_time = time.time() if now is None else now
        active_minimum_fan = None
        if self.minimum_airflow_enabled:
            active_minimum_fan = self.minimum_airflow_fans[
                int(current_time / self.minimum_airflow_interval_seconds) % 2
            ]
        if not self.sensor_state:
            level = 0
            return self._apply_fan_overrides(self._fan_command(level, active_minimum_fan), current_time)

        temps = [
            float(value)
            for key, value in self.sensor_state.items()
            if self._has_sensor_kind(key, "temperature")
            and isinstance(value, (int, float))
        ]

        if not temps:
            return self._apply_fan_overrides(self._fan_command(0, active_minimum_fan), current_time)

        average_temp = sum(temps) / len(temps)

        if average_temp < self.fan_thresholds["low"]:
            level = self.fan_levels["off"]
        elif average_temp < self.fan_thresholds["medium"]:
            level = self.fan_levels["low"]
        elif average_temp < self.fan_thresholds["high"]:
            level = self.fan_levels["medium"]
        elif average_temp < self.fan_thresholds["max_safe"]:
            level = self.fan_levels["high"]
        else:
            level = self.fan_levels["max"]

        return self._apply_fan_overrides(self._fan_command(int(level), active_minimum_fan), current_time)

    def set_fan_override(
        self,
        channels: Dict[str, int],
        level: int = 0,
        duration_minutes: Optional[float] = None,
        fan_name: Optional[str] = None,
    ) -> Dict[str, object]:
        """Hold one or more manual fan levels until they expire or Auto is restored."""
        expires_at = None
        if duration_minutes is not None:
            expires_at = time.time() + max(0.0, float(duration_minutes)) * 60
        targets = [fan_name] if fan_name else [f"fan{number}" for number in range(1, 7)]
        for target in targets:
            self.manual_fan_overrides[target] = {"level": max(0, min(100, int(channels.get(target, level)))), "expires_at": expires_at}
        return self.evaluate_fan_command()

    def clear_fan_override(self, fan_name: Optional[str] = None) -> None:
        """Return fan control to the automatic climate rules."""
        if fan_name:
            self.manual_fan_overrides.pop(fan_name, None)
        else:
            self.manual_fan_overrides.clear()

    def fan_override_expiry(self, fan_name: str) -> Optional[float]:
        override = self.manual_fan_overrides.get(fan_name)
        return None if override is None else override.get("expires_at")

    def set_led_override(self, led_name: str, brightness: int, duration_minutes: Optional[float] = None) -> None:
        """Hold one LED brightness until it expires or Auto is restored."""
        expires_at = None
        if duration_minutes is not None:
            expires_at = time.time() + max(0.0, float(duration_minutes)) * 60
        self.manual_led_overrides[led_name] = {
            "brightness": max(0, min(100, int(brightness))),
            "expires_at": expires_at,
        }

    def clear_led_override(self, led_name: str) -> None:
        """Return one LED to its automatic schedule."""
        self.manual_led_overrides.pop(led_name, None)

    def led_override_expiry(self, led_name: str) -> Optional[float]:
        override = self.manual_led_overrides.get(led_name)
        return None if override is None else override.get("expires_at")

    def _apply_led_overrides(self, leds: Dict[str, int]) -> Dict[str, int]:
        current_time = time.time()
        result = dict(leds)
        for led_name, override in list(self.manual_led_overrides.items()):
            expires_at = override.get("expires_at")
            if expires_at is not None and current_time >= float(expires_at):
                self.manual_led_overrides.pop(led_name, None)
                continue
            if led_name in result:
                result[led_name] = int(override["brightness"])
        return result

    def _light_command(self, leds: Dict[str, int]) -> Dict[str, object]:
        applied_leds = self._apply_led_overrides(leds)
        brightness = max(applied_leds.values())
        return {
            "state": "on" if brightness else "off",
            "brightness": brightness,
            "leds": applied_leds,
            "overrides": {name: item.get("expires_at") for name, item in self.manual_led_overrides.items()},
        }

    def _fan_command(self, level: int, active_minimum_fan: Optional[int]) -> Dict[str, object]:
        """Keep one of the two end fans moving to prevent stagnant air."""
        if self.minimum_airflow_enabled:
            level = max(int(level), self.minimum_airflow_percent)
        channels = {f"fan{number}": int(level) for number in range(1, 7)}
        if self.minimum_airflow_enabled:
            for fan_number in self.minimum_airflow_fans:
                channels[f"fan{fan_number}"] = (
                    self.minimum_airflow_percent
                    if fan_number == active_minimum_fan
                    else 0
                )
        return {
            "mode": "auto",
            "level": level,
            "channels": channels,
            "minimum_airflow": {
                "enabled": self.minimum_airflow_enabled,
                "active_fan": active_minimum_fan,
                "percent": self.minimum_airflow_percent,
            },
        }

    def _apply_fan_overrides(self, command: Dict[str, object], current_time: float) -> Dict[str, object]:
        channels = dict(command["channels"])
        active_overrides: Dict[str, object] = {}
        for fan_name, override in list(self.manual_fan_overrides.items()):
            expires_at = override.get("expires_at")
            if expires_at is not None and current_time >= float(expires_at):
                self.manual_fan_overrides.pop(fan_name, None)
                continue
            channels[fan_name] = int(override["level"])
            active_overrides[fan_name] = expires_at
        if not active_overrides:
            return command
        return {**command, "mode": "manual", "channels": channels, "overrides": active_overrides}

    def update_heartbeat(self, timestamp: int) -> None:
        """Record the last successful ESP32 heartbeat timestamp."""
        self.last_heartbeat = timestamp

    def evaluate_esp32_health(self, now: Optional[int] = None) -> Dict[str, object]:
        """Return offline/alarm state when ESP32 stops transmitting."""
        if now is None:
            import time

            now = int(time.time())

        if self.last_heartbeat is None:
            return {
                "status": "offline",
                "alarm": True,
                "reason": "no_heartbeat_received",
            }

        if self.last_heartbeat > now:
            return {
                "status": "offline",
                "alarm": True,
                "reason": "heartbeat_in_future",
            }

        age = now - self.last_heartbeat
        if age > self.heartbeat_timeout_seconds:
            return {
                "status": "offline",
                "alarm": True,
                "reason": f"heartbeat_timeout_{age}s",
            }

        return {
            "status": "online",
            "alarm": False,
            "reason": "heartbeat_ok",
        }

    def evaluate_light_transition(
        self,
        time_str: str,
        season: Optional[str] = None,
    ) -> Dict[str, int]:
        """Return the configured per-LED dimming profile for the current dawn phase."""
        try:
            hour, minute = [int(part) for part in time_str.split(":")]
            total_minutes = hour * 60 + minute
        except (TypeError, ValueError):
            return self._dark_leds()
        season = self.active_season() if season is None else season
        sunrise_hour, sunrise_minute = map(int, self.schedule["sunrise"].split(":"))
        elapsed = total_minutes - (sunrise_hour * 60 + sunrise_minute)
        return self._scheduled_dawn_profile(elapsed, season)

    def evaluate_light_command(
        self,
        time_str: str,
        season: Optional[str] = None,
    ) -> Dict[str, object]:
        """Build the lighting command from the configured schedule and season profile."""
        try:
            hour, minute = [int(part) for part in time_str.split(":")]
            total_minutes = hour * 60 + minute
        except (TypeError, ValueError):
            return self._light_command(self._dark_leds())

        season = self.active_season() if season is None else season
        if not self.lighting_settings.get("enabled", True):
            return self._light_command(self._dark_leds())

        sunrise_hour, sunrise_minute = map(int, self.schedule["sunrise"].split(":"))
        sunset_hour, sunset_minute = map(int, self.schedule["sunset"].split(":"))
        sunrise = sunrise_hour * 60 + sunrise_minute
        sunset = sunset_hour * 60 + sunset_minute
        transition = max(
            0, int(self.lighting_settings.get("dawn_dusk_transition_minutes", 20))
        )
        if total_minutes < sunrise or total_minutes >= sunset + transition:
            return self._light_command(self._dark_leds())

        if transition and total_minutes < sunrise + transition:
            leds = self._scheduled_dawn_profile(total_minutes - sunrise, season)
        elif total_minutes >= sunset:
            elapsed = total_minutes - sunset
            factor = max(0.0, 1.0 - (elapsed / max(transition, 1)))
            target = self._season_brightness(season)
            leds = {
                key: int(target * factor)
                for key in ("led1", "led2", "led3", "led4")
            }
        else:
            target = self._season_brightness(season)
            leds = {key: target for key in ("led1", "led2", "led3", "led4")}

        return self._light_command(leds)
    def evaluate_moxa_light_outputs(
        self,
        time_str: str,
        season: Optional[str] = None,
    ) -> Dict[str, object]:
        """Build Moxa power commands for the four LED driver outputs."""
        light = self.evaluate_light_command(time_str, season)
        leds = light["leds"]

        return {
            self.output_key("led1"): "ON" if leds["led1"] > 0 else "OFF",
            self.output_key("led2"): "ON" if leds["led2"] > 0 else "OFF",
            self.output_key("led3"): "ON" if leds["led3"] > 0 else "OFF",
            self.output_key("led4"): "ON" if leds["led4"] > 0 else "OFF",
            "state": light["state"],
            "brightness": light["brightness"],
        }

    @staticmethod
    def _dark_leds() -> Dict[str, int]:
        return {key: 0 for key in ("led1", "led2", "led3", "led4")}

    def _season_brightness(self, season: Optional[str]) -> int:
        season = self.active_season() if season is None else season
        brightness = self.lighting_settings.get("day_brightness_by_season", {})
        if isinstance(brightness, dict):
            value = brightness.get(season)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return max(0, min(100, int(value)))
        return 75

    def _scheduled_dawn_profile(
        self,
        elapsed: int,
        season: Optional[str],
    ) -> Dict[str, int]:
        """Select the last configured lighting step reached before this time."""
        steps = self.lighting_settings.get("transition_steps", [])
        if not isinstance(steps, list) or not steps:
            target = self._season_brightness(season)
            return {key: target for key in ("led1", "led2", "led3", "led4")}

        profile: Dict[str, int] = self._dark_leds()
        for step in sorted(
            (item for item in steps if isinstance(item, dict)),
            key=lambda item: float(item.get("minutes_from_start", 0)),
        ):
            start = float(step.get("minutes_from_start", 0))
            if elapsed < start:
                break
            leds = step.get("leds", {})
            if isinstance(leds, dict):
                profile = {
                    key: int(value)
                    for key, value in leds.items()
                    if key in ("led1", "led2", "led3", "led4")
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                }
                profile = {
                    key: profile.get(key, 0) for key in ("led1", "led2", "led3", "led4")
                }

        target = self._season_brightness(season)
        if elapsed >= max(
            0, int(self.lighting_settings.get("dawn_dusk_transition_minutes", 20))
        ):
            return {key: target for key in ("led1", "led2", "led3", "led4")}
        return profile

    @staticmethod
    def _minutes_to_time(total_minutes: int) -> str:
        hour, minute = divmod(total_minutes, 60)
        return f"{hour:02d}:{minute:02d}"
