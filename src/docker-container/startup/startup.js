const phaseNames = {
    INITIALIZING: "Initialising",
    WAITING_FOR_DATABASE: "Waiting for database",
    DATABASE_READY: "Database ready",
    MIGRATING_DATABASE: "Migrating database",
    STARTING_BACKEND: "Starting backend",
    STARTING_FRONTEND: "Starting frontend",
    READY: "Ready",
    CONFIGURATION_FAILED: "Configuration error",
    DATABASE_FAILED: "Database failed",
    MIGRATION_FAILED: "Migration failed",
    BACKEND_FAILED: "Backend failed",
    BACKEND_TIMEOUT: "Backend timeout",
    FRONTEND_FAILED: "Frontend failed",
    BACKEND_CRASHED: "Backend stopped"
};

const labels = ["database", "migrations", "backend", "frontend"];
const pretty = v => v ? v.charAt(0).toUpperCase() + v.slice(1) : "unknown";

let pollInterval = 50;   // fast until READY
let ready = false;

function render(s) {
    const titleEl = document.querySelector("#title");
    const spinnerEl = document.querySelector("#spinner");
    const tickEl = document.querySelector("#ready-icon");
    const failureEl = document.querySelector("#failure-icon");
    const failed = s.overall === "failed" || /(?:_FAILED|_CRASHED)$/.test(s.phase || "");

    // Title + heading
    if (s.overall === "ready") {
        document.title = "Unnamed Tracking";
        titleEl.textContent = "Application Started";
    } else if (failed) {
        document.title = "Unnamed Tracking — Failed";
        titleEl.textContent = "Application failed";
    } else {
        document.title = "Unnamed Tracking — Starting";
        titleEl.textContent = "Starting application";
    }

    // Phase + message
    document.querySelector("#phase").textContent = phaseNames[s.phase] || s.phase;
    document.querySelector("#message").textContent = failed
        ? (s.message || "The application could not finish starting.")
        : (s.message || "");

    // Steps
    document.querySelector("#steps").innerHTML = labels.map(k =>
        `<div class="step ${s[k] || "unknown"}">
            <span>${k}</span>
            <span>${pretty(s[k])}</span>
        </div>`
    ).join("");

    // Details on failure
    const details = document.querySelector("details");
    if (failed) {
        spinnerEl.style.animationPlayState = "paused";
        details.open = true;
    }

    // Icon and reload logic: only one status icon is visible
    if (s.phase === "READY") {
        if (!ready) {
            ready = true;
            pollInterval = 10000;
        }

        spinnerEl.hidden = true;
        tickEl.style.display = "inline-flex";
        failureEl.style.display = "none";
    } else if (failed) {
        // failed: show failure icon, hide spinner and tick
        ready = false;
        pollInterval = 10000;

        spinnerEl.hidden = true;
        tickEl.style.display = "none";
        failureEl.style.display = "inline-flex";
    } else {
        // not ready: show spinner, hide tick and failure icon
        ready = false;
        pollInterval = 200;

        spinnerEl.hidden = false;
        tickEl.style.display = "none";
        failureEl.style.display = "none";
    }
}


async function poll() {
    try {
        const r = await fetch("/_startup/status.json?ts=" + Date.now(), { cache: "no-store" });
        if (r.ok) render(await r.json());

        const d = await fetch("/_startup/details.txt?ts=" + Date.now(), { cache: "no-store" });
        if (d.ok) document.querySelector("#details").textContent = await d.text();
    } catch {
        document.querySelector("#message").textContent =
            "Waiting for the startup service to respond…";
    }

    setTimeout(poll, pollInterval);
}

poll();
