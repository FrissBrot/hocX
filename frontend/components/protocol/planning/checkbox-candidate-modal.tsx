"use client";

import { useMemo, useState } from "react";

import { Modal } from "@/components/ui/modal";

export type CandidateItem = {
  id: string;
  label: string;
  sublabel?: string;
  checked: boolean;
  disabled?: boolean;
  groupLabel?: string;
  /** Set to false to hide the onRemove button for this specific item (e.g. candidates that don't exist yet). */
  removable?: boolean;
  /** Set to false to hide the edit icon for this specific item. */
  editable?: boolean;
};

type CheckboxCandidateModalProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  items: CandidateItem[];
  searchable?: boolean;
  loading?: boolean;
  emptyMessage?: string;
  onToggle: (item: CandidateItem, nextChecked: boolean) => void | Promise<void>;
  /** Optional destructive action per item (e.g. "endgültig löschen"), separate from the checked/unchecked toggle. */
  onRemove?: (item: CandidateItem) => void | Promise<void>;
  removeLabel?: string;
  /** Renders an inline edit form inside the card when the item's edit icon is clicked. */
  renderEditForm?: (item: CandidateItem, close: () => void) => React.ReactNode;
  /** Rendered above the search/list — for scope toggles, "+ Neu anlegen", etc. */
  topActions?: React.ReactNode;
};

/**
 * Generic "search + click-to-toggle card list" popup, modelled on the editor's existing
 * multi-participant picker. Used for both "Termine pro Element" (3a) and "Matrix-Spalten
 * aus Quelle" (3b) checkbox-selection popups in planning mode ("geplant") — a new, parallel
 * component rather than a refactor of the participant picker, to avoid touching state that
 * "durchgeführt" still relies on. Checked state is shown via the card's border/background,
 * not a visible checkbox — clicking anywhere on the card toggles it.
 */
export function CheckboxCandidateModal({
  open,
  onClose,
  title,
  description,
  items,
  searchable = true,
  loading = false,
  emptyMessage = "Keine Elemente gefunden.",
  onToggle,
  onRemove,
  removeLabel = "Endgültig löschen",
  renderEditForm,
  topActions,
}: CheckboxCandidateModalProps) {
  const [search, setSearch] = useState("");
  const [editingItem, setEditingItem] = useState<CandidateItem | null>(null);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter(
      (item) => item.label.toLowerCase().includes(query) || (item.sublabel ?? "").toLowerCase().includes(query)
    );
  }, [items, search]);

  const groups = useMemo(() => {
    const map = new Map<string, CandidateItem[]>();
    for (const item of filtered) {
      const key = item.groupLabel ?? "";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(item);
    }
    return Array.from(map.entries());
  }, [filtered]);

  return (
    <Modal open={open} onClose={onClose} title={title} description={description} size="wide">
      <div className="checkbox-candidate-modal">
        {topActions ? <div className="checkbox-candidate-modal-top-actions">{topActions}</div> : null}

        {searchable && (
          <label className="field-stack">
            <span className="field-label">Suche</span>
            <input className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Suchen…" autoFocus />
          </label>
        )}

        {loading ? (
          <p className="muted">Lädt…</p>
        ) : filtered.length === 0 ? (
          <p className="muted">{emptyMessage}</p>
        ) : (
          groups.map(([groupLabel, groupItems], groupIndex) => (
            <div key={groupLabel || "_"} className={`candidate-group${groupIndex > 0 ? " candidate-group-divider" : ""}`}>
              {groupLabel ? (
                <div className="candidate-group-heading">
                  <span>{groupLabel}</span>
                  <span className="candidate-group-count">{groupItems.length}</span>
                </div>
              ) : null}
              <div className="participant-check-grid">
                {groupItems.map((item) => (
                  <div
                    key={item.id}
                    role="button"
                    tabIndex={item.disabled ? -1 : 0}
                    aria-pressed={item.checked}
                    className={`candidate-card${item.checked ? " candidate-card-checked" : ""}${item.disabled ? " candidate-card-disabled" : ""}`}
                    onClick={() => {
                      if (item.disabled) return;
                      void onToggle(item, !item.checked);
                    }}
                    onKeyDown={(e) => {
                      if (item.disabled) return;
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        void onToggle(item, !item.checked);
                      }
                    }}
                  >
                    {(renderEditForm && item.editable !== false) || (onRemove && item.removable !== false) ? (
                      <div className="candidate-card-toolbar">
                        {renderEditForm && item.editable !== false ? (
                          <button
                            type="button"
                            className="button-ghost button-icon candidate-card-edit"
                            title="Termin bearbeiten"
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditingItem(item);
                            }}
                          >
                            ✎
                          </button>
                        ) : (
                          <span />
                        )}
                        {onRemove && item.removable !== false ? (
                          <button
                            type="button"
                            className="button-ghost button-icon button-icon-danger"
                            title={removeLabel}
                            onClick={(e) => {
                              e.stopPropagation();
                              void onRemove(item);
                            }}
                          >
                            x
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                    <div className="candidate-card-body">
                      <div>{item.label}</div>
                      {item.sublabel ? <div className="muted">{item.sublabel}</div> : null}
                    </div>
                    <span className="candidate-card-check" aria-hidden="true">
                      ✓
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {renderEditForm ? (
        <Modal open={Boolean(editingItem)} onClose={() => setEditingItem(null)} title="Termin bearbeiten" size="wide">
          {editingItem ? renderEditForm(editingItem, () => setEditingItem(null)) : null}
        </Modal>
      ) : null}
    </Modal>
  );
}
