"use client";

import { useEffect, useState } from "react";
import { Activity, Wifi, WifiOff } from "lucide-react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type View = "dashboard" | "schedule" | "overrides";
type Season = "dry" | "rainy";
type Profile = {
  season: Season;
  tempDay: [number, number];
  tempNight: [number, number];
  humidityDay: [number, number];
  humidityNight: [number, number];
  soil: [number, number];
  led: number[];
  fanDay: number;
  fanNight: number;
  humidityBoost: number;
  mistFrequency: number;
  mistDuration: number;
  atomizerFrequency: number;
  atomizerDuration: number;
  sunrise: string;
  sunset: string;
  rainSimulation: boolean;
};
type Actor = { id: string; name: string; type: string; icon: string; mode: "auto" | "manual"; pendingMode?: "auto" | "manual"; state: boolean; currentState: boolean; intensity?: number; overrideExpiresAt?: number };
type HistoryItem = { timestamp: number; source: string; values: Record<string, unknown> };

const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const shortMonths = months.map((month) => month.slice(0, 3));
const dryMonths = new Set([0, 1, 2, 3, 11]);

const makeProfile = (month: number): Profile => {
  const rainy = !dryMonths.has(month);
  return {
    season: rainy ? "rainy" : "dry",
    tempDay: rainy ? [26, 30] : [28, 32], tempNight: rainy ? [22, 26] : [24, 28],
    humidityDay: rainy ? [80, 90] : [60, 70], humidityNight: rainy ? [85, 95] : [55, 65],
    soil: rainy ? [55, 70] : [40, 50], led: rainy ? [70, 70, 50, 50] : [90, 90, 70, 70],
    fanDay: rainy ? 55 : 40, fanNight: rainy ? 35 : 25, humidityBoost: rainy ? 80 : 70,
    mistFrequency: rainy ? 60 : 180, mistDuration: rainy ? 40 : 15, atomizerFrequency: rainy ? 90 : 240, atomizerDuration: rainy ? 25 : 10,
    sunrise: rainy ? "05:00" : "06:00", sunset: "18:00", rainSimulation: rainy,
  };
};

const initialActors: Actor[] = [
  ...Array.from({ length: 6 }, (_, index) => ({ id: `fan-${index + 1}`, name: `Fan ${index + 1}`, type: "Fan", icon: "◉", mode: "auto" as const, state: false, currentState: false, intensity: 50 })),
  ...["LED 1", "LED 2", "LED 3", "LED 4"].map((name, index) => ({ id: `led-${index + 1}`, name, type: "LED", icon: "✦", mode: "auto" as const, state: false, currentState: false, intensity: 70 })),
  { id: "heat-lamp", name: "Heat Lamp", type: "Heat Lamp", icon: "☼", mode: "auto" as const, state: false, currentState: false },
  { id: "mistmaker", name: "Mist Maker", type: "Mist Maker", icon: "≋", mode: "auto" as const, state: false, currentState: false }, { id: "atomizer", name: "Atomizer", type: "Atomizer", icon: "◌", mode: "auto" as const, state: false, currentState: false },
  { id: "irrigation", name: "Irrigation Pump", type: "Pump", icon: "↯", mode: "auto" as const, state: false, currentState: false }, { id: "fill-mist", name: "Mist Reservoir Pump", type: "Pump", icon: "↯", mode: "auto" as const, state: false, currentState: false },
  { id: "fill-irrigation", name: "Irrigation Reservoir Pump", type: "Pump", icon: "↯", mode: "auto" as const, state: false, currentState: false }, { id: "waterfall", name: "Waterfall Pump", type: "Pump", icon: "↯", mode: "auto" as const, state: false, currentState: false },
];

function RangeCard({ label, values, unit, onChange, editing, min = 0, max = 100 }: { label: string; values: [number, number]; unit: string; onChange: (value: [number, number]) => void; editing: boolean; min?: number; max?: number }) {
  return <div className="setting-card"><span>{label}</span>{editing ? <div className="range-inputs"><input className="number-input" type="number" min={min} max={max} value={values[0]} onChange={(event) => onChange([Number(event.target.value), values[1]])} /><b>-</b><input className="number-input" type="number" min={min} max={max} value={values[1]} onChange={(event) => onChange([values[0], Number(event.target.value)])} /><em>{unit}</em></div> : <strong className="range-value">{values[0]} - {values[1]}{unit}</strong>}</div>;
}

function ScheduleView({ month, setMonth }: { month: number; setMonth: (month: number) => void }) {
  const [profiles, setProfiles] = useState<Record<number, Profile>>(() => Object.fromEntries(months.map((_, index) => [index, makeProfile(index)])));
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    fetch("/api/schedule", { cache: "no-store" })
      .then((response) => response.json())
      .then((payload: { profiles?: Record<string, Profile> }) => {
        const storedProfiles = payload.profiles;
        if (storedProfiles && Object.keys(storedProfiles).length > 0) {
          setProfiles((current) => ({ ...current, ...Object.fromEntries(Object.entries(storedProfiles).map(([key, value]) => [Number(key), value])) }));
        }
      })
      .catch(() => undefined);
  }, []);
  const profile = profiles[month];
  const update = <K extends keyof Profile>(key: K, value: Profile[K]) => setProfiles((current) => ({ ...current, [month]: { ...current[month], [key]: value } }));
  const updateLed = (index: number, value: number) => update("led", profile.led.map((entry, ledIndex) => ledIndex === index ? value : entry));
  const saveProfiles = async () => {
    await fetch("/api/schedule", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profiles }) });
    setEditing(false);
  };
  return <div className="workspace"><div className="month-tabs">{shortMonths.map((name, index) => <button key={name} className={month === index ? "selected" : ""} onClick={() => { setMonth(index); setEditing(false); }}><span>{name}</span><i className={profiles[index].season} /></button>)}</div>
    <section className={`profile-header ${profile.season}`}><div><span className="section-kicker">Monthly climate profile</span><h2>▣ {months[month]}</h2>{editing ? <select className="season-select" value={profile.season} onChange={(event) => update("season", event.target.value as Season)}><option value="dry">Dry Season</option><option value="rainy">Rainy Season</option></select> : <span className={`season-badge ${profile.season}`}>{profile.season === "dry" ? "Dry Season" : "Rainy Season"}</span>}</div><button className="button pale" onClick={() => editing ? void saveProfiles() : setEditing(true)}>{editing ? "Save Profile" : "Edit"}</button></section>
    <div className="profile-grid"><div className="column"><h3>♨ Temperature Settings</h3><RangeCard label="☼ Day Range" values={profile.tempDay} unit="°C" min={10} max={40} editing={editing} onChange={(value) => update("tempDay", value)} /><RangeCard label="☾ Night Range" values={profile.tempNight} unit="°C" min={10} max={40} editing={editing} onChange={(value) => update("tempNight", value)} /><RangeCard label="Soil Moisture Target" values={profile.soil} unit="%" editing={editing} onChange={(value) => update("soil", value)} /><h3>♧ Humidity Settings</h3><RangeCard label="☼ Day Range" values={profile.humidityDay} unit="%" editing={editing} onChange={(value) => update("humidityDay", value)} /><RangeCard label="☾ Night Range" values={profile.humidityNight} unit="%" editing={editing} onChange={(value) => update("humidityNight", value)} /></div>
      <div className="column"><h3>✦ LED Dimming</h3><div className="led-grid">{["LED 1", "LED 2", "LED 3", "LED 4"].map((label, index) => <label className="slider-card" key={label}><span>{label}<b>{profile.led[index]}%</b></span><input type="range" min="0" max="100" value={profile.led[index]} onChange={(event) => updateLed(index, Number(event.target.value))} disabled={!editing} /></label>)}</div><label className="checkbox-row"><input type="checkbox" checked={profile.rainSimulation} onChange={(event) => update("rainSimulation", event.target.checked)} disabled={!editing} /> Rain simulation mode</label><h3>◷ Schedule</h3><div className="schedule-fields"><label>Sunrise<input type="time" value={profile.sunrise} onChange={(event) => update("sunrise", event.target.value)} disabled={!editing} /></label><label>Sunset<input type="time" value={profile.sunset} onChange={(event) => update("sunset", event.target.value)} disabled={!editing} /></label></div></div>
      <div className="column"><h3>≋ Fan Speed Profiles</h3>{([["Day Speed", "fanDay"], ["Night Speed", "fanNight"], ["High Humidity Boost", "humidityBoost"]] as const).map(([label, key]) => <label className="slider-card" key={key}><span>{label}<b>{profile[key]}%</b></span><input type="range" min="0" max="100" value={profile[key]} onChange={(event) => update(key, Number(event.target.value))} disabled={!editing} /></label>)}<h3>≋ Misting Settings</h3><div className="mini-grid"><label><span>Mist Frequency</span>{editing ? <input className="number-input" type="number" min="1" value={profile.mistFrequency} onChange={(event) => update("mistFrequency", Number(event.target.value))} /> : <strong>{profile.mistFrequency} min</strong>}</label><label><span>Mist Duration</span>{editing ? <input className="number-input" type="number" min="1" value={profile.mistDuration} onChange={(event) => update("mistDuration", Number(event.target.value))} /> : <strong>{profile.mistDuration} sec</strong>}</label><label><span>Atomizer Frequency</span>{editing ? <input className="number-input" type="number" min="1" value={profile.atomizerFrequency} onChange={(event) => update("atomizerFrequency", Number(event.target.value))} /> : <strong>{profile.atomizerFrequency} min</strong>}</label><label><span>Atomizer Duration</span>{editing ? <input className="number-input" type="number" min="1" value={profile.atomizerDuration} onChange={(event) => update("atomizerDuration", Number(event.target.value))} /> : <strong>{profile.atomizerDuration} sec</strong>}</label></div></div></div>
  </div>;
}

function ActorCard({ actor, onUpdate }: { actor: Actor; onUpdate: (actor: Actor) => void }) {
  const [duration, setDuration] = useState(60);
  const sendOverride = async (next: Actor, mode: "auto" | "manual") => {
    const response = await fetch("/api/override", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_type: next.type, actor_name: next.id, mode, state: next.state, intensity: next.intensity ?? 100, duration_minutes: duration }) });
    if (!response.ok) throw new Error("Override request failed");
    const result = await response.json() as { expires_at?: number };
    let applied = { ...next, pendingMode: undefined, overrideExpiresAt: result.expires_at };
    if (mode === "auto") {
      const statusResponse = await fetch("/api/status", { cache: "no-store" });
      if (statusResponse.ok) {
        applied = { ...applied, currentState: currentActorState(next, await statusResponse.json() as RuntimeStatus) };
      }
    }
    onUpdate(applied);
  };
  const selectedMode = actor.pendingMode ?? actor.mode;
  const manual = selectedMode === "manual";
  return <article className={`actor-card ${actor.currentState ? "is-on" : ""}`}><div className="actor-heading"><div className="actor-icon">{actor.icon}</div><div><strong>{actor.name}</strong><span>{actor.type}</span></div><i className={actor.currentState ? "state-dot on" : "state-dot"} /></div><div className="current-state"><span>Current state</span><b className={actor.currentState ? "state-on" : "state-off"}>{actor.currentState ? "ON" : "OFF"}</b></div><div className="mode-switch"><span>Control mode</span><div><button className={selectedMode === "auto" ? "selected" : ""} onClick={() => onUpdate({ ...actor, pendingMode: "auto" })}>Auto</button><button className={selectedMode === "manual" ? "selected" : ""} onClick={() => onUpdate({ ...actor, pendingMode: "manual", state: actor.currentState })}>Manual</button></div></div>{manual && <><div className="actor-control"><span>Manual power</span><button className={`switch ${actor.state ? "on" : ""}`} aria-label={`${actor.name} manual power`} onClick={() => onUpdate({ ...actor, state: !actor.state })}><i /></button></div>{actor.intensity !== undefined && <label className="intensity"><span>Intensity: <b>{actor.intensity}%</b></span><input type="range" min="0" max="100" value={actor.intensity} onChange={(event) => onUpdate({ ...actor, intensity: Number(event.target.value) })} /></label>}<label className="duration">Override duration<select value={duration} onChange={(event) => setDuration(Number(event.target.value))}><option value="30">30 minutes</option><option value="60">1 hour</option><option value="120">2 hours</option><option value="240">4 hours</option></select></label><button className="button override" onClick={() => void sendOverride({ ...actor, mode: "manual", currentState: actor.state }, "manual")}>◉ Apply Override</button>{actor.overrideExpiresAt && <small className="override-expiry">Ends {new Date(actor.overrideExpiresAt * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</small>}</>}{actor.pendingMode === "auto" && <button className="button override auto-apply" onClick={() => void sendOverride({ ...actor, mode: "auto", state: actor.currentState }, "auto")}>↶ Apply Auto</button>}</article>;
}

function OverridesView({ actors, setActors }: { actors: Actor[]; setActors: (actors: Actor[]) => void }) {
  const groups = ["Fan", "LED", "Heat Lamp", "Mist Maker", "Atomizer", "Pump"];
  const update = (next: Actor) => setActors(actors.map((actor) => actor.id === next.id ? next : actor));
  return <div className="workspace"><div className="override-intro"><div><span className="section-kicker">Manual control</span><h2>Actor Overrides</h2><p>Manual overrides take precedence over automatic climate control until they expire or are returned to Auto.</p></div><div className="override-count">{actors.filter((actor) => actor.mode === "manual").length}<span>active overrides</span></div></div>{groups.map((group) => <section className="actor-group" key={group}><h3>{group}s</h3><div className="actor-grid">{actors.filter((actor) => actor.type === group).map((actor) => <ActorCard key={actor.id} actor={actor} onUpdate={update} />)}</div></section>)}</div>;
}

type RuntimeStatus = {
  service?: { status?: string };
  mqtt?: { status?: string };
  esp32?: { status?: string; sensors?: Record<string, number | null> };
  moxa?: { status?: string; outputs?: Record<string, unknown> };
  commands?: Record<string, Record<string, unknown>>;
};

function isActive(value: unknown): boolean {
  return value === true || value === "ON" || Number(value) > 0;
}

function currentActorState(actor: Actor, status: RuntimeStatus): boolean {
  const fanCommand = status.commands?.["esp32/cmd/fans"] ?? {};
  const fanChannels = (fanCommand.channels ?? {}) as Record<string, unknown>;
  if (actor.type === "Fan") {
    const fanNumber = actor.id.split("-")[1];
    return isActive(fanChannels[`fan${fanNumber}`] ?? (Number(fanNumber) >= 2 && Number(fanNumber) <= 5 ? fanCommand.level : 0));
  }
  if (actor.type === "LED") {
    const lights = status.commands?.["esp32/cmd/lights"] ?? {};
    const leds = (lights.leds ?? {}) as Record<string, unknown>;
    return isActive(leds[`led${actor.id.split("-")[1]}`]);
  }
  const outputs = (status.moxa?.outputs ?? status.commands?.["moxa/cmd/output"] ?? {}) as Record<string, unknown>;
  if (actor.type === "Heat Lamp") return isActive(outputs.do6 ?? outputs["DO@DO-06"]);
  if (actor.type === "Mist Maker" || actor.type === "Atomizer") return isActive(outputs.do5 ?? outputs["DO@DO-05"]);
  if (actor.type === "Pump") {
    const output = { "fill-mist": "do4", "fill-irrigation": "do5", waterfall: "do7", irrigation: "do4" }[actor.id];
    return isActive(output ? outputs[output] ?? outputs[`DO@DO-${output.slice(2).padStart(2, "0")}`] : false);
  }
  return actor.currentState;
}

function currentOverride(actor: Actor, status: RuntimeStatus): { mode: "auto" | "manual"; expiresAt?: number } {
  const topic = actor.type === "Fan" ? "esp32/cmd/fans" : actor.type === "LED" ? "esp32/cmd/lights" : "moxa/cmd/output";
  const command = status.commands?.[topic] ?? {};
  const overrides = (command.overrides ?? {}) as Record<string, unknown>;
  const outputKeys: Record<string, string> = { "heat-lamp": "do6", mistmaker: "do5", atomizer: "do5", "fill-mist": "do4", "fill-irrigation": "do5", waterfall: "do7", irrigation: "do4" };
  const key = actor.type === "Fan" ? actor.id.replace("-", "") : actor.type === "LED" ? actor.id.replace("-", "") : outputKeys[actor.id] ?? actor.id;
  const expiry = overrides[key];
  return expiry !== undefined ? { mode: "manual", expiresAt: typeof expiry === "number" ? expiry : undefined } : { mode: "auto", expiresAt: undefined };
}

function TrendGraph({ history }: { history: HistoryItem[] }) {
  const readings = history.filter((item) => item.source === "esp32_sensors").slice(0, 96).reverse();
  const chartData = readings.map((item, index) => ({
    label: new Date(item.timestamp * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }),
    temperature: Number(item.values.temperature_top),
    humidity: Number(item.values.humidity_top),
    index,
  })).filter((item) => Number.isFinite(item.temperature) || Number.isFinite(item.humidity));
  return <article className="dashboard-panel trend-graph"><div className="trend-graph-heading"><h2><Activity size={17} /> 24-Hour Trends</h2><span>{readings.length ? `${readings.length} readings` : "Waiting for history"}</span></div><div className="recharts-wrap"><ResponsiveContainer width="100%" height={270}><LineChart data={chartData} margin={{ top: 12, right: 12, left: 0, bottom: 4 }}><CartesianGrid stroke="#d8e3ee" strokeDasharray="3 4" /><XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={35} /><YAxis yAxisId="temperature" domain={[15, 40]} tick={{ fontSize: 10, fill: "#ff7627" }} /><YAxis yAxisId="humidity" orientation="right" domain={[40, 100]} tick={{ fontSize: 10, fill: "#3b82f6" }} /><Tooltip /><Legend /><Line yAxisId="temperature" type="monotone" dataKey="temperature" name="Temp (°C)" stroke="#ff7627" dot={false} strokeWidth={2.5} connectNulls /><Line yAxisId="humidity" type="monotone" dataKey="humidity" name="Humidity (%)" stroke="#3b82f6" dot={false} strokeWidth={2.5} connectNulls /></LineChart></ResponsiveContainer></div></article>;
}

function DashboardView({ actors, status, history }: { actors: Actor[]; status: RuntimeStatus; history: HistoryItem[] }) {
  const sensors = status.esp32?.sensors ?? {};
  const outputs = status.moxa?.outputs ?? {};
  const value = (key: string, fallback = 0) => typeof sensors[key] === "number" ? Number(sensors[key]) : fallback;
  const temperatures = { right: value("temperature_right", 0), middle: value("temperature_top", 0), left: value("temperature_left", 0) };
  const averageTemperature = (temperatures.right + temperatures.middle + temperatures.left) / 3;
  const humiditySensors = { right: value("humidity_right", 0), middle: value("humidity_top", 0), left: value("humidity_left", 0) };
  const averageHumidity = (humiditySensors.right + humiditySensors.middle + humiditySensors.left) / 3;
  const soilSensors = { right: value("soil_right", 0), left: value("soil_left", 0) };
  const averageSoil = (soilSensors.right + soilSensors.left) / 2;
  const temperatureHistory = history.filter((item) => item.source === "esp32_sensors").sort((left, right) => right.timestamp - left.timestamp);
  const latestHistory = temperatureHistory[0];
  const previousHistory = latestHistory ? temperatureHistory.find((item) => latestHistory.timestamp - item.timestamp >= 15 * 60) : undefined;
  const historyAverage = (item: HistoryItem, keys: string[]) => keys.map((key) => Number(item.values[key])).filter((entry) => Number.isFinite(entry)).reduce((sum, entry, _, values) => sum + entry / values.length, 0);
  const temperatureDelta = previousHistory && latestHistory ? historyAverage(latestHistory, ["temperature_right", "temperature_top", "temperature_left"]) - historyAverage(previousHistory, ["temperature_right", "temperature_top", "temperature_left"]) : 0;
  const humidityDelta = previousHistory && latestHistory ? historyAverage(latestHistory, ["humidity_right", "humidity_top", "humidity_left"]) - historyAverage(previousHistory, ["humidity_right", "humidity_top", "humidity_left"]) : 0;
  const soilDelta = previousHistory && latestHistory ? historyAverage(latestHistory, ["soil_right", "soil_left"]) - historyAverage(previousHistory, ["soil_right", "soil_left"]) : 0;
  const temperatureTrend = temperatureDelta > 0.15 ? "Up" : temperatureDelta < -0.15 ? "Down" : "Stable";
  const humidityTrend = humidityDelta > 0.3 ? "Up" : humidityDelta < -0.3 ? "Down" : "Stable";
  const soilTrend = soilDelta > 0.3 ? "Up" : soilDelta < -0.3 ? "Down" : "Stable";
  const temperatureZone = averageTemperature < 24 ? "cold" : averageTemperature > 27 ? "hot" : "zone";
  const humidityZone = averageHumidity < 85 ? "cold" : averageHumidity > 95 ? "hot" : "zone";
  const soilZone = averageSoil < 65 ? "cold" : averageSoil > 80 ? "hot" : "zone";
  const active = actors.filter((actor) => actor.currentState).length;
  const on = (key: string) => isActive(outputs[key] ?? outputs[`DO@DO-${key.slice(2).padStart(2, "0")}`]);
  const zoneLabel = (zone: string) => zone === "cold" ? "Too low" : zone === "hot" ? "Too high" : "In zone";
  const sensorTriplet = (sensors: { right: number; middle: number; left: number }) => <div className="temperature-sensors"><span><b>R</b>{sensors.right.toFixed(1)}</span><span><b>M</b>{sensors.middle.toFixed(1)}</span><span><b>L</b>{sensors.left.toFixed(1)}</span></div>;
  const health = (online: boolean, label: string, value: string) => { const StatusIcon = online ? Wifi : WifiOff; return <span className={`status-pill ${online ? "online" : "offline"}`}><StatusIcon size={14} /> {label} <b>{value}</b></span>; };
  return <div className="dashboard-view"><div className="dashboard-status"><span className="section-kicker">System health</span><div className="health-pills">{health(status.esp32?.status === "online", "ESP32 Sensor", status.esp32?.status === "online" ? "Online" : "Offline")}{health(status.moxa?.status === "online", "Moxa 4510", status.moxa?.status === "online" ? "Online" : "Offline")}{health(status.service?.status === "online", "Pi service", status.service?.status === "online" ? "Online" : "Offline")}{health(status.mqtt?.status === "connected", "MQTT broker", status.mqtt?.status === "connected" ? "Connected" : "Offline")}</div></div><section className="dashboard-metrics"><article className={`dashboard-metric temp temperature-card-${temperatureZone}`}><div className="temperature-heading"><span>Temperature</span><b>{temperatureTrend}</b></div><strong>{averageTemperature.toFixed(1)}°C</strong>{sensorTriplet(temperatures)}<div className="temperature-target"><span>Target: 24 - 27°C</span><b>{temperatureTrend}</b></div><small className="temperature-zone-label">{zoneLabel(temperatureZone)}</small><div className="temperature-bar"><i className="cold" /><i className="zone" /><i className="hot" /></div></article><article className={`dashboard-metric humidity temperature-card-${humidityZone}`}><div className="temperature-heading"><span>Humidity</span><b>{humidityTrend}</b></div><strong>{averageHumidity.toFixed(1)}%</strong>{sensorTriplet(humiditySensors)}<div className="temperature-target"><span>Target: 85 - 95%</span><b>{humidityTrend}</b></div><small className="temperature-zone-label">{zoneLabel(humidityZone)}</small><div className="temperature-bar"><i className="cold" /><i className="zone" /><i className="hot" /></div></article><article className={`dashboard-metric soil temperature-card-${soilZone}`}><div className="temperature-heading"><span>Soil moisture</span><b>{soilTrend}</b></div><strong>{averageSoil.toFixed(1)}%</strong><div className="temperature-sensors"><span><b>R</b>{soilSensors.right.toFixed(1)}</span><span><b>L</b>{soilSensors.left.toFixed(1)}</span></div><div className="temperature-target"><span>Target: 65 - 80%</span><b>{soilTrend}</b></div><small className="temperature-zone-label">{zoneLabel(soilZone)}</small><div className="temperature-bar"><i className="cold" /><i className="zone" /><i className="hot" /></div></article><article className="dashboard-metric season"><span>Climate profile</span><strong>Rainy Season</strong><small>Current schedule</small></article></section><TrendGraph history={history} /><section className="dashboard-grid"><article className="dashboard-panel"><h2>Active actuators</h2><div className="actuator-summary"><strong>{active}</strong><span>active now</span></div><div className="health-row"><span>Fans</span><b>{actors.filter((actor) => actor.type === "Fan" && actor.currentState).length}/6</b></div><div className="health-row"><span>LEDs</span><b>{actors.filter((actor) => actor.type === "LED" && actor.currentState).length}/4</b></div><div className="health-row"><span>Heat lamp</span><b>{on("do6") ? "ON" : "OFF"}</b></div></article><article className="dashboard-panel dashboard-wide"><h2>Current outputs</h2><div className="output-grid">{[{ key: "do0", label: "LED 1 power" }, { key: "do1", label: "LED 2 power" }, { key: "do2", label: "LED 3 power" }, { key: "do3", label: "LED 4 power" }, { key: "do4", label: "Irrigation" }, { key: "do5", label: "Mist maker" }, { key: "do6", label: "Heat lamp" }, { key: "do7", label: "Waterfall" }].map(({ key, label }) => <div className="output-chip" key={key}><i className={on(key) ? "on" : ""} /><span>{label}</span><b>{on(key) ? "ON" : "OFF"}</b></div>)}</div></article></section></div>;
}

export default function Home() {
  const [view, setView] = useState<View>("dashboard");
  const [month, setMonth] = useState(new Date().getMonth());
  const [actors, setActors] = useState<Actor[]>(initialActors);
  const [now, setNow] = useState<Date | null>(null);
  const [status, setStatus] = useState<RuntimeStatus>({});
  const [history, setHistory] = useState<HistoryItem[]>([]);
  useEffect(() => { setNow(new Date()); const timer = window.setInterval(() => setNow(new Date()), 1000); return () => window.clearInterval(timer); }, []);
  useEffect(() => {
    const refreshActors = async () => {
      try {
        const [statusResponse, historyResponse] = await Promise.all([fetch("/api/status", { cache: "no-store" }), fetch("/api/history", { cache: "no-store" })]);
        if (!statusResponse.ok) return;
        const status = await statusResponse.json() as RuntimeStatus;
        const historyPayload = historyResponse.ok ? await historyResponse.json() : [];
        setHistory(Array.isArray(historyPayload) ? historyPayload : []);
        setStatus(status);
        setActors((current) => current.map((actor) => {
          const override = currentOverride(actor, status);
          if (actor.pendingMode) {
            return { ...actor, currentState: currentActorState(actor, status) };
          }
          return { ...actor, currentState: currentActorState(actor, status), mode: override.mode, overrideExpiresAt: override.expiresAt };
        }));
      } catch {
        // Keep the last known actuator state while the Pi API is unavailable.
      }
    };
    void refreshActors();
    const timer = window.setInterval(() => void refreshActors(), 30000);
    return () => window.clearInterval(timer);
  }, []);
  const clockText = now ? now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "--:--";
  const pageTitle = view === "dashboard" ? "Live dashboard" : view === "schedule" ? "Yearly climate planning" : "Manual actor control";
  const pageDescription = view === "dashboard" ? "Real-time terrarium monitoring and actuator status." : view === "schedule" ? "Configure every month to match the seasonal rhythm." : "Override fans, lighting, pumps and climate actors individually.";
  return <main className="shell"><aside className="sidebar"><div className="brand"><span className="brand-mark">◒</span><div><h1>Terrarium</h1><p>Climate Control</p></div></div><nav className="nav"><button className={view === "dashboard" ? "active" : ""} onClick={() => setView("dashboard")}>⌂ <span>Dashboard</span></button><button className={view === "schedule" ? "active" : ""} onClick={() => setView("schedule")}>▦ <span>Seasonal Schedule</span></button><button className={view === "overrides" ? "active" : ""} onClick={() => setView("overrides")}>⚙ <span>Actor Overrides</span>{actors.some((actor) => actor.mode === "manual") && <b>{actors.filter((actor) => actor.mode === "manual").length}</b>}</button></nav><div className="sidebar-footer"><span className="live-dot" /> System online<br /><small>Last sync {clockText}</small></div></aside><section className="main"><header className="topbar"><div><span className="eyebrow">Terrarium control center</span><h1>{pageTitle}</h1><p>{pageDescription}</p></div><time className="clock">{clockText}<small> Local time</small></time></header>{view === "dashboard" ? <DashboardView actors={actors} status={status} history={history} /> : view === "schedule" ? <ScheduleView month={month} setMonth={setMonth} /> : <OverridesView actors={actors} setActors={setActors} />}</section></main>;
}
