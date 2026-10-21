// Szenario B - 20-50 Personen bearbeiten gleichzeitig DASSELBE Protokoll.
// Jede VU: WebSocket öffnen, Präsenz/Locks empfangen, Felder sperren, field_update senden,
// parallel per REST speichern. Misst Broadcast-Verzögerung (Zeitstempel im Patch),
// abgelehnte Updates, Verbindungsabbrüche und 409-Konflikte.
// Aufruf: k6 run -e COLLAB_USERS=50 -e TENANT_FILTER=0 -e HOCX_LOADTEST_TARGET_CONFIRMED=isolated collab.js
import ws from "k6/ws";
import http from "k6/http";
import { check } from "k6";
import { Counter, Trend } from "k6/metrics";
import { BASE_URL, COOKIE_NAME, discover, interactiveLatency, params, pick, record, sessionForVu } from "./lib/common.js";

const broadcastDelay = new Trend("hocx_ws_broadcast_ms", true);
const wsRejected = new Counter("hocx_ws_update_rejected");
const wsDropped = new Counter("hocx_ws_unexpected_close");
const wsSnapshot = new Trend("hocx_ws_snapshot_ms", true);
const USERS = parseInt(__ENV.COLLAB_USERS || "30", 10);

export const options = {
  scenarios: {
    editors: { executor: "per-vu-iterations", vus: USERS, iterations: 1, maxDuration: __ENV.COLLAB_DURATION || "15m", exec: "editor" },
  },
  thresholds: { hocx_ws_broadcast_ms: ["p(95)<500"], hocx_ws_unexpected_close: ["count==0"] },
};

export function editor() {
  const session = sessionForVu(__VU, __ENV.TENANT_FILTER || "0");
  const data = discover(session);
  const protocol = data.protocols[0];
  const wsBase = BASE_URL.replace(/^http/, "ws");
  const opened = Date.now();
  const holdSeconds = parseInt(__ENV.COLLAB_SECONDS || "600", 10);
  const res = ws.connect(`${wsBase}/api/ws/protocols/${protocol}`, {
    headers: { Cookie: `${COOKIE_NAME}=${session.token}`, Origin: BASE_URL },
  }, (socket) => {
    let heldField = null;
    socket.on("message", (raw) => {
      const msg = JSON.parse(raw);
      if (msg.type === "snapshot") wsSnapshot.add(Date.now() - opened);
      if (msg.type === "field_update" && msg.patch && msg.patch.sent_at) broadcastDelay.add(Date.now() - msg.patch.sent_at);
      if (msg.type === "field_update_rejected") wsRejected.add(1);
      if (msg.type === "lock_acquired" && msg.field_key === heldField) {
        socket.send(JSON.stringify({ type: "field_update", field_key: heldField, patch: { sent_at: Date.now(), vu: __VU } }));
      }
    });
    socket.on("close", () => {
      if ((Date.now() - opened) / 1000 < holdSeconds - 5) wsDropped.add(1);
    });
    socket.setInterval(() => {
      // Abwechselnd ein Feld sperren und per REST speichern (wie focused-element-editor.tsx)
      const target = pick(data.textBlocks.filter((t) => t.protocol === protocol));
      if (!target) return;
      heldField = `block-${target.block}`;
      socket.send(JSON.stringify({ type: "lock_request", field_key: heldField }));
      const body = JSON.stringify({ content: `<p>collab ${__VU} ${Date.now()}</p>` });
      record(http.put(`${BASE_URL}/api/protocol-element-blocks/${target.block}/text`, body,
        params(session, { name: "collab_text_save" }, { headers: { "Content-Type": "application/json" } })), interactiveLatency, "collab_text_save");
      socket.send(JSON.stringify({ type: "unlock", field_key: heldField }));
    }, 2000 + Math.random() * 2000);
    socket.setInterval(() => {
      if (heldField) socket.send(JSON.stringify({ type: "heartbeat", field_key: heldField }));
    }, 20000);
    socket.setTimeout(() => socket.close(), holdSeconds * 1000);
  });
  check(res, { "ws upgrade 101": (r) => r && r.status === 101 });
}
