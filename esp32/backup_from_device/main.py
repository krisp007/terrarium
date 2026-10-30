from machine import I2C, Pin
import json
import time

import sys
import uselect
from machine import WDT

from sht30 import read_sht30
from tca9548a import select_channel

from aquarium import read_aquarium_temp
from soil import read_soil_left
from soil import read_soil_right

from pca9685 import PCA9685
from vents import VentController


vent_controller = None
fan_outputs = {f"fan{channel + 1}": 0 for channel in range(6)}
FAN_STARTUP_BOOST_PERCENT = 100
FAN_STARTUP_BOOST_MS = 1000


def handle_fan_command(message):
    """Apply per-channel fan commands, falling back to the shared level."""
    global vent_controller
    try:
        command = json.loads(message)
        channels = command.get("channels", {})
        level = command.get("level", 0)
        target_outputs = {
            f"fan{channel}": channels.get(f"fan{channel}", level)
            for channel in range(1, 7)
        }
        starting_channels = [
            channel
            for channel in range(6)
            if target_outputs[f"fan{channel + 1}"] > 0
            and fan_outputs[f"fan{channel + 1}"] == 0
        ]
        for channel in starting_channels:
            vent_controller.set_fan(channel, FAN_STARTUP_BOOST_PERCENT)
        if starting_channels:
            time.sleep_ms(FAN_STARTUP_BOOST_MS)
        for channel in range(6):
            fan_name = f"fan{channel + 1}"
            vent_controller.set_fan(channel, target_outputs[fan_name])
            fan_outputs[fan_name] = target_outputs[fan_name]
        print("Fan command applied", command)
    except Exception as error:
        print("Fan command error", error)

# ---------------------------------
# USB serial link (frames: "@" + JSON {"t": topic, "p": payload})
# ---------------------------------

SENSOR_INTERVAL_MS = 60000
STATUS_INTERVAL_MS = 60000
WATCHDOG_MS = 30000

poller = uselect.poll()
poller.register(sys.stdin, uselect.POLLIN)
rx_buffer = ""


def send_frame(topic, payload):
    print("@" + json.dumps({"t": topic, "p": payload}))


def handle_frame(line):
    try:
        frame = json.loads(line)
    except Exception as error:
        print("Bad frame", error)
        return
    if frame.get("t") == "esp32/cmd/fans":
        handle_fan_command(json.dumps(frame.get("p", {})))


def poll_serial():
    """Read pending serial characters without blocking and dispatch frames."""
    global rx_buffer
    while poller.poll(0):
        char = sys.stdin.read(1)
        if not char:
            return
        if char == "\n":
            line = rx_buffer.strip()
            rx_buffer = ""
            if line.startswith("@"):
                handle_frame(line[1:])
        elif len(rx_buffer) < 2048:
            rx_buffer += char
        else:
            rx_buffer = ""


# ---------------------------------
# SHT30 helper
# ---------------------------------

def read_sht(i2c, channel):

    try:

        select_channel(i2c, channel)

        return read_sht30(i2c)

    except Exception as e:

        print(
            "SHT30 Channel",
            channel,
            e
        )

        return None, None


# ---------------------------------
# Payload
# ---------------------------------

def build_payload(i2c):

    temp_left, hum_left = read_sht(i2c, 0)

    temp_top, hum_top = read_sht(i2c, 1)

    temp_right, hum_right = read_sht(i2c, 2)

    return {

        "temperature_top": temp_top,
        "humidity_top": hum_top,

        "temperature_left": temp_left,
        "humidity_left": hum_left,

        "temperature_right": temp_right,
        "humidity_right": hum_right,

        "aquarium_temp": read_aquarium_temp(),

        "soil_left": read_soil_left(),
        "soil_right": read_soil_right()
    }


# ---------------------------------
# Setup
# ---------------------------------

i2c = I2C(
    0,
    scl=Pin(22),
    sda=Pin(21),
    freq=10000
)

pca = PCA9685(i2c)
pca.freq(20000)
vent_controller = VentController(pca)

print("I2C Scan:", i2c.scan())

wdt = WDT(timeout=WATCHDOG_MS)

# ---------------------------------
# Main Loop
# ---------------------------------

last_sensors = time.ticks_add(time.ticks_ms(), -SENSOR_INTERVAL_MS)
last_status = last_sensors

while True:

    wdt.feed()
    poll_serial()
    now = time.ticks_ms()

    if time.ticks_diff(now, last_status) >= STATUS_INTERVAL_MS:
        last_status = now
        send_frame("esp32/status", {
            "device": "esp32_sensor_node",
            "status": "online",
            "transport": "usb_serial",
            "firmware": "2.0.0",
        })

    if time.ticks_diff(now, last_sensors) >= SENSOR_INTERVAL_MS:
        last_sensors = now
        try:
            send_frame("esp32/sensors", build_payload(i2c))
        except Exception as e:
            print("ERROR:", e)
        wdt.feed()

    time.sleep_ms(50)
