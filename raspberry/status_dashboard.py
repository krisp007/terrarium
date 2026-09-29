"""Small local status dashboard for the terrarium MQTT service."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, Optional


class StatusStore:
    """Thread-safe snapshot of the latest system and hardware status."""

    def __init__(self, history_path: str = "terrarium_history.db", max_history: int = 5000) -> None:
        self._lock = threading.Lock()
        self.history_path = history_path
        self.max_history = max_history
        self._database = sqlite3.connect(history_path, check_same_thread=False)
        self._database.execute(
            "CREATE TABLE IF NOT EXISTS history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, "
            "source TEXT NOT NULL, topic TEXT, values_json TEXT NOT NULL)"
        )
        self._database.commit()
        self._status: Dict[str, Any] = {
            "service": {"status": "starting"},
            "mqtt": {"status": "disconnected"},
            "esp32": {"status": "unknown", "sensors": {}},
            "moxa": {"status": "unknown", "inputs": {}, "outputs": {}},
            "commands": {},
        }

    def update(self, section: str, values: Dict[str, Any]) -> None:
        with self._lock:
            current = self._status.setdefault(section, {})
            if isinstance(current, dict):
                current.update(values)

    def update_nested(self, section: str, key: str, value: Any) -> None:
        with self._lock:
            target = self._status.setdefault(section, {})
            if isinstance(target, dict):
                target[key] = value

    def record(self, source: str, values: Dict[str, Any], topic: Optional[str] = None) -> None:
        """Persist one timestamped measurement or command."""
        with self._lock:
            self._database.execute(
                "INSERT INTO history(timestamp, source, topic, values_json) VALUES (?, ?, ?, ?)",
                (time.time(), source, topic, json.dumps(values)),
            )
            self._database.execute(
                "DELETE FROM history WHERE id NOT IN ("
                "SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                (self.max_history,),
            )
            self._database.commit()

    def history(self, limit: int = 100, source: Optional[str] = None) -> list[Dict[str, Any]]:
        """Return recent persisted records, newest first."""
        safe_limit = max(1, min(int(limit), self.max_history))
        query = "SELECT timestamp, source, topic, values_json FROM history"
        parameters: list[Any] = []
        if source:
            query += " WHERE source = ?"
            parameters.append(source)
        query += " ORDER BY id DESC LIMIT ?"
        parameters.append(safe_limit)
        with self._lock:
            rows = self._database.execute(query, parameters).fetchall()
        return [
            {
                "timestamp": row[0],
                "source": row[1],
                "topic": row[2],
                "values": json.loads(row[3]),
            }
            for row in rows
        ]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._status))

    def schedule(self) -> Dict[str, Any]:
        """Read the locally cached monthly profiles for offline operation."""
        path = Path(os.getenv("TERRARIUM_SCHEDULE_FILE", "terrarium_schedule.json"))
        try:
            with path.open("r", encoding="utf-8") as schedule_file:
                payload = json.load(schedule_file)
            return payload if isinstance(payload, dict) else {"profiles": {}}
        except (OSError, json.JSONDecodeError):
            return {"profiles": {}, "storage": "local", "sync": "pending"}

    def save_schedule(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist profiles atomically so the Pi remains the offline source of truth."""
        path = Path(os.getenv("TERRARIUM_SCHEDULE_FILE", "terrarium_schedule.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        document = {"profiles": payload.get("profiles", {}), "storage": "local", "sync": "pending", "updated_at": time.time()}
        with temporary_path.open("w", encoding="utf-8") as schedule_file:
            json.dump(document, schedule_file, indent=2)
            schedule_file.write("\n")
        temporary_path.replace(path)
        return document


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Terrarium climate</title>
<style>
:root{color-scheme:dark;background:#101b18;color:#f2f5ef;font-family:Georgia,serif}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;min-height:100dvh;display:grid;place-items:center;padding:36px;background:#101b18}
main{width:min(1120px,100%)}
header{display:flex;justify-content:space-between;align-items:end;gap:24px;margin-bottom:28px}
h1{font-size:32px;font-weight:400;margin:0}
.eyebrow{font:600 13px Arial,sans-serif;letter-spacing:2px;text-transform:uppercase;color:#9eafa5;margin-bottom:10px}
#sensor-state{font:16px Arial,sans-serif;color:#9eafa5;text-align:right}
#sensor-state.offline{color:#ff8b76}
.readings{display:grid;grid-template-columns:1fr 1fr;gap:20px}
article{min-height:330px;padding:32px;background:#1c3029;border:1px solid #385046;border-radius:8px;display:flex;flex-direction:column;justify-content:space-between}
article.humidity{background:#203039;border-color:#405764}
h2{font:600 16px Arial,sans-serif;margin:0;color:#c2d0c8}
.value{font:400 112px Georgia,serif;line-height:1;white-space:nowrap;color:#f2cd73}
.humidity .value{color:#78d5ce}
.unit{font:400 38px Arial,sans-serif;margin-left:8px;color:#d4ddd7}
@media(max-width:640px){body{padding:20px}.readings{grid-template-columns:1fr;gap:12px}article{min-height:220px;padding:24px}.value{font-size:76px}header{align-items:start;flex-direction:column;margin-bottom:18px}#sensor-state{text-align:left}}
</style>
</head>
<body>
<main>
<header><div><div class="eyebrow">Terrarium climate</div><h1>Live readings</h1></div><div id="sensor-state" role="status" aria-live="polite">Waiting for sensor data</div></header>
<div class="readings">
<article><h2>Air temperature</h2><div class="value"><span id="temperature">--</span><span class="unit">&#176;C</span></div></article>
<article class="humidity"><h2>Humidity</h2><div class="value"><span id="humidity">--</span><span class="unit">%</span></div></article>
</div>
</main>
<script>
const temperature=document.querySelector('#temperature');
const humidity=document.querySelector('#humidity');
const sensorState=document.querySelector('#sensor-state');
function averageReading(sensors,prefix){
 const readings=Object.entries(sensors||{}).filter(([name,value])=>name.startsWith(prefix)&&typeof value==='number'&&Number.isFinite(value)).map(([,value])=>value);
 return readings.length?readings.reduce((sum,value)=>sum+value,0)/readings.length:null;
}
function showReading(element,value){element.textContent=value===null?'--':value.toFixed(1);}
async function refresh(){
 try{
  const response=await fetch('/api/status',{cache:'no-store'});
  if(!response.ok)throw new Error('Status request failed');
  const status=await response.json();
  const sensors=status.esp32?.sensors||{};
  const temperatureValue=averageReading(sensors,'temperature_');
  const humidityValue=averageReading(sensors,'humidity_');
  showReading(temperature,temperatureValue);
  showReading(humidity,humidityValue);
  const hasReadings=temperatureValue!==null||humidityValue!==null;
  const lastSeen=Number(status.esp32?.last_seen);
  const stale=!Number.isFinite(lastSeen)||Date.now()/1000-lastSeen>60;
  sensorState.classList.toggle('offline',!hasReadings||stale);
  sensorState.textContent=!hasReadings?'Waiting for sensor data':stale?'Sensor data is stale':'Updated '+new Date(lastSeen*1000).toLocaleTimeString();
 }catch{
  showReading(temperature,null);
  showReading(humidity,null);
  sensorState.classList.add('offline');
  sensorState.textContent='Pi status unavailable';
 }
}
refresh();
window.setInterval(refresh,3000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    store: StatusStore
    override_callback: Any = None

    def do_GET(self) -> None:
        parsed_path = urlparse(self.path)
        query = parse_qs(parsed_path.query)
        if parsed_path.path == "/api/history":
            limit = int(query.get("limit", ["100"])[0])
            body = json.dumps(self.store.history(limit=limit)).encode("utf-8")
            content_type = "application/json"
        elif parsed_path.path == "/api/schedule":
            body = json.dumps(self.store.schedule()).encode("utf-8")
            content_type = "application/json"
        elif parsed_path.path == "/api/status":
            body = json.dumps(self.store.snapshot()).encode("utf-8")
            content_type = "application/json"
        elif parsed_path.path == "/":
            body = HTML.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self) -> None:
        if self.path != "/api/schedule":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("profiles", {}), dict):
                raise ValueError("profiles must be an object")
            body = json.dumps(self.store.save_schedule(payload)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid schedule payload")

    def do_POST(self) -> None:
        if self.path != "/api/override" or self.override_callback is None:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or not payload.get("actor_type") or not payload.get("actor_name"):
                raise ValueError("actor_type and actor_name are required")
            body = json.dumps(self.override_callback(payload)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_error(400, str(error))

    def log_message(self, *_args: object) -> None:
        return


def start_dashboard(store: StatusStore, host: str = "0.0.0.0", port: int = 8080, override_callback: Any = None) -> ThreadingHTTPServer:
    handler = type("TerrariumDashboardHandler", (DashboardHandler,), {"store": store, "override_callback": override_callback})
    server = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, name="status-dashboard", daemon=True).start()
    return server