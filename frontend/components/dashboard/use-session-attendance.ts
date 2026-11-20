"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { NextSessionAttendanceEntry, NextSessionInfo } from "@/types/api";

export function useSessionAttendance(initialSessions: NextSessionInfo[], canExcuse: boolean) {
  const [sessions, setSessions] = useState(initialSessions);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const t = useTranslations("dashboard");
  const showToast = useToast();

  useEffect(() => setSessions(initialSessions), [initialSessions]);

  async function toggleExcused(session: NextSessionInfo, entry: NextSessionAttendanceEntry) {
    const protocol = session.protocol;
    const key = `${protocol?.id}:${entry.participant_id}`;
    if (!canExcuse || !protocol || busy[key]) return;
    const nextExcused = entry.status !== "excused";
    const setStatus = (status: string) => setSessions((current) => current.map((item) =>
      item.protocol?.id === protocol.id
        ? { ...item, entries: item.entries.map((person) => person.participant_id === entry.participant_id ? { ...person, status } : person) }
        : item
    ));
    setBusy((current) => ({ ...current, [key]: true }));
    setStatus(nextExcused ? "excused" : "absent");
    try {
      const result = await browserApiFetch<{ fines_kept?: number }>(`/api/protocols/${protocol.id}/attendance/${entry.participant_id}/excuse`, {
        method: "POST",
        body: JSON.stringify({ excused: nextExcused }),
      });
      // Ohne Bussenrecht bleiben offene Bussen stehen (die Kasse entscheidet) - das sagen statt still.
      const finesKept = Number(result?.fines_kept ?? 0);
      if (nextExcused && finesKept > 0) {
        showToast(t("excusedFinesKept", { name: entry.participant_name, count: finesKept }), "info");
      }
    } catch (error) {
      setStatus(entry.status);
      showToast(error instanceof Error ? error.message : t("statusChangeFailed"), "error");
    } finally {
      setBusy((current) => ({ ...current, [key]: false }));
    }
  }

  return { sessions, busy, toggleExcused };
}
