"use client";

// Eingabefelder des Eigenschaftenpanels. Farben und Schriften bevorzugt als Brand-Referenz
// ($brand.primary, $brand.font.heading), Datenbindungen und Bedingungen werden aus Listen
// gewählt - Benutzer schreiben nie Ausdrücke oder Code.

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { resolveColor } from "@/components/documents/designer/brand-preview";
import { modeAllows, useDesigner } from "@/components/documents/designer/designer-context";
import { bindingLabel } from "@/components/documents/studio-labels";
import { locales } from "@/i18n/locale-config.generated";
import type { BindingInfo } from "@/lib/documents/api";
import { Border, Condition, FormatSpec, Inline, Spacing, TextContent, TextStyle } from "@/lib/documents/layout";

const HEX = /^#[0-9A-Fa-f]{6}$/;

export function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <label className="field-stack">
      <span className="field-label">{label}</span>
      {children}
      {help && <span className="field-help">{help}</span>}
    </label>
  );
}

export function CheckField({ label, checked, onChange, help }: { label: string; checked: boolean; onChange: (value: boolean) => void; help?: string }) {
  return (
    <label className="studio-inline-check">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>
        {label}
        {help && <span className="field-help studio-check-help">{help}</span>}
      </span>
    </label>
  );
}

/** Bezeichnung einer Farbreferenz; eigene Brand-Farben tragen ihren Schlüssel als Namen. */
function colorRefLabel(t: (key: string) => string, ref: string): string {
  if (ref.startsWith("$brand.custom.")) return ref.slice("$brand.custom.".length);
  return t(`colorRef.${ref.replace("$brand.", "").replace(/\./g, "_")}`);
}

/** Farbe: Brand-Farben als Auswahlfelder, optional eigene Hex-Farbe (Experte/Erweitert). */
export function ColorField({ label, value, onChange, allowEmpty = true }: { label: string; value: string | null | undefined; onChange: (value: string | null) => void; allowEmpty?: boolean }) {
  const t = useTranslations("documentStudio");
  const { brand, catalog, mode } = useDesigner();
  const references = catalog.color_references.filter((ref) => !ref.includes("table_") && !ref.includes("watermark"));
  const [custom, setCustom] = useState(value && value.startsWith("#") ? value : "");
  return (
    <div className="field-stack">
      <span className="field-label">{label}</span>
      <div className="studio-swatches" role="radiogroup" aria-label={label}>
        {allowEmpty && (
          <button type="button" role="radio" aria-checked={!value} className={!value ? "studio-swatch studio-swatch-none studio-swatch-active" : "studio-swatch studio-swatch-none"} onClick={() => onChange(null)} aria-label={t("fields.colorInherit")}>
            ∅
          </button>
        )}
        {references.map((ref) => (
          <button
            key={ref}
            type="button"
            role="radio"
            aria-checked={value === ref}
            title={colorRefLabel(t, ref)}
            aria-label={colorRefLabel(t, ref)}
            className={value === ref ? "studio-swatch studio-swatch-active" : "studio-swatch"}
            style={{ background: resolveColor(ref, brand) }}
            onClick={() => onChange(ref)}
          />
        ))}
      </div>
      {modeAllows(mode, "advanced") && (
        <div className="studio-color-custom">
          <input
            type="color"
            aria-label={t("fields.customColor")}
            value={HEX.test(custom) ? custom : "#000000"} // design-ok: Dokumentfarbe (Daten), keine UI-Farbe
            onChange={(event) => {
              setCustom(event.target.value);
              onChange(event.target.value.toUpperCase());
            }}
          />
          <input
            value={custom}
            placeholder="#RRGGBB" // i18n-ok: Farbformat
            maxLength={7}
            aria-label={t("fields.customColorHex")}
            onChange={(event) => {
              setCustom(event.target.value);
              if (HEX.test(event.target.value)) onChange(event.target.value.toUpperCase());
            }}
          />
        </div>
      )}
    </div>
  );
}

const LENGTH = /^(auto|fill|\d{1,4}(\.\d{1,2})?(mm|%|fr))$/;

/** Breite/Höhe: auto, volle Breite, mm, % oder Anteil (fr). */
export function LengthField({ label, value, onChange, allowFr = false, allowNull = false }: { label: string; value: string | null | undefined; onChange: (value: string | null) => void; allowFr?: boolean; allowNull?: boolean }) {
  const t = useTranslations("documentStudio");
  const { mode } = useDesigner();
  const current = value ?? (allowNull ? "" : "auto");
  const match = /^(\d+(?:\.\d+)?)(mm|%|fr)$/.exec(current);
  const unit = current === "auto" || current === "fill" || current === "" ? current : match?.[2] ?? "auto";
  const number = match?.[1] ?? "";
  const units = ["auto", "fill", "%", ...(allowFr ? ["fr"] : []), ...(modeAllows(mode, "expert") ? ["mm"] : [])];
  return (
    <div className="field-stack">
      <span className="field-label">{label}</span>
      <div className="studio-length">
        <select
          value={unit}
          aria-label={t("fields.unit")}
          onChange={(event) => {
            const next = event.target.value;
            if (next === "" && allowNull) onChange(null);
            else if (next === "auto" || next === "fill") onChange(next);
            else onChange(`${number || (next === "fr" ? "1" : next === "%" ? "50" : "40")}${next}`);
          }}
        >
          {allowNull && <option value="">{t("fields.automatic")}</option>}
          {units.map((item) => (
            <option key={item} value={item}>
              {t(`fields.lengthUnit.${item === "%" ? "percent" : item}`)}
            </option>
          ))}
        </select>
        {unit !== "auto" && unit !== "fill" && unit !== "" && (
          <input
            type="number"
            min={0}
            step={unit === "fr" ? 0.5 : 1}
            aria-label={label}
            value={number}
            onChange={(event) => {
              const next = `${event.target.value}${unit}`;
              if (LENGTH.test(next)) onChange(next);
            }}
          />
        )}
      </div>
    </div>
  );
}

export function NumberField({ label, value, onChange, min = 0, max = 1000, step = 1, suffix, help }: { label: string; value: number | null | undefined; onChange: (value: number) => void; min?: number; max?: number; step?: number; suffix?: string; help?: string }) {
  return (
    <Field label={label} help={help}>
      <span className="studio-number">
        <input type="number" min={min} max={max} step={step} value={value ?? ""} onChange={(event) => event.target.value !== "" && onChange(Math.min(max, Math.max(min, Number(event.target.value))))} />
        {suffix && <span className="studio-number-suffix">{suffix}</span>}
      </span>
    </Field>
  );
}

export function SpacingField({ label, value, onChange }: { label: string; value: Spacing | undefined; onChange: (value: Spacing) => void }) {
  const t = useTranslations("documentStudio");
  const current = value ?? { top: 0, right: 0, bottom: 0, left: 0 };
  return (
    <fieldset className="studio-fieldset">
      <legend className="field-label">{label}</legend>
      <div className="studio-spacing">
        {(["top", "right", "bottom", "left"] as const).map((side) => (
          <label key={side} className="studio-spacing-side">
            <span className="field-help">{t(`fields.side.${side}`)}</span>
            <input type="number" min={0} max={200} step={0.5} value={current[side]} onChange={(event) => onChange({ ...current, [side]: Math.max(0, Number(event.target.value || 0)) })} aria-label={`${label} ${t(`fields.side.${side}`)}`} />
          </label>
        ))}
      </div>
      <span className="field-help">{t("fields.mmHint")}</span>
    </fieldset>
  );
}

export function TextStyleFields({ value, onChange, mergeKey }: { value: TextStyle | undefined; onChange: (value: TextStyle, mergeKey?: string) => void; mergeKey?: string }) {
  const t = useTranslations("documentStudio");
  const { catalog, mode } = useDesigner();
  const style = value ?? {};
  const set = (patch: Partial<TextStyle>, key: string) => onChange({ ...style, ...patch }, `${mergeKey ?? "text"}:${key}`);
  const fonts = ["$brand.font.body", "$brand.font.heading", ...catalog.fonts];
  return (
    <div className="studio-field-grid">
      <Field label={t("fields.font")}>
        <select value={style.font ?? ""} onChange={(event) => set({ font: event.target.value || null }, "font")}>
          <option value="">{t("fields.inherit")}</option>
          {fonts.map((font) => (
            <option key={font} value={font}>
              {font.startsWith("$brand.font.") ? t(`fields.brandFont.${font.slice(12)}`) : font}
            </option>
          ))}
        </select>
      </Field>
      <NumberField label={t("fields.fontSize")} value={style.size ?? null} min={4} max={96} step={0.5} suffix={t("brand.unitPt")} onChange={(size) => set({ size }, "size")} />
      <Field label={t("fields.weight")}>
        <select value={style.weight ?? ""} onChange={(event) => set({ weight: (event.target.value || null) as TextStyle["weight"] }, "weight")}>
          <option value="">{t("fields.inherit")}</option>
          {(["regular", "medium", "bold"] as const).map((weight) => (
            <option key={weight} value={weight}>
              {t(`fields.weightValue.${weight}`)}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t("fields.align")}>
        <select value={style.align ?? ""} onChange={(event) => set({ align: (event.target.value || null) as TextStyle["align"] }, "align")}>
          <option value="">{t("fields.inherit")}</option>
          {(["left", "center", "right", "justify"] as const).map((align) => (
            <option key={align} value={align}>
              {t(`fields.alignValue.${align}`)}
            </option>
          ))}
        </select>
      </Field>
      <div className="studio-field-span">
        <ColorField label={t("fields.textColor")} value={style.color} onChange={(color) => set({ color }, "color")} />
      </div>
      <CheckField label={t("fields.italic")} checked={style.italic === true} onChange={(italic) => set({ italic: italic || null }, "italic")} />
      {modeAllows(mode, "advanced") && (
        <>
          <NumberField label={t("fields.lineHeight")} value={style.line_height ?? null} min={0.8} max={3} step={0.05} onChange={(line_height) => set({ line_height }, "lineHeight")} />
          <NumberField label={t("fields.letterSpacing")} value={style.letter_spacing ?? null} min={-2} max={10} step={0.1} suffix={t("brand.unitPt")} onChange={(letter_spacing) => set({ letter_spacing }, "letterSpacing")} />
          <Field label={t("fields.transform")}>
            <select value={style.transform ?? ""} onChange={(event) => set({ transform: (event.target.value || null) as TextStyle["transform"] }, "transform")}>
              <option value="">{t("fields.inherit")}</option>
              {(["none", "upper", "lower"] as const).map((transform) => (
                <option key={transform} value={transform}>
                  {t(`fields.transformValue.${transform}`)}
                </option>
              ))}
            </select>
          </Field>
        </>
      )}
    </div>
  );
}

export function BorderField({ value, onChange }: { value: Border | null | undefined; onChange: (value: Border | null) => void }) {
  const t = useTranslations("documentStudio");
  const border: Border = value ?? { width: 0.5, color: "$brand.border", style: "solid", sides: ["top", "right", "bottom", "left"], radius: 0 };
  return (
    <fieldset className="studio-fieldset">
      <legend className="field-label">{t("fields.border")}</legend>
      <CheckField label={t("fields.borderEnabled")} checked={!!value && value.width > 0} onChange={(enabled) => onChange(enabled ? border : null)} />
      {value && (
        <div className="studio-field-grid">
          <NumberField label={t("fields.borderWidth")} value={border.width} min={0.1} max={10} step={0.1} suffix={t("brand.unitPt")} onChange={(width) => onChange({ ...border, width })} />
          <NumberField label={t("fields.radius")} value={border.radius} min={0} max={30} step={0.5} suffix={t("brand.unitMm")} onChange={(radius) => onChange({ ...border, radius })} />
          <Field label={t("fields.borderStyle")}>
            <select value={border.style} onChange={(event) => onChange({ ...border, style: event.target.value as Border["style"] })}>
              {(["solid", "dashed", "dotted"] as const).map((style) => (
                <option key={style} value={style}>
                  {t(`fields.lineStyle.${style}`)}
                </option>
              ))}
            </select>
          </Field>
          <div className="studio-field-span studio-sides">
            {(["top", "right", "bottom", "left"] as const).map((side) => (
              <CheckField
                key={side}
                label={t(`fields.side.${side}`)}
                checked={border.sides.includes(side)}
                onChange={(checked) => onChange({ ...border, sides: checked ? [...border.sides, side] : border.sides.filter((item) => item !== side) })}
              />
            ))}
          </div>
          <div className="studio-field-span">
            <ColorField label={t("fields.borderColor")} value={border.color} allowEmpty={false} onChange={(color) => onChange({ ...border, color: color ?? "$brand.border" })} />
          </div>
        </div>
      )}
    </fieldset>
  );
}

/** Datenbindung aus der Registry wählen (gruppiert, gefiltert nach Typ, mit item.* im Wiederholungskontext). */
export function BindingSelect({ value, onChange, types, scope, label, allowEmpty = true }: { value: string | null | undefined; onChange: (path: string | null) => void; types?: BindingInfo["type"][]; scope?: string | null; label?: string; allowEmpty?: boolean }) {
  const t = useTranslations("documentStudio");
  const { catalog, capabilities, documentType } = useDesigner();
  const needsProtocolOk = catalog.document_types.find((item) => item.key === documentType)?.needs_protocol ?? false;
  const scopeBinding = scope ? catalog.bindings.find((item) => item.path === scope) : null;
  const allowed = (binding: BindingInfo) => (!types || types.includes(binding.type));
  const groups = useMemo(() => {
    const result: Record<string, BindingInfo[]> = {};
    for (const binding of catalog.bindings) if (allowed(binding)) (result[binding.group] ??= []).push(binding);
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.bindings, types]);
  const restricted = (binding: BindingInfo) => (binding.access === "finance" && !capabilities.finance_data) || (binding.access === "writer" && !capabilities.personal_data);
  const select = (
    <select value={value ?? ""} onChange={(event) => onChange(event.target.value || null)} aria-label={label ?? t("fields.dataSource")}>
      {allowEmpty && <option value="">{t("fields.noBinding")}</option>}
      {scopeBinding && (
        <optgroup label={t("fields.itemFields", { list: bindingLabel(t, scopeBinding.path) })}>
          {scopeBinding.item_fields
            .filter((field) => !types || types.includes(field.type as BindingInfo["type"]))
            .map((field) => (
              <option key={field.key} value={`item.${field.key}`}>
                {bindingLabel(t, `item.${field.key}`)}
              </option>
            ))}
        </optgroup>
      )}
      {Object.entries(groups).map(([group, bindings]) => (
        <optgroup key={group} label={t(`bindingGroup.${group}`)}>
          {bindings.map((binding) => (
            <option key={binding.path} value={binding.path} disabled={restricted(binding)}>
              {bindingLabel(t, binding.path)}
              {binding.needs_protocol && !needsProtocolOk ? ` (${t("fields.needsProtocol")})` : ""}
              {restricted(binding) ? ` (${t("fields.noPermission")})` : ""}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
  return label ? <Field label={label}>{select}</Field> : select;
}

function FormatOptions({ binding, value, onChange }: { binding: BindingInfo | undefined; value: FormatSpec | undefined; onChange: (value: FormatSpec) => void }) {
  const t = useTranslations("documentStudio");
  const format = value ?? {};
  if (!binding) return null;
  return (
    <div className="studio-inline-format">
      {binding.type === "date" && (
        <select value={format.date ?? "short"} onChange={(event) => onChange({ ...format, date: event.target.value as FormatSpec["date"] })} aria-label={t("fields.dateFormat")}>
          {(["short", "long", "weekday", "month_year", "year"] as const).map((item) => (
            <option key={item} value={item}>
              {t(`fields.dateFormatValue.${item}`)}
            </option>
          ))}
        </select>
      )}
      {binding.type === "number" && (
        <select value={format.number ?? "integer"} onChange={(event) => onChange({ ...format, number: event.target.value as FormatSpec["number"] })} aria-label={t("fields.numberFormat")}>
          {(["integer", "decimal", "percent", "amount"] as const).map((item) => (
            <option key={item} value={item}>
              {t(`fields.numberFormatValue.${item}`)}
            </option>
          ))}
        </select>
      )}
      <select value={format.transform ?? "none"} onChange={(event) => onChange({ ...format, transform: event.target.value as FormatSpec["transform"] })} aria-label={t("fields.transform")}>
        {(["none", "upper", "lower"] as const).map((item) => (
          <option key={item} value={item}>
            {t(`fields.transformValue.${item}`)}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Text mit eingebetteten Datenfeldern. Segmente: Text, Datenfeld, Zeilenumbruch. */
export function TextContentEditor({ value, onChange, scope, mergeKey, label }: { value: TextContent | null | undefined; onChange: (value: TextContent, mergeKey?: string) => void; scope?: string | null; mergeKey: string; label: string }) {
  const t = useTranslations("documentStudio");
  const tPdf = useTranslations("documentPdf");
  const { catalog, mode } = useDesigner();
  const [language, setLanguage] = useState<string>("default");
  const content: TextContent = value ?? { default: [] };
  const inlines = language === "default" ? content.default : content.translations?.[language] ?? [];
  const setInlines = (next: Inline[], key: string) => {
    if (language === "default") onChange({ ...content, default: next }, `${mergeKey}:${key}`);
    else onChange({ ...content, translations: { ...(content.translations ?? {}), [language]: next } }, `${mergeKey}:${language}:${key}`);
  };
  const update = (index: number, inline: Inline, key: string) => setInlines(inlines.map((item, itemIndex) => (itemIndex === index ? inline : item)), `${index}:${key}`);
  const remove = (index: number) => setInlines(inlines.filter((_, itemIndex) => itemIndex !== index), `remove:${index}`);
  return (
    <fieldset className="studio-fieldset studio-text-editor">
      <legend className="field-label">{label}</legend>
      {modeAllows(mode, "expert") && (
        <div className="studio-language-tabs" role="tablist" aria-label={t("fields.translations")}>
          {["default", ...locales].map((code) => (
            <button key={code} type="button" role="tab" aria-selected={language === code} className={language === code ? "button-pill button-pill-active" : "button-pill"} onClick={() => setLanguage(code)}>
              {code === "default" ? t("fields.allLanguages") : code.toUpperCase()}
            </button>
          ))}
        </div>
      )}
      {language !== "default" && <p className="field-help">{t("fields.translationHelp")}</p>}
      {inlines.map((inline, index) => (
        <div key={index} className="studio-inline-row">
          {inline.t === "text" && (
            <textarea rows={1} className="studio-inline-text" value={inline.v} aria-label={t("fields.textSegment")} onChange={(event) => update(index, { ...inline, v: event.target.value }, "text")} />
          )}
          {inline.t === "key" && <span className="studio-binding-chip studio-binding-chip-static">{tPdf.has(inline.key) ? tPdf(inline.key) : inline.key}</span>}
          {inline.t === "br" && <span className="studio-inline-break">{t("fields.lineBreak")}</span>}
          {inline.t === "bind" && (
            <div className="studio-inline-binding">
              <BindingSelect value={inline.path} allowEmpty={false} scope={scope} types={["text", "date", "number", "amount", "percent", "bool", "list"]} onChange={(path) => path && update(index, { ...inline, path }, "path")} />
              <FormatOptions binding={inline.path.startsWith("item.") ? undefined : catalog.bindings.find((item) => item.path === inline.path)} value={inline.format} onChange={(format) => update(index, { ...inline, format }, "format")} />
              <input value={inline.fallback ?? ""} placeholder={t("fields.fallback")} aria-label={t("fields.fallback")} onChange={(event) => update(index, { ...inline, fallback: event.target.value }, "fallback")} />
            </div>
          )}
          {inline.t !== "br" && (
            <span className="studio-inline-marks">
              <button type="button" className={inline.b ? "button-icon-soft button-icon-soft-sm studio-mark-active" : "button-icon-soft button-icon-soft-sm"} aria-pressed={!!inline.b} aria-label={t("fields.bold")} onClick={() => update(index, { ...inline, b: !inline.b } as Inline, "b")}>
                B
              </button>
              <button type="button" className={inline.i ? "button-icon-soft button-icon-soft-sm studio-mark-active" : "button-icon-soft button-icon-soft-sm"} aria-pressed={!!inline.i} aria-label={t("fields.italic")} onClick={() => update(index, { ...inline, i: !inline.i } as Inline, "i")}>
                I
              </button>
            </span>
          )}
          <button type="button" className="button-icon-soft button-icon-soft-sm button-icon-soft-danger" aria-label={t("fields.removeSegment")} onClick={() => remove(index)}>
            ✕
          </button>
        </div>
      ))}
      <div className="studio-inline-add">
        <button type="button" className="button-secondary button-ghost" onClick={() => setInlines([...inlines, { t: "text", v: "" }], "addText")}>
          {t("fields.addText")}
        </button>
        <button type="button" className="button-secondary button-ghost" onClick={() => setInlines([...inlines, { t: "bind", path: scope ? `item.${catalog.bindings.find((item) => item.path === scope)?.item_fields[0]?.key ?? "name"}` : "document.title" }], "addBinding")}>
          {t("fields.addBinding")}
        </button>
        <button type="button" className="button-secondary button-ghost" onClick={() => setInlines([...inlines, { t: "br" }], "addBreak")}>
          {t("fields.addBreak")}
        </button>
      </div>
    </fieldset>
  );
}

const COMPARE_OPS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains"] as const;
type Rule = Exclude<Condition, { op: "all" | "any" | "not" }>;

function ruleOf(condition: Condition): { rule: Rule; negated: boolean } | null {
  if (condition.op === "not" && condition.item.op !== "all" && condition.item.op !== "any" && condition.item.op !== "not") return { rule: condition.item as Rule, negated: true };
  if (condition.op !== "all" && condition.op !== "any" && condition.op !== "not") return { rule: condition as Rule, negated: false };
  return null;
}

/** Sichtbarkeitsregel visuell: «Anzeigen, wenn [alle|eine] der Regeln zutreffen». */
export function ConditionEditor({ value, onChange, scope }: { value: Condition | null | undefined; onChange: (value: Condition | null) => void; scope?: string | null }) {
  const t = useTranslations("documentStudio");
  const group: { op: "all" | "any"; items: Condition[] } = !value ? { op: "all", items: [] } : value.op === "all" || value.op === "any" ? value : { op: "all", items: [value] };
  const rules = group.items.map(ruleOf);
  const emit = (op: "all" | "any", items: Condition[]) => onChange(items.length === 0 ? null : items.length === 1 && op === "all" ? items[0] : { op, items });
  const setRule = (index: number, rule: Rule, negated: boolean) => emit(group.op, group.items.map((item, itemIndex) => (itemIndex === index ? (negated ? { op: "not", item: rule } : rule) : item)));
  return (
    <fieldset className="studio-fieldset">
      <legend className="field-label">{t("condition.title")}</legend>
      {group.items.length === 0 ? (
        <p className="field-help">{t("condition.always")}</p>
      ) : (
        <Field label={t("condition.combine")}>
          <select value={group.op} onChange={(event) => emit(event.target.value as "all" | "any", group.items)}>
            <option value="all">{t("condition.all")}</option>
            <option value="any">{t("condition.any")}</option>
          </select>
        </Field>
      )}
      {rules.map((entry, index) => {
        if (!entry) return <p key={index} className="field-help">{t("condition.complex")}</p>;
        const { rule, negated } = entry;
        const operator = rule.op === "count" ? `count_${rule.cmp}` : rule.op;
        return (
          <div key={index} className="studio-condition-rule">
            <BindingSelect value={rule.path} allowEmpty={false} scope={scope} onChange={(path) => path && setRule(index, { ...rule, path } as Rule, negated)} />
            <select
              value={negated ? `not_${operator}` : operator}
              aria-label={t("condition.operator")}
              onChange={(event) => {
                let next = event.target.value;
                const isNot = next.startsWith("not_");
                if (isNot) next = next.slice(4);
                if (next.startsWith("count_")) setRule(index, { op: "count", path: rule.path, cmp: next.slice(6) as "gt", value: "value" in rule && typeof rule.value === "number" ? rule.value : 0 }, isNot);
                else if (next === "exists" || next === "empty") setRule(index, { op: next, path: rule.path }, isNot);
                else setRule(index, { op: next as (typeof COMPARE_OPS)[number], path: rule.path, value: "value" in rule ? (rule.value as string) : "" }, isNot);
              }}
            >
              {["exists", "empty", ...COMPARE_OPS, "count_gt", "count_eq", "count_lt"].map((op) => (
                <option key={op} value={op}>
                  {t(`condition.op.${op}`)}
                </option>
              ))}
              <option value="not_exists">{t("condition.op.not_exists")}</option>
            </select>
            {rule.op !== "exists" && rule.op !== "empty" && rule.op !== "in" && rule.op !== "not_in" && (
              <input
                aria-label={t("condition.value")}
                value={"value" in rule ? String(rule.value ?? "") : ""}
                type={rule.op === "count" ? "number" : "text"}
                onChange={(event) => setRule(index, { ...rule, value: rule.op === "count" ? Number(event.target.value || 0) : event.target.value } as Rule, negated)}
              />
            )}
            <button type="button" className="button-icon-soft button-icon-soft-sm button-icon-soft-danger" aria-label={t("condition.remove")} onClick={() => emit(group.op, group.items.filter((_, itemIndex) => itemIndex !== index))}>
              ✕
            </button>
          </div>
        );
      })}
      <button type="button" className="button-secondary button-ghost" onClick={() => emit(group.op, [...group.items, { op: "exists", path: "document.title" }])}>
        {t("condition.add")}
      </button>
    </fieldset>
  );
}
