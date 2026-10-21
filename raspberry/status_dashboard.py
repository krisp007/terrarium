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

    RAW_SENSOR_RETENTION_SECONDS = 30 * 24 * 60 * 60
    FIVE_MINUTE_RETENTION_SECONDS = 180 * 24 * 60 * 60
    HOURLY_RETENTION_SECONDS = 2 * 365 * 24 * 60 * 60
    EVENT_RETENTION_SECONDS = 180 * 24 * 60 * 60
    ALERT_RETENTION_SECONDS = 365 * 24 * 60 * 60
    CLEANUP_INTERVAL_SECONDS = 60 * 60
    MAX_HISTORY_QUERY_LIMIT = 10_000

    def __init__(self, history_path: str = "terrarium_history.db") -> None:
        self._lock = threading.Lock()
        self.history_path = history_path
        self._last_cleanup_at = 0.0
        self._database = sqlite3.connect(history_path, check_same_thread=False)
        self._database.execute(
            "CREATE TABLE IF NOT EXISTS history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, "
            "source TEXT NOT NULL, topic TEXT, values_json TEXT NOT NULL)"
        )
        self._database.execute(
            "CREATE INDEX IF NOT EXISTS history_source_timestamp "
            "ON history(source, timestamp)"
        )
        self._database.execute(
            "CREATE TABLE IF NOT EXISTS latest_event_state ("
            "source TEXT NOT NULL, topic TEXT NOT NULL, values_json TEXT NOT NULL, "
            "PRIMARY KEY(source, topic))"
        )
        self._database.execute(
            "CREATE TABLE IF NOT EXISTS sensor_rollups ("
            "bucket_seconds INTEGER NOT NULL, bucket_start INTEGER NOT NULL, "
            "sensor_name TEXT NOT NULL, sample_count INTEGER NOT NULL, "
            "minimum REAL NOT NULL, maximum REAL NOT NULL, average REAL NOT NULL, "
            "PRIMARY KEY(bucket_seconds, bucket_start, sensor_name))"
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

    def record(
        self,
        source: str,
        values: Dict[str, Any],
        topic: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Persist one timestamped measurement or command."""
        with self._lock:
            current_time = time.time() if timestamp is None else timestamp
            self._insert_record_locked(source, values, topic, current_time)
            self._database.commit()
            self._cleanup_if_due_locked(current_time)

    def record_state_change(
        self,
        source: str,
        values: Dict[str, Any],
        topic: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> bool:
        """Persist an event only when its payload differs from the last known state."""
        normalized_values = json.dumps(values, sort_keys=True, separators=(",", ":"))
        state_topic = topic or ""
        with self._lock:
            row = self._database.execute(
                "SELECT values_json FROM latest_event_state WHERE source = ? AND topic = ?",
                (source, state_topic),
            ).fetchone()
            if row is not None and row[0] == normalized_values:
                return False
            current_time = time.time() if timestamp is None else timestamp
            self._insert_record_locked(source, values, topic, current_time)
            self._database.execute(
                "INSERT INTO latest_event_state(source, topic, values_json) VALUES (?, ?, ?) "
                "ON CONFLICT(source, topic) DO UPDATE SET values_json = excluded.values_json",
                (source, state_topic, normalized_values),
            )
            self._database.commit()
            self._cleanup_if_due_locked(current_time)
            return True

    def cleanup(self, now: Optional[float] = None) -> None:
        """Apply retention and compact old sensor readings into aggregate buckets."""
        with self._lock:
            self._cleanup_locked(time.time() if now is None else now)

    def _insert_record_locked(
        self,
        source: str,
        values: Dict[str, Any],
        topic: Optional[str],
        timestamp: float,
    ) -> None:
        self._database.execute(
            "INSERT INTO history(timestamp, source, topic, values_json) VALUES (?, ?, ?, ?)",
            (timestamp, source, topic, json.dumps(values)),
        )

    def _cleanup_if_due_locked(self, now: float) -> None:
        if now - self._last_cleanup_at >= self.CLEANUP_INTERVAL_SECONDS:
            self._cleanup_locked(now)

    def _cleanup_locked(self, now: float) -> None:
        sensor_cutoff = now - self.RAW_SENSOR_RETENTION_SECONDS
        checkpoint_table = self._database.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cloud_sync'"
        ).fetchone()
        checkpoint = 0
        if checkpoint_table is not None:
            checkpoint_row = self._database.execute(
                "SELECT last_history_id FROM cloud_sync WHERE name = 'cosmos'"
            ).fetchone()
            checkpoint = int(checkpoint_row[0]) if checkpoint_row is not None else 0
        rows = self._database.execute(
            "SELECT id, timestamp, values_json FROM history "
            "WHERE source = 'esp32_sensors' AND timestamp < ? AND id <= ? ORDER BY id",
            (sensor_cutoff, checkpoint),
        ).fetchall()
        for history_id, timestamp, values_json in rows:
            values = json.loads(values_json)
            for sensor_name, value in values.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self._add_rollup_locked(300, timestamp, sensor_name, float(value))
            self._database.execute("DELETE FROM history WHERE id = ?", (history_id,))

        five_minute_cutoff = now - self.FIVE_MINUTE_RETENTION_SECONDS
        rows = self._database.execute(
            "SELECT bucket_start, sensor_name, sample_count, minimum, maximum, average "
            "FROM sensor_rollups WHERE bucket_seconds = 300 AND bucket_start < ?",
            (five_minute_cutoff,),
        ).fetchall()
        for bucket_start, sensor_name, sample_count, minimum, maximum, average in rows:
            self._merge_rollup_locked(
                3600,
                bucket_start,
                sensor_name,
                int(sample_count),
                float(minimum),
                float(maximum),
                float(average),
            )
        self._database.execute(
            "DELETE FROM sensor_rollups WHERE bucket_seconds = 300 AND bucket_start < ?",
            (five_minute_cutoff,),
        )
        self._database.execute(
            "DELETE FROM sensor_rollups WHERE bucket_seconds = 3600 AND bucket_start < ?",
            (now - self.HOURLY_RETENTION_SECONDS,),
        )
        self._database.execute(
            "DELETE FROM history WHERE source IN ('command', 'moxa_write', 'moxa_read') "
            "AND timestamp < ?",
            (now - self.EVENT_RETENTION_SECONDS,),
        )
        self._database.execute(
            "DELETE FROM history WHERE source = 'esp32_status' AND timestamp < ?",
            (sensor_cutoff,),
        )
        self._database.execute(
            "DELETE FROM history WHERE source = 'alert' AND timestamp < ?",
            (now - self.ALERT_RETENTION_SECONDS,),
        )
        self._database.commit()
        self._last_cleanup_at = now

    def _add_rollup_locked(
        self,
        bucket_seconds: int,
        timestamp: float,
        sensor_name: str,
        value: float,
    ) -> None:
        self._merge_rollup_locked(
            bucket_seconds,
            timestamp,
            sensor_name,
            sample_count=1,
            minimum=value,
            maximum=value,
            average=value,
        )

    def _merge_rollup_locked(
        self,
        bucket_seconds: int,
        timestamp: float,
        sensor_name: str,
        sample_count: int,
        minimum: float,
        maximum: float,
        average: float,
    ) -> None:
        bucket_start = int(timestamp // bucket_seconds) * bucket_seconds
        row = self._database.execute(
            "SELECT sample_count, minimum, maximum, average FROM sensor_rollups "
            "WHERE bucket_seconds = ? AND bucket_start = ? AND sensor_name = ?",
            (bucket_seconds, bucket_start, sensor_name),
        ).fetchone()
        if row is None:
            self._database.execute(
                "INSERT INTO sensor_rollups("
                "bucket_seconds, bucket_start, sensor_name, sample_count, minimum, maximum, average"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (bucket_seconds, bucket_start, sensor_name, sample_count, minimum, maximum, average),
            )
            return
        existing_count, existing_minimum, existing_maximum, existing_average = row
        total_count = int(existing_count) + sample_count
        merged_average = (
            float(existing_average) * int(existing_count) + average * sample_count
        ) / total_count
        self._database.execute(
            "UPDATE sensor_rollups SET sample_count = ?, minimum = ?, maximum = ?, average = ? "
            "WHERE bucket_seconds = ? AND bucket_start = ? AND sensor_name = ?",
            (
                total_count,
                min(float(existing_minimum), minimum),
                max(float(existing_maximum), maximum),
                merged_average,
                bucket_seconds,
                bucket_start,
                sensor_name,
            ),
        )

    def history(self, limit: int = 100, source: Optional[str] = None) -> list[Dict[str, Any]]:
        """Return recent persisted records, newest first."""
        safe_limit = max(1, min(int(limit), self.MAX_HISTORY_QUERY_LIMIT))
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

    def temperature_history(self, period: str) -> list[Dict[str, Optional[float]]]:
        """Return a chart-ready, time-bucketed temperature series."""
        periods = {
            "24h": (24 * 60 * 60, 2 * 60),
            "week": (7 * 24 * 60 * 60, 15 * 60),
            "month": (30 * 24 * 60 * 60, 60 * 60),
            "year": (365 * 24 * 60 * 60, 24 * 60 * 60),
        }
        if period not in periods:
            raise ValueError("unsupported temperature history period")
        duration, bucket_seconds = periods[period]
        cutoff = time.time() - duration
        readings: Dict[int, Dict[str, list[float]]] = {}
        temperature_keys = {
            "temperature_left": "left",
            "temperature_right": "right",
            "temperature_top": "middle",
            "aquarium_temp": "water",
            "humidity_left": "humidity_left",
            "humidity_right": "humidity_right",
            "humidity_top": "humidity_middle",
        }

        def add_reading(timestamp: float, name: str, value: float) -> None:
            bucket = int(timestamp // bucket_seconds) * bucket_seconds
            bucket_readings = readings.setdefault(
                bucket, {"left": [], "right": [], "middle": [], "water": []}
            )
            for humidity_key in ("humidity_left", "humidity_right", "humidity_middle"):
                bucket_readings.setdefault(humidity_key, [])
            key = temperature_keys.get(name)
            if key is not None:
                bucket_readings[key].append(value)

        with self._lock:
            raw_rows = self._database.execute(
                "SELECT timestamp, values_json FROM history "
                "WHERE source = 'esp32_sensors' AND timestamp >= ? ORDER BY timestamp",
                (cutoff,),
            ).fetchall()
            for timestamp, values_json in raw_rows:
                for name, value in json.loads(values_json).items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        add_reading(float(timestamp), name, float(value))
            rollup_rows = self._database.execute(
                "SELECT bucket_start, sensor_name, average FROM sensor_rollups "
                "WHERE bucket_start >= ? ORDER BY bucket_start",
                (cutoff,),
            ).fetchall()
            for timestamp, sensor_name, average in rollup_rows:
                add_reading(float(timestamp), sensor_name, float(average))

        return [
            {
                "timestamp": bucket,
                "air_temperature": (
                    sum(
                        value
                        for position in ("left", "right", "middle")
                        for value in values[position]
                    )
                    / sum(len(values[position]) for position in ("left", "right", "middle"))
                    if any(values[position] for position in ("left", "right", "middle"))
                    else None
                ),
                "temperature_left": (
                    sum(values["left"]) / len(values["left"]) if values["left"] else None
                ),
                "temperature_right": (
                    sum(values["right"]) / len(values["right"]) if values["right"] else None
                ),
                "temperature_middle": (
                    sum(values["middle"]) / len(values["middle"])
                    if values["middle"]
                    else None
                ),
                "aquarium_temperature": (
                    sum(values["water"]) / len(values["water"])
                    if values["water"]
                    else None
                ),
                "humidity_left": (
                    sum(values["humidity_left"]) / len(values["humidity_left"])
                    if values["humidity_left"]
                    else None
                ),
                "humidity_right": (
                    sum(values["humidity_right"]) / len(values["humidity_right"])
                    if values["humidity_right"]
                    else None
                ),
                "humidity_middle": (
                    sum(values["humidity_middle"]) / len(values["humidity_middle"])
                    if values["humidity_middle"]
                    else None
                ),
            }
            for bucket, values in sorted(readings.items())
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
.panel{margin-top:20px;padding:24px;background:#172721;border:1px solid #385046;border-radius:8px}
.panel h2{margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.item{padding:14px;background:#20352d;border-radius:6px;font:14px Arial,sans-serif}
.item strong{display:block;font-size:18px;margin-top:5px}
.on{color:#8fe0a6}.off{color:#a9b8b0}.alarm{color:#ff8b76}
.buttons{display:flex;flex-wrap:wrap;gap:8px}
button{border:1px solid #5b806d;border-radius:5px;background:#29463a;color:#f2f5ef;padding:9px 13px;cursor:pointer}
button:hover{background:#37604e}
#message{min-height:20px;color:#d7bd72;font:14px Arial,sans-serif}
#camera{width:100%;min-height:180px;border:0;border-radius:6px;background:#0e1714}
textarea{width:100%;min-height:360px;margin-top:12px;padding:14px;border:1px solid #5b806d;border-radius:5px;background:#101b18;color:#f2f5ef;font:13px/1.5 monospace;resize:vertical}
summary{cursor:pointer;font:600 16px Arial,sans-serif;color:#c2d0c8}
@media(max-width:800px){.grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:640px){body{padding:20px}.readings{grid-template-columns:1fr;gap:12px}article{min-height:220px;padding:24px}.value{font-size:76px}header{align-items:start;flex-direction:column;margin-bottom:18px}#sensor-state{text-align:left}}
</style>
</head>
<body>
<main>
<header><div><div class="eyebrow">Terrarium climate</div><h1>Live readings</h1></div><div id="sensor-state" role="status" aria-live="polite">Waiting for sensor data</div></header>
<p><a href="/history">Temperature history and trend</a></p>
<div class="readings">
<article><h2>Air temperature</h2><div class="value"><span id="temperature">--</span><span class="unit">&#176;C</span></div></article>
<article class="humidity"><h2>Humidity</h2><div class="value"><span id="humidity">--</span><span class="unit">%</span></div></article>
</div>
<section class="panel"><h2>Individual sensors</h2><div id="sensor-details" class="grid"></div></section>
<section class="panel"><h2>System and alarms</h2><div id="alarms" class="grid"></div></section>
<section class="panel"><h2>Actuators</h2><div id="actuators" class="grid"></div></section>
<section class="panel"><h2>Manual control</h2><div class="buttons">
<button onclick="override('Heat Lamp','on')">Heat lamp on</button>
<button onclick="override('Heat Lamp','off')">Heat lamp off</button>
<button onclick="override('Mist Maker','on')">Mist maker on</button>
<button onclick="override('Mist Maker','off')">Mist maker off</button>
<button onclick="override('Pump:irrigation','on')">Irrigation on</button>
<button onclick="override('Pump:irrigation','off')">Irrigation off</button>
<button onclick="override('Pump:ro','on')">RO on</button>
<button onclick="override('Pump:ro','off')">RO off</button>
<button onclick="restoreAuto('Heat Lamp')">Heat lamp auto</button>
<button onclick="restoreAuto('Mist Maker')">Mist maker auto</button>
<button onclick="restoreAuto('Pump','ro')">RO auto</button>
</div><p id="message" role="status" aria-live="polite"></p></section>
<details class="panel"><summary>Climate settings (JSON)</summary>
<p>Edit the active JSON profile. Changes are validated, saved to the settings file, and applied immediately.</p>
<textarea id="settings-json" spellcheck="false" aria-label="Terrarium settings JSON"></textarea>
<div class="buttons"><button onclick="loadSettings()">Reload</button><button onclick="saveSettings()">Save and apply</button></div>
<p id="settings-message" role="status" aria-live="polite"></p></details>
<section class="panel"><h2>Recent history</h2><div id="history" class="grid"></div></section>
<section class="panel" id="camera-panel"><h2>Camera</h2><img id="camera" alt="Terrarium camera unavailable"></section>
</main>
<script>
const temperature=document.querySelector('#temperature');
const humidity=document.querySelector('#humidity');
const sensorState=document.querySelector('#sensor-state');
const alarms=document.querySelector('#alarms');
const actuators=document.querySelector('#actuators');
const message=document.querySelector('#message');
const settingsEditor=document.querySelector('#settings-json');
const settingsMessage=document.querySelector('#settings-message');
const history=document.querySelector('#history');
const sensorDetails=document.querySelector('#sensor-details');
const cameraUrl=__CAMERA_URL__;
let activeSensorSettings={temperature_prefixes:['temperature'],humidity_prefixes:['humidity_'],labels:{}};
function averageReading(sensors,prefixes){
 const readings=Object.entries(sensors||{}).filter(([name,value])=>prefixes.some(prefix=>name.startsWith(prefix))&&typeof value==='number'&&Number.isFinite(value)).map(([,value])=>value);
 return readings.length?readings.reduce((sum,value)=>sum+value,0)/readings.length:null;
}
function showReading(element,value){element.textContent=value===null?'--':value.toFixed(1);}
function escapeHtml(value){return String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#39;");}
function card(name,value,extra=''){return `<div class="item">${escapeHtml(name)}<strong class="${extra}">${escapeHtml(value)}</strong></div>`;}
function outputState(value){return value==='ON'?'ON':'OFF';}
const sensorLabels={
 temperature_left:'Temperature left',
 temperature_right:'Temperature right',
 temperature_top:'Temperature middle/top',
 humidity_left:'Humidity left',
 humidity_right:'Humidity right',
 humidity_top:'Humidity middle/top',
 soil_left:'Soil moisture left',
 soil_right:'Soil moisture right',
 aquarium_temp:'Aquarium temperature'
};
const sensorUnits={
 temperature_left:'°C',
 temperature_right:'°C',
 temperature_top:'°C',
 humidity_left:'%',
 humidity_right:'%',
 humidity_top:'%',
 soil_left:'%',
 soil_right:'%',
 aquarium_temp:'°C'
};
function setSensorSettings(settings){
 activeSensorSettings={
  temperature_prefixes:settings?.temperature_prefixes||['temperature'],
  humidity_prefixes:settings?.humidity_prefixes||['humidity_'],
  labels:{...sensorLabels,...(settings?.labels||{})}
 };
}
function renderSensors(sensors){
 const keys=new Set([...Object.keys(sensorLabels),...Object.keys(sensors||{})]);
 const entries=[...keys].map(key=>{
  const label=activeSensorSettings.labels?.[key]||sensorLabels[key]||key.replaceAll('_',' ');
  const value=sensors[key];
  const prefixes=activeSensorSettings.temperature_prefixes||[];
  const humidityPrefixes=activeSensorSettings.humidity_prefixes||[];
  const unit=prefixes.some(prefix=>key.startsWith(prefix))?'°C':humidityPrefixes.some(prefix=>key.startsWith(prefix))||key.startsWith('soil_')?'%':'';
  return [key,label,value,unit];
 });
 sensorDetails.innerHTML=entries.map(([key,label,value])=>{
  const numeric=typeof value==='number'&&Number.isFinite(value);
  const prefixes=activeSensorSettings.temperature_prefixes||[];
  const humidityPrefixes=activeSensorSettings.humidity_prefixes||[];
  const unit=sensorUnits[key]||(
   prefixes.some(prefix=>key.startsWith(prefix))?'°C':
   humidityPrefixes.some(prefix=>key.startsWith(prefix))||key.startsWith('soil_')?'%':''
  );
  return card(label,numeric?`${value.toFixed(1)} ${unit}`:'--','on');
 }).join('');
}
function renderStatus(status){
 const sensors=status.esp32?.sensors||{};
 renderSensors(sensors);
 const lastSeen=Number(status.esp32?.last_seen);
 const stale=!Number.isFinite(lastSeen)||Date.now()/1000-lastSeen>60;
 const command=status.commands?.['moxa/cmd/output']||{};
 const alarmItems=[];
 if(stale)alarmItems.push(card('ESP32','OFFLINE','alarm'));
 if(status.mqtt?.status!=='connected')alarmItems.push(card('MQTT','OFFLINE','alarm'));
 if(status.moxa?.status!=='online')alarmItems.push(card('Moxa',status.moxa?.status||'UNKNOWN','alarm'));
 if(command.alarm)alarmItems.push(card('Safety alarm',command.reason||'ACTIVE','alarm'));
 alarms.innerHTML=alarmItems.length?alarmItems.join(''):card('Alarms','None','on');
 const outputs=Object.entries(command).filter(([key])=>key.startsWith('do'));
 actuators.innerHTML=outputs.length?outputs.map(([key,value])=>card(key.toUpperCase(),outputState(value),value==='ON'?'on':'off')).join(''):card('Outputs','No data');
}
function renderHistory(rows){
 history.innerHTML=rows.length?rows.slice(0,8).map(row=>card(
  row.source.replaceAll('_',' '),
  new Date(Number(row.timestamp)*1000).toLocaleTimeString(),
  'on'
 )).join(''):card('History','No data');
}
async function postOverride(actorType,actorName,state){
 const response=await fetch('/api/override',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor_type:actorType,actor_name:actorName,state:state==='on',intensity:100,duration_minutes:30})});
 if(!response.ok)throw new Error('Override failed');
 message.textContent='Command sent';
}
async function postAuto(actorType,actorName){
 const response=await fetch('/api/override',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'auto',actor_type:actorType,actor_name:actorName})});
 if(!response.ok)throw new Error('Auto mode failed');
 message.textContent='Automatic mode restored';
}
function override(actor, state){
 const [actorType,actorName]=actor.includes(':')?actor.split(':'): [actor,actor];
 postOverride(actorType,actorName,state).catch(()=>{message.textContent='Command failed';});
}
function restoreAuto(actorType,actorName=actorType){
 postAuto(actorType,actorName).catch(()=>{message.textContent='Auto mode failed';});
}
async function loadSettings(){
 settingsMessage.textContent='Loading settings...';
 try{
  const response=await fetch('/api/settings',{cache:'no-store'});
  if(!response.ok)throw new Error(await response.text());
  const settings=await response.json();
  setSensorSettings(settings.sensors);
  settingsEditor.value=JSON.stringify(settings,null,2);
  renderSensors(window.latestSensors||{});
  settingsMessage.textContent='Settings loaded';
 }catch(error){settingsMessage.textContent=`Settings unavailable: ${error.message}`;}
}
async function saveSettings(){
 settingsMessage.textContent='Saving settings...';
 try{
  const settings=JSON.parse(settingsEditor.value);
  const response=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});
  if(!response.ok)throw new Error(await response.text());
  const savedSettings=await response.json();
  setSensorSettings(savedSettings.sensors);
  settingsEditor.value=JSON.stringify(savedSettings,null,2);
  renderSensors(window.latestSensors||{});
  settingsMessage.textContent='Settings saved and applied';
 }catch(error){settingsMessage.textContent=`Could not save settings: ${error.message}`;}
}
async function refresh(){
 try{
  const response=await fetch('/api/status',{cache:'no-store'});
  if(!response.ok)throw new Error('Status request failed');
  const status=await response.json();
  const historyResponse=await fetch('/api/history?limit=8',{cache:'no-store'});
  if(!historyResponse.ok)throw new Error('History request failed');
  renderHistory(await historyResponse.json());
  const sensors=status.esp32?.sensors||{};
  window.latestSensors=sensors;
  renderSensors(sensors);
  const temperatureValue=averageReading(sensors,activeSensorSettings.temperature_prefixes||[]);
  const humidityValue=averageReading(sensors,activeSensorSettings.humidity_prefixes||[]);
  showReading(temperature,temperatureValue);
  showReading(humidity,humidityValue);
  const hasReadings=temperatureValue!==null||humidityValue!==null;
  const lastSeen=Number(status.esp32?.last_seen);
  const stale=!Number.isFinite(lastSeen)||Date.now()/1000-lastSeen>60;
  sensorState.classList.toggle('offline',!hasReadings||stale);
  sensorState.textContent=!hasReadings?'Waiting for sensor data':stale?'Sensor data is stale':'Updated '+new Date(lastSeen*1000).toLocaleTimeString();
  renderStatus(status);
 }catch{
  showReading(temperature,null);
  showReading(humidity,null);
  sensorState.classList.add('offline');
  sensorState.textContent='Pi status unavailable';
  renderSensors({});
  alarms.innerHTML=card('Pi','OFFLINE','alarm');
  actuators.innerHTML='';
 }
}
if(cameraUrl){document.querySelector('#camera').src=cameraUrl;}else{document.querySelector('#camera-panel').hidden=true;}
loadSettings();
refresh();
window.setInterval(refresh,3000);
</script>
</body>
</html>"""

HISTORY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Terrarium temperature history</title>
<style>
:root{color-scheme:dark;background:#101b18;color:#f2f5ef;font-family:Arial,sans-serif}
*{box-sizing:border-box}body{margin:0;padding:28px;background:#101b18}main{width:min(1120px,100%);margin:auto}
a{color:#8fe0a6}h1{font:400 32px Georgia,serif;margin:12px 0}.subtitle{color:#a9b8b0}
.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:20px 0}.card{padding:18px;background:#1c3029;border:1px solid #385046;border-radius:8px}.card span{display:block;color:#a9b8b0;font-size:14px}.card strong{display:block;margin-top:8px;font-size:24px}
.chart{position:relative;width:100%;min-height:360px;background:#172721;border:1px solid #385046;border-radius:8px;padding:12px}.legend{display:flex;gap:18px;flex-wrap:wrap;margin:15px 0;color:#c2d0c8}.legend-group{display:flex;gap:14px;flex-wrap:wrap}.humidity-legend{margin-left:auto}.dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px}.left{background:#f2cd73}.right{background:#ff9f6d}.middle{background:#8fe0a6}.water{background:#78d5ce}.forecast{background:#cc9cff}.humidity-left{background:#7187e8}.humidity-right{background:#bb7be8}.humidity-middle{background:#ed75a5}
.ranges{display:flex;gap:8px;flex-wrap:wrap}.ranges button{background:#29463a;color:#f2f5ef;border:1px solid #5b806d;border-radius:5px;padding:8px 12px;cursor:pointer}.ranges button.active{background:#78d5ce;color:#10211b}
#tooltip{display:none;position:absolute;z-index:2;max-width:230px;padding:10px;border:1px solid #6d8d7d;border-radius:6px;background:#10211bf2;color:#f2f5ef;font-size:12px;line-height:1.5;pointer-events:none;box-shadow:0 3px 12px #0008}.tooltip-title{font-weight:700;color:#d7bd72}
#status{color:#a9b8b0}.error{color:#ff8b76}@media(max-width:640px){body{padding:18px}.summary{grid-template-columns:1fr}.chart{min-height:280px}}
</style>
</head>
<body>
<main>
<a href="/">← Live dashboard</a>
<h1>Temperature history</h1>
<p class="subtitle">Air temperature, aquarium water temperature, and a 30-minute linear trend forecast based on the latest air-temperature measurements.</p>
<div class="ranges" aria-label="History period"><button class="active" data-range="24h">24 hours</button><button data-range="week">Week</button><button data-range="month">Month</button><button data-range="year">Year</button></div>
<div class="summary"><div class="card"><span>Latest air temperature</span><strong id="air-value">--</strong></div><div class="card"><span>Latest water temperature</span><strong id="water-value">--</strong></div><div class="card"><span>30-minute air trend</span><strong id="forecast-value">--</strong></div></div>
<div class="legend"><div class="legend-group"><span><i class="dot left"></i>Air left</span><span><i class="dot right"></i>Air right</span><span><i class="dot middle"></i>Air middle/top</span><span><i class="dot water"></i>Aquarium water</span><span><i class="dot forecast"></i>Average forecast</span></div><div class="legend-group humidity-legend"><span><i class="dot humidity-left"></i>Humidity left</span><span><i class="dot humidity-right"></i>Humidity right</span><span><i class="dot humidity-middle"></i>Humidity middle/top</span></div></div>
<div class="chart"><svg id="chart" viewBox="0 0 1000 360" role="img" aria-label="Air and water temperature history"></svg><div id="tooltip" role="status"></div></div>
<p id="status" role="status">Loading history...</p>
</main>
<script>
const svg=document.querySelector('#chart');
const airValue=document.querySelector('#air-value');
const waterValue=document.querySelector('#water-value');
const forecastValue=document.querySelector('#forecast-value');
const status=document.querySelector('#status');
const chartContainer=document.querySelector('.chart');
const tooltip=document.querySelector('#tooltip');
const width=1000,height=360,pad={left:60,right:24,top:24,bottom:42};
const minimumTemperature=15;
const maximumTemperature=35;
function pointPath(points,x,y){return points.map((point,index)=>`${index?'L':'M'}${x(point.x).toFixed(1)},${y(point.y).toFixed(1)}`).join(' ');}
function valueLabel(label,value,unit){return typeof value==='number'&&Number.isFinite(value)?`${label}: ${value.toFixed(2)} ${unit}`:'';}
function trend(points){
 if(points.length<2)return null;
 const origin=points[0].x;
 const values=points.map(point=>({x:(point.x-origin)/60000,y:point.y}));
 const count=values.length,sumX=values.reduce((sum,point)=>sum+point.x,0),sumY=values.reduce((sum,point)=>sum+point.y,0);
 const sumXY=values.reduce((sum,point)=>sum+point.x*point.y,0),sumXX=values.reduce((sum,point)=>sum+point.x*point.x,0);
 const denominator=count*sumXX-sumX*sumX;
 if(!denominator)return null;
 const slope=(count*sumXY-sumX*sumY)/denominator;
 const intercept=(sumY-slope*sumX)/count;
 return {slope,at:minutes=>intercept+slope*minutes};
}
function render(rows){
 const air=rows.map(row=>({x:Number(row.timestamp)*1000,y:row.air_temperature})).filter(point=>typeof point.y==='number'&&Number.isFinite(point.y));
 const left=rows.map(row=>({x:Number(row.timestamp)*1000,y:row.temperature_left})).filter(point=>typeof point.y==='number'&&Number.isFinite(point.y));
 const right=rows.map(row=>({x:Number(row.timestamp)*1000,y:row.temperature_right})).filter(point=>typeof point.y==='number'&&Number.isFinite(point.y));
 const middle=rows.map(row=>({x:Number(row.timestamp)*1000,y:row.temperature_middle})).filter(point=>typeof point.y==='number'&&Number.isFinite(point.y));
 const water=rows.map(row=>({x:Number(row.timestamp)*1000,y:row.aquarium_temperature})).filter(point=>typeof point.y==='number'&&Number.isFinite(point.y));
 const humidityLeft=rows.map(row=>({x:Number(row.timestamp)*1000,y:row.humidity_left})).filter(point=>typeof point.y==='number'&&Number.isFinite(point.y));
 const humidityRight=rows.map(row=>({x:Number(row.timestamp)*1000,y:row.humidity_right})).filter(point=>typeof point.y==='number'&&Number.isFinite(point.y));
 const humidityMiddle=rows.map(row=>({x:Number(row.timestamp)*1000,y:row.humidity_middle})).filter(point=>typeof point.y==='number'&&Number.isFinite(point.y));
 const all=[...left,...right,...middle,...water];
 if(!all.length){status.textContent='No temperature history is available yet.';return;}
 const forecast=trend(air.slice(-30));
 const lastAir=air.at(-1),lastWater=water.at(-1);
 const forecastPoint=forecast&&lastAir?{x:lastAir.x+30*60000,y:Math.min(maximumTemperature,Math.max(minimumTemperature,forecast.at((lastAir.x-air[0].x)/60000+30)))}:null;
 const values=forecastPoint?[...all,forecastPoint]:all;
 const minX=Math.min(...values.map(point=>point.x)),maxX=Math.max(...values.map(point=>point.x));
 const minY=minimumTemperature,maxY=maximumTemperature;
 const x=value=>pad.left+(value-minX)/(maxX-minX||1)*(width-pad.left-pad.right);
 const y=value=>height-pad.bottom-(value-minY)/(maxY-minY||1)*(height-pad.top-pad.bottom);
 const humidityY=value=>height-pad.bottom-value/100*(height-pad.top-pad.bottom);
 const grid=[0,.25,.5,.75,1].map(fraction=>{const value=minY+(maxY-minY)*fraction,humidity=100*fraction,position=y(value);return `<line x1="${pad.left}" x2="${width-pad.right}" y1="${position}" y2="${position}" stroke="#385046"/><text x="4" y="${position+5}" fill="#a9b8b0" font-size="13">${value.toFixed(1)}°C</text><text x="${width-pad.right+4}" y="${position+5}" fill="#a9b8b0" font-size="13">${humidity.toFixed(0)}%</text>`;}).join('');
 const historyEnd=Math.max(...all.map(point=>point.x));
 const xGrid=[0,.25,.5,.75,1].map(fraction=>{const timestamp=minX+(maxX-minX)*fraction,position=x(timestamp);return `<line x1="${position}" x2="${position}" y1="${pad.top}" y2="${height-pad.bottom}" stroke="#385046"/><text x="${position}" y="${height-12}" text-anchor="middle" fill="#a9b8b0" font-size="13">${new Date(timestamp).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</text>`;}).join('');
 svg.innerHTML=`${grid}${xGrid}<line x1="${pad.left}" x2="${width-pad.right}" y1="${height-pad.bottom}" y2="${height-pad.bottom}" stroke="#a9b8b0"/><path d="${left.length?pointPath(left,x,y):''}" fill="none" stroke="#f2cd73" stroke-width="3"/><path d="${right.length?pointPath(right,x,y):''}" fill="none" stroke="#ff9f6d" stroke-width="3"/><path d="${middle.length?pointPath(middle,x,y):''}" fill="none" stroke="#8fe0a6" stroke-width="3"/><path d="${water.length?pointPath(water,x,y):''}" fill="none" stroke="#78d5ce" stroke-width="3"/><path d="${humidityLeft.length?pointPath(humidityLeft,x,humidityY):''}" fill="none" stroke="#7187e8" stroke-width="2"/><path d="${humidityRight.length?pointPath(humidityRight,x,humidityY):''}" fill="none" stroke="#bb7be8" stroke-width="2"/><path d="${humidityMiddle.length?pointPath(humidityMiddle,x,humidityY):''}" fill="none" stroke="#ed75a5" stroke-width="2"/>${forecastPoint?`<path d="${pointPath([lastAir,forecastPoint],x,y)}" fill="none" stroke="#cc9cff" stroke-width="3" stroke-dasharray="8 6"/>`:''}<line id="crosshair" x1="0" x2="0" y1="${pad.top}" y2="${height-pad.bottom}" stroke="#f2f5ef" stroke-width="1" stroke-dasharray="4 4" visibility="hidden"/>`;
 const crosshair=document.querySelector('#crosshair');
 svg.onmousemove=event=>{
  const bounds=svg.getBoundingClientRect();
  const chartX=(event.clientX-bounds.left)/bounds.width*width;
  const targetTime=minX+(Math.max(pad.left,Math.min(width-pad.right,chartX))-pad.left)/(width-pad.left-pad.right)*(maxX-minX||1);
  const row=rows.reduce((closest,current)=>Math.abs(Number(current.timestamp)*1000-targetTime)<Math.abs(Number(closest.timestamp)*1000-targetTime)?current:closest);
  const position=x(Number(row.timestamp)*1000);
  crosshair.setAttribute('x1',position);crosshair.setAttribute('x2',position);crosshair.setAttribute('visibility','visible');
  const details=[
   valueLabel('Air left',row.temperature_left,'°C'),valueLabel('Air right',row.temperature_right,'°C'),valueLabel('Air middle/top',row.temperature_middle,'°C'),valueLabel('Water',row.aquarium_temperature,'°C'),
   valueLabel('Humidity left',row.humidity_left,'%'),valueLabel('Humidity right',row.humidity_right,'%'),valueLabel('Humidity middle/top',row.humidity_middle,'%')
  ].filter(Boolean).join('<br>');
  tooltip.innerHTML=`<div class="tooltip-title">${new Date(Number(row.timestamp)*1000).toLocaleString()}</div>${details}`;
  tooltip.style.display='block';
  tooltip.style.left=`${Math.min(event.clientX-bounds.left+14,bounds.width-240)}px`;
  tooltip.style.top=`${Math.max(event.clientY-bounds.top-20,8)}px`;
 };
 svg.onmouseleave=()=>{crosshair.setAttribute('visibility','hidden');tooltip.style.display='none';};
 airValue.textContent=lastAir?`${lastAir.y.toFixed(1)} °C`:'--';
 waterValue.textContent=lastWater?`${lastWater.y.toFixed(1)} °C`:'--';
 forecastValue.textContent=forecastPoint?`${forecastPoint.y.toFixed(1)} °C`:air.length<2?'Need more data':'--';
 status.textContent=forecastPoint?`Trend: ${(forecast.slope*60).toFixed(2)} °C/hour. This is a simple linear estimate, not a control target.`:`Showing ${all.length} temperature measurements.`;
}
async function loadPeriod(period){
 status.textContent='Loading history...';
 try{
  const response=await fetch(`/api/temperature-history?range=${period}`,{cache:'no-store'});
  if(!response.ok)throw new Error();
  render(await response.json());
 }catch{status.textContent='History is unavailable.';status.classList.add('error');}
}
document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-range]').forEach(item=>item.classList.toggle('active',item===button));loadPeriod(button.dataset.range);}));
loadPeriod('24h');
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    store: StatusStore
    override_callback: Any = None
    settings_callback: Any = None
    update_settings_callback: Any = None
    camera_url: str = ""

    def do_GET(self) -> None:
        parsed_path = urlparse(self.path)
        query = parse_qs(parsed_path.query)
        if parsed_path.path == "/api/history":
            limit = int(query.get("limit", ["100"])[0])
            body = json.dumps(self.store.history(limit=limit)).encode("utf-8")
            content_type = "application/json"
        elif parsed_path.path == "/api/temperature-history":
            period = query.get("range", ["24h"])[0]
            try:
                body = json.dumps(self.store.temperature_history(period)).encode("utf-8")
            except ValueError:
                self.send_error(400, "range must be 24h, week, month, or year")
                return
            content_type = "application/json"
        elif parsed_path.path == "/api/schedule":
            body = json.dumps(self.store.schedule()).encode("utf-8")
            content_type = "application/json"
        elif parsed_path.path == "/api/settings":
            if self.settings_callback is None:
                self.send_error(503, "Settings are unavailable")
                return
            body = json.dumps(self.settings_callback()).encode("utf-8")
            content_type = "application/json"
        elif parsed_path.path == "/api/status":
            body = json.dumps(self.store.snapshot()).encode("utf-8")
            content_type = "application/json"
        elif parsed_path.path == "/":
            body = HTML.replace("__CAMERA_URL__", json.dumps(self.camera_url)).encode("utf-8")
            content_type = "text/html; charset=utf-8"
        elif parsed_path.path == "/history":
            body = HISTORY_HTML.encode("utf-8")
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
        if self.path == "/api/settings":
            if self.update_settings_callback is None:
                self.send_error(503, "Settings are read-only")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("settings must be a JSON object")
                body = json.dumps(self.update_settings_callback(payload)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, json.JSONDecodeError) as error:
                self.send_error(400, str(error))
            except OSError:
                self.send_error(500, "Could not persist settings")
            return
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


def start_dashboard(
    store: StatusStore,
    host: str = "0.0.0.0",
    port: int = 8080,
    override_callback: Any = None,
    settings_callback: Any = None,
    update_settings_callback: Any = None,
) -> ThreadingHTTPServer:
    handler = type(
        "TerrariumDashboardHandler",
        (DashboardHandler,),
        {
            "store": store,
            "override_callback": staticmethod(override_callback),
            "settings_callback": staticmethod(settings_callback),
            "update_settings_callback": staticmethod(update_settings_callback),
            "camera_url": os.getenv("TERRARIUM_CAMERA_URL", ""),
        },
    )
    server = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, name="status-dashboard", daemon=True).start()
    return server