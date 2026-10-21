// Szenario D - Upload-Sturm auf die öffentliche Abgabebox (z. B. kurz vor einer Abgabefrist),
// gleichzeitig Galerie-Uploads in der App. Zählt 503 "Upload-Kapazität belegt" (UploadAdmission-
// Middleware: 1 aktiver POST /api/public/* je abgabebox-Worker), Scan-Fehler (ClamAV MaxThreads 2,
// MaxQueue 16) und Gesamtdauer pro erfolgreichem Upload.
// Voraussetzung: Captcha im Lasttest-Stack NICHT konfiguriert (dev/test überspringt es).
// Aufruf: k6 run -e STORM_VUS=50 -e HOCX_LOADTEST_TARGET_CONFIRMED=isolated abgabebox_storm.js
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";
import { FormData } from "https://jslib.k6.io/formdata/0.0.2/index.js"; // mehrere Felder "files"
import { ABGABEBOX_URL, TENANTS } from "./lib/common.js";

const capacity503 = new Counter("hocx_abgabebox_capacity_503");
const scanFailed = new Counter("hocx_abgabebox_scan_rejected");
const uploadMs = new Trend("hocx_abgabebox_upload_ms", true);
const image = open(__ENV.FIXTURE_IMAGE || "../fixtures/photo-8mb.jpg", "b");
const FILES = parseInt(__ENV.FILES_PER_UPLOAD || "5", 10);

// JPEG mit angehängter Markierung hinter dem EOI: Magic Bytes und Dekodierbarkeit bleiben, die
// Prüfsumme ist je Datei eindeutig (sonst bestätigt die Abgabebox Duplikate ohne Scan).
function uniqueImage(marker) {
  const source = new Uint8Array(image);
  const out = new Uint8Array(source.length + marker.length);
  out.set(source);
  for (let i = 0; i < marker.length; i += 1) out[source.length + i] = marker.charCodeAt(i) & 0xff;
  return out.buffer;
}

export const options = {
  scenarios: {
    storm: { executor: "per-vu-iterations", vus: parseInt(__ENV.STORM_VUS || "50", 10), iterations: parseInt(__ENV.STORM_ITERATIONS || "3", 10), maxDuration: "30m" },
  },
  thresholds: { hocx_abgabebox_capacity_503: ["count==0"] },
};

export function setup() {
  const targets = [];
  for (const tenant of TENANTS) {
    const { link_token: link, assignment_slug: slug } = tenant.abgabebox || {};
    if (!link || !slug) continue;
    const res = http.get(`${ABGABEBOX_URL}/api/public/${link}/assignments/${slug}/elements`);
    const elements = res.status === 200 ? res.json() : [];
    for (const element of elements) {
      const ref = element.element_ref;
      if (ref) targets.push({ link, slug, ref: String(ref) });
    }
  }
  if (!targets.length) throw new Error("Keine offenen Abgabe-Elemente gefunden");
  return { targets };
}

export default function (data) {
  const target = data.targets[(__VU - 1) % data.targets.length];
  const base = `${ABGABEBOX_URL}/api/public/${target.link}/assignments/${target.slug}/elements/${encodeURIComponent(target.ref)}`;
  const captcha = http.post(`${base}/captcha-verify`, { captcha_solution: "loadtest" }, { tags: { name: "captcha_verify" } });
  if (captcha.status === 503) capacity503.add(1, { step: "captcha" });
  if (captcha.status !== 200) return;
  const form = new FormData();
  form.append("captcha_session_token", captcha.json().session_token);
  form.append("include_gps", "true");
  // Eindeutige Bytes je Datei, sonst greift die Duplikaterkennung vor dem Scan.
  for (let i = 0; i < FILES; i += 1) {
    const marker = `${__VU}-${__ITER}-${i}-${Date.now()}`;
    form.append("files", http.file(uniqueImage(marker), `storm-${marker}.jpg`, "image/jpeg"));
  }
  const started = Date.now();
  const res = http.post(`${base}/upload`, form.body(), {
    headers: { "Content-Type": `multipart/form-data; boundary=${form.boundary}` }, timeout: "900s", tags: { name: "abgabebox_upload" },
  });
  uploadMs.add(Date.now() - started);
  if (res.status === 503) capacity503.add(1, { step: "upload" });
  if (res.status === 400 && String(res.body).includes("Virenprüfung")) scanFailed.add(1);
  check(res, { "upload 2xx": (r) => r.status >= 200 && r.status < 300 });
  sleep(1);
}
