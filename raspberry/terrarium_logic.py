"""Pi-side terrarium control logic.

This module contains the core rules used by the Raspberry Pi to translate
MQTT status messages from the ESP32 and Moxa into safety actions and fan
control commands.
"""

from __future__ import annotations

from typing import Dict, Optional


class TerrariumLogic:
    """Evaluate safety and climate rules for the terrarium."""

    def __init__(self) -> None:
        self.sensor_state: Dict[str, float] = {}
        self.moxa_state: Optional[Dict[str, object]] = None
        self.last_heartbeat: Optional[int] = None
        self.heartbeat_timeout_seconds = 180
        self.mistmaker_on_humidity = 82.0
        self.mistmaker_off_humidity = 90.0
        self.irrigation_on_soil = 35.0
        self.irrigation_off_soil = 55.0

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
                "mistmaker": "OFF",
                "beregening": "OFF",
                "alarm": True,
                "reason": "leak_detected",
            }

        humidity = sum(humidity_values) / len(humidity_values) if humidity_values else None
        soil = sum(soil_values) / len(soil_values) if soil_values else None
        mistmaker = "OFF"
        irrigation = "OFF"

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
            "mistmaker": mistmaker,
            "beregening": irrigation,
            "alarm": reservoir_alarm,
            "reason": "reservoir_low" if reservoir_alarm else "sensor_control",
        }

    def evaluate_fan_command(self) -> Dict[str, object]:
        """Compute a safe fan level from the current average temperature."""
        if not self.sensor_state:
            return {"mode": "auto", "level": 0}

        temps = [
            float(value)
            for key, value in self.sensor_state.items()
            if key.startswith("temperature") and isinstance(value, (int, float))
        ]

        if not temps:
            return {"mode": "auto", "level": 0}

        average_temp = sum(temps) / len(temps)

        if average_temp < 22:
            level = 0
        elif average_temp < 26:
            level = 35
        elif average_temp < 29:
            level = 60
        elif average_temp < 32:
            level = 80
        else:
            level = 100

        return {"mode": "auto", "level": int(level)}

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
