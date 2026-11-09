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
- elke ventilator die van `0` naar een actief niveau start, draait eerst 1 seconde op 100%
  en gaat daarna naar het gevraagde PWM-niveau

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

Dezelfde Moxa-payload bevat ook de vier LED-voedingsuitgangen. De Moxa schakelt
de voeding fysiek aan of uit; de ESP32 regelt het dimniveau via
`esp32/cmd/lights` en de DFR0971:

```json
{
  "do0": "ON",
  "do1": "ON",
  "do2": "ON",
  "do3": "ON",
  "do4": "OFF",
  "do5": "ON",
  "do6": "OFF",
  "mistmaker": "ON",
  "beregening": "OFF",
  "alarm": false,
  "reason": "sensor_control"
}
```

De lichtscheduler gebruikt `DO0` tot en met `DO3` als volgt:

- overdag of tijdens de dawn/dusk-ramp: `ON` voor elke LED-groep met een dimwaarde groter dan 0
- 's nachts: `OFF` voor alle vier LED-groepen
- elk Moxa-commando wordt vertaald naar `ioThinx_4510/write/DO@DO-xx/doStatus`
  met `{"value":1}` voor `ON` en `{"value":0}` voor `OFF`

De as-built mapping is:

- `DO0` = LED Links voeding
- `DO1` = LED Mid1 voeding
- `DO2` = LED Mid2 voeding
- `DO3` = LED Rechts voeding
- `DO4` = beregening
- `DO5` = mistmaker
- `DO6` = warmtelamp

`DO4` is een korte regenpuls; bodemvochtmetingen zijn alleen telemetry en
starten deze uitgang niet. In het actieve regenseizoen kan regen willekeurig
met de ingestelde kans starten, of gepland in het venster vóór zonsopkomst en
zonsondergang. Beide triggers vereisen dat de gemiddelde RH op of onder de
actieve dag-/nachtwaarde `humidity.min_percent` ligt. Een regenpuls duurt
maximaal één minuut.

Tijdens regen is `DO4 ON` en `DO5 OFF`. Alleen na een geplande regenpuls kan
`DO5` maximaal 10 minuten als napermist draaien. Napermist wordt onderdrukt
zodra RH `humidity.target_percent + 5` bereikt; boven die grens heeft
ventilatie voorrang.

De luchtvochtigheids- en temperatuurdoelen komen uit de actieve
`seasons.<season>.<day|night>`-instellingen. Bij `target + 5` wordt ventilatie
op 50% gezet en daarboven op 100%. De warmtelamp (`DO6`) gaat aan wanneer de
gemiddelde temperatuur onder het actieve `temperature.target_c` ligt, behalve
bij de ingestelde hoge-temperatuur- of leksafety.

Een lek- of veiligheidsalarm heeft altijd voorrang: het schakelt regen, mist,
warmtelamp, aquarium-bijvulling (`DO12`) en RO-ventiel (`DO15`) uit.

Een lek (`DI2`) heeft altijd prioriteit en schakelt DO12 en DO15 uit. DI0 is de
RO-vlotter: alleen bij actieve DI0 zonder lekalarm wordt DO15 `ON`. DI1 is de
aquarium-bijvulvlotter: alleen bij actieve DI1 zonder lekalarm wordt DO12 `ON`.
Bij inactieve of ontbrekende DI0/DI1 blijven de bijbehorende uitgangen `OFF`.

De cyclische pompen worden ingesteld met de rootvelden `waterfall` en
`orchid_dripper`. `waterfall.enabled` staat voorlopig op `false` totdat de
beplanting geworteld is; die functie gebruikt DO10. De orchideeëndruppelaar
gebruikt DO11 en leest `enabled`, `auto_mode`, `cycle_minutes` en
`duration_seconds` uit JSON. Met de huidige instellingen draait DO11 45
seconden per 90 minuten. De timer start pas wanneer de Moxa online is en DI2
geen lek meldt; bij offline Moxa of alarm worden DO10 en DO11 uitgeschakeld.

Tijdens het regenseizoen kan de regelengine willekeurig een korte regenbui
starten. De instellingen staan onder `seasons.rainy.rainstorm`:

```json
{
  "enabled": true,
  "chance_percent": 5,
  "duration_minutes": 1,
  "cooldown_minutes": 30,
  "pre_light_lead_minutes": 5,
  "post_rain_mist_minutes": 10
}
```

Een regenpuls zet `DO4` aan. `DO5` blijft tijdens de regen uit en kan alleen na
een geplande puls als napermist worden ingeschakeld. Regen werkt niet buiten
het actieve regenseizoen, boven de minimumvochtigheid of bij lek-/alarmstatus.

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
