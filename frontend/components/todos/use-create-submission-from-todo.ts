"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useTranslations } from "next-intl";

import { ApiError, browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import type { TodoListItem } from "@/types/api";

/** Antwort von POST /api/protocol-todos/{id}/create-submission (backend TodoSubmissionCreated). */
export type TodoSubmissionCreated = {
  assignment_id: string;
  title: string;
  public_slug: string;
  element_url: string | null;
  todo: TodoListItem;
};

/** Pendenz, aus der sich eine Abgabe einsammeln lässt (Knopf/Menüeintrag nur dann zeigen). */
export function canCollectAsSubmission(todo: { submission_assignment_id?: string | null; todo_status_code?: string | null; pending_delete?: boolean; task_package_id?: string | null }): boolean {
  return !todo.submission_assignment_id && !todo.pending_delete && !todo.task_package_id && todo.todo_status_code !== "done" && todo.todo_status_code !== "cancelled";
}

/**
 * «Als Abgabe einsammeln»: legt mit einem Klick eine Einzelabgabe aus der Pendenz an (die Pendenz
 * wird die Pendenz des Abgabe-Elements) und meldet das mit «Link kopieren» und «Anpassen».
 * Liefert die Antwort oder null (Fehler schon als Toast gemeldet).
 */
export function useCreateSubmissionFromTodo() {
  const t = useTranslations("todos.toSubmission");
  const showToast = useToast();
  const router = useRouter();

  return useCallback(async (todoId: string): Promise<TodoSubmissionCreated | null> => {
    try {
      const result = await browserApiFetch<TodoSubmissionCreated>(`/api/protocol-todos/${todoId}/create-submission`, { method: "POST" });
      const elementUrl = result.element_url;
      showToast(t("created", { title: result.title }), "success", {
        actions: [
          ...(elementUrl ? [{
            label: t("copyLink"),
            onClick: () => {
              navigator.clipboard.writeText(elementUrl).then(
                () => showToast(t("linkCopied"), "success"),
                () => showToast(t("copyFailed"), "error"),
              );
            },
          }] : []),
          {
            label: t("customize"),
            onClick: () => router.push(`/submission-assignments?assignment=${encodeURIComponent(result.assignment_id)}&edit=1` as Route),
          },
        ],
      });
      return result;
    } catch (error) {
      const code = error instanceof ApiError ? (error.detail as { code?: unknown } | undefined)?.code : undefined;
      const message = typeof code === "string" && /^[a-z_]+$/.test(code) && t.has(`errors.${code}`)
        ? t(`errors.${code}`)
        : error instanceof Error && error.message ? error.message : t("failed");
      showToast(message, "error");
      return null;
    }
  }, [router, showToast, t]);
}
