"""Pi-side terrarium control logic.

This module contains the core rules used by the Raspberry Pi to translate
MQTT status messages from the ESP32 and Moxa into safety actions and fan
control commands.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, time as datetime_time, timedelta
from typing import Callable, Dict, Optional, Set


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
    "duration_minutes": 1,
    "cooldown_minutes": 30,
    "pre_light_lead_minutes": 5,
    "post_rain_mist_minutes": 10,
}


class TerrariumLogic:
    """Evaluate safety and climate rules for the terrarium."""

    def __init__(self, settings: Optional[Dict[str, object]] = None) -> None:
        self.settings: Dict[str, object] = {}
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
        self.post_rain_mist_until = 0.0
        self.post_rain_mist_enabled = False
        self.scheduled_rain_events: Set[str] = set()
        self._pump_schedule_started_at: Dict[str, float] = {}
        self.random_source: Callable[[], float] = random.random
        self.minimum_airflow_percent = 30
        self.minimum_airflow_interval_seconds = 60
        self.manual_fan_overrides: Dict[str, Dict[str, object]] = {}
        self.manual_led_overrides: Dict[str, Dict[str, object]] = {}
        if settings is not None:
            self.update_settings(settings)

    def update_settings(self, settings: Dict[str, object]) -> None:
        """Apply editable settings without changing the rule engine."""
        self.settings.update(settings)
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

    @staticmethod
    def _parse_clock(value: object, fallback: datetime_time) -> datetime_time:
        if not isinstance(value, str):
            return fallback
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
            return datetime_time(hour, minute)
        except (ValueError, TypeError):
            return fallback

    def _active_climate_targets(self, current: Optional[datetime] = None) -> Dict[str, object]:
        """Resolve the active season and day/night climate targets from settings."""
        current = current or datetime.now()
        schedule = self.settings.get("schedule", {})
        if not isinstance(schedule, dict):
            schedule = {}
        sunrise = self._parse_clock(schedule.get("sunrise"), datetime_time(5, 45))
        sunset = self._parse_clock(schedule.get("sunset"), datetime_time(18, 15))
        period_name = "day" if sunrise <= current.time() < sunset else "night"

        seasons = self.settings.get("seasons", {})
        if not isinstance(seasons, dict):
            seasons = {}
        active = [
            name for name, config in seasons.items()
            if isinstance(config, dict) and config.get("active") is True
        ]
        season_name = "rainy" if "rainy" in active else active[0] if active else "rainy"
        season = seasons.get(season_name, {})
        if not isinstance(season, dict):
            season = {}
        period = season.get(period_name, {})
        if not isinstance(period, dict):
            period = {}
        temperature = period.get("temperature", {})
        humidity = period.get("humidity", {})
        if not isinstance(temperature, dict):
            temperature = {}
        if not isinstance(humidity, dict):
            humidity = {}

        return {
            "season": season_name,
            "period": period_name,
            "sunrise": sunrise,
            "sunset": sunset,
            "temperature_target": float(temperature.get("target_c", self.heater_thresholds["temperature_too_low_c"])),
            "humidity_min": float(humidity.get("min_percent", self.mistmaker_on_humidity)),
            "humidity_target": float(humidity.get("target_percent", self.mistmaker_off_humidity)),
        }
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
                "do10": "OFF",
                "do11": "OFF",
                "do12": "OFF",
                "do15": "OFF",
                "alarm": True,
                "reason": "leak_detected",
            }

        return {
            "do6": self.evaluate_heater_command()["state"],
            "do12": "ON" if payload.get("di1") is True else "OFF",
            "do15": "ON" if payload.get("di0") is True else "OFF",
            "alarm": False,
            "reason": "normal",
        }

    def evaluate_moxa_outputs(
        self,
        now: Optional[datetime] = None,
        random_value: Optional[float] = None,
    ) -> Dict[str, object]:
        """Evaluate timed rain/mist outputs and independent Moxa interlocks."""
        current = now or datetime.now()
        climate = self._active_climate_targets(current)
        humidity_values = [
            value for key, value in self.sensor_state.items()
            if key.startswith("humidity_")
        ]
        humidity = sum(humidity_values) / len(humidity_values) if humidity_values else None

        if self.moxa_state is not None and (
            self.moxa_state.get("di2") is True or self.moxa_state.get("alarm") is True
        ):
            return {
                "do4": "OFF",
                "do5": "OFF",
                "do6": "OFF",
                "do10": "OFF",
                "do11": "OFF",
                "do12": "OFF",
                "do15": "OFF",
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
                "do10": "OFF",
                "do11": "OFF",
                "do12": "OFF",
                "do15": "OFF",
                "mistmaker": "OFF",
                "beregening": "OFF",
                "alarm": True,
                "reason": "moxa_status_unknown",
            }

        event = self.evaluate_rainstorm(
            season=str(climate["season"]),
            now=current.timestamp(),
            random_value=random_value,
            humidity=humidity,
            minimum_humidity=float(climate["humidity_min"]),
            scheduled_event=self._scheduled_rain_event(current, climate),
        )
        mistmaker = event["do5"]
        humidity_target = float(climate["humidity_target"])
        if mistmaker == "ON" and humidity is not None and humidity >= humidity_target + 5:
            mistmaker = "OFF"

        return {
            "do4": event["do4"],
            "do5": mistmaker,
            "do6": self.evaluate_heater_command(climate_time=current)["state"],
            "do12": "ON" if self.moxa_state.get("di1") is True else "OFF",
            "do15": "ON" if self.moxa_state.get("di0") is True else "OFF",
            "mistmaker": mistmaker,
            "beregening": event["do4"],
            "alarm": False,
            "reason": event["reason"],
        }

    def evaluate_scheduled_pump_outputs(
        self,
        now: Optional[float] = None,
        moxa_online: bool = False,
    ) -> Dict[str, str]:
        """Return JSON-configured auxiliary pump states; first cycle waits one interval."""
        current_time = time.monotonic() if now is None else now
        safe = (
            moxa_online
            and self.moxa_state is not None
            and self.moxa_state.get("di2") is not True
            and self.moxa_state.get("alarm") is not True
        )
        outputs: Dict[str, str] = {}
        for config_name, output_name in (("waterfall", "do10"), ("orchid_dripper", "do11")):
            config = self.settings.get(config_name, {})
            if not isinstance(config, dict):
                config = {}
            enabled = config.get("enabled") is True and config.get("auto_mode") is True
            if not safe or not enabled:
                self._pump_schedule_started_at.pop(config_name, None)
                outputs[output_name] = "OFF"
                continue

            cycle_seconds = max(1.0, float(config.get("cycle_minutes", 90)) * 60)
            duration_seconds = max(0.0, min(float(config.get("duration_seconds", 45)), cycle_seconds))
            started_at = self._pump_schedule_started_at.setdefault(config_name, current_time)
            elapsed = max(0.0, current_time - started_at)
            phase = elapsed % cycle_seconds
            outputs[output_name] = (
                "ON" if elapsed >= cycle_seconds and phase < duration_seconds else "OFF"
            )
        return outputs

    def scheduled_pump_status(
        self,
        now: Optional[float] = None,
        moxa_online: bool = False,
    ) -> Dict[str, Dict[str, object]]:
        """Return configured cycle timing and current state for dashboard display."""
        current_time = time.monotonic() if now is None else now
        outputs = self.evaluate_scheduled_pump_outputs(current_time, moxa_online)
        result: Dict[str, Dict[str, object]] = {}
        for config_name, output_name in (("waterfall", "do10"), ("orchid_dripper", "do11")):
            config = self.settings.get(config_name, {})
            if not isinstance(config, dict):
                config = {}
            cycle_minutes = max(1.0, float(config.get("cycle_minutes", 90)))
            duration_seconds = max(0.0, min(float(config.get("duration_seconds", 45)), cycle_minutes * 60))
            result[output_name] = {
                "name": "Waterfall pump" if output_name == "do10" else "Orchid dripper",
                "enabled": config.get("enabled") is True and config.get("auto_mode") is True,
                "state": outputs[output_name],
                "cycle_minutes": cycle_minutes,
                "duration_seconds": duration_seconds,
                "next_run_seconds": None,
                "remaining_run_seconds": 0.0,
            }
            started_at = self._pump_schedule_started_at.get(config_name)
            if result[output_name]["enabled"] and moxa_online and started_at is not None:
                elapsed = max(0.0, current_time - started_at)
                cycle_seconds = cycle_minutes * 60
                phase = elapsed % cycle_seconds
                if elapsed >= cycle_seconds and phase < duration_seconds:
                    result[output_name]["remaining_run_seconds"] = duration_seconds - phase
                    result[output_name]["next_run_seconds"] = 0.0
                else:
                    result[output_name]["next_run_seconds"] = (
                        cycle_seconds - elapsed if elapsed < cycle_seconds else cycle_seconds - phase
                    )
        return result

    def _scheduled_rain_event(
        self,
        current: datetime,
        climate: Dict[str, object],
    ) -> Optional[str]:
        lead_minutes = max(1, int(self.rainstorm.get("pre_light_lead_minutes", 5)))
        for event_name in ("sunrise", "sunset"):
            light_time = climate[event_name]
            light_at = datetime.combine(current.date(), light_time)
            event_key = f"{current.date().isoformat()}:{event_name}"
            if (
                event_key not in self.scheduled_rain_events
                and light_at - timedelta(minutes=lead_minutes) <= current < light_at
            ):
                return event_key
        return None

    def evaluate_rainstorm(
        self,
        season: str = "rainy",
        now: Optional[float] = None,
        random_value: Optional[float] = None,
        humidity: Optional[float] = None,
        minimum_humidity: Optional[float] = None,
        scheduled_event: Optional[str] = None,
    ) -> Dict[str, object]:
        """Run a humidity-gated rain event and planned-rain mist follow-up."""
        current_time = time.time() if now is None else now
        inactive = {
            "active": False,
            "do4": "OFF",
            "do5": "OFF",
            "reason": "inactive",
            "phase": "idle",
        }
        if season != "rainy" or not self.rainstorm.get("enabled", False):
            return inactive
        if self.moxa_state is not None and (
            self.moxa_state.get("di2") is True
            or self.moxa_state.get("alarm") is True
        ):
            return {**inactive, "reason": "safety_block"}
        if current_time < self.rainstorm_until:
            return {
                "active": True,
                "do4": "ON",
                "do5": "OFF",
                "reason": "scheduled_rain" if self.post_rain_mist_enabled else "rainstorm",
                "phase": "rain",
            }
        if current_time < self.post_rain_mist_until and self.post_rain_mist_enabled:
            return {
                "active": False,
                "do4": "OFF",
                "do5": "ON",
                "reason": "post_rain_mist",
                "phase": "mist",
            }
        if humidity is None or minimum_humidity is None or humidity > minimum_humidity:
            return {**inactive, "reason": "minimum_humidity_not_reached"}
        if current_time < self.rainstorm_cooldown_until:
            return {**inactive, "reason": "cooldown"}

        scheduled = scheduled_event is not None
        if scheduled:
            if scheduled_event in self.scheduled_rain_events:
                return {**inactive, "reason": "scheduled_event_complete"}
        else:
            chance = float(self.rainstorm.get("chance_percent", 0.0)) / 100.0
            if (self.random_source() if random_value is None else random_value) >= chance:
                return inactive

        configured_duration = float(self.rainstorm.get("duration_minutes", 1))
        duration_seconds = min(60.0, max(1.0, configured_duration * 60))
        cooldown = max(0.0, float(self.rainstorm.get("cooldown_minutes", 30))) * 60
        self.rainstorm_until = current_time + duration_seconds
        self.rainstorm_cooldown_until = self.rainstorm_until + cooldown
        self.post_rain_mist_enabled = scheduled
        if scheduled:
            self.scheduled_rain_events.add(str(scheduled_event))
            mist_minutes = max(0.0, float(self.rainstorm.get("post_rain_mist_minutes", 10)))
            self.post_rain_mist_until = self.rainstorm_until + mist_minutes * 60
        else:
            self.post_rain_mist_until = 0.0
        return {
            "active": True,
            "do4": "ON",
            "do5": "OFF",
            "reason": "scheduled_rain" if scheduled else "rainstorm",
            "phase": "rain",
        }

    def evaluate_heater_command(
        self,
        climate_time: Optional[datetime] = None,
    ) -> Dict[str, object]:
        """Switch the Moxa warmtelamp on only below the configured minimum."""
        temperatures = [
            value for key, value in self.sensor_state.items()
            if key.startswith("temperature")
        ]
        if not temperatures:
            return {"state": "OFF", "do6": "OFF", "reason": "no_temperature"}

        average_temperature = sum(temperatures) / len(temperatures)
        temperature_target = float(self._active_climate_targets(climate_time)["temperature_target"])
        if average_temperature >= self.heater_thresholds["temperature_too_high_c"]:
            state = "OFF"
            reason = "temperature_too_high"
        elif average_temperature < temperature_target:
            state = "ON"
            reason = "temperature_too_low"
        else:
            state = "OFF"
            reason = "at_or_above_target"

        if self.moxa_state is not None and (
            self.moxa_state.get("di2") is True or self.moxa_state.get("alarm") is True
        ):
            state = "OFF"
            reason = "safety_alarm"

        return {"state": state, "do6": state, "reason": reason}

    def evaluate_fan_command(
        self,
        now: Optional[float] = None,
        climate_time: Optional[datetime] = None,
    ) -> Dict[str, object]:
        """Compute a safe fan level from the current average temperature."""
        current_time = time.time() if now is None else now
        active_minimum_fan = 1 if int(current_time / self.minimum_airflow_interval_seconds) % 2 == 0 else 6
        if not self.sensor_state:
            level = 0
            return self._apply_fan_overrides(self._fan_command(level, active_minimum_fan), current_time)

        temps = [
            float(value)
            for key, value in self.sensor_state.items()
            if key.startswith("temperature") and isinstance(value, (int, float))
        ]
        humidity_values = [
            float(value)
            for key, value in self.sensor_state.items()
            if key.startswith("humidity_") and isinstance(value, (int, float))
        ]
        climate = self._active_climate_targets(climate_time)
        level = self.fan_levels["low"]
        seasons = self.settings.get("seasons", {})
        has_season_targets = isinstance(seasons, dict) and bool(seasons)
        if temps and not has_season_targets:
            average_temp = sum(temps) / len(temps)
            if average_temp < self.fan_thresholds["low"]:
                level = self.fan_levels["low"]
            elif average_temp < self.fan_thresholds["medium"]:
                level = self.fan_levels["low"]
            elif average_temp < self.fan_thresholds["high"]:
                level = self.fan_levels["medium"]
            elif average_temp < self.fan_thresholds["max_safe"]:
                level = self.fan_levels["high"]
            else:
                level = self.fan_levels["max"]
        elif temps:
            average_temp = sum(temps) / len(temps)
            level = max(
                level,
                self._ventilation_level(average_temp - float(climate["temperature_target"])),
            )
        if humidity_values:
            average_humidity = sum(humidity_values) / len(humidity_values)
            level = max(
                level,
                self._ventilation_level(average_humidity - float(climate["humidity_target"])),
            )

        return self._apply_fan_overrides(self._fan_command(int(level), active_minimum_fan), current_time)

    def _ventilation_level(self, target_delta: float) -> int:
        if target_delta > 5:
            return self.fan_levels["max"]
        if target_delta >= 5:
            return self.fan_levels["medium"]
        return self.fan_levels["low"]

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

    def _fan_command(self, level: int, active_minimum_fan: int) -> Dict[str, object]:
        """Keep one of the two end fans moving to prevent stagnant air."""
        level = max(int(level), self.minimum_airflow_percent)
        fan1 = self.minimum_airflow_percent if active_minimum_fan == 1 else 0
        fan6 = self.minimum_airflow_percent if active_minimum_fan == 6 else 0
        return {
            "mode": "auto",
            "level": level,
            "channels": {
                "fan1": fan1,
                "fan2": level,
                "fan3": level,
                "fan4": level,
                "fan5": level,
                "fan6": fan6,
            },
            "minimum_airflow": {
                "enabled": True,
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

    def evaluate_light_command(
        self,
        time_str: str,
        season: Optional[str] = None,
    ) -> Dict[str, object]:
        """Build the lighting command for the current Costa Rica day cycle."""
        try:
            hour, minute = [int(part) for part in time_str.split(":")]
            total_minutes = hour * 60 + minute
        except Exception:
            return self._light_command(self._dark_leds())

        current = datetime.combine(datetime.now().date(), datetime_time(hour, minute))
        climate = self._active_climate_targets(current)
        sunrise_time = climate["sunrise"]
        sunset_time = climate["sunset"]
        sunrise = sunrise_time.hour * 60 + sunrise_time.minute
        sunset = sunset_time.hour * 60 + sunset_time.minute
        active_season = season or str(climate["season"])
        lighting = self.settings.get("lighting", {})
        transition = 20
        if isinstance(lighting, dict):
            value = lighting.get("dawn_dusk_transition_minutes", transition)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                transition = max(1, int(value))
        if total_minutes < sunrise or total_minutes >= sunset + transition:
            return self._light_command(self._dark_leds())

        if total_minutes < sunrise + transition:
            leds = self._scheduled_dawn_profile(total_minutes - sunrise, active_season)
        elif total_minutes >= sunset:
            dawn_profile = self.evaluate_light_transition(
                self._minutes_to_time(sunrise + transition), season=active_season
            )
            elapsed = total_minutes - sunset
            factor = max(0.0, 1.0 - (elapsed / transition))
            leds = {
                key: int(value * factor)
                for key, value in dawn_profile.items()
            }
        else:
            target = 80 if active_season == "rainy" else 100
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
            "do0": "ON" if leds["led1"] > 0 else "OFF",
            "do1": "ON" if leds["led2"] > 0 else "OFF",
            "do2": "ON" if leds["led3"] > 0 else "OFF",
            "do3": "ON" if leds["led4"] > 0 else "OFF",
            "state": light["state"],
            "brightness": light["brightness"],
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
