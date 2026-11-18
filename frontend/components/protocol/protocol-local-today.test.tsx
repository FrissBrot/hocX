import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: vi.fn().mockResolvedValue({}),
  ApiError: class ApiError extends Error {},
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/hooks/use-refresh-on-restore", () => ({ useRefreshOnRestore: () => undefined }));
vi.mock("@/lib/hooks/use-infinite-scroll", () => ({ useInfiniteScroll: () => () => undefined }));

import { ProtocolBuilder } from "./protocol-builder";
import { createProtocolEventDraft } from "./protocol-editor-shared";
import type { TemplateSummary } from "@/types/api";

// «Heute» muss das lokale Datum sein. toISOString() liefert UTC: in der Schweiz war zwischen
// 00:00 und 01:00 (Sommer 02:00) Uhr noch «gestern» vorausgewählt - typisch nach einem Hock.
beforeEach(() => {
  vi.stubEnv("TZ", "Europe/Zurich");
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-18T23:30:00Z")); // 19.11.2026, 00:30 in Zürich
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

it("preselects the local date in the create form", () => {
  const template = { id: "t-1", name: "Hock" } as TemplateSummary;
  render(<ProtocolBuilder initialProtocols={[]} templates={[template]} />);
  fireEvent.click(screen.getAllByRole("button", { name: /Neues Protokoll/ })[0]);
  expect(screen.getByDisplayValue("19.11.2026")).toBeTruthy();
  expect(screen.queryByDisplayValue("18.11.2026")).toBeNull();
});

it("uses the local date for a new event without protocol date", () => {
  expect(createProtocolEventDraft(undefined).event_date).toBe("2026-11-19");
});
