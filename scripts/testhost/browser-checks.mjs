// Browser-Prüfungen für die Abnahme auf dem Test-Host (Skill testhost-abnahme). Läuft im
// Playwright-Container (abnahme.sh), schreibt je Prüfung eine Zeile nach $TH_OUT/results.jsonl
// und legt Screenshots in $TH_OUT/shots ab. Zugangsdaten kommen nur aus der Umgebung.
//
// Nur TH-25 schreibt (mit TH_WRITE=1): ein Wegwerf-Protokoll, das am Ende wieder gelöscht wird.
// Der Crawler (TH-20) klickt zwar Schaltflächen an, blockiert aber alle schreibenden Anfragen.
import { chromium, request as pwRequest } from "playwright";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const env = process.env;
const BASE = env.TH_BASE;
const ADMIN_BASE = env.TH_ADMIN_BASE || "";
const OUT = env.TH_OUT;
const REPO = env.TH_REPO;
const MAX_PAGES = Number(env.TH_MAX_PAGES || 70);
const MAX_CLICKS = Number(env.TH_MAX_CLICKS || 14);
const SHOTS = path.join(OUT, "shots");
// TH_ONLY="TH-24 TH-25": nur diese Prüfungen wiederholen (Präfix genügt)
const only = (env.TH_ONLY || "").split(/\s+/).filter(Boolean);
const wanted = (id) => !only.length || only.some((prefix) => id.startsWith(prefix));
fs.mkdirSync(SHOTS, { recursive: true });

const report = (id, status, summary, details) => {
  fs.appendFileSync(path.join(OUT, "results.jsonl"), `${JSON.stringify({ id, status, summary, details })}\n`);
  console.log(`[${status}] ${id}: ${summary}`);
};

// --- Anmeldung -------------------------------------------------------------------------------
const base32 = (secret) => {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.toUpperCase().replace(/=+$/, "")) bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
};
const totp = (secret) => {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const hash = crypto.createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = hash[19] & 15;
  return String((hash.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
};

// Meldet an und gibt die Cookies zurück. Richtet nie MFA ein: Fehlt der Faktor oder sein Secret,
// ist das Konto für diese Prüfung nicht nutzbar (Grund in .skip).
async function login(base, prefix, who) {
  const email = env[`TH_${who}_EMAIL`];
  const password = env[`TH_${who}_PASSWORD`];
  if (!email || !password) return { skip: `TH_${who}_EMAIL/PASSWORD fehlen` };
  const ctx = await pwRequest.newContext({ baseURL: base, ignoreHTTPSErrors: true, extraHTTPHeaders: { Origin: base } });
  const response = await ctx.post(`${prefix}/login`, { data: { email, password } });
  if (!response.ok()) return { skip: `Login ${who} schlug fehl: HTTP ${response.status()}` };
  const body = await response.json();
  if (body.mfa?.status === "setup_required") return { skip: `${who}: MFA nicht eingerichtet, das Skript richtet sie nicht ein` };
  if (body.mfa?.status === "verification_required") {
    const secret = env[`TH_${who}_TOTP`];
    if (!secret) return { skip: `${who}: braucht TOTP, TH_${who}_TOTP fehlt` };
    const verify = await ctx.post(`${prefix}/mfa/totp/verify`, { data: { ticket: body.mfa.ticket, code: totp(secret) } });
    if (!verify.ok()) return { skip: `${who}: TOTP abgelehnt (HTTP ${verify.status()}), evtl. gleiches 30-s-Fenster wie zuvor` };
  }
  const { cookies } = await ctx.storageState();
  await ctx.dispose();
  return { cookies };
}

const apiFor = (base, cookies) =>
  pwRequest.newContext({ baseURL: base, ignoreHTTPSErrors: true, extraHTTPHeaders: { Origin: base }, storageState: { cookies, origins: [] } });

// --- TH-20/21: Crawler ------------------------------------------------------------------------
// Klassen, die nur in Bereichs-CSS (frontend/app/styles) definiert sind. Trägt ein Element eine
// solche Klasse und enthält keines der geladenen Stylesheets eine Regel dafür, fehlt auf dieser
// Route ein Bundle: das Element ist ungestylt. Jede Seite wird hart geladen, damit CSS von zuvor
// besuchten Routen den Fehler nicht verdeckt.
const scopedClasses = new Set();
const stylesDir = path.join(REPO, "frontend/app/styles");
for (const file of fs.readdirSync(stylesDir).filter((name) => name.endsWith(".css"))) {
  const css = fs.readFileSync(path.join(stylesDir, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/url\([^)]*\)/g, "");
  for (const block of css.matchAll(/([^{}]+)\{/g)) for (const match of block[1].matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) scopedClasses.add(match[1]);
}
// Einzige Quelle der Sprachen ist i18n/locales.json (CLAUDE.md, i18n Regel 8).
const localeConfig = JSON.parse(fs.readFileSync(path.join(REPO, "i18n/locales.json"), "utf8"));
const locales = Object.keys(localeConfig.locales);
const namespaces = fs.readdirSync(path.join(REPO, `frontend/messages/${localeConfig.defaultLocale}`)).map((name) => name.replace(/\.json$/, ""));
const rawKeyPattern = new RegExp(`\\b(?:${namespaces.join("|")})\\.[a-zA-Z_]+(?:\\.[a-zA-Z_]+)*\\b`);

const IGNORED_LINK = /^\/(api|_next)\b|logout|abmelden|\/login\b|\.(pdf|zip|csv|xlsx|docx|png|jpe?g)$/i;
const SKIP_CLICK = /abmelden|log ?out|sign ?out|déconnexion|esci/i;
const routePattern = (pathname) =>
  pathname
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, ":id")
    .replace(/\/\d+(?=\/|$)/g, "/:id");

const collectFromPage = (page) =>
  page.evaluate(() => {
    const loaded = new Set();
    const walk = (rules) => {
      for (const rule of rules) {
        if (rule.selectorText) for (const match of rule.selectorText.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) loaded.add(match[1]);
        if (rule.cssRules) walk(rule.cssRules);
      }
    };
    for (const sheet of document.styleSheets) {
      try {
        walk(sheet.cssRules);
      } catch {
        // fremde Stylesheets sind nicht lesbar und für die Prüfung irrelevant
      }
    }
    const used = new Set();
    for (const element of document.querySelectorAll("[class]")) for (const name of element.classList) used.add(name);
    return { loaded: [...loaded], used: [...used], text: document.body.innerText.slice(0, 200000) };
  });

async function crawl(browser, { label, base, cookies, starts, viewport, clicks, locale }) {
  const context = await browser.newContext({ viewport, ignoreHTTPSErrors: true, reducedMotion: "reduce" });
  await context.addCookies(cookies);
  if (locale) await context.addCookies([{ name: localeConfig.cookieName, value: locale, url: base }]);
  const page = await context.newPage();
  // Schreibschutz: alles ausser Lesen wird abgebrochen, auch Abmelden und Löschen.
  await page.route("**/*", (route) => {
    const method = route.request().method();
    return ["GET", "HEAD", "OPTIONS"].includes(method) ? route.continue() : route.abort();
  });
  const findings = { missingCss: new Map(), rawKeys: new Map(), serverErrors: new Map(), jsErrors: new Map(), missingMessages: new Map() };
  let current = "";
  const note = (map, key, where) => {
    if (!map.has(key)) map.set(key, where);
  };
  page.on("pageerror", (error) => note(findings.jsErrors, String(error.message).slice(0, 200), current));
  page.on("console", (message) => {
    if (/MISSING_MESSAGE/.test(message.text())) note(findings.missingMessages, message.text().slice(0, 200), current);
  });
  page.on("response", (response) => {
    if (response.status() >= 500 && response.url().startsWith(base)) note(findings.serverErrors, `${response.status()} ${new URL(response.url()).pathname}`, current);
  });
  const inspect = async (where) => {
    const { loaded, used, text } = await collectFromPage(page);
    const known = new Set(loaded);
    for (const name of used) if (scopedClasses.has(name) && !known.has(name)) note(findings.missingCss, name, where);
    // Audit- und Fehlerprotokoll zeigen technische Codes bewusst im Original
    const raw = /^\/admin\/(audit|error-logs)/.test(where) ? null : text.match(rawKeyPattern);
    if (raw) note(findings.rawKeys, raw[0], where);
  };
  const queue = [...starts];
  const seen = new Map();
  const visited = [];
  let dialogs = 0;
  let shotCount = 0;
  const shot = async (name) => {
    if (shotCount++ < 120) await page.screenshot({ path: path.join(SHOTS, `${label}-${name.replace(/\W+/g, "_").slice(0, 70)}.png`) }).catch(() => {});
  };
  while (queue.length && visited.length < MAX_PAGES) {
    const target = queue.shift();
    const pattern = routePattern(new URL(target, base).pathname);
    if (seen.has(pattern)) continue;
    seen.set(pattern, target);
    current = pattern;
    try {
      await page.goto(base + target, { waitUntil: "load", timeout: 60000 });
      await page.waitForTimeout(1200);
      const landed = routePattern(new URL(page.url()).pathname);
      if (/login/.test(landed)) continue;
      if (landed !== pattern) seen.set(landed, target);
      visited.push(landed);
      await inspect(landed);
      await shot(landed);
      const links = await page.$$eval("a[href]", (nodes) => nodes.map((node) => node.getAttribute("href")));
      for (const href of links) {
        if (!href?.startsWith("/") || href.startsWith("//") || IGNORED_LINK.test(href)) continue;
        const clean = href.split("#")[0];
        if (!seen.has(routePattern(new URL(clean, base).pathname))) queue.push(clean);
      }
      const texts = new Set();
      for (let index = 0, done = 0; done < clicks && index < 80; index++) {
        const button = page.locator(viewport.width < 640 ? "button" : "main button, main [role=tab], main summary, [role=main] button, .admin-page button").nth(index);
        if (!(await button.count())) break;
        if (!(await button.isVisible().catch(() => false)) || (await button.isDisabled().catch(() => true))) continue;
        const name = ((await button.innerText().catch(() => "")) || (await button.getAttribute("aria-label").catch(() => "")) || "").trim().slice(0, 40);
        if (!name || texts.has(name) || SKIP_CLICK.test(name)) continue;
        texts.add(name);
        done++;
        if (!(await button.click({ timeout: 2500 }).then(() => true).catch(() => false))) continue;
        await page.waitForTimeout(500);
        const after = new URL(page.url());
        if (after.pathname !== new URL(target, base).pathname) {
          // Schaltfläche führt auf eine andere Seite: später dort weiter, hier neu laden.
          if (!IGNORED_LINK.test(after.pathname)) queue.push(after.pathname + after.search);
          await page.goto(base + target, { waitUntil: "load", timeout: 60000 });
          await page.waitForTimeout(800);
          continue;
        }
        await inspect(`${landed} → ${name}`);
        const dialog = page.locator("[role=dialog], [role=menu], .modal-sheet").first();
        if (await dialog.isVisible().catch(() => false)) {
          dialogs++;
          if (dialogs <= 40) await shot(`${landed}-dialog-${name}`);
          await page.keyboard.press("Escape");
          await page.waitForTimeout(250);
          if (await page.locator("[role=dialog], .modal-sheet").first().isVisible().catch(() => false)) {
            await page.goto(base + target, { waitUntil: "load", timeout: 60000 });
            await page.waitForTimeout(800);
          }
        }
      }
    } catch (error) {
      note(findings.jsErrors, `Crawler: ${String(error.message).slice(0, 160)}`, pattern);
    }
  }
  await context.close();
  return { visited, dialogs, findings };
}

const entries = (map) => [...map.entries()].map(([what, where]) => `${what} @ ${where}`);

function reportCrawl(id, label, { visited, dialogs, findings }) {
  const missing = entries(findings.missingCss);
  const server = entries(findings.serverErrors);
  const keys = [...entries(findings.rawKeys), ...entries(findings.missingMessages)];
  const js = entries(findings.jsErrors);
  const details = { visited, dialogs, missingCss: missing, serverErrors: server, untranslated: keys, jsErrors: js };
  if (!visited.length) return report(id, "FAIL", `${label}: keine Seite erreicht`, details);
  const status = missing.length || server.length || keys.length ? "FAIL" : js.length ? "WARN" : "PASS";
  report(id, status, `${label}: ${visited.length} Routen, ${dialogs} Dialoge, CSS fehlt ${missing.length}, 5xx ${server.length}, Roh-Schlüssel ${keys.length}, JS-Fehler ${js.length}`, details);
}

// --- TH-22: Ladezeiten ------------------------------------------------------------------------
const median = (values) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];

async function loadMetrics(browser, cookies, target) {
  const runs = [];
  for (let run = 0; run < 3; run++) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, ignoreHTTPSErrors: true });
    await context.addCookies(cookies);
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await page.addInitScript(() => {
      window.__tasks = [];
      new PerformanceObserver((list) => list.getEntries().forEach((entry) => window.__tasks.push(entry.duration))).observe({ type: "longtask", buffered: true });
    });
    await page.goto(BASE + target, { waitUntil: "load", timeout: 120000 });
    await page.waitForTimeout(3000);
    runs.push(
      await page.evaluate(() => {
        const nav = performance.getEntriesByType("navigation")[0];
        const resources = performance.getEntriesByType("resource");
        const kb = (filter) => Math.round(resources.filter(filter).reduce((sum, item) => sum + (item.decodedBodySize || 0), 0) / 1024);
        return {
          ttfb: Math.round(nav.responseStart),
          dom: Math.round(nav.domContentLoadedEventEnd),
          htmlWireKB: Math.round(nav.transferSize / 1024),
          cssKB: kb((item) => item.name.includes(".css")),
          jsKB: kb((item) => item.name.includes(".js")),
          maxTask: Math.round(Math.max(0, ...window.__tasks)),
          blockedMs: Math.round(window.__tasks.reduce((sum, item) => sum + item, 0)),
        };
      }),
    );
    await context.close();
  }
  return Object.fromEntries(Object.keys(runs[0]).map((key) => [key, median(runs.map((item) => item[key]))]));
}

// Grösstes der letzten Protokolle mit Pendenzenblock, oder TH_PROTOCOL_ID, wenn gesetzt.
async function pickProtocol(api) {
  if (env.TH_PROTOCOL_ID) return env.TH_PROTOCOL_ID;
  const response = await api.get("/api/protocols");
  if (!response.ok()) return null;
  const body = await response.json();
  const list = Array.isArray(body) ? body : body.items ?? [];
  let best = null;
  let bestSize = -1;
  for (const protocol of list.slice(0, 12)) {
    const elements = await api.get(`/api/protocols/${protocol.id}/elements`);
    const todos = await api.get(`/api/protocols/${protocol.id}/block-todos`);
    const hasTodoBlocks = todos.ok() && Object.keys(await todos.json()).length > 0;
    // Mit Pendenzenblock zuerst, sonst vergleicht TH-24 nichts
    const size = (elements.ok() ? (await elements.body()).length : 0) + (hasTodoBlocks ? 1e9 : 0);
    if (size > bestSize) [best, bestSize] = [protocol.id, size];
  }
  return best;
}

// --- Ablauf -----------------------------------------------------------------------------------
const browser = await chromium.launch();
const user = await login(BASE, "/api/auth", "WRITER");
const tenantAdmin = await login(BASE, "/api/auth", "TENANT_ADMIN");
const platformAdmin = ADMIN_BASE ? await login(ADMIN_BASE, "/api/admin/auth", "PLATFORM_ADMIN") : { skip: "TH_ADMIN_BASE nicht gesetzt" };

// Ohne Anmeldung
if (wanted("TH-20a")) {
  const result = await crawl(browser, { label: "anon", base: BASE, cookies: [], starts: ["/login"], viewport: { width: 1440, height: 1000 }, clicks: 0 });
  // /login wird für diesen Crawl bewusst nicht als Umleitung gewertet
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const response = await page.goto(`${BASE}/login`, { waitUntil: "load" });
  report("TH-20a", response?.ok() ? "PASS" : "FAIL", `/login antwortet mit ${response?.status()}`, { visited: result.visited });
  await context.close();
}

const crawlStarts = ["/", "/protocols", "/events", "/participants", "/todos", "/lists", "/documents", "/templates", "/elements", "/photos", "/files", "/finances", "/fines", "/statistics", "/agenda", "/submission-assignments", "/shared-links", "/connections", "/tools", "/cycles", "/task-packages", "/settings"];
const adminStarts = ["/tenant-settings", "/tenant-settings/abo", "/tenant-settings/activity", "/tenant-settings/domains", "/tenant-settings/privacy", "/tenant-settings/retention", "/tenant-settings/verification", "/users", "/users/roles", ...crawlStarts];
const desktop = { width: 1440, height: 1000 };
const mobile = { width: 390, height: 844 };

if (!wanted("TH-20b")) {
  // ausgelassen
} else if (user.skip) report("TH-20b", "SKIP", user.skip);
else reportCrawl("TH-20b", "Schreibkonto Desktop", await crawl(browser, { label: "writer", base: BASE, cookies: user.cookies, starts: crawlStarts, viewport: desktop, clicks: MAX_CLICKS }));

if (!wanted("TH-20c")) {
  // ausgelassen
} else if (tenantAdmin.skip) report("TH-20c", "SKIP", tenantAdmin.skip);
else reportCrawl("TH-20c", "Mandanten-Admin Desktop", await crawl(browser, { label: "tenantadmin", base: BASE, cookies: tenantAdmin.cookies, starts: adminStarts, viewport: desktop, clicks: MAX_CLICKS }));

if (!wanted("TH-20d")) {
  // ausgelassen
} else if (platformAdmin.skip) report("TH-20d", "SKIP", platformAdmin.skip);
else reportCrawl("TH-20d", "Plattform-Admin Desktop", await crawl(browser, { label: "platform", base: ADMIN_BASE, cookies: platformAdmin.cookies, starts: ["/admin", "/admin/tenants", "/admin/users", "/admin/plans", "/admin/cashflow", "/admin/storage", "/admin/system", "/admin/jobs", "/admin/backups", "/admin/maintenance", "/admin/document-templates", "/admin/security", "/admin/audit"], viewport: desktop, clicks: MAX_CLICKS }));

const main = user.cookies ? user : tenantAdmin.cookies ? tenantAdmin : null;
if (!main) {
  for (const id of ["TH-20e", "TH-21", "TH-22", "TH-23", "TH-24", "TH-25"]) if (wanted(id)) report(id, "SKIP", "kein nutzbares Mandanten-Konto");
} else {
  if (wanted("TH-20e")) reportCrawl("TH-20e", "Mobil", await crawl(browser, { label: "mobile", base: BASE, cookies: main.cookies, starts: crawlStarts, viewport: mobile, clicks: 4 }));

  // TH-21: Übersetzungen werden je Bereich nachgeladen. In jeder Sprache darf kein Schlüssel roh erscheinen.
  if (wanted("TH-21")) {
    const problems = [];
    let routes = 0;
    for (const locale of locales) {
      const result = await crawl(browser, { label: `i18n-${locale}`, base: BASE, cookies: main.cookies, starts: crawlStarts, viewport: desktop, clicks: 0, locale });
      routes += result.visited.length;
      for (const item of [...entries(result.findings.rawKeys), ...entries(result.findings.missingMessages), ...entries(result.findings.serverErrors)]) problems.push(`${locale}: ${item}`);
    }
    report("TH-21", problems.length ? "FAIL" : "PASS", `${routes} Seitenaufrufe in ${locales.length} Sprachen, ${problems.length} Funde`, { problems });
  }

  const api = await apiFor(BASE, main.cookies);
  const protocolId = await pickProtocol(api);

  // TH-22: Ladezeiten (Median aus 3 Läufen, CPU 4-fach gedrosselt)
  if (wanted("TH-22")) {
    const targets = ["/", "/events", "/participants", "/todos", ...(protocolId ? [`/protocols/${protocolId}`] : [])];
    const metrics = {};
    for (const target of targets) metrics[target] = await loadMetrics(browser, main.cookies, target);
    const problems = [];
    const warnings = [];
    for (const [target, value] of Object.entries(metrics)) {
      const isProtocol = target.startsWith("/protocols/");
      if (value.cssKB > 400) problems.push(`${target}: CSS ${value.cssKB} KB (Grenze 400)`);
      if (value.ttfb > (isProtocol ? 1500 : 800)) problems.push(`${target}: TTFB ${value.ttfb} ms`);
      else if (value.ttfb > (isProtocol ? 800 : 400)) warnings.push(`${target}: TTFB ${value.ttfb} ms`);
      if (value.maxTask > (isProtocol ? 1000 : 500)) warnings.push(`${target}: längste Blockade ${value.maxTask} ms`);
    }
    if (!protocolId) warnings.push("kein Protokoll vorhanden, Protokollseite nicht gemessen");
    report("TH-22", problems.length ? "FAIL" : warnings.length ? "WARN" : "PASS", `${targets.length} Seiten gemessen, ${problems.length} über der Grenze, ${warnings.length} Warnungen`, { metrics, problems, warnings });
  }

  // TH-23: Komprimierung über Traefik, je Antworttyp mit echten Antwortköpfen
  if (wanted("TH-23")) {
    const encoded = (response) => response.headers()["content-encoding"] || "";
    const headers = { "Accept-Encoding": "zstd, br, gzip" };
    const checks = [];
    const html = await api.get("/", { headers });
    const body = await html.text();
    checks.push({ what: "HTML", encoding: encoded(html), want: true, status: html.status() });
    const asset = (pattern) => body.match(pattern)?.[1];
    for (const [what, url] of [["CSS", asset(/href="(\/_next\/static\/[^"]+\.css[^"]*)"/)], ["JS", asset(/src="(\/_next\/static\/[^"]+\.js[^"]*)"/)]]) {
      if (!url) continue;
      const response = await api.get(url, { headers });
      checks.push({ what, encoding: encoded(response), want: true, status: response.status() });
    }
    if (protocolId) {
      const response = await api.get(`/api/protocols/${protocolId}/elements`, { headers });
      const size = (await response.body()).length;
      if (size >= 1024) checks.push({ what: "API-JSON", encoding: encoded(response), want: true, status: response.status() });
    }
    const icon = body.match(/<link[^>]+rel="icon"[^>]+href="([^"]+\.(?:png|ico)[^"]*)"/)?.[1];
    if (icon) {
      const response = await api.get(icon, { headers });
      checks.push({ what: "Icon", encoding: encoded(response), want: false, status: response.status() });
    }
    const wrong = checks.filter((check) => check.status < 400 && Boolean(check.encoding) !== check.want);
    report("TH-23", wrong.length ? "FAIL" : "PASS", wrong.length ? `falsch: ${wrong.map((item) => item.what).join(", ")}` : `${checks.length} Antworttypen korrekt`, { checks });
  }

  // TH-24: Sammel-Endpunkte müssen dasselbe liefern wie die Einzelrouten; Rechte wie dort
  if (!wanted("TH-24")) {
    // ausgelassen
  } else if (!protocolId) report("TH-24", "SKIP", "kein Protokoll vorhanden");
  else {
    const problems = [];
    const bundle = await (await api.get(`/api/protocols/${protocolId}/block-todos`)).json();
    let compared = 0;
    for (const [blockId, todos] of Object.entries(bundle).slice(0, 25)) {
      const single = await (await api.get(`/api/protocol-element-blocks/${blockId}/todos`)).json();
      compared++;
      if (JSON.stringify(single) !== JSON.stringify(todos)) problems.push(`Todos in Block ${blockId} weichen ab`);
    }
    const images = await (await api.get(`/api/protocols/${protocolId}/block-images`)).json();
    for (const [blockId, list] of Object.entries(images).slice(0, 25)) {
      const single = await (await api.get(`/api/protocol-element-blocks/${blockId}/images`)).json();
      compared++;
      if (JSON.stringify(single) !== JSON.stringify(list)) problems.push(`Bilder in Block ${blockId} weichen ab`);
    }
    const anonymous = await pwRequest.newContext({ baseURL: BASE, ignoreHTTPSErrors: true });
    for (const route of ["block-todos", "block-images"]) {
      const denied = await anonymous.get(`/api/protocols/${protocolId}/${route}`);
      if (denied.status() !== 401) problems.push(`${route} ohne Anmeldung: HTTP ${denied.status()} statt 401`);
      const unknown = await api.get(`/api/protocols/${crypto.randomUUID()}/${route}`);
      if (unknown.status() !== 404) problems.push(`${route} unbekanntes Protokoll: HTTP ${unknown.status()} statt 404`);
    }
    await anonymous.dispose();
    report("TH-24", problems.length ? "FAIL" : compared ? "PASS" : "WARN", `${compared} Blöcke verglichen, Rechte geprüft, ${problems.length} Abweichungen`, { protocolId, problems });
  }

  // TH-25: Pendenz tippen, Verzögerung messen, nach Neuladen muss der Text erhalten sein
  if (!wanted("TH-25")) {
    // ausgelassen
  } else if (env.TH_WRITE !== "1") report("TH-25", "SKIP", "Schreibtest nicht freigegeben (TH_WRITE=1 fehlt)");
  else {
    const templates = await (await api.get("/api/templates")).json();
    let created = null;
    try {
      // Testvorlagen zuletzt; eine Vorlage ohne Nummernmuster scheitert und wird übersprungen
      const isTestTemplate = (item) => /E2E|Import/.test(item.name);
      const candidates = [...templates.filter((item) => !isTestTemplate(item)), ...templates.filter(isTestTemplate)];
      let lastError = "keine Vorlage";
      for (const template of candidates.slice(0, 12)) {
        const response = await api.post("/api/protocols/from-template", {
          data: { template_id: template.id, protocol_date: new Date(Date.now() + 40 * 86400000).toISOString().slice(0, 10), title: `Abnahme ${Date.now()}` },
        });
        if (!response.ok()) {
          lastError = `${template.name}: HTTP ${response.status()}`;
          continue;
        }
        const protocol = await response.json();
        const blocks = await (await api.get(`/api/protocols/${protocol.id}/block-todos`)).json();
        if (Object.keys(blocks).length) {
          created = { id: protocol.id, blockId: Object.keys(blocks)[0] };
          break;
        }
        await api.delete(`/api/protocols/${protocol.id}`);
        lastError = `${template.name}: kein Pendenzenblock`;
      }
      if (!created) report("TH-25", "SKIP", `keine Vorlage mit Pendenzenblock unter den ersten 12 (zuletzt ${lastError}); Vorlage anlegen lassen und wiederholen`);
      else {
        const todo = await api.post(`/api/protocol-element-blocks/${created.blockId}/todos`, { data: { task: "Abnahme" } });
        if (!todo.ok()) throw new Error(`Pendenz anlegen: HTTP ${todo.status()} ${(await todo.text()).slice(0, 120)}`);
        const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, ignoreHTTPSErrors: true });
        await context.addCookies(main.cookies);
        const page = await context.newPage();
        await page.addInitScript(() => {
          window.__keys = [];
          new PerformanceObserver((list) => list.getEntries().forEach((entry) => entry.name === "keydown" && window.__keys.push(entry.duration))).observe({ type: "event", durationThreshold: 16 });
        });
        await page.goto(`${BASE}/protocols/${created.id}`, { waitUntil: "load", timeout: 120000 });
        const input = page.locator("textarea.todo-input").first();
        await input.waitFor({ timeout: 60000 });
        await input.scrollIntoViewIfNeeded();
        await input.click();
        await page.keyboard.press("End");
        const cdp = await context.newCDPSession(page);
        await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
        await page.waitForTimeout(800);
        await page.evaluate(() => (window.__keys = []));
        const typed = " Schnell getippter Satz zum Messen";
        await page.keyboard.type(typed, { delay: 80 });
        await page.waitForTimeout(3000);
        const keys = (await page.evaluate(() => window.__keys)).sort((a, b) => a - b);
        const p50 = Math.round(keys[Math.floor(keys.length / 2)] ?? 0);
        await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
        await page.locator("body").click({ position: { x: 5, y: 5 } }).catch(() => {});
        await page.waitForTimeout(2500);
        await context.close();
        const saved = await (await api.get(`/api/protocols/${created.id}/block-todos`)).json();
        const kept = saved[created.blockId]?.some((item) => item.task === `Abnahme${typed}`);
        const status = !kept ? "FAIL" : p50 > 250 ? "FAIL" : p50 > 150 ? "WARN" : "PASS";
        report("TH-25", status, `Text ${kept ? "gespeichert" : "NICHT gespeichert"}, Verzögerung pro Taste p50 ${p50} ms bei 4-facher Drosselung`, { p50, keys: keys.length, saved: saved[created.blockId]?.map((item) => item.task) });
      }
    } catch (error) {
      report("TH-25", "FAIL", String(error.message).slice(0, 200));
    } finally {
      if (created) {
        const removed = await api.delete(`/api/protocols/${created.id}`);
        if (!removed.ok()) report("TH-25c", "WARN", `Wegwerf-Protokoll ${created.id} nicht gelöscht: HTTP ${removed.status()}`);
      }
    }
  }
  await api.dispose();
}
await browser.close();
