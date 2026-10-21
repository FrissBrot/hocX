// Szenario C - schwere Aufgaben während normaler Nutzung, getrennt nach Mandant:
//   Mandant(en) HEAVY_TENANTS lösen PDF-Exporte, Vorschauen, Galerie-Uploads (Bilder und ZIP),
//   Ähnlichkeitsgruppen und Vereinsexporte aus; Mandant(en) INTERACTIVE_TENANTS arbeiten normal.
// Kernmessung: hocx_interactive_ms{phase=heavy} gegen den Lauf von interactive.js ohne Last
// (Baseline) - steigt die Latenz eines Mandanten, wenn ein ANDERER Mandant schwer arbeitet?
// Aufruf: k6 run -e HEAVY_TENANTS=0 -e INTERACTIVE_TENANTS=1,2,3 -e INTERACTIVE_VUS=100 \
//         -e HOCX_LOADTEST_TARGET_CONFIRMED=isolated heavy.js
// Fixtures: loadtest/fixtures/ (siehe README, make_fixtures.py).
import http from "k6/http";
import { sleep } from "k6";
import {
  BASE_URL, TENANTS, discover, getJson, heavyLatency, interactiveLatency, params, pick, record, sessionForVu,
} from "./lib/common.js";

const HEAVY = __ENV.HEAVY_TENANTS || "0";
const INTERACTIVE = __ENV.INTERACTIVE_TENANTS || "1";
const DURATION = __ENV.HEAVY_DURATION || "15m";
const image = open(__ENV.FIXTURE_IMAGE || "../fixtures/photo-8mb.jpg", "b");
const zip = __ENV.FIXTURE_ZIP ? open(__ENV.FIXTURE_ZIP, "b") : null;

// Eindeutige Prüfsumme je Upload (Markierung hinter dem JPEG-EOI), sonst filtert die
// Duplikaterkennung alles vor Scan und Thumbnail heraus und die Last entsteht nie.
function uniqueImage(marker) {
  const source = new Uint8Array(image);
  const out = new Uint8Array(source.length + marker.length);
  out.set(source);
  for (let i = 0; i < marker.length; i += 1) out[source.length + i] = marker.charCodeAt(i) & 0xff;
  return out.buffer;
}

export const options = {
  scenarios: {
    interactive: {
      executor: "constant-vus", vus: parseInt(__ENV.INTERACTIVE_VUS || "50", 10), duration: DURATION,
      exec: "interactive", tags: { class: "interactive", phase: "heavy" },
    },
    pdf_exports: { executor: "constant-vus", vus: parseInt(__ENV.EXPORT_VUS || "4", 10), duration: DURATION, exec: "pdfExport", tags: { class: "heavy" } },
    previews: { executor: "constant-vus", vus: parseInt(__ENV.PREVIEW_VUS || "4", 10), duration: DURATION, exec: "preview", tags: { class: "heavy" } },
    uploads: { executor: "constant-vus", vus: parseInt(__ENV.UPLOAD_VUS || "3", 10), duration: DURATION, exec: "galleryUpload", tags: { class: "heavy" } },
    similarity: { executor: "constant-arrival-rate", rate: 1, timeUnit: "30s", duration: DURATION, preAllocatedVUs: 2, exec: "similarity", tags: { class: "heavy" } },
    tenant_export: { executor: "per-vu-iterations", vus: 1, iterations: 1, exec: "tenantExport", tags: { class: "heavy" } },
  },
  thresholds: { "hocx_interactive_ms{phase:heavy}": ["p(95)<1000"] },
};

export function interactive() {
  const session = sessionForVu(__VU, INTERACTIVE);
  const data = discover(session);
  const protocol = pick(data.protocols);
  getJson(session, "/api/protocols?limit=100", "protocol_list");
  if (protocol) getJson(session, `/api/protocols/${protocol}/elements`, "protocol_elements");
  const target = pick(data.textBlocks);
  if (target) {
    record(http.put(`${BASE_URL}/api/protocol-element-blocks/${target.block}/text`, JSON.stringify({ content: `<p>i ${Date.now()}</p>` }),
      params(session, { name: "text_autosave" }, { headers: { "Content-Type": "application/json" } })), interactiveLatency, "text_autosave");
  }
  sleep(2 + Math.random() * 2);
}

function documentBody(protocol) {
  return JSON.stringify({ protocol_id: protocol, document_type: "protocol" });
}

export function pdfExport() {
  const session = sessionForVu(__VU, HEAVY);
  const protocol = pick(discover(session).protocols);
  if (!protocol) return;
  record(http.post(`${BASE_URL}/api/documents/render`, documentBody(protocol),
    params(session, { name: "pdf_render" }, { headers: { "Content-Type": "application/json" }, timeout: "180s" })), heavyLatency, "pdf_render");
  sleep(1);
}

export function preview() {
  const session = sessionForVu(__VU, HEAVY);
  const protocol = pick(discover(session).protocols);
  if (!protocol) return;
  record(http.post(`${BASE_URL}/api/documents/preview?max_pages=4`, documentBody(protocol),
    params(session, { name: "pdf_preview" }, { headers: { "Content-Type": "application/json" }, timeout: "120s" })), heavyLatency, "pdf_preview");
  sleep(0.5);
}

export function galleryUpload() {
  const session = sessionForVu(__VU, HEAVY);
  const useZip = zip && Math.random() < 0.3;
  const form = useZip
    ? { files: http.file(zip, `lt-${__VU}-${__ITER}.zip`, "application/zip") }
    : { files: http.file(uniqueImage(`lt-${__VU}-${__ITER}-${Date.now()}`), `lt-${__VU}-${__ITER}.jpg`, "image/jpeg") };
  // Galerie: max. 1 aktiver Upload je uvicorn-Worker (UploadAdmissionMiddleware) -> 503 zählen.
  record(http.post(`${BASE_URL}/api/files/gallery-uploads`, form,
    params(session, { name: useZip ? "gallery_zip" : "gallery_image" }, { timeout: "600s" })), heavyLatency, useZip ? "gallery_zip" : "gallery_image");
  sleep(1);
}

export function similarity() {
  const session = sessionForVu(__VU, HEAVY);
  getJson(session, "/api/files/similarity-groups?kind=duplicate&min_size=2", "similarity_groups", heavyLatency);
}

export function tenantExport() {
  const index = parseInt(HEAVY.split(",")[0], 10);
  const admin = TENANTS[index].admin_session;
  if (!admin) return;
  const session = { token: admin, tenantIndex: index };
  record(http.post(`${BASE_URL}/api/tenant-data-exports`, JSON.stringify({ password: `lt-${Date.now()}-export`, include_files: true }),
    params(session, { name: "tenant_export_request" }, { headers: { "Content-Type": "application/json" } })), heavyLatency, "tenant_export_request");
}
