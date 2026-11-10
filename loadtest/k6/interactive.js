// Szenario A - viele normale Benutzer aus mehreren Mandanten: lesen, navigieren, speichern.
// Zusätzlich zwei Sonden, die Engpässe getrennt sichtbar machen:
//   loop_probe  - OPTIONS-Preflight, beantwortet CORSMiddleware direkt im Event-Loop (kein
//                 Threadpool, keine DB) -> misst Event-Loop-Lag des Workers.
//   pool_probe  - GET /api/health ist eine sync-Route -> misst Threadpool-Wartezeit ohne DB.
// Aufruf: k6 run -e PROFILE=u100 -e HOCX_LOADTEST_TARGET_CONFIRMED=isolated -e TOKENS_FILE=../tokens.json interactive.js
import http from "k6/http";
import { sleep } from "k6";
import { Trend } from "k6/metrics";
import {
  BASE_URL, DEFAULT_THRESHOLDS, discover, getJson, interactiveLatency, params, pick, record, sessionForVu, stagesFor,
} from "./lib/common.js";

const loopLag = new Trend("hocx_loop_probe_ms", true);
const threadpoolLag = new Trend("hocx_threadpool_probe_ms", true);
const THINK = parseFloat(__ENV.THINK_SECONDS || "3");

export const options = {
  scenarios: {
    users: { executor: "ramping-vus", stages: stagesFor(__ENV.PROFILE || "u10"), exec: "user", tags: { class: "interactive" } },
    probes: { executor: "constant-arrival-rate", rate: 2, timeUnit: "1s", duration: __ENV.PROBE_DURATION || "10m", preAllocatedVUs: 4, exec: "probe", tags: { class: "probe" } },
  },
  thresholds: { ...DEFAULT_THRESHOLDS, hocx_loop_probe_ms: ["p(99)<250"], hocx_threadpool_probe_ms: ["p(99)<500"] },
};

export function probe() {
  const preflight = http.options(`${BASE_URL}/api/health`, null, {
    headers: { Origin: BASE_URL, "Access-Control-Request-Method": "GET" }, tags: { name: "loop_probe" },
  });
  loopLag.add(preflight.timings.duration);
  const health = http.get(`${BASE_URL}/api/health`, { tags: { name: "pool_probe" } });
  threadpoolLag.add(health.timings.duration);
}

export function user() {
  const session = sessionForVu(__VU);
  const data = discover(session);
  const roll = Math.random();
  if (roll < 0.25) {
    getJson(session, "/api/protocols?limit=100", "protocol_list");
  } else if (roll < 0.45) {
    const protocol = pick(data.protocols);
    if (protocol) {
      getJson(session, `/api/protocols/${protocol}`, "protocol_detail");
      getJson(session, `/api/protocols/${protocol}/elements`, "protocol_elements");
    }
  } else if (roll < 0.55) {
    getJson(session, "/api/todos/my", "todos_my");
  } else if (roll < 0.62) {
    getJson(session, "/api/events", "events");
  } else if (roll < 0.70) {
    getJson(session, "/api/files?limit=50", "files_list");
  } else if (roll < 0.75) {
    // Diagramm-Polling (chart-block.tsx pollt alle 15 s) - Aggregation über Anwesenheitsblöcke
    getJson(session, "/api/statistics/overview", "statistics_overview");
  } else if (roll < 0.90) {
    // Autosave eines Textblocks (PUT .../text), ohne expected_content wie ältere Clients
    const target = pick(data.textBlocks);
    if (target) {
      const body = JSON.stringify({ content: `<p>Lasttest ${__VU}-${__ITER} ${Date.now()}</p>` });
      record(http.put(`${BASE_URL}/api/protocol-element-blocks/${target.block}/text`, body,
        params(session, { name: "text_autosave" }, { headers: { "Content-Type": "application/json" } })), interactiveLatency, "text_autosave");
    }
  } else {
    const target = pick(data.attendanceBlocks);
    const participant = pick(data.participants);
    if (target && participant) {
      const body = JSON.stringify({ status: pick(["present", "late", "excused", "absent"]) });
      record(http.post(`${BASE_URL}/api/protocol-element-blocks/${target.block}/attendance/${participant}`, body,
        params(session, { name: "attendance_set" }, { headers: { "Content-Type": "application/json" } })), interactiveLatency, "attendance_set");
    }
  }
  sleep(THINK * (0.5 + Math.random()));
}
