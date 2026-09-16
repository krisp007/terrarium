# Terrarium Master Documentation v1.0

Auteur: Kristiaan Pinxten
Versie: 1.0
Status: Design Baseline

---

# 1. Doel

Deze documentatie beschrijft de volledige architectuur van het terrarium/paludarium controlesysteem.

Doelstellingen:

- Volautomatische klimaatregeling
- Lokale autonomie
- MQTT communicatie
- Azure logging
- Veiligheidsfuncties
- Herstelbaarheid na Raspberry Pi of SD-kaart crash
- Modulaire uitbreidbaarheid

---

# 2. Overzicht Architectuur

                           Azure Cloud
                                │
                                │
                           MQTT / IoT
                                │
                                │
                    ┌───────────┴───────────┐
                    │    Raspberry Pi 5     │
                    │───────────────────────│
                    │ Mosquitto MQTT Broker │
                    │ Climate Logic         │
                    │ Automation Rules      │
                    │ Historian             │
                    │ Azure Integration     │
                    └───────┬───────┬───────┘
                            │       │
                       MQTT │       │ MQTT
                            │       │
                            ▼       ▼

                ┌─────────────────┐
                │      ESP32      │
                └─────────────────┘

                ┌─────────────────┐
                │   Moxa ioThinx  │
                │      4510       │
                └─────────────────┘

---

# 3. Raspberry Pi 5

Functie:

Centraal brein van de installatie.

Taken:

- MQTT Broker (Mosquitto)
- Klimaatregeling
- Regels en automatisatie
- Historische databank
- Azure IoT Hub
- Alarmen
- Logging
- Dashboard

Publisht:

moxa/cmd/#
esp32/cmd/#

Subscribes:

esp32/sensors
esp32/status
moxa/status

---

# 4. ESP32

Functie:

Realtime sensornode en PWM-controller.

Taken:

- Klimaatsensoren uitlezen
- PWM stuurwaarden ontvangen
- Ventilatoren aansturen
- LED dimsignalen genereren
- Heartbeat sturen

Publiceert:

esp32/sensors
esp32/status

Ontvangt:

esp32/cmd/fans
esp32/cmd/lights

---

# 5. ESP32 Sensoren

## I²C Bus

GPIO21 = SDA
GPIO22 = SCL

---

## TCA9548A

Adres:

0x70

---

## SHT30

Kanaal 0:

SHT30 Top

Kanaal 1:

SHT30 Left

Kanaal 2:

SHT30 Right

Metingen:

- temperatuur
- luchtvochtigheid

---

## DS18B20

GPIO4

Functie:

Aquarium temperatuur

Bekabeling:

- VCC → 3.3V
- DATA → GPIO4
- GND → GND

Pull-up:

1kΩ

Kabellengte:

10 meter

---

## Soil Sensor Left

GPIO32

Type:

Capacitive Soil Moisture Sensor v1.2

---

## Soil Sensor Right

GPIO33

Type:

Capacitive Soil Moisture Sensor v1.2

---

# 6. ESP32 Heartbeat

Topic:

esp32/status

Payload:

{
  "device": "esp32_main",
  "status": "online",
  "uptime": 3600
}

Interval:

60 seconden

---

# 7. PCA9685

Adres:

0x40

Communicatie:

I²C

---

# 8. Ventilator Kanalen

CH0 = Left Front

CH1 = Left Back

CH2 = Mid Front

CH3 = Mid Back

CH4 = Right Front

CH5 = Right Back

Aantal:

6 ventilatoren

Type:

Anima AF12X2

Voeding:

12V DC

---

# 9. XY-MOS Modules

Aantal:

6

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