import { browserApiFetch } from "@/lib/api/client";
import { EventSummary } from "@/types/api";

export type ProtocolCycleInfo = {
  cycle_config_id: string;
  cycle_year: number;
  label: string;
};

export type ProtocolCycleEvents = {
  items: EventSummary[];
  total: number;
  cycle: ProtocolCycleInfo | null;
};

/**
 * Event pool for the planning-mode popups (Terminübersicht, Checkbox-Kandidaten).
 * scope="current" restricts to the protocol's resolved cycle (falls back to "all"
 * server-side if the template has no cycle configured); scope="all" ignores cycles.
 * Bypasses the incomplete `availableEvents` array in the editor, which only holds
 * the newest 100 tenant-wide events (GET /api/events default limit).
 */
export async function fetchCycleEvents(
  protocolId: string,
  options: { scope?: "current" | "all"; search?: string; skip?: number; limit?: number } = {}
): Promise<ProtocolCycleEvents> {
  const params = new URLSearchParams();
  params.set("scope", options.scope ?? "current");
  if (options.search) params.set("search", options.search);
  if (options.skip) params.set("skip", String(options.skip));
  params.set("limit", String(options.limit ?? 500));
  return browserApiFetch<ProtocolCycleEvents>(`/api/protocols/${protocolId}/cycle-events?${params.toString()}`);
}
