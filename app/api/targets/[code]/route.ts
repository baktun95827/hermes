import { NextResponse } from "next/server";
import { getPostgresTargetReadProjection } from "@/packages/signal-radar-core/src";

export const runtime = "nodejs";

type TargetRouteProps = {
  params: Promise<{ code: string }>;
};

export async function GET(_: Request, { params }: TargetRouteProps) {
  try {
    const { code } = await params;
    const payload = await getPostgresTargetReadProjection(code);
    return NextResponse.json(payload);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: error instanceof Error && error.message.includes("DATABASE_URL") ? 503 : 400 }
    );
  }
}
