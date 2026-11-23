"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";

export type AuditPerson = { kind: "user" | "admin"; id: string; label: string };

type SearchGroups = { groups: { group: string; items: { id: string; label: string; sublabel?: string | null }[] }[] };
type FilterOptions = { admins: { id: string; display_name: string }[] };

/** Person für das Audit-Log wählen (Token «person:», 1.6): Konten über die Admin-Suche (POST, der
 * Suchbegriff steht nur im Body und wird nicht protokolliert), Plattform-Admins aus den
 * Filteroptionen. In Filter und URL kommen nur Art und öffentliche ID, nie der Name. */
export function AuditPersonPicker({
  kind,
  id,
  onChange,
  triggerId,
}: {
  kind: string;
  id: string;
  onChange: (person: AuditPerson | null) => void;
  triggerId?: string;
}) {
  const t = useTranslations("admin.auditLog");
  const [admins, setAdmins] = useState<AuditPerson[]>([]);
  const [selected, setSelected] = useState<AuditPerson | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    browserApiFetch<FilterOptions>("/api/admin/audit-log/filter-options", { signal: controller.signal })
      .then((options) => setAdmins(options.admins.map((admin) => ({ kind: "admin", id: admin.id, label: admin.display_name }))))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  // Deep Link: Plattform-Admins haben einen Namen aus den Filteroptionen; Konten erscheinen ohne
  // Nachschlagen als «Person gewählt» (kein zusätzlicher, protokollierter Personenabruf).
  const current: AuditPerson | null = !id
    ? null
    : selected?.id === id
      ? selected
      : admins.find((admin) => admin.id === id) ?? { kind: kind === "admin" ? "admin" : "user", id, label: t("person.selected") };

  const loadOptions = useCallback(
    async (query: string, signal: AbortSignal): Promise<AuditPerson[]> => {
      const term = query.trim().toLowerCase();
      const matchingAdmins = admins.filter((admin) => !term || admin.label.toLowerCase().includes(term));
      if (term.length < 3) return matchingAdmins;
      const result = await browserApiFetch<SearchGroups>("/api/admin/search", { method: "POST", body: JSON.stringify({ q: query.trim() }), signal });
      const users = result.groups.find((group) => group.group === "users")?.items ?? [];
      return [
        ...matchingAdmins,
        ...users.map((user) => ({ kind: "user" as const, id: user.id, label: user.sublabel ? `${user.label} · ${user.sublabel}` : user.label })),
      ];
    },
    [admins],
  );

  return (
    <SearchableSelect<AuditPerson, string>
      options={[]}
      loadOptions={loadOptions}
      selectedOption={current}
      getId={(person) => person.id}
      getLabel={(person) => (person.kind === "admin" ? t("person.adminLabel", { name: person.label }) : person.label)}
      value={id || null}
      onChange={(person) => {
        setSelected(person);
        onChange(person);
      }}
      nullLabel={t("person.all")}
      placeholder={t("person.placeholder")}
      searchPlaceholder={t("person.searchPlaceholder")}
      triggerProps={triggerId ? { id: triggerId } : undefined}
    />
  );
}
