# Terrarium Project

Project status: v2.1 hardware baseline

Dit project beschrijft een geautomatiseerd terrarium / paludarium met:

- Raspberry Pi 5 als centrale controller
- ESP32 als lokale sensornode en actuatorcontroller
- Moxa ioThinx 4510 als veiligheidscontroller
- MQTT als lokale communicatie- en controlebus
- Azure als mogelijke cloud- of logginglaag

## Doel

Het doel is een stabiel en lokaal autonoom systeem dat een Costa Rica-achtige terrariumomgeving nabootst, met een natuurlijke klimaatsimulatie van:

- dag en nacht cyclus
- regenseizoen en droog seizoen
- hoge luchtvochtigheid in de regenseizoensfases
- warmere, drogere periodes tijdens daglicht en droge fase
- temperatuur en luchtvochtigheid bewaakt
- aquariumtemperatuur volgt
- bodemvocht controleert
- ventilatie en verlichting bestuurt
- waterniveau en lekkage detecteert
- alarms en veilige fallback-gedragingen toepast

## Systeemoverzicht

- Raspberry Pi 5
  - Mosquitto broker
  - automations / climate logic
  - historisch loggen en monitoring
  - service management

- ESP32
  - SHT30 sensoren
  - DS18B20 aquariumtemperatuur
  - bodemvocht sensoren
  - heartbeat status
  - PWM-ventilatoren / output control

- Moxa ioThinx 4510
  - veiligheidslogica
  - digitale ingangen voor reservoirs en lekdetectie
  - digitale uitgangen voor verlichting / waterstroom / pompen

## Belangrijkste maps

- `docs/`: system design en installatie documentatie
- `esp32/`: ESP32 firmware en helpers
- `hardware/`: hardware- en bekabelingsdocumentatie
- `moxa/`: Moxa configuratie en I/O mapping
- `raspberry/`: Raspberry-specifieke scripts en services
- `services/`: systemd services

## Documentatie-index

- [docs/architectuurdiagram.md](docs/architectuurdiagram.md) — systeemarchitectuur en dataflow
- [docs/as_built_summary.md](docs/as_built_summary.md) — compacte as-built overzicht van de huidige bouw
- [docs/network_configuration.md](docs/network_configuration.md) — Pi, WiFi en MQTT netwerkinstellingen
- [docs/gpio_mapping.md](docs/gpio_mapping.md) — ESP32 GPIO- en bus mapping
- [docs/hardware_wiring.md](docs/hardware_wiring.md) — bekabelingsschema en hardwareopzet
- [docs/hardware_bouwplan_per_kabel_en_pin.md](docs/hardware_bouwplan_per_kabel_en_pin.md) — praktische bouwgids per kabel en pin
- [docs/control_logic_checklist.md](docs/control_logic_checklist.md) — checklist voor Pi-control logic en klimaatregels
- [docs/mqtt_topics.md](docs/mqtt_topics.md) — MQTT contract en payloads
- [docs/praktische_bouwgids.md](docs/praktische_bouwgids.md) — praktijkgerichte bouw- en testgids
- [docs/raspberry_installation_guide.md](docs/raspberry_installation_guide.md) — Raspberry installatie en service setup
- [docs/esp32_installation_guide.md](docs/esp32_installation_guide.md) — ESP32 installatie en upload
- [docs/backup_and_recovery.md](docs/backup_and_recovery.md) — backup en herstelproces
- [docs/moxa_io_map.md](docs/moxa_io_map.md) — Moxa ingangs-/uitgangsmap

## Snelstart

1. Raspberry Pi opzetten volgens [docs/raspberry_installation_guide.md](docs/raspberry_installation_guide.md)
2. Netwerk en MQTT-opstelling controleren via [docs/network_configuration.md](docs/network_configuration.md)
3. ESP32 installeren volgens [docs/esp32_installation_guide.md](docs/esp32_installation_guide.md)
4. Hardware controleren via [docs/gpio_mapping.md](docs/gpio_mapping.md) en [docs/hardware_wiring.md](docs/hardware_wiring.md)
5. MQTT verkeer controleren met:

```bash
mosquitto_sub -h 192.168.24.166 -t "#" -v
```

## Baseline-opmerking

Deze documentatie is een werkdocument voor de eerste bouw- en testfase. Houd de GPIO-toewijzing, MQTT-topics, Moxa-IO mapping en netwerkconfiguratie altijd synchroon met de werkelijke hardware.

## Settings template

Het project bevat een default configuratiebestand voor de klimaatsimulatie en latere UI-editing:

- [terrarium_settings_template.json](terrarium_settings_template.json)

Deze template bevat:
- dag-/nachtcyclus
- min/max temperatuur en luchtvochtigheid
- zon op / zon onder
- seizoeninstellingen (droog / nat)
- veiligheidsregels en actuators
- waarden die later door een UI kunnen worden aangepast zonder de logica te wijzigen
