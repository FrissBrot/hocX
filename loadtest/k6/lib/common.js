// Gemeinsame Hilfen für alle hocX-k6-Szenarien. Nur gegen einen ausdrücklich freigegebenen,
// isolierten Lasttest-Stack verwenden (siehe loadtest/README.md, Sicherheitsregeln).
import http from "k6/http";
import { check, fail } from "k6";
import { Trend, Counter } from "k6/metrics";

export const BASE_URL = (__ENV.BASE_URL || "http://localhost:18000").replace(/\/$/, "");
export const ABGABEBOX_URL = (__ENV.ABGABEBOX_URL || "http://localhost:18001").replace(/\/$/, "");
// Ohne ausdrückliche Bestätigung startet kein Szenario - verhindert versehentliche Läufe gegen
// Produktion oder die Dev-Instanz.
if (__ENV.HOCX_LOADTEST_TARGET_CONFIRMED !== "isolated") {
  fail("HOCX_LOADTEST_TARGET_CONFIRMED=isolated fehlt - Ziel muss ein freigegebener Wegwerf-Stack sein.");
}
const forbidden = (__ENV.FORBIDDEN_HOSTS || "").split(",").map((h) => h.trim()).filter(Boolean);
for (const host of forbidden) {
  if (BASE_URL.includes(host) || ABGABEBOX_URL.includes(host)) fail(`Ziel ${host} ist ausdrücklich gesperrt.`);
}

const seed = JSON.parse(open(__ENV.TOKENS_FILE || "../tokens.json"));
export const COOKIE_NAME = seed.cookie_name || "hocx_session";
export const TENANTS = seed.tenants;
export const SESSIONS = TENANTS.flatMap((tenant, tenantIndex) =>
  tenant.sessions.map((token) => ({ token, tenantIndex, tenant: tenant.tenant })),
);

// Messgrössen getrennt nach Aktionsklasse: interaktiv vs. schwer, damit Interferenz sichtbar wird.
export const interactiveLatency = new Trend("hocx_interactive_ms", true);
export const heavyLatency = new Trend("hocx_heavy_ms", true);
export const conflicts = new Counter("hocx_conflicts_409");
export const busy = new Counter("hocx_busy_503_429");

// Feste Zuordnung VU -> Session (Mandanten gleichmässig verteilt); TENANT_FILTER=a,b begrenzt
// auf bestimmte Mandanten (für "Mandant A schwer, Mandant B interaktiv").
export function sessionForVu(vu, filter = __ENV.TENANT_FILTER) {
  const allowed = filter ? new Set(filter.split(",").map((v) => parseInt(v, 10))) : null;
  const pool = allowed ? SESSIONS.filter((s) => allowed.has(s.tenantIndex)) : SESSIONS;
  if (pool.length === 0) fail("Keine Session für TENANT_FILTER");
  return pool[(vu - 1) % pool.length];
}

export function params(session, tags = {}, extra = {}) {
  const result = {
    headers: { Cookie: `${COOKIE_NAME}=${session.token}`, Origin: BASE_URL, ...(extra.headers || {}) },
    tags: { tenant: String(session.tenantIndex), ...tags },
    timeout: extra.timeout || "120s",
  };
  // k6 lehnt responseType: undefined ab ("does not belong to ResponseType values")
  if (extra.responseType) result.responseType = extra.responseType;
  return result;
}

export function record(res, trend, name) {
  trend.add(res.timings.duration, { name });
  if (res.status === 409) conflicts.add(1, { name });
  if (res.status === 503 || res.status === 429) busy.add(1, { name });
  check(res, { [`${name} ok`]: (r) => r.status >= 200 && r.status < 400 });
  return res;
}

export function getJson(session, path, name, trend = interactiveLatency) {
  const res = record(http.get(`${BASE_URL}${path}`, params(session, { name })), trend, name);
  try {
    return res.status === 200 ? res.json() : null;
  } catch (_e) {
    return null;
  }
}

// Protokolle, Text- und Anwesenheitsblöcke eines Mandanten einmal je VU ermitteln.
const discovered = {};
export function discover(session) {
  if (discovered[session.tenantIndex]) return discovered[session.tenantIndex];
  const protocols = getJson(session, "/api/protocols?limit=50", "discover_protocols") || [];
  const items = Array.isArray(protocols) ? protocols : protocols.items || [];
  const result = { protocols: [], textBlocks: [], attendanceBlocks: [], participants: [] };
  for (const protocol of items.slice(0, 5)) {
    result.protocols.push(protocol.id);
    const elements = getJson(session, `/api/protocols/${protocol.id}/elements`, "discover_elements") || [];
    for (const element of elements) {
      for (const block of element.blocks || []) {
        if (block.element_type_id === 1) result.textBlocks.push({ protocol: protocol.id, block: block.id });
        if (block.element_type_id === 9) result.attendanceBlocks.push({ protocol: protocol.id, block: block.id });
      }
    }
  }
  const participants = getJson(session, "/api/participants", "discover_participants") || [];
  result.participants = (Array.isArray(participants) ? participants : participants.items || []).map((p) => p.id);
  discovered[session.tenantIndex] = result;
  return result;
}

export function pick(list) {
  return list.length ? list[Math.floor(Math.random() * list.length)] : null;
}

// Lastprofile: PROFILE=u10|u50|u100|u250|u500|u1000|burst|soak (Rampen sind bewusst lang genug,
// damit Pool-/Thread-Sättigung nicht nur als Startspitze erscheint).
export function stagesFor(profile) {
  const ramp = (target, hold = "5m") => [
    { duration: "2m", target },
    { duration: hold, target },
    { duration: "1m", target: 0 },
  ];
  switch (profile) {
    case "smoke": return [{ duration: "10s", target: 5 }, { duration: "50s", target: 5 }];
    case "u10": return ramp(10);
    case "u50": return ramp(50);
    case "u100": return ramp(100);
    case "u250": return ramp(250);
    case "u500": return ramp(500);
    case "u1000": return ramp(1000);
    case "burst": return [
      { duration: "1m", target: 20 },
      { duration: "10s", target: 500 },
      { duration: "1m", target: 500 },
      { duration: "10s", target: 20 },
      { duration: "3m", target: 20 },
      { duration: "30s", target: 0 },
    ];
    case "soak": return [
      { duration: "5m", target: 80 },
      { duration: __ENV.SOAK_DURATION || "4h", target: 80 },
      { duration: "2m", target: 0 },
    ];
    default: fail(`Unbekanntes PROFILE ${profile}`);
  }
}

export const DEFAULT_THRESHOLDS = {
  // Erfolgskriterien (siehe README): Startwerte, nach der ersten Baseline-Messung anpassen.
  "hocx_interactive_ms": ["p(95)<800", "p(99)<2000"],
  "http_req_failed{class:interactive}": ["rate<0.01"],
};
