"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { browserApiFetch } from "@/lib/api/client";

// Gemeinsame Logik der Admin-Tabellen mit Server-Pagination (Admin-Redesign Plan §5.1):
// limit/offset/sort/dir und Filter, Sync in die URL (router.replace, scroll:false), Debounce der
// Freitextsuche, AbortController für überholte Anfragen.
//
// Datenschutz: In die URL kommen nur IDs und Codes. Das Freitextfeld wird nur synchronisiert, wenn
// die Tabelle ausdrücklich `syncTextToUrl` setzt (z. B. Mandantenname) - bei Tabellen mit
// Personendaten (Benutzer, Zustellung) bleibt es nur im Zustand der Seite.

export type ServerTableFilters = Record<string, string>;
export type SortDir = "asc" | "desc";

export type ServerTableConfig<F extends ServerTableFilters> = {
  /** API-Pfad ohne Query, z. B. "/api/admin/audit-log". */
  path: string;
  pageSize: number;
  /** Standardwerte aller Filter ("" = nicht gesetzt). */
  defaults: F;
  /** Filter, die in der URL stehen dürfen (nur IDs/Codes). Standard: alle ausser dem Textfeld. */
  urlKeys?: Array<keyof F & string>;
  /** Freitextfeld (wird verzögert geladen). */
  textKey?: keyof F & string;
  /** Freitext in die URL schreiben - nur ohne Personendaten. */
  syncTextToUrl?: boolean;
  /** Erlaubte Sortierschlüssel; der erste ist der Standard. */
  sortKeys?: string[];
  defaultDir?: SortDir;
  /** Filterwerte prüfen, bevor sie aus der URL übernommen werden (unbekannt = Standard). */
  validate?: Partial<Record<keyof F & string, (value: string) => boolean>>;
  /** Name eines Filters in der API, falls er anders heisst als in der URL. */
  apiNames?: Partial<Record<keyof F & string, string>>;
  debounceMs?: number;
};

export type ServerTableState<F extends ServerTableFilters> = {
  filters: F;
  offset: number;
  sort: string | null;
  dir: SortDir;
};

const DEFAULT_DEBOUNCE_MS = 300;

function urlKeysOf<F extends ServerTableFilters>(config: ServerTableConfig<F>): string[] {
  const keys = config.urlKeys ?? (Object.keys(config.defaults) as string[]);
  return keys.filter((key) => key !== config.textKey || config.syncTextToUrl);
}

/** Zustand aus URL-Parametern; Unbekanntes fällt auf den Standard zurück (nie ungeprüft ans Backend). */
export function serverTableStateFromParams<F extends ServerTableFilters>(
  params: URLSearchParams,
  config: ServerTableConfig<F>,
): ServerTableState<F> {
  const filters = { ...config.defaults };
  for (const key of urlKeysOf(config)) {
    const raw = params.get(key);
    if (raw === null) continue;
    const value = raw.slice(0, 200);
    const check = config.validate?.[key as keyof F & string];
    if (!check || check(value)) (filters as Record<string, string>)[key] = value;
  }
  const offset = Math.max(0, Number.parseInt(params.get("offset") ?? "0", 10) || 0);
  const sortParam = params.get("sort");
  const sort = config.sortKeys?.length ? (sortParam && config.sortKeys.includes(sortParam) ? sortParam : config.sortKeys[0]) : null;
  const dirParam = params.get("dir");
  const dir: SortDir = dirParam === "asc" || dirParam === "desc" ? dirParam : config.defaultDir ?? "asc";
  return { filters, offset, sort, dir };
}

/** Query der Browser-URL: nur erlaubte Schlüssel und nur Abweichungen vom Standard. */
export function serverTableUrlQuery<F extends ServerTableFilters>(state: ServerTableState<F>, config: ServerTableConfig<F>): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of urlKeysOf(config)) {
    const value = state.filters[key];
    if (value && value !== config.defaults[key]) params.set(key, value);
  }
  if (config.sortKeys?.length && state.sort && state.sort !== config.sortKeys[0]) params.set("sort", state.sort);
  if (config.sortKeys?.length && state.dir !== (config.defaultDir ?? "asc")) params.set("dir", state.dir);
  if (state.offset > 0) params.set("offset", String(state.offset));
  return params;
}

/** Query der API-Anfrage: alle gesetzten Filter (auch das Textfeld) plus limit/offset/sort. */
export function serverTableApiQuery<F extends ServerTableFilters>(state: ServerTableState<F>, config: ServerTableConfig<F>): URLSearchParams {
  const params = new URLSearchParams({ limit: String(config.pageSize), offset: String(state.offset) });
  for (const [key, value] of Object.entries(state.filters)) {
    const trimmed = value.trim();
    if (trimmed) params.set(config.apiNames?.[key as keyof F & string] ?? key, trimmed);
  }
  if (state.sort) {
    params.set("sort", state.sort);
    params.set("dir", state.dir);
  }
  return params;
}

export type ServerTable<F extends ServerTableFilters, T> = ServerTableState<F> & {
  data: T | null;
  loading: boolean;
  failed: boolean;
  forbidden: boolean;
  setFilter: (key: keyof F & string, value: string) => void;
  setFilters: (next: Partial<F>) => void;
  setOffset: (offset: number) => void;
  toggleSort: (key: string) => void;
  reload: () => void;
};

export function useServerTable<F extends ServerTableFilters, T>(config: ServerTableConfig<F>, initialData: T | null = null): ServerTable<F, T> {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const configRef = useRef(config);
  configRef.current = config;
  const [state, setState] = useState<ServerTableState<F>>(() => serverTableStateFromParams(new URLSearchParams(searchParams?.toString() ?? ""), config));
  const [data, setData] = useState<T | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [tick, setTick] = useState(0);

  const apiQuery = serverTableApiQuery(state, config).toString();
  const textValue = config.textKey ? state.filters[config.textKey] : "";
  // Nur die Texteingabe wird verzögert; Filter, Seite und Sortierung laden sofort.
  const lastText = useRef(textValue);

  useEffect(() => {
    const currentConfig = configRef.current;
    const urlQuery = serverTableUrlQuery(state, currentConfig).toString();
    // Nur ersetzen, wenn sich die Adresse ändert und die Seite noch angezeigt wird: ein verspätetes
    // replace (Debounce) überschriebe sonst einen Klick auf einen Link (Muster Mandantenliste).
    if (typeof window !== "undefined" && window.location.pathname === pathname && window.location.search.replace(/^\?/, "") !== urlQuery) {
      router.replace((urlQuery ? `${pathname}?${urlQuery}` : pathname) as Route, { scroll: false });
    }
    const controller = new AbortController();
    const textChanged = lastText.current !== textValue;
    lastText.current = textValue;
    const timer = window.setTimeout(() => {
      setLoading(true);
      browserApiFetch<T>(`${currentConfig.path}?${apiQuery}`, { signal: controller.signal })
        .then((result) => {
          setData(result);
          setFailed(false);
          setForbidden(false);
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          const status = (error as { status?: number } | null)?.status;
          if (status === 403) setForbidden(true);
          else setFailed(true);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, textChanged ? currentConfig.debounceMs ?? DEFAULT_DEBOUNCE_MS : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // state steckt vollständig in apiQuery (+ URL-Query); pathname/router sind stabil genug
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiQuery, tick]);

  const setFilters = useCallback((next: Partial<F>) => {
    setState((current) => ({ ...current, offset: 0, filters: { ...current.filters, ...next } as F }));
  }, []);
  const setFilter = useCallback((key: keyof F & string, value: string) => setFilters({ [key]: value } as Partial<F>), [setFilters]);
  const setOffset = useCallback((offset: number) => setState((current) => ({ ...current, offset: Math.max(0, offset) })), []);
  const toggleSort = useCallback((key: string) => {
    setState((current) => ({
      ...current,
      offset: 0,
      sort: key,
      dir: current.sort === key ? (current.dir === "asc" ? "desc" : "asc") : configRef.current.defaultDir ?? "asc",
    }));
  }, []);
  const reload = useCallback(() => setTick((value) => value + 1), []);

  return useMemo(
    () => ({ ...state, data, loading, failed, forbidden, setFilter, setFilters, setOffset, toggleSort, reload }),
    [state, data, loading, failed, forbidden, setFilter, setFilters, setOffset, toggleSort, reload],
  );
}
