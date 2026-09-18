"""MQTT controller for the Pi-side terrarium logic."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .terrarium_logic import TerrariumLogic


class TerrariumMQTTController:
    """Bridge MQTT topics with the terrarium logic rules."""

    def __init__(self, broker: str = "192.168.24.166") -> None:
        self.broker = broker
        self.logic = TerrariumLogic()

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish a JSON payload to the given MQTT topic.

        This method is intentionally lightweight so it can be monkeypatched in
        tests without needing a live broker dependency.
        """
        raise NotImplementedError("The MQTT transport is implemented by the runtime host")

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
