# Terrarium Master Documentation v2.1

Auteur: Kristiaan Pinxten
Versie: 2.1
Status: Current Hardware Baseline

---

# 1. Doel

Deze documentatie beschrijft de huidige hardware-architectuur van het terrariumproject zoals deze in de praktijk is opgebouwd.

Het systeem is ontworpen als een terrarium op basis van een Costa Rica-achtig klimaat: het simuleert dag/nacht, regenseizoen en droog seizoen, met een natuurlijke variatie in vochtigheid, temperatuur en lichtcycli.

Het systeem bevat:

- Raspberry Pi 5 als centrale controller en MQTT broker
- ESP32 als lokale sensor- en actuatorcontroller
- Moxa ioThinx 4510 als veiligheidscontroller
- Azure IoT Hub / Cosmos als cloudlaag voor monitoring en historie
- PWM-ventilatie, verlichting en beschermende logica voor reservoirs en lekkage

---

# 2. Systeemarchitectuur

```text
                                  ┌──────────────────────────┐
                                  │       Azure Cloud        │
                                  │ IoT Hub / Cosmos / Grafana│
                                  └────────────┬─────────────┘
                                               │
                                               │ MQTT / IoT
                                               │
                                  ┌────────────▼─────────────┐
                                  │     Raspberry Pi 5       │
                                  │──────────────────────────│
                                  │ Mosquitto MQTT Broker    │
                                  │ Climate Logic            │
                                  │ Historiek / Dashboard    │
                                  │ Command dispatch         │
                                  └────────────┬─────────────┘
                                               │
                              ┌────────────────┼────────────────┐
                              │                │                │
                              │ MQTT           │ MQTT           │ MQTT
                              ▼                ▼                ▼
                      ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
                      │    ESP32     │  │    ESP32     │  │    Moxa      │
                      │ Sensor node │  │ Actuator     │  │ Safety ctrl  │
                      └──────────────┘  └──────────────┘  └──────────────┘
```

---

# 3. Rollen per subsystem

## 3.1 Raspberry Pi 5

Functie:

Centrale controller en edge-platform.

Taken:

- Mosquitto broker
- climate control logic
- historiek en dashboard
- Azure integratie
- MQTT command dispatch naar ESP32 en Moxa

Publisheert:

- `moxa/cmd/#`
- `esp32/cmd/#`

Subscribes:

- `esp32/sensors`
- `esp32/status`
- `moxa/status`

---

## 3.2 ESP32

Functie:

Sensor- en actuatorcontroller voor lokale metingen en ventilatie.

Taken:

- SHT30 sensoren uitlezen
- aquariumtemperatuur meten
- bodemvocht meten
- heartbeat publiceren
- ventilatoren bedienen via PCA9685
- dimmen van LED-groepen via DFR0971
- lokale dag-/nachtcyclus ondersteunen in combinatie met de Pi-logica

Publiceert:

- `esp32/sensors`
- `esp32/status`

Ontvangt:

- `esp32/cmd/fans`
- `esp32/cmd/lights`

---

## 3.3 Moxa ioThinx 4510

Functie:

Veiligheids- en schakelcontroller voor kritische functies.

Taken:

- reservoirniveau bewaken
- lekdetectie
- RO-niveau bewaken
- LED-voeding en watercirculatie regelen
- alarmstatus via MQTT publiceren
- fail-safe beveiliging bij verlies van klimaatcontrole of vochtigheidsscenario's

Publiceert:

- `moxa/status`

Ontvangt:

- `moxa/cmd/output`

---

# 4. ESP32 bus- en I/O mapping

## 4.1 I²C bus

- SDA = GPIO21
- SCL = GPIO22

Op deze bus zitten:

- TCA9548A @ 0x70
- PCA9685 @ 0x40
- DFR0971 dimming board

---

## 4.2 TCA9548A

Adres:

- `0x70`

Kanalen:

- CH0 = SHT30 Left
- CH1 = SHT30 Top
- CH2 = SHT30 Right

---

## 4.3 SHT30 sensoren

Metingen:

- temperatuur
- luchtvochtigheid

Sensoren:

- SHT30 Left
- SHT30 Top
- SHT30 Right

---

## 4.4 DS18B20 aquariumtemperatuur

Pin:

- GPIO4

Bekabeling:

- VCC → 3.3V
- DATA → GPIO4
- GND → GND
- 1kΩ pull-up naar 3.3V

---

## 4.5 Soil sensors

- GPIO32 = Soil Sensor Left
- GPIO33 = Soil Sensor Right

---

## 4.6 PCA9685

Adres:

- `0x40`

Fan kanalen:

- CH0 = Ventilator 1
- CH1 = Ventilator 2
- CH2 = Ventilator 3
- CH3 = Ventilator 4
- CH4 = Ventilator 5
- CH5 = Ventilator 6

---

## 4.7 DFR0971

- VOUT0 = LED 1 dim
- VOUT1 = LED 2 dim

---

# 5. ESP32 heartbeat

Topic:

- `esp32/status`

Interval:

- elke 60 seconden

Voorbeeld payload:

```json
{
  "device": "esp32_sensor_node",
  "status": "online",
  "ip": "192.168.24.141",
  "firmware": "1.0.0"
}
```

---

# 6. ESP32 sensordata

Topic:

- `esp32/sensors`

Voorbeeld payload:

```json
{
  "temperature_top": 26.4,
  "humidity_top": 68.7,
  "temperature_left": 28.7,
  "humidity_left": 49.3,
  "temperature_right": 26.6,
  "humidity_right": 55.2,
  "aquarium_temp": 24.5,
  "soil_left": 72,
  "soil_right": 68
}
```

---

# 7. Moxa veiligheidsmap

## 7.1 Digitale ingangen

- DI0 = Vlotter mistmaker
- DI1 = Vlotter beregening
- DI2 = Lekdetectie
- DI3 = Vlotter min RO
- DI4 = Vlotter max RO

## 7.2 Digitale uitgangen

- DO0 = LED Links voeding
- DO1 = LED Mid1 voeding
- DO2 = LED Mid2 voeding
- DO3 = LED Rechts voeding
- DO4 = Beregening
- DO5 = Mistmaker
- DO6 = Warmtelamp
- DO7 = Watervalpomp
- DO8 = Reserve
- DO9 = Pomp 1 mistmaker
- DO10 = Pomp 2 beregening
- DO11 = Pomp 3
- DO12 = Pomp 4
- DO13 = Reserve
- DO14 = Reserve
- DO15 = WaterValve RO

---

# 8. Veiligheidsregels

- lekdetectie => mistmaker, beregening, pompen OFF
- reservoir laag => pomp stop / alarm
- RO niveau buiten bereik => RO verwerking stop / alarm
- no heartbeat ESP32 => alarm / systeem in fail-safe modus

---

# 9. Belangrijkste opmerking

De float switches en lekdetectie worden rechtstreeks naar de Moxa geleid. De ESP32 heeft geen directe GPIO-positie voor deze veiligheidsingangen.

---

Einde document v2.1

```json
{
  "device": "esp32_sensor_node",
  "status": "online",
  "ip": "192.168.24.141",
  "firmware": "1.0.0"
}
```

Interval:

- 60 seconden

Doel:

- controleer of de sensor-node nog online is
- detecteer offline-condities en trigger alarms

---

# 6. Actuatorplatform

## 6.1 PCA9685

Adres:

- `0x40`

Communicatie:

- I²C

Functie:

- PWM-signalen genereren
- ventilatoren aansturen

## 6.2 Ventilator kanalen

- CH0 = Ventilator Left Front
- CH1 = Ventilator Left Back
- CH2 = Ventilator Middle Front
- CH3 = Ventilator Middle Back
- CH4 = Ventilator Right Front
- CH5 = Ventilator Right Back

Aantal:

- 6 ventilatoren
- 12V DC voeding

## 6.3 XY-MOS modules

- ieder ventilator kanaal heeft een eigen PWM-geschakeld module
- gezamenlijke 12V voeding
- gemeenschappelijke GND met ESP32, PCA9685 en modules

---

# 7. Moxa veiligheidslogica

## 7.1 Digitale ingangen

- DI0 = Mistmaker niveau
- DI1 = Beregening niveau
- DI2 = Lekdetectie

## 7.2 Digitale uitgangen

- DO0 = Warmtelamp links
- DO1 = Warmtelamp rechts
- DO2 = Mistmaker
- DO3 = Beregening
- DO4 = Vulpomp mistmaker
- DO5 = Vulpomp beregening
- DO6 = Watervalpomp

---

# 8. Verlichting

- 4x Mars Hydro FC-E1500
- 150W per licht
- volgroeide spectrumverlichting

Indeling:

- LED Left
- LED Mid1
- LED Mid2
- LED Right

Controle:

- ON/OFF via Moxa
- dimmen nog te definiëren

---

# 9. MQTT basiscontract

## 9.1 ESP32 topics

- `esp32/sensors`
- `esp32/status`
- `esp32/cmd/fans`
- `esp32/cmd/lights`

## 9.2 Moxa topics

- `moxa/status`
- `moxa/cmd/output`

---

# 10. Veiligheidsregels

## Lek gedetecteerd

Acties:

- mistmaker OFF
- beregening OFF
- vulpomp mistmaker OFF
- vulpomp beregening OFF
- alarm genereren

## Reservoir laag / leeg

Acties:

- pomp stoppen
- alarm genereren

## Geen ESP32 heartbeat

Acties:

- systeemstatus markeren als offline
- alarm genereren na timeout

---

# 11. Toekomstige uitbreidingen

- ESP32-CAM
- CO₂ sensor
- PAR sensor
- LUX sensor
- weerstation
- Azure dashboard
- automatische zonsopgang / zonsondergang
- camera snapshots bij alarm

---

# 12. Disaster Recovery

Na Raspberry crash:

1. Raspberry Pi OS installeren
2. Git repository clonen
3. Python virtual environment herstellen
4. `requirements.txt` installeren
5. Mosquitto installeren
6. services activeren
7. ESP32 firmware uploaden
8. MQTT testen
9. systeem online brengen

---

Einde document v2.0


Functie:

PWM → Vermogensschakelaar

Per ventilator:

1 module

Schema:

PCA9685
    │
PWM
    │
XY-MOS
    │
Ventilator

---

# 10. Ventilator Voeding

12V voeding

Aangesloten op:

- 6 ventilatoren
- XY-MOS modules

Gemeenschappelijke GND:

ESP32
PCA9685
XY-MOS
12V voeding

---

# 11. Moxa ioThinx 4510

Functie:

Safety Controller

Realtime ingangen

Realtime uitgangen

---

# 12. Moxa Ingangen

DI0

Mistmaker niveau

---

DI1

Beregening niveau

---

DI2

Lekdetectie

---

# 13. Moxa Uitgangen

DO0

Warmtelamp links

---

DO1

Warmtelamp rechts

---

DO2

Mistmaker

---

DO3

Beregening

---

DO4

Vulpomp mistmaker

---

DO5

Vulpomp beregening

---

DO6

Watervalpomp

---

# 14. LED Verlichting

4x Mars Hydro FC-E1500

150W

Volspectrum

---

Indeling:

LED Left

LED Mid1

LED Mid2

LED Right

---

Voedingen:

ON/OFF via Moxa

---

Dimming:

Nog te bepalen

Waarschijnlijk:

RJ11 0-10V interface

Onderzoek lopende.

---

# 15. MQTT Topics

## ESP32

esp32/sensors

esp32/status

esp32/cmd/fans

esp32/cmd/lights

---

## Moxa

moxa/status

moxa/cmd/output

---

# 16. Veiligheidsregels

## Lek gedetecteerd

Acties:

- Mistmaker OFF
- Beregening OFF
- Vulpomp mistmaker OFF
- Vulpomp beregening OFF

Alarm genereren

---

## Reservoir Vol

Acties:

- Vulpomp stoppen

---

## Geen Heartbeat

ESP32 > 180 seconden offline

Alarm genereren

---

# 17. Toekomstige Uitbreidingen

- ESP32-CAM
- CO₂ sensor
- PAR sensor
- LUX sensor
- Weerstation
- Azure Dashboard
- Automatische zonsopgang
- Automatische zonsondergang
- Camera snapshots bij alarm

---

# 18. Disaster Recovery

Na Raspberry crash:

1. Raspberry Pi OS installeren
2. Git repository klonen
3. Python Virtual Environment herstellen
4. requirements.txt uitvoeren
5. Mosquitto installeren
6. Services activeren
7. ESP32 firmware uploaden
8. MQTT testen
9. Systeem online brengen

Einde document.