# Moxa ioThinx 4510 I/O Map

## Doel

De Moxa is de veiligheids- en schakelcontroller. Zij bewaakt de kritische status van reservoirniveaus, lekdetectie, RO-niveau en de voedingen van verlichting, warmte en irrigatie.

Netwerkadres: `192.168.24.50`
MQTT-broker: `192.168.24.51:1883`

---

## 1. Digitale ingangen

| Input | Functie | Beschrijving |
|-------|---------|-------------|
| DI0 | Vlotter mistmaker | Controleert of het mistmakerreservoir voldoende gevuld is |
| DI1 | Vlotter beregening | Controleert of het beregeningsreservoir voldoende gevuld is |
| DI2 | Lekdetectie | Geeft alarm bij waterlek |
| DI3 | Drukknop | vullen aquarium |
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
| DO6 | Warmtelamp 1 | Verlichting / warmte |
| DO7 | Warmtelamp 2 | Verlichting / warmte |
| DO8 | Reserve | Vrije output / toekomstige functie |
| DO9 | Reserve | Vrije output / toekomstige functie |
| DO10 | Pomp 1 (12v DC) Watervalpomp | Waterstroom / extra circulatie |
| DO11 | Pomp 2 (12v DC) beregening | druppelaar boomstam |
| DO12 | Pomp 3 (12v DC) | mistmaker |
| DO13 | Pomp 4 (12v DC) | aquarium bijvullen; actief zolang DI3 is ingedrukt |
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

DI3 is de drukknop voor aquariumvulpomp DO13 en is geen RO-minimumsensor meer.
DI4 blijft de maximumvlotter van het RO-reservoir. Omdat er geen
RO-minimum-/startsignaal is toegewezen, blijft DO15 uit totdat dit signaal is
vastgelegd. Lekdetectie (DI2) of alarm schakelt DO15 direct `OFF`.

### Beregening en mistmaker: frequentie en duur

Beregening en mistmaker volgen een cyclus uit `terrarium_settings_template.json`
(`irrigation.cycle_minutes` / `duration_seconds` en `mistmaker.max_runtime_minutes`
/ `pause_minutes`). De beregeningscyclus wordt niet gestuurd door de
bodemvochtsensoren; die waarden zijn momenteel alleen voor monitoring:

- Beregening volgt de ingestelde cyclus, mits reservoir OK en geen lekalarm
- De mistmaker volgt de ingestelde cyclus en luchtvochtigheid
- DO4/DO5 zijn de activeringsuitgangen. DO11 (beregeningspomp) en DO12
  (mistmakerpomp) zijn afzonderlijke uitgangen en worden niet automatisch aan
  DO4/DO5 gekoppeld.

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