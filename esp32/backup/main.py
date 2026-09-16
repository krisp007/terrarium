from machine import Pin, I2C
from tca9548a import select_channel
from aquarium import read_aquarium_temp
from soil import read_soil_left
from soil import read_soil_right

from Wifi import connect_to_wifi
from mqtt_pi import connect_mqtt
from sht30 import read_sht30

import network
import json
import time


# --------------------------------------------------
# MQTT Heartbeat
# --------------------------------------------------
def send_heartbeat(client):
    wlan = network.WLAN(network.STA_IF)

    heartbeat = {
        "device": "esp32_main",
        "status": "online",
        "uptime": time.ticks_ms() // 1000,
        "ip": wlan.ifconfig()[0]
    }

    client.publish(
        "esp32/status",
        json.dumps(heartbeat)
    )


# --------------------------------------------------
# WiFi + MQTT
# --------------------------------------------------
connect_to_wifi()
client = connect_mqtt()


# --------------------------------------------------
# I2C
# --------------------------------------------------
i2c = I2C(
    0,
    scl=Pin(22),
    sda=Pin(21),
    freq=10000
)


# --------------------------------------------------
# Inputs
# --------------------------------------------------

# Float switches
mistmaker_float = Pin(34, Pin.IN)
sprinkler_float = Pin(35, Pin.IN)

# Leak sensor
leak_sensor = Pin(27, Pin.IN)


# --------------------------------------------------
# Debug: scan TCA9548A channels
# --------------------------------------------------
print("I2C Channel Scan")

for channel in range(8):
    try:
        select_channel(i2c, channel)
        print(
            "Kanaal",
            channel,
            "=>",
            i2c.scan()
        )
    except Exception as e:
        print(
            "Kanaal",
            channel,
            "fout:",
            e
        )


# --------------------------------------------------
# Main Loop
# --------------------------------------------------
last_heartbeat = 0

while True:

    # ------------------------------
    # Heartbeat every minute
    # ------------------------------
    try:
        if time.time() - last_heartbeat >= 60:
            send_heartbeat(client)
            last_heartbeat = time.time()
    except Exception as e:
        print("Heartbeat error:", e)

    # ------------------------------
    # SHT30 TOP
    # ------------------------------
    try:
        select_channel(i2c, 0)
        temp_top, hum_top = read_sht30(i2c)
    except Exception as e:
        print("TOP sensor:", e)
        temp_top = None
        hum_top = None

    # ------------------------------
    # SHT30 LEFT
    # ------------------------------
    try:
        select_channel(i2c, 1)
        temp_left, hum_left = read_sht30(i2c)
    except Exception as e:
        print("LEFT sensor:", e)
        temp_left = None
        hum_left = None

    # ------------------------------
    # SHT30 RIGHT
    # ------------------------------
    try:
        select_channel(i2c, 2)
        temp_right, hum_right = read_sht30(i2c)
    except Exception as e:
        print("RIGHT sensor:", e)
        temp_right = None
        hum_right = None

    # ------------------------------
    # Aquarium temperature
    # ------------------------------
    try:
        aquarium_temp = read_aquarium_temp()
    except Exception as e:
        print("Aquarium sensor:", e)
        aquarium_temp = None

    # ------------------------------
    # Soil sensors
    # ------------------------------
    try:
        soil_left = read_soil_left()
    except Exception as e:
        print("Soil Left:", e)
        soil_left = None

    try:
        soil_right = read_soil_right()
    except Exception as e:
        print("Soil Right:", e)
        soil_right = None

    # ------------------------------
    # Water levels
    # ------------------------------
    try:
        mistmaker_level = mistmaker_float.value()
    except:
        mistmaker_level = None

    try:
        sprinkler_level = sprinkler_float.value()
    except:
        sprinkler_level = None

    # ------------------------------
    # Leak detection
    # ------------------------------
    try:
        leak_detected = leak_sensor.value()
    except:
        leak_detected = None

    # ------------------------------
    # Payload
    # ------------------------------
    payload = {
        "temperature_top": temp_top,
        "humidity_top": hum_top,

        "temperature_left": temp_left,
        "humidity_left": hum_left,

        "temperature_right": temp_right,
        "humidity_right": hum_right,

        "aquarium_temp": aquarium_temp,

        "soil_left": soil_left,
        "soil_right": soil_right,

        "mistmaker_level": mistmaker_level,
        "sprinkler_level": sprinkler_level,

        "leak_detected": leak_detected
    }

    print(payload)

    # ------------------------------
    # MQTT Publish
    # ------------------------------
    try:
        client.publish(
            "esp32/sensors",
            json.dumps(payload)
        )

    except Exception as e:
        print("MQTT Error:", e)

        try:
            client = connect_mqtt()
            print("MQTT reconnected")
        except Exception as reconnect_error:
            print(
                "MQTT reconnect failed:",
                reconnect_error
            )

    # ------------------------------
    # Wait 2 minutes
    # ------------------------------
    time.sleep(120)