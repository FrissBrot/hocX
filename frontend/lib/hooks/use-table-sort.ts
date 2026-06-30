import { useMemo, useState } from "react";

export function useTableSort<T extends string>(defaultKey: T, defaultDirection: "asc" | "desc" = "asc") {
  const [sortKey, setSortKey] = useState<T>(defaultKey);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">(defaultDirection);

  function toggleSort(key: T) {
    setSortKey((current) => {
      if (current === key) {
        setSortDirection((dir) => (dir === "asc" ? "desc" : "asc"));
        return current;
      }
      setSortDirection("asc");
      return key;
    });
  }

  function sortIndicator(key: T): "asc" | "desc" | null {
    return sortKey === key ? sortDirection : null;
  }

  return { sortKey, sortDirection, toggleSort, sortIndicator };
}

export function sortByKey<T>(
  items: T[],
  key: keyof T,
  direction: "asc" | "desc",
  compareFn?: (a: T, b: T, direction: number) => number
): T[] {
  const dir = direction === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    if (compareFn) return compareFn(a, b, dir);
    const av = String(a[key] ?? "").toLowerCase();
    const bv = String(b[key] ?? "").toLowerCase();
    return av.localeCompare(bv) * dir;
  });
}
