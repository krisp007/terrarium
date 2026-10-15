import network
import json


def send_heartbeat(client):

    if client is None:
        print("No MQTT client available, heartbeat skipped")
        return False

    try:

        wlan = network.WLAN(network.STA_IF)

        heartbeat = {

            "device": "esp32_sensor_node",

            "status": "online",

            "ip": wlan.ifconfig()[0],

            "firmware": "1.0.0"
        }

        client.publish(
            "esp32/status",
            json.dumps(heartbeat)
        )

        print("Heartbeat sent")

        return True

    except Exception as e:

        print("Error sending heartbeat:", e)

        return False