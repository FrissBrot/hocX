#!/usr/bin/env python3
"""Lasttest-Läufe zusammenfassen: k6-Summary (summary.json) und Monitor-CSVs je Lauf.

Usage: python3 loadtest/stack/summarize.py /docker/loadtest-stack/results u10 u50 ...
Ausgabe: Markdown-Tabellen (Latenzen/Fehler, Spitzenwerte der Container, DB-Verbindungen).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def _metric(summary: dict, name: str, key: str):
    values = summary.get("metrics", {}).get(name, {})
    return values.get(key, values.get("values", {}).get(key))


def _mem_mib(text: str) -> float:
    match = re.match(r"([\d.]+)\s*([KMG]i?B)", text.strip())
    if not match:
        return 0.0
    value, unit = float(match.group(1)), match.group(2)
    return value * {"KiB": 1 / 1024, "KB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}[unit]


def main() -> None:
    root = Path(sys.argv[1])
    runs = sys.argv[2:]
    print("| Lauf | Requests | req/s | interaktiv p50 / p95 / p99 (ms) | Fehler interaktiv | Loop-Sonde p99 | Threadpool-Sonde p99 | 503/429 |")
    print("|---|---|---|---|---|---|---|---|")
    for run in runs:
        path = root / run / "summary.json"
        if not path.exists():
            print(f"| {run} | – fehlt – |||||||")
            continue
        summary = json.loads(path.read_text())
        reqs = _metric(summary, "http_reqs", "count") or 0
        rate = _metric(summary, "http_reqs", "rate") or 0
        p = lambda name, key: _metric(summary, name, key) or 0  # noqa: E731
        failed = summary.get("metrics", {}).get("http_req_failed{class:interactive}", {})
        fail_rate = failed.get("value", failed.get("values", {}).get("rate", 0)) if failed else _metric(summary, "http_req_failed", "value")
        busy = _metric(summary, "hocx_busy_503_429", "count") or 0
        print(
            f"| {run} | {int(reqs)} | {rate:.1f} | {p('hocx_interactive_ms', 'med'):.0f} / {p('hocx_interactive_ms', 'p(95)'):.0f} / "
            f"{p('hocx_interactive_ms', 'p(99)'):.0f} | {100 * (fail_rate or 0):.2f} % | {p('hocx_loop_probe_ms', 'p(99)'):.0f} ms | "
            f"{p('hocx_threadpool_probe_ms', 'p(99)'):.0f} ms | {int(busy)} |"
        )
    print()
    print("| Lauf | Container | CPU max % | RAM max (MiB) |")
    print("|---|---|---|---|")
    for run in runs:
        stats = root / run / "monitor" / "docker_stats.csv"
        if not stats.exists():
            continue
        peak_cpu: dict[str, float] = defaultdict(float)
        peak_mem: dict[str, float] = defaultdict(float)
        with stats.open() as handle:
            for row in csv.DictReader(handle):
                name = row["container"].removeprefix("hocx-loadtest-").removesuffix("-1")
                peak_cpu[name] = max(peak_cpu[name], float(row["cpu_pct"].rstrip("%") or 0))
                peak_mem[name] = max(peak_mem[name], _mem_mib(row["mem_usage"].split("/")[0]))
        for name in sorted(peak_cpu, key=lambda key: -peak_cpu[key])[:5]:
            print(f"| {run} | {name} | {peak_cpu[name]:.0f} | {peak_mem[name]:.0f} |")
    print()
    print("| Lauf | DB-Verbindungen max | davon idle in transaction max | längste Transaktion (s) | Lock-Wartende max |")
    print("|---|---|---|---|---|")
    for run in runs:
        activity = root / run / "monitor" / "pg_activity.csv"
        waits = root / run / "monitor" / "pg_lock_waits.csv"
        if not activity.exists():
            continue
        per_ts: dict[str, int] = defaultdict(int)
        idle_tx: dict[str, int] = defaultdict(int)
        oldest = 0
        with activity.open() as handle:
            for row in csv.reader(handle):
                if row[0] == "ts" or len(row) < 5:
                    continue
                ts, _user, state, count, xact = row[:5]
                per_ts[ts] += int(count)
                if state == "idle in transaction":
                    idle_tx[ts] += int(count)
                if state != "idle":
                    oldest = max(oldest, int(xact or 0))
        max_waits = 0
        if waits.exists():
            with waits.open() as handle:
                for row in csv.reader(handle):
                    if row[0] != "ts" and len(row) >= 2:
                        max_waits = max(max_waits, int(row[1] or 0))
        print(f"| {run} | {max(per_ts.values(), default=0)} | {max(idle_tx.values(), default=0)} | {oldest} | {max_waits} |")


if __name__ == "__main__":
    main()
