"use client";

import { useTranslations } from "next-intl";

// Traktanden-Änderungen gegenüber der Vorlage beim «Protokoll abschliessen» (API
// GET /protocols/{id}/template-changes): genaue Liste, jede Änderung einzeln wählbar. Änderungen im
// Protokoll ändern die Vorlage nie von selbst - nur, was hier gewählt und bestätigt wird.

export type TemplateChange =
  | { key: string; kind: "added"; element_id: string; title: string; after_title: string | null }
  | { key: string; kind: "renamed"; element_id: string; old_title: string; new_title: string }
  | { key: string; kind: "visibility"; element_id: string; title: string; old_visible: boolean; new_visible: boolean }
  | { key: string; kind: "order"; old_order: { element_id: string; title: string }[]; new_order: { element_id: string; title: string }[] };

export type TemplateChanges = {
  template_id: string;
  template_name: string;
  template_version: number;
  can_apply: boolean;
  changes: TemplateChange[];
};

type Props = {
  data: TemplateChanges;
  selected: ReadonlySet<string>;
  onToggle: (key: string) => void;
};

export function TemplateChangesReview({ data, selected, onToggle }: Props) {
  const t = useTranslations("protocols.editor.templateChanges");

  function describe(change: TemplateChange): string {
    switch (change.kind) {
      case "added":
        return change.after_title ? t("added", { title: change.title, after: change.after_title }) : t("addedFirst", { title: change.title });
      case "renamed":
        return t("renamed", { from: change.old_title, to: change.new_title });
      case "visibility":
        return change.new_visible ? t("shown", { title: change.title }) : t("hidden", { title: change.title });
      case "order":
        return t("order", { order: change.new_order.map((entry) => entry.title).join(" → ") });
    }
  }

  return (
    <section className="protocol-template-changes" aria-labelledby="protocol-template-changes-title">
      <h3 className="protocol-drawer-section-title" id="protocol-template-changes-title">
        {t("title", { template: data.template_name })}
      </h3>
      <p className="field-help">{data.can_apply ? t("intro") : t("noPermission")}</p>
      <ul className="protocol-template-changes-list">
        {data.changes.map((change) => (
          <li key={change.key}>
            {data.can_apply ? (
              <label className="protocol-template-change">
                <input type="checkbox" checked={selected.has(change.key)} onChange={() => onToggle(change.key)} />
                <span>{describe(change)}</span>
              </label>
            ) : (
              <span className="protocol-template-change">{describe(change)}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
