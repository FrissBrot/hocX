"""Eindeutige Punktnamen ausschliesslich aus passenden lokalen Geo-Namen."""
from itertools import combinations


def unique_environment_name(names, reserved_names=()):
    used = {name.strip().casefold() for name in reserved_names if name and name.strip()}
    candidates, seen = [], set()
    for name in names:
        if not name or not name.strip():
            continue
        name = name.strip()
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            candidates.append(name)
        if key not in used:
            return name
    # Erst andere Geo-Namen ausschöpfen, dann die nächsten Namen kombinieren.
    # Die Auswahl bleibt deterministisch; keine Nummern oder Typzusätze erfinden.
    for count in range(2, len(candidates) + 1):
        for parts in combinations(candidates, count):
            name = ' / '.join(parts)
            if name.casefold() not in used:
                return name
    return None
