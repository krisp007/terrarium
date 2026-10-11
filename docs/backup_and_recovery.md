# Backup and Recovery

## Doel

Dit document beschrijft hoe de terrarium-installatie veilig kan worden geback-upt en hoe een crash van de Raspberry Pi of de SD-kaart kan worden hersteld zonder het volledige systeem opnieuw op te bouwen.

---

## 1. Repository backup

Het project staat in Git. De belangrijkste broncode en documentatie moeten regelmatig worden gepusht.

```bash
cd ~/terrarium-project
git status
git add .
git commit -m "Update terrarium configuration"
git push
```

### Richtlijn

- elke wijziging aan code of docs committen
- elke werkdag pushen naar de remote
- alle kritische wijzigingen vooraf testen

---

## 2. Volledige projectbackup

Naast Git is een volledige projectarchive handig voor herstel.

```bash
cd ~
tar -czf terrarium_backup.tar.gz ~/terrarium-project
```

Bewaar de backup op:

- NAS
- externe SSD
- OneDrive / cloud backup

---

## 3. ESP32 backup

De ESP32-firmware is lokaal op het apparaat. Maak een backup van de belangrijkste bestanden voordat deze worden gewijzigd.

```bash
source ~/terrarium-project/esp32env/bin/activate
mpremote connect /dev/ttyUSB0 fs ls
mpremote connect /dev/ttyUSB0 fs cp :main.py ./main_backup.py
```

Als extra bestanden zijn aangepast, ook die apart backuppen.

---

## 4. Raspberry Pi herstel na crash

Bij een SD-kaart- of Raspberry-crash:

1. Raspberry Pi OS installeren
2. SSH activeren
3. Git repo clonen
4. Python virtual environment aanmaken
5. dependencies installeren
6. Mosquitto installeren en activeren
7. netwerkconfiguratie herstellen
8. ESP32 firmware uploaden
9. MQTT testen
10. services activeren
11. systeem online brengen

### Basisstappen

```bash
mkdir -p ~/terrarium-project
cd ~/terrarium-project
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Mosquitto herstel

```bash
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
sudo systemctl status mosquitto
```

Controleer verkeer:

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

---

## 6. Recovery checklist

Na herstel moet het volgende gecontroleerd worden:

- [ ] Raspberry Pi reachable via SSH
- [ ] Git repository aanwezig
- [ ] Python omgeving actief
- [ ] Mosquitto actief
- [ ] ESP32 heartbeat zichtbaar
- [ ] ESP32 sensor data zichtbaar
- [ ] Moxa communicatie OK
- [ ] MQTT topics correct
- [ ] services gestart

---

## 7. Preventie

- houd Git-updates up-to-date
- maak regelmatig backup van de ESP32-firmware
- documenteer alle hardwarewijzigingen
- versieer configuratiebestanden bij wijzigingen aan GPIO- of netwerkconfiguratie

Deze maatregelen minimaliseren downtime bij een hardware- of softwarecrash.