# Moxa ioThinx 4510 I/O Map

## Doel

De Moxa is de veiligheids- en schakelcontroller. Zij bewaakt de kritische status van reservoirniveaus, lekdetectie, RO-niveau en de voedingen van verlichting, warmte en irrigatie.

Netwerkadres: `192.168.24.50`
MQTT-broker: `192.168.24.166:1883`

---

## 1. Digitale ingangen

| Input | Functie | Beschrijving |
|-------|---------|-------------|
| DI0 | Vlotter mistmaker | Controleert of het mistmakerreservoir voldoende gevuld is |
| DI1 | Vlotter beregening | Controleert of het beregeningsreservoir voldoende gevuld is |
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
| DO7 | Watervalpomp | Waterstroom / extra circulatie |
| DO8 | Reserve | Vrije output / toekomstige functie |
| DO9 | Pomp 1 mistmaker | Toekomstige of extra pompfunctie |
| DO10 | Pomp 2 beregening | Toekomstige of extra pompfunctie |
| DO11 | Pomp 3 | Reserve |
| DO12 | Pomp 4 | Reserve |
| DO13 | Reserve | Vrije output |
| DO14 | Reserve | Vrije output |
| DO15 | WaterValve RO | RO-waterafsluiting of RO-voeding |

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

### RO-niveau buiten bereik

Acties:

- RO-verwerking stoppen of blokkeren
- alarm genereren

### RO-vulregeling (DO15)

DO15 (RO-waterklep) wordt geregeld met hysterese tussen DI3 (minimumniveau) en
DI4 (maximumniveau):

- DI3 = `false` (onder minimum) → DO15 = `ON`, klep vult bij
- DI4 = `true` (maximum bereikt) → DO15 = `OFF`, vullen stopt
- Tussen minimum en maximum blijft de laatste status behouden (bang-bang regeling)
- Lekdetectie (DI2) of alarm schakelt DO15 direct `OFF`

### Beregening en mistmaker: frequentie en duur

Beregening en mistmaker volgen een cyclus uit `terrarium_settings_template.json`
(`irrigation.cycle_minutes` / `duration_seconds` en `mistmaker.max_runtime_minutes`
/ `pause_minutes`), en starten alleen wanneer de sensorwaarde dit toelaat:

- Bodemvocht te laag → beregening mag starten (`OK`)
- Bodemvocht te hoog → beregening geforceerd uit (`niet OK`)
- Dezelfde logica geldt voor luchtvochtigheid en de mistmaker

### Vlotter-override reservoirs (DI0/DI1)

Zolang de vlotters op het mistmaker- en beregeningsreservoir nog niet
bekabeld zijn, forceert `safety.float_overrides` in de instellingen deze
inputs naar `true` (reservoir OK). Zodra de vlotters zijn aangesloten, de
override verwijderen of op `null` zetten zodat de echte DI-waarde geldt.

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