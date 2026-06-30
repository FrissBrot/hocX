"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { browserApiFetch } from "@/lib/api/client";

export type TagConfig = Record<string, { color?: string }>;

export function useTagConfig() {
  const [tagConfig, setTagConfig] = useState<TagConfig>({});
  const configRef = useRef<TagConfig>({});
  configRef.current = tagConfig;

  useEffect(() => {
    browserApiFetch<TagConfig>("/api/tag-config")
      .then((data) => { if (data && typeof data === "object") setTagConfig(data as TagConfig); })
      .catch(() => {});
  }, []);

  const updateTagColor = useCallback(async (tag: string, color: string) => {
    setTagConfig((prev) => ({ ...prev, [tag]: { ...(prev[tag] ?? {}), color } }));
    await browserApiFetch("/api/tag-config", {
      method: "PATCH",
      body: JSON.stringify({ [tag]: { color } }),
    }).catch(() => {});
  }, []);

  const renameTag = useCallback(async (oldTag: string, newTag: string): Promise<void> => {
    const nt = newTag.trim();
    if (!nt || nt === oldTag) return;
    await browserApiFetch("/api/events/rename-tag", {
      method: "POST",
      body: JSON.stringify({ old_tag: oldTag, new_tag: nt }),
    }).catch(() => {});
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
