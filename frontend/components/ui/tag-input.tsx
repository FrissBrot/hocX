"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { usePopupEscape } from "@/lib/hooks/use-popup-escape";
import { ActionIcon } from "@/components/ui/action-icons";
import type { TagConfig } from "@/lib/hooks/use-tag-config";

export const TAG_COLORS = [
  "#3B82F6", "#8B5CF6", "#EC4899", "#EF4444",
  "#F97316", "#EAB308", "#22C55E", "#06B6D4", "#94A3B8",
];

export function TagInput({
  value,
  onChange,
  suggestions = [],
  placeholder,
  multi = true,
  readOnly = false,
  alwaysShowPlaceholder = false,
  tagConfig,
  onTagColorChange,
  onTagRename,
  offerCreate = false,
}: {
  value: string;
  onChange: (value: string) => void;
  suggestions?: string[];
  placeholder?: string;
  multi?: boolean;
  readOnly?: boolean;
  /** Keeps the placeholder visible even once tags exist, so the trailing input still reads
   * as an "add tag" affordance (e.g. a compact "+ Tag" pill) instead of an empty box. */
  alwaysShowPlaceholder?: boolean;
  tagConfig?: TagConfig;
  onTagColorChange?: (tag: string, color: string) => Promise<void>;
  /** `false` = abgebrochen (z. B. Rückfrage verneint): nichts übernehmen, Eingabe bleibt offen. */
  onTagRename?: (oldTag: string, newTag: string) => Promise<void | boolean>;
  /** Zeigt beim Tippen eines unbekannten Tags den Eintrag «„x“ neu erstellen» in der Liste. */
  offerCreate?: boolean;
}) {
  const t = useTranslations("common.tagInput");
  const tCommonClose = useTranslations("common")("close");
  const resolvedPlaceholder = placeholder ?? t("addPlaceholder");
  const tags = value ? value.split(",").map((tag) => tag.trim()).filter(Boolean) : [];
  const [inputVal, setInputVal] = useState("");
  const [open, setOpen] = useState(false);
  const [editingTag, setEditingTag] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const [saving, setSaving] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const filtered = suggestions.filter(
    (s) => !tags.includes(s) && (inputVal === "" || s.toLowerCase().includes(inputVal.toLowerCase()))
  );

  function addTag(tag: string) {
    const t = tag.trim();
    if (!t || readOnly) return;
    if (multi) {
      if (!tags.includes(t)) onChange([...tags, t].join(","));
    } else {
      onChange(t);
    }
    setInputVal("");
    setOpen(false);
  }

  function removeTag(tag: string) {
    if (readOnly) return;
    onChange(tags.filter((t) => t !== tag).join(","));
  }

  // Maus: Fokus bleibt im Eingabefeld (die Aktion läuft über onClick, damit Enter/Leertaste auf
  // einem fokussierten Knopf dasselbe tun - früher reagierten die Knöpfe nur auf pointerdown).
  function keepInputFocus(event: React.MouseEvent) {
    event.preventDefault();
  }

  function dropdownOptions(): HTMLElement[] {
    return Array.from(wrapRef.current?.querySelectorAll<HTMLElement>(".tag-input-dropdown .tag-input-option") ?? []);
  }

  // Pfeile wandern zwischen Eingabefeld und Vorschlägen
  function handleDropdownKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const options = dropdownOptions();
    const index = options.indexOf(document.activeElement as HTMLElement);
    if (index < 0) return;
    e.preventDefault();
    const next = index + (e.key === "ArrowDown" ? 1 : -1);
    if (next < 0) inputRef.current?.focus();
    else options[Math.min(next, options.length - 1)]?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && dropdownOptions().length > 0) {
      e.preventDefault();
      setOpen(true);
      dropdownOptions()[0]?.focus();
      return;
    }
    if (e.key === "Enter" && inputVal.trim()) {
      e.preventDefault();
      addTag(inputVal);
    } else if (e.key === "Backspace" && !inputVal && tags.length > 0) {
      removeTag(tags[tags.length - 1]);

    }
  }

  async function handleRenameConfirm() {
    if (!editingTag || !renameVal.trim() || !onTagRename) return;
    setSaving(true);
    setRenameError(null);
    const oldTag = editingTag;
    const newTag = renameVal.trim();
    try {
      if ((await onTagRename(oldTag, newTag)) === false) return;
      // Update current value if it contained the renamed tag
      if (tags.includes(oldTag)) {
        onChange(tags.map((t) => (t === oldTag ? newTag : t)).join(","));
      }
      setEditingTag(null);
    } catch {
      // Rename failed server-side - keep the edit panel open so the user
      // can retry, instead of silently pretending it worked.
      setRenameError(t("renameFailed"));
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
        setEditingTag(null);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  const showInput = !readOnly && (multi || tags.length === 0);
  const typed = inputVal.trim();
  const createOption = offerCreate && typed !== "" && !tags.includes(typed) && !suggestions.some((s) => s.toLowerCase() === typed.toLowerCase());
  const showDropdown = open && (filtered.length > 0 || createOption || editingTag !== null || (onTagColorChange && suggestions.length > 0));

  usePopupEscape(Boolean(showDropdown), async () => {
    if (editingTag && renameVal.trim() !== editingTag) {
      await handleRenameConfirm();
      return;
    }
    setEditingTag(null);
    setOpen(false);
  }, wrapRef);

  function tagDot(tag: string, size = 10) {
    const color = tagConfig?.[tag]?.color;
    if (!color) return null;
    return (
      <span
        className="tag-color-dot"
        style={{ background: color, width: size, height: size, borderRadius: "50%", display: "inline-block", flexShrink: 0 }}
      />
    );
  }

  return (
    <div
      className="tag-input-wrap"
      ref={wrapRef}
      onBlur={(event) => {
        // Fokus verlässt das Feld per Tab: Vorschläge schliessen statt offen über dem Formular stehen lassen
        if (event.relatedTarget && !wrapRef.current?.contains(event.relatedTarget as Node)) {
          setOpen(false);
          setEditingTag(null);
        }
      }}
    >
      <div className="tag-input-field" onClick={() => inputRef.current?.focus()}> {/* a11y-ok: Klickfläche fokussiert nur das Eingabefeld, das selbst per Tab erreichbar ist */}
        {tags.map((tag) => {
          const color = tagConfig?.[tag]?.color;
          return (
            <span
              key={tag}
              className="tag-chip"
              style={color ? { backgroundColor: `${color}22`, borderColor: `${color}55`, color } : undefined}
            >
              {tagDot(tag, 8)}
              {tag}
              {!readOnly && (
                <button
                  type="button"
                  className="tag-chip-remove"
                  onClick={(e) => { e.stopPropagation(); removeTag(tag); }}
                  aria-label={t("removeTag", { tag })}
                >
                  ×
                </button>
              )}
            </span>
          );
        })}
        {showInput && (
          <input
            ref={inputRef}
            className="tag-input-text"
            value={inputVal}
            onChange={(e) => { setInputVal(e.target.value); setOpen(true); setEditingTag(null); }}
            onFocus={() => setOpen(true)}
            onKeyDown={handleKeyDown}
            placeholder={alwaysShowPlaceholder || tags.length === 0 ? resolvedPlaceholder : ""}
          />
        )}
      </div>

      {showDropdown && (
        <div className="tag-input-dropdown" onKeyDown={handleDropdownKeyDown}>
          {editingTag !== null ? (
            <div className="tag-edit-panel">
              <div className="tag-edit-header">
                <span className="tag-edit-title">{t("editTag")}</span>
                <button type="button" className="tag-edit-cancel" title={tCommonClose} aria-label={tCommonClose} onMouseDown={keepInputFocus} onClick={() => { setEditingTag(null); setRenameError(null); inputRef.current?.focus(); }}><ActionIcon name="close" /></button>
              </div>
              {onTagRename && (
                <input
                  className="tag-edit-rename"
                  value={renameVal}
                  onChange={(e) => { setRenameVal(e.target.value); setRenameError(null); }}
                  onKeyDown={(e) => { if (e.key === "Enter") void handleRenameConfirm(); }}
                  placeholder={t("newNamePlaceholder")}
                  autoFocus
                />
              )}
              {renameError && (
                <div style={{ color: "var(--danger)", fontSize: "var(--text-xs)", padding: "2px var(--space-1)" }}>{renameError}</div>
              )}
              {onTagColorChange && (
                <div className="tag-color-swatches">
                  {TAG_COLORS.map((hex) => (
                    <button
                      key={hex}
                      type="button"
                      className={`tag-color-swatch${tagConfig?.[editingTag]?.color === hex ? " tag-color-swatch-active" : ""}`}
                      style={{ background: hex }}
                      onMouseDown={keepInputFocus}
                      onClick={() => void onTagColorChange(editingTag, hex)}
                      title={hex}
                      aria-label={hex}
                      aria-pressed={tagConfig?.[editingTag]?.color === hex}
                    />
                  ))}
                  <button
                    type="button"
                    className="tag-color-swatch tag-color-swatch-none"
                    onMouseDown={keepInputFocus}
                    onClick={() => void onTagColorChange(editingTag, "")}
                    title={t("noColor")}
                    aria-label={t("noColor")}
                  >
                    <span aria-hidden="true">✕</span>
                  </button>
                </div>
              )}
              {onTagRename && (
                <button
                  type="button"
                  className="tag-edit-save"
                  disabled={saving || !renameVal.trim() || renameVal.trim() === editingTag}
                  onMouseDown={keepInputFocus}
                  onClick={() => void handleRenameConfirm()}
                >
                  {saving ? "…" : t("rename")}
                </button>
              )}
            </div>
          ) : null}

          {createOption ? (
            <div className="tag-input-option-row">
              <button
                type="button"
                className="tag-input-option tag-input-option-create"
                onMouseDown={keepInputFocus}
                onClick={() => { addTag(typed); inputRef.current?.focus(); }}
              >
                {t("createTag", { tag: typed })}
              </button>
            </div>
          ) : null}
          {filtered.map((s) => (
            <div key={s} className="tag-input-option-row">
              <button
                type="button"
                className="tag-input-option"
                onMouseDown={keepInputFocus}
                onClick={() => { addTag(s); inputRef.current?.focus(); }}
              >
                {tagDot(s)}
                {s}
              </button>
              {(onTagColorChange || onTagRename) && (
                <button
                  type="button"
                  className="tag-input-edit-btn"
                  title={t("colorOrRename")}
                  aria-label={t("colorOrRename")}
                  onMouseDown={keepInputFocus}
                  onClick={() => {
                    setEditingTag(s);
                    setRenameVal(s);
                    setRenameError(null);
                  }}
                >
                  <ActionIcon name="edit" />
                </button>
              )}
            </div>
          ))}

          {filtered.length === 0 && editingTag === null && inputVal.trim() && (
            <button
              type="button"
              className="tag-input-option"
              onMouseDown={keepInputFocus}
              onClick={() => { addTag(inputVal); inputRef.current?.focus(); }}
            >
              {t("addNewTag", { tag: inputVal })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
