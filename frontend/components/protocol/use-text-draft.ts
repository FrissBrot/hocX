"use client";

import { useCallback, useSyncExternalStore } from "react";

import type { TextDraftStore } from "@/components/protocol/text-drafts";

/** Text eines Blocks aus dem Entwurfs-Store; rendert nur bei Änderungen dieses Blocks neu (T3). */
export function useTextDraft(store: TextDraftStore, blockId: string): string | undefined {
  const subscribe = useCallback((listener: () => void) => store.subscribe(blockId, listener), [store, blockId]);
  const read = useCallback(() => store.get(blockId), [store, blockId]);
  return useSyncExternalStore(subscribe, read, read);
}

/** Leer-Signatur aller Textblöcke (PDF-Abdeckung): ändert sich nur beim Wechsel leer/gefüllt. */
export function useTextDraftEmptiness(store: TextDraftStore): string {
  return useSyncExternalStore(store.subscribeEmptiness, store.getEmptinessKey, store.getEmptinessKey);
}
