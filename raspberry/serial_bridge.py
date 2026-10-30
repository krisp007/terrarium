"""USB serial link to the ESP32 sensor node.

Protocol: newline-delimited lines starting with "@" followed by JSON
``{"t": "<topic>", "p": <payload>}``. Anything else (REPL/debug output) is ignored.
"""

from __future__ import annotations

import glob
import json
import logging
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable, Optional

LOGGER = logging.getLogger("terrarium.serial")
FRAME_PREFIX = "@"
DEFAULT_GLOB = "/dev/serial/by-id/*CP2102*"
RECONNECT_SECONDS = 5
READ_TIMEOUT_SECONDS = 1


class SerialBridge:
    """Receive ESP32 frames and send ESP32 commands over a serial port."""

    def __init__(
        self,
        on_message: Callable[[Any, Any, Any], None],
        port: Optional[str] = None,
        baudrate: int = 115200,
    ) -> None:
        self._on_message = on_message
        self._port = port
        self._baudrate = baudrate
        self._serial: Any = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="esp32-serial", daemon=True)
        self.last_frame_at: Optional[float] = None

    @property
    def connected(self) -> bool:
        return self._serial is not None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def send(self, topic: str, payload: dict[str, Any]) -> bool:
        """Send a command frame; returns False when the port is unavailable."""
        frame = FRAME_PREFIX + json.dumps({"t": topic, "p": payload}, separators=(",", ":")) + "\n"
        with self._write_lock:
            serial_port = self._serial
            if serial_port is None:
                return False
            try:
                serial_port.write(frame.encode("utf-8"))
                return True
            except Exception:
                LOGGER.exception("Serial write failed")
                return False

    def handle_line(self, line: str) -> None:
        if not line.startswith(FRAME_PREFIX):
            return
        try:
            frame = json.loads(line[len(FRAME_PREFIX):])
            topic = frame["t"]
            payload = json.dumps(frame["p"]).encode("utf-8")
        except (ValueError, KeyError, TypeError):
            LOGGER.warning("Ignoring malformed serial frame: %.120s", line)
            return
        self.last_frame_at = time.time()
        self._on_message(None, None, SimpleNamespace(topic=topic, payload=payload))

    def _resolve_port(self) -> Optional[str]:
        if self._port:
            return self._port
        matches = sorted(glob.glob(DEFAULT_GLOB))
        return matches[0] if matches else None

    def _open(self) -> Any:
        import serial

        port = self._resolve_port()
        if port is None:
            return None
        connection = serial.Serial()
        connection.port = port
        connection.baudrate = self._baudrate
        connection.timeout = READ_TIMEOUT_SECONDS
        # Keep DTR/RTS low so opening the port does not reset the ESP32.
        connection.dtr = False
        connection.rts = False
        connection.open()
        return connection

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                connection = self._open()
            except Exception as error:
                LOGGER.warning("Cannot open ESP32 serial port: %s", error)
                connection = None
            if connection is None:
                self._stop.wait(RECONNECT_SECONDS)
                continue
            LOGGER.info("ESP32 serial connected on %s", connection.port)
            with self._write_lock:
                self._serial = connection
            try:
                while not self._stop.is_set():
                    raw = connection.readline()
                    if raw:
                        self.handle_line(raw.decode("utf-8", errors="replace").strip())
            except Exception:
                LOGGER.exception("ESP32 serial read failed; reconnecting")
            finally:
                with self._write_lock:
                    self._serial = None
                try:
                    connection.close()
                except Exception:
                    pass
            self._stop.wait(RECONNECT_SECONDS)
