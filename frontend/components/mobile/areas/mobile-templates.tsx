"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useMobileSession, useOpenMore } from "@/components/mobile/mobile-shell";
import {
  MobileActionSheet,
  MobileDesktopHint,
  MobileEmpty,
  MobileFab,
  MobileGroupCard,
  MobileListRow,
  MobileSegmented,
  MobileSubHeader,
  MobileSwitch,
} from "@/components/mobile/mobile-ui";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { CycleConfigSummary, DocumentTemplate, ParticipantSummary, TemplateElement, TemplateSummary } from "@/types/api";

type Settings = {
  name: string;
  description: string;
  protocol_number_pattern: string;
  title_pattern: string;
  cycle_config_id: string;
  auto_create_next_protocol: boolean;
  document_template_id: string;
};

function settingsFrom(template: TemplateSummary | null): Settings {
  return {
    name: template?.name ?? "",
    description: template?.description ?? "",
    protocol_number_pattern: template?.protocol_number_pattern ?? "",
    title_pattern: template?.title_pattern ?? "",
    cycle_config_id: template?.cycle_config_id ?? "",
    auto_create_next_protocol: template?.auto_create_next_protocol ?? false,
    document_template_id: template?.document_template_id ?? "",
  };
}

/** Formular fuer Neu und "Einstellungen bearbeiten" - Elemente selbst bleiben am Computer. */
function TemplateSettingsSheet({
  template,
  cycleConfigs,
  documentTemplates,
  onClose,
  onSaved,
}: {
  template: TemplateSummary | null;
  cycleConfigs: CycleConfigSummary[];
  documentTemplates?: DocumentTemplate[];
  onClose: () => void;
  onSaved: (template: TemplateSummary, created: boolean) => void;
}) {
  const t = useTranslations("templates.builder");
  const showToast = useToast();
  const [form, setForm] = useState<Settings>(() => settingsFrom(template));
  const [saving, setSaving] = useState(false);
  const update = (patch: Partial<Settings>) => setForm((current) => ({ ...current, ...patch }));

  async function save() {
    if (!form.name.trim() || saving) return;
    setSaving(true);
    const common = {
      name: form.name.trim(),
      description: form.description || null,
      protocol_number_pattern: form.protocol_number_pattern || null,
      title_pattern: form.title_pattern || null,
      auto_create_next_protocol: form.auto_create_next_protocol,
      cycle_config_id: form.cycle_config_id || null,
    };
    try {
      const saved = template
        ? await browserApiFetch<TemplateSummary>(`/api/templates/${template.id}`, {
            method: "PATCH",
            body: JSON.stringify({ ...common, ...(documentTemplates ? { document_template_id: form.document_template_id || null } : {}) }),
          })
        : await browserApiFetch<TemplateSummary>("/api/templates", {
            method: "POST",
            body: JSON.stringify({ ...common, version: 1, status: "active", created_by: null }),
          });
      showToast(template ? t("saveTemplate") : t("createdToast", { name: saved.name }), "success");
      onSaved(saved, !template);
    } catch (error) {
      showToast(error instanceof Error ? error.message : template ? t("templateSaveFailed") : t("createFailedToast"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={template ? t("settingsTitle") : t("createTitle")}
      description={template ? t("settingsDescription") : t("createDescription")}
      onClose={onClose}
      className="mobile-sheet mobile-sheet-tall"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("cancel")}
          </button>
          <button type="button" className="button-primary" data-modal-save disabled={!form.name.trim() || saving} onClick={() => void save()}>
            {template ? t("saveTemplate") : t("createSubmit")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <label className="field-stack">
          <span className="field-label">{t("nameLabel")}</span>
          <input value={form.name} onChange={(event) => update({ name: event.target.value })} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("descriptionLabel")}</span>
          <textarea rows={2} value={form.description} onChange={(event) => update({ description: event.target.value })} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("protocolNumberPatternLabel")}</span>
          <input value={form.protocol_number_pattern} onChange={(event) => update({ protocol_number_pattern: event.target.value })} placeholder={t("protocolNumberPatternPlaceholder")} />
          <span className="field-help">{t("protocolNumberPatternHelp")}</span>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("titlePatternLabel")}</span>
          <input value={form.title_pattern} onChange={(event) => update({ title_pattern: event.target.value })} placeholder={t("titlePatternPlaceholder")} />
          <span className="field-help">{t("titlePatternHelp")}</span>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("cycleLabel")}</span>
          <select value={form.cycle_config_id} onChange={(event) => update({ cycle_config_id: event.target.value })}>
            <option value="">{t("noCycle")}</option>
            {cycleConfigs.map((config) => (
              <option key={config.id} value={config.id}>
                {config.name}
              </option>
            ))}
          </select>
        </label>
        {documentTemplates ? (
          <label className="field-stack">
            <span className="field-label">{t("pdfLayoutLabel")}</span>
            <select value={form.document_template_id} onChange={(event) => update({ document_template_id: event.target.value })}>
              <option value="">{t("noLayoutAssigned")}</option>
              {documentTemplates.map((layout) => (
                <option key={layout.id} value={layout.id}>
                  {layout.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="mobile-card mobile-group-card">
          <button type="button" className="mobile-list-row" aria-pressed={form.auto_create_next_protocol} onClick={() => update({ auto_create_next_protocol: !form.auto_create_next_protocol })}>
            <span className="mobile-list-row-label">{t("autoCreateNextProtocolLabel")}</span>
            <MobileSwitch checked={form.auto_create_next_protocol} />
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function MobileTemplates({ initialTemplates, cycleConfigs }: { initialTemplates: TemplateSummary[]; cycleConfigs: CycleConfigSummary[] }) {
  const t = useTranslations("templates.builder");
  const tMobile = useTranslations("mobile");
  const router = useRouter();
  const openMore = useOpenMore();
  const session = useMobileSession();
  const confirm = useConfirm();
  const showToast = useToast();
  const [templates, setTemplates] = useState(initialTemplates);
  const [tab, setTab] = useState<"active" | "archived">("active");
  const [search, setSearch] = useState("");
  const [actionsFor, setActionsFor] = useState<TemplateSummary | null>(null);
  const [creating, setCreating] = useState(false);
  const [duplicateOf, setDuplicateOf] = useState<TemplateSummary | null>(null);
  const visible = templates.filter(
    (template) => (tab === "archived" ? template.status === "archived" : template.status !== "archived") && (!search.trim() || template.name.toLowerCase().includes(search.trim().toLowerCase()))
  );

  async function toggleArchived(template: TemplateSummary) {
    const status = template.status === "archived" ? "active" : "archived";
    try {
      const updated = await browserApiFetch<TemplateSummary>(`/api/templates/${template.id}`, { method: "PATCH", body: JSON.stringify({ status }) });
      setTemplates((list) => list.map((item) => (item.id === updated.id ? updated : item)));
      showToast(status === "archived" ? t("archivedToast") : t("unarchivedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("statusChangeFailedToast"), "error");
    }
  }

  async function remove(template: TemplateSummary) {
    if (!(await confirm({ message: t("deleteConfirm"), tone: "danger", confirmLabel: t("delete") }))) return;
    try {
      await browserApiFetch(`/api/templates/${template.id}`, { method: "DELETE" });
      setTemplates((list) => list.filter((item) => item.id !== template.id));
      showToast(t("deletedToast", { name: template.name }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFailedToast"), "error");
    }
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={t("pageTitle")} subtitle={tMobile("templates.subtitle")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section">
        <MobileSegmented<"active" | "archived">
          ariaLabel={t("pageTitle")}
          value={tab}
          onChange={setTab}
          options={[
            { value: "active", label: t("active") },
            { value: "archived", label: t("archived") },
          ]}
        />
        <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
      </div>
      {visible.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {visible.map((template) => (
              <div key={template.id} className="mobile-list-row">
                <button type="button" className="mobile-row-button" onClick={() => router.push(`/templates/${template.id}` as Route)}>
                  <span className="mobile-row-stack">
                    <span className="mobile-row-title">{template.name}</span>
                    <span className="mobile-row-meta">
                      {[`v${template.version}`, template.cycle_config?.name, template.description || null].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </button>
                <button type="button" className="mobile-icon-button" aria-label={t("colActions")} onClick={() => setActionsFor(template)}>
                  <MobileIcon name="more" />
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <MobileEmpty title={t("noMatchingElements")} />
      )}
      <div className="mobile-section">
        <MobileDesktopHint text={tMobile("templates.desktopHint")} email={session?.user?.email} />
      </div>
      <MobileFab label={tMobile("templates.fab")} onClick={() => setCreating(true)} />

      {actionsFor ? (
        <MobileActionSheet
          title={`${actionsFor.name} · v${actionsFor.version}`}
          onClose={() => setActionsFor(null)}
          actions={[
            { label: tMobile("templates.editSettings"), onClick: () => router.push(`/templates/${actionsFor.id}` as Route) },
            { label: t("duplicate"), onClick: () => setDuplicateOf(actionsFor) },
            { label: actionsFor.status === "archived" ? t("unarchive") : t("archive"), onClick: () => void toggleArchived(actionsFor) },
            { label: t("delete"), onClick: () => void remove(actionsFor), danger: true },
          ]}
        />
      ) : null}
      {creating ? (
        <TemplateSettingsSheet
          template={null}
          cycleConfigs={cycleConfigs}
          onClose={() => setCreating(false)}
          onSaved={(saved) => {
            setTemplates((list) => [saved, ...list]);
            setCreating(false);
            router.push(`/templates/${saved.id}` as Route);
          }}
        />
      ) : null}
      {duplicateOf ? (
        <DuplicateSheet
          template={duplicateOf}
          onClose={() => setDuplicateOf(null)}
          onCreated={(created) => {
            setTemplates((list) => [created, ...list]);
            setDuplicateOf(null);
          }}
        />
      ) : null}
    </div>
  );
}

function DuplicateSheet({ template, onClose, onCreated }: { template: TemplateSummary; onClose: () => void; onCreated: (template: TemplateSummary) => void }) {
  const t = useTranslations("templates.builder");
  const showToast = useToast();
  const [name, setName] = useState(t("duplicateNameSuggestion", { name: template.name }));
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      const created = await browserApiFetch<TemplateSummary>(`/api/templates/${template.id}/duplicate`, { method: "POST", body: JSON.stringify({ name: name.trim() }) });
      showToast(t("duplicatedToast", { name: created.name }), "success");
      onCreated(created);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("duplicateFailedToast"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={t("duplicateTitleNamed", { name: template.name })}
      description={t("duplicateDescription")}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("cancel")}
          </button>
          <button type="button" className="button-primary" data-modal-save disabled={!name.trim() || busy} onClick={() => void submit()}>
            {busy ? t("duplicating") : t("duplicate")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <label className="field-stack">
          <span className="field-label">{t("newNameLabel")}</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
      </div>
    </Modal>
  );
}

export function MobileTemplateDetail({
  initialTemplate,
  elements,
  participants,
  initialAssigned,
  documentTemplates,
  cycleConfigs,
}: {
  initialTemplate: TemplateSummary;
  elements: TemplateElement[];
  participants: ParticipantSummary[];
  initialAssigned: ParticipantSummary[];
  documentTemplates: DocumentTemplate[];
  cycleConfigs: CycleConfigSummary[];
}) {
  const t = useTranslations("templates.builder");
  const tMobile = useTranslations("mobile");
  const router = useRouter();
  const session = useMobileSession();
  const showToast = useToast();
  const [template, setTemplate] = useState(initialTemplate);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [participantsOpen, setParticipantsOpen] = useState(false);
  const [assigned, setAssigned] = useState(() => new Map(initialAssigned.map((participant) => [participant.id, !!participant.exclude_from_attendance])));
  const [search, setSearch] = useState("");
  const cycle = cycleConfigs.find((config) => config.id === template.cycle_config_id) ?? null;
  const layout = documentTemplates.find((item) => item.id === template.document_template_id) ?? null;
  const sortedElements = useMemo(() => [...elements].sort((a, b) => a.sort_index - b.sort_index), [elements]);
  const activeParticipants = participants.filter((participant) => participant.is_active || assigned.has(participant.id));
  const filteredParticipants = activeParticipants.filter((participant) => !search.trim() || participant.display_name.toLowerCase().includes(search.trim().toLowerCase()));

  async function saveParticipants(next: Map<string, boolean>) {
    const previous = assigned;
    setAssigned(next);
    try {
      await browserApiFetch(`/api/templates/${template.id}/participants`, {
        method: "PUT",
        body: JSON.stringify({ participants: [...next.entries()].map(([participant_id, exclude]) => ({ participant_id, exclude_from_attendance: exclude })) }),
      });
    } catch (error) {
      setAssigned(previous);
      showToast(error instanceof Error ? error.message : t("participantAssignmentsSaveFailed"), "error");
    }
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={template.name} subtitle={`v${template.version}`} backLabel={t("pageTitle")} onBack={() => router.push("/templates" as Route)} />
      <div className="mobile-section">
        <MobileGroupCard label={t("settingsTitle")}>
          <MobileListRow label={t("protocolNumberPatternLabel")} value={template.protocol_number_pattern || "—"} onClick={() => setSettingsOpen(true)} />
          <MobileListRow label={t("titlePatternLabel")} value={template.title_pattern || "—"} onClick={() => setSettingsOpen(true)} />
          <MobileListRow label={t("cycleLabel")} value={cycle?.name ?? t("noCycle")} onClick={() => setSettingsOpen(true)} />
          <MobileListRow label={t("pdfLayoutLabel")} value={layout?.name ?? t("noLayoutAssigned")} onClick={() => setSettingsOpen(true)} />
          <MobileListRow label={t("autoCreateNextProtocolLabel")} trailing={<MobileSwitch checked={!!template.auto_create_next_protocol} />} onClick={() => setSettingsOpen(true)} chevron={false} />
        </MobileGroupCard>
        <MobileGroupCard label={t("chooseParticipantsTitle")}>
          <MobileListRow
            leading={<MobileIcon name="people" className="mobile-list-row-navicon" />}
            label={tMobile("templates.participantCount", { count: assigned.size })}
            onClick={() => setParticipantsOpen(true)}
          />
        </MobileGroupCard>
        <MobileGroupCard label={t("elementsTitle")}>
          {sortedElements.length === 0 ? <MobileListRow label={t("noElementsYet")} /> : null}
          {sortedElements.map((element, index) => (
            <MobileListRow key={element.id} label={`${index + 1}. ${element.title}`} value={t("blockCount", { count: element.blocks.length })} />
          ))}
        </MobileGroupCard>
        <MobileDesktopHint text={tMobile("templates.elementsHint")} email={session?.user?.email} />
      </div>

      {settingsOpen ? (
        <TemplateSettingsSheet
          template={template}
          cycleConfigs={cycleConfigs}
          documentTemplates={documentTemplates}
          onClose={() => setSettingsOpen(false)}
          onSaved={(saved) => {
            setTemplate(saved);
            setSettingsOpen(false);
          }}
        />
      ) : null}
      {participantsOpen ? (
        <Modal open size="sheet" title={t("chooseParticipantsTitle")} description={t("chooseParticipantsDescription")} onClose={() => setParticipantsOpen(false)} className="mobile-sheet mobile-sheet-tall">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchParticipantsPlaceholder")} />
          <div className="mobile-sheet-list">
            {filteredParticipants.map((participant) => {
              const on = assigned.has(participant.id);
              return (
                <button
                  key={participant.id}
                  type="button"
                  className="mobile-picker-option"
                  aria-pressed={on}
                  onClick={() => {
                    const next = new Map(assigned);
                    if (on) next.delete(participant.id);
                    else next.set(participant.id, false);
                    void saveParticipants(next);
                  }}
                >
                  <span className={`mobile-check mobile-check-square${on ? " mobile-check-on" : ""}`} aria-hidden="true">
                    {on ? <MobileIcon name="check" size={14} strokeWidth={3} /> : null}
                  </span>
                  <span className="mobile-picker-option-label">{participant.display_name}</span>
                </button>
              );
            })}
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
