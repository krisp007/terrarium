# TerraControl UI

Next.js dashboard for the local Costa Rica rainforest terrarium.

## Run

Requires Node.js 20+ and npm:

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

The UI proxies status requests to the Pi backend. Set `TERRARIUM_PI_URL` when the backend is not running on `127.0.0.1:8080`.

- `/api/status` shows the current Pi, MQTT, ESP32 and Moxa state.
- `/api/history` shows persisted sensor and command history.
