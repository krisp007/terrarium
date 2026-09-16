# Network Configuration

## Raspberry Pi 5

### Hostname

```text
KrisPi
```

### WiFi SSID

```text
IUVARE_LAN
```

### Vast IP-adres

```text
192.168.24.166
```

### Gateway

```text
192.168.24.1
```

### DNS

```text
192.168.24.1
8.8.8.8
```

---

# Configuratie op Debian 13 (Trixie)

Controleer profielnaam:

```bash
nmcli connection show
```

Verwacht:

```text
netplan-wlan0-IUVARE_LAN
```

Stel vast IP in:

```bash
sudo nmcli connection modify netplan-wlan0-IUVARE_LAN \
ipv4.addresses 192.168.24.166/24 \
ipv4.gateway 192.168.24.1 \
ipv4.dns "192.168.24.1 8.8.8.8" \
ipv4.method manual
```

Activeer configuratie:

```bash
sudo nmcli connection down netplan-wlan0-IUVARE_LAN

sudo nmcli connection up netplan-wlan0-IUVARE_LAN
```

Controle:

```bash
hostname -I
```

Verwacht:

```text
192.168.24.166
```

---

# Terug naar DHCP

```bash
sudo nmcli connection modify netplan-wlan0-IUVARE_LAN \
ipv4.method auto

sudo nmcli connection up netplan-wlan0-IUVARE_LAN
```

---

# Gebruikt door

## Mosquitto

```text
192.168.24.166:1883
```

## ESP32

MQTT Broker:

```text
192.168.24.166
```

## Moxa ioThinx 4510

MQTT Broker:

```text
192.168.24.166
```

---

# Acceptance Test

```bash
ping 192.168.24.166
```

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

```bash
ssh krisp@192.168.24.166
```

Alle testen moeten succesvol zijn.