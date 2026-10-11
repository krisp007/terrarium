# Azure setup plan for the terrarium project

## Goal

Host the web interface in Azure while keeping the Raspberry Pi as the real controller and local safety layer. The Pi remains the source of truth for sensors, Moxa/ESP32 logic, alarms and local automations. Azure is used as a remote dashboard, cloud history store and optional mirror of the latest state.

## Recommended architecture

- Frontend: Azure Static Web Apps (Free)
- API: Azure Functions (Consumption)
- Database: Azure Cosmos DB for NoSQL
- Local controller: Raspberry Pi with SQLite queue for offline sync
- Optional telemetry: Application Insights

## Why this is the best fit

This project is control-heavy and must remain stable even when internet connectivity is down. The Raspberry Pi already owns the real automation loop:

- MQTT broker
- terrarium logic
- Moxa input/output control
- fail-safe actions
- local status API

So Azure should not replace that controller. Azure should only provide:

- a hosted web UI
- remote access and monitoring
- a cloud history and settings store
- a backup when the Pi is online

## Exact Azure resource names

### Resource group

- rg-terrarium-prod

### Static Web App

- swa-terrarium-ui

### Function App

- func-terrarium-api

### Storage account for Azure Functions

- stterrariumprod001

### Cosmos DB account

- cosmos-terrarium-prod

### Cosmos database

- db-terrarium

### Cosmos containers

- sensor_readings
- settings
- alerts
- device_status

### Application Insights

- appi-terrarium-prod

## Resource layout

```text
Azure
├── Resource Group: rg-terrarium-prod
│   ├── Static Web App: swa-terrarium-ui
│   ├── Function App: func-terrarium-api
│   ├── Storage Account: stterrariumprod001
│   ├── Cosmos DB Account: cosmos-terrarium-prod
│   │   └── Database: db-terrarium
│   │       ├── Container: sensor_readings
│   │       ├── Container: settings
│   │       ├── Container: alerts
│   │       └── Container: device_status
│   └── App Insights: appi-terrarium-prod
```

## Data model

### sensor_readings

Used for sensor samples from the Pi.

Suggested partition key:

- /deviceId

Example fields:

- id
- deviceId
- timestamp
- temperature_top
- humidity_top
- temperature_left
- humidity_left
- temperature_right
- humidity_right
- aquarium_temp
- soil_left
- soil_right
- source
- syncedAt

### settings

Used for terrarium settings and profile snapshots.

Suggested partition key:

- /profileName

Example fields:

- id
- profileName
- version
- updatedAt
- config
- active

### alerts

Used for leak, heat, humidity, reservoir, heartbeat and other alarm events.

Suggested partition key:

- /deviceId

Example fields:

- id
- deviceId
- alertType
- severity
- message
- occurredAt
- resolved

### device_status

Used for current status and last seen metadata.

Suggested partition key:

- /deviceId

Example fields:

- deviceId
- status
- lastSeen
- mqttConnected
- piOnline
- firmwareVersion

## Local Pi offline-first pattern

The Pi should keep working even if Azure is unreachable.

Recommended flow:

1. Raspberry Pi reads sensors and status from MQTT / ESP32 / Moxa.
2. Pi runs terrarium logic locally and controls outputs.
3. Pi stores state and events in a local SQLite database.
4. Pi batches new records and retries them to Azure when online.
5. Azure receives the cloud copy but does not control the hardware.

This makes the Pi the real controller and Azure a cloud mirror / remote dashboard.

## Free-tier recommendation

Best free-first setup:

- Azure Static Web Apps: Free
- Azure Functions: Consumption
- Cosmos DB: serverless / free tier if available in the region
- Application Insights: optional and low-cost

This is the best option to keep the project inexpensive while still giving you remote access.

## Azure CLI creation flow

```bash
az login
az account set --subscription "<subscription ID>"

export LOCATION="westeurope"
export RG="rg-terrarium-prod"
export SWA="swa-terrarium-ui"
export FUNC="func-terrarium-api"
export STORAGE="stterrariumprod001"
export COSMOS="cosmos-terrarium-prod"
export DB="db-terrarium"

az group create --name "$RG" --location "$LOCATION"
az storage account create \
  --name "$STORAGE" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2

az extension add --name staticwebapp --upgrade

az staticwebapp create \
  --name "$SWA" \
  --resource-group "$RG" \
  --source https://github.com/krisp007/terra_ui \
  --branch main \
  --location "$LOCATION" \
  --app-location ui \
  --output-location .next \
  --login-with-github

az functionapp create \
  --name "$FUNC" \
  --resource-group "$RG" \
  --storage-account "$STORAGE" \
  --consumption-plan-location "$LOCATION" \
  --runtime python \
  --runtime-version 3.12 \
  --functions-version 4 \
  --os-type Linux

az cosmosdb create \
  --name "$COSMOS" \
  --resource-group "$RG" \
  --locations regionName="$LOCATION" failoverPriority=0 isZoneRedundant=False \
  --default-consistency-level Session \
  --capabilities EnableServerless

az cosmosdb sql database create \
  --account-name "$COSMOS" \
  --resource-group "$RG" \
  --name "$DB"

az cosmosdb sql container create \
  --account-name "$COSMOS" \
  --resource-group "$RG" \
  --database-name "$DB" \
  --name sensor_readings \
  --partition-key-path "/deviceId"

az cosmosdb sql container create \
  --account-name "$COSMOS" \
  --resource-group "$RG" \
  --database-name "$DB" \
  --name settings \
  --partition-key-path "/profileName"

az cosmosdb sql container create \
  --account-name "$COSMOS" \
  --resource-group "$RG" \
  --database-name "$DB" \
  --name alerts \
  --partition-key-path "/deviceId"

az cosmosdb sql container create \
  --account-name "$COSMOS" \
  --resource-group "$RG" \
  --database-name "$DB" \
  --name device_status \
  --partition-key-path "/deviceId"

az monitor app-insights component create \
  --app appi-terrarium-prod \
  --location "$LOCATION" \
  --resource-group "$RG" \
  --application-type web
```

## Environment variables for the Pi

In the local `.env` file, keep values like this:

```dotenv
TERRARIUM_MQTT_BROKER=192.168.24.166
TERRARIUM_MQTT_PORT=1883
TERRARIUM_SETTINGS_FILE=terrarium_settings_template.json
TERRARIUM_LOG_LEVEL=INFO
TERRARIUM_PI_URL=http://127.0.0.1:8080

COSMOS_URL=https://cosmos-terrarium-prod.documents.azure.com:443/
COSMOS_KEY=<primary-key>
COSMOS_DATABASE=db-terrarium
COSMOS_CONTAINER=sensor_readings
```

## Final recommendation

Use this exact Azure pattern:

- Azure Static Web Apps for the UI
- Azure Functions for the API
- Cosmos DB for cloud history and settings
- Raspberry Pi for local control and offline-first sync

This is the most practical and lowest-complexity Azure setup for your terrarium project.
