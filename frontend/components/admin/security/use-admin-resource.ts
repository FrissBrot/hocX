"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, browserApiFetch } from "@/lib/api/client";

export type ResourceState<T> = { data: T | null; loading: boolean; forbidden: boolean; failed: boolean; reload: () => void };

/** Lädt einen Admin-Endpunkt im Browser; 403 (z. B. support-Rolle bei owner-Ansichten) wird als
 * `forbidden` gemeldet statt als Fehler. */
export function useAdminResource<T>(path: string): ResourceState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    browserApiFetch<T>(path, { signal: controller.signal })
      .then((result) => {
        setData(result);
        setForbidden(false);
        setFailed(false);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 403) setForbidden(true);
        else setFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, loading, forbidden, failed, reload };
}
