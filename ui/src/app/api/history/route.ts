import { NextResponse } from "next/server";

const backend = process.env.TERRARIUM_API_URL ?? process.env.TERRARIUM_PI_URL ?? "http://127.0.0.1:8080";

export async function GET() {
  try {
    const response = await fetch(`${backend}/api/cloud-history?limit=100`, { cache: "no-store" });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Pi history API unavailable" }, { status: 503 });
  }
}
