import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { pathname } = vi.hoisted(() => ({ pathname: { current: "/tenant-settings/search" } }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current, useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/mobile/mobile-shell", () => ({ useOpenMore: () => vi.fn(), useMobileSession: () => null }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import { MobileTenantSettings } from "./mobile-admin";

describe("MobileTenantSettings (Bereichsauswahl)", () => {
  it("zeigt auf /tenant-settings/search «Suche & Synonyme» als gewählten Bereich", () => {
    render(<MobileTenantSettings title="Mandant-Einstellungen"><p>Inhalt</p></MobileTenantSettings>);
    const select = screen.getByLabelText("Mandant-Einstellungen") as HTMLSelectElement;
    expect(select.value).toBe("search");
    expect(select.selectedOptions[0].textContent).toBe("Suche & Synonyme");
  });
});
