"use client";

import { useEffect, useMemo, useState } from "react";

type Status = {
  service?: Record<string, unknown>;
  mqtt?: Record<string, unknown>;
  esp32?: { status?: string; sensors?: Record<string, number | null>; ip?: string; last_seen?: number };
  moxa?: { status?: string; inputs?: Record<string, number>; outputs?: Record<string, number>; last_seen?: number };
  commands?: Record<string, Record<string, unknown>>;
};
type HistoryItem = { timestamp: number; source: string; topic?: string; values: Record<string, unknown> };

const formatValue = (value: number | null | undefined, unit = "") => value == null ? "--" : `${value.toFixed(1)}${unit}`;
const active = (value: unknown) => value === 1 || value === "ON" || value === true;

export default function Home() {
  const [status, setStatus] = useState<Status>({});
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [now, setNow] = useState(new Date());
  const [error, setError] = useState("");

  useEffect(() => {
    const refresh = async () => {
      try {
        const [statusResponse, historyResponse] = await Promise.all([fetch("/api/status", { cache: "no-store" }), fetch("/api/history", { cache: "no-store" })]);
        if (!statusResponse.ok) throw new Error("Pi API offline");
        setStatus(await statusResponse.json());
        if (historyResponse.ok) setHistory(await historyResponse.json());
        setError("");
      } catch (refreshError) {
        setError(refreshError instanceof Error ? refreshError.message : "Dashboard offline");
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    return () => { window.clearInterval(timer); window.clearInterval(clock); };
  }, []);

  const sensors = status.esp32?.sensors ?? {};
  const outputs = status.moxa?.outputs ?? {};
  const recentHistory = useMemo(() => history.slice(0, 18), [history]);
  const online = status.service?.status === "online" && status.mqtt?.status === "connected";

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">◒</div><div><h1>TerraControl</h1><p>Costa Rica rainforest</p></div></div>
      <nav className="nav"><button className="active">◈ Overview</button><button>◌ Climate schedule</button><button>⌁ History</button><button>⚙ System</button></nav>
      <div className="sidebar-footer"><span className="live-dot" />{online ? "Local control online" : "Connection check required"}<br /><span>Pi · MQTT · Moxa · ESP32</span></div>
    </aside>
    <main className="main">
      <header className="topbar"><div><div className="eyebrow">Live terrarium control</div><h2>Rainforest overview</h2><p>System state, climate readings and actuator feedback.</p></div><div className="clock">{now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}<br /><small>Pi local time</small></div></header>
      {error && <div className="card" style={{ borderColor: "var(--red)", marginBottom: 16 }}>Dashboard connection: {error}</div>}
      <div className="grid">
        <section className="card span-3"><h3>Temperature</h3><div className="metric">{formatValue(sensors.temperature_top, "°C")}</div><div className="label">Top sensor</div></section>
        <section className="card span-3"><h3>Humidity</h3><div className="metric">{formatValue(sensors.humidity_top, "%")}</div><div className="label">Top sensor</div></section>
        <section className="card span-3"><h3>Soil moisture</h3><div className="metric">{formatValue(sensors.soil_left, "%")}</div><div className="label">Left zone</div></section>
        <section className="card span-3"><h3>Water temperature</h3><div className="metric">{formatValue(sensors.aquarium_temp, "°C")}</div><div className="label">DS18B20</div></section>

        <section className="card span-8"><h3>Sensor field</h3><div className="sensor-grid">
          <div className="sensor"><span>Top temperature</span><strong>{formatValue(sensors.temperature_top, "°C")}</strong></div><div className="sensor blue"><span>Top humidity</span><strong>{formatValue(sensors.humidity_top, "%")}</strong></div><div className="sensor amber"><span>Left soil</span><strong>{formatValue(sensors.soil_left, "%")}</strong></div>
          <div className="sensor"><span>Left temperature</span><strong>{formatValue(sensors.temperature_left, "°C")}</strong></div><div className="sensor blue"><span>Left humidity</span><strong>{formatValue(sensors.humidity_left, "%")}</strong></div><div className="sensor amber"><span>Right soil</span><strong>{formatValue(sensors.soil_right, "%")}</strong></div>
        </div></section>
        <section className="card span-4"><h3>System health</h3><div className="status-row"><span>Pi service</span><span className="pill">{String(status.service?.status ?? "unknown")}</span></div><div className="status-row"><span>MQTT broker</span><span className="pill">{String(status.mqtt?.status ?? "unknown")}</span></div><div className="status-row"><span>ESP32</span><span className={`pill ${status.esp32?.status === "online" ? "" : "warn"}`}>{status.esp32?.status ?? "unknown"}</span></div><div className="status-row"><span>Moxa ioThinx</span><span className={`pill ${status.moxa?.status === "online" ? "" : "warn"}`}>{status.moxa?.status ?? "unknown"}</span></div></section>

        <section className="card span-6"><h3>Moxa outputs</h3>{[0,1,2,3,4,5,6].map((output) => { const key = `DO@DO-${String(output).padStart(2, "0")}`; return <div className="status-row" key={key}><span>DO{String(output).padStart(2, "0")} {output < 4 ? "Lamp" : output === 5 ? "Mistmaker" : output === 6 ? "Warmtelamp" : "Irrigation"}</span><span className={`pill ${active(outputs[key]) ? "" : "off"}`}>{active(outputs[key]) ? "ON" : "OFF"}</span></div>; })}</section>
        <section className="card span-6"><h3>Recent history</h3><div className="history">{recentHistory.length ? recentHistory.map((item, index) => <div className="history-row" key={`${item.timestamp}-${index}`}><span>{new Date(item.timestamp * 1000).toLocaleTimeString("en-GB")}</span><strong>{item.source}</strong><code>{JSON.stringify(item.values)}</code></div>) : <div className="empty">No history available yet.</div>}</div></section>
      </div>
    </main>
  </div>;
}
