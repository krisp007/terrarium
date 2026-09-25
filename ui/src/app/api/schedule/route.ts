import { NextRequest, NextResponse } from "next/server";

const backend = process.env.TERRARIUM_API_URL ?? process.env.TERRARIUM_PI_URL ?? "http://127.0.0.1:8080";
const cloudBackend = process.env.TERRARIUM_PROFILE_API_URL;
const deviceId = process.env.TERRARIUM_DEVICE_ID ?? "terrarium-pi";

export async function GET() {
  try {
    if (cloudBackend) {
      const cloudResponse = await fetch(`${cloudBackend}?deviceId=${encodeURIComponent(deviceId)}`, { cache: "no-store" });
      if (cloudResponse.ok) return NextResponse.json({ ...(await cloudResponse.json()), storage: "cosmos", sync: "synced" });
    }
    const localResponse = await fetch(`${backend}/api/schedule`, { cache: "no-store" });
    return NextResponse.json(await localResponse.json(), { status: localResponse.status });
  } catch {
    return NextResponse.json({ profiles: {}, storage: "browser", sync: "offline" }, { status: 200 });
  }
}

export async function PUT(request: NextRequest) {
  const payload = await request.json();
  try {
    const localResponse = await fetch(`${backend}/api/schedule`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const localPayload = await localResponse.json();
    if (!localResponse.ok) return NextResponse.json(localPayload, { status: localResponse.status });
    if (!cloudBackend) return NextResponse.json(localPayload);
    try {
      const cloudResponse = await fetch(`${cloudBackend}?deviceId=${encodeURIComponent(deviceId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (cloudResponse.ok) return NextResponse.json({ ...(await cloudResponse.json()), storage: "cosmos", sync: "synced" });
    } catch {
      // The local copy remains authoritative until the next successful sync.
    }
    return NextResponse.json({ ...localPayload, sync: "pending" });
  } catch {
    return NextResponse.json({ error: "Local schedule storage unavailable", sync: "offline" }, { status: 503 });
  }
}