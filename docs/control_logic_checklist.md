# Controle-logic checklist

Deze checklist is bedoeld als functionele control baseline voor het terrariumproject. Ze helpt bij het controleren van de Pi-logica, MQTT-communicatie, veiligheid, klimaatregels en actuatorcontrole.

---

## 1. Basisstatus

- [ ] ESP32 heartbeat is binnen timeout
- [ ] MQTT broker is bereikbaar op `192.168.24.166`
- [ ] `esp32/sensors` wordt ontvangen
- [ ] `esp32/status` wordt ontvangen
- [ ] `moxa/status` wordt ontvangen

---

## 2. Veiligheid

- [ ] lekkage detecteren op `moxa/status` (`di2`)
- [ ] mistmaker uit bij lek
- [ ] beregening uit bij lek
- [ ] alarm activeren bij lek
- [ ] reservoirniveau controleren
- [ ] RO-niveau controleren
- [ ] bij geen heartbeat: status = offline en alarm aan

---

## 3. Klimaatregels

- [ ] dag/nacht bepalen uit tijdschema
- [ ] seizoen bepalen (`rainy` / `dry`)
- [ ] temperatuur binnen min/max houden
- [ ] luchtvochtigheid binnen min/max houden
- [ ] mistmaker bij droge of te lage RH activeren
- [ ] irrigatie volgens schema of vochttekort
- [ ] verlichting aanpassen op zon op / zon onder

---

## 4. Ventilatie

- [ ] fan snelheid berekenen op basis van temperatuur
- [ ] `low` / `medium` / `high` levels consistent met config
- [ ] fan OFF bij te lage temp
- [ ] fan max bij hoge temp
- [ ] safety override heeft prioriteit

---

## 5. Actuators

- [ ] `esp32/cmd/fans` wordt verzonden
- [ ] `esp32/cmd/lights` wordt verzonden
- [ ] `moxa/cmd/output` wordt verzonden
- [ ] outputcommando’s volgen config
- [ ] geen actuator werkt als veiligheidsalarm actief

---

## 6. Config / UI

- [ ] settings template is geladen
- [ ] profielnaam is zichtbaar
- [ ] seizoen en tijdschema wijzigbaar
- [ ] min/max temp en RH wijzigbaar
- [ ] zon op / zon onder wijzigbaar
- [ ] wijzigingen opgeslagen in config/json of UI-state

---

## 7. Testcases

- [ ] normale dagcondities
- [ ] nachtcondities
- [ ] regenperiode
- [ ] droog seizoen
- [ ] temp te hoog
- [ ] temp te laag
- [ ] RH te laag
- [ ] RH te hoog
- [ ] MQTT offline
- [ ] lekdetectie
- [ ] reservoir laag

---

## 8. Acceptatie

- [ ] systeem staat stabiel
- [ ] geen loop / duplicate commands
- [ ] geen alarm bij normale waarden
- [ ] fail-safe werkt bij foutcondities

---

## 9. Notities

Deze checklist is bedoeld als basis voor de eerste implementatie van de Pi-control logic en kan later worden omgezet naar een UI-formulier of JSON-schema voor instelbare klimaatprofielen.
