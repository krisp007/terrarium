import { NextRequest, NextResponse } from "next/server";

const backend = process.env.TERRARIUM_API_URL ?? process.env.TERRARIUM_PI_URL ?? "http://127.0.0.1:8080";

export async function POST(request: NextRequest) {
  try {
    const response = await fetch(`${backend}/api/override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(await request.json()),
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ error: "MQTT override API unavailable" }, { status: 503 });
  }
}