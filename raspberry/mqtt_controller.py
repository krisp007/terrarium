"""MQTT controller for the Pi-side terrarium logic."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

from .terrarium_logic import TerrariumLogic


class TerrariumMQTTController:
    """Bridge MQTT topics with the terrarium logic rules."""

    def __init__(self, broker: Optional[str] = None, settings: Optional[Dict[str, object]] = None) -> None:
        self.broker = broker or os.getenv("TERRARIUM_MQTT_BROKER", "127.0.0.1")
        self.logic = TerrariumLogic(settings=settings)
        self.manual_output_overrides: Dict[str, Dict[str, object]] = {}
        self.last_irrigation_command = "OFF"
        self.last_mistmaker_command: Optional[str] = None

    def update_settings(self, settings: Dict[str, object]) -> None:
        """Pass UI/profile changes to the live rule engine."""
        self.logic.update_settings(settings)

    def replace_settings(self, settings: Dict[str, object]) -> None:
        """Replace the active JSON profile and retain current runtime state."""
        self.logic.replace_settings(settings)

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
            self.logic.output_key("irrigation"): "OFF",
            self.logic.output_key("mistmaker"): "OFF",
            self.logic.output_key("heater"): "OFF",
            self.logic.output_key("waterfall"): "OFF",
            self.logic.output_key("ro_fill"): "OFF",
            "mistmaker": "OFF",
            "beregening": "OFF",
            "alarm": True,
            "reason": "startup_safe_state",
        }
        self.publish("esp32/cmd/fans", fan_command)
        self.publish("esp32/cmd/lights", light_command)
        self.publish_moxa_output(safe_outputs)

    def publish_scheduled_lights(self, now: Optional[datetime] = None) -> None:
        """Apply the current light schedule independently of sensor updates."""
        current_time = (now or datetime.now()).strftime("%H:%M")
        lights = self.logic.evaluate_light_command(current_time)
        outputs = self.logic.evaluate_moxa_light_outputs(current_time)
        self.publish("esp32/cmd/lights", lights)
        self.publish_moxa_output(outputs)

    def publish_scheduled_irrigation(self, now: Optional[datetime] = None) -> None:
        """Update irrigation and post-irrigation mist timers without sensor updates."""
        current = now or datetime.now()
        timestamp = current.timestamp()
        irrigation_output = self.logic.output_key("irrigation")
        mistmaker_output = self.logic.output_key("mistmaker")
        outputs: Dict[str, Any] = {
            irrigation_output: self.logic.evaluate_irrigation_command(now=timestamp),
        }
        mistmaker = self.logic.evaluate_scheduled_morning_mistmaker(now=timestamp)
        if mistmaker is not None:
            outputs[mistmaker_output] = mistmaker
        effective = self.apply_output_overrides(outputs)
        changed_outputs = {
            key: effective[key]
            for key in (irrigation_output, mistmaker_output)
            if key in effective
            and effective[key] != (
                self.last_irrigation_command
                if key == irrigation_output
                else self.last_mistmaker_command
            )
        }
        if changed_outputs:
            self.publish_moxa_output(changed_outputs)

    def publish_moxa_output(self, payload: Dict[str, Any]) -> None:
        effective = self.apply_output_overrides(payload)
        self.publish("moxa/cmd/output", effective)
        irrigation_output = self.logic.output_key("irrigation")
        mistmaker_output = self.logic.output_key("mistmaker")
        if irrigation_output in effective:
            self.last_irrigation_command = str(effective[irrigation_output])
        if mistmaker_output in effective:
            self.last_mistmaker_command = str(effective[mistmaker_output])

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
                requested_minutes = max(0.0, float(payload.get("duration_minutes", 0)))
                # Protect the rain and mist pumps from running longer than they can handle.
                if output == self.logic.output_key("mistmaker"):
                    requested_minutes = min(requested_minutes, float(self.logic.mistmaker_settings.get("max_runtime_minutes", 10)))
                elif output == self.logic.output_key("irrigation"):
                    requested_minutes = min(requested_minutes, float(self.logic.irrigation_settings.get("max_runtime_minutes", 10)))
                expires_at = time.time() + requested_minutes * 60
                self.manual_output_overrides[output] = {"state": outputs[output], "expires_at": expires_at}
            self.publish_moxa_output(outputs)

        expiry = None
        if actor_type == "Fan" and channel.isdigit() and 1 <= int(channel) <= 6:
            expiry = self.logic.fan_override_expiry(f"fan{channel}")
        if actor_type == "LED" and channel.isdigit() and 1 <= int(channel) <= 4:
            expiry = self.logic.led_override_expiry(f"led{channel}")
        output = self._output_for_actor(actor_type, actor_name)
        if output in self.manual_output_overrides:
            expiry = self.manual_output_overrides[output].get("expires_at")
        return {"status": "applied", "actor_type": actor_type, "actor_name": actor_name, "state": state, "intensity": intensity, "expires_at": expiry}

    def _output_for_actor(self, actor_type: str, actor_name: str) -> Optional[str]:
        return {
            "Heat Lamp": self.logic.output_key("heater"),
            "Mist Maker": self.logic.output_key("mistmaker"),
            "Atomizer": self.logic.output_key("mistmaker"),
            "Pump": {
                "fill-mist": self.logic.output_key("irrigation"),
                "fill-irrigation": self.logic.output_key("mistmaker"),
                "waterfall": self.logic.output_key("waterfall"),
                "irrigation": self.logic.output_key("irrigation"),
                "ro": self.logic.output_key("ro_fill"),
            }.get(actor_name),
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
            self.publish_scheduled_lights()
            self.publish_moxa_output(self.logic.evaluate_moxa_outputs())
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
            self.publish_moxa_output(actions)
            return actions

        return {"status": "ignored", "reason": "unknown_topic"}
