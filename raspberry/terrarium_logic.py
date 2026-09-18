"""Pi-side terrarium control logic.

This module contains the core rules used by the Raspberry Pi to translate
MQTT status messages from the ESP32 and Moxa into safety actions and fan
control commands.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Dict, Optional


DEFAULT_FAN_THRESHOLDS = {
    "low": 22.0,
    "medium": 24.5,
    "high": 27.0,
    "max_safe": 30.0,
}
DEFAULT_FAN_LEVELS = {
    "off": 0,
    "low": 20,
    "medium": 35,
    "high": 55,
    "max": 70,
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


class TerrariumLogic:
    """Evaluate safety and climate rules for the terrarium."""

    def __init__(self, settings: Optional[Dict[str, object]] = None) -> None:
        self.sensor_state: Dict[str, float] = {}
        self.moxa_state: Optional[Dict[str, object]] = None
        self.last_heartbeat: Optional[int] = None
        self.heartbeat_timeout_seconds = 180
        self.mistmaker_on_humidity = 82.0
        self.mistmaker_off_humidity = 90.0
        self.irrigation_on_soil = 35.0
        self.irrigation_off_soil = 55.0
        self.fan_thresholds: Dict[str, float] = dict(DEFAULT_FAN_THRESHOLDS)
        self.fan_levels: Dict[str, int] = dict(DEFAULT_FAN_LEVELS)
        self.heater_thresholds: Dict[str, float] = dict(DEFAULT_HEATER_THRESHOLDS)
        self.rainstorm: Dict[str, object] = dict(DEFAULT_RAINSTORM)
        self.rainstorm_until = 0.0
        self.rainstorm_cooldown_until = 0.0
        self.random_source: Callable[[], float] = random.random
        self.minimum_airflow_percent = 25
        self.minimum_airflow_interval_seconds = 60
        if settings is not None:
            self.update_settings(settings)

    def update_settings(self, settings: Dict[str, object]) -> None:
        """Apply editable settings without changing the rule engine."""
        fan_control = settings.get("fan_control", {})
        if isinstance(fan_control, dict):
            thresholds = fan_control.get("temp_thresholds_c", {})
            levels = fan_control.get("fan_levels_percent", {})
            if isinstance(thresholds, dict):
                for key in DEFAULT_FAN_THRESHOLDS:
                    value = thresholds.get(key)
                    if isinstance(value, (int, float)):
                        self.fan_thresholds[key] = float(value)
            if isinstance(levels, dict):
                for key in DEFAULT_FAN_LEVELS:
                    value = levels.get(key)
                    if isinstance(value, (int, float)):
                        self.fan_levels[key] = int(value)

        safety = settings.get("safety", {})
        if isinstance(safety, dict):
            for key in DEFAULT_HEATER_THRESHOLDS:
                value = safety.get(key)
                if isinstance(value, (int, float)):
                    self.heater_thresholds[key] = float(value)

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

    def update_sensor_state(self, payload: Dict[str, object]) -> Dict[str, object]:
        """Store the latest sensor measurements."""
        for key, value in payload.items():
            if isinstance(value, (int, float)):
                self.sensor_state[key] = float(value)
        return dict(self.sensor_state)

    def evaluate_moxa_state(self, payload: Dict[str, object]) -> Dict[str, object]:
        """Apply safety rules from the Moxa digital inputs."""
        self.moxa_state = dict(payload)
        if payload.get("di2") is True or payload.get("alarm") is True:
            return {
                "mistmaker": "OFF",
                "beregening": "OFF",
                "do4": "OFF",
                "do5": "OFF",
                "do6": "OFF",
                "alarm": True,
                "reason": "leak_detected",
            }

        mistmaker = "OFF" if payload.get("di0") is False else "ON"
        irrigation = "OFF" if payload.get("di1") is False else "ON"
        reservoir_alarm = mistmaker == "OFF" or irrigation == "OFF"

        return {
            "mistmaker": mistmaker,
            "beregening": irrigation,
            "do4": irrigation,
            "do5": mistmaker,
            "do6": self.evaluate_heater_command()["state"],
            "alarm": reservoir_alarm,
            "reason": "reservoir_low" if reservoir_alarm else "normal",
        }

    def evaluate_moxa_outputs(self) -> Dict[str, object]:
        """Translate the latest sensors to Moxa DO4/DO5 commands."""
        humidity_values = [
            value for key, value in self.sensor_state.items()
            if key.startswith("humidity_")
        ]
        soil_values = [
            value for key, value in self.sensor_state.items()
            if key.startswith("soil_")
        ]

        if self.moxa_state is not None and (
            self.moxa_state.get("di2") is True or self.moxa_state.get("alarm") is True
        ):
            return {
                "do4": "OFF",
                "do5": "OFF",
                "do6": "OFF",
                "mistmaker": "OFF",
                "beregening": "OFF",
                "alarm": True,
                "reason": "leak_detected",
            }

        if self.moxa_state is None:
            return {
                "do4": "OFF",
                "do5": "OFF",
                "do6": self.evaluate_heater_command()["state"],
                "mistmaker": "OFF",
                "beregening": "OFF",
                "alarm": True,
                "reason": "moxa_status_unknown",
            }

        humidity = sum(humidity_values) / len(humidity_values) if humidity_values else None
        soil = sum(soil_values) / len(soil_values) if soil_values else None
        mistmaker = "OFF"
        irrigation = "OFF"

        rainstorm = self.evaluate_rainstorm()
        if rainstorm["active"]:
            mistmaker = "ON"
            irrigation = "ON"

        if humidity is not None:
            mistmaker = "ON" if humidity < self.mistmaker_on_humidity else "OFF"
            if humidity >= self.mistmaker_off_humidity:
                mistmaker = "OFF"

        if soil is not None:
            irrigation = "ON" if soil < self.irrigation_on_soil else "OFF"
            if soil >= self.irrigation_off_soil:
                irrigation = "OFF"

        if self.moxa_state is not None:
            if self.moxa_state.get("di0") is False:
                mistmaker = "OFF"
            if self.moxa_state.get("di1") is False:
                irrigation = "OFF"

        reservoir_alarm = (
            self.moxa_state is not None
            and (self.moxa_state.get("di0") is False or self.moxa_state.get("di1") is False)
        )

        return {
            "do4": irrigation,
            "do5": mistmaker,
            "do6": self.evaluate_heater_command()["state"],
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
        season: str = "rainy",
        now: Optional[float] = None,
        random_value: Optional[float] = None,
    ) -> Dict[str, object]:
        """Start a random short rainstorm during the configured rainy season."""
        import time

        current_time = time.time() if now is None else now
        inactive = {"active": False, "do4": "OFF", "do5": "OFF", "reason": "inactive"}
        if season != "rainy" or not self.rainstorm.get("enabled", False):
            return inactive
        if self.moxa_state is not None and (
            self.moxa_state.get("di2") is True
            or self.moxa_state.get("alarm") is True
            or self.moxa_state.get("di0") is False
            or self.moxa_state.get("di1") is False
        ):
            return {**inactive, "reason": "safety_block"}
        if current_time < self.rainstorm_until:
            return {"active": True, "do4": "ON", "do5": "ON", "reason": "rainstorm"}
        if current_time < self.rainstorm_cooldown_until:
            return {**inactive, "reason": "cooldown"}

        chance = float(self.rainstorm.get("chance_percent", 0.0)) / 100.0
        if (self.random_source() if random_value is None else random_value) >= chance:
            return inactive

        duration = max(1.0, float(self.rainstorm.get("duration_minutes", 2))) * 60
        cooldown = max(0.0, float(self.rainstorm.get("cooldown_minutes", 30))) * 60
        self.rainstorm_until = current_time + duration
        self.rainstorm_cooldown_until = self.rainstorm_until + cooldown
        return {"active": True, "do4": "ON", "do5": "ON", "reason": "rainstorm"}

    def evaluate_heater_command(self) -> Dict[str, object]:
        """Switch the Moxa warmtelamp on only below the configured minimum."""
        temperatures = [
            value for key, value in self.sensor_state.items()
            if key.startswith("temperature")
        ]
        if not temperatures:
            return {"state": "OFF", "do6": "OFF", "reason": "no_temperature"}

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

        if self.moxa_state is not None and (
            self.moxa_state.get("di2") is True or self.moxa_state.get("alarm") is True
        ):
            state = "OFF"
            reason = "safety_alarm"

        return {"state": state, "do6": state, "reason": reason}

    def evaluate_fan_command(self, now: Optional[float] = None) -> Dict[str, object]:
        """Compute a safe fan level from the current average temperature."""
        current_time = time.time() if now is None else now
        active_minimum_fan = 1 if int(current_time / self.minimum_airflow_interval_seconds) % 2 == 0 else 6
        if not self.sensor_state:
            level = 0
            return self._fan_command(level, active_minimum_fan)

        temps = [
            float(value)
            for key, value in self.sensor_state.items()
            if key.startswith("temperature") and isinstance(value, (int, float))
        ]

        if not temps:
            return self._fan_command(0, active_minimum_fan)

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

        return self._fan_command(int(level), active_minimum_fan)

    def _fan_command(self, level: int, active_minimum_fan: int) -> Dict[str, object]:
        """Keep one of the two end fans moving to prevent stagnant air."""
        fan1 = self.minimum_airflow_percent if active_minimum_fan == 1 else 0
        fan6 = self.minimum_airflow_percent if active_minimum_fan == 6 else 0
        return {
            "mode": "auto",
            "level": int(level),
            "channels": {
                "fan1": fan1,
                "fan6": fan6,
            },
            "minimum_airflow": {
                "enabled": True,
                "active_fan": active_minimum_fan,
                "percent": self.minimum_airflow_percent,
            },
        }

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

    def evaluate_light_transition(self, time_str: str, season: str = "rainy") -> Dict[str, int]:
        """Return the per-LED dimming profile for the 20-minute dawn/dusk transition."""
        try:
            hour, minute = [int(part) for part in time_str.split(":")]
            total_minutes = hour * 60 + minute
        except Exception:
            return {
                "led1": 0,
                "led2": 0,
                "led3": 0,
                "led4": 0,
            }

        season_target = 80 if season == "rainy" else 100

        if total_minutes < 5 * 60 + 50:
            return {"led1": 0, "led2": 20, "led3": 0, "led4": 0}

        if total_minutes < 6 * 60 + 10:
            return {"led1": 0, "led2": 20, "led3": 20, "led4": 0}

        if total_minutes < 6 * 60 + 20:
            return {"led1": 20, "led2": 40, "led3": 40, "led4": 20}

        if total_minutes < 6 * 60 + 30:
            return {"led1": 40, "led2": 60, "led3": 60, "led4": 40}

        if total_minutes < 7 * 60:
            return {
                "led1": season_target,
                "led2": season_target,
                "led3": season_target,
                "led4": season_target,
            }

        return {
            "led1": season_target,
            "led2": season_target,
            "led3": season_target,
            "led4": season_target,
        }

    def evaluate_light_command(self, time_str: str, season: str = "rainy") -> Dict[str, object]:
        """Build the lighting command for the current Costa Rica day cycle."""
        try:
            hour, minute = [int(part) for part in time_str.split(":")]
            total_minutes = hour * 60 + minute
        except Exception:
            return {"state": "off", "brightness": 0, "leds": self._dark_leds()}

        sunrise = 5 * 60 + 45
        sunset = 18 * 60 + 15
        transition = 20
        if total_minutes < sunrise or total_minutes >= sunset + transition:
            return {"state": "off", "brightness": 0, "leds": self._dark_leds()}

        if total_minutes < sunrise + transition:
            leds = self._scheduled_dawn_profile(total_minutes - sunrise, season)
        elif total_minutes >= sunset:
            dawn_profile = self.evaluate_light_transition(
                self._minutes_to_time(sunrise + transition), season=season
            )
            elapsed = total_minutes - sunset
            factor = max(0.0, 1.0 - (elapsed / transition))
            leds = {
                key: int(value * factor)
                for key, value in dawn_profile.items()
            }
        else:
            target = 80 if season == "rainy" else 100
            leds = {key: target for key in ("led1", "led2", "led3", "led4")}

        brightness = max(leds.values())
        return {
            "state": "on" if brightness else "off",
            "brightness": brightness,
            "leds": leds,
        }

    @staticmethod
    def _dark_leds() -> Dict[str, int]:
        return {key: 0 for key in ("led1", "led2", "led3", "led4")}

    @staticmethod
    def _scheduled_dawn_profile(elapsed: int, season: str) -> Dict[str, int]:
        target = 80 if season == "rainy" else 100
        profiles = (
            {"led1": 0, "led2": 20, "led3": 0, "led4": 0},
            {"led1": 0, "led2": 20, "led3": 20, "led4": 0},
            {"led1": 20, "led2": 40, "led3": 40, "led4": 20},
            {"led1": 40, "led2": 60, "led3": 60, "led4": 40},
            {"led1": target, "led2": target, "led3": target, "led4": target},
        )
        return profiles[min(max(elapsed, 0) // 5, len(profiles) - 1)]

    @staticmethod
    def _minutes_to_time(total_minutes: int) -> str:
        hour, minute = divmod(total_minutes, 60)
        return f"{hour:02d}:{minute:02d}"
