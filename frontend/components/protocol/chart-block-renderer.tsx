"use client";

import { ChartBlock } from "@/components/protocol/chart-block";

export function ChartBlockRenderer({ blockId, config, editable, onSave }: {
  blockId: number;
  config: { chart_type?: string; cycle_key?: string };
  editable: boolean;
  onSave: (cfg: Record<string, unknown>) => void;
}) {
  return <ChartBlock blockId={blockId} config={config} editable={editable} onSave={onSave} />;
}
