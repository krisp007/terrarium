# Network Configuration v2.0

## 1. Doel

Dit document beschrijft de vaste netwerkconfiguratie van de terrarium-installatie, zodat de Raspberry Pi, ESP32 en Moxa op consistent IP-adres en MQTT-broker kunnen communiceren.

---

## 2. Statische netwerkkaart

### Raspberry Pi 5

- Hostname: `KrisPi`
- WiFi SSID: `IUVARE_LAN`
- Vast IP: `192.168.24.166`
- Gateway: `192.168.24.1`
- DNS: `192.168.24.1` en `8.8.8.8`

### ESP32

- IP: `192.168.24.141`
- MQTT-broker: `192.168.24.166`

### Moxa ioThinx 4510

- IP: `192.168.24.50`
- MQTT-broker: `192.168.24.166`

---

## 3. Debian / Raspberry OS configuratie

Controleer netwerkprofielen:

```bash
nmcli connection show
```

Selecteer het juiste profiel, meestal:

```text
netplan-wlan0-IUVARE_LAN
```

Stel het vaste IP-adres in:

```bash
sudo nmcli connection modify netplan-wlan0-IUVARE_LAN \
  ipv4.addresses 192.168.24.166/24 \
  ipv4.gateway 192.168.24.1 \
  ipv4.dns "192.168.24.1 8.8.8.8" \
  ipv4.method manual
```

Activeer de nieuwe configuratie:

```bash
sudo nmcli connection down netplan-wlan0-IUVARE_LAN
sudo nmcli connection up netplan-wlan0-IUVARE_LAN
```

Controleer:

```bash
hostname -I
```

Verwachte output:

```text
192.168.24.166
```

---

## 4. MQTT broker endpoint

Mosquitto draait op:

```text
192.168.24.166:1883
```

De ESP32 en Moxa communiceren met deze broker.

---

## 5. Mosquitto configuratie

Maak een lokale configuratie aan:

```bash
sudo nano /etc/mosquitto/conf.d/terrarium.conf
```

Inhoud:

```text
listener 1883
allow_anonymous true
```

Herstart Mosquitto:

```bash
sudo systemctl restart mosquitto
```

Controleer luisterpoort:

```bash
ss -tln | grep 1883
```

Verwacht:

```text
0.0.0.0:1883
```

---

## 6. Acceptatiechecks

```bash
ping 192.168.24.166
```

```bash
ping 192.168.24.50
```

```bash
ssh krisp@192.168.24.166
```

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

Alle checks moeten succesvol zijn.

---

## 7. Terug naar DHCP

Als je weer DHCP wilt gebruiken:

```bash
sudo nmcli connection modify netplan-wlan0-IUVARE_LAN \
  ipv4.method auto
sudo nmcli connection up netplan-wlan0-IUVARE_LAN
```

Gebruik deze optie alleen tijdelijk voor diagnose of migratie.
