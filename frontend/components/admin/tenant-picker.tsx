"use client";

import { useCallback, useEffect, useState } from "react";

import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import type { AdminTenantPage, AdminTenantSummary } from "@/types/api";

type TenantOption = Pick<AdminTenantSummary, "id" | "name">;

/** Höchstens so viele Treffer lädt der Picker je Eingabe (Plan §5.1: `/tenants?q=&limit=20`). */
export const TENANT_PICKER_LIMIT = 20;

/** Mandanten-Auswahl mit Remote-Suche (SearchableSelect.loadOptions) statt der ganzen Mandantenliste.
 * Mandantennamen sind keine Personendaten; der Suchbegriff geht als `q` an /api/admin/tenants. */
export function TenantPicker({
  value,
  onChange,
  nullLabel,
  placeholder,
  triggerId,
}: {
  value: string | null;
  onChange: (tenant: TenantOption | null) => void;
  nullLabel?: string;
  placeholder?: string;
  /** ID des Auslösers (z. B. um ihn aus einer Token-Suche zu fokussieren) */
  triggerId?: string;
}) {
  const [selected, setSelected] = useState<TenantOption | null>(null);

  // Beschriftung für eine ID aus der URL (Deep Link), die noch unter keinem Treffer war.
  useEffect(() => {
    if (!value) {
      setSelected(null);
      return;
    }
    if (selected?.id === value) return;
    const controller = new AbortController();
    browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${encodeURIComponent(value)}`, { signal: controller.signal })
      .then((tenant) => setSelected({ id: tenant.id, name: tenant.name }))
      .catch(() => undefined);
    return () => controller.abort();
  }, [value, selected?.id]);

  const loadOptions = useCallback(async (query: string, signal: AbortSignal) => {
    const params = new URLSearchParams({ limit: String(TENANT_PICKER_LIMIT), offset: "0" });
    if (query) params.set("q", query);
    const page = await browserApiFetch<AdminTenantPage>(`/api/admin/tenants?${params.toString()}`, { signal });
    return page.items.map((tenant) => ({ id: tenant.id, name: tenant.name }));
  }, []);

  return (
    <SearchableSelect<TenantOption, string>
      options={[]}
      loadOptions={loadOptions}
      selectedOption={selected}
      getId={(tenant) => tenant.id}
      getLabel={(tenant) => tenant.name}
      value={value}
      onChange={(tenant) => {
        setSelected(tenant);
        onChange(tenant);
      }}
      nullLabel={nullLabel}
      placeholder={placeholder}
      triggerProps={triggerId ? { id: triggerId } : undefined}
    />
  );
}
