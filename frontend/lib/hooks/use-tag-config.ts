"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { browserApiFetch } from "@/lib/api/client";
import { useTranslations } from "next-intl";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";

type RenameTagCounts = { updated: number; events: number; submission_assignments: number; target_events: number };

export type TagConfigEntry = { color?: string; important?: boolean };
export type TagConfig = Record<string, TagConfigEntry>;

/** Als wichtig markierte Tags zuerst (alphabetisch), danach die übrigen alphabetisch. */
export function sortTagsByImportance<T>(items: T[], config: TagConfig, tagOf: (item: T) => string): T[] {
  return [...items].sort((left, right) => {
    const leftTag = tagOf(left);
    const rightTag = tagOf(right);
    const importance = Number(!!config[rightTag]?.important) - Number(!!config[leftTag]?.important);
    return importance || leftTag.localeCompare(rightTag);
  });
}

export function useTagConfig() {
  const [tagConfig, setTagConfig] = useState<TagConfig>({});
  const configRef = useRef<TagConfig>({});
  configRef.current = tagConfig;
  const showToast = useToast();
  const tCommon = useTranslations("common");
  const tEvents = useTranslations("common");
  const confirm = useConfirm();

  useEffect(() => {
    browserApiFetch<TagConfig>("/api/tag-config")
      .then((data) => { if (data && typeof data === "object") setTagConfig(data as TagConfig); })
      .catch(() => {});
  }, []);

  const patchTagEntry = useCallback(async (tag: string, patch: TagConfigEntry, errorMessage: string) => {
    const previousEntry = configRef.current[tag];
    setTagConfig((prev) => ({ ...prev, [tag]: { ...(prev[tag] ?? {}), ...patch } }));
    try {
      await browserApiFetch("/api/tag-config", {
        method: "PATCH",
        body: JSON.stringify({ [tag]: patch }),
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
      showToast(error instanceof Error ? error.message : errorMessage, "error");
    }
  }, [showToast]);

  const updateTagColor = useCallback(
    (tag: string, color: string) => patchTagEntry(tag, { color }, tEvents("tagRename.colorSaveFailed")),
    [patchTagEntry, tEvents]
  );

  const toggleTagImportant = useCallback(
    (tag: string) => patchTagEntry(tag, { important: !configRef.current[tag]?.important }, tEvents("tagRename.importantSaveFailed")),
    [patchTagEntry, tEvents]
  );

  const renameTag = useCallback(async (oldTag: string, newTag: string): Promise<boolean> => {
    const nt = newTag.trim();
    if (!nt || nt === oldTag) return false;
    // Erst zählen, dann nachfragen: Umbenennen ändert alle Termine des Mandanten mit diesem Tag
    // und die Filter der Abgaben; ist der neue Tag schon vergeben, verschmelzen beide dauerhaft.
    const counts = await browserApiFetch<RenameTagCounts>("/api/events/rename-tag", {
      method: "POST",
      body: JSON.stringify({ old_tag: oldTag, new_tag: nt, dry_run: true }),
    });
    const parts = [tEvents("tagRename.confirmEvents", { oldTag, newTag: nt, count: counts.events })];
    if (counts.submission_assignments > 0) {
      parts.push(tEvents("tagRename.confirmAssignments", { count: counts.submission_assignments }));
    }
    if (counts.target_events > 0) {
      parts.push(tEvents("tagRename.confirmMerge", { newTag: nt, count: counts.target_events }));
    }
    const ok = await confirm({
      title: counts.target_events > 0 ? tEvents("tagRename.mergeTitle") : tEvents("tagRename.title"),
      message: parts.join(" "),
      confirmLabel: counts.target_events > 0 ? tEvents("tagRename.mergeConfirm") : tEvents("tagRename.confirm"),
    });
    if (!ok) return false;
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
    try {
      await browserApiFetch("/api/tag-config", {
        method: "PATCH",
        body: JSON.stringify({ [nt]: configRef.current[oldTag] ?? {}, [oldTag]: {} }),
      });
    } catch {
      // The rename itself already succeeded (above) - only the color carry-over failed, so
      // this must not throw and undo it. Still tell the user, otherwise the tag silently
      // loses its color with no indication anything went wrong.
      showToast(tCommon("clientErrors.tagColorTransferFailed"), "error");
    }
    return true;
  }, [showToast, tCommon, tEvents, confirm]);

  return { tagConfig, updateTagColor, toggleTagImportant, renameTag };
}
