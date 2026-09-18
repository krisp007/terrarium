"""MQTT controller for the Pi-side terrarium logic."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from .terrarium_logic import TerrariumLogic


class TerrariumMQTTController:
    """Bridge MQTT topics with the terrarium logic rules."""

    def __init__(self, broker: str = "192.168.24.166", settings: Optional[Dict[str, object]] = None) -> None:
        self.broker = broker
        self.logic = TerrariumLogic(settings=settings)

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
        safe_outputs = {
            "do4": "OFF",
            "do5": "OFF",
            "do6": "OFF",
            "mistmaker": "OFF",
            "beregening": "OFF",
            "alarm": True,
            "reason": "startup_safe_state",
        }
        self.publish("esp32/cmd/fans", fan_command)
        self.publish("esp32/cmd/lights", light_command)
        self.publish("moxa/cmd/output", safe_outputs)

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
            lights = self.logic.evaluate_light_command(datetime.now().strftime("%H:%M"))
            self.publish("esp32/cmd/lights", lights)
            moxa_command = self.logic.evaluate_moxa_outputs()
            self.publish("moxa/cmd/output", moxa_command)
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
            self.publish("moxa/cmd/output", actions)
            return actions

        return {"status": "ignored", "reason": "unknown_topic"}
