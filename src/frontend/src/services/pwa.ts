import { reactive } from "vue";

type InstallEvent = Event & {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export const pwaState = reactive({
  enabled: false,
  available: false,
  online: navigator.onLine,
  version: "",
  installable: false,
  updatePending: false,
  message: "",
});
let promptEvent: InstallEvent | undefined;
let generation = "";
let registration: ServiceWorkerRegistration | undefined;
let busy = false;
let started = false;
let dirty = false;
let reloading = false;
const workerPath = "/service-worker.js";
const cachePrefix = "unnamed-tracking:pwa:";

function owned(worker: ServiceWorker | null | undefined) {
  return !!worker && new URL(worker.scriptURL).pathname === workerPath;
}

async function retireWorker(worker: ServiceWorker) {
  await new Promise<void>((resolve) => {
    const channel = new MessageChannel();
    const finish = () => {
      window.clearTimeout(timeout);
      channel.port1.close();
      resolve();
    };
    // Earlier worker versions do not acknowledge retirement. Their caches are
    // still cleared below; a failed worker must not block disablement forever.
    const timeout = window.setTimeout(finish, 3000);
    channel.port1.onmessage = (event) => {
      if (event.data?.type === "tracking-pwa-retired") finish();
    };
    try {
      worker.postMessage({ type: "tracking-pwa-retire" }, [channel.port2]);
    } catch {
      finish();
    }
  });
}

async function retire() {
  document.querySelector('link[data-tracking-pwa="manifest"]')?.remove();
  registration = undefined;
  promptEvent = undefined;
  pwaState.installable = false;
  generation = "";
  if ("serviceWorker" in navigator) {
    for (const item of await navigator.serviceWorker.getRegistrations()) {
      if (owned(item.active) || owned(item.waiting) || owned(item.installing)) {
        const workers = [item.active, item.waiting, item.installing].filter(
          (worker): worker is ServiceWorker => owned(worker),
        );
        await Promise.all(workers.map(retireWorker));
        await item.unregister();
      }
    }
  }
  if ("caches" in window) {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter(
          (key) => key.startsWith(cachePrefix) || key === "tracking-shell-v1",
        )
        .map((key) => caches.delete(key)),
    );
  }
}

export async function refreshPwa() {
  if (busy) return;
  busy = true;
  try {
    const response = await fetch("/pwa/status", {
      cache: "no-store",
      credentials: "omit",
    });
    if (!response.ok) throw new Error("PWA infrastructure is unavailable.");
    const status: {
      enabled: boolean;
      generation?: string;
      version?: string;
    } = await response.json();
    if (typeof status.enabled !== "boolean")
      throw new Error("Invalid PWA status.");
    pwaState.enabled = status.enabled;
    pwaState.available = true;
    pwaState.version = status.version || "";
    if (!status.enabled) {
      await retire();
      return;
    }
    if (!window.isSecureContext || !("serviceWorker" in navigator)) {
      pwaState.message =
        "PWA installation requires HTTPS and a supported browser.";
      return;
    }
    const existing = await navigator.serviceWorker.getRegistration("/");
    if (existing?.active && !owned(existing.active)) {
      pwaState.message =
        "Another service worker controls this site. PWA activation is unavailable.";
      return;
    }
    if (!document.querySelector('link[data-tracking-pwa="manifest"]')) {
      const link = document.createElement("link");
      link.rel = "manifest";
      link.href = "/manifest.webmanifest";
      link.dataset.trackingPwa = "manifest";
      document.head.append(link);
    }
    if (!registration) {
      registration = await navigator.serviceWorker.register(workerPath, {
        scope: "/",
        updateViaCache: "none",
      });
    } else if (generation !== status.generation) {
      await registration.update();
    }
    generation = status.generation || "";
    pwaState.message = "";
  } catch {
    // A transient outage is not affirmative disablement. Preserve the neutral
    // offline page and let the ordinary application retain its session policy.
    pwaState.available = false;
    pwaState.message =
      "PWA installation is currently unavailable. Reconnect and try again.";
  } finally {
    busy = false;
  }
}

export function startPwa() {
  if (started) return;
  started = true;
  window.addEventListener("beforeinstallprompt", (event) => {
    if (!pwaState.enabled) return;
    event.preventDefault();
    promptEvent = event as InstallEvent;
    pwaState.installable = true;
  });
  window.addEventListener("appinstalled", () => {
    promptEvent = undefined;
    pwaState.installable = false;
  });
  window.addEventListener("online", () => {
    pwaState.online = true;
    void refreshPwa();
  });
  window.addEventListener("offline", () => (pwaState.online = false));
  document.addEventListener("input", () => (dirty = true));
  if ("serviceWorker" in navigator) {
    let controlled = owned(navigator.serviceWorker.controller);
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      const nowControlled = owned(navigator.serviceWorker.controller);
      if (controlled && nowControlled && !reloading) {
        // A retirement worker also replaces the controller. Confirm a live
        // provider before reloading, so disable/uninstall cannot interrupt
        // ordinary navigation or turn withdrawal into an update prompt.
        void fetch("/pwa/status", { cache: "no-store", credentials: "omit" })
          .then(async (response) => {
            if (!response.ok || !(await response.json()).enabled || reloading)
              return;
            if (!owned(navigator.serviceWorker.controller)) return;
            if (dirty) pwaState.updatePending = true;
            else if (document.readyState === "complete") reloadPwa();
          })
          .catch(() => {});
      }
      controlled = nowControlled;
    });
  }
  void refreshPwa();
  window.setInterval(() => void refreshPwa(), 30000);
}

export function reloadPwa() {
  reloading = true;
  window.location.reload();
}

export async function installPwa() {
  if (!promptEvent) return;
  try {
    await promptEvent.prompt();
    await promptEvent.userChoice;
    promptEvent = undefined;
    pwaState.installable = false;
  } catch {
    pwaState.message =
      "The browser could not install the app. Use its install menu or try again.";
  }
}
