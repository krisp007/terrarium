from umqtt.simple import MQTTClient
import json

def load_mqtt_config():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            server_ip = config['mqtt']['server']
            client_id = config['mqtt']['client_id']
            return server_ip, client_id
    except Exception as e:
        print("Error loading MQTT configuration:", e)
        return None, None


def connect_mqtt():

    server_ip, client_id = load_mqtt_config()
    if server_ip is None or client_id is None:
        print("MQTT configuration not found or invalid.")
        return None
    
    try:
        client = MQTTClient(client_id, server_ip)
        client.connect()
        print("Connected to MQTT broker at {}:{}".format(server_ip, 1883))
        return client
    except Exception as e:
        print("Failed to connect to MQTT broker:", e)
        return None