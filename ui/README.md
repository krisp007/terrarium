# TerraControl UI

Next.js dashboard for the local Costa Rica rainforest terrarium.

## Run

Requires Node.js 20+ and npm:

```bash
npm install
TERRARIUM_PI_URL=http://192.168.24.166:8080 npm run dev
```

Open `http://localhost:3000`.

Run this app on your development PC, not on the Raspberry Pi. Set `TERRARIUM_PI_URL` to the Pi's reachable address; the example above uses the current Pi address.

- `/api/status` shows the current Pi, MQTT, ESP32 and Moxa state.
- `/api/history` shows persisted sensor and command history.

In PowerShell, set the backend before starting Next.js:

```powershell
$env:TERRARIUM_PI_URL = "http://192.168.24.166:8080"
npm run dev
```
