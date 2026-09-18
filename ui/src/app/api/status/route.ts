import { NextResponse } from "next/server";

const backend = process.env.TERRARIUM_PI_URL ?? "http://127.0.0.1:8080";

export async function GET() {
  try {
    const response = await fetch(`${backend}/api/status`, { cache: "no-store" });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ error: "Pi status API unavailable" }, { status: 503 });
  }
}
