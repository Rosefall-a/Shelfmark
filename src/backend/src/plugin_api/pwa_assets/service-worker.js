// Reviewed PWA infrastructure v1. The host prefixes this source with PWA metadata.
const CONFIG = typeof PWA === "undefined" ? { enabled: false, generation: "disabled" } : PWA;
const PREFIX = "unnamed-tracking:pwa:";
const CACHE = PREFIX + CONFIG.generation;
const OFFLINE = "/pwa/offline.html";
let retired = false;
let precache = Promise.resolve();

async function clean(keep) {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => (key.startsWith(PREFIX) || key === "tracking-shell-v1") && key !== keep)
    .map(key => caches.delete(key)));
}

async function retire() {
  retired = true;
  // An installing worker may still be writing the offline page. Do not report
  // retirement until that operation has settled and its cache is removed.
  try { await precache; } catch { /* Failed installation still needs cleanup. */ }
  try { await clean(null); } catch { /* Storage unavailable: still unregister. */ }
  await self.registration.unregister();
}

self.addEventListener("message", event => {
  if (event.data?.type === "tracking-pwa-retire") {
    event.waitUntil(retire().then(() => event.ports?.[0]?.postMessage({ type: "tracking-pwa-retired" })));
  }
});

self.addEventListener("install", event => {
  precache = (async () => {
    if (CONFIG.enabled && !retired) {
      const response = await fetch(OFFLINE, { cache: "no-store", credentials: "omit" });
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) {
        throw new Error("Offline page unavailable");
      }
      if (!retired) await (await caches.open(CACHE)).put(OFFLINE, response);
    }
  })();
  event.waitUntil(precache.then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => event.waitUntil((async () => {
  if (!CONFIG.enabled || retired) { await retire(); return; }
  // The configuration response may predate a concurrent disable/uninstall.
  // Network failure is not withdrawal; only affirmative server state retires.
  try {
    const state = await fetch("/pwa/status", { cache: "no-store", credentials: "omit" });
    if (state.ok && (await state.json()).enabled === false) { await retire(); return; }
  } catch { /* Keep neutral offline behavior during a transient outage. */ }
  await clean(CACHE);
  if (retired) { await retire(); return; }
  await self.clients.claim();
})()));

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  // Private responses never enter a runtime cache. Only navigation has an
  // offline fallback; API/auth/cross-origin and non-GET traffic pass through.
  if (!CONFIG.enabled || retired || event.request.method !== "GET" || url.origin !== self.location.origin ||
      event.request.mode !== "navigate" ||
      /^\/(?:api|login|auth|setup|_startup|pwa)(?:\/|$)/i.test(url.pathname)) return;
  event.waitUntil(fetch("/pwa/status", { cache: "no-store", credentials: "omit" })
    .then(async state => {
      if (!state.ok) return;
      const data = await state.json();
      if (data.enabled === false) await retire();
      else if (data.generation !== CONFIG.generation) await self.registration.update();
    }).catch(() => {}));
  event.respondWith((async () => {
    try {
      const response = await fetch(event.request);
      return response;
    } catch {
      try {
        if (!retired) {
          const page = await caches.match(OFFLINE, { cacheName: CACHE });
          if (page && !retired) return page;
        }
      } catch { /* Storage failure must still yield neutral reconnect guidance. */ }
      return new Response("Waiting for internet. Reconnect and reload Unnamed Tracking.", {
          status: 503, headers: { "Content-Type": "text/plain", "Cache-Control": "no-store" }
        });
    }
  })());
});
