"use client";

import type { ReactElement } from "react";
import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { elementTypeOptions } from "@/lib/constants/element-types";
import { ELEMENT_TYPE_CATEGORIES, elementTypeCode, pickableElementTypes } from "@/lib/element-types/registry";

/** Skizze eines Blocktyps (Typauswahl und Vorschau in der Seitenleiste). */
export function BlockTypePreview({ elementTypeId }: { elementTypeId: number }) {
  const code = elementTypeCode(elementTypeId);
  const rows = (count: number, render: (index: number) => ReactElement) => Array.from({ length: count }).map((_, index) => render(index));
  if (code === "todo") {
    return (
      <div className="block-type-preview">
        {rows(3, (index) => (
          <div key={index} className="block-type-preview-row">
            <div className={`block-type-preview-checkbox${index !== 1 ? " block-type-preview-checkbox-checked" : ""}`} />
            <div className={`block-type-preview-line${index !== 1 ? " block-type-preview-line-short" : ""}`} />
          </div>
        ))}
      </div>
    );
  }
  if (code === "image") {
    return (
      <div className="block-type-preview">
        <div className="block-type-preview-image" />
        <div className="block-type-preview-line block-type-preview-line-short" />
      </div>
    );
  }
  if (code === "form") {
    return (
      <div className="block-type-preview">
        <div className="block-type-preview-grid block-type-preview-grid-cols-2">
          {rows(6, (index) => <div key={index} className={`block-type-preview-cell${index % 2 ? " block-type-preview-cell-accent" : ""}`} />)}
        </div>
      </div>
    );
  }
  if (code === "event_list") {
    return (
      <div className="block-type-preview">
        {rows(3, (index) => (
          <div key={index} className="block-type-preview-row">
            <div className="block-type-preview-tag" />
            <div className={`block-type-preview-line${index === 1 ? " block-type-preview-line-short" : ""}`} />
          </div>
        ))}
      </div>
    );
  }
  if (code === "attendance" || code === "entry_exit") {
    const count = code === "attendance" ? 4 : 2;
    return (
      <div className="block-type-preview">
        {rows(count, (index) => (
          <div key={index} className="block-type-preview-row">
            <div className={`block-type-preview-dot${index === 2 || (code === "entry_exit" && index === 1) ? " block-type-preview-dot-muted" : ""}`} />
            <div className={`block-type-preview-line${index % 2 === 0 ? " block-type-preview-line-short" : ""}`} />
          </div>
        ))}
      </div>
    );
  }
  if (code === "session_date") {
    return (
      <div className="block-type-preview-calendar">
        <div className="block-type-preview-calendar-head" />
        <div className="block-type-preview-calendar-body">
          {rows(8, (index) => (
            <div key={index} className={`block-type-preview-calendar-cell${index === 5 ? " block-type-preview-calendar-cell-active" : ""}`} />
          ))}
        </div>
      </div>
    );
  }
  if (code === "matrix") {
    return (
      <div className="block-type-preview">
        <div className="block-type-preview-grid block-type-preview-grid-cols-3">
          {rows(9, (index) => <div key={index} className={`block-type-preview-cell${index < 3 ? " block-type-preview-cell-accent" : ""}`} />)}
        </div>
      </div>
    );
  }
  if (code === "finance_balance") {
    return (
      <div className="block-type-preview">
        <div className="block-type-preview-line block-type-preview-line-short" />
        <div className="block-type-preview-amount" />
        <div className="block-type-preview-line block-type-preview-line-short" />
      </div>
    );
  }
  if (code === "finance_transactions" || code === "fine_list") {
    return (
      <div className="block-type-preview">
        {rows(3, (index) => (
          <div key={index} className="block-type-preview-row-between">
            <div className={`block-type-preview-line${index === 1 ? " block-type-preview-line-short" : ""}`} />
            <div className={`block-type-preview-tag${code === "fine_list" ? " block-type-preview-tag-warn" : ""}`} />
          </div>
        ))}
      </div>
    );
  }
  if (code === "chart") {
    return (
      <div className="block-type-preview">
        <div className="block-type-preview-bars">
          {[45, 78, 32, 90, 58].map((height) => (
            <div key={height} className="block-type-preview-bar" style={{ height: `${height}%` }} />
          ))}
        </div>
      </div>
    );
  }
  if (code === "session_notes") {
    return (
      <div className="block-type-preview">
        <div className="block-type-preview-chip-row">
          <div className="block-type-preview-chip" />
        </div>
        <div className="block-type-preview-line" />
        <div className="block-type-preview-line block-type-preview-line-short" />
        <div className="block-type-preview-line" />
      </div>
    );
  }
  return (
    <div className="block-type-preview">
      <div className="block-type-preview-title" />
      <div className="block-type-preview-line" />
      <div className="block-type-preview-line" />
      <div className="block-type-preview-line block-type-preview-line-short" />
    </div>
  );
}

export function TypePickerModal({
  open,
  activeTypeId,
  onPick,
  onClose,
}: {
  open: boolean;
  activeTypeId: number;
  onPick: (elementTypeId: number) => void;
  onClose: () => void;
}) {
  const t = useTranslations("templates.elementEditor");
  const tTypes = useTranslations("templates");
  const options = elementTypeOptions(tTypes);
  const pickable = pickableElementTypes();
  return (
    <Modal open={open} onClose={onClose} title={t("typePicker.title")} description={t("typePicker.description")} size="fullscreen">
      <div className="grid">
        <div className="block-type-category-stack">
          {ELEMENT_TYPE_CATEGORIES.map((category) => {
            const types = pickable.filter((type) => type.category === category);
            if (!types.length) return null;
            return (
              <section key={category} className="block-type-category">
                <div className="block-type-category-head">
                  <h3>{t(`typePicker.categories.${category}.title`)}</h3>
                  <p className="muted">{t(`typePicker.categories.${category}.description`)}</p>
                </div>
                <div className="block-type-grid">
                  {types.map((type) => {
                    const option = options.find((entry) => entry.value === String(type.id));
                    return (
                      <button
                        key={type.id}
                        type="button"
                        className={`block-type-card${activeTypeId === type.id ? " block-type-card-active" : ""}`}
                        onClick={() => onPick(type.id)}
                      >
                        <BlockTypePreview elementTypeId={type.id} />
                        <div className="block-type-summary">
                          <div className="block-type-card-head">
                            <strong>{option?.label ?? type.code}</strong>
                          </div>
                          <span className="muted">{option?.description}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("cancel")}</button>
        </div>
      </div>
    </Modal>
  );
}
