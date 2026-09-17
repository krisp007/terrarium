# Terrarium Project - As-Built Summary

## 1. Systeemdoel

Het terrariumproject is opgebouwd als een lokaal geautomatiseerd klimaatsysteem met:

- Raspberry Pi 5 als centrale controller
- ESP32 als lokale sensor- en actuatorcontroller
- Moxa ioThinx 4510 als veiligheids- en schakelcontroller
- MQTT als lokale communicatiebus
- Azure IoT Hub / Cosmos voor historie en monitoring

---

## 2. Hardwarestructuur

### Raspberry Pi 5

Functie:

- MQTT broker (Mosquitto)
- klimaatlogica en automations
- dashboard / historiek
- Azure integratie
- command dispatch naar ESP32 en Moxa

Netwerk:

- Hostname: `KrisPi`
- IP: `192.168.24.166`
- Gateway: `192.168.24.1`
- WiFi SSID: `IUVARE_LAN`

---

### ESP32

Functie:

- sensoren uitlezen
- heartbeat sturen
- PWM-fanbesturing via PCA9685
- dimming van LED-groepen via DFR0971
- lokale status publiceren via MQTT

#### I²C bus

- SDA = GPIO21
- SCL = GPIO22

#### Sensoren op I²C / bus

- TCA9548A @ 0x70
- SHT30 Left → TCA9548A CH0
- SHT30 Top → TCA9548A CH1
- SHT30 Right → TCA9548A CH2

#### Lokale hardware inputs

- DS18B20 aquariumtemperatuur → GPIO4
- Soil Sensor Left → GPIO32
- Soil Sensor Right → GPIO33

#### Ventilators via PCA9685

- CH0 = Ventilator 1
- CH1 = Ventilator 2
- CH2 = Ventilator 3
- CH3 = Ventilator 4
- CH4 = Ventilator 5
- CH5 = Ventilator 6

#### DFR0971 dimming

- VOUT0 = LED 1 dim
- VOUT1 = LED 2 dim

---

### Moxa ioThinx 4510

Functie:

- veiligheidscontroller
- reservoirniveaus bewaken
- lekkage detecteren
- RO-niveau regelen
- outputschakeling voor verlichting, mistmaker, beregening, pompen

#### Digitale ingangen

- DI0 = Vlotter mistmaker
- DI1 = Vlotter beregening
- DI2 = Lekdetectie
- DI3 = Vlotter min RO
- DI4 = Vlotter max RO

#### Digitale uitgangen

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

## 3. MQTT contract

### ESP32 → Raspberry Pi

#### Topic

- `esp32/sensors`

#### Payload voorbeeld

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

#### Heartbeat

- Topic: `esp32/status`
- Interval: elke 60 seconden

Voorbeeld:

```json
{
  "device": "esp32_sensor_node",
  "status": "online",
  "ip": "192.168.24.141",
  "firmware": "1.0.0"
}
```

### Moxa → Raspberry Pi

- Topic: `moxa/status`

### Raspberry Pi → Moxa / ESP32

- `moxa/cmd/output`
- `esp32/cmd/fans`
- `esp32/cmd/lights`

---

## 4. Veiligheidsregels

- lekkage => mistmaker, beregening en pompen OFF
- reservoir laag => pomp stop / alarm
- RO niveau buiten bereik => RO-verwerking stop / alarm
- geen ESP32 heartbeat => fail-safe alarm

---

## 5. Huidige status

Dit is de huidige as-built baseline van het terrariumproject:

- Raspberry Pi = centrale controller en broker
- ESP32 = sensor- en ventilatiecontroller
- Moxa = veiligheidslaag
- MQTT = lokale command & telemetry bus
- Azure = cloudhistoriek / monitoringlaag

---

## 6. Belangrijkste aandachtspunt

De float switches en lekdetectie gaan rechtstreeks naar de Moxa. Ze zijn geen ESP32 GPIO-signalen. De ESP32 blijft verantwoordelijk voor lokale metingen, heartbeat en PWM/LED-besturing.

---

Einde as-built summary.
