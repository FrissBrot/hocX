"use client";

import { Dispatch, FormEvent, SetStateAction, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { DocumentTemplate, DocumentTemplatePart } from "@/types/api";

type Props = {
  initialTemplates: DocumentTemplate[];
  initialParts: DocumentTemplatePart[];
  tenantId: string | null;
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
  name: string;
  description: string;
  version: string;
  is_active: boolean;
  is_default: boolean;
  orientation: string;
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

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function latexSlotDefinitions(t: TFunc) {
  return [
    { key: "preamble",              label: t("slot.preamble.label"),           help: t("slot.preamble.help") },
    { key: "macros",                label: t("slot.macros.label"),             help: t("slot.macros.help") },
    { key: "title_page",            label: t("slot.titlePage.label"),          help: t("slot.titlePage.help") },
    { key: "header_footer",         label: t("slot.headerFooter.label"),       help: t("slot.headerFooter.help") },
    { key: "toc",                   label: t("slot.toc.label"),                help: t("slot.toc.help") },
    { key: "element_text",          label: t("slot.elementText.label"),        help: t("slot.elementText.help") },
    { key: "element_todo",          label: t("slot.elementTodo.label"),        help: t("slot.elementTodo.help") },
    { key: "element_image",         label: t("slot.elementImage.label"),       help: t("slot.elementImage.help") },
    { key: "element_static_text",   label: t("slot.elementStaticText.label"),  help: t("slot.elementStaticText.help") },
    { key: "element_form",          label: t("slot.elementForm.label"),        help: t("slot.elementForm.help") },
    { key: "element_events",        label: t("slot.elementEvents.label"),      help: t("slot.elementEvents.help") },
    { key: "element_bullet_list",   label: t("slot.elementBulletList.label"),  help: t("slot.elementBulletList.help") },
    { key: "element_attendance",    label: t("slot.elementAttendance.label"),  help: t("slot.elementAttendance.help") },
    { key: "element_session_date",  label: t("slot.elementSessionDate.label"), help: t("slot.elementSessionDate.help") },
  ] as const;
}

function fontSlotDefinitions(t: TFunc) {
  return [
    { key: "font_regular",     label: t("slot.fontRegular.label"),    shortLabel: t("slot.fontRegular.short"),    help: t("slot.fontRegular.help") },
    { key: "font_bold",        label: t("slot.fontBold.label"),       shortLabel: t("slot.fontBold.short"),       help: t("slot.fontBold.help") },
    { key: "font_italic",      label: t("slot.fontItalic.label"),     shortLabel: t("slot.fontItalic.short"),     help: t("slot.fontItalic.help") },
    { key: "font_bold_italic", label: t("slot.fontBoldItalic.label"), shortLabel: t("slot.fontBoldItalic.short"), help: t("slot.fontBoldItalic.help") },
  ] as const;
}

function imageSlotDefinitions(t: TFunc) {
  return [
    { key: "title_header_image", label: t("slot.titleHeaderImage.label"), help: t("slot.titleHeaderImage.help") },
    { key: "title_footer_image", label: t("slot.titleFooterImage.label"), help: t("slot.titleFooterImage.help") },
  ] as const;
}

const imagePartTypeKeys: Set<string> = new Set(["title_header_image", "title_footer_image"]);
const partTypeOptions = [
  "preamble", "macros", "title_page", "header_footer", "toc",
  "element_text", "element_todo", "element_image", "element_static_text",
  "element_form", "element_events", "element_bullet_list",
  "element_attendance", "element_session_date",
  "font_regular", "font_bold", "font_italic", "font_bold_italic",
  "title_header_image", "title_footer_image",
];
const fontPartTypeKeys: Set<string> = new Set(["font_regular", "font_bold", "font_italic", "font_bold_italic"]);

type PartKind = "image" | "font" | "latex";

function partKinds(t: TFunc): {
  value: PartKind;
  label: string;
  fileLabel: string;
  accept: string;
  formats: string;
  hint: string;
  defs: readonly { key: string; label: string; help: string }[];
}[] {
  return [
    {
      value: "image", label: t("kindImage"), fileLabel: t("kindImageFile"), accept: ".png,.jpg,.jpeg,.svg", formats: ".png · .jpg · .svg",
      hint: t("kindImageHint"),
      defs: imageSlotDefinitions(t),
    },
    {
      value: "font", label: t("kindFont"), fileLabel: t("kindFontFile"), accept: ".ttf,.otf", formats: ".ttf · .otf",
      hint: t("kindFontHint"),
      defs: fontSlotDefinitions(t),
    },
    {
      value: "latex", label: t("kindLatex"), fileLabel: t("kindLatexFile"), accept: ".tex", formats: ".tex",
      hint: t("kindLatexHint"),
      defs: latexSlotDefinitions(t),
    },
  ];
}

function partKindOf(partType: string): PartKind {
  return imagePartTypeKeys.has(partType) ? "image" : fontPartTypeKeys.has(partType) ? "font" : "latex";
}

const initialPartForm: PartFormState = {
  name: "", part_type: "title_header_image", description: "", version: "1", is_active: true, file: null,
};

const initialTemplateForm: TemplateFormState = {
  name: "", description: "", version: "1", is_active: true, is_default: false,
  orientation: "portrait",
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

function templateInitials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
}

function templateFormFromTemplate(template: DocumentTemplate): TemplateFormState {
  const config = (template.configuration_json ?? {}) as Record<string, any>;
  const theme = config.theme ?? {};
  const options = config.options ?? {};
  const slots = config.slots ?? {};
  const fontParts = theme.font_parts ?? {};
  const presets = config.presets ?? {};
  return {
    name: template.name,
    description: template.description ?? "",
    version: String(template.version),
    is_active: template.is_active,
    is_default: template.is_default,
    orientation: options.orientation ?? "portrait",
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
    title_header_image: config.title_assets?.header_image_part_id ? String(config.title_assets.header_image_part_id) : "",
    title_footer_image: config.title_assets?.footer_image_part_id ? String(config.title_assets.footer_image_part_id) : "",
    title_text_line1: config.title_text?.line1 ?? "",
    title_text_line2: config.title_text?.line2 ?? "",
    title_org_name: config.title_text?.org_name ?? "",
    title_location: config.title_text?.location ?? "",
    title_footer_contact: config.title_text?.footer_contact ?? "",
    title_footer_color: config.title_text?.footer_color ?? "444444",
    show_metadata: !(options.hide_metadata ?? true),
  };
}

function buildTemplatePayload(form: TemplateFormState, tenantId: string | null) {
  return {
    tenant_id: tenantId,
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
            .map((slot) => [slot, form[slot as keyof TemplateFormState] as string])
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
        orientation: form.orientation,
      },
      title_assets: {
        header_image_part_id: form.title_header_image ? form.title_header_image : null,
        footer_image_part_id: form.title_footer_image ? form.title_footer_image : null,
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
          .map((slot) => [slot, form[slot as keyof TemplateFormState] as string])
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

function LandscapePageMockup({ children, bg = "white" }: { children?: React.ReactNode; bg?: string }) {
  return (
    <svg viewBox="0 0 82 60" width="72" height="52" style={{ display: "block", margin: "0 auto" }}>
      <rect x="3" y="3" width="77" height="55" rx="2" fill="#d8d8d8" />
      <rect x="2" y="2" width="77" height="55" rx="2" fill={bg} stroke="#e0e0e0" strokeWidth="0.6" />
      {children}
    </svg>
  );
}

const LANDSCAPE_CONTENT_LINES = [16, 20, 24, 28, 32, 36, 40];

function LandscapeContentLines({ from = 0, count = 5, accent = "#e4e4e4" }: { from?: number; count?: number; accent?: string }) {
  return (
    <>
      {LANDSCAPE_CONTENT_LINES.slice(from, from + count).map((y, i) => (
        <rect key={y} x="8" y={y} width={i % 3 === 2 ? 44 : 62} height="1.8" fill={accent} rx="0.9" />
      ))}
    </>
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

// ── Landscape header/footer previews ────────────────────────────────────────

const landscapeHeaderPreviews: Record<string, React.ReactNode> = {
  none: (
    <LandscapePageMockup>
      <LandscapeContentLines />
    </LandscapePageMockup>
  ),
  minimal: (
    <LandscapePageMockup>
      <rect x="64" y="5.5" width="12" height="1.8" fill="#bbb" rx="0.9" />
      <LandscapeContentLines from={1} />
    </LandscapePageMockup>
  ),
  standard: (
    <LandscapePageMockup>
      <rect x="8" y="5.5" width="28" height="1.8" fill="#aaa" rx="0.9" />
      <rect x="58" y="5.5" width="16" height="1.8" fill="#aaa" rx="0.9" />
      <line x1="8" y1="9.5" x2="76" y2="9.5" stroke="#ddd" strokeWidth="0.7" />
      <LandscapeContentLines from={1} />
    </LandscapePageMockup>
  ),
  bar: (
    <LandscapePageMockup>
      <rect x="2" y="2" width="77" height="10" fill="var(--dt-accent, #174B7A)" rx="2" />
      <rect x="8" y="5" width="30" height="2" fill="rgba(255,255,255,0.85)" rx="1" />
      <rect x="62" y="5" width="12" height="2" fill="rgba(255,255,255,0.6)" rx="1" />
      <LandscapeContentLines from={1} />
    </LandscapePageMockup>
  ),
  logo: (
    <LandscapePageMockup>
      <rect x="8" y="3.5" width="10" height="7" fill="var(--dt-accent, #174B7A)" rx="1" opacity="0.7" />
      <rect x="25" y="5.5" width="26" height="1.8" fill="#aaa" rx="0.9" />
      <rect x="58" y="5.5" width="16" height="1.8" fill="#aaa" rx="0.9" />
      <line x1="8" y1="12" x2="76" y2="12" stroke="#ddd" strokeWidth="0.7" />
      <LandscapeContentLines from={1} />
    </LandscapePageMockup>
  ),
  logo_bar: (
    <LandscapePageMockup>
      <rect x="2" y="2" width="77" height="11" fill="var(--dt-accent, #174B7A)" rx="2" />
      <rect x="5" y="3.5" width="9" height="7" fill="rgba(255,255,255,0.8)" rx="1" />
      <rect x="22" y="5.5" width="30" height="2" fill="rgba(255,255,255,0.85)" rx="1" />
      <rect x="60" y="5.5" width="16" height="2" fill="rgba(255,255,255,0.6)" rx="1" />
      <LandscapeContentLines from={1} />
    </LandscapePageMockup>
  ),
  logo_date: (
    <LandscapePageMockup>
      <rect x="8" y="3.5" width="10" height="7" fill="var(--dt-accent, #174B7A)" rx="1" opacity="0.7" />
      <rect x="30" y="5.5" width="22" height="1.8" fill="#bbb" rx="0.9" />
      <rect x="64" y="5.5" width="10" height="1.8" fill="#bbb" rx="0.9" />
      <line x1="8" y1="12" x2="76" y2="12" stroke="#ddd" strokeWidth="0.7" />
      <LandscapeContentLines from={1} />
    </LandscapePageMockup>
  ),
};

const landscapeFooterPreviews: Record<string, React.ReactNode> = {
  none: (
    <LandscapePageMockup>
      <LandscapeContentLines />
    </LandscapePageMockup>
  ),
  minimal: (
    <LandscapePageMockup>
      <LandscapeContentLines count={4} />
      <rect x="37" y="49" width="8" height="1.8" fill="#bbb" rx="0.9" />
    </LandscapePageMockup>
  ),
  standard: (
    <LandscapePageMockup>
      <LandscapeContentLines count={4} />
      <line x1="8" y1="47" x2="76" y2="47" stroke="#ddd" strokeWidth="0.7" />
      <rect x="8" y="49" width="20" height="1.8" fill="#aaa" rx="0.9" />
      <rect x="62" y="49" width="12" height="1.8" fill="#aaa" rx="0.9" />
    </LandscapePageMockup>
  ),
  date_page: (
    <LandscapePageMockup>
      <LandscapeContentLines count={4} />
      <line x1="8" y1="47" x2="76" y2="47" stroke="#ddd" strokeWidth="0.7" />
      <rect x="8" y="49" width="18" height="1.8" fill="#aaa" rx="0.9" />
      <rect x="64" y="49" width="10" height="1.8" fill="#aaa" rx="0.9" />
    </LandscapePageMockup>
  ),
  with_version: (
    <LandscapePageMockup>
      <LandscapeContentLines count={4} />
      <line x1="8" y1="47" x2="76" y2="47" stroke="#ddd" strokeWidth="0.7" />
      <rect x="8" y="49" width="16" height="1.8" fill="#aaa" rx="0.9" />
      <rect x="34" y="49" width="14" height="1.8" fill="#bbb" rx="0.9" />
      <rect x="62" y="49" width="12" height="1.8" fill="#aaa" rx="0.9" />
    </LandscapePageMockup>
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
            <span className="muted" style={{ fontSize: "var(--text-xs)" }}>{opt.description}</span>
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
  const t = useTranslations("templates.documentTemplates");
  const safe = value.replace("#", "");
  return (
    <div className="color-field">
      <span className="field-label">{label}</span>
      <div className="color-field-row">
        <label className="color-swatch-label" title={t("chooseColor")}>
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

function fontOptions(t: TFunc) {
  return [
    { value: "arial", label: "Arial", description: t("fontDescArial"), sample: "Aa", style: { fontFamily: "Arial, sans-serif" } },
    { value: "helvet", label: "Helvetica", description: t("fontDescHelvetica"), sample: "Aa", style: { fontFamily: "Helvetica, Arial, sans-serif" } },
    { value: "palatino", label: "Palatino", description: t("fontDescPalatino"), sample: "Aa", style: { fontFamily: "Palatino, Georgia, serif" } },
    { value: "century_gothic", label: "Century Gothic", description: t("fontDescCenturyGothic"), sample: "Aa", style: { fontFamily: "Century Gothic, Futura, sans-serif" } },
    { value: "uploaded", label: t("fontCustom"), description: t("fontDescCustom"), sample: "Aa", style: {} },
  ] as const;
}

function FontFamilyPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = useTranslations("templates.documentTemplates");
  return (
    <div className="doctpl-choice-grid">
      {fontOptions(t).map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`doctpl-choice doctpl-choice-stack${value === opt.value ? " doctpl-choice-active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          <span className="doctpl-choice-sample" style={opt.style}>{opt.sample}</span>
          <span className="doctpl-choice-title" style={opt.style}>{opt.label}</span>
          <span className="doctpl-choice-desc">{opt.description}</span>
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
  const t = useTranslations("templates.documentTemplates");
  const imageParts = useMemo(
    () => allParts.filter((p) => /\.(png|jpg|jpeg|svg|webp)$/i.test(p.storage_path)),
    [allParts]
  );
  const [activeTab, setActiveTab] = useState<"design" | "structure" | "advanced">("design");
  const isLandscape = form.orientation === "landscape";

  const headerOptions: PresetOption[] = isLandscape ? [
    { value: "none", label: t("preset.header.none.label"), description: t("preset.header.none.desc"), preview: landscapeHeaderPreviews.none },
    { value: "minimal", label: t("preset.header.minimal.label"), description: t("preset.header.minimal.desc"), preview: landscapeHeaderPreviews.minimal },
    { value: "standard", label: t("preset.header.standard.label"), description: t("preset.header.standard.desc"), preview: landscapeHeaderPreviews.standard },
    { value: "bar", label: t("preset.header.bar.label"), description: t("preset.header.bar.desc"), preview: landscapeHeaderPreviews.bar },
    { value: "logo", label: t("preset.header.logo.label"), description: t("preset.header.logo.desc"), preview: landscapeHeaderPreviews.logo },
    { value: "logo_bar", label: t("preset.header.logoBar.label"), description: t("preset.header.logoBar.desc"), preview: landscapeHeaderPreviews.logo_bar },
    { value: "logo_date", label: t("preset.header.logoDate.label"), description: t("preset.header.logoDate.desc"), preview: landscapeHeaderPreviews.logo_date },
  ] : [
    { value: "none", label: t("preset.header.none.label"), description: t("preset.header.none.desc"), preview: headerPreviews.none },
    { value: "minimal", label: t("preset.header.minimal.label"), description: t("preset.header.minimal.desc"), preview: headerPreviews.minimal },
    { value: "standard", label: t("preset.header.standard.label"), description: t("preset.header.standard.desc"), preview: headerPreviews.standard },
    { value: "bar", label: t("preset.header.bar.label"), description: t("preset.header.bar.desc"), preview: headerPreviews.bar },
  ];

  const footerOptions: PresetOption[] = isLandscape ? [
    { value: "none", label: t("preset.footer.none.label"), description: t("preset.footer.none.desc"), preview: landscapeFooterPreviews.none },
    { value: "minimal", label: t("preset.footer.minimal.label"), description: t("preset.footer.minimal.desc"), preview: landscapeFooterPreviews.minimal },
    { value: "standard", label: t("preset.footer.standard.label"), description: t("preset.footer.standard.desc"), preview: landscapeFooterPreviews.standard },
    { value: "date_page", label: t("preset.footer.datePage.label"), description: t("preset.footer.datePage.desc"), preview: landscapeFooterPreviews.date_page },
    { value: "with_version", label: t("preset.footer.withVersion.label"), description: t("preset.footer.withVersion.desc"), preview: landscapeFooterPreviews.with_version },
  ] : [
    { value: "none", label: t("preset.footer.none.label"), description: t("preset.footer.none.desc"), preview: footerPreviews.none },
    { value: "minimal", label: t("preset.footer.minimal.label"), description: t("preset.footer.minimal.desc"), preview: footerPreviews.minimal },
    { value: "standard", label: t("preset.footer.standard.label"), description: t("preset.footer.standard.desc"), preview: footerPreviews.standard },
    { value: "with_version", label: t("preset.footer.withVersion.label"), description: t("preset.footer.withVersion.desc"), preview: footerPreviews.with_version },
  ];

  const titlePageOptions: PresetOption[] = [
    { value: "none", label: t("preset.titlePage.none.label"), description: t("preset.titlePage.none.desc"), preview: titlePagePreviews.none },
    { value: "minimal", label: t("preset.titlePage.minimal.label"), description: t("preset.titlePage.minimal.desc"), preview: titlePagePreviews.minimal },
    { value: "modern", label: t("preset.titlePage.modern.label"), description: t("preset.titlePage.modern.desc"), preview: titlePagePreviews.modern },
    { value: "bold", label: t("preset.titlePage.bold.label"), description: t("preset.titlePage.bold.desc"), preview: titlePagePreviews.bold },
    { value: "combined_toc", label: t("preset.titlePage.combinedToc.label"), description: t("preset.titlePage.combinedToc.desc"), preview: combinedTocPreview },
  ];

  const tocOptions: PresetOption[] = [
    { value: "none", label: t("preset.toc.none.label"), description: t("preset.toc.none.desc"), preview: tocPreviews.none },
    { value: "standard", label: t("preset.toc.standard.label"), description: t("preset.toc.standard.desc"), preview: tocPreviews.standard },
    { value: "compact", label: t("preset.toc.compact.label"), description: t("preset.toc.compact.desc"), preview: tocPreviews.compact },
  ];

  const hasCustomSlot = (keys: string[]) => keys.some((k) => !!form[k as keyof TemplateFormState]);

  return (
    <div className="grid">
      {/* Metadata — always visible */}
      <div className="doctpl-fields">
        <label className="field-stack">
          <span className="field-label">{t("fieldName")}</span>
          <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("fieldVersion")}</span>
          <input type="number" min={1} value={form.version} onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("fieldDescription")}</span>
          <input value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
        </label>
        <div className="doctpl-fields-flags">
          <label className="checkbox-row">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
            {t("fieldActive")}
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={form.is_default} onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))} />
            {t("defaultForTenant")}
          </label>
        </div>
      </div>

      {/* Orientation selector */}
      <div className="doctpl-panel">
        <div className="eyebrow">{t("formatLabel")}</div>
        <div className="doctpl-choice-grid doctpl-choice-grid-2">
          {([["portrait", t("orientationPortrait"), t("orientationPortraitDesc")], ["landscape", t("orientationLandscape"), t("orientationLandscapeDesc")]] as const).map(([val, label, desc]) => (
            <button
              key={val}
              type="button"
              className={`doctpl-choice${form.orientation === val ? " doctpl-choice-active" : ""}`}
              onClick={() => setForm((f) => ({
                ...f,
                orientation: val,
                preset_header: val === "landscape" ? "logo" : "standard",
                preset_footer: val === "landscape" ? "date_page" : "standard",
                preset_title_page: val === "landscape" ? "none" : f.preset_title_page,
              }))}
            >
              <span className={`doctpl-thumb${val === "landscape" ? " doctpl-thumb-landscape" : ""}`} aria-hidden="true" />
              <span>
                <span className="doctpl-choice-title">{label}</span>
                <span className="doctpl-choice-desc">{desc}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Tab nav */}
      <div className="tabs-list doctpl-tabs" role="tablist">
        {([
          ["design", t("tabDesign"), false],
          ["structure", t("tabStructure"), false],
          ["advanced", t("tabAdvanced"), hasCustomSlot(["preamble", "macros", "title_page", "header_footer", "toc"])],
        ] as const).map(([value, label, marked]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={activeTab === value}
            className={activeTab === value ? "tabs-trigger tabs-trigger-active" : "tabs-trigger"}
            onClick={() => setActiveTab(value)}
          >
            {label}
            {marked ? <span className="doctpl-tabs-dot" title={t("customLatexFilesTitle")} /> : null}
          </button>
        ))}
      </div>

      {/* ── Gestaltung ── */}
      {activeTab === "design" && (
        <div className="grid">
          <div className="doctpl-panel">
            <div className="eyebrow">{t("colorsLabel")}</div>
            <div className="doctpl-colors">
              <ColorField
                label={t("primaryColor")}
                value={form.primary_color}
                onChange={(v) => setForm((f) => ({ ...f, primary_color: v }))}
              />
              <ColorField
                label={t("secondaryColor")}
                value={form.secondary_color}
                onChange={(v) => setForm((f) => ({ ...f, secondary_color: v }))}
              />
            </div>
            <div className="doctpl-color-preview">
              <div
                className="doctpl-color-preview-tile"
                style={{ background: `linear-gradient(135deg, #${form.primary_color} 50%, #${form.secondary_color} 50%)` }}
              />
              {t("preview")}
            </div>
            <button type="button" className="button-secondary"
              onClick={() => setForm((f) => ({ ...f, primary_color: "174B7A", secondary_color: "4F6D7A" }))}>
              {t("resetColors")}
            </button>
          </div>

          <div className="doctpl-panel">
            <div className="eyebrow">{t("fontFamilyLabel")}</div>
            <FontFamilyPicker value={form.font_family} onChange={(v) => setForm((f) => ({ ...f, font_family: v }))} />
            {(form.font_family === "century_gothic" || form.font_family === "uploaded") && (
              <div className="doctpl-font-note">
                <p>
                  {form.font_family === "century_gothic"
                    ? t("fontNoteNotPreinstalled")
                    : t("fontNoteCustom")}
                </p>
                <div className="doctpl-font-slots">
                  {fontSlotDefinitions(t).map(({ key, shortLabel }) => (
                    <label className="field-stack" key={key}>
                      <span className="field-label">{shortLabel}</span>
                      <SearchableSelect
                        options={partsByType[key] ?? []}
                        getId={(part) => String(part.id)}
                        getLabel={(part) => part.name}
                        value={(form[key as keyof TemplateFormState] as string) || null}
                        onChange={(part) => setForm((f) => ({ ...f, [key]: part ? String(part.id) : "" }))}
                        nullLabel={t("none")}
                      />
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="doctpl-panel">
            <div className="eyebrow">{t("fontSizeLabel")}</div>
            <div className="doctpl-choice-grid doctpl-choice-grid-sizes">
              {(["10pt", "11pt", "12pt"] as const).map((size) => (
                <button
                  key={size}
                  type="button"
                  className={`doctpl-choice doctpl-choice-stack${form.font_size === size ? " doctpl-choice-active" : ""}`}
                  onClick={() => setForm((f) => ({ ...f, font_size: size }))}
                >
                  <span className="doctpl-choice-sample">Aa</span> {/* i18n-ok: Schriftmuster, sprachunabhängig */}
                  <span className="doctpl-choice-desc">{size}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Struktur ── */}
      {activeTab === "structure" && (
        <div className="grid">
          <div className="doctpl-panel"
            style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}
          >
            <div className="eyebrow">{t("headerLabel")}</div>
            <p className="muted" style={{ marginTop: "var(--space-1)", fontSize: "var(--text-sm)" }}>{t("headerHint")}</p>
            <div style={{ marginTop: "var(--space-3)" }}>
              <PresetCardGrid options={headerOptions} value={form.preset_header} onChange={(v) => setForm((f) => ({ ...f, preset_header: v }))} accentColor={form.primary_color} />
            </div>
            {["logo", "logo_bar", "logo_date"].includes(form.preset_header) && (
              <div style={{ marginTop: "var(--space-4)" }}>
                <label className="field-stack">
                  <span className="field-label">{t("headerImageLabel")}</span>
                  <SearchableSelect
                    options={imageParts}
                    getId={(p) => String(p.id)}
                    getLabel={(p) => p.name}
                    value={form.title_header_image || null}
                    onChange={(p) => setForm((f) => ({ ...f, title_header_image: p ? String(p.id) : "" }))}
                    nullLabel={t("noImage")}
                  />
                  <span className="field-help">{t("headerImageHelp")}</span>
                </label>
              </div>
            )}
          </div>

          <div className="doctpl-panel"
            style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}
          >
            <div className="eyebrow">{t("footerLabel")}</div>
            <p className="muted" style={{ marginTop: "var(--space-1)", fontSize: "var(--text-sm)" }}>{t("footerHint")}</p>
            <div style={{ marginTop: "var(--space-3)" }}>
              <PresetCardGrid options={footerOptions} value={form.preset_footer} onChange={(v) => setForm((f) => ({ ...f, preset_footer: v }))} accentColor={form.primary_color} />
            </div>
          </div>

          {!isLandscape && (
          <div className="doctpl-panel"
            style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}
          >
            <div className="eyebrow">{t("titlePageLabel")}</div>
            <p className="muted" style={{ marginTop: "var(--space-1)", fontSize: "var(--text-sm)" }}>{t("titlePageHint")}</p>
            <div style={{ marginTop: "var(--space-3)" }}>
              <PresetCardGrid options={titlePageOptions} value={form.preset_title_page} onChange={(v) => setForm((f) => ({ ...f, preset_title_page: v }))} accentColor={form.primary_color} />
            </div>
          </div>
          )}

          {!isLandscape && (form.preset_title_page === "combined_toc" ? (
            <div className="doctpl-panel" style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}>
              <div className="eyebrow">{t("combinedTocLabel")}</div>
              <p className="muted" style={{ marginTop: "var(--space-1)", fontSize: "var(--text-sm)" }}>
                {t("combinedTocHint")}
              </p>
              <div style={{ display: "flex", gap: "var(--space-4)", marginTop: "var(--space-4)", flexWrap: "wrap" }}>
                <label className="field-stack" style={{ flex: 1, minWidth: "200px" }}>
                  <span className="field-label">{t("topLeftImageLabel")}</span>
                  <SearchableSelect
                    options={imageParts}
                    getId={(p) => String(p.id)}
                    getLabel={(p) => p.name}
                    value={form.title_header_image || null}
                    onChange={(p) => setForm((f) => ({ ...f, title_header_image: p ? String(p.id) : "" }))}
                    nullLabel={t("noImage")}
                  />
                  <span className="field-help">{t("topLeftImageHelp")}</span>
                </label>
                <label className="field-stack" style={{ flex: 1, minWidth: "200px" }}>
                  <span className="field-label">{t("bottomLeftFooterImageLabel")}</span>
                  <SearchableSelect
                    options={imageParts}
                    getId={(p) => String(p.id)}
                    getLabel={(p) => p.name}
                    value={form.title_footer_image || null}
                    onChange={(p) => setForm((f) => ({ ...f, title_footer_image: p ? String(p.id) : "" }))}
                    nullLabel={t("noImage")}
                  />
                  <span className="field-help">{t("bottomLeftFooterImageHelp")}</span>
                </label>
                <label className="field-stack" style={{ minWidth: "160px" }}>
                  <span className="field-label">{t("tocSpacingLabel")}</span>
                  <select value={form.toc_spacing} onChange={(e) => setForm((f) => ({ ...f, toc_spacing: e.target.value }))}>
                    <option value="normal">{t("tocSpacingStandard")}</option>
                    <option value="compact">{t("tocSpacingCompact")}</option>
                    <option value="very_compact">{t("tocSpacingVeryCompact")}</option>
                  </select>
                  <span className="field-help">{t("tocSpacingHelp")}</span>
                </label>
              </div>
              <div style={{ display: "flex", gap: "var(--space-4)", marginTop: "var(--space-3)", flexWrap: "wrap" }}>
                <label className="field-stack" style={{ flex: 1, minWidth: "140px" }}>
                  <span className="field-label">{t("locationLabel")}</span>
                  <input value={form.title_location} onChange={(e) => setForm((f) => ({ ...f, title_location: e.target.value }))} placeholder={t("locationPlaceholder")} />
                  <span className="field-help">{t("locationHelp")}</span>
                </label>
                <label className="field-stack" style={{ flex: 2, minWidth: "200px" }}>
                  <span className="field-label">{t("footerContactLabel")}</span>
                  <textarea rows={2} value={form.title_footer_contact} onChange={(e) => setForm((f) => ({ ...f, title_footer_contact: e.target.value }))} placeholder={t("footerContactPlaceholder")} />
                  <span className="field-help">{t("footerContactHelp")}</span>
                </label>
                <div style={{ minWidth: "140px" }}>
                  <ColorField
                    label={t("footerTextColor")}
                    value={form.title_footer_color}
                    onChange={(v) => setForm((f) => ({ ...f, title_footer_color: v }))}
                  />
                  <span className="field-help" style={{ display: "block", marginTop: "var(--space-1)" }}>{t("footerTextColorHelp")}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="doctpl-panel"
              style={{ "--dt-accent": `#${form.primary_color}` } as React.CSSProperties}
            >
              <div className="eyebrow">{t("tocLabel")}</div>
              <p className="muted" style={{ marginTop: "var(--space-1)", fontSize: "var(--text-sm)" }}>{t("tocHint")}</p>
              <div style={{ marginTop: "var(--space-3)" }}>
                <PresetCardGrid options={tocOptions} value={form.preset_toc} onChange={(v) => setForm((f) => ({ ...f, preset_toc: v }))} accentColor={form.primary_color} />
              </div>
            </div>
          ))}

          <div className="doctpl-panel">
            <div className="eyebrow">{t("numberingLabel")}</div>
            <div style={{ display: "flex", gap: "var(--space-3)", marginTop: "var(--space-3)" }}>
              {([["sections", t("numberingSections"), t("numberingSectionsDesc")], ["none", t("numberingNone"), t("numberingNoneDesc")]] as const).map(([val, label, desc]) => (
                <button
                  key={val}
                  type="button"
                  className={`block-type-card${form.numbering_mode === val ? " block-type-card-active" : ""}`}
                  style={{ flex: 1 }}
                  onClick={() => setForm((f) => ({ ...f, numbering_mode: val }))}
                >
                  <div className="block-type-summary">
                    <strong>{label}</strong>
                    <span className="muted" style={{ fontSize: "var(--text-xs)" }}>{desc}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="doctpl-panel">
            <div className="eyebrow">{t("moreOptionsLabel")}</div>
            <label style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", marginTop: "var(--space-3)", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={form.show_metadata}
                onChange={(e) => setForm((f) => ({ ...f, show_metadata: e.target.checked }))}
              />
              <span>{t("showMetadataLabel")}</span>
            </label>
            <p className="muted" style={{ marginTop: "var(--space-1)", fontSize: "var(--text-sm)" }}>{t("showMetadataHelp")}</p>
          </div>
        </div>
      )}

      {/* ── Erweitert ── */}
      {activeTab === "advanced" && (
        <div className="grid">
          <div className="info-note">
            {t("advancedInfoNote")}
          </div>
          <div className="three-col">
            {latexSlotDefinitions(t).map(({ key, label, help }) => (
              <label className="field-stack" key={key}>
                <span className="field-label">{label}</span>
                <SearchableSelect
                  options={partsByType[key] ?? []}
                  getId={(part) => String(part.id)}
                  getLabel={(part) => part.name}
                  value={(form[key as keyof TemplateFormState] as string) || null}
                  onChange={(part) => setForm((f) => ({ ...f, [key]: part ? String(part.id) : "" }))}
                  nullLabel={t("usePreset")}
                />
                <span className="field-help">{help}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Part-Upload ───────────────────────────────────────────────────────────────

function PartUploadModal({
  open, onClose, form, setForm, onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  form: PartFormState;
  setForm: Dispatch<SetStateAction<PartFormState>>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const t = useTranslations("templates.documentTemplates");
  const [dragOver, setDragOver] = useState(false);
  const kinds = partKinds(t);
  const kind = kinds.find((k) => k.value === partKindOf(form.part_type)) ?? kinds[0];

  function pickFile(file: File | null | undefined) {
    if (file) setForm((f) => ({ ...f, file }));
  }

  return (
    <Modal open={open} onClose={onClose} title={t("uploadPartTitle")} className="doctpl-part-modal" hideCloseButton>
      <form className="doctpl-part-form" onSubmit={onSubmit}>
        <header className="doctpl-part-heading">
          <div>
            <h2>{t("uploadPartTitle")}</h2>
            <p className="muted">{t("uploadPartDescription")}</p>
          </div>
          <button type="button" className="doctpl-part-close" title={t("close")} aria-label={t("close")} onClick={onClose}><ActionIcon name="close" /></button>
        </header>

        <div className="doctpl-part-body">
          <div className="doctpl-part-main grid">
            <div className="field-stack doctpl-kind">
              <span className="field-label">{t("partKindLabel")}</span>
              <FilterTabs
                options={kinds.map((k) => ({ value: k.value, label: k.label }))}
                value={kind.value}
                onChange={(value) => {
                  const next = kinds.find((k) => k.value === value);
                  if (next) setForm((f) => ({ ...f, part_type: next.defs[0].key, file: null }));
                }}
              />
            </div>

            <div className="field-stack">
              <span className="field-label">{t("slotLabel")}</span>
              <div className="doctpl-slots" role="radiogroup" aria-label={t("slotLabel")}>
                {kind.defs.map((def) => (
                  <label key={def.key} className="field-radio-option doctpl-slot">
                    <input
                      type="radio"
                      name="part_type"
                      value={def.key}
                      checked={form.part_type === def.key}
                      onChange={() => setForm((f) => ({ ...f, part_type: def.key }))}
                    />
                    <span>
                      <span className="doctpl-choice-title">{def.label}</span>
                      <span className="doctpl-choice-desc">{def.help}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <div className="doctpl-part-row">
              <label className="field-stack">
                <span className="field-label">{t("fieldName")}</span>
                <input value={form.name} placeholder={t("partNamePlaceholder")} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("fieldVersion")}</span>
                <input type="number" min={1} value={form.version} onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))} />
              </label>
            </div>

            <label className="field-stack">
              <span className="field-label">{t("fieldDescription")} <span className="doctpl-optional">{t("optionalSuffix")}</span></span>
              <input value={form.description} placeholder={t("partDescriptionPlaceholder")} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </label>
          </div>

          <aside className="doctpl-part-side">
            <div className="field-stack">
              <span className="field-label">{kind.fileLabel}</span>
              <label
                className={`doctpl-drop${dragOver ? " doctpl-drop-over" : ""}${form.file ? " doctpl-drop-filled" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => { e.preventDefault(); setDragOver(false); pickFile(e.dataTransfer.files?.[0]); }}
              >
                <input
                  type="file"
                  className="doctpl-drop-input"
                  accept={kind.accept}
                  onChange={(e) => pickFile(e.target.files?.[0])}
                />
                <span className="doctpl-drop-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <path d="M9 12V3M9 3L5.5 6.5M9 3l3.5 3.5M3 12.5v1.25c0 .69.56 1.25 1.25 1.25h9.5c.69 0 1.25-.56 1.25-1.25V12.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                {form.file ? (
                  <>
                    <span className="doctpl-choice-title">{form.file.name}</span>
                    <span className="doctpl-drop-sub">{formatFileSize(form.file.size)} · <span className="doctpl-drop-link">{t("chooseOtherFile")}</span></span>
                  </>
                ) : (
                  <>
                    <span className="doctpl-choice-title">{t("dragFileHere")}</span>
                    <span className="doctpl-drop-sub">{t("or")} <span className="doctpl-drop-link">{t("browse")}</span></span>
                    <span className="doctpl-mono doctpl-drop-formats">{kind.formats}</span>
                  </>
                )}
              </label>
            </div>

            <div className="doctpl-summary">
              <div className="eyebrow">{t("libraryEntryLabel")}</div>
              <dl>
                <dt>{t("typeLabel")}</dt><dd className="doctpl-mono">{form.part_type}</dd>
                <dt>{t("fieldVersion")}</dt><dd>v{form.version || "1"}</dd>
                <dt>{t("statusLabel")}</dt><dd><Badge variant="success">{t("fieldActive")}</Badge></dd>
              </dl>
            </div>

            <p className="doctpl-part-hint">{kind.hint}</p>
          </aside>
        </div>

        <footer className="doctpl-part-footer">
          <button type="button" className="button-secondary" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" className="button-primary" disabled={!form.name.trim() || !form.file}>{t("upload")}</button>
        </footer>
      </form>
    </Modal>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function DocumentTemplateManager({ initialTemplates, initialParts, tenantId }: Props) {
  const t = useTranslations("templates.documentTemplates");
  const showToast = useToast();
  const confirm = useConfirm();
  const [parts, setParts] = useState(initialParts);
  const [templates, setTemplates] = useState(initialTemplates);
  const [activePanel, setActivePanel] = useState<"parts" | "layouts">("layouts");
  const [partSearch, setPartSearch] = useState("");
  const [layoutSearch, setLayoutSearch] = useState("");
  const [showPartForm, setShowPartForm] = useState(false);
  const [showTemplateForm, setShowTemplateForm] = useState(false);
  const [partForm, setPartForm] = useState(initialPartForm);
  const [templateForm, setTemplateForm] = useState(initialTemplateForm);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(initialTemplates[0]?.id ?? null);
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
    return !q ? templates : templates.filter((t) => `${t.name} ${t.description ?? ""}`.toLowerCase().includes(q));
  }, [layoutSearch, templates]);

  function selectTemplate(template: DocumentTemplate) {
    setSelectedTemplateId(template.id);
    setSelectedTemplateForm(templateFormFromTemplate(template));
  }

  function closePartForm() {
    setShowPartForm(false);
    setPartForm(initialPartForm);
  }

  async function createPart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!partForm.file) { showToast(t("pleaseChooseFile"), "error"); return; }
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
      showToast(t("partUploadedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("uploadErrorToast"), "error");
    }
  }

  async function deletePart(partId: string) {
    const part = parts.find((p) => p.id === partId);
    if (!(await confirm({ message: part ? t("deletePartConfirmNamed", { name: part.name }) : t("deletePartConfirm"), tone: "danger", confirmLabel: t("delete") }))) return;
    try {
      await browserApiFetch<{ message: string }>(`/api/document-template-parts/${partId}`, { method: "DELETE" });
      setParts((cur) => cur.filter((p) => p.id !== partId));
      showToast(t("partDeletedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteErrorToast"), "error");
    }
  }

  async function createTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const created = await browserApiFetch<DocumentTemplate>("/api/document-templates", {
        method: "POST", body: JSON.stringify(buildTemplatePayload(templateForm, tenantId)),
      });
      setTemplates((cur) => [created, ...cur.filter((t) => t.id !== created.id)]);
      setTemplateForm(initialTemplateForm);
      setShowTemplateForm(false);
      selectTemplate(created);
      showToast(t("layoutCreatedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createErrorToast"), "error");
    }
  }

  // Ein Layout mit den Standardwerten anlegen, damit Exporte sofort ein definiertes Aussehen haben.
  async function createStandardLayout() {
    try {
      const created = await browserApiFetch<DocumentTemplate>("/api/document-templates", {
        method: "POST",
        body: JSON.stringify(buildTemplatePayload({ ...initialTemplateForm, name: t("standardLayoutName"), is_default: true }, tenantId)),
      });
      setTemplates((cur) => [created, ...cur.filter((t) => t.id !== created.id)]);
      selectTemplate(created);
      showToast(t("standardLayoutCreatedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createErrorToast"), "error");
    }
  }

  async function saveSelectedTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTemplate) return;
    try {
      const updated = await browserApiFetch<DocumentTemplate>(`/api/document-templates/${selectedTemplate.id}`, {
        method: "PATCH", body: JSON.stringify(buildTemplatePayload(selectedTemplateForm, tenantId)),
      });
      setTemplates((cur) => cur.map((t) => (t.id === updated.id ? updated : t)));
      selectTemplate(updated);
      showToast(t("layoutSavedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveErrorToast"), "error");
    }
  }

  async function deleteTemplate(templateId: string) {
    const template = templates.find((item) => item.id === templateId);
    if (!(await confirm({ message: template ? t("deleteLayoutConfirmNamed", { name: template.name }) : t("deleteLayoutConfirm"), tone: "danger", confirmLabel: t("delete") }))) return;
    try {
      await browserApiFetch<{ message: string }>(`/api/document-templates/${templateId}`, { method: "DELETE" });
      const remaining = templates.filter((item) => item.id !== templateId);
      setTemplates(remaining);
      if (selectedTemplateId === templateId) {
        setSelectedTemplateId(remaining[0]?.id ?? null);
        setSelectedTemplateForm(remaining[0] ? templateFormFromTemplate(remaining[0]) : initialTemplateForm);
      }
      showToast(t("layoutDeletedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteErrorToast"), "error");
    }
  }

  const hasNothingYet = templates.length === 0 && parts.length === 0;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{hasNothingYet ? t("pageIntroEmpty") : t("pageIntro")}</p>
        </div>
        {hasNothingYet ? null : (
          <button type="button" className="button-primary" onClick={() => setShowTemplateForm(true)}>{t("newLayoutButton")}</button>
        )}
      </div>

      {hasNothingYet ? null : (
        <FilterTabs
          options={[
            { value: "layouts", label: t("layoutsLabel") },
            { value: "parts", label: t("partsLibraryLabel") },
          ]}
          value={activePanel}
          onChange={setActivePanel}
        />
      )}

      <PartUploadModal open={showPartForm} onClose={closePartForm} form={partForm} setForm={setPartForm} onSubmit={createPart} />

      <Modal open={showTemplateForm} onClose={() => setShowTemplateForm(false)} title={t("createLayoutTitle")} size="wide">
        <ModalSaveForm className="grid" onSubmit={createTemplate}>
          <TemplateForm form={templateForm} setForm={setTemplateForm} partsByType={partsByType} allParts={parts} />
          <div className="table-toolbar-actions">
            <button data-modal-save type="submit" className="button-secondary">{t("createLayoutSubmit")}</button>
          </div>
        </ModalSaveForm>
      </Modal>

      {hasNothingYet ? (
        <EmptyState
          title={t("emptyStateTitle")}
          description={t("emptyStateDescription")}
          actions={
            <>
              <button type="button" className="button-primary" onClick={() => setShowTemplateForm(true)}>
                {t("newDocumentTemplateButton")}
              </button>
              <button type="button" className="button-secondary" onClick={() => void createStandardLayout()}>
                {t("useStandardLayoutButton")}
              </button>
            </>
          }
        />
      ) : activePanel === "parts" ? (
        <article className="card doctpl-card">
          <div className="doctpl-card-head">
            <DataToolbar
              title={t("partsLibraryLabel")}
              description={t("partsLibraryDescription")}
              actions={
                <>
                  <div className="doctpl-search">
                    <SearchInput value={partSearch} onChange={setPartSearch} placeholder={t("searchPartsPlaceholder")} aria-label={t("searchPartsPlaceholder")} />
                  </div>
                  <button type="button" className="button-secondary" onClick={() => setShowPartForm(true)}>{t("newPartButton")}</button>
                </>
              }
            />
          </div>
          <div className="doctpl-table">
            <DataTable columns={[t("fieldName"), t("typeLabel"), t("fieldVersion"), t("statusLabel"), t("colActions")]} emptyMessage={t("noPartsFound")}>
              {filteredParts.map((part) => (
                <tr key={part.id}>
                  <td><strong>{part.name}</strong></td>
                  <td><span className="doctpl-mono">{part.part_type}</span></td>
                  <td className="muted">v{part.version}</td>
                  <td><Badge variant={part.is_active ? "success" : "neutral"}>{part.is_active ? t("fieldActive") : t("inactive")}</Badge></td>
                  <td>
                    <button type="button" className="row-text-action row-text-action-danger" onClick={() => deletePart(part.id)}>{t("delete")}</button>
                  </td>
                </tr>
              ))}
            </DataTable>
          </div>
        </article>
      ) : (
        <article className="card doctpl-card">
          <div className="doctpl-card-head">
            <DataToolbar title={t("pdfLayoutsLabel")} description={t("pdfLayoutsDescription")} />
          </div>
          <div className="doctpl-split">
            <aside className="doctpl-list">
              <h3 className="eyebrow doctpl-list-title">{t("layoutsLabel")}</h3>
              <SearchInput value={layoutSearch} onChange={setLayoutSearch} placeholder={t("searchEllipsis")} aria-label={t("searchLayoutsAriaLabel")} />
              {filteredTemplates.map((template) => {
                const cfg = (template.configuration_json ?? {}) as Record<string, any>;
                const isLandscape = cfg?.options?.orientation === "landscape";
                return (
                  <button
                    key={template.id}
                    type="button"
                    className={`doctpl-item${selectedTemplateId === template.id ? " doctpl-item-active" : ""}`}
                    onClick={() => selectTemplate(template)}
                  >
                    <span className="doctpl-avatar" aria-hidden="true">{templateInitials(template.name)}</span>
                    <span className="doctpl-item-name">{template.name}</span>
                    <span className="doctpl-item-meta">
                      <Badge>v{template.version}</Badge>
                      {template.is_default && <Badge variant="info">{t("fieldStandard")}</Badge>}
                      {isLandscape && <Badge>{t("orientationLandscape")}</Badge>}
                      {!template.is_active && <Badge variant="warning">{t("inactive")}</Badge>}
                    </span>
                  </button>
                );
              })}
              {filteredTemplates.length === 0 && <div className="doctpl-empty">{t("noLayouts")}</div>}
            </aside>

            <div className="doctpl-detail-wrap">
              {selectedTemplate ? (
                <form className="doctpl-detail" onSubmit={saveSelectedTemplate}>
                  <div className="doctpl-detail-head">
                    <div>
                      <div className="eyebrow">{t("layoutLabel")}</div>
                      <h2>{selectedTemplate.name}</h2>
                    </div>
                    <button type="button" className="doctpl-delete" onClick={() => deleteTemplate(selectedTemplate.id)}>
                      {t("delete")}
                    </button>
                  </div>
                  <TemplateForm form={selectedTemplateForm} setForm={setSelectedTemplateForm} partsByType={partsByType} allParts={parts} />
                  <div className="doctpl-detail-actions">
                    <button type="submit" className="button-primary">{t("saveLayoutButton")}</button>
                  </div>
                </form>
              ) : (
                <div className="doctpl-empty">{t("chooseLayoutFromList")}</div>
              )}
            </div>
          </div>
        </article>
      )}
    </div>
  );
}
