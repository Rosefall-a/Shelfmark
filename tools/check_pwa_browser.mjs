// Full browser + real Plugin Manager acceptance. No plugin API is mocked.
import assert from "node:assert/strict";
import { createServer, request as httpRequest } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const [pluginsRoot] = process.argv.slice(2);
const require = createRequire(path.join(pluginsRoot, "package.json"));
const { chromium } = require("playwright");
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/frontend/dist");
const server = createServer(async (incoming, outgoing) => {
  if (/^\/(?:api\/|pwa\/|service-worker\.js|manifest\.webmanifest)/.test(incoming.url)) {
    const upstream = httpRequest(new URL(incoming.url, process.env.PLUGIN_GATEWAY_URL), {
      method: incoming.method, headers: incoming.headers,
    }, response => { outgoing.writeHead(response.statusCode, response.headers); response.pipe(outgoing); });
    upstream.on("error", () => { outgoing.writeHead(503); outgoing.end(); });
    incoming.pipe(upstream);
    return;
  }
  const relative = decodeURIComponent(new URL(incoming.url, "http://localhost").pathname).slice(1);
  const file = path.resolve(frontend, relative.startsWith("assets/") ? relative : "index.html");
  if (!file.startsWith(frontend + path.sep)) { outgoing.writeHead(403); outgoing.end(); return; }
  try {
    outgoing.setHeader("Content-Type", ({ ".js": "text/javascript", ".css": "text/css", ".html": "text/html" })[path.extname(file)] || "application/octet-stream");
    outgoing.end(await readFile(file));
  } catch { outgoing.writeHead(404); outgoing.end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
// The disposable HTTPS catalogue points at a fixture branch which is never
// published. Map its public icon acquisition to the same real source bytes;
// host/plugin routes and browser service-worker infrastructure remain real.
await context.route("https://raw.githubusercontent.com/Rosefall-a/unnamed_tracking_app_plugins/integration-fixture/official/pwa/pwa/pwa-icon.svg", async route => {
  await route.fulfill({ contentType: "image/svg+xml", body: await readFile(path.join(process.env.PWA_ACCEPTANCE_ROOT, "official/pwa/pwa/pwa-icon.svg")) });
});
const page = await context.newPage();
const checkpoints = [];
async function checkpoint(name) {
  checkpoints.push(name);
  await writeFile(path.join(process.env.PWA_ACCEPTANCE_WORK, "pwa-conformance.json"), JSON.stringify({
    status: "running", package_version: "0.0.1", passed: checkpoints,
    limitation: "OS install surfaces and physical Android/iOS/Windows device testing require human devices.",
  }, null, 2));
  console.log(name);
}
async function api(method, route, expected = 200, options = {}) {
  const response = await context.request.fetch(origin + route, { method, ...options });
  assert.equal(response.status(), expected, `${route}: ${await response.text()}`);
  return response.status() === 204 ? null : await response.json();
}
const source = version => ({ url: `https://raw.githubusercontent.com/Rosefall-a/unnamed_tracking_app_plugins/integration-fixture/dist/official.pwa-${version}.utp`, source_type: "catalogue",
  catalogue_url: "https://raw.githubusercontent.com/Rosefall-a/unnamed_tracking_app_plugins/integration-fixture/list.json" });
const pluginPath = "/api/plugins/official.pwa";
const current = async () => (await api("GET", "/api/plugins")).find(item => item.plugin_id === "official.pwa");
const upload = async name => ({ file: { name: name + ".utp", mimeType: "application/octet-stream",
  buffer: await readFile(path.join(process.env.PWA_ACCEPTANCE_WORK, name + ".utp")) } });
const cacheKeys = () => page.evaluate(() => caches.keys());
async function reloadControlled() {
  await page.goto(origin + "/");
  await page.waitForFunction(() => !!navigator.serviceWorker.controller, { timeout: 30000 });
}
try {
  await api("POST", "/api/auth/login", 200, { data: { username_or_email: process.env.PRIMARY_USER_USERNAME, password: process.env.PRIMARY_USER_PASSWORD } });
  const unsigned = await api("POST", "/api/plugins/install/preview", 200, { multipart: await upload("unsigned") });
  assert.equal(unsigned.publisher_channel, "unverified");
  assert.equal(unsigned.trust_status, "unsigned");
  await api("POST", "/api/plugins/install", 409, { multipart: await upload("unsigned") });
  await api("POST", "/api/plugins/install", 201, {
    params: { allow_untrusted: "true", confirm_dangerous: "true", approved_permissions: unsigned.permissions[0].key },
    multipart: { ...await upload("unsigned"), admin_password: process.env.PRIMARY_USER_PASSWORD },
  });
  assert.equal((await current()).trust.publisher_channel, "unverified");
  assert.equal((await api("GET", "/pwa/status")).enabled, true);
  await api("DELETE", pluginPath, 204);
  const invalid = await api("POST", "/api/plugins/install/preview", 200, { multipart: await upload("invalid") });
  assert.equal(invalid.installable, false);
  await api("POST", "/api/plugins/install", 400, { params: { allow_untrusted: "true" }, multipart: await upload("invalid") });
  await api("POST", "/api/plugins/install/preview", 400, { multipart: { file: { name: "malformed.utp", mimeType: "application/octet-stream", buffer: Buffer.from("invalid archive") } } });
  assert.equal((await api("GET", "/pwa/status")).enabled, false);
  await checkpoint("unsigned requires consent; bad signature cannot be overridden; malformed PWA package rejected before execution");
  await api("PATCH", "/api/plugins/catalogues/official", 200, { data: { enabled: false } });
  await api("POST", "/api/plugins/catalogues", 201, { data: { name: "PWA acceptance", url: source("0.0.1").catalogue_url } });
  const catalogue = await api("GET", "/api/plugins/catalog?source=" + encodeURIComponent(source("0.0.1").catalogue_url));
  assert.equal(catalogue[0].plugin_id, "official.pwa");
  const preview = await api("POST", "/api/plugins/install/preview-url", 200, { data: source("0.0.1") });
  assert.equal(preview.publisher_channel, "official");
  assert.equal(preview.signing_version, 2);
  assert.equal(preview.signature_verified, true);
  assert.equal(preview.permissions[0].capability, "frontend.pwa");
  await api("POST", "/api/plugins/install/url", 201, { data: source("0.0.1") });
  assert.equal((await api("GET", "/pwa/status")).enabled, false);
  await api("POST", pluginPath + "/permissions/grant", 200, { data: { approved_permissions: [preview.permissions[0].key], expected_digest: preview.package_digest } });
  assert.equal((await current()).status, "running");
  assert.equal((await current()).trust.publisher_channel, "official");
  await api("POST", pluginPath + "/permissions/revoke");
  assert.equal((await api("GET", "/pwa/status")).enabled, false);
  assert.equal((await context.request.get(origin + "/manifest.webmanifest")).status(), 404);
  await api("POST", pluginPath + "/permissions/grant", 200, { data: { approved_permissions: [preview.permissions[0].key], expected_digest: preview.package_digest } });
  assert.equal((await api("GET", "/pwa/status")).enabled, true);
  await checkpoint("discover → signed inspection → real installation → explicit site-wide permission → healthy worker");

  await reloadControlled();
  await page.goto(origin + "/settings?section=plugins");
  await page.getByText("Official · verified", { exact: true }).waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll(".plugin img")].every(icon => icon.complete && icon.naturalWidth > 0));
  await page.screenshot({ path: path.join(process.env.PWA_ACCEPTANCE_WORK, "pwa-plugin-installed.png"), fullPage: true });
  const status1 = await api("GET", "/pwa/status");
  const manifest = await api("GET", "/manifest.webmanifest");
  assert.equal(manifest.scope, "/");
  assert.equal(manifest.start_url, "/?pwa=1");
  assert.equal(manifest.id, "/");
  for (const icon of manifest.icons) assert.equal((await context.request.get(origin + icon.src)).status(), 200);
  const cdp = await context.newCDPSession(page);
  const parsed = await cdp.send("Page.getAppManifest");
  assert.equal(parsed.url, origin + "/manifest.webmanifest");
  assert.ok(parsed.data.includes("Unnamed Tracking"));
  await page.evaluate(async () => { await caches.open("another-app-cache"); });
  const keys1 = await cacheKeys();
  assert.ok(keys1.includes("unnamed-tracking:pwa:" + status1.generation));
  await page.evaluate(async () => {
    const keys = await caches.keys();
    for (const key of keys.filter(key => key.startsWith("unnamed-tracking:pwa:"))) {
      const entries = await (await caches.open(key)).keys();
      if (entries.length !== 1 || !entries[0].url.endsWith("/pwa/offline.html")) throw new Error("Private or unexpected cache entry");
    }
  });
  await checkpoint("real frontend reload → official UI badge → browser parses root PWA manifest/icons → cache contains only neutral offline HTML");

  await context.setOffline(true);
  await page.goto(origin + "/?pwa=1");
  await page.getByRole("heading", { name: "Waiting for internet", exact: true }).waitFor();
  await page.screenshot({ path: path.join(process.env.PWA_ACCEPTANCE_WORK, "pwa-offline.png") });
  assert.equal(await page.evaluate(async () => { try { await fetch("/api/auth/me"); return "unexpected"; } catch { return "network failure"; } }), "network failure");
  await page.evaluate(async () => {
    for (const key of (await caches.keys()).filter(key => key.startsWith("unnamed-tracking:pwa:"))) {
      await (await caches.open(key)).delete("/pwa/offline.html");
    }
  });
  const missingCache = await page.goto(origin + "/?pwa=1");
  assert.equal(missingCache.status(), 503);
  await page.getByText("Waiting for internet. Reconnect and reload Unnamed Tracking.", { exact: true }).waitFor();
  await context.setOffline(false);
  await reloadControlled();
  await checkpoint("offline app launch → neutral reconnect page → private API fails offline → missing cache falls back safely → online full application returns");

  await writeFile(path.join(process.env.PWA_ACCEPTANCE_ROOT, "list.json"),
    await readFile(path.join(process.env.PWA_ACCEPTANCE_WORK, "catalogue-0.0.2.json")));
  await api("POST", pluginPath + "/update/preview-url", 200, { data: source("0.0.2") });
  await api("PUT", pluginPath + "/auto-update", 200, { data: { mode: "enabled" } });
  const automatic = execFileSync(process.env.PWA_ACCEPTANCE_PYTHON, [path.join(path.dirname(fileURLToPath(import.meta.url)), "check_plugin_repository_lifecycle.py"), "--mode", "automatic"], { env: process.env, encoding: "utf8" });
  assert.equal(JSON.parse(automatic.trim().split("\n").at(-1)).installed, 1);
  assert.equal((await current()).version, "0.0.2");
  await reloadControlled();
  const status2 = await api("GET", "/pwa/status");
  assert.notEqual(status2.generation, status1.generation);
  await page.waitForFunction(async generation => {
    const keys = await caches.keys();
    return keys.includes("unnamed-tracking:pwa:" + generation) && keys.filter(key => key.startsWith("unnamed-tracking:pwa:")).length === 1;
  }, status2.generation);
  assert.ok((await cacheKeys()).includes("another-app-cache"));
  assert.equal((await context.request.get(origin + manifest.icons[0].src)).status(), 404);
  await checkpoint("real automatic signed update → automatic worker replacement → owned cache migration → stale icon withdrawn → unrelated cache retained");

  const package3 = await readFile(path.join(process.env.PWA_ACCEPTANCE_ROOT, "dist/official.pwa-0.0.3.utp"));
  const failed = await context.request.put(origin + pluginPath + "/update", { multipart: { file: { name: "broken.utp", mimeType: "application/octet-stream", buffer: package3 } } });
  assert.equal(failed.status(), 200, await failed.text());
  assert.equal((await failed.json()).status, "rolled_back");
  assert.equal((await current()).version, "0.0.2");
  assert.equal((await api("GET", "/pwa/status")).generation, status2.generation);
  await api("PUT", pluginPath + "/update", 409, { multipart: { file: {
    name: "old.utp", mimeType: "application/octet-stream",
    buffer: await readFile(path.join(process.env.PWA_ACCEPTANCE_ROOT, "dist/official.pwa-0.0.1.utp")),
  } } });
  await checkpoint("failed real-worker update rolls back PWA provider/assets/grants; old version update rejected");

  await api("POST", pluginPath + "/disable");
  assert.equal((await api("GET", "/pwa/status")).enabled, false);
  assert.equal((await context.request.get(origin + "/manifest.webmanifest")).status(), 404);
  await page.goto(origin + "/?pwa=1");
  await page.waitForFunction(async () => !(await navigator.serviceWorker.getRegistrations()).length);
  assert.ok(!(await cacheKeys()).some(key => key.startsWith("unnamed-tracking:pwa:")));
  await page.getByText("PWA plugin is not enabled.", { exact: false }).waitFor();
  await page.screenshot({ path: path.join(process.env.PWA_ACCEPTANCE_WORK, "pwa-plugin-disabled.png") });
  await api("DELETE", pluginPath, 204);
  await writeFile(path.join(process.env.PWA_ACCEPTANCE_ROOT, "list.json"),
    await readFile(path.join(process.env.PWA_ACCEPTANCE_WORK, "catalogue-0.0.1.json")));
  await api("POST", "/api/plugins/install/url", 201, { params: { approved_permissions: preview.permissions[0].key }, data: source("0.0.1") });
  await reloadControlled();
  const reinstalled = await api("GET", "/pwa/status");
  assert.notEqual(reinstalled.generation, status1.generation);
  await checkpoint("disabled while browser PWA is installed → installability/cache/worker withdrawn → uninstall → reinstall receives fresh identity");

  execFileSync(process.env.PWA_ACCEPTANCE_PYTHON, [path.join(path.dirname(fileURLToPath(import.meta.url)), "check_pwa_lifecycle.py"), "--expire-session"], { env: process.env });
  await page.goto(origin + "/");
  await page.waitForURL("**/login");
  const cacheEntries = await page.evaluate(async () => {
    const keys = await caches.keys();
    return (await Promise.all(keys.filter(key => key.startsWith("unnamed-tracking:pwa:")).map(async key => (await (await caches.open(key)).keys()).map(r => r.url)))).flat();
  });
  assert.ok(cacheEntries.every(url => url.endsWith("/pwa/offline.html")));
  await checkpoint("real API session expires → default login; credentials and private responses absent from caches");
  await api("POST", "/api/auth/login", 200, { data: { username_or_email: process.env.PRIMARY_USER_USERNAME, password: process.env.PRIMARY_USER_PASSWORD } });
  await api("DELETE", pluginPath, 204);
  const brokenInstall = await context.request.post(origin + "/api/plugins/install", { multipart: { file: { name: "broken.utp", mimeType: "application/octet-stream", buffer: package3 } } });
  assert.equal(brokenInstall.status(), 201, await brokenInstall.text());
  const brokenResult = await brokenInstall.json();
  assert.equal(brokenResult.healthy, false);
  assert.equal(brokenResult.status, "unhealthy");
  assert.notEqual((await current()).status, "running");
  assert.equal((await api("GET", "/pwa/status")).enabled, false);
  assert.equal((await context.request.get(origin + "/manifest.webmanifest")).status(), 404);
  await api("DELETE", pluginPath, 204);
  assert.equal(await current(), undefined);
  await checkpoint("failed initial worker startup is visibly unhealthy, exposes no PWA assets/provider, and uninstalls cleanly");
  await page.goto(origin + "/");
  await page.waitForFunction(async () => !(await navigator.serviceWorker.getRegistrations()).length);
  await writeFile(path.join(process.env.PWA_ACCEPTANCE_WORK, "pwa-conformance.json"), JSON.stringify({ status: "passed", package_version: "0.0.1", passed: checkpoints, limitation: "Native browser OS installation UI and physical device coverage remain manual." }, null, 2));
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
