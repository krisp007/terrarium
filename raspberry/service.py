"""Long-running MQTT service for the Pi-side terrarium rules."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
from typing import Any, Callable, Optional

from .mqtt_controller import TerrariumMQTTController


LOGGER = logging.getLogger("terrarium.service")
SUBSCRIPTIONS = ("esp32/sensors", "esp32/status", "moxa/status")
MQTT_SUCCESS = 0
MOXA_OUTPUT_TOPIC = "moxa/cmd/output"


class TerrariumMQTTService:
    """Connect the rule engine to MQTT and keep it running."""

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        client_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.broker = broker
        self.port = port
        if client_factory is None:
            import paho.mqtt.client as mqtt

            client_factory = mqtt.Client
        self.client = client_factory()
        self.controller = TerrariumMQTTController(broker=broker)
        self.controller.publish = self._publish

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish controller output as a JSON MQTT message."""
        result = self.client.publish(topic, json.dumps(payload))
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
        LOGGER.info("Connected to MQTT broker %s:%s", self.broker, self.port)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        try:
            payload = message.payload.decode("utf-8")
            result = self.controller.handle_message(message.topic, payload)
            LOGGER.debug("Handled %s: %s", message.topic, result)
        except Exception:
            LOGGER.exception("Failed to handle MQTT message on %s", message.topic)

    def stop(self, *_signals: int) -> None:
        LOGGER.info("Stopping terrarium MQTT service")
        self.client.disconnect()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the terrarium MQTT rule engine")
    parser.add_argument("--broker", default=os.getenv("TERRARIUM_MQTT_BROKER", "192.168.24.166"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TERRARIUM_MQTT_PORT", "1883")))
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("TERRARIUM_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    import paho.mqtt.client as mqtt

    TerrariumMQTTService(args.broker, args.port, client_factory=mqtt.Client).run()


if __name__ == "__main__":
    main()