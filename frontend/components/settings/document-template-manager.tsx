"use client";

import { Dispatch, FormEvent, SetStateAction, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { DocumentTemplate, DocumentTemplatePart } from "@/types/api";

type Props = {
  initialTemplates: DocumentTemplate[];
  initialParts: DocumentTemplatePart[];
};

type PartFormState = {
  name: string;
  part_type: string;
  description: string;
  version: string;
  is_active: boolean;
  file: File | null;
};

type TemplateFormState = {
  code: string;
  name: string;
  description: string;
  version: string;
  is_active: boolean;
  is_default: boolean;
  primary_color: string;
  secondary_color: string;
  font_family: string;
  font_size: string;
  font_regular: string;
  font_bold: string;
  font_italic: string;
  font_bold_italic: string;
  preset_header: string;
  preset_footer: string;
  preset_title_page: string;
  preset_toc: string;
  numbering_mode: string;
  preamble: string;
  macros: string;
  title_page: string;
  header_footer: string;
  toc: string;
  element_text: string;
  element_todo: string;
  element_image: string;
  element_static_text: string;
  element_form: string;
  element_events: string;
  element_bullet_list: string;
  element_attendance: string;
  element_session_date: string;
  title_header_image: string;
  title_footer_image: string;
  title_text_line1: string;
  title_text_line2: string;
  title_org_name: string;
  title_location: string;
  title_footer_contact: string;
  title_footer_color: string;
  toc_spacing: string;
  show_metadata: boolean;
};

const latexSlotDefinitions = [
  { key: "preamble",              label: "LaTeX — Präambel",            help: "LaTeX-Pakete und globale Einstellungen." },
  { key: "macros",                label: "LaTeX — Makros",              help: "Wiederverwendbare Befehle und Hilfsfunktionen." },
  { key: "title_page",            label: "Layout — Titelblatt",         help: "Überschreibt das gewählte Titelblatt-Preset." },
  { key: "header_footer",         label: "Layout — Kopf- & Fusszeile",  help: "Überschreibt die gewählten Header/Footer-Presets." },
  { key: "toc",                   label: "Layout — Inhaltsverzeichnis", help: "Überschreibt das gewählte Inhaltsverzeichnis-Preset." },
  { key: "element_text",          label: "Element — Text",              help: "Wie Textblöcke im PDF gerendert werden." },
  { key: "element_todo",          label: "Element — Todo-Liste",        help: "Wie Todo-Listen im PDF gerendert werden." },
  { key: "element_image",         label: "Element — Bild",              help: "Wie Bilder im PDF gerendert werden." },
  { key: "element_static_text",   label: "Element — Statischer Text",   help: "Wie fixer Text im PDF gerendert wird." },
  { key: "element_form",          label: "Element — Formular",          help: "Wie Formularzeilen im PDF gerendert werden." },
  { key: "element_events",        label: "Element — Terminliste",       help: "Wie Terminlisten im PDF gerendert werden." },
  { key: "element_bullet_list",   label: "Element — Aufzählung",        help: "Wie Aufzählungen im PDF gerendert werden." },
  { key: "element_attendance",    label: "Element — Anwesenheit",       help: "Wie Anwesenheitslisten im PDF gerendert werden." },
  { key: "element_session_date",  label: "Element — Sitzungsdatum",     help: "Wie das nächste Sitzungsdatum im PDF gerendert wird." },
] as const;

const fontSlotDefinitions = [
  { key: "font_regular",     label: "Schrift — Regular",     help: "Haupt-Fontdatei (.ttf oder .otf)" },
  { key: "font_bold",        label: "Schrift — Fett",        help: "Optionale Fett-Variante." },
  { key: "font_italic",      label: "Schrift — Kursiv",      help: "Optionale Kursiv-Variante." },
  { key: "font_bold_italic", label: "Schrift — Fett Kursiv", help: "Optionale Fett-Kursiv-Variante." },
] as const;

const imageSlotDefinitions = [
  { key: "title_header_image", label: "Bild — Titelblatt Logo",        help: "Logo oben links auf dem Titelblatt (.png, .jpg, .svg)" },
  { key: "title_footer_image", label: "Bild — Titelblatt Footer",      help: "Bild unten links auf dem Titelblatt (.png, .jpg, .svg)" },
] as const;

const imagePartTypes = new Set(imageSlotDefinitions.map((d) => d.key));

const partTypeGroups = [
  { label: "Bilder",      defs: imageSlotDefinitions },
  { label: "Schriftart",  defs: fontSlotDefinitions },
  { label: "LaTeX / Erweitert", defs: latexSlotDefinitions },
] as const;

const partTypeDefinitions = [...latexSlotDefinitions, ...fontSlotDefinitions, ...imageSlotDefinitions] as const;
const partTypeOptions = partTypeDefinitions.map((entry) => entry.key);
const fontPartTypes = new Set(fontSlotDefinitions.map((entry) => entry.key));

const initialPartForm: PartFormState = {
  name: "", part_type: "title_header_image", description: "", version: "1", is_active: true, file: null,
};

const initialTemplateForm: TemplateFormState = {
  code: "", name: "", description: "", version: "1", is_active: true, is_default: false,
  primary_color: "174B7A", secondary_color: "4F6D7A",
  font_family: "arial", font_size: "11pt",
  font_regular: "", font_bold: "", font_italic: "", font_bold_italic: "",
  preset_header: "standard", preset_footer: "standard",
  preset_title_page: "modern", preset_toc: "standard",
  numbering_mode: "sections",
  preamble: "", macros: "", title_page: "", header_footer: "", toc: "",
  element_text: "", element_todo: "", element_image: "", element_static_text: "",
  element_form: "", element_events: "", element_bullet_list: "",
  element_attendance: "", element_session_date: "",
  title_header_image: "", title_footer_image: "",
  title_text_line1: "", title_text_line2: "",
  title_org_name: "", title_location: "", title_footer_contact: "",
  title_footer_color: "444444",
  toc_spacing: "normal",
  show_metadata: false,
};

function templateFormFromTemplate(template: DocumentTemplate): TemplateFormState {
  const config = (template.configuration_json ?? {}) as Record<string, any>;
  const theme = config.theme ?? {};
  const options = config.options ?? {};
  const slots = config.slots ?? {};
  const fontParts = theme.font_parts ?? {};
  const presets = config.presets ?? {};
  return {
    code: template.code,
    name: template.name,
    description: template.description ?? "",
    version: String(template.version),
    is_active: template.is_active,
    is_default: template.is_default,
    primary_color: theme.primary_color ?? "174B7A",
    secondary_color: theme.secondary_color ?? "4F6D7A",
    font_family: theme.font_family ?? "arial",
    font_size: theme.font_size ?? "11pt",
    font_regular: fontParts.font_regular ? String(fontParts.font_regular) : "",
    font_bold: fontParts.font_bold ? String(fontParts.font_bold) : "",
    font_italic: fontParts.font_italic ? String(fontParts.font_italic) : "",
    font_bold_italic: fontParts.font_bold_italic ? String(fontParts.font_bold_italic) : "",
    preset_header: presets.header ?? "standard",
    preset_footer: presets.footer ?? "standard",
    preset_title_page: presets.title_page ?? "modern",
    preset_toc: presets.toc ?? "standard",
    numbering_mode: options.numbering_mode ?? "sections",
    toc_spacing: options.toc_spacing ?? "normal",
    preamble: slots.preamble ? String(slots.preamble) : "",
    macros: slots.macros ? String(slots.macros) : "",
    title_page: slots.title_page ? String(slots.title_page) : "",
    header_footer: slots.header_footer ? String(slots.header_footer) : "",
    toc: slots.toc ? String(slots.toc) : "",
    element_text: slots.element_text ? String(slots.element_text) : "",
    element_todo: slots.element_todo ? String(slots.element_todo) : "",
    element_image: slots.element_image ? String(slots.element_image) : "",
    element_static_text: slots.element_static_text ? String(slots.element_static_text) : "",
    element_form: slots.element_form ? String(slots.element_form) : "",
    element_events: slots.element_events ? String(slots.element_events) : "",
    element_bullet_list: slots.element_bullet_list ? String(slots.element_bullet_list) : "",
    element_attendance: slots.element_attendance ? String(slots.element_attendance) : "",
    element_session_date: slots.element_session_date ? String(slots.element_session_date) : "",
    title_header_image: (config.title_assets as any)?.header_image_part_id ? String((config.title_assets as any).header_image_part_id) : "",
    title_footer_image: (config.title_assets as any)?.footer_image_part_id ? String((config.title_assets as any).footer_image_part_id) : "",
    title_text_line1: (config.title_text as any)?.line1 ?? "",
    title_text_line2: (config.title_text as any)?.line2 ?? "",
    title_org_name: (config.title_text as any)?.org_name ?? "",
    title_location: (config.title_text as any)?.location ?? "",
    title_footer_contact: (config.title_text as any)?.footer_contact ?? "",
    title_footer_color: (config.title_text as any)?.footer_color ?? "444444",
    show_metadata: !(options.hide_metadata ?? true),
  };
}

function buildTemplatePayload(form: TemplateFormState) {
  return {
    tenant_id: 1,
    code: form.code,
    name: form.name,
    description: form.description || null,
    version: Number(form.version),
    is_active: form.is_active,
    is_default: form.is_default,
    configuration_json: {
      theme: {
        primary_color: form.primary_color,
        secondary_color: form.secondary_color,
        font_family: form.font_family,
        font_size: form.font_size,
        font_parts: Object.fromEntries(
          ["font_regular", "font_bold", "font_italic", "font_bold_italic"]
            .filter((slot) => form[slot as keyof TemplateFormState])
            .map((slot) => [slot, Number(form[slot as keyof TemplateFormState] as string)])
        ),
      },
      presets: {
        header: form.preset_header,
        footer: form.preset_footer,
        title_page: form.preset_title_page,
        toc: form.preset_title_page === "combined_toc" ? "standard" : form.preset_toc,
      },
      options: {
        show_toc: form.preset_title_page === "combined_toc" || form.preset_toc !== "none",
        numbering_mode: form.numbering_mode,
        toc_spacing: form.toc_spacing,
        hide_metadata: !form.show_metadata,
      },
      title_assets: {
        header_image_part_id: form.title_header_image ? Number(form.title_header_image) : null,
        footer_image_part_id: form.title_footer_image ? Number(form.title_footer_image) : null,
      },
      title_text: {
        line1: form.title_text_line1,
        line2: form.title_text_line2,
        org_name: form.title_org_name,
        location: form.title_location,
        footer_contact: form.title_footer_contact,
        footer_color: form.title_footer_color,
      },
      slots: Object.fromEntries(
        ["preamble", "macros", "title_page", "header_footer", "toc",
          "element_text", "element_todo", "element_image", "element_static_text",
          "element_form", "element_events", "element_bullet_list",
          "element_attendance", "element_session_date"]
          .filter((slot) => form[slot as keyof TemplateFormState])
          .map((slot) => [slot, Number(form[slot as keyof TemplateFormState] as string)])
      ),
    },
  };
}

// ── SVG page mockup helpers ──────────────────────────────────────────────────

function PageMockup({ children, bg = "white" }: { children?: React.ReactNode; bg?: string }) {
  return (
    <svg viewBox="0 0 60 82" width="60" height="82" style={{ display: "block", margin: "0 auto" }}>
      <rect x="3" y="3" width="55" height="77" rx="2" fill="#d8d8d8" />
      <rect x="2" y="2" width="55" height="77" rx="2" fill={bg} stroke="#e0e0e0" strokeWidth="0.6" />
      {children}
    </svg>
  );
}

const CONTENT_LINES = [14, 19, 24, 29, 34, 39, 44, 49, 54];

function ContentLines({ from = 0, count = 6, accent = "#e4e4e4" }: { from?: number; count?: number; accent?: string }) {
  return (
    <>
      {CONTENT_LINES.slice(from, from + count).map((y, i) => (
        <rect key={y} x="8" y={y} width={i % 3 === 2 ? 30 : 42} height="1.8" fill={accent} rx="0.9" />
      ))}
    </>
  );
}

// ── Header previews ──────────────────────────────────────────────────────────

const headerPreviews: Record<string, React.ReactNode> = {
  none: (
    <PageMockup>
      <ContentLines />
    </PageMockup>
  ),
  minimal: (
    <PageMockup>
      <rect x="44" y="5.5" width="10" height="1.8" fill="#bbb" rx="0.9" />
      <ContentLines from={1} />
    </PageMockup>
  ),
  standard: (
    <PageMockup>
      <rect x="8" y="5.5" width="20" height="1.8" fill="#aaa" rx="0.9" />
      <rect x="42" y="5.5" width="12" height="1.8" fill="#aaa" rx="0.9" />
      <line x1="8" y1="9.5" x2="54" y2="9.5" stroke="#ddd" strokeWidth="0.7" />
      <ContentLines from={1} />
    </PageMockup>
  ),
  bar: (
    <PageMockup>
      <rect x="2" y="2" width="55" height="10" fill="var(--dt-accent, #174B7A)" rx="2" />
      <rect x="8" y="5" width="22" height="2" fill="rgba(255,255,255,0.85)" rx="1" />
      <rect x="42" y="5" width="10" height="2" fill="rgba(255,255,255,0.6)" rx="1" />
      <ContentLines from={1} />
    </PageMockup>
  ),
};

// ── Footer previews ──────────────────────────────────────────────────────────

const footerPreviews: Record<string, React.ReactNode> = {
  none: (
    <PageMockup>
      <ContentLines />
    </PageMockup>
  ),
  minimal: (
    <PageMockup>
      <ContentLines count={5} />
      <rect x="26" y="72" width="6" height="1.8" fill="#bbb" rx="0.9" />
    </PageMockup>
  ),
  standard: (
    <PageMockup>
      <ContentLines count={5} />
      <line x1="8" y1="70" x2="54" y2="70" stroke="#ddd" strokeWidth="0.7" />
      <rect x="8" y="72" width="16" height="1.8" fill="#aaa" rx="0.9" />
      <rect x="46" y="72" width="8" height="1.8" fill="#aaa" rx="0.9" />
    </PageMockup>
  ),
  with_version: (
    <PageMockup>
      <ContentLines count={5} />
      <line x1="8" y1="70" x2="54" y2="70" stroke="#ddd" strokeWidth="0.7" />
      <rect x="8" y="72" width="16" height="1.8" fill="#aaa" rx="0.9" />
      <rect x="24" y="72" width="10" height="1.8" fill="#bbb" rx="0.9" />
      <rect x="46" y="72" width="8" height="1.8" fill="#aaa" rx="0.9" />
    </PageMockup>
  ),
};

// ── Title page previews ──────────────────────────────────────────────────────

const titlePagePreviews: Record<string, React.ReactNode> = {
  none: (
    <PageMockup>
      <ContentLines />
    </PageMockup>
  ),
  minimal: (
    <PageMockup>
      <rect x="10" y="22" width="38" height="4" fill="var(--dt-accent, #174B7A)" rx="2" />
      <rect x="18" y="29" width="22" height="2" fill="#bbb" rx="1" />
      <line x1="22" y1="35" x2="36" y2="35" stroke="var(--dt-accent, #174B7A)" strokeWidth="1.2" />
      <rect x="16" y="46" width="10" height="1.6" fill="#ddd" rx="0.8" />
      <rect x="29" y="46" width="16" height="1.6" fill="#ddd" rx="0.8" />
    </PageMockup>
  ),
  modern: (
    <PageMockup>
      <rect x="2" y="2" width="55" height="26" fill="var(--dt-accent, #174B7A)" rx="2" />
      <rect x="8" y="9" width="34" height="4" fill="rgba(255,255,255,0.9)" rx="2" />
      <rect x="8" y="16" width="22" height="2.2" fill="rgba(255,255,255,0.55)" rx="1.1" />
      <rect x="8" y="36" width="10" height="1.8" fill="#ccc" rx="0.9" />
      <rect x="22" y="36" width="20" height="1.8" fill="#ddd" rx="0.9" />
      <rect x="8" y="41" width="10" height="1.8" fill="#ccc" rx="0.9" />
      <rect x="22" y="41" width="16" height="1.8" fill="#ddd" rx="0.9" />
      <line x1="8" y1="70" x2="54" y2="70" stroke="var(--dt-accent, #174B7A)" strokeWidth="1" />
      <line x1="8" y1="72" x2="54" y2="72" stroke="#bbb" strokeWidth="0.5" />
    </PageMockup>
  ),
  bold: (
    <PageMockup bg="var(--dt-accent, #174B7A)">
      <rect x="8" y="22" width="42" height="5" fill="rgba(255,255,255,0.9)" rx="2.5" />
      <rect x="16" y="31" width="26" height="2.5" fill="rgba(255,255,255,0.5)" rx="1.25" />
      <line x1="18" y1="39" x2="40" y2="39" stroke="rgba(255,255,255,0.35)" strokeWidth="0.8" />
      <rect x="20" y="46" width="18" height="2" fill="rgba(255,255,255,0.6)" rx="1" />
      <rect x="22" y="51" width="14" height="2" fill="rgba(255,255,255,0.4)" rx="1" />
    </PageMockup>
  ),
};

const combinedTocPreview = (
  <PageMockup>
    {/* Logo top left */}
    <rect x="5" y="5" width="9" height="9" fill="var(--dt-accent, #174B7A)" rx="1" opacity="0.7" />
    {/* Colored boxes center */}
    <rect x="17" y="5" width="22" height="4" fill="var(--dt-accent, #174B7A)" rx="1" />
    <rect x="17" y="10" width="22" height="4" fill="var(--dt-accent, #174B7A)" rx="1" />
    {/* Title top right */}
    <rect x="42" y="5" width="13" height="3" fill="#aaa" rx="1" />
    <rect x="42" y="9" width="10" height="2" fill="#ccc" rx="1" />
    {/* Org name */}
    <rect x="5" y="17" width="16" height="2" fill="var(--dt-accent, #174B7A)" rx="1" />
    <rect x="40" y="17" width="15" height="2" fill="#ddd" rx="1" />
    {/* TOC heading */}
    <rect x="5" y="22" width="20" height="3" fill="#666" rx="1.5" />
    {/* TOC entries */}
    {[28, 32, 36, 40, 44, 48].map((y, i) => (
      <g key={y}>
        <rect x={5 + (i % 3 === 0 ? 0 : 3)} y={y} width={i % 3 === 0 ? 36 : 30} height="1.8" fill="#e0e0e0" rx="0.9" />
        <rect x="47" y={y} width="6" height="1.8" fill="#eee" rx="0.9" />
      </g>
    ))}
    {/* Footer image left */}
    <rect x="5" y="67" width="25" height="8" fill="#ddd" rx="1" opacity="0.6" />
    {/* Footer text right */}
    <rect x="35" y="69" width="18" height="1.6" fill="#ccc" rx="0.8" />
    <rect x="35" y="72" width="14" height="1.6" fill="#ccc" rx="0.8" />
  </PageMockup>
);

// ── TOC previews ─────────────────────────────────────────────────────────────

const tocPreviews: Record<string, React.ReactNode> = {
  none: (
    <PageMockup>
      <rect x="8" y="8" width="30" height="3" fill="var(--dt-accent, #174B7A)" rx="1.5" />
      <ContentLines from={1} />
    </PageMockup>
  ),
  standard: (
    <PageMockup>
      <rect x="8" y="7" width="22" height="2.5" fill="#888" rx="1.25" />
      {[13, 18, 23, 28, 33].map((y, i) => (
        <g key={y}>
          <rect x={8 + (i % 2 === 0 ? 0 : 4)} y={y} width={i % 2 === 0 ? 34 : 28} height="1.8" fill="#ddd" rx="0.9" />
          <rect x={46} y={y} width="6" height="1.8" fill="#e8e8e8" rx="0.9" />
        </g>
      ))}
    </PageMockup>
  ),
  compact: (
    <PageMockup>
      <rect x="8" y="7" width="18" height="2" fill="#888" rx="1" />
      {[12, 16, 20, 24, 28, 32, 36].map((y, i) => (
        <g key={y}>
          <rect x={8 + (i % 3 === 0 ? 0 : 3)} y={y} width={i % 3 === 0 ? 34 : 28} height="1.4" fill="#ddd" rx="0.7" />
          <rect x={46} y={y} width="5" height="1.4" fill="#e8e8e8" rx="0.7" />
        </g>
      ))}
    </PageMockup>
  ),
};

// ── Generic preset card grid ─────────────────────────────────────────────────

type PresetOption = { value: string; label: string; description: string; preview: React.ReactNode };

function PresetCardGrid({
  options, value, onChange, accentColor,
}: {
  options: PresetOption[];
  value: string;
  onChange: (v: string) => void;
  accentColor?: string;
}) {
  return (
    <div
      className="block-type-grid"
      style={{ "--dt-accent": accentColor ? `#${accentColor}` : "#174B7A" } as React.CSSProperties}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`block-type-card${value === opt.value ? " block-type-card-active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          <div className="preset-card-preview">{opt.preview}</div>
          <div className="block-type-summary">
            <strong>{opt.label}</strong>
            <span className="muted" style={{ fontSize: "0.78rem" }}>{opt.description}</span>
          </div>
        </button>
      ))}
    </div>
  );
}

// ── Color picker ─────────────────────────────────────────────────────────────

function ColorField({
  label, value, onChange,
}: {
  label: string;
  value: string;
  onChange: (hex: string) => void;
}) {
  const safe = value.replace("#", "");
  return (
    <div className="color-field">
      <span className="field-label">{label}</span>
      <div className="color-field-row">
        <label className="color-swatch-label" title="Farbe wählen">
          <div className="color-swatch" style={{ backgroundColor: `#${safe}` }} />
          <input
            type="color"
            value={`#${safe}`}
            onChange={(e) => onChange(e.target.value.slice(1).toUpperCase())}
            className="color-input-hidden"
          />
        </label>
        <input
          className="color-hex-input"
          maxLength={6}
          value={safe}
          onChange={(e) => {
            const v = e.target.value.replace(/[^0-9a-fA-F]/g, "").toUpperCase();
            if (v.length <= 6) onChange(v);
          }}
          placeholder="RRGGBB"
        />
      </div>
    </div>
  );
}

// ── Font family cards ────────────────────────────────────────────────────────

const fontOptions = [
  { value: "arial", label: "Arial", description: "Klassisch, gut lesbar", sample: "Aa", style: { fontFamily: "Arial, sans-serif" } },
  { value: "helvet", label: "Helvetica", description: "Modern, neutral", sample: "Aa", style: { fontFamily: "Helvetica, Arial, sans-serif" } },
  { value: "palatino", label: "Palatino", description: "Elegant, seriös", sample: "Aa", style: { fontFamily: "Palatino, Georgia, serif" } },
  { value: "century_gothic", label: "Century Gothic", description: "Geometrisch, modern", sample: "Aa", style: { fontFamily: "Century Gothic, Futura, sans-serif" } },
  { value: "uploaded", label: "Eigene Schrift", description: "Font-Dateien hochladen", sample: "↑", style: {} },
] as const;

function FontFamilyPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="block-type-grid">
      {fontOptions.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`block-type-card font-family-card${value === opt.value ? " block-type-card-active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          <div className="font-sample" style={opt.style}>{opt.sample}</div>
          <div className="block-type-summary">
            <strong style={opt.style}>{opt.label}</strong>
            <span className="muted" style={{ fontSize: "0.78rem" }}>{opt.description}</span>
          </div>
        </button>
      ))}
    </div>
  );
}

// ── TemplateForm with tabs ───────────────────────────────────────────────────

function TemplateForm({
  form,
  setForm,
  partsByType,
  allParts = [],
}: {
  form: TemplateFormState;
  setForm: Dispatch<SetStateAction<TemplateFormState>>;
  partsByType: Record<string, DocumentTemplatePart[]>;
  allParts?: DocumentTemplatePart[];
}) {
  const imageParts = useMemo(
    () => allParts.filter((p) => /\.(png|jpg|jpeg|svg|webp)$/i.test(p.storage_path)),
    [allParts]
  );
  const [activeTab, setActiveTab] = useState<"design" | "structure" | "advanced">("design");

  const headerOptions: PresetOption[] = [
    { value: "none", label: "Kein Header", description: "Seite ohne Kopfzeile", preview: headerPreviews.none },
    { value: "minimal", label: "Seitennummer", description: "Nur Seitennummer oben rechts", preview: headerPreviews.minimal },
    { value: "standard", label: "Titel & Datum", description: "Titel links, Datum rechts", preview: headerPreviews.standard },
    { value: "bar", label: "Farbiger Balken", description: "Akzentfarbe mit weissem Text", preview: headerPreviews.bar },
  ];

  const footerOptions: PresetOption[] = [
    { value: "none", label: "Kein Footer", description: "Seite ohne Fusszeile", preview: footerPreviews.none },
    { value: "minimal", label: "Seitennummer", description: "Nur Seitennummer zentriert", preview: footerPreviews.minimal },
    { value: "standard", label: "Protokoll & Seite", description: "Protokollnummer links, Seite rechts", preview: footerPreviews.standard },
    { value: "with_version", label: "Mit Version", description: "Nummer links, Version mitte, Seite rechts", preview: footerPreviews.with_version },
  ];

  const titlePageOptions: PresetOption[] = [
    { value: "none", label: "Kein Titelblatt", description: "Direkt mit Inhalt starten", preview: titlePagePreviews.none },
    { value: "minimal", label: "Minimalistisch", description: "Zentrierter Titel, clean", preview: titlePagePreviews.minimal },
    { value: "modern", label: "Modern", description: "Farbiger Header-Block", preview: titlePagePreviews.modern },
    { value: "bold", label: "Bold", description: "Vollflächige Akzentfarbe", preview: titlePagePreviews.bold },
    { value: "combined_toc", label: "Titelblatt + Inhaltsverzeichnis", description: "Logo, Farb-Boxen, Titel & TOC auf einer Seite", preview: combinedTocPreview },
  ];

  const tocOptions: PresetOption[] = [
    { value: "none", label: "Kein Inhaltsverzeichnis", description: "Ohne Übersichtsseite", preview: tocPreviews.none },
    { value: "standard", label: "Standard", description: "Mit Seitenzahlen", preview: tocPreviews.standard },
    { value: "compact", label: "Kompakt", description: "Kleiner, dichter gesetzt", preview: tocPreviews.compact },
  ];

  const hasCustomSlot = (keys: string[]) => keys.some((k) => !!form[k as keyof TemplateFormState]);

  return (
    <div className="grid">
      {/* Metadata — always visible */}
      <div className="three-col">
        <label className="field-stack">
          <span className="field-label">Code</span>
          <input value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} required />
        </label>
        <label className="field-stack">
          <span className="field-label">Name</span>
          <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
        </label>
        <label className="field-stack">
          <span className="field-label">Version</span>
          <input type="number" min={1} value={form.version} onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))} />
        </label>
      </div>
      <div className="three-col">
        <label className="field-stack">
          <span className="field-label">Beschreibung</span>
          <input value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
        </label>
        <div style={{ display: "flex", gap: "20px", alignItems: "flex-end", paddingBottom: "4px" }}>
          <label className="checkbox-row">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
            Aktiv
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={form.is_default} onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))} />
            Standard für Tenant
          </label>
        </div>
      </div>

      {/* Tab nav */}
      <div className="segment-control" style={{ marginTop: "8px" }}>
        <button type="button" className={`segment-button${activeTab === "design" ? " segment-button-active" : ""}`} onClick={() => setActiveTab("design")}>
          Gestaltung
        </button>
        <button type="button" className={`segment-button${activeTab === "structure" ? " segment-button-active" : ""}`} onClick={() => setActiveTab("structure")}>
          Struktur
        </button>
        <button type="button" className={`segment-button${activeTab === "advanced" ? " segment-button-active" : ""}`} onClick={() => setActiveTab("advanced")}>
          Erweitert {hasCustomSlot(["preamble", "macros", "title_page", "header_footer", "toc"]) ? "·" : ""}
        </button>
      </div>

      {/* ── Gestaltung ── */}
      {activeTab === "design" && (
        <div className="grid">
          <div className="card inset-card">
            <div className="eyebrow">Farben</div>
            <div style={{ display: "flex", gap: "32px", flexWrap: "wrap", marginTop: "12px" }}>
              <ColorField
                label="Primärfarbe"
                value={form.primary_color}
                onChange={(v) => setForm((f) => ({ ...f, primary_color: v }))}
              />
              <ColorField
                label="Sekundärfarbe"
                value={form.secondary_color}
                onChange={(v) => setForm((f) => ({ ...f, secondary_color: v }))}
              />
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <div style={{ width: "80px", height: "80px", borderRadius: "12px", background: `linear-gradient(135deg, #${form.primary_color} 50%, #${form.secondary_color} 50%)`, border: "1px solid var(--border)", flexShrink: 0 }} />
                <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>Vorschau</div>
              </div>
            </div>
            <div style={{ marginTop: "10px" }}>
              <button type="button" className="button-inline" style={{ fontSize: "0.78rem" }}
                onClick={() => setForm((f) => ({ ...f, primary_color: "174B7A", secondary_color: "4F6D7A" }))}>
                Farben zurücksetzen
              </button>
            </div>
          </div>

          <div className="card inset-card">
            <div className="eyebrow">Schriftart</div>
            <div style={{ marginTop: "12px" }}>
              <FontFamilyPicker value={form.font_family} onChange={(v) => setForm((f) => ({ ...f, font_family: v }))} />
            </div>
            {(form.font_family === "century_gothic" || form.font_family === "uploaded") && (
              <div className="card inset-card" style={{ marginTop: "16px" }}>
                <div className="info-note" style={{ marginBottom: "12px" }}>
                  {form.font_family === "century_gothic"
                    ? "Century Gothic ist nicht vorinstalliert. Bitte die Font-Dateien hochladen."
                    : "Eigene Font-Dateien hochladen. Regular ist erforderlich, Varianten sind optional."}
                </div>
                <div className="four-col">
                  {fontSlotDefinitions.map(({ key, label, help }) => (
                    <label className="field-stack" key={key}>
                      <span className="field-label">{label}</span>
                      <select value={form[key as keyof TemplateFormState] as string} onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}>
                        <option value="">Keine</option>
                        {(partsByType[key] ?? []).map((part) => (
                          <option key={part.id} value={part.id}>{part.name}</option>
                        ))}
                      </select>
                      <span className="field-help">{help}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="card inset-card">
            <div className="eyebrow">Schriftgrösse</div>
            <div style={{ display: "flex", gap: "12px", marginTop: "12px", flexWrap: "wrap" }}>
              {(["10pt", "11pt", "12pt"] as const).map((size) => (
                <button
                  key={size}
                  type="button"
                  className={`block-type-card font-size-card${form.font_size === size ? " block-type-card-active" : ""}`}
                  onClick={() => setForm((f) => ({ ...f, font_size: size }))}
                  style={{ minWidth: "90px", padding: "14px 16px" }}
                >
                  <span style={{ fontSize: size === "10pt" ? "1.1rem" : size === "11pt" ? "1.3rem" : "1.5rem", fontWeight: 600 }}>Aa</span>
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "4px", display: "block" }}>{size}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Struktur ── */}
      {activeTab === "structure" && (
        <div className="grid">
          <div className="card inset-card"
            style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}
          >
            <div className="eyebrow">Kopfzeile (Header)</div>
            <p className="muted" style={{ marginTop: "4px", fontSize: "0.82rem" }}>Erscheint oben auf jeder Seite.</p>
            <div style={{ marginTop: "12px" }}>
              <PresetCardGrid options={headerOptions} value={form.preset_header} onChange={(v) => setForm((f) => ({ ...f, preset_header: v }))} accentColor={form.primary_color} />
            </div>
          </div>

          <div className="card inset-card"
            style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}
          >
            <div className="eyebrow">Fusszeile (Footer)</div>
            <p className="muted" style={{ marginTop: "4px", fontSize: "0.82rem" }}>Erscheint unten auf jeder Seite.</p>
            <div style={{ marginTop: "12px" }}>
              <PresetCardGrid options={footerOptions} value={form.preset_footer} onChange={(v) => setForm((f) => ({ ...f, preset_footer: v }))} accentColor={form.primary_color} />
            </div>
          </div>

          <div className="card inset-card"
            style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}
          >
            <div className="eyebrow">Titelblatt</div>
            <p className="muted" style={{ marginTop: "4px", fontSize: "0.82rem" }}>Erste Seite des Protokolls mit Metadaten.</p>
            <div style={{ marginTop: "12px" }}>
              <PresetCardGrid options={titlePageOptions} value={form.preset_title_page} onChange={(v) => setForm((f) => ({ ...f, preset_title_page: v }))} accentColor={form.primary_color} />
            </div>
          </div>

          {form.preset_title_page === "combined_toc" ? (
            <div className="card inset-card" style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}>
              <div className="eyebrow">Titelblatt + Inhaltsverzeichnis — Konfiguration</div>
              <p className="muted" style={{ marginTop: "4px", fontSize: "0.82rem" }}>
                Das Inhaltsverzeichnis ist in diesem Titelblatt integriert.
              </p>
              <div style={{ display: "flex", gap: "16px", marginTop: "16px", flexWrap: "wrap" }}>
                <label className="field-stack" style={{ flex: 1, minWidth: "200px" }}>
                  <span className="field-label">Logo / Bild oben links</span>
                  <select value={form.title_header_image} onChange={(e) => setForm((f) => ({ ...f, title_header_image: e.target.value }))}>
                    <option value="">Kein Bild</option>
                    {imageParts.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  <span className="field-help">PNG oder JPG — aus der Parts-Bibliothek wählen.</span>
                </label>
                <label className="field-stack" style={{ flex: 1, minWidth: "200px" }}>
                  <span className="field-label">Footer-Bild unten links</span>
                  <select value={form.title_footer_image} onChange={(e) => setForm((f) => ({ ...f, title_footer_image: e.target.value }))}>
                    <option value="">Kein Bild</option>
                    {imageParts.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  <span className="field-help">Silhouette o.ä. — aus der Parts-Bibliothek wählen.</span>
                </label>
                <label className="field-stack" style={{ minWidth: "160px" }}>
                  <span className="field-label">Zeilenabstand IHV</span>
                  <select value={form.toc_spacing} onChange={(e) => setForm((f) => ({ ...f, toc_spacing: e.target.value }))}>
                    <option value="normal">Standard</option>
                    <option value="compact">Kompakt</option>
                    <option value="very_compact">Sehr kompakt</option>
                  </select>
                  <span className="field-help">Abstände zwischen IHV-Einträgen.</span>
                </label>
              </div>
              <div style={{ display: "flex", gap: "16px", marginTop: "12px", flexWrap: "wrap" }}>
                <label className="field-stack" style={{ flex: 1, minWidth: "140px" }}>
                  <span className="field-label">Ort</span>
                  <input value={form.title_location} onChange={(e) => setForm((f) => ({ ...f, title_location: e.target.value }))} placeholder="z.B. Musterort" />
                  <span className="field-help">Erscheint mit Datum links oben.</span>
                </label>
                <label className="field-stack" style={{ flex: 2, minWidth: "200px" }}>
                  <span className="field-label">Footer-Text (Kontakt)</span>
                  <textarea rows={2} value={form.title_footer_contact} onChange={(e) => setForm((f) => ({ ...f, title_footer_contact: e.target.value }))} placeholder={"z.B. Verein Musterort | 1234 Musterort\nwww.beispiel.ch"} />
                  <span className="field-help">Zeilenumbrüche werden unterstützt.</span>
                </label>
                <div style={{ minWidth: "140px" }}>
                  <ColorField
                    label="Textfarbe Footer"
                    value={form.title_footer_color}
                    onChange={(v) => setForm((f) => ({ ...f, title_footer_color: v }))}
                  />
                  <span className="field-help" style={{ display: "block", marginTop: "4px" }}>Farbe für den Kontakttext.</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="card inset-card"
              style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}
            >
              <div className="eyebrow">Inhaltsverzeichnis</div>
              <p className="muted" style={{ marginTop: "4px", fontSize: "0.82rem" }}>Übersicht aller Abschnitte.</p>
              <div style={{ marginTop: "12px" }}>
                <PresetCardGrid options={tocOptions} value={form.preset_toc} onChange={(v) => setForm((f) => ({ ...f, preset_toc: v }))} accentColor={form.primary_color} />
              </div>
            </div>
          )}

          <div className="card inset-card">
            <div className="eyebrow">Nummerierung</div>
            <div style={{ display: "flex", gap: "12px", marginTop: "12px" }}>
              {([["sections", "Mit Nummern", "1. Abschnitt, 1.1 Unterabschnitt"], ["none", "Ohne Nummern", "Nur Titel, keine Nummern"]] as const).map(([val, label, desc]) => (
                <button
                  key={val}
                  type="button"
                  className={`block-type-card${form.numbering_mode === val ? " block-type-card-active" : ""}`}
                  style={{ flex: 1 }}
                  onClick={() => setForm((f) => ({ ...f, numbering_mode: val }))}
                >
                  <div className="block-type-summary">
                    <strong>{label}</strong>
                    <span className="muted" style={{ fontSize: "0.78rem" }}>{desc}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="card inset-card">
            <div className="eyebrow">Weitere Optionen</div>
            <label style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "12px", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={form.show_metadata}
                onChange={(e) => setForm((f) => ({ ...f, show_metadata: e.target.checked }))}
              />
              <span>Protokoll-Metadaten anzeigen</span>
            </label>
            <p className="muted" style={{ marginTop: "4px", fontSize: "0.82rem" }}>Zeigt einen automatischen Metadaten-Block (Nummer, Titel, Datum, Status) im exportierten PDF an. Standardmässig ausgeblendet.</p>
          </div>
        </div>
      )}

      {/* ── Erweitert ── */}
      {activeTab === "advanced" && (
        <div className="grid">
          <div className="info-note">
            Eigene LaTeX-Dateien überschreiben die gewählten Presets aus dem Struktur-Tab. Leer lassen = Preset verwenden.
          </div>
          <div className="three-col">
            {latexSlotDefinitions.map(({ key, label, help }) => (
              <label className="field-stack" key={key}>
                <span className="field-label">{label}</span>
                <select value={form[key as keyof TemplateFormState] as string} onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}>
                  <option value="">— Preset verwenden —</option>
                  {(partsByType[key] ?? []).map((part) => (
                    <option key={part.id} value={part.id}>{part.name}</option>
                  ))}
                </select>
                <span className="field-help">{help}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function DocumentTemplateManager({ initialTemplates, initialParts }: Props) {
  const showToast = useToast();
  const [parts, setParts] = useState(initialParts);
  const [templates, setTemplates] = useState(initialTemplates);
  const [activePanel, setActivePanel] = useState<"parts" | "layouts">("layouts");
  const [partSearch, setPartSearch] = useState("");
  const [layoutSearch, setLayoutSearch] = useState("");
  const [showPartForm, setShowPartForm] = useState(false);
  const [showTemplateForm, setShowTemplateForm] = useState(false);
  const [partForm, setPartForm] = useState(initialPartForm);
  const [templateForm, setTemplateForm] = useState(initialTemplateForm);
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(initialTemplates[0]?.id ?? null);
  const [selectedTemplateForm, setSelectedTemplateForm] = useState<TemplateFormState>(
    initialTemplates[0] ? templateFormFromTemplate(initialTemplates[0]) : initialTemplateForm
  );

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.id === selectedTemplateId) ?? null,
    [templates, selectedTemplateId]
  );

  const partsByType = useMemo(() => {
    const grouped: Record<string, DocumentTemplatePart[]> = {};
    for (const part of parts) {
      grouped[part.part_type] = [...(grouped[part.part_type] ?? []), part];
    }
    return grouped;
  }, [parts]);

  const filteredParts = useMemo(() => {
    const q = partSearch.trim().toLowerCase();
    return !q ? parts : parts.filter((p) => `${p.name} ${p.code} ${p.description ?? ""} ${p.part_type}`.toLowerCase().includes(q));
  }, [partSearch, parts]);

  const filteredTemplates = useMemo(() => {
    const q = layoutSearch.trim().toLowerCase();
    return !q ? templates : templates.filter((t) => `${t.name} ${t.code} ${t.description ?? ""}`.toLowerCase().includes(q));
  }, [layoutSearch, templates]);

  function selectTemplate(template: DocumentTemplate) {
    setSelectedTemplateId(template.id);
    setSelectedTemplateForm(templateFormFromTemplate(template));
  }

  async function createPart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!partForm.file) { showToast("Bitte eine Datei auswählen", "error"); return; }
    try {
      const body = new FormData();
      body.append("name", partForm.name);
      body.append("part_type", partForm.part_type);
      body.append("description", partForm.description);
      body.append("version", partForm.version);
      body.append("is_active", String(partForm.is_active));
      body.append("file", partForm.file);
      const created = await browserApiFetch<DocumentTemplatePart>("/api/document-template-parts", { method: "POST", body });
      setParts((cur) => [...cur, created].sort((a, b) => a.part_type.localeCompare(b.part_type) || a.name.localeCompare(b.name)));
      setPartForm(initialPartForm);
      setShowPartForm(false);
      showToast("Part hochgeladen", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Fehler beim Hochladen", "error");
    }
  }

  async function deletePart(partId: number) {
    try {
      await browserApiFetch<{ message: string }>(`/api/document-template-parts/${partId}`, { method: "DELETE" });
      setParts((cur) => cur.filter((p) => p.id !== partId));
      showToast("Part gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Fehler beim Löschen", "error");
    }
  }

  async function createTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const created = await browserApiFetch<DocumentTemplate>("/api/document-templates", {
        method: "POST", body: JSON.stringify(buildTemplatePayload(templateForm)),
      });
      setTemplates((cur) => [created, ...cur.filter((t) => t.id !== created.id)]);
      setTemplateForm(initialTemplateForm);
      setShowTemplateForm(false);
      selectTemplate(created);
      showToast("Layout erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Fehler beim Erstellen", "error");
    }
  }

  async function saveSelectedTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTemplate) return;
    try {
      const updated = await browserApiFetch<DocumentTemplate>(`/api/document-templates/${selectedTemplate.id}`, {
        method: "PATCH", body: JSON.stringify(buildTemplatePayload(selectedTemplateForm)),
      });
      setTemplates((cur) => cur.map((t) => (t.id === updated.id ? updated : t)));
      selectTemplate(updated);
      showToast("Layout gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Fehler beim Speichern", "error");
    }
  }

  async function deleteTemplate(templateId: number) {
    try {
      await browserApiFetch<{ message: string }>(`/api/document-templates/${templateId}`, { method: "DELETE" });
      const remaining = templates.filter((t) => t.id !== templateId);
      setTemplates(remaining);
      if (selectedTemplateId === templateId) {
        setSelectedTemplateId(remaining[0]?.id ?? null);
        setSelectedTemplateForm(remaining[0] ? templateFormFromTemplate(remaining[0]) : initialTemplateForm);
      }
      showToast("Layout gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Fehler beim Löschen", "error");
    }
  }

  return (
    <div className="grid">
      <div className="segment-control">
        <button type="button" className={`segment-button${activePanel === "layouts" ? " segment-button-active" : ""}`} onClick={() => setActivePanel("layouts")}>
          Layouts
        </button>
        <button type="button" className={`segment-button${activePanel === "parts" ? " segment-button-active" : ""}`} onClick={() => setActivePanel("parts")}>
          Parts-Bibliothek
        </button>
      </div>

      <Modal open={showPartForm} onClose={() => setShowPartForm(false)} title="LaTeX-Part hochladen" description="Eigene .tex-Datei oder Font-Datei hochladen.">
        <form className="grid" onSubmit={createPart}>
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">Name</span>
              <input value={partForm.name} onChange={(e) => setPartForm((f) => ({ ...f, name: e.target.value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">Typ</span>
              <select value={partForm.part_type} onChange={(e) => setPartForm((f) => ({ ...f, part_type: e.target.value }))}>
                {partTypeGroups.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {group.defs.map((d) => (
                      <option key={d.key} value={d.key}>{d.label}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="field-stack">
              <span className="field-label">{imagePartTypes.has(partForm.part_type as any) ? "Bilddatei" : fontPartTypes.has(partForm.part_type as any) ? "Font-Datei" : "LaTeX-Datei"}</span>
              <input type="file" accept={imagePartTypes.has(partForm.part_type as any) ? ".png,.jpg,.jpeg,.svg" : fontPartTypes.has(partForm.part_type as any) ? ".ttf,.otf" : ".tex"}
                onChange={(e) => setPartForm((f) => ({ ...f, file: e.target.files?.[0] ?? null }))} required />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Beschreibung</span>
            <input value={partForm.description} onChange={(e) => setPartForm((f) => ({ ...f, description: e.target.value }))} />
          </label>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Hochladen</button>
          </div>
        </form>
      </Modal>

      <Modal open={showTemplateForm} onClose={() => setShowTemplateForm(false)} title="Neues Layout erstellen" size="wide">
        <form className="grid" onSubmit={createTemplate}>
          <TemplateForm form={templateForm} setForm={setTemplateForm} partsByType={partsByType} allParts={parts} />
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Layout erstellen</button>
          </div>
        </form>
      </Modal>

      {activePanel === "parts" ? (
        <article className="card">
          <DataToolbar
            title="Parts-Bibliothek"
            description="Eigene LaTeX-Snippets oder Fonts hochladen und in Layouts einbinden."
            actions={<button type="button" className="button-inline" onClick={() => setShowPartForm(true)}>Part hochladen</button>}
          />
          <article className="card">
            <label className="field-stack">
              <span className="field-label">Suche</span>
              <input value={partSearch} onChange={(e) => setPartSearch(e.target.value)} placeholder="Parts durchsuchen" />
            </label>
          </article>
          <DataTable columns={["Name", "Typ", "Version", "Status", "Aktionen"]} emptyMessage="Keine Parts gefunden.">
            {filteredParts.map((part) => (
              <tr key={part.id}>
                <td><strong>{part.name}</strong><div className="muted">{part.code}</div></td>
                <td>{partTypeDefinitions.find((d) => d.key === part.part_type)?.label ?? part.part_type}</td>
                <td>{part.version}</td>
                <td><span className="pill">{part.is_active ? "Aktiv" : "Inaktiv"}</span></td>
                <td>
                  <div className="table-actions">
                    <button type="button" className="button-inline button-danger" onClick={() => deletePart(part.id)}>Löschen</button>
                  </div>
                </td>
              </tr>
            ))}
          </DataTable>
        </article>
      ) : (
        <article className="card">
          <DataToolbar
            title="PDF-Layouts"
            description="Layouts definieren das Aussehen des exportierten Protokolls."
            actions={<button type="button" className="button-inline" onClick={() => setShowTemplateForm(true)}>Neues Layout</button>}
          />
          <div className="editor-shell">
            <aside className="editor-nav">
              <div className="editor-nav-section">
                <h3 className="editor-nav-title">Layouts</h3>
                <label className="field-stack" style={{ padding: "0 8px 8px" }}>
                  <input value={layoutSearch} onChange={(e) => setLayoutSearch(e.target.value)} placeholder="Suchen…" style={{ fontSize: "0.82rem" }} />
                </label>
                {filteredTemplates.map((template) => (
                  <button
                    key={template.id}
                    type="button"
                    className={`editor-nav-item${selectedTemplateId === template.id ? " editor-nav-item-active" : ""}`}
                    onClick={() => selectTemplate(template)}
                  >
                    <strong>{template.name}</strong>
                    <span className="muted">{template.code}</span>
                    <div className="status-row">
                      <span className="pill">v{template.version}</span>
                      {template.is_default && <span className="pill">Standard</span>}
                    </div>
                  </button>
                ))}
                {filteredTemplates.length === 0 && <div className="editor-panel-empty">Keine Layouts.</div>}
              </div>
            </aside>

            <div className="editor-panel">
              {selectedTemplate ? (
                <form className="grid" onSubmit={saveSelectedTemplate}>
                  <div className="editor-panel-header">
                    <div>
                      <div className="eyebrow">Layout</div>
                      <h2>{selectedTemplate.name}</h2>
                    </div>
                    <button type="button" className="button-inline button-danger" onClick={() => deleteTemplate(selectedTemplate.id)}>
                      Löschen
                    </button>
                  </div>
                  <TemplateForm form={selectedTemplateForm} setForm={setSelectedTemplateForm} partsByType={partsByType} allParts={parts} />
                  <div className="table-toolbar-actions">
                    <button type="submit" className="button-inline">Layout speichern</button>
                  </div>
                </form>
              ) : (
                <div className="editor-panel-empty">Layout aus der Liste auswählen.</div>
              )}
            </div>
          </div>
        </article>
      )}
    </div>
  );
}
