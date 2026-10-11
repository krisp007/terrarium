import network # type: ignore
import time
import json

def load_wifi_config():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            ssid = config['wifi']['ssid']
            password = config['wifi']['password']
            return ssid, password
    except Exception as e:
        print("Error loading WiFi configuration:", e)
        return None, None
    
def connect_to_wifi():
    ssid, password = load_wifi_config()
    if ssid is None or password is None:
        print("WiFi configuration not found or invalid.")
        return False
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(ssid, password)

        timeout = 10  # seconds  
         # Wait for the connection to establish
        while not wlan.isconnected():
            print("Connecting to WiFi...")
            time.sleep(1)
            timeout -= 1
    if wlan.isconnected():
        print("Connected to WiFi")
        print("Network config:", wlan.ifconfig())
        return True
    else:
        print("Failed to connect to WiFi")
        return False