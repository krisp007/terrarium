# ESP32 Installation Guide

## Doel

De ESP32 is de lokale sensor- en actuatorcontroller voor temperatuur, luchtvochtigheid, bodemvocht, aquariumtemperatuur en de ventilatoren. De firmware wordt lokaal geupload via MicroPython en communiceert met de Raspberry Pi over MQTT.

---

## 1. Virtuele omgeving

```bash
cd ~/terrarium-project
source esp32env/bin/activate
```

Controleer of `mpremote` beschikbaar is:

```bash
mpremote --help
```

---

## 2. Vast IP-netwerk voor ESP32

De ESP32 krijgt in de huidige opzet een vaste IP binnen het lokale netwerk, zodat MQTT-verbindingen en diagnose consistent blijven.

| Device | IP |
|--------|-----|
| Raspberry Pi 5 | 192.168.24.166 |
| ESP32 Klimaatcontroller | 192.168.24.141 |
| Moxa ioThinx 4510 | 192.168.24.170 |

Gebruik deze waarden in de WiFi- en MQTT-configuratie.

---

## 3. Verbinden met de ESP32

Controleer de poort:

```bash
ls /dev/ttyUSB*
ls /dev/ttyACM*
```

Gebruik meestal:

```bash
mpremote connect /dev/ttyUSB0 fs ls
mpremote connect /dev/ttyUSB0 repl
mpremote connect /dev/ttyUSB0 soft-reset
mpremote connect /dev/ttyUSB0 monitor
```

---

## 4. WiFi configuratie

De ESP32 gebruikt een WiFi-configuratiebestand met SSID en wachtwoord. Zorg dat de WiFi-gegevens exact overeenkomen met het lokale netwerk.

Voorbeeld `config.json`:

```json
{
  "wifi": {
    "ssid": "IUVARE_LAN",
    "password": "<wachtwoord>"
  },
  "mqtt": {
    "server": "192.168.24.166",
    "client_id": "esp32_sensor_node"
  }
}
```

Bij het uploaden van de firmware moet deze config lokaal beschikbaar zijn op de ESP32.

---

## 5. Firmware uploaden

Upload de hoofdcode:

```bash
mpremote connect /dev/ttyUSB0 fs cp main.py :main.py
```

Bij een nieuwe of gewijzigde firmware ook deze bestanden controleren en uploaden indien nodig:

```bash
mpremote connect /dev/ttyUSB0 fs ls
```

Na upload:

```bash
mpremote connect /dev/ttyUSB0 reset
```

---

## 6. Handige controlecommando's

```bash
source ~/terrarium-project/esp32env/bin/activate
mpremote connect /dev/ttyUSB0 fs ls
mpremote connect /dev/ttyUSB0 repl
mpremote connect /dev/ttyUSB0 monitor
```

Controleer in de REPL of het netwerk en MQTT-verbinding succesvol zijn.

---

## 7. Verificatie

Na een reset moet de ESP32:

- verbinding maken met WiFi
- verbinding maken met de MQTT-broker op `192.168.24.166`
- een `esp32/status` heartbeat publiceren
- sensordata publiceren op `esp32/sensors`

Controleer via:

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

Als de heartbeat verschijnt en de sensordata wordt gepubliceerd, is de ESP32 correct geinstalleerd.

---

## 8. Belangrijkste aandachtspunt

Hou de WiFi-gegevens, MQTT-server, client ID en GPIO-mapping altijd in sync met de actuele hardware. Het systeem werkt alleen betrouwbaar als de sensor- en actuatorconfiguratie exact overeenkomt met de fysieke opstelling.