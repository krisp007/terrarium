"""MQTT controller for the Pi-side terrarium logic."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, Optional

from .terrarium_logic import TerrariumLogic


class TerrariumMQTTController:
    """Bridge MQTT topics with the terrarium logic rules."""

    def __init__(self, broker: str = "192.168.24.166", settings: Optional[Dict[str, object]] = None) -> None:
        self.broker = broker
        self.logic = TerrariumLogic(settings=settings)
        self.manual_output_overrides: Dict[str, Dict[str, object]] = {}

    def update_settings(self, settings: Dict[str, object]) -> None:
        """Pass UI/profile changes to the live rule engine."""
        self.logic.update_settings(settings)

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish a JSON payload to the given MQTT topic.

        This method is intentionally lightweight so it can be monkeypatched in
        tests without needing a live broker dependency.
        """
        raise NotImplementedError("The MQTT transport is implemented by the runtime host")

    def publish_current_state(self, now: Optional[datetime] = None) -> None:
        """Re-apply the present-time state after a Pi/MQTT reconnect."""
        current = now or datetime.now()
        fan_command = self.logic.evaluate_fan_command()
        light_command = self.logic.evaluate_light_command(current.strftime("%H:%M"))
        light_outputs = self.logic.evaluate_moxa_light_outputs(current.strftime("%H:%M"))
        safe_outputs = {
            **light_outputs,
            "do4": "OFF",
            "do5": "OFF",
            "do6": "OFF",
            "do7": "OFF",
            "mistmaker": "OFF",
            "beregening": "OFF",
            "alarm": True,
            "reason": "startup_safe_state",
        }
        self.publish("esp32/cmd/fans", fan_command)
        self.publish("esp32/cmd/lights", light_command)
        self.publish("moxa/cmd/output", self.apply_output_overrides(safe_outputs))

    def apply_output_overrides(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Merge active manual Moxa outputs while allowing them to expire."""
        result = dict(payload)
        now = time.time()
        for output, override in list(self.manual_output_overrides.items()):
            expires_at = override.get("expires_at")
            if expires_at is not None and now >= float(expires_at):
                self.manual_output_overrides.pop(output, None)
                continue
            result[output] = override["state"]
        if self.manual_output_overrides:
            result["mode"] = "manual"
            result["overrides"] = {name: item.get("expires_at") for name, item in self.manual_output_overrides.items()}
        return result

    def apply_override(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Publish one manual actor command while keeping its transport explicit."""
        actor_type = str(payload.get("actor_type", ""))
        actor_name = str(payload.get("actor_name", ""))
        if payload.get("mode") == "auto":
            channel = actor_name.rsplit("-", 1)[-1]
            if actor_type == "Fan":
                self.logic.clear_fan_override(f"fan{channel}" if channel.isdigit() else actor_name)
            if actor_type == "LED":
                self.logic.clear_led_override(f"led{channel}" if channel.isdigit() else actor_name)
            output = self._output_for_actor(actor_type, actor_name)
            if output:
                self.manual_output_overrides.pop(output, None)
            return {"status": "auto", "actor_name": actor_name}
        state = bool(payload.get("state", False))
        intensity = max(0, min(100, int(payload.get("intensity", 100))))
        level = intensity if state else 0
        channel = actor_name.rsplit("-", 1)[-1]

        if actor_type == "Fan":
            channels = {f"fan{number}": 0 for number in range(1, 7)}
            if channel.isdigit() and 1 <= int(channel) <= 6:
                channels[f"fan{int(channel)}"] = level
            command = self.logic.set_fan_override(
                channels,
                level=level if actor_name not in {"fan-1", "fan-6"} else 0,
                duration_minutes=payload.get("duration_minutes"),
                fan_name=f"fan{channel}" if channel.isdigit() and 1 <= int(channel) <= 6 else None,
            )
            self.publish("esp32/cmd/fans", command)
        elif actor_type == "LED":
            leds = {f"led{number}": 0 for number in range(1, 5)}
            channel = actor_name.rsplit("-", 1)[-1]
            if channel.isdigit() and 1 <= int(channel) <= 4:
                leds[f"led{int(channel)}"] = level
                led_name = f"led{int(channel)}"
                self.logic.set_led_override(led_name, level, payload.get("duration_minutes"))
            light_command = self.logic.evaluate_light_command(datetime.now().strftime("%H:%M"))
            self.publish("esp32/cmd/lights", {"mode": "manual", **light_command})
            self.publish("moxa/cmd/output", self.logic.evaluate_moxa_light_outputs(datetime.now().strftime("%H:%M")))
        else:
            outputs: Dict[str, Any] = {"mode": "manual", "state": "ON" if state else "OFF", "reason": "ui_override"}
            output = self._output_for_actor(actor_type, actor_name)
            if isinstance(output, str):
                outputs[output] = "ON" if state else "OFF"
                expires_at = time.time() + max(0.0, float(payload.get("duration_minutes", 0))) * 60
                self.manual_output_overrides[output] = {"state": outputs[output], "expires_at": expires_at}
            self.publish("moxa/cmd/output", outputs)

        expiry = None
        if actor_type == "Fan" and channel.isdigit() and 1 <= int(channel) <= 6:
            expiry = self.logic.fan_override_expiry(f"fan{channel}")
        if actor_type == "LED" and channel.isdigit() and 1 <= int(channel) <= 4:
            expiry = self.logic.led_override_expiry(f"led{channel}")
        output = self._output_for_actor(actor_type, actor_name)
        if output in self.manual_output_overrides:
            expiry = self.manual_output_overrides[output].get("expires_at")
        return {"status": "applied", "actor_type": actor_type, "actor_name": actor_name, "state": state, "intensity": intensity, "expires_at": expiry}

    @staticmethod
    def _output_for_actor(actor_type: str, actor_name: str) -> Optional[str]:
        return {
            "Heat Lamp": "do6",
            "Mist Maker": "do5",
            "Atomizer": "do5",
            "Pump": {"fill-mist": "do4", "fill-irrigation": "do5", "waterfall": "do7", "irrigation": "do4"}.get(actor_name),
        }.get(actor_type)

    def handle_message(self, topic: str, payload: str) -> Dict[str, Any]:
        """Process a message from the broker and emit commands when needed."""
        try:
            data = json.loads(payload)
        except Exception:
            return {"status": "ignored", "reason": "invalid_json"}

        if topic == "esp32/sensors":
            self.logic.update_sensor_state(data)
            command = self.logic.evaluate_fan_command()
            self.publish("esp32/cmd/fans", command)
            current_time = datetime.now().strftime("%H:%M")
            lights = self.logic.evaluate_light_command(current_time)
            self.publish("esp32/cmd/lights", lights)
            moxa_command = {
                **self.logic.evaluate_moxa_light_outputs(current_time),
                **self.logic.evaluate_moxa_outputs(),
            }
            self.publish("moxa/cmd/output", self.apply_output_overrides(moxa_command))
            return command

        if topic == "esp32/status":
            if isinstance(data, dict) and "timestamp" in data:
                self.logic.update_heartbeat(int(data["timestamp"]))
            else:
                self.logic.update_heartbeat(0)
            health = self.logic.evaluate_esp32_health(now=0)
            return health

        if topic == "moxa/status":
            actions = self.logic.evaluate_moxa_state(data)
            self.publish("moxa/cmd/output", self.apply_output_overrides(actions))
            return actions

        return {"status": "ignored", "reason": "unknown_topic"}
