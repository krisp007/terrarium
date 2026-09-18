# Controle-logic checklist

Deze checklist is bedoeld als functionele control baseline voor het terrariumproject. Ze helpt bij het controleren van de Pi-logica, MQTT-communicatie, veiligheid, klimaatregels en actuatorcontrole.

---

## 1. Basisstatus

- [x] ESP32 heartbeat is binnen timeout
- [x] MQTT broker is bereikbaar op `192.168.24.166`
- [x] `esp32/sensors` wordt ontvangen
- [x] `esp32/status` wordt ontvangen
- [ ] `moxa/status` wordt ontvangen
- [x] Pi-regelengine draait als systemd-service
- [x] service start automatisch bij boot

---

## 2. Veiligheid

- [x] lekkage detecteren op `moxa/status` (`di2`) in de regelengine
- [x] mistmaker uit bij lek
- [x] beregening uit bij lek
- [x] alarm activeren bij lek
- [x] reservoirniveau blokkeert de bijbehorende output
- [ ] RO-niveau controleren
- [x] bij geen heartbeat: status = offline en alarm aan
- [x] Pi-start controleert eerst alarmen en gebruikt een veilige actuatorstatus

---

## 3. Klimaatregels

- [x] dag/nacht bepalen uit tijdschema
- [x] seizoen bepaalt de lichtsterkte (`rainy` / `dry`)
- [ ] temperatuur binnen min/max houden
- [ ] luchtvochtigheid binnen min/max houden
- [x] mistmaker bij droge of te lage RH activeren
- [x] irrigatie bij vochttekort activeren
- [x] willekeurige regenbui tijdens `rainy` met configureerbare duur en cooldown
- [x] verlichting aanpassen op zon op / zon onder
- [x] verlichting heeft een 20-minuten dawn/dusk ramp
- [x] na Pi-restart lichtregeling start op basis van de actuele kloktijd

---

## 4. Ventilatie

- [x] fan snelheid berekenen op basis van temperatuur
- [x] `low` / `medium` / `high` levels volgen `fan_control` uit de settings template
- [x] fanwaarden kunnen via `update_settings()` worden aangepast voor latere UI-integratie
- [x] fan OFF bij te lage temp
- [x] fan max bij hoge temp
- [x] minimum airflow tegen schimmel: fan 1 en fan 6 afwisselend op 25%
- [x] safety override heeft prioriteit
- [x] warmtelamp `DO06` aan bij temperatuur onder `temperature_too_low_c`
- [x] warmtelamp uit bij normale of te hoge temperatuur
- [x] warmtelamp uit bij lek- of veiligheidsalarm
- [x] na Pi-restart ventilatie start met actuele regeling en minimum airflow

---

## 5. Actuators

- [x] `esp32/cmd/fans` wordt verzonden
- [x] `esp32/cmd/lights` wordt verzonden door de Pi-regelengine
- [x] `moxa/cmd/output` wordt verzonden
- [x] Moxa DO-commando's gebruiken `ioThinx_4510/write/DO@DO-xx/doStatus`
- [x] outputwaarden gebruiken numerieke payloads (`{"value":1}` / `{"value":0}`)
- [x] DO00-DO03 en DO05 live geactiveerd en bevestigd met `value:1`
- [x] geen mistmaker/beregening bij lek of laag reservoir

---

## 6. Config / UI

- [x] settings template is aanwezig
- [ ] profielnaam is zichtbaar
- [ ] seizoen en tijdschema wijzigbaar
- [ ] min/max temp en RH wijzigbaar
- [ ] zon op / zon onder wijzigbaar
- [ ] wijzigingen opgeslagen in config/json of UI-state

---

## 7. Testcases

- [x] normale dagcondities in unit tests
- [x] nachtcondities in unit tests
- [x] regenperiode in unit tests
- [x] droog seizoen in unit tests
- [x] temp te hoog in unit tests
- [x] temp te laag in unit tests
- [x] warmtelamp bij te lage temperatuur in unit tests
- [x] RH te laag in unit tests
- [x] lekdetectie in unit tests
- [x] reservoir laag in unit tests
- [x] regenbui alleen in regenseizoen in unit tests
- [x] regenbui geblokkeerd door lek of leeg reservoir in unit tests
- [x] Pi-restart recovery in unit tests
- [ ] MQTT offline live testen
- [ ] RO-niveau live testen
- [ ] Moxa DI-inputs live testen

---

## 8. Acceptatie

- [ ] systeem staat stabiel
- [ ] geen loop / duplicate commands
- [ ] geen alarm bij normale waarden
- [ ] fail-safe werkt bij foutcondities

---

## 9. Live installatiechecks

- [x] Moxa bereikbaar op `192.168.24.50`
- [x] MQTT broker bereikbaar op `192.168.24.166:1883`
- [x] Moxa DO-feedback zichtbaar via `ioThinx_4510/read/#`
- [x] Pi-service actief als `terrarium-logic.service`
- [x] service enabled voor automatisch starten
- [x] status-UI beschikbaar op `http://192.168.24.166:8080`
- [x] status-API toont Moxa DO-feedback
- [x] waarde- en commandogeschiedenis wordt lokaal bewaard
- [x] historie-API beschikbaar op `http://192.168.24.166:8080/api/history`
- [x] ESP32 echte sensorwaarden ontvangen
- [ ] ESP32 echte sensorwaarden langdurig monitoren
- [ ] Moxa DI-topics voor DI0-DI4 beschikbaar maken
- [ ] fysieke mistmakerwerking onder toezicht testen
- [ ] fysieke beregening onder toezicht testen

---

## 10. Notities

Deze checklist onderscheidt unit-testvalidatie van live hardwarevalidatie. Een
afgevinkte unit-test bewijst de regel, maar niet dat de fysieke actuator of
Moxa-ingang correct bedraad is. Schakel water- en mistapparatuur bij live tests
alleen onder toezicht in.
- [x] reservoir laag in unit tests
- [x] regenbui alleen in regenseizoen in unit tests
- [x] regenbui geblokkeerd door lek of leeg reservoir in unit tests
- [ ] MQTT offline live testen
- [ ] RO-niveau live testen
- [ ] Moxa DI-inputs live testen

---

## 8. Acceptatie

- [ ] systeem staat stabiel
- [ ] geen loop / duplicate commands
- [ ] geen alarm bij normale waarden
- [ ] fail-safe werkt bij foutcondities

---

## 9. Live installatiechecks

- [x] Moxa bereikbaar op `192.168.24.50`
- [x] MQTT broker bereikbaar op `192.168.24.166:1883`
- [x] Moxa DO-feedback zichtbaar via `ioThinx_4510/read/#`
- [x] Pi-service actief als `terrarium-logic.service`
- [x] service enabled voor automatisch starten
- [x] status-UI beschikbaar op `http://192.168.24.166:8080`
- [x] status-API toont Moxa DO-feedback
- [x] ESP32 echte sensorwaarden ontvangen
- [ ] ESP32 echte sensorwaarden langdurig monitoren
- [ ] Moxa DI-topics voor DI0-DI4 beschikbaar maken
- [ ] fysieke mistmakerwerking onder toezicht testen
- [ ] fysieke beregening onder toezicht testen

---

## 10. Notities

Deze checklist onderscheidt unit-testvalidatie van live hardwarevalidatie. Een
afgevinkte unit-test bewijst de regel, maar niet dat de fysieke actuator of
Moxa-ingang correct bedraad is. Schakel water- en mistapparatuur bij live tests
alleen onder toezicht in.
