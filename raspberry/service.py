"""Long-running MQTT service for the Pi-side terrarium rules."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .mqtt_controller import TerrariumMQTTController
from .status_dashboard import StatusStore, start_dashboard
from .terrarium_logic import TerrariumLogic


LOGGER = logging.getLogger("terrarium.service")
SUBSCRIPTIONS = ("esp32/sensors", "esp32/status", "moxa/status")
MQTT_SUCCESS = 0
MOXA_OUTPUT_TOPIC = "moxa/cmd/output"
MOXA_READ_TOPIC = "ioThinx_4510/read/#"
LIGHT_SCHEDULE_INTERVAL_SECONDS = 60
IRRIGATION_SCHEDULE_INTERVAL_SECONDS = 1


class TerrariumMQTTService:
    """Connect the rule engine to MQTT and keep it running."""

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        settings: Optional[dict[str, object]] = None,
        settings_path: Optional[str] = None,
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
        self.settings_path = Path(
            settings_path
            or os.getenv("TERRARIUM_SETTINGS_FILE", "terrarium_settings_template.json")
        )
        self.settings = json.loads(json.dumps(settings or {}))
        self._settings_lock = threading.Lock()
        self.status = StatusStore()
        self.status_server = None
        self._light_schedule_stop = threading.Event()
        self.status.update("service", {"status": "online", "started_at": int(time.time())})

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish controller output as a JSON MQTT message."""
        result = self.client.publish(topic, json.dumps(payload))
        self.status.update_nested("commands", topic, payload)
        self.status.record_state_change("command", payload, topic=topic)
        if "alarm" in payload:
            self.status.record_state_change(
                "alert",
                {
                    "active": bool(payload["alarm"]),
                    "reason": payload.get("reason", "unspecified"),
                },
                topic=topic,
            )
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
            result = self.client.publish(topic, json.dumps(value))
            self.status.record_state_change(
                "moxa_write",
                {
                    **value,
                    "logical_topic": MOXA_OUTPUT_TOPIC,
                    "logical_state": state,
                    "publish_rc": getattr(result, "rc", MQTT_SUCCESS),
                },
                topic=topic,
            )
            LOGGER.info("Moxa DO%02d <- %s", output, state)

    def apply_override(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply a UI override or re-publish the current automatic state."""
        if payload.get("mode") == "auto":
            result = self.controller.apply_override(payload)
            self.controller.publish_current_state()
            return result
        result = self.controller.apply_override(payload)
        result["mode"] = "manual"
        return result

    def get_settings(self) -> dict[str, object]:
        """Return a detached copy of the active JSON settings."""
        with self._settings_lock:
            return json.loads(json.dumps(self.settings))

    def apply_settings(self, settings: dict[str, object]) -> dict[str, object]:
        """Validate, persist, and apply settings without restarting the service."""
        self.controller.logic.validate_settings(settings)
        document = json.loads(json.dumps(settings))
        with self._settings_lock:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.settings_path.with_suffix(
                f"{self.settings_path.suffix}.tmp"
            )
            try:
                with temporary_path.open("w", encoding="utf-8") as settings_file:
                    json.dump(document, settings_file, indent=2)
                    settings_file.write("\n")
                temporary_path.replace(self.settings_path)
            except OSError:
                LOGGER.exception("Could not persist settings to %s", self.settings_path)
                raise
            self.controller.replace_settings(document)
            self.settings = document

        self._publish(
            "esp32/cmd/fans",
            self.controller.logic.evaluate_fan_command(),
        )
        self.controller.publish_scheduled_lights()
        return self.get_settings()

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
                self.status.record_state_change("esp32_status", esp_status, topic=message.topic)
            result = self.controller.handle_message(message.topic, payload)
            LOGGER.debug("Handled %s: %s", message.topic, result)
        except Exception:
            LOGGER.exception("Failed to handle MQTT message on %s", message.topic)

    def _update_moxa_reading(self, topic: str, payload: str) -> None:
        reading = json.loads(payload)
        value = reading.get("value")
        self.status.record_state_change("moxa_read", reading, topic=topic)
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
            self.controller.publish_moxa_output(actions)
        except (ValueError, TypeError, json.JSONDecodeError):
            LOGGER.warning("Invalid Moxa DI message on %s", topic)

    def _run_light_schedule(self) -> None:
        while not self._light_schedule_stop.wait(LIGHT_SCHEDULE_INTERVAL_SECONDS):
            try:
                self.controller.publish_scheduled_lights()
            except Exception:
                LOGGER.exception("Failed to publish scheduled light state")

    def _run_irrigation_schedule(self) -> None:
        while not self._light_schedule_stop.wait(IRRIGATION_SCHEDULE_INTERVAL_SECONDS):
            try:
                self.controller.publish_scheduled_irrigation()
            except Exception:
                LOGGER.exception("Failed to publish scheduled irrigation state")

    def stop(self, *_signals: int) -> None:
        LOGGER.info("Stopping terrarium MQTT service")
        self._light_schedule_stop.set()
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
            override_callback=self.apply_override,
            settings_callback=self.get_settings,
            update_settings_callback=self.apply_settings,
        )
        self.status.update(
            "mqtt",
            {
                "status": "connecting",
                "broker": f"{self.broker}:{self.port}",
            },
        )
        self._light_schedule_stop.clear()
        light_schedule_thread = threading.Thread(
            target=self._run_light_schedule,
            name="light-schedule",
            daemon=True,
        )
        irrigation_schedule_thread = threading.Thread(
            target=self._run_irrigation_schedule,
            name="irrigation-schedule",
            daemon=True,
        )
        light_schedule_thread.start()
        irrigation_schedule_thread.start()
        try:
            self.client.connect_async(self.broker, self.port, keepalive=60)
            self.client.loop_forever(retry_first_connection=True)
        finally:
            self._light_schedule_stop.set()
            light_schedule_thread.join(timeout=LIGHT_SCHEDULE_INTERVAL_SECONDS + 1)
            irrigation_schedule_thread.join(timeout=IRRIGATION_SCHEDULE_INTERVAL_SECONDS + 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the terrarium MQTT rule engine")
    parser.add_argument("--broker", default=os.getenv("TERRARIUM_MQTT_BROKER", "127.0.0.1"))
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
        if not isinstance(loaded_settings, dict):
            raise ValueError(f"Settings file is not a JSON object: {args.settings}")
        settings = loaded_settings
        TerrariumLogic.validate_settings(settings)
    except (OSError, json.JSONDecodeError, ValueError):
        LOGGER.exception("Could not load valid settings file %s", args.settings)
        raise

    import paho.mqtt.client as mqtt

    TerrariumMQTTService(
        args.broker,
        args.port,
        settings=settings,
        settings_path=args.settings,
        client_factory=mqtt.Client,
    ).run()


if __name__ == "__main__":
    main()