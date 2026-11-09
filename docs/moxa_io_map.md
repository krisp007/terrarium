# Moxa ioThinx 4510 I/O Map

## Doel

De Moxa is de veiligheids- en schakelcontroller. Zij bewaakt de kritische status van reservoirniveaus, lekdetectie, RO-niveau en de voedingen van verlichting, warmte en irrigatie.

Netwerkadres: `192.168.24.50`
MQTT-broker: `192.168.24.166:1883`

---

## 1. Digitale ingangen

| Input | Functie | Beschrijving |
|-------|---------|-------------|
| DI0 | Vlotter RO-vat | Actief geeft toestemming om het RO-ventiel te openen |
| DI1 | Aquarium bijvulvlotter | Actief vraagt bijvullen van het aquarium aan |
| DI2 | Lekdetectie | Geeft alarm bij waterlek |
| DI3 | Vlotter min RO | RO-reservoir minimaal niveau |
| DI4 | Vlotter max RO | RO-reservoir maximaal niveau |

---

## 2. Digitale uitgangen

| Output | Functie | Beschrijving |
|--------|---------|-------------|
| DO0 | LED Links voeding | Voeding voor LED links |
| DO1 | LED Mid1 voeding | Voeding voor LED middelste 1 |
| DO2 | LED Mid2 voeding | Voeding voor LED middelste 2 |
| DO3 | LED Rechts voeding | Voeding voor LED rechts |
| DO4 | Beregening | Activering irrigatie |
| DO5 | Mistmaker | Activering mistmaker |
| DO6 | Warmtelamp | Verlichting / warmte |
| DO7 | Reserve | Vrije output |
| DO8 | Reserve | Vrije output / toekomstige functie |
| DO9 | Pomp 1 mistmaker | Toekomstige of extra pompfunctie |
| DO10 | Watervalpomp | Voorlopig uitgeschakeld tot de beplanting geworteld is |
| DO11 | Orchideeën druppelaar | JSON-cyclus: elke 90 minuten 45 seconden aan |
| DO12 | Aquarium bijvulpomp | Bekrachtigd = aquarium bijvullen |
| DO13 | Reserve | Vrije output |
| DO14 | Reserve | Vrije output |
| DO15 | WaterValve RO | Bekrachtigd = RO-ventiel open |

---

## 3. Veiligheidsregels

### Lek gedetecteerd

Acties:

- Mistmaker OFF
- Beregening OFF
- Vulpomp mistmaker OFF
- Vulpomp beregening OFF
- alarm genereren

### Reservoir laag

Acties:

- pomp stoppen
- alarm genereren

### RO-vat en RO-ventiel

- DI0 actief en geen lekalarm: DO15 `ON` (ventiel bekrachtigd/open)
- DI0 inactief of onbekend: DO15 `OFF` (ventiel spanningsloos/gesloten)
- DI2 lekalarm: DO15 `OFF`, ongeacht DI0

### Aquarium bijvullen

- DI1 actief en geen lekalarm: DO12 `ON`
- DI1 inactief of onbekend: DO12 `OFF`
- DI2 lekalarm: DO12 `OFF`, ongeacht DI1

### RO-niveau buiten bereik

Acties:

- RO-verwerking stoppen of blokkeren
- alarm genereren

### Geen heartbeat ESP32

Acties:

- veiligheidsstatus controleren
- alarm genereren na timeout

---

## 4. MQTT communicatie

De Moxa rapporteert status over:

```text
moxa/status
```

Commando's worden verzonden naar:

```text
moxa/cmd/output
```

De Pi-runtime vertaalt een logisch commando zoals `{"do5":"ON"}` daarnaast
naar het ioThinx MQTT-write-topic:

```text
ioThinx_4510/write/DO@DO-05/doStatus
```

met payload:

```json
{"value": 1}
```

De Moxa-feedback komt binnen via bijvoorbeeld:

```text
ioThinx_4510/read/DO@DO-05/doStatus
```

met `{"value":1}` voor aan en `{"value":0}` voor uit. Als de feedback na een
write `0` blijft, controleer dan in de Moxa MQTT-configuratie of remote writes
zijn ingeschakeld en of het write-topic exact overeenkomt met bovenstaande
notatie.

Deze mapping is de basis voor de veiligheidslogica en moet synchroon blijven met de werkelijke hardwareconfiguratie.