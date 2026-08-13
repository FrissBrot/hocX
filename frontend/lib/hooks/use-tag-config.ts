"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";

export type TagConfig = Record<string, { color?: string }>;

export function useTagConfig() {
  const [tagConfig, setTagConfig] = useState<TagConfig>({});
  const configRef = useRef<TagConfig>({});
  configRef.current = tagConfig;
  const showToast = useToast();

  useEffect(() => {
    browserApiFetch<TagConfig>("/api/tag-config")
      .then((data) => { if (data && typeof data === "object") setTagConfig(data as TagConfig); })
      .catch(() => {});
  }, []);

  const updateTagColor = useCallback(async (tag: string, color: string) => {
    const previousEntry = configRef.current[tag];
    setTagConfig((prev) => ({ ...prev, [tag]: { ...(prev[tag] ?? {}), color } }));
    try {
      await browserApiFetch("/api/tag-config", {
        method: "PATCH",
        body: JSON.stringify({ [tag]: { color } }),
      });
    } catch (error) {
      // Roll back only this tag's entry so a failed save doesn't clobber other
      // tag-config changes that may have landed in the meantime.
      setTagConfig((prev) => {
        const next = { ...prev };
        if (previousEntry) {
          next[tag] = previousEntry;
        } else {
          delete next[tag];
        }
        return next;
      });
      showToast(error instanceof Error ? error.message : "Farbe konnte nicht gespeichert werden", "error");
    }
  }, [showToast]);

  const renameTag = useCallback(async (oldTag: string, newTag: string): Promise<void> => {
    const nt = newTag.trim();
    if (!nt || nt === oldTag) return;
    // No .catch() here on purpose: if the backend rejects the rename, the error
    // must propagate to the caller instead of us renaming the tag only locally.
    await browserApiFetch("/api/events/rename-tag", {
      method: "POST",
      body: JSON.stringify({ old_tag: oldTag, new_tag: nt }),
    });
    setTagConfig((prev) => {
      const next = { ...prev };
      const oldCfg = next[oldTag];
      delete next[oldTag];
      if (oldCfg) next[nt] = oldCfg;
      return next;
    });
    await browserApiFetch("/api/tag-config", {
      method: "PATCH",
      body: JSON.stringify({ [nt]: configRef.current[oldTag] ?? {}, [oldTag]: {} }),
    }).catch(() => {});
  }, []);

  return { tagConfig, updateTagColor, renameTag };
}
