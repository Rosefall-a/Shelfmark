// Real built frontend against the acceptance backend; no mocked API responses.
import assert from "node:assert/strict";
import { createServer, request as httpRequest } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const [pluginsRoot, phase] = process.argv.slice(2);
const require = createRequire(path.join(pluginsRoot, "package.json"));
const { chromium } = require("playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/frontend/dist");
const mime = { ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".html": "text/html" };
const server = createServer(async (incoming, outgoing) => {
  if (incoming.url.startsWith("/api/")) {
    const upstream = httpRequest(new URL(incoming.url, process.env.PLUGIN_GATEWAY_URL), {
      method: incoming.method, headers: incoming.headers,
    }, (response) => {
      outgoing.writeHead(response.statusCode, response.headers);
      response.pipe(outgoing);
    });
    upstream.on("error", (error) => { outgoing.writeHead(502); outgoing.end(String(error)); });
    incoming.pipe(upstream);
    return;
  }
  let relative = decodeURIComponent(new URL(incoming.url, "http://localhost").pathname).replace(/^\//, "");
  if (!relative.startsWith("assets/")) relative = "index.html";
  const file = path.resolve(root, relative);
  if (!file.startsWith(root + path.sep)) { outgoing.writeHead(403); outgoing.end(); return; }
  try {
    outgoing.setHeader("Content-Type", mime[path.extname(file)] ?? "application/octet-stream");
    outgoing.end(await readFile(file));
  } catch { outgoing.writeHead(404); outgoing.end(); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(String(error)));
const review = JSON.parse(process.env.INTEGRATION_REVIEW);
const plugin = page.locator("article.plugin").filter({ has: page.getByRole("heading", { name: "Jellyfin Media Sync", exact: true }) });
try {
  const login = await context.request.post(origin + "/api/auth/login", {
    data: { username_or_email: process.env.PRIMARY_USER_USERNAME, password: process.env.PRIMARY_USER_PASSWORD },
  });
  assert.equal(login.status(), 200);
  let releaseCatalogue;
  if (phase === "offline") {
    const catalogueGate = new Promise((resolve) => { releaseCatalogue = resolve; });
    await page.route("**/api/plugins/catalogues", async (route) => {
      await catalogueGate;
      await route.continue();
    });
  }
  await page.goto(origin + "/settings?section=plugins");
  await page.getByRole("button", { name: "All", exact: true }).waitFor();
  await page.getByText(
    phase === "offline" ? "Plugin runtime unavailable" : "Per-plugin sandbox isolation is unavailable.",
    { exact: false },
  ).waitFor();
  if (phase === "install") {
    await page.getByRole("button", { name: "Available to Install", exact: true }).click();
    await page.getByRole("searchbox", { name: "Filter plugins" }).fill("Jellyfin");
    await page.getByRole("combobox", { name: "Filter by tag" }).selectOption("media");
    assert.equal(await plugin.count(), 1);
    await plugin.getByRole("button", { name: "Review plugin", exact: true }).click();
    const consent = page.getByRole("dialog", { name: "Review Jellyfin Media Sync", exact: true });
    await consent.waitFor();
    await consent.getByText("Plugin documentation", { exact: true }).click();
    await consent.locator(".readme article").waitFor();
    const summary = consent.getByLabel("Requested permission risks").first();
    assert.match(await summary.innerText(), new RegExp(`${review.permissions.length} scopes`));
    assert.equal(await summary.locator(".risk-bubble").count(), 4);
    for (const risk of ["critical", "high", "medium", "low"]) {
      const count = review.permissions.filter((item) => item.risk === risk).length;
      assert.match(await summary.locator(`.risk-bubble.${risk}`).innerText(), new RegExp(`^${count}\\s`));
    }
    for (const category of await consent.locator(".category-header input[type=checkbox]").all()) await category.check();
    assert.match(await consent.innerText(), new RegExp(`${review.permissions.length} of ${review.permissions.length} newly granted`));
    await page.screenshot({ path: path.join(process.env.INTEGRATION_WORK_ROOT, "permission-review.png"), fullPage: true });
    // Hold a real contribution request to reproduce fast-install/slow-refresh timing.
    let releaseRefresh;
    let holdRefresh = true;
    const refreshGate = new Promise((resolve) => { releaseRefresh = resolve; });
    const refreshRequest = page.waitForRequest("**/api/plugins/example.jellyfin-media-sync/ui");
    await page.route("**/api/plugins/example.jellyfin-media-sync/ui", async (route) => {
      if (holdRefresh) { holdRefresh = false; await refreshGate; }
      await route.continue();
    });
    await consent.getByRole("button", { name: "Install with selected access", exact: true }).click();
    await consent.waitFor({ state: "hidden" });
    await refreshRequest;
    assert.equal(await page.getByRole("button", { name: "Install a plugin", exact: true }).isDisabled(), true);
    releaseRefresh();
    await page.getByRole("button", { name: "Installed", exact: true }).click();
    await plugin.getByText("running", { exact: true }).waitFor();
    await page.getByRole("button", { name: "All", exact: true }).click();
    assert.equal(await plugin.count(), 1);
    // Same installation selected from the catalogue produces explicit choices.
    await page.getByRole("button", { name: "Install a plugin", exact: true }).click();
    await page.locator(".catalogue-entry").filter({ hasText: "Jellyfin Media Sync" }).getByRole("button", { name: "Install", exact: true }).click();
    const duplicate = page.getByRole("dialog", { name: "Plugin already installed" });
    await duplicate.waitFor();
    for (const name of ["Review update", "Reinstall installed release, retaining data", "Replace package", "Cancel"]) {
      assert.equal(await duplicate.getByRole("button", { name, exact: true }).count(), 1);
    }
    await duplicate.getByRole("button", { name: "Cancel", exact: true }).click();
    await duplicate.waitFor({ state: "hidden" });
    await page.getByRole("dialog", { name: "Install a plugin", exact: true }).getByRole("button", { name: "Close", exact: true }).click();
    await page.goto(origin + "/plugins/example.jellyfin-media-sync");
    await page.getByText("Jellyfin server URL", { exact: true }).waitFor();
    await page.screenshot({ path: path.join(process.env.INTEGRATION_WORK_ROOT, "jellyfin-native-ui.png"), fullPage: true });
    console.log("Browser catalogue filtering, README, scope counts, risk bubbles, approval, installation, duplicate choices and native UI: passed");
  } else if (phase === "offline") {
    // Backend inventory must render even before catalogue discovery completes.
    await plugin.getByText("unknown", { exact: true }).first().waitFor();
    assert.equal(await plugin.count(), 1);
    await page.getByText("Refreshing catalogues…", { exact: true }).waitFor();
    await page.screenshot({ path: path.join(process.env.INTEGRATION_WORK_ROOT, "offline-inventory.png"), fullPage: true });
    releaseCatalogue();
    await plugin.getByRole("button", { name: "Manage plugin", exact: true }).click();
    const settings = page.getByRole("dialog", { name: "Jellyfin Media Sync", exact: true });
    await settings.getByRole("button", { name: "Diagnostics", exact: true }).click();
    await settings.getByText("Runtime availability", { exact: true }).waitFor();
    assert.equal(await settings.getByText("Active", { exact: true }).count(), 0);
    assert.equal(await settings.getByText("Reduced isolation", { exact: true }).count(), 0);
    await page.screenshot({ path: path.join(process.env.INTEGRATION_WORK_ROOT, "offline-diagnostics.png"), fullPage: true });
    console.log("Browser authoritative installed inventory during runtime outage and delayed catalogues: passed");
  } else {
    await page.getByRole("button", { name: "All", exact: true }).click();
    await page.getByRole("heading", { name: "Integration catalogue help", exact: true }).waitFor();
    await page.getByRole("heading", { name: "Scoped Document Viewer", exact: true }).waitFor();
    assert.equal(await plugin.count(), 1);
    await page.getByRole("button", { name: "Updates Available", exact: true }).click();
    await plugin.getByRole("button", { name: /^Review v.* update$/ }).click();
    const consent = page.getByRole("dialog", { name: "Review Jellyfin Media Sync", exact: true });
    await consent.waitFor();
    await page.screenshot({ path: path.join(process.env.INTEGRATION_WORK_ROOT, "update-review.png"), fullPage: true });
    await consent.getByRole("button", { name: "Update with selected access", exact: true }).click();
    await consent.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Installed", exact: true }).click();
    await plugin.getByText("running", { exact: true }).waitFor();
    console.log("Browser Updates Available direct review and update: passed");
  }
  assert.deepEqual(errors, [], "Browser runtime errors");
} catch (error) {
  await page.screenshot({ path: path.join(process.env.INTEGRATION_WORK_ROOT, `browser-${phase}-failure.png`), fullPage: true });
  throw error;
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
