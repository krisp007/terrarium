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
.readings{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
article{min-width:0;min-height:300px;padding:24px;background:#1c3029;border:1px solid #385046;border-radius:8px;display:flex;flex-direction:column;justify-content:space-between;gap:22px}
article.humidity{background:#203039;border-color:#405764}
article.water{background:#28372b;border-color:#53684e}
h2{font:600 16px Arial,sans-serif;margin:0;color:#c2d0c8}
.value{font:400 72px Georgia,serif;line-height:1;white-space:nowrap;color:#f2cd73}
.humidity .value{color:#78d5ce}
.water .value{color:#a7d879}
.unit{font:400 28px Arial,sans-serif;margin-left:6px;color:#d4ddd7}
.sensor-breakdown{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:auto;padding-top:14px;border-top:1px solid #385046;font-family:Arial,sans-serif}
.sensor-breakdown div{display:flex;align-items:baseline;gap:3px;white-space:nowrap}
.sensor-label{color:#9eafa5;font-size:12px;margin-right:auto}
.sensor-value{font-size:18px;color:#f2f5ef}
.sensor-unit{font-size:12px;color:#a9b8b0}
.ventilation{margin-top:16px;padding:22px 24px;background:#1c3029;border:1px solid #385046;border-radius:8px}
.ventilation-header{display:flex;justify-content:space-between;align-items:center;gap:16px}
.ventilation-header h2{margin:0}
#fan-state{font:600 14px Arial,sans-serif;color:#a7d879}
.ventilation-sequence{margin:16px 0 0;color:#a9b8b0;font:14px Arial,sans-serif}
.fan-channels{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-top:16px}
.fan-channel{padding:12px;background:#172721;border:1px solid #385046;border-radius:6px;display:flex;justify-content:space-between;align-items:center;font:14px Arial,sans-serif}
.fan-channel.sequence-active{border-color:#a7d879;color:#a7d879}
.fan-level{font-weight:600;color:#f2f5ef}
.lighting{margin-top:16px;padding:22px 24px;background:#302d22;border:1px solid #665b38;border-radius:8px}
.lighting-header{display:flex;justify-content:space-between;align-items:center;gap:16px}
#light-state{font:600 14px Arial,sans-serif;color:#f2cd73}
.lighting-sequence{margin:16px 0 0;color:#c2b98f;font:14px Arial,sans-serif}
.led-channels{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:16px}
.led-channel{padding:12px;background:#211f19;border:1px solid #665b38;border-radius:6px;display:flex;justify-content:space-between;align-items:center;font:14px Arial,sans-serif}
.led-channel.active{border-color:#f2cd73;color:#f2cd73}
.led-level{font-weight:600;color:#f2f5ef}
.climate-strip{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 12px}
.climate-chip{padding:9px 12px;background:#1c3029;border:1px solid #385046;border-radius:6px;color:#c2d0c8;font:13px Arial,sans-serif}
.climate-chip strong{color:#f2f5ef;margin-left:5px}
.alarm-bar{padding:13px 16px;margin:0 0 16px;border:1px solid #50624b;border-radius:6px;background:#1c3029;color:#b5db9a;font:600 14px Arial,sans-serif}
.alarm-bar.warning{border-color:#98763b;background:#332b1c;color:#f2cd73}
.alarm-bar.critical{border-color:#a34e43;background:#351f1d;color:#ff9b89}
.pump-board{margin-top:16px;padding:22px 24px;background:#1c3029;border:1px solid #385046;border-radius:8px}
.pump-board h2{margin-bottom:14px}
.pump-table{width:100%;border-collapse:collapse;font:14px Arial,sans-serif}
.pump-table th,.pump-table td{padding:10px 8px;text-align:left;border-bottom:1px solid #385046}
.pump-table th{color:#9eafa5;font-size:12px;font-weight:600}
.pump-state{font-weight:700}.pump-state.on{color:#a7d879}.pump-state.off{color:#a9b8b0}
.expected-runtime{color:#c2d0c8}
@media(max-width:850px){.readings{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:640px){body{padding:20px}.readings{grid-template-columns:1fr;gap:12px}article{min-height:220px;padding:24px;gap:18px}.value{font-size:76px}header{align-items:start;flex-direction:column;margin-bottom:18px}#sensor-state{text-align:left}.ventilation,.lighting,.pump-board{padding:18px}.fan-channels{grid-template-columns:repeat(3,minmax(0,1fr))}.ventilation-header,.lighting-header{align-items:flex-start;flex-direction:column}.pump-table th,.pump-table td{padding:9px 4px;font-size:12px}}
</style>
</head>
<body>
<main>
<header><div><div class="eyebrow">Terrarium climate</div><h1>Live readings</h1></div><div id="sensor-state" role="status" aria-live="polite">Waiting for sensor data</div></header>
<div class="climate-strip"><div class="climate-chip">Season<strong id="season-status">--</strong></div><div class="climate-chip">Period<strong id="period-status">--</strong></div><div class="climate-chip">Targets<strong id="climate-targets">--</strong></div></div>
<div id="alarm-bar" class="alarm-bar warning" role="status" aria-live="assertive">Checking alarm status...</div>
<div class="readings">
<article><h2>Air temperature</h2><div class="value"><span id="temperature">--</span><span class="unit">&#176;C</span></div><div class="sensor-breakdown"><div><span class="sensor-label">L</span><span class="sensor-value" id="temperature-left">--</span><span class="sensor-unit">&#176;C</span></div><div><span class="sensor-label">M</span><span class="sensor-value" id="temperature-middle">--</span><span class="sensor-unit">&#176;C</span></div><div><span class="sensor-label">R</span><span class="sensor-value" id="temperature-right">--</span><span class="sensor-unit">&#176;C</span></div></div></article>
<article class="water"><h2>Aquarium temperature</h2><div class="value"><span id="aquarium-temperature">--</span><span class="unit">&#176;C</span></div></article>
<article class="humidity"><h2>Humidity</h2><div class="value"><span id="humidity">--</span><span class="unit">%</span></div><div class="sensor-breakdown"><div><span class="sensor-label">L</span><span class="sensor-value" id="humidity-left">--</span><span class="sensor-unit">%</span></div><div><span class="sensor-label">M</span><span class="sensor-value" id="humidity-middle">--</span><span class="sensor-unit">%</span></div><div><span class="sensor-label">R</span><span class="sensor-value" id="humidity-right">--</span><span class="sensor-unit">%</span></div></div></article>
</div>
<section class="ventilation" aria-labelledby="ventilation-title">
<div class="ventilation-header"><h2 id="ventilation-title">Ventilation</h2><div id="fan-state" role="status" aria-live="polite">Waiting for fan command</div></div>
<p id="fan-sequence" class="ventilation-sequence">Minimum airflow sequence: F1 -&gt; F6 -&gt; F1</p>
<div class="fan-channels"><div class="fan-channel" id="fan-1"><span>F1</span><span class="fan-level" id="fan-1-level">--</span></div><div class="fan-channel" id="fan-2"><span>F2</span><span class="fan-level" id="fan-2-level">--</span></div><div class="fan-channel" id="fan-3"><span>F3</span><span class="fan-level" id="fan-3-level">--</span></div><div class="fan-channel" id="fan-4"><span>F4</span><span class="fan-level" id="fan-4-level">--</span></div><div class="fan-channel" id="fan-5"><span>F5</span><span class="fan-level" id="fan-5-level">--</span></div><div class="fan-channel" id="fan-6"><span>F6</span><span class="fan-level" id="fan-6-level">--</span></div></div>
</section>
<section class="lighting" aria-labelledby="lighting-title">
<div class="lighting-header"><h2 id="lighting-title">Lighting</h2><div id="light-state" role="status" aria-live="polite">Waiting for lighting command</div></div>
<p id="lighting-sequence" class="lighting-sequence">Dawn 05:45: LED2 -&gt; LED2+3 -&gt; all four over 20 min. Dusk 18:15: fade to off over 20 min.</p>
<div class="led-channels"><div class="led-channel" id="led-1"><span>LED1</span><span class="led-level" id="led-1-level">--</span></div><div class="led-channel" id="led-2"><span>LED2</span><span class="led-level" id="led-2-level">--</span></div><div class="led-channel" id="led-3"><span>LED3</span><span class="led-level" id="led-3-level">--</span></div><div class="led-channel" id="led-4"><span>LED4</span><span class="led-level" id="led-4-level">--</span></div></div>
</section>
<section class="pump-board" aria-labelledby="pump-board-title">
<h2 id="pump-board-title">Pump status</h2>
<table class="pump-table"><thead><tr><th>Output</th><th>Status</th><th>Expected runtime</th></tr></thead><tbody>
<tr id="pump-do4"><td>DO4 Rain</td><td class="pump-state" id="pump-do4-state">--</td><td class="expected-runtime" id="pump-do4-runtime">Up to 60 s</td></tr>
<tr id="pump-do5"><td>DO5 Mist</td><td class="pump-state" id="pump-do5-state">--</td><td class="expected-runtime" id="pump-do5-runtime">10 min after scheduled rain</td></tr>
<tr id="pump-do10"><td>DO10 Waterfall</td><td class="pump-state" id="pump-do10-state">--</td><td class="expected-runtime" id="pump-do10-runtime">--</td></tr>
<tr id="pump-do11"><td>DO11 Orchid dripper</td><td class="pump-state" id="pump-do11-state">--</td><td class="expected-runtime" id="pump-do11-runtime">--</td></tr>
<tr id="pump-do12"><td>DO12 Aquarium refill</td><td class="pump-state" id="pump-do12-state">--</td><td class="expected-runtime" id="pump-do12-runtime">While DI1 active</td></tr>
<tr id="pump-do15"><td>DO15 RO valve</td><td class="pump-state" id="pump-do15-state">--</td><td class="expected-runtime" id="pump-do15-runtime">While DI0 active</td></tr>
</tbody></table>
</section>
</main>
<script>
const temperature=document.querySelector('#temperature');
const humidity=document.querySelector('#humidity');
const aquariumTemperature=document.querySelector('#aquarium-temperature');
const sensorState=document.querySelector('#sensor-state');
const fanState=document.querySelector('#fan-state');
const fanSequence=document.querySelector('#fan-sequence');
const lightState=document.querySelector('#light-state');
const lightingSequence=document.querySelector('#lighting-sequence');
const seasonStatus=document.querySelector('#season-status');
const periodStatus=document.querySelector('#period-status');
const climateTargets=document.querySelector('#climate-targets');
const alarmBar=document.querySelector('#alarm-bar');
const fanChannels=Array.from({length:6},(_,index)=>({
 element:document.querySelector(`#fan-${index+1}`),
 level:document.querySelector(`#fan-${index+1}-level`)
}));
const ledChannels=Array.from({length:4},(_,index)=>({
 element:document.querySelector(`#led-${index+1}`),
 level:document.querySelector(`#led-${index+1}-level`)
}));
const sensorReadings={
 temperature_left:document.querySelector('#temperature-left'),
 temperature_top:document.querySelector('#temperature-middle'),
 temperature_right:document.querySelector('#temperature-right'),
 humidity_left:document.querySelector('#humidity-left'),
 humidity_top:document.querySelector('#humidity-middle'),
 humidity_right:document.querySelector('#humidity-right')
};
function averageReading(sensors,prefix){
 const readings=Object.entries(sensors||{}).filter(([name,value])=>name.startsWith(prefix)&&typeof value==='number'&&Number.isFinite(value)).map(([,value])=>value);
 return readings.length?readings.reduce((sum,value)=>sum+value,0)/readings.length:null;
}
function showReading(element,value){element.textContent=value===null?'--':value.toFixed(1);}
function showFanStatus(commands){
 const command=commands?.['esp32/cmd/fans'];
 if(!command){fanState.textContent='Fan command unavailable';fanSequence.textContent='Minimum airflow sequence unavailable';return;}
 const channels=command.channels||{};
 const minimum=command.minimum_airflow||{};
 const activeFan=Number(minimum.active_fan);
 fanChannels.forEach(({element,level},index)=>{
    const fanNumber=index+1,value=channels[`fan${fanNumber}`];
    level.textContent=typeof value==='number'&&Number.isFinite(value)?`${value}%`:'--';
    element.classList.toggle('sequence-active',command.mode==='auto'&&minimum.enabled===true&&fanNumber===activeFan);
 });
 fanState.textContent=`${command.mode==='manual'?'Manual':'Automatic'} · ${typeof command.level==='number'?`${command.level}%`:''}`.trim();
 fanSequence.textContent=minimum.enabled===true&&command.mode==='auto'
    ?`Minimum airflow: F1 -> F6 -> F1, switches every 60 s. Active: F${activeFan} at ${minimum.percent}%`
    :minimum.enabled===true?'Minimum airflow sequence paused during manual control':'Minimum airflow sequence disabled';
}
function showLightingStatus(commands){
 const command=commands?.['esp32/cmd/lights'];
 if(!command){lightState.textContent='Lighting command unavailable';lightingSequence.textContent='Lighting sequence unavailable';return;}
 const leds=command.leds||{};
 ledChannels.forEach(({element,level},index)=>{
    const brightness=leds[`led${index+1}`];
    level.textContent=typeof brightness==='number'&&Number.isFinite(brightness)?`${brightness}%`:'--';
    element.classList.toggle('active',typeof brightness==='number'&&brightness>0);
 });
 const mode=command.mode==='manual'?'Manual':'Automatic';
 const state=command.state==='on'?'On':'Off';
 lightState.textContent=`${mode} · ${state} · ${typeof command.brightness==='number'?`${command.brightness}%`:''}`.trim();
 lightingSequence.textContent=command.mode==='manual'
    ?'Day/night sequence paused during manual control.'
    :'Dawn 05:45: LED2 -> LED2+3 -> all four over 20 min. Dusk 18:15: fade to off over 20 min.';
}
function showOperationalStatus(status){
 const climate=status.climate||{};
 seasonStatus.textContent=climate.season||'Unknown';
 periodStatus.textContent=climate.period||'Unknown';
 climateTargets.textContent=typeof climate.temperature_target==='number'&&typeof climate.humidity_target==='number'
    ?`${climate.temperature_target.toFixed(1)} C / ${climate.humidity_target.toFixed(0)}% RH`
    :'--';

 const alarms=status.alarms||{};
 const messages=Array.isArray(alarms.messages)?alarms.messages:[];
 alarmBar.className=`alarm-bar ${alarms.severity||'warning'}`;
 alarmBar.textContent=messages.length?messages.join(' · '):'No active alarms';

 const commands=status.commands?.['moxa/cmd/output']||{};
 const feedback=status.moxa?.outputs||{};
 const rows=[4,5,10,11,12,15];
 for(const output of rows){
    const channel=`DO@DO-${String(output).padStart(2,'0')}`;
    const value=feedback[channel];
    const state=value===0||value===1||typeof value==='boolean'
     ?(Boolean(value)?'ON':'OFF')
     :(commands[`do${output}`]||'--');
    const stateElement=document.querySelector(`#pump-do${output}-state`);
    stateElement.textContent=state;
    stateElement.classList.toggle('on',state==='ON');
    stateElement.classList.toggle('off',state==='OFF');
 }

 const pumpSchedules=status.pump_schedule||{};
 for(const output of [10,11]){
    const pump=pumpSchedules[`do${output}`];
    const runtime=document.querySelector(`#pump-do${output}-runtime`);
    if(!pump){runtime.textContent='Schedule unavailable';continue;}
    if(!pump.enabled){runtime.textContent=`Disabled · ${pump.duration_seconds}s / ${pump.cycle_minutes} min configured`;continue;}
    const remaining=Number(pump.remaining_run_seconds||0);
    const next=Number(pump.next_run_seconds);
    const timing=remaining>0?`${Math.ceil(remaining)} s remaining`:Number.isFinite(next)?`next in ${Math.ceil(next/60)} min`:'';
    runtime.textContent=`${pump.duration_seconds} s every ${pump.cycle_minutes} min${timing?` · ${timing}`:''}`;
 }
}
async function refresh(){
 try{
  const response=await fetch('/api/status',{cache:'no-store'});
  if(!response.ok)throw new Error('Status request failed');
  const status=await response.json();
    showOperationalStatus(status);
    showFanStatus(status.commands);
    showLightingStatus(status.commands);
  const sensors=status.esp32?.sensors||{};
  const temperatureValue=averageReading(sensors,'temperature_');
  const humidityValue=averageReading(sensors,'humidity_');
    const aquariumValue=typeof sensors.aquarium_temp==='number'&&Number.isFinite(sensors.aquarium_temp)?sensors.aquarium_temp:null;
  showReading(temperature,temperatureValue);
  showReading(humidity,humidityValue);
    showReading(aquariumTemperature,aquariumValue);
    for(const [name,element] of Object.entries(sensorReadings))showReading(element,typeof sensors[name]==='number'&&Number.isFinite(sensors[name])?sensors[name]:null);
    const hasReadings=temperatureValue!==null||humidityValue!==null||aquariumValue!==null;
    const lastSeen=Number(status.esp32?.last_sensor_seen??status.esp32?.last_seen);
    const staleAfter=Number(status.climate?.sensor_stale_timeout_seconds??360);
    const stale=!Number.isFinite(lastSeen)||Date.now()/1000-lastSeen>staleAfter;
  sensorState.classList.toggle('offline',!hasReadings||stale);
  sensorState.textContent=!hasReadings?'Waiting for sensor data':stale?'Sensor data is stale':'Updated '+new Date(lastSeen*1000).toLocaleTimeString();
 }catch{
    alarmBar.className='alarm-bar critical';
    alarmBar.textContent='Pi status unavailable';
    showFanStatus(null);
    showLightingStatus(null);
  showReading(temperature,null);
  showReading(humidity,null);
    showReading(aquariumTemperature,null);
    for(const element of Object.values(sensorReadings))showReading(element,null);
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