import { NextResponse } from "next/server";

import liveRecords from "@/app/data/issues/issues.json";
import testRecords from "@/app/data/issues/test/issues.json";

type IssueRecord = {
  id: string;
  issueId: string;
  issue: string;
  observedAt: string;
  type: string;
};

function matchesType(recordType: string, requestedType: string) {
  if (requestedType === "ALL") return true;
  if (requestedType === "Detected") {
    return recordType === "Actively Happening" || recordType.startsWith("Unresolved ·") || recordType.startsWith("Resolved ·");
  }
  if (requestedType === "User Reported") return recordType.startsWith("User Reported ·");
  if (requestedType === "Snoozed") return recordType.startsWith("Snoozed ·");
  return recordType === requestedType;
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const source = searchParams.get("source") === "live" ? "live" : "test";
  const requestedType = searchParams.get("type") || "ALL";
  const start = Date.parse(searchParams.get("start") || "");
  const end = Date.parse(searchParams.get("end") || "");

  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) {
    return NextResponse.json({ error: "Choose a valid date range." }, { status: 400 });
  }

  const records = (source === "test" ? testRecords : liveRecords) as IssueRecord[];
  const matches = records
    .filter((record) => {
      const observed = Date.parse(record.observedAt);
      return observed >= start && observed <= end && matchesType(record.type, requestedType);
    })
    .sort((a, b) => Date.parse(b.observedAt) - Date.parse(a.observedAt));

  return NextResponse.json({
    records: matches,
    source,
    folder: source === "test" ? "/var/lib/guardian/issues/test" : "/var/lib/guardian/issues"
  });
}
