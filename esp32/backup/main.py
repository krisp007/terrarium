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

from heartbeat import send_heartbeat
from pca9685 import PCA9685
from vents import VentController


vent_controller = None
fan_outputs = {"fan1": 0, "fan6": 0}


def handle_fan_command(topic, message):
    """Apply Pi fan commands: CH0=fan1 and CH5=fan6."""
    global vent_controller
    try:
        command = json.loads(message)
        channels = command.get("channels", {})
        fan1 = channels.get("fan1", 0)
        fan6 = channels.get("fan6", 0)
        if fan1 > 0 and fan_outputs["fan1"] == 0:
            vent_controller.set_fan(0, 100)
            time.sleep_ms(2000)
        if fan6 > 0 and fan_outputs["fan6"] == 0:
            vent_controller.set_fan(5, 100)
            time.sleep_ms(2000)
        vent_controller.set_fan(0, fan1)
        vent_controller.set_fan(5, fan6)
        fan_outputs["fan1"] = fan1
        fan_outputs["fan6"] = fan6
        level = command.get("level", 0)
        for channel in range(1, 5):
            vent_controller.set_fan(channel, level)
        print("Fan command applied", command)
    except Exception as error:
        print("Fan command error", error)

def configure_mqtt_client(mqtt_client):
    mqtt_client.set_callback(handle_fan_command)
    mqtt_client.subscribe("esp32/cmd/fans")

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

wifi_ok = connect_to_wifi()

if wifi_ok:
    print("WiFi connected")
else:
    print("WiFi failed, starting without network")

client = connect_mqtt()

if client is None:
    print("MQTT connection failed")
else:
    print("MQTT connected")
    configure_mqtt_client(client)
    send_heartbeat(client)


i2c = I2C(
    0,
    scl=Pin(22),
    sda=Pin(21),
    freq=10000
)

pca = PCA9685(i2c)
pca.freq(500)
vent_controller = VentController(pca)

print("I2C Scan:", i2c.scan())


# ---------------------------------
# Main Loop
# ---------------------------------

while True:

    try:

        if client is None:
            client = connect_mqtt()
            if client is not None:
                configure_mqtt_client(client)

        if client is not None:
            client.check_msg()
            payload = build_payload(i2c)
            print("Payload OK")
            print(payload)
            if send_heartbeat(client):
                print("Publishing MQTT")
                client.publish(
                    "esp32/sensors",
                    json.dumps(payload)
                )
                print("MQTT Published")
        else:
            print("MQTT unavailable, skipping publish")

    except Exception as e:

        print("ERROR:")
        print(e)

    for _ in range(120):
        if client is not None:
            try:
                client.check_msg()
            except Exception as error:
                print("MQTT command check error", error)
        time.sleep(1)
