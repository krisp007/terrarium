"""Long-running MQTT service for the Pi-side terrarium rules."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
from datetime import datetime
from typing import Any, Callable, Optional

from .mqtt_controller import TerrariumMQTTController
from .status_dashboard import StatusStore, start_dashboard


LOGGER = logging.getLogger("terrarium.service")
SUBSCRIPTIONS = ("esp32/sensors", "esp32/status", "moxa/status")
MQTT_SUCCESS = 0
MOXA_OUTPUT_TOPIC = "moxa/cmd/output"
MOXA_READ_TOPIC = "ioThinx_4510/read/#"


class TerrariumMQTTService:
    """Connect the rule engine to MQTT and keep it running."""

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        settings: Optional[dict[str, object]] = None,
        status_port: Optional[int] = None,
        client_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.broker = broker
        self.port = port
        self.status_port = status_port if status_port is not None else int(
            os.getenv("TERRARIUM_STATUS_PORT", "8080")
        )
        if client_factory is None:
            import paho.mqtt.client as mqtt

            client_factory = mqtt.Client
        self.client = client_factory()
        self.controller = TerrariumMQTTController(broker=broker, settings=settings)
        self.controller.publish = self._publish
        self.status = StatusStore()
        self.status_server = None
        self.status.update("service", {"status": "online", "started_at": int(time.time())})

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish controller output as a JSON MQTT message."""
        result = self.client.publish(topic, json.dumps(payload))
        self.status.update_nested("commands", topic, payload)
        self.status.record("command", payload, topic=topic)
        if hasattr(result, "rc") and result.rc != MQTT_SUCCESS:
            LOGGER.warning("MQTT publish failed for %s (rc=%s)", topic, result.rc)

        if topic == MOXA_OUTPUT_TOPIC:
            self._publish_moxa_outputs(payload)

    def _publish_moxa_outputs(self, payload: dict[str, Any]) -> None:
        """Translate logical DO commands to the ioThinx MQTT write topics."""
        for key, state in payload.items():
            if not key.startswith("do") or not key[2:].isdigit():
                continue

            output = int(key[2:])
            if output < 0 or output > 15 or state not in ("ON", "OFF"):
                continue

            topic = f"ioThinx_4510/write/DO@DO-{output:02d}/doStatus"
            value = {"value": 1 if state == "ON" else 0}
            self.client.publish(topic, json.dumps(value))
            LOGGER.info("Moxa DO%02d <- %s", output, state)

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc != MQTT_SUCCESS:
            LOGGER.error("MQTT connection failed (rc=%s)", rc)
            return

        for topic in SUBSCRIPTIONS:
            client.subscribe(topic)
        client.subscribe(MOXA_READ_TOPIC)
        self.status.update("mqtt", {"status": "connected", "broker": f"{self.broker}:{self.port}"})
        self.controller.publish_current_state(now=datetime.now())
        LOGGER.info("Connected to MQTT broker %s:%s", self.broker, self.port)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        try:
            payload = message.payload.decode("utf-8")
            if message.topic.startswith("ioThinx_4510/read/"):
                self._update_moxa_reading(message.topic, payload)
                self._handle_moxa_input(message.topic, payload)
                return
            if message.topic == "esp32/sensors":
                sensor_data = json.loads(payload)
                self.status.update("esp32", {"status": "online", "sensors": sensor_data, "last_seen": int(time.time())})
                self.status.record("esp32_sensors", sensor_data, topic=message.topic)
            elif message.topic == "esp32/status":
                esp_status = json.loads(payload)
                self.status.update("esp32", {**esp_status, "last_seen": int(time.time())})
                self.status.record("esp32_status", esp_status, topic=message.topic)
            result = self.controller.handle_message(message.topic, payload)
            LOGGER.debug("Handled %s: %s", message.topic, result)
        except Exception:
            LOGGER.exception("Failed to handle MQTT message on %s", message.topic)

    def _update_moxa_reading(self, topic: str, payload: str) -> None:
        reading = json.loads(payload)
        value = reading.get("value")
        self.status.record("moxa_read", reading, topic=topic)
        channel = topic.split("/")[-2]
        target = "inputs" if "@DI-" in channel else "outputs"
        self.status.update_nested("moxa", target, {**self.status.snapshot()["moxa"].get(target, {}), channel: value})
        self.status.update("moxa", {"status": "online", "last_seen": int(time.time())})

    def _handle_moxa_input(self, topic: str, payload: str) -> None:
        """Feed retained ioThinx DI feedback into the safety rules."""
        channel = topic.split("/")[-2]
        if "@DI-" not in channel:
            return
        try:
            value = json.loads(payload).get("value")
            input_number = int(channel.split("@DI-")[-1])
            current = dict(self.controller.logic.moxa_state or {})
            current[f"di{input_number}"] = bool(value)
            actions = self.controller.logic.evaluate_moxa_state(current)
            self._publish("moxa/cmd/output", actions)
        except (ValueError, TypeError, json.JSONDecodeError):
            LOGGER.warning("Invalid Moxa DI message on %s", topic)

    def stop(self, *_signals: int) -> None:
        LOGGER.info("Stopping terrarium MQTT service")
        self.status.update("service", {"status": "stopping"})
        if self.status_server is not None:
            self.status_server.shutdown()
        self.client.disconnect()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.status_server = start_dashboard(
            self.status,
            port=self.status_port,
        )
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the terrarium MQTT rule engine")
    parser.add_argument("--broker", default=os.getenv("TERRARIUM_MQTT_BROKER", "192.168.24.166"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TERRARIUM_MQTT_PORT", "1883")))
    parser.add_argument(
        "--settings",
        default=os.getenv("TERRARIUM_SETTINGS_FILE", "terrarium_settings_template.json"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("TERRARIUM_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings: dict[str, object] = {}
    try:
        with open(args.settings, "r", encoding="utf-8") as settings_file:
            loaded_settings = json.load(settings_file)
        if isinstance(loaded_settings, dict):
            settings = loaded_settings
        else:
            LOGGER.warning("Settings file is not a JSON object: %s", args.settings)
    except (OSError, json.JSONDecodeError) as error:
        LOGGER.warning("Could not load settings file %s: %s", args.settings, error)

    import paho.mqtt.client as mqtt

    TerrariumMQTTService(
        args.broker,
        args.port,
        settings=settings,
        client_factory=mqtt.Client,
    ).run()


if __name__ == "__main__":
    main()