from machine import I2C, Pin
import json
import time

from Wifi import connect_to_wifi
from mqtt_pi import connect_mqtt

from sht30 import read_sht30
from tca9548a import select_channel

from aquarium import read_aquarium_temp
from soil import read_soil_left
from soil import read_soil_right


# ---------------------------------
# MQTT Heartbeat
# ---------------------------------

def send_heartbeat(client):

    heartbeat = {
        "device": "esp32_main",
        "status": "online",
        "uptime": time.ticks_ms() // 1000
    }

    client.publish(
        "esp32/status",
        json.dumps(heartbeat)
    )


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

    temp_top, hum_top = read_sht(i2c, 0)

    temp_left, hum_left = read_sht(i2c, 1)

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

connect_to_wifi()

client = connect_mqtt()

i2c = I2C(
    0,
    scl=Pin(22),
    sda=Pin(21),
    freq=10000
)

print("I2C Scan:", i2c.scan())

last_heartbeat = time.time()


# ---------------------------------
# Main Loop
# ---------------------------------

while True:

    try:

        if time.time() - last_heartbeat >= 60:

            send_heartbeat(client)

            last_heartbeat = time.time()

        payload = build_payload(i2c)

        client.publish(
            "esp32/sensors",
            json.dumps(payload)
        )

        print(payload)

    except Exception as e:

        print("Error:", e)

    time.sleep(120)