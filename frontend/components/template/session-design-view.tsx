"use client";

// Ansicht «PDF» bzw. «Einladung» im Vorlagen-Editor: welche Gestaltung (Aussehen) dieses
// Sitzungsdokument verwendet, wer sie sonst noch verwendet und drei klar benannte Wege:
// andere Gestaltung zuweisen, die geltende bearbeiten (wirkt auf alle Vorlagen, die sie
// verwenden) oder nur für diese Vorlage anpassen (Kopie, läuft danach nicht mehr mit).
// Gehört die Gestaltung allein dieser Vorlage, wird sie direkt im Designer bearbeitet.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useLocale, useTranslations } from "next-intl";

import { TemplateDesigner } from "@/components/documents/designer/designer";
import { templateDisplayName } from "@/components/documents/studio-labels";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, Capabilities, DocumentTemplateInfo, previewDocument, SessionDesign, SessionTemplateRef, studioApi } from "@/lib/documents/api";
import type { TemplateSummary } from "@/types/api";

type Props = { sessionTemplate: TemplateSummary; documentType: "protocol" | "invitation"; onChanged?: () => void };

export function SessionDesignView({ sessionTemplate, documentType, onChanged }: Props) {
  const t = useTranslations("templates.studio");
  const tStudio = useTranslations("documentStudio");
  const locale = useLocale();
  const toast = useToast();
  const [design, setDesign] = useState<SessionDesign | null | undefined>(undefined);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [choices, setChoices] = useState<DocumentTemplateInfo[]>([]);
  const [pages, setPages] = useState<string[]>([]);
  const [editingShared, setEditingShared] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const rows = await studioApi.sessionDesigns(sessionTemplate.id);
      setDesign((rows ?? []).find((item) => item.document_type === documentType) ?? null);
    } catch (reason) {
      setDesign(null);
      setError(apiErrorMessage(reason, t("design.loadFailed")));
    }
    // t ist während der Lebensdauer unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionTemplate.id, documentType]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    studioApi
      .capabilities()
      .then(setCapabilities)
      // Ohne Rechte nur Anzeige, keine Aktionen
      .catch(() => setCapabilities(null));
  }, []);
  // Wählbare Gestaltungen (nur wer zuweisen darf): veröffentlicht und aktiv
  useEffect(() => {
    if (!capabilities?.publish_templates) return;
    studioApi
      .listTemplates({ documentType })
      .then((rows) => setChoices((rows ?? []).filter((item) => item.status === "active" && item.published_revision)))
      .catch(() => setChoices([]));
  }, [capabilities?.publish_templates, documentType, design?.template_id]);

  // Vorschau der geltenden (geteilten) Gestaltung mit den Traktanden dieser Vorlage
  useEffect(() => {
    if (!design || design.owned || editingShared) return;
    const controller = new AbortController();
    previewDocument({ document_type: documentType, template_id: design.template_id, protocol_template_id: sessionTemplate.id, data_mode: "data" }, 4, controller.signal)
      .then((result) => setPages(result.pages))
      .catch((reason) => {
        if (!controller.signal.aborted) setError(apiErrorMessage(reason, tStudio("preview.failed")));
      });
    return () => controller.abort();
    // tStudio ist während der Lebensdauer unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [design, documentType, sessionTemplate.id, editingShared]);

  const listFormat = useMemo(() => new Intl.ListFormat(locale, { style: "long", type: "conjunction" }), [locale]);
  const designName = (item: { name: string; origin: DocumentTemplateInfo["origin"]; system_key: string | null }) => templateDisplayName(tStudio, item);
  const currentName = design ? designName({ name: design.template_name, origin: design.template_origin, system_key: design.template_system_key }) : "";
  const others = (design?.used_in ?? []).filter((ref) => ref.id !== sessionTemplate.id);
  const isDefault = !!design && design.source !== "protocol_template";

  async function changed(message: string) {
    setNotice(message);
    await load();
    onChanged?.();
  }

  async function customize() {
    if (!design) return;
    setBusy(true);
    try {
      const created = await studioApi.customizeSessionDesign(sessionTemplate.id, documentType, t("design.copyName", { name: sessionTemplate.name, type: tStudio(`docType.${documentType}`) }));
      setEditingShared(false);
      await changed(t("design.customized", { copy: created.name, source: currentName }));
    } catch (reason) {
      toast(apiErrorMessage(reason, t("design.customizeFailed")), "error");
    } finally {
      setBusy(false);
    }
  }

  // Auswahl speichert sofort (reines Auswahl-Popup); ``null`` = Standard des Vereins verwenden
  async function assign(templateId: string | null) {
    setBusy(true);
    try {
      await studioApi.setAssignment({ document_type: documentType, protocol_template_id: sessionTemplate.id, template_id: templateId });
      setEditingShared(false);
      await changed(t("design.assigned"));
    } catch (reason) {
      toast(apiErrorMessage(reason, t("design.assignFailed")), "error");
    } finally {
      setBusy(false);
    }
  }

  function usageNames(refs: SessionTemplateRef[]) {
    return listFormat.format(refs.map((ref) => ref.name));
  }

  if (design === undefined) return <p className="muted">{tStudio("common.loading")}</p>;

  const canChoose = !!capabilities?.publish_templates;
  const canEditShared = !!design && !design.owned && design.editable && !!capabilities?.publish_templates;
  const canCustomize = !!design && !design.owned && !!capabilities?.edit_templates;
  const defaultChoice = choices.find((item) => item.is_default) ?? null;
  const showDesigner = !!design && (design.owned || editingShared);

  return (
    <div className="grid">
      {error ? <StatusBanner tone="error" message={error} /> : null}
      <section className="session-design-bar" aria-label={t(`design.title.${documentType}`)}>
        <div className="session-design-bar-head">
          <div className="session-design-current">
            <span className="session-design-kicker">{t(`design.uses.${documentType}`)}</span>
            {design ? (
              <span className="session-design-name">
                {currentName}
                {isDefault ? <Badge variant="neutral">{t("design.defaultBadge")}</Badge> : null}
              </span>
            ) : (
              <span className="muted">{t("design.noneInfo")}</span>
            )}
          </div>
          {design ? (
            <p className="session-design-usage">
              {design.owned ? (
                t("design.usage.only")
              ) : others.length > 0 ? (
                <>
                  {t("design.usage.alsoIn")}{" "}
                  {others.map((ref, index) => (
                    <span key={ref.id}>
                      {index > 0 ? ", " : ""}
                      <Link href={`/templates/${ref.id}` as Route}>{ref.name}</Link>
                    </span>
                  ))}
                </>
              ) : (
                t("design.usage.onlyFallback")
              )}
              {isDefault ? ` ${t("design.usage.default")}` : ""}
            </p>
          ) : null}
        </div>
        {notice ? <StatusBanner tone="success" message={notice} /> : null}
        {design && (canChoose || canEditShared || canCustomize || editingShared) ? (
          <div className="session-design-actions">
            {canChoose ? (
              <button type="button" className="session-design-action" disabled={busy} onClick={() => setChoosing(true)}>
                <span className="session-design-action-title">{t("design.action.choose")}</span>
                <span className="session-design-action-hint">{t("design.action.chooseHint", { count: choices.length })}</span>
              </button>
            ) : null}
            {canEditShared && !editingShared ? (
              <button type="button" className="session-design-action" disabled={busy} onClick={() => { setNotice(""); setEditingShared(true); }}>
                <span className="session-design-action-title">{t("design.action.edit")}</span>
                <span className="session-design-action-hint session-design-action-hint-warning">{t("design.action.editHint", { count: design.used_in.length })}</span>
              </button>
            ) : null}
            {editingShared ? (
              <button type="button" className="session-design-action" disabled={busy} onClick={() => setEditingShared(false)}>
                <span className="session-design-action-title">{t("design.action.stopEditing")}</span>
                <span className="session-design-action-hint">{t("design.action.stopEditingHint")}</span>
              </button>
            ) : null}
            {canCustomize ? (
              <button type="button" className="session-design-action" disabled={busy} onClick={() => void customize()}>
                <span className="session-design-action-title">{t("design.action.customize")}</span>
                <span className="session-design-action-hint">{t("design.action.customizeHint", { name: sessionTemplate.name })}</span>
              </button>
            ) : null}
          </div>
        ) : null}
      </section>

      {showDesigner && design ? (
        <div className="session-design-designer">
          <TemplateDesigner
            key={design.template_id}
            templateId={design.template_id}
            sessionTemplateId={sessionTemplate.id}
            onDetach={canCustomize ? { label: t("design.action.customizeFor", { name: sessionTemplate.name }), run: () => void customize() } : null}
          />
        </div>
      ) : (
        <div className="studio-preview-pages session-design-pages">
          {pages.map((page, index) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={index} className="studio-preview-page" src={page} alt={tStudio("preview.pageAlt", { page: index + 1 })} />
          ))}
        </div>
      )}

      <Modal open={choosing} onClose={() => setChoosing(false)} title={t("design.choose.title")}>
        <p className="muted">{t("design.choose.description", { name: sessionTemplate.name })}</p>
        <div className="session-design-choices" role="radiogroup" aria-label={t("design.choose.title")}>
          <button type="button" role="radio" aria-checked={isDefault} disabled={busy} className={isDefault ? "session-design-choice session-design-choice-selected" : "session-design-choice"} onClick={() => void (isDefault ? null : assign(null))}>
            <span className="session-design-choice-title">{t("design.choose.default")}</span>
            <span className="session-design-choice-hint">{defaultChoice ? t("design.choose.defaultHint", { name: designName(defaultChoice) }) : t("design.choose.defaultHintNone")}</span>
          </button>
          {choices.map((item) => {
            const selected = !isDefault && design?.template_id === item.id;
            const users = item.used_in ?? [];
            return (
              <button key={item.id} type="button" role="radio" aria-checked={selected} disabled={busy} className={selected ? "session-design-choice session-design-choice-selected" : "session-design-choice"} onClick={() => void (selected ? null : assign(item.id))}>
                <span className="session-design-choice-title">{designName(item)}</span>
                <span className="session-design-choice-hint">{users.length > 0 ? t("design.choose.usedIn", { names: usageNames(users) }) : t("design.choose.unused")}</span>
              </button>
            );
          })}
        </div>
      </Modal>
    </div>
  );
}
