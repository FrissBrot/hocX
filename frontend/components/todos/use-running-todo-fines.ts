"use client";

import { useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import type { TodoFineListItem } from "@/types/api";

/** IDs der Pendenzen, für die gerade eine Busse läuft (Badge «Busse läuft» in den Listen).
 *  Nutzt GET /api/todo-fines - ohne reports.personal liefert das Backend nur die eigenen
 *  Bussen. Fehler sind hier nicht kritisch (der Badge ist nur ein Hinweis) und bleiben still. */
export function runningFineTodoIds(items: TodoFineListItem[]): Set<string> {
  return new Set(items.filter((item) => item.status === "running" && item.todo_id).map((item) => item.todo_id as string));
}

export function useRunningTodoFines(enabled: boolean): Set<string> {
  const [ids, setIds] = useState<Set<string>>(() => new Set());
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    browserApiFetch<TodoFineListItem[]>("/api/todo-fines")
      .then((items) => {
        if (!cancelled) setIds(runningFineTodoIds(items ?? []));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return ids;
}
