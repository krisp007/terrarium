"""Small local status dashboard for the terrarium MQTT service."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional


class StatusStore:
    """Thread-safe snapshot of the latest system and hardware status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
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

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._status))


HTML = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terrarium status</title><style>
body{font:16px system-ui,sans-serif;background:#eef2ed;color:#18221c;margin:0;padding:24px}
main{max-width:1100px;margin:auto}h1{margin-top:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
section{background:white;border:1px solid #cbd6cc;border-radius:8px;padding:16px;box-shadow:0 2px 8px #18221c12}
h2{font-size:1.05rem;margin:0 0 12px}.ok{color:#137333}.bad{color:#b3261e}dl{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin:0}dt{color:#5d6b61}dd{margin:0;text-align:right;font-weight:600;overflow-wrap:anywhere}
small{color:#5d6b61}pre{white-space:pre-wrap;margin:0;font-size:.82rem}
</style></head><body><main><h1>Terrarium status</h1><small id="updated">Laden...</small><div class="grid" id="cards"></div></main>
<script>
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function entries(obj){return Object.entries(obj||{}).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(typeof v==='object'?JSON.stringify(v):v)}</dd>`).join('')}
function card(title,data){let status=data.status||'';let cls=['online','connected','ok','normal'].includes(status)?'ok':(['offline','disconnected','alarm'].includes(status)?'bad':'');return `<section><h2>${esc(title)} <span class="${cls}">${esc(status)}</span></h2><dl>${entries(data)}</dl></section>`}
async function refresh(){try{let r=await fetch('/api/status',{cache:'no-store'});let d=await r.json();document.querySelector('#cards').innerHTML=card('Pi service',d.service)+card('MQTT',d.mqtt)+card('ESP32',d.esp32)+card('Moxa',d.moxa)+card('Laatste commando\'s',d.commands);document.querySelector('#updated').textContent='Bijgewerkt: '+new Date().toLocaleTimeString();}catch(e){document.querySelector('#updated').textContent='Dashboard niet bereikbaar';}}
refresh();setInterval(refresh,3000);
</script></body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    store: StatusStore

    def do_GET(self) -> None:
        if self.path == "/api/status":
            body = json.dumps(self.store.snapshot()).encode("utf-8")
            content_type = "application/json"
        elif self.path == "/":
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

    def log_message(self, *_args: object) -> None:
        return


def start_dashboard(store: StatusStore, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    handler = type("TerrariumDashboardHandler", (DashboardHandler,), {"store": store})
    server = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, name="status-dashboard", daemon=True).start()
    return server