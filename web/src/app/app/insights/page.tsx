"use client";

import { Insights } from "../../../views/Insights";
import { useBoardData } from "../../../lib/board";

export default function InsightsPage() {
  return <Insights stats={useBoardData().stats} />;
}
