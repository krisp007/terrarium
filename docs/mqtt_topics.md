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
- `channels.fan1` en `channels.fan6` houden permanent minimale luchtstroom in stand
- fan 1 en fan 6 wisselen standaard elke 60 seconden op 25%

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
- de Pi publiceert dit commando bij elk `esp32/sensors`-bericht
- dag, nacht, zonsopkomst en zonsondergang volgen de terrarium-schedule

Voorbeeld overdag:

```json
{
  "state": "on",
  "brightness": 80,
  "leds": {
    "led1": 80,
    "led2": 80,
    "led3": 80,
    "led4": 80
  }
}
```

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

## 8. Sensorregeling naar Moxa

Bij elk bericht op `esp32/sensors` stuurt de Pi naast het fancommando ook een
commando naar `moxa/cmd/output`:

```json
{
  "do4": "OFF",
  "do5": "ON",
  "mistmaker": "ON",
  "beregening": "OFF",
  "alarm": false,
  "reason": "sensor_control"
}
```

De as-built mapping is:

- `DO4` = beregening
- `DO5` = mistmaker

De standaard regenwoudgrenzen zijn:

- gemiddelde RH onder 82%: `DO5 ON`
- gemiddelde RH vanaf 90%: `DO5 OFF`
- gemiddelde bodemvochtigheid onder 35%: `DO4 ON`
- gemiddelde bodemvochtigheid vanaf 55%: `DO4 OFF`

Bij een gemiddelde temperatuur onder `safety.temperature_too_low_c` wordt
`DO06` als warmtelamp ingeschakeld. Bij normale of te hoge temperatuur wordt
`DO06` uitgeschakeld. Een lek- of veiligheidsalarm heeft voorrang en schakelt
`DO06` uit.

Een lek (`DI2`) of laag reservoir (`DI0` / `DI1`) heeft altijd prioriteit en
blokkeert de bijbehorende uitgang.

Tijdens het regenseizoen kan de regelengine willekeurig een korte regenbui
starten. De instellingen staan onder `seasons.rainy.rainstorm`:

```json
{
  "enabled": true,
  "chance_percent": 5,
  "duration_minutes": 2,
  "cooldown_minutes": 30
}
```

Een actieve bui zet `DO4` (beregening) en `DO5` (mistmaker) aan. De bui werkt
niet tijdens het droge seizoen en wordt altijd geblokkeerd door lek-, alarm- of
reservoirstatus.

---

## 9. Convention notes

- JSON is de standaard payloadvorm
- topicnamen zijn lowercase en logisch benoemd
- bij veranderingen aan topic-namen of velden moet de documentatie direct worden aangepast
- alle status- en alarmtopics moeten in de regels van de automations terug te vinden zijn

---

## 10. Acceptatiechecks

Controleer in de broker met:

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

Je verwacht:

- `esp32/sensors`
- `esp32/status`
- `moxa/status`

Als deze topics zichtbaar zijn, is de MQTT-basis opstelling correct.
