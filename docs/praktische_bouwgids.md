# Praktische bouwgids terrarium v1.0

## 1. Doel

Deze gids is de praktische opvolger van de technische ontwerpdocumentatie. Ze is bedoeld om het systeem in de echte praktijk te bouwen, aan te sluiten, op te starten en te testen zonder dat je elke keer terug hoeft te kijken naar meerdere losse documentatiebestanden.

De focus ligt op:

- componenten en bekabeling
- opstartvolgorde
- MQTT en netwerkcontrole
- eerste testcyclus
- veilig werken tijdens de bouwfase

---

## 2. Componentenlijst

### Centrale controller

- Raspberry Pi 5
- microSD of SSD-opslag
- USB-C voeding
- Ethernet of WiFi

### Sensor-/actuator node

- ESP32 DevKit
- SHT30 sensoren (3x)
- DS18B20 aquariumtemperatuur sensor
- capacitive soil moisture sensors (2x)
- PCA9685 PWM board
- 6 ventilatoren 12V DC
- XY-MOS modules

### Veiligheidscontroller

- Moxa ioThinx 4510
- digitale ingangen voor reservoirniveau en lekdetectie
- digitale uitgangen voor pompen, mistmaker en verlichting

### Extra

- 12V voeding voor ventilatoren
- 230V voeding voor lampen / verwarming / pompen
- jumperdraden, breadboard of vaste bedrading
- gemeenschappelijke GND bij de 12V-sectie

---

## 3. Hardwareopstelling

### 3.1 Raspberry Pi

Plaats de Raspberry Pi centraal in de kast of op een veilige, goed geventileerde plek.

Controles:

- Pi heeft netwerkverbinding
- SSH werkt
- Mosquitto is geïnstalleerd
- de repo staat lokaal in `~/terrarium-project`

### 3.2 ESP32

De ESP32 wordt het lokale meet- en besturingscentrum. Deze node is het dichtst bij de sensoren en de ventilatoren.

Gebruik:

- GPIO21 = SDA
- GPIO22 = SCL
- GPIO4 = DS18B20
- GPIO32 = Soil Left
- GPIO33 = Soil Right
- GPIO34 = Mistmaker Reservoir
- GPIO35 = Irrigation Reservoir
- GPIO27 = Leak Sensor

### 3.3 PCA9685 en ventilatoren

- PCA9685 adres `0x40`
- CH0 t/m CH5 = 6 ventilatoren
- PWM-signalen naar XY-MOS modules
- 12V voeding naar ventilatoren en modules
- gemeenschappelijke GND met ESP32/PCA9685

### 3.4 Moxa

De Moxa moet als veiligheidslaag worden gezien. De kritische functies mogen niet alleen op software-logica afhangen.

Gebruikelijke ingangen:

- DI0 = Mistmaker niveau
- DI1 = Beregening niveau
- DI2 = Lekdetectie

Gebruikelijke uitgangen:

- DO0 = Warmtelamp links
- DO1 = Warmtelamp rechts
- DO2 = Mistmaker
- DO3 = Beregening
- DO4 = Vulpomp mistmaker
- DO5 = Vulpomp beregening
- DO6 = Watervalpomp

---

## 4. Bekabelingschecklist

Controleer stap voor stap:

- [ ] voeding voor Raspberry Pi correct en stabiel
- [ ] ESP32 voedingsspanning correct
- [ ] GND van 3.3V- en 12V-secties goed gescheiden
- [ ] I²C-sensoren op GPIO21/GPIO22 aangesloten
- [ ] PCA9685 op I²C-bus aangesloten
- [ ] DS18B20 heeft pull-up en juiste pin
- [ ] bodemvochtsensoren hebben vaste aansluitingen
- [ ] float switches goed aangesloten op de juiste GPIO's
- [ ] leak sensor naar GPIO27
- [ ] Moxa ingangen voor niveau en lekdetectie correct aangesloten
- [ ] Moxa uitgangen gekoppeld aan pompen, mistmaker en verlichting
- [ ] 12V ventilatoren en XY-MOS modules aangesloten op gemeenschappelijke voeding

> Als één aansluitpunt niet klopt, werkt de volledige automatisering niet betrouwbaar.

---

## 5. Netwerk en MQTT opzet

### 5.1 Raspberry Pi

Gebruik vaste netwerkconfiguratie:

- IP: `192.168.24.166`
- Gateway: `192.168.24.1`
- WiFi SSID: `IUVARE_LAN`
- hostname: `KrisPi`

Check:

```bash
hostname -I
ping 192.168.24.166
```

### 5.2 MQTT

Broker op Raspberry Pi:

```text
192.168.24.166:1883
```

Test:

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

Als er geen berichten binnenkomen, controleer:

- Mosquitto service status
- firewall / lokale netwerk
- juiste MQTT topic
- ESP32 is online

---

## 6. Opstartvolgorde

Gebruik deze volgorde om problemen te voorkomen.

### Stap 1: Raspberry Pi opstarten

```bash
ssh krisp@192.168.24.166
```

Controleer:

```bash
sudo systemctl status mosquitto
```

### Stap 2: code en environment

```bash
cd ~/terrarium-project
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Stap 3: ESP32 voorbereiden

```bash
cd ~/terrarium-project
source esp32env/bin/activate
mpremote --help
```

### Stap 4: ESP32 firmware uploaden

```bash
mpremote connect /dev/ttyUSB0 fs cp main.py :main.py
mpremote connect /dev/ttyUSB0 reset
```

### Stap 5: testen

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

Je zou nu data moeten zien op:

- `esp32/status`
- `esp32/sensors`

---

## 7. MQTT topics en payloads

### ESP32 status

```json
{
  "device": "esp32_sensor_node",
  "status": "online",
  "ip": "192.168.24.141",
  "firmware": "1.0.0"
}
```

Topic:

```text
esp32/status
```

### ESP32 sensordata

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

Topic:

```text
esp32/sensors
```

### Moxa status

```text
moxa/status
```

### Moxa commando's

```text
moxa/cmd/output
```

---

## 8. Eerste testcyclus

Na de eerste opstart uitvoeren:

### 8.1 Controleer netwerk

```bash
ping 192.168.24.166
```

### 8.2 Controleer MQTT

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

### 8.3 Controleer ESP32 heartbeat

Je verwacht een bericht zoals:

```json
{"device":"esp32_sensor_node","status":"online"}
```

### 8.4 Controleer sensor payload

Je verwacht de temperatuur-, vocht- en bodemvochtswaarden.

### 8.5 Controleer Moxa-data

Controleer of de Moxa ingangen en alarmstatus correct binnenkomen op `moxa/status`.

### 8.6 Controleer ventilatoren

Zet de ventilatoren tijdelijk handmatig aan in testmodus.

Controleer:

- PWM werkt
- 12V voeding aanwezig
- fan draait correct
- geen kortsluiting / te hoge stroom

---

## 9. Veilige bedrijfsregels

De volgende regels moeten altijd gelden:

- als lekdetectie actief is: alle pompen en mistmaker stoppen
- als reservoirniveau laag is: stop vulpomp of irrigatie
- als ESP32 heartbeat wegvalt: alarmstatus activeren
- geen hardwarewijziging doen zonder documentatie bij te werken

---

## 10. Veelvoorkomende problemen

### ESP32 maakt geen verbinding met WiFi

Controleer:

- SSID en wachtwoord
- router bereik
- netwerknaam exact overeen met configuratie

### Geen MQTT-berichten

Controleer:

- broker draait
- telnet/poort 1883 open
- ESP32 reset en logs lezen
- mqtt config correct

### Sensor geeft onlogische waarden

Controleer:

- I²C aansluitingen
- TCA9548A kanaalinstelling
- GND en spanningsniveau
- sensor status in REPL

### Ventilator doet niets

Controleer:

- PCA9685 adres en PWM-output
- 12V voeding
- XY-MOS module
- GND en signaal doorverbinding

---

## 11. Bouwchecklist voor eerste opstart

Voer deze lijst uit voordat je het systeem in gebruik neemt:

- [ ] Raspberry Pi reachable
- [ ] Mosquitto actief
- [ ] ESP32 heartbeat zichtbaar
- [ ] sensor payload zichtbaar
- [ ] Moxa status zichtbaar
- [ ] ventilatoren draaien
- [ ] mistmaker en pompen veilig getest
- [ ] lekkagealarm getest
- [ ] reservoir alarm getest
- [ ] systeemdocumentatie bijgewerkt

---

## 12. Praktische conclusie

Dit systeem werkt alleen betrouwbaar als de volgende 3 dingen correct zijn:

1. hardware bekabeling klopt
2. netwerk en MQTT correct geconfigureerd zijn
3. de status- en alarmstromen zichtbaar zijn in de live broker

Wanneer deze drie punten op orde zijn, is het terrarium systeem klaar voor eerste automatische klimaatcontrole en veilige operationele runs.

---

Einde praktische bouwgids.
