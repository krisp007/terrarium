# Hardware bouwplan per kabel en pin

## 1. Doel

Dit document is het praktische bouwplan voor de echte aansluiting van alle componenten. Het beschrijft per kabel, pin en signaal wat er wordt aangesloten, waar de GND ligt, welke voeding erbij hoort en welke functie het heeft.

Gebruik dit document tijdens het fysieke bouwen, testen en debuggen.

---

## 2. Basisregels

- houd 3.3V-sensoren en 12V-voedingssecties gescheiden
- alle GND-punten die logisch samen horen, moeten zorgvuldig verbonden zijn
- gebruik duidelijke labels op alle kabels
- zet de ESP32, PCA9685 en Moxa in dezelfde fysieke logische stroomgroep als je wil debuggen
- maak geen “doorgestoken” kabels zonder label of overzicht

---

## 3. Raspberry Pi 5

### 3.1 Netwerk

- WiFi SSID: `IUVARE_LAN`
- hostname: `KrisPi`
- IP: `192.168.24.166`
- gateway: `192.168.24.1`
- DNS: `192.168.24.1` en `8.8.8.8`

### 3.2 MQTT

- broker IP: `192.168.24.166`
- broker port: `1883`

### 3.3 Gebruik

- MQTT broker
- automations
- logging
- alarms
- monitoring

---

## 4. ESP32 pinplan

### 4.1 I²C bus

| Functie | ESP32 pin | Doel |
|---------|-----------|------|
| SDA | GPIO21 | I²C data voor TCA9548A / SHT30 / PCA9685 |
| SCL | GPIO22 | I²C clock |

### 4.2 Temperatuur en vocht

| Functie | ESP32 pin | Doel |
|---------|-----------|------|
| DS18B20 DATA | GPIO4 | Aquariumtemperatuur |
| Soil Left | GPIO32 | Bodemvocht links |
| Soil Right | GPIO33 | Bodemvocht rechts |

### 4.3 Spanningsregels

- DS18B20: 3.3V + data + GND + 1k pull-up
- capacitive soil sensors: vaste analoge meting op GPIO32/GPIO33
- float switches en leak detection behoren niet op de ESP32 GPIO’s, maar op de Moxa digitale ingangen
- de ESP32 blijft verantwoordelijk voor sensoren, heartbeat en PWM-besturing

---

## 5. TCA9548A en SHT30 busplan

### 5.1 Multiplexer

- adres: `0x70`

### 5.2 Kanaalconfiguratie

| Kanaal | Sensor | Doel |
|--------|--------|------|
| CH0 | SHT30 Top | temperatuur + luchtvochtigheid boven |
| CH1 | SHT30 Left | temperatuur + luchtvochtigheid links |
| CH2 | SHT30 Right | temperatuur + luchtvochtigheid rechts |

### 5.3 Bekabeling per sensor

- VCC → 3.3V
- GND → GND
- SDA → I²C bus SDA
- SCL → I²C bus SCL

Bij de TCA9548A:

- de multiplexer zelf zit op de I²C-bus van de ESP32
- elk kanaal wordt geselecteerd via de multiplexer
- elke SHT30 wordt vervolgens op dat kanaal uitgelezen

---

## 6. PCA9685 en ventilatoren

### 6.1 PCA9685

| Functie | Pin / adres | Doel |
|---------|-------------|------|
| I²C adres | `0x40` | PWM-controller |
| SDA | GPIO21 | I²C data |
| SCL | GPIO22 | I²C clock |
| VCC | 3.3V of 5V afhankelijk van module | voeding controller |
| GND | GND | common ground |

### 6.2 Ventilatorkanalen

| Kanaal | Ventilator | Doel |
|--------|------------|------|
| CH0 | Left Front | luchtstroom front links |
| CH1 | Left Back | luchtstroom back links |
| CH2 | Mid Front | luchtstroom front midden |
| CH3 | Mid Back | luchtstroom back midden |
| CH4 | Right Front | luchtstroom front rechts |
| CH5 | Right Back | luchtstroom back rechts |

### 6.3 Voeding

- 12V DC naar ventilatoren
- 12V naar XY-MOS modules
- GND van 12V-voeding gedeeld met PCA9685 en ESP32 als standaardlogica
- signaal vanuit PCA9685 naar XY-MOS module
- PWMsignaal is geen 12V-signaal, maar een besturingssignaal voor de module

---

## 7. XY-MOS module wiring

| Deel | Verbinding |
|------|------------|
| 12V voeding | naar +12V ingang van XY-MOS |
| GND | naar GND van 12V-voeding |
| PWM input | van PCA9685 kanaal |
| uitgang | naar ventilator 12V-aansluiting |

Controleer:

- PWM signaal correct verbonden
- XY-MOS niet per ongeluk te hoog belast
- ventilatorpolen niet verkeerd aangesloten

---

## 8. Moxa ioThinx 4510 pin / I/O plan

### 8.1 Digitale ingangen

| Input | Functie | Doel |
|-------|---------|------|
| DI0 | Mistmaker reservoir | niveau controle |
| DI1 | Beregening reservoir | niveau controle |
| DI2 | Lekdetectie | alarm op waterlek |

> Opmerking: deze signalen worden rechtstreeks op de Moxa aangesloten. De ESP32 heeft hier geen directe GPIO-positie voor in de sensorkaart.

### 8.2 Digitale uitgangen

| Output | Functie | Doel |
|--------|---------|------|
| DO0 | LED Links voeding | lichtschakeling |
| DO1 | LED Mid1 voeding | lichtschakeling |
| DO2 | LED Mid2 voeding | lichtschakeling |
| DO3 | LED Rechts voeding | lichtschakeling |
| DO4 | Beregening | irrigatie systeem |
| DO5 | Mistmaker | waterpijpleiding |
| DO6 | Warmtelamp | veiligheid / warmte |
| DO7 | Watervalpomp | waterstroom / bijzonder circuit |
| DO8 | Reserve | vrije output |
| DO9 | Pomp 1 mistmaker | toekomstige of extra pompfunctie |
| DO10 | Pomp 2 beregening | toekomstige of extra pompfunctie |
| DO11 | Pomp 3 | reserve |
| DO12 | Pomp 4 | reserve |
| DO13 | Reserve | vrije output |
| DO14 | Reserve | vrije output |
| DO15 | WaterValve RO | RO-waterafsluiting of RO-voeding |

### 8.3 Moxa voeding

- vaste 24V of adaptieve voeding volgens Moxa specificatie
- GND correct verbinden
- alarm- en statuslijnen goed labelen

---

## 9. Verlichting en power plan

### 9.1 LED-verlichting

- 4x Mars Hydro FC-E1500
- 150W per licht
- elk licht via eigen controle of via groepcontrole

### 9.2 Powerplan

- verwarmings- en verlichtingscircuits gescheiden houden van sensor- en logic circuits
- relays / Moxa outputs moeten op juiste belastbaarheid zijn geselecteerd
- gebruik zekering of beveiliging op de 230V- of 12V-zijde waar nodig

---

## 10. Kabel labeling standaard

Gebruik op elke kabel:

- functie
- bron
- bestemming
- spanning
- labelnummer

Voorbeeld:

- `ESP32-GPIO21-SDA-TCA9548A`
- `PCA9685-CH0-FAN-LF`
- `MOXA-DI2-LEAK-SENSOR`
- `12V-FAN-LF-POWER`

---

## 11. Bouwvolgorde

### Fase 1: power en basis

- Raspberry Pi voeding
- ESP32 voeding
- Moxa voeding
- 12V ventilatoren voeding
- 230V-verlichting / pompen veilig op aparte circuits

### Fase 2: signal wiring

- GPIO21/GPIO22 voor I²C
- DS18B20 + pull-up
- soil sensor inputs
- float switches and leak sensor
- Moxa DI/DO lines

### Fase 3: test op enkelvoudige onderdelen

- I²C scan
- sensor waarden checken
- PWM fan test
- Moxa input test
- MQTT test

### Fase 4: integratie

- alle onderdelen in één systeem
- sensorpayload checken
- heartbeat checken
- alarmstatus checken
- first run met beperkte belasting

---

## 12. Eerste werkende testlijst

Vervul alles in deze volgorde:

- [ ] Raspberry Pi online
- [ ] ESP32 online
- [ ] I²C scan werkt
- [ ] SHT30 sensoren gelezen
- [ ] DS18B20 waarde zichtbaar
- [ ] soil sensors meten
- [ ] float switch statuses OK
- [ ] leak detection OK
- [ ] PCA9685 PWM werkt
- [ ] ventilatoren draaien
- [ ] Moxa inputs lezen
- [ ] Moxa outputs schakelen
- [ ] MQTT topics zichtbaar
- [ ] heartbeat werkt

---

## 13. Praktische conclusie

Het bouwen van dit terrarium werkt alleen betrouwbaar als de bewustere fysieke structuur klopt:

- juiste pin mapping
- juiste voeding
- juiste GND en signaalroutes
- juiste labels op kabels
- volledige testfase per onderdeel

Als alle pinnen en kabels logisch aansluiten en alle stromen getest zijn, dan is de kans op onverwachte problemen veel kleiner.

---

Einde hardware bouwplan per kabel en pin.
