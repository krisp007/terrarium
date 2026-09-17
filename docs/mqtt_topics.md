# MQTT Topics v2.0

## 1. Doel

MQTT is het centrale communicatieprotocol binnen het terrariumproject. De ESP32 publiceert sensordata en status naar de Raspberry Pi, en de Raspberry Pi stuurt opdrachten terug naar de ESP32 of Moxa.

---

## 2. Gebruik van topics

### ESP32 > Raspberry Pi

- `esp32/sensors` — metingen van temperatuur, luchtvochtigheid, aquariumtemperatuur en bodemvocht
- `esp32/status` — heartbeat en online-status

### Raspberry Pi > ESP32

- `esp32/cmd/fans` — ventilaatorcommando's
- `esp32/cmd/lights` — verlichtingscommando's

### Moxa > Raspberry Pi

- `moxa/status` — status van digitale ingangen en alarmcondities

### Raspberry Pi > Moxa

- `moxa/cmd/output` — outputs aan/uit of relaiscommando's

---

## 3. Payload: esp32/sensors

```json
{
  "temperature_top": 25.6,
  "humidity_top": 67.2,
  "temperature_left": 25.9,
  "humidity_left": 68.5,
  "temperature_right": 26.1,
  "humidity_right": 66.8,
  "aquarium_temp": 24.3,
  "soil_left": 52.1,
  "soil_right": 48.7
}
```

Beschrijving:

- `temperature_top`: temperatuur aan bovenste SHT30
- `humidity_top`: luchtvochtigheid bovenste SHT30
- `temperature_left`: temperatuur aan linker SHT30
- `humidity_left`: luchtvochtigheid linker SHT30
- `temperature_right`: temperatuur aan rechter SHT30
- `humidity_right`: luchtvochtigheid rechter SHT30
- `aquarium_temp`: aquariumtemperatuur via DS18B20
- `soil_left`: bodemvocht links
- `soil_right`: bodemvocht rechts

---

## 4. Payload: esp32/status

```json
{
  "device": "esp32_sensor_node",
  "status": "online",
  "ip": "192.168.24.141",
  "firmware": "1.0.0"
}
```

Gebruik:

- controleer beschikbaarheid van de sensor-node
- detecteer offline-status na timeout
- log heartbeat voor alarmcontrole

---

## 5. Payload: esp32/cmd/fans

Voorbeeld:

```json
{
  "mode": "auto",
  "level": 75
}
```

Gebruik:

- status voor ventilatiecontrole
- PWM-niveau of modusoverschrijving

---

## 6. Payload: esp32/cmd/lights

Voorbeeld:

```json
{
  "state": "on",
  "brightness": 60
}
```

Gebruik:

- verlichtingsschakeling en dimniveau
- nog te definiëren in detail afhankelijk van de gebruikte hardwareinterface

---

## 7. Payload: moxa/status

Voorbeeld:

```json
{
  "di0": true,
  "di1": false,
  "di2": false,
  "alarm": false,
  "timestamp": 1720000000
}
```

Gebruik:

- status van reservoirniveaus en lekdetectie
- alarm- en veiligheidscontrole

---

## 8. Convention notes

- JSON is de standaard payloadvorm
- topicnamen zijn lowercase en logisch benoemd
- bij veranderingen aan topic-namen of velden moet de documentatie direct worden aangepast
- alle status- en alarmtopics moeten in de regels van de automations terug te vinden zijn

---

## 9. Acceptatiechecks

Controleer in de broker met:

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

Je verwacht:

- `esp32/sensors`
- `esp32/status`
- `moxa/status`

Als deze topics zichtbaar zijn, is de MQTT-basis opstelling correct.
