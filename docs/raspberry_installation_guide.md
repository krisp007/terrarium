# Raspberry Installation Guide
## Terrarium Project v1.0

Auteur: Kristiaan Pinxten  
Platform: Raspberry Pi 5  
OS: Raspberry Pi OS Lite (64-bit)

---

# 1. Doel

Dit document beschrijft de volledige installatieprocedure van een nieuwe Raspberry Pi voor het Terrarium Project.

Na het volgen van deze procedure is het systeem opnieuw operationeel na:

- SD-kaart crash
- SSD crash
- Raspberry vervanging
- Migratie naar nieuwe hardware

---

# 2. Raspberry Pi OS Installatie

Installeer:

```text
Raspberry Pi OS Lite (64-bit)
```

Via:

```text
Raspberry Pi Imager
```

Tijdens installatie configureren:

```text
Hostname:
KrisPi

SSH:
Enabled

Username:
krisp

WiFi:
Niet nodig indien bekabeld
```

---

# 3. Eerste Login

```bash
ssh krisp@KrisPi.local
```

of

```bash
ssh krisp@<ip-adres>
```

---

# 4. Systeem Update

```bash
sudo apt update
sudo apt upgrade -y
sudo apt dist-upgrade -y
sudo reboot
```

---

# 5. Basis Tools

```bash
sudo apt install -y \
git \
curl \
wget \
nano \
vim \
htop \
tree \
unzip
```

---

# 6. Python Installatie

Controle:

```bash
python3 --version
```

Installeren indien nodig:

```bash
sudo apt install -y \
python3 \
python3-pip \
python3-venv
```

---

# 7. Project Directory

```bash
mkdir -p ~/terrarium-project
cd ~/terrarium-project
```

---

# 8. Git Repository Herstellen

Clone repository:

```bash
git clone <GITHUB_URL> .
```

Controle:

```bash
git status
```

---

# 9. Python Virtual Environment

Aanmaken:

```bash
python3 -m venv .venv
```

Activeren:

```bash
source .venv/bin/activate
```

Prompt wordt:

```text
(.venv) krisp@terrapi
```

---

# 10. Python Libraries

Installeren:

```bash
pip install --upgrade pip
```

Herstellen vanuit repository:

```bash
pip install -r requirements.txt
```

Controle:

```bash
pip list
```

---

# 11. Mosquitto MQTT

Installatie:

```bash
sudo apt install -y \
mosquitto \
mosquitto-clients
```

Activeren:

```bash
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

Controle:

```bash
sudo systemctl status mosquitto
```

---

# 12. MQTT Test

Terminal 1:

```bash
mosquitto_sub -t test
```

Terminal 2:

```bash
mosquitto_pub -t test -m hello
```

Resultaat:

```text
hello
```

---

# 13. MQTT Topics

## Sensor Data

```text
esp32/sensors
```

## Heartbeat

```text
esp32/status
```

## Ventilator Commands

```text
esp32/cmd/fans
```

## Lighting Commands

```text
esp32/cmd/lights
```

## Moxa Status

```text
moxa/status
```

## Moxa Commands

```text
moxa/cmd/output
```

---

# 14. Azure Libraries

Installeren:

```bash
pip install azure-iot-device
pip install azure-cosmos
```

Controle:

---

# 15. Terrarium rule-engine service

De Pi-regelengine draait als een systemd-service en verwerkt:

- `esp32/sensors`
- `esp32/status`
- `moxa/status`

Installeer de unit vanuit de projectmap:

```bash
sudo install -m 0644 services/terrarium-logic.service /etc/systemd/system/terrarium-logic.service
sudo systemctl daemon-reload
sudo systemctl enable --now terrarium-logic.service
```

Controleer daarna de verbinding met MQTT:

```bash
sudo systemctl status terrarium-logic.service
journalctl -u terrarium-logic.service -f
```

Verwachte logregel:

```text
Connected to MQTT broker 192.168.24.166:1883
```

De unit gebruikt `/home/krisp/terrarium-project/.venv/bin/python`. Pas
`ExecStart` in `services/terrarium-logic.service` aan wanneer de projectmap
of virtuele omgeving op een andere locatie staat.

```bash
pip list | grep azure
```

---

# 15. Raspberry Services

Map:

```bash
~/terrarium-project/services
```

Voorbeeld:

```text
event_worker.service
mqtt_receiver.service
climate_logic.service
```

---

# 16. Systemd Service

Voorbeeld:

```bash
sudo nano /etc/systemd/system/terrarium.service
```

Inhoud:

```ini
[Unit]
Description=Terrarium Service
After=network.target

[Service]
User=krisp
WorkingDirectory=/home/krisp/terrarium-project
ExecStart=/home/krisp/terrarium-project/.venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Activeren:

```bash
sudo systemctl daemon-reload

sudo systemctl enable terrarium

sudo systemctl start terrarium
```

Controle:

```bash
systemctl status terrarium
```

---

# 17. ESP32 Development Environment

Map:

```bash
mkdir -p ~/terrarium-project/esp32
```

Virtual environment:

```bash
python3 -m venv esp32env
```

Activeren:

```bash
source esp32env/bin/activate
```

Installeren:

```bash
pip install mpremote
```

Controle:

```bash
mpremote --help
```

---

# 18. ESP32 Detecteren

Controle poort:

```bash
ls /dev/ttyUSB*
```

of

```bash
ls /dev/ttyACM*
```

Typisch:

```text
/dev/ttyUSB0
```

---

# 19. ESP32 Backup

Bestandslijst:

```bash
mpremote connect /dev/ttyUSB0 fs ls
```

main.py ophalen:

```bash
mpremote connect /dev/ttyUSB0 fs cp :main.py .
```

---

# 20. ESP32 Upload

Nieuwe firmware:

```bash
mpremote connect /dev/ttyUSB0 fs cp main.py :main.py
```

Herstart:

```bash
mpremote connect /dev/ttyUSB0 reset
```

---

# 21. MQTT Monitoring

Sensoren:

```bash
mosquitto_sub -t esp32/sensors -v
```

Heartbeat:

```bash
mosquitto_sub -t esp32/status -v
```

Alle verkeer:

```bash
mosquitto_sub -t "#" -v
```

---

# 22. Git Workflow

Dagelijks:

```bash
git pull
```

Wijzigingen:

```bash
git add .
git commit -m "Beschrijving wijziging"
git push
```

Voorbeeld:

```bash
git commit -m "Added PCA9685 fan control"
```

---

# 23. Backup Strategie

## Dagelijks

Git push:

```bash
git push
```

## Wekelijks

Backup project:

```bash
tar -czf terrarium_backup.tar.gz \
~/terrarium-project
```

## Maandelijks

Volledige SD image maken.

Bewaren op:

```text
NAS
OneDrive
Externe SSD
```

---

# 24. Recovery Procedure

Bij SD-kaart crash:

1. Nieuwe SD installeren
2. Raspberry Pi OS installeren
3. SSH activeren
4. Git repository clonen
5. Virtual environment aanmaken
6. requirements.txt installeren
7. Mosquitto installeren
8. Services activeren
9. ESP32 testen
10. Moxa testen
11. MQTT verifiëren
12. Systeem online brengen

---

# 25. Acceptance Test

Controlepunten:

```text
[ ] Raspberry bereikbaar
[ ] Git repository geladen
[ ] Python omgeving actief
[ ] Mosquitto actief
[ ] MQTT berichten zichtbaar
[ ] ESP32 heartbeat zichtbaar
[ ] ESP32 sensordata zichtbaar
[ ] Moxa communicatie OK
[ ] Azure connectie OK
[ ] Services automatisch gestart
```

---
## Mosquitto Network Access

Maak bestand:

/etc/mosquitto/conf.d/terrarium.conf

Inhoud:

listener 1883
allow_anonymous true

Herstart:

sudo systemctl restart mosquitto

Controle:

ss -tln | grep 1883

Verwacht:

0.0.0.0:1883

# Einde Raspberry Installation Guide v1.0
``