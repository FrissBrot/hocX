// CONC-022: Liefert das Backend unter vielen parallelen direkten Verbindungen (SSR-Muster:
// INTERNAL_API_URL=http://backend:8000) je Session immer die eigene Antwort? frontend/proxy.ts
// behauptete "gelegentlich die falsche Antwort für eine gültige Session".
// Jeder Request: zufällige Session, GET /api/auth/session, Antwort muss zum Mandanten und Konto
// dieser Session passen (Mandanten-ID, E-Mail-Domain lt<NNN>, stabile E-Mail je Token).
// Aufruf: loadtest/stack/k6.sh session_consistency.js conc022 -e RATE=300 -e DURATION=5m
import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";
import { BASE_URL, COOKIE_NAME, SESSIONS, TENANTS } from "./lib/common.js";

const mismatches = new Counter("hocx_session_mismatch");
const firstSeen = {};

export const options = {
  discardResponseBodies: false,
  scenarios: {
    ssr: {
      executor: "constant-arrival-rate",
      rate: parseInt(__ENV.RATE || "200", 10),
      timeUnit: "1s",
      duration: __ENV.DURATION || "5m",
      preAllocatedVUs: 200,
      maxVUs: 600,
    },
  },
  thresholds: { hocx_session_mismatch: ["count==0"] },
};

export default function () {
  const session = SESSIONS[Math.floor(Math.random() * SESSIONS.length)];
  const tenant = TENANTS[session.tenantIndex];
  const res = http.get(`${BASE_URL}/api/auth/session`, {
    headers: { Cookie: `${COOKIE_NAME}=${session.token}` },
    tags: { name: "auth_session" },
  });
  if (res.status !== 200) {
    check(res, { "status 200": () => false });
    return;
  }
  let body;
  try {
    body = res.json();
  } catch (_e) {
    mismatches.add(1, { reason: "invalid_json" });
    return;
  }
  const email = body && body.user ? body.user.email : null;
  const domain = `@lt${String(session.tenantIndex + 1).padStart(3, "0")}.hocx.local`;
  const tenantOk = body && body.current_tenant && body.current_tenant.id === tenant.tenant_public_id;
  const emailOk = typeof email === "string" && email.endsWith(domain);
  const stableOk = firstSeen[session.token] === undefined || firstSeen[session.token] === email;
  if (firstSeen[session.token] === undefined) firstSeen[session.token] = email;
  const ok = body.authenticated === true && tenantOk && emailOk && stableOk;
  if (!ok) {
    mismatches.add(1, { reason: !tenantOk ? "tenant" : !emailOk ? "email" : "unstable" });
    console.error(`Fremde Antwort: Mandant ${tenant.tenant} erwartet, erhalten ${email} / ${body.current_tenant && body.current_tenant.name}`);
  }
  check(res, { "eigene Session": () => ok });
}
