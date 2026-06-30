"use client";
import { useEffect, useRef, useState } from "react";
import type { TagConfig } from "@/lib/hooks/use-tag-config";

export const TAG_COLORS = [
  "#3B82F6", "#8B5CF6", "#EC4899", "#EF4444",
  "#F97316", "#EAB308", "#22C55E", "#06B6D4", "#94A3B8",
];

export function TagInput({
  value,
  onChange,
  suggestions = [],
  placeholder = "Tag hinzufügen…",
  multi = true,
  readOnly = false,
  tagConfig,
  onTagColorChange,
  onTagRename,
}: {
  value: string;
  onChange: (value: string) => void;
  suggestions?: string[];
  placeholder?: string;
  multi?: boolean;
  readOnly?: boolean;
  tagConfig?: TagConfig;
  onTagColorChange?: (tag: string, color: string) => Promise<void>;
  onTagRename?: (oldTag: string, newTag: string) => Promise<void>;
}) {
  const tags = value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [];
  const [inputVal, setInputVal] = useState("");
  const [open, setOpen] = useState(false);
  const [editingTag, setEditingTag] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const [saving, setSaving] = useState(false);
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

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && inputVal.trim()) {
      e.preventDefault();
      addTag(inputVal);
    } else if (e.key === "Backspace" && !inputVal && tags.length > 0) {
      removeTag(tags[tags.length - 1]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  async function handleRenameConfirm() {
    if (!editingTag || !renameVal.trim() || !onTagRename) return;
    setSaving(true);
    const oldTag = editingTag;
    const newTag = renameVal.trim();
    await onTagRename(oldTag, newTag);
    // Update current value if it contained the renamed tag
    if (tags.includes(oldTag)) {
      onChange(tags.map((t) => (t === oldTag ? newTag : t)).join(","));
    }
    setSaving(false);
    setEditingTag(null);
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
  const showDropdown = open && (filtered.length > 0 || editingTag !== null || (onTagColorChange && suggestions.length > 0));

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
    <div className="tag-input-wrap" ref={wrapRef}>
      <div className="tag-input-field" onClick={() => inputRef.current?.focus()}>
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
                  tabIndex={-1}
                  onClick={(e) => { e.stopPropagation(); removeTag(tag); }}
                  aria-label={`Tag ${tag} entfernen`}
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
            placeholder={tags.length === 0 ? placeholder : ""}
          />
        )}
      </div>

      {showDropdown && (
        <div className="tag-input-dropdown">
          {editingTag !== null ? (
            <div className="tag-edit-panel">
              <div className="tag-edit-header">
                <span className="tag-edit-title">Tag bearbeiten</span>
                <button type="button" className="tag-edit-cancel" onPointerDown={(e) => { e.preventDefault(); setEditingTag(null); }}>✕</button>
              </div>
              {onTagRename && (
                <input
                  className="tag-edit-rename"
                  value={renameVal}
                  onChange={(e) => setRenameVal(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") void handleRenameConfirm(); }}
                  placeholder="Neuer Name…"
                  autoFocus
                />
              )}
              {onTagColorChange && (
                <div className="tag-color-swatches">
                  {TAG_COLORS.map((hex) => (
                    <button
                      key={hex}
                      type="button"
                      className={`tag-color-swatch${tagConfig?.[editingTag]?.color === hex ? " tag-color-swatch-active" : ""}`}
                      style={{ background: hex }}
                      onPointerDown={async (e) => {
                        e.preventDefault();
                        await onTagColorChange(editingTag, hex);
                      }}
                      title={hex}
                    />
                  ))}
                  <button
                    type="button"
                    className="tag-color-swatch tag-color-swatch-none"
                    onPointerDown={async (e) => {
                      e.preventDefault();
                      await onTagColorChange(editingTag, "");
                    }}
                    title="Keine Farbe"
                  >
                    ✕
                  </button>
                </div>
              )}
              {onTagRename && (
                <button
                  type="button"
                  className="tag-edit-save"
                  disabled={saving || !renameVal.trim() || renameVal.trim() === editingTag}
                  onPointerDown={async (e) => { e.preventDefault(); await handleRenameConfirm(); }}
                >
                  {saving ? "…" : "Umbenennen"}
                </button>
              )}
            </div>
          ) : null}

          {filtered.map((s) => (
            <div key={s} className="tag-input-option-row">
              <button
                type="button"
                className="tag-input-option"
                onPointerDown={(e) => { e.preventDefault(); addTag(s); }}
              >
                {tagDot(s)}
                {s}
              </button>
              {(onTagColorChange || onTagRename) && (
                <button
                  type="button"
                  className="tag-input-edit-btn"
                  title="Farbe / Umbenennen"
                  onPointerDown={(e) => {
                    e.preventDefault();
                    setEditingTag(s);
                    setRenameVal(s);
                  }}
                >
                  ✎
                </button>
              )}
            </div>
          ))}

          {filtered.length === 0 && editingTag === null && inputVal.trim() && (
            <button
              type="button"
              className="tag-input-option"
              onPointerDown={(e) => { e.preventDefault(); addTag(inputVal); }}
            >
              + „{inputVal}" hinzufügen
            </button>
          )}
        </div>
      )}
    </div>
  );
}
