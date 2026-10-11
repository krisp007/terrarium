# ESP32 GPIO / I2C Mapping

## I2C bus

GPIO21 = SDA
GPIO22 = SCL

Op deze bus staan:

- TCA9548A @ 0x70
- PCA9685 @ 0x40
- DFR0971 dimming board

---

## DS18B20

GPIO4 = Aquarium Temperature

Bekabeling:

- VCC → 3.3V
- DATA → GPIO4
- GND → GND
- 1kΩ pull-up naar 3.3V

---

## Soil Sensors

GPIO32 = Soil Left
GPIO33 = Soil Right

---

## TCA9548A channels

Adres: 0x70

- CH0 = SHT30 Left
- CH1 = SHT30 Top
- CH2 = SHT30 Right

---

## PCA9685 fan map

Adres: 0x40

- CH0 = Ventilator 1
- CH1 = Ventilator 2
- CH2 = Ventilator 3
- CH3 = Ventilator 4
- CH4 = Ventilator 5
- CH5 = Ventilator 6

---

## DFR0971 dimming board

- VOUT0 = LED 1 dim
- VOUT1 = LED 2 dim

> De float switches en de lekdetectie worden niet rechtstreeks op de ESP32 GPIO's aangesloten. Deze zijn beveiligingssignalen en gaan direct naar de Moxa digital inputs.
