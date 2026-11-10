"use client";

// Zuweisungen: Standardvorlage je Dokumenttyp und - für Protokoll-Dokumente - abweichende
// Vorlage oder abweichendes Brand-Profil je Protokollvorlage. Priorität beim Export:
// explizit gewählt > Protokollvorlage > Mandanten-Standard > Plattform-Standard.

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { templateDisplayName } from "@/components/documents/studio-labels";
import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage, Assignment, Brand, DocumentTemplateInfo, DocumentTypeInfo, studioApi } from "@/lib/documents/api";
import { Select } from "@/components/ui/select";

type ProtocolTemplate = { id: string; name: string };
type Props = { open: boolean; onClose: () => void; types: DocumentTypeInfo[]; templates: DocumentTemplateInfo[] };

export function AssignmentsModal({ open, onClose, types, templates }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [protocolTemplates, setProtocolTemplates] = useState<ProtocolTemplate[]>([]);
  const [newScope, setNewScope] = useState<string | null>(null);

  const load = useCallback(() => {
    void studioApi.assignments().then(setAssignments).catch((error) => toast(apiErrorMessage(error, t("assignments.loadFailed")), "error"));
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
    void studioApi.brands().then(setBrands);
    void browserApiFetch<ProtocolTemplate[]>("/api/templates").then((rows) => setProtocolTemplates(rows ?? []));
  }, [load]);

  async function save(body: { document_type: string; protocol_template_id?: string | null; template_id?: string | null; brand_id?: string | null }) {
    try {
      await studioApi.setAssignment(body);
      toast(t("assignments.saved"), "success");
      load();
    } catch (error) {
      toast(apiErrorMessage(error, t("common.actionFailed")), "error");
    }
  }

  const published = (documentType: string) => templates.filter((item) => item.document_type === documentType && item.published_revision && item.status === "active");
  const scoped = assignments.filter((item) => item.protocol_template_id);
  const protocolTypes = types.filter((item) => item.needs_protocol);

  return (
    <Modal className="studio-modal" open={open} onClose={onClose} title={t("assignments.title")} description={t("assignments.description")} size="wide">
      <section className="grid" aria-labelledby="studio-assign-defaults">
        <h3 id="studio-assign-defaults" className="studio-section-title">
          {t("assignments.defaults")}
        </h3>
        <div className="table-shell">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t("assignments.documentType")}</th>
                <th scope="col">{t("assignments.template")}</th>
                <th scope="col">{t("assignments.brand")}</th>
              </tr>
            </thead>
            <tbody>
              {types.map((type) => {
                const current = assignments.find((item) => item.document_type === type.key && !item.protocol_template_id);
                return (
                  <tr key={type.key}>
                    <td>{t(`docType.${type.key}`)}</td>
                    <td>
                      <SearchableSelect
                        options={published(type.key)}
                        getId={(item) => item.id}
                        getLabel={(item) => templateDisplayName(t, item)}
                        value={current?.template_id ?? null}
                        onChange={(item) => void save({ document_type: type.key, template_id: item?.id ?? null, brand_id: current?.brand_id ?? null })}
                        nullLabel={t("assignments.platformDefault")}
                      />
                    </td>
                    <td>
                      <Select value={current?.brand_id ?? ""} onChange={(event) => void save({ document_type: type.key, template_id: current?.template_id ?? null, brand_id: event.target.value || null })}>
                        <option value="">{t("assignments.brandDefault")}</option>
                        {brands.map((brand) => (
                          <option key={brand.id} value={brand.id}>
                            {brand.name}
                          </option>
                        ))}
                      </Select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid studio-assign-scoped" aria-labelledby="studio-assign-scoped">
        <h3 id="studio-assign-scoped" className="studio-section-title">
          {t("assignments.perProtocolTemplate")}
        </h3>
        <p className="field-help">{t("assignments.perProtocolTemplateHelp")}</p>
        <div className="table-shell">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t("assignments.protocolTemplate")}</th>
                <th scope="col">{t("assignments.documentType")}</th>
                <th scope="col">{t("assignments.template")}</th>
                <th scope="col">{t("assignments.brand")}</th>
                <th scope="col" aria-label={t("assignments.actions")} />
              </tr>
            </thead>
            <tbody>
              {scoped.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    {t("assignments.noScoped")}
                  </td>
                </tr>
              )}
              {scoped.map((item) => (
                <tr key={`${item.protocol_template_id}-${item.document_type}`}>
                  <td>{item.protocol_template_name}</td>
                  <td>{t(`docType.${item.document_type}`)}</td>
                  <td>
                    <SearchableSelect
                      options={published(item.document_type)}
                      getId={(template) => template.id}
                      getLabel={(template) => templateDisplayName(t, template)}
                      value={item.template_id}
                      onChange={(template) => void save({ document_type: item.document_type, protocol_template_id: item.protocol_template_id, template_id: template?.id ?? null, brand_id: item.brand_id })}
                      nullLabel={t("assignments.inherit")}
                    />
                  </td>
                  <td>
                    <Select value={item.brand_id ?? ""} onChange={(event) => void save({ document_type: item.document_type, protocol_template_id: item.protocol_template_id, template_id: item.template_id, brand_id: event.target.value || null })}>
                      <option value="">{t("assignments.inherit")}</option>
                      {brands.map((brand) => (
                        <option key={brand.id} value={brand.id}>
                          {brand.name}
                        </option>
                      ))}
                    </Select>
                  </td>
                  <td>
                    <button type="button" className="button-danger" onClick={() => void save({ document_type: item.document_type, protocol_template_id: item.protocol_template_id })}>
                      {t("assignments.remove")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="studio-assign-add">
          <SearchableSelect options={protocolTemplates} getId={(item) => item.id} getLabel={(item) => item.name} value={newScope} onChange={(item) => setNewScope(item?.id ?? null)} placeholder={t("assignments.chooseProtocolTemplate")} />
          <button
            type="button"
            className="button-secondary"
            disabled={!newScope || brands.length === 0}
            onClick={() => {
              const brand = brands.find((item) => item.is_default) ?? brands[0];
              if (newScope && brand) void save({ document_type: protocolTypes[0]?.key ?? "protocol", protocol_template_id: newScope, brand_id: brand.id });
              setNewScope(null);
            }}
          >
            {t("assignments.add")}
          </button>
        </div>
      </section>
    </Modal>
  );
}
