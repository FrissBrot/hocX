"use client";

import { ChartBlock } from "@/components/protocol/chart-block";

export function ChartBlockRenderer({ config, editable, onSave }: {
  config: { chart_type?: string; cycle_key?: string };
  editable: boolean;
  onSave: (cfg: Record<string, unknown>) => void;
}) {
  return <ChartBlock config={config} editable={editable} onSave={onSave} />;
}
