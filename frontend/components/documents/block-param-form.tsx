"use client";

// Formular für die Parameter eines Katalog-Blocks, generiert aus dem JSON-Schema
// (GET /api/documents/catalog, params_schema). Referenzfelder (x-source) laden ihre Optionen
// über /api/documents/sources/{source}; Felder mit x-widget "hidden" erscheinen nicht.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { DateInput } from "@/components/ui/date-input";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { fetchSourceOptions, JsonSchema, resolveSchema, SourceOption, unwrapNullable } from "@/lib/documents/api";

type Props = {
  schema: JsonSchema;
  params: Record<string, unknown>;
  onChange: (params: Record<string, unknown>) => void;
  /** Kontext-Protokoll für Quellen, die ein Protokoll brauchen (Elemente, Blöcke). */
  protocolId?: string | null;
};

const sourceCache = new Map<string, Promise<SourceOption[]>>();

export function loadSource(source: string, protocolId?: string | null): Promise<SourceOption[]> {
  const key = `${source}:${protocolId ?? ""}`;
  if (!sourceCache.has(key)) {
    sourceCache.set(
      key,
      fetchSourceOptions(source, protocolId).catch(() => {
        sourceCache.delete(key);
        return [];
      })
    );
  }
  return sourceCache.get(key)!;
}

function useSource(source: string | undefined, protocolId?: string | null) {
  const [options, setOptions] = useState<SourceOption[]>([]);
  useEffect(() => {
    if (!source) return;
    let active = true;
    void loadSource(source, protocolId).then((loaded) => {
      if (active) setOptions(loaded);
    });
    return () => {
      active = false;
    };
  }, [source, protocolId]);
  return options;
}

function optionLabel(option: SourceOption) {
  return option.detail ? `${option.label} · ${option.detail}` : option.label;
}

function SourceField({ source, value, onChange, protocolId, multiple }: { source: string; value: unknown; onChange: (value: unknown) => void; protocolId?: string | null; multiple: boolean }) {
  const t = useTranslations("documents");
  const options = useSource(source, protocolId);
  if (multiple) {
    const values = Array.isArray(value) ? (value as string[]) : [];
    return (
      <SearchableMultiSelect
        options={options}
        getId={(option) => option.id}
        getLabel={optionLabel}
        values={values}
        onChange={(ids) => onChange(ids)}
        emptySelectionLabel={t("params.none")}
      />
    );
  }
  return (
    <SearchableSelect
      options={options}
      getId={(option) => option.id}
      getLabel={optionLabel}
      value={typeof value === "string" ? value : null}
      onChange={(option) => onChange(option ? option.id : null)}
      nullLabel={t("params.none")}
    />
  );
}

function enumLabel(t: ReturnType<typeof useTranslations>, value: string | number) {
  return t(`enum.${value === "" ? "none" : String(value)}`);
}

function ObjectRows({ name, itemSchema, root, value, onChange }: { name: string; itemSchema: JsonSchema; root: JsonSchema; value: unknown; onChange: (value: unknown) => void }) {
  const t = useTranslations("documents");
  const rows = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  const properties = Object.entries(resolveSchema(itemSchema, root).properties ?? {});
  function update(index: number, key: string, next: unknown) {
    onChange(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, [key]: next } : row)));
  }
  return (
    <div className="docexport-rows">
      {rows.map((row, index) => (
        <div key={index} className="docexport-row">
          {properties.map(([key]) => (
            <input
              key={key}
              aria-label={t(`params.${key}`)}
              placeholder={t(`params.${key}`)}
              value={String(row[key] ?? "")}
              onChange={(event) => update(index, key, event.target.value)}
            />
          ))}
          <button type="button" className="button-icon-soft button-icon-soft-danger" aria-label={t("dialog.removeRow")} onClick={() => onChange(rows.filter((_, rowIndex) => rowIndex !== index))}>
            ✕
          </button>
        </div>
      ))}
      <button type="button" className="button-secondary button-ghost" onClick={() => onChange([...rows, Object.fromEntries(properties.map(([key]) => [key, ""]))])}>
        {t("dialog.addRow", { field: t(`params.${name}`) })}
      </button>
    </div>
  );
}

export function BlockParamForm({ schema, params, onChange, protocolId }: Props) {
  const t = useTranslations("documents");
  const properties = Object.entries(schema.properties ?? {});

  function set(name: string, value: unknown) {
    onChange({ ...params, [name]: value });
  }

  const contextProtocol = typeof params.protocol_id === "string" ? params.protocol_id : protocolId;

  return (
    <div className="docexport-params">
      {properties.map(([name, raw]) => {
        const property = unwrapNullable(raw, schema);
        if (property["x-widget"] === "hidden" || raw["x-widget"] === "hidden") return null;
        const value = params[name] ?? (raw.default as unknown) ?? null;
        const label = t(`params.${name}`);
        const source = property["x-source"] ?? raw["x-source"] ?? property.items?.["x-source"];

        if (property.type === "boolean") {
          return (
            <label key={name} className="docexport-check">
              <input type="checkbox" checked={Boolean(value)} onChange={(event) => set(name, event.target.checked)} />
              <span>{label}</span>
            </label>
          );
        }

        let control: React.ReactNode;
        if (property.type === "array") {
          const items = resolveSchema(property.items ?? {}, schema);
          if (source) {
            control = <SourceField source={source} value={value} onChange={(next) => set(name, next)} protocolId={contextProtocol} multiple />;
          } else if (items.enum) {
            const selected = Array.isArray(value) ? (value as string[]) : [];
            control = (
              <div className="docexport-checkgroup">
                {items.enum.map((option) => (
                  <label key={String(option)} className="docexport-check">
                    <input
                      type="checkbox"
                      checked={selected.includes(String(option))}
                      onChange={(event) =>
                        set(name, event.target.checked ? [...selected, String(option)] : selected.filter((entry) => entry !== String(option)))
                      }
                    />
                    <span>{enumLabel(t, option)}</span>
                  </label>
                ))}
              </div>
            );
          } else if (items.properties) {
            control = <ObjectRows name={name} itemSchema={property.items ?? {}} root={schema} value={value} onChange={(next) => set(name, next)} />;
          } else if (items.type === "array") {
            // Tabellenzeilen: eine Zeile pro Eintrag, Zellen mit ";" getrennt
            const rows = Array.isArray(value) ? (value as string[][]) : [];
            control = (
              <textarea
                rows={5}
                value={rows.map((row) => row.join("; ")).join("\n")}
                onChange={(event) => set(name, event.target.value.split("\n").filter((line) => line.trim()).map((line) => line.split(";").map((cell) => cell.trim())))}
              />
            );
          } else {
            const lines = Array.isArray(value) ? (value as string[]) : [];
            control = <textarea rows={4} value={lines.join("\n")} onChange={(event) => set(name, event.target.value.split("\n").filter((line) => line.trim()))} />;
          }
        } else if (source) {
          control = <SourceField source={source} value={value} onChange={(next) => set(name, next)} protocolId={contextProtocol} multiple={false} />;
        } else if (property.enum) {
          control = (
            <select value={String(value ?? "")} onChange={(event) => set(name, typeof property.enum?.[0] === "number" ? Number(event.target.value) : event.target.value)}>
              {property.enum.map((option) => (
                <option key={String(option)} value={String(option)}>
                  {enumLabel(t, option)}
                </option>
              ))}
            </select>
          );
        } else if (property.format === "date") {
          control = <DateInput value={typeof value === "string" ? value : ""} onChange={(next) => set(name, next || null)} />;
        } else if (property.type === "integer" || property.type === "number") {
          control = (
            <input
              type="number"
              min={property.minimum}
              max={property.maximum}
              value={value === null || value === undefined ? "" : String(value)}
              onChange={(event) => set(name, event.target.value === "" ? null : Number(event.target.value))}
            />
          );
        } else if (property["x-widget"] === "markdown") {
          control = <textarea rows={6} value={String(value ?? "")} onChange={(event) => set(name, event.target.value)} />;
        } else {
          control = <input value={String(value ?? "")} maxLength={property.maxLength} onChange={(event) => set(name, event.target.value || null)} />;
        }

        return (
          <div key={name} className="field-stack">
            <span className="field-label">{label}</span>
            {control}
          </div>
        );
      })}
    </div>
  );
}
