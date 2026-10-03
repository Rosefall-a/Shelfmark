let token = document.querySelector('meta[name="devcontainer-token"]').content;
let busy = false;

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {}), "X-Devcontainer-Token": token}
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Request failed");
  return result;
}

function setBusy(button, state, label) {
  button.disabled = state;
  button.classList.toggle("busy", state);
  button.textContent = state ? "Working…" : label;
}

function value(id) { return document.querySelector(id).value; }

let environmentScope = null;
let currentInstance = null;

function loadEnvironment(result) {
  document.querySelector("#env-editor").value = result.text || "";
  document.querySelector("#env-state").textContent = result.scope === "instance" ? "Instance loaded" : "Global loaded";
}

async function openEnvironment(instanceId = null) {
  currentInstance = instanceId;
  environmentScope = instanceId ? "instance" : "global";
  const result = await api("/api/environment" + (instanceId ? "?instance_id=" + encodeURIComponent(instanceId) : ""));
  loadEnvironment(result);
  document.querySelector("#env-modal-title").textContent = instanceId ? "Instance .env" : "Global .env";
  document.querySelector("#env-modal").showModal();
}

async function saveEnvironment() {
  const b = document.querySelector("#save-env");
  setBusy(b, true, "Save .env");
  document.querySelector("#env-state").textContent = "Saving…";
  try {
    const result = await api("/api/environment", {
      method: "PUT",
      body: JSON.stringify({instance_id: currentInstance, text: value("#env-editor")})
    });
    loadEnvironment(result);
    document.querySelector("#last-action").textContent =
      (currentInstance ? "Instance" : "Global") + " .env saved. Rebuild/restart the affected stack to apply it.";
    document.querySelector("#env-modal").close();
  } catch (error) {
    document.querySelector("#env-state").textContent = "Save failed";
    document.querySelector("#output").textContent = error.message;
  } finally {
    setBusy(b, false, "Save .env");
  }
}

async function buildImages() {
  const b = document.querySelector("#build-images");
  setBusy(b, true, "Build all 3 images from source");
  document.querySelector("#last-action").textContent = "Building all 3 images…";
  document.querySelector("#output").textContent = "Building production, frontend and backend images. This may take several minutes…";
  try {
    const result = await api("/api/build-images", {method: "POST", body: JSON.stringify({tag: value("#build-tag") || "main"})});
    document.querySelector("#last-action").textContent = "All 3 images built and tagged.";
    document.querySelector("#output").textContent = result.output || "";
  } catch (error) {
    document.querySelector("#last-action").textContent = "Image build failed.";
    document.querySelector("#output").textContent = error.message;
  } finally { setBusy(b, false, "Build all 3 images from source"); }
}

function syncTagField() {
  const mode = document.querySelector("#instance-mode").value;
  const tag = document.querySelector("#instance-tag");
  const tagLabel = document.querySelector("#instance-tag-label");
  const enabled = mode === "tag";
  tag.disabled = !enabled;
  tagLabel.classList.toggle("hidden", !enabled);
  if (!enabled) tag.value = "main";
}

function editInstance(instance) {
  document.querySelector("#instance-id").value = instance.id;
  document.querySelector("#instance-env").value = instance.environment;
  document.querySelector("#instance-port").value = instance.port;
  document.querySelector("#instance-mode").value = instance.build_mode || "source";
  document.querySelector("#instance-tag").value = instance.tag || "main";
  syncTagField();
  document.querySelector("#save-instance").textContent = "Save instance";
}

function clearInstanceForm() {
  document.querySelector("#instance-form").reset();
  document.querySelector("#instance-id").value = "";
  document.querySelector("#instance-mode").value = "source";
  document.querySelector("#instance-tag").value = "main";
  syncTagField();
  document.querySelector("#save-instance").textContent = "Add instance";
}

async function saveInstance(event) {
  event.preventDefault();
  const button = document.querySelector("#save-instance");
  const originalLabel = button.textContent;
  const editing = Boolean(value("#instance-id"));
  setBusy(button, true, originalLabel);
  try {
    const payload = {
      id: value("#instance-id") || ("instance-" + Date.now()),
      environment: value("#instance-env"),
      port: Number(value("#instance-port")),
      build_mode: value("#instance-mode"),
      tag: value("#instance-tag") || "main"
    };
    const result = await api("/api/instances", {method: editing ? "PUT" : "POST", body: JSON.stringify(payload)});
    document.querySelector("#last-action").textContent = "Instance saved.";
    clearInstanceForm();
    render(result);
  } catch (error) {
    document.querySelector("#output").textContent = error.message;
  } finally {
    setBusy(button, false, editing ? "Save instance" : "Add instance");
  }
}

async function deleteInstance(id) {
  if (!confirm("Remove this instance definition? Running containers are not stopped automatically.")) return;
  try {
    render(await api("/api/instances", {method: "DELETE", body: JSON.stringify({id})}));
    document.querySelector("#last-action").textContent = "Instance definition removed.";
  } catch (error) {
    document.querySelector("#output").textContent = error.message;
  }
}

function actionButton(instance, action, label, className = "") {
  const b = document.createElement("button");
  b.textContent = label;
  if (className) b.classList.add(className);
  b.dataset.action = action;
  b.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    setBusy(b, true, label);
    document.querySelector("#last-action").textContent = label + " " + instance.name + "…";
    document.querySelector("#output").textContent = action === "logs" ? "Fetching recent container logs…" : "Docker is working. Deploy waits for the application to become healthy.";
    try {
      const result = await api("/api/action", {method: "POST", body: JSON.stringify({instance_id: instance.id, action})});
      document.querySelector("#last-action").textContent = "Action completed.";
      document.querySelector("#output").textContent = result.output || "";
      await refresh();
    } catch (error) {
      document.querySelector("#last-action").textContent = "Action failed.";
      document.querySelector("#output").textContent = error.message;
    } finally {
      setBusy(b, false, label);
      busy = false;
    }
  });
  return b;
}

function render(instances) {
  const root = document.querySelector("#stacks");
  root.replaceChildren();
  for (const instance of instances) {
    const section = document.createElement("section");
    section.className = "stack";
    section.dataset.instanceId = instance.id;
    const title = document.createElement("h2");
    title.textContent = instance.name;
    const summary = document.createElement("div");
    summary.className = "status";
    summary.textContent = [
      (instance.environment === "prod" ? "Production-like" : "Development") + " · " + instance.build_mode,
      "Project: " + instance.project,
      "URL: http://localhost:" + instance.port + "/",
      "Final tag: " + (instance.tag || "main"),
      instance.build_mode === "tag" ? "Images: fixed GHCR repositories" : "Images: current checkout"
    ].join("\n");
    const actions = document.createElement("div");
    actions.className = "actions";
    const deploy = actionButton(instance, "start", "Deploy", "deploy");
    const stop = actionButton(instance, "stop", "Stop", "stop");
    stop.hidden = true;
    actions.append(deploy, stop, actionButton(instance, "rebuild", "Redeploy", "rebuild"),
      actionButton(instance, "reset", "Reset volumes", "danger"),
      actionButton(instance, "logs", "Logs"));
    const edit = document.createElement("button");
    edit.textContent = "Edit";
    edit.addEventListener("click", () => editInstance(instance));
    actions.appendChild(edit);
    const env = document.createElement("button");
    env.textContent = ".env";
    env.addEventListener("click", () => openEnvironment(instance.id));
    actions.appendChild(env);
    const remove = document.createElement("button");
    remove.textContent = "Remove";
    remove.addEventListener("click", () => deleteInstance(instance.id));
    const open = document.createElement("a");
    open.className = "button-link";
    open.href = "http://localhost:" + instance.port + "/";
    open.target = "_blank";
    open.rel = "noreferrer";
    open.textContent = "Open";
    actions.appendChild(open);
    remove.classList.add("danger");
    actions.appendChild(remove);
    const live = document.createElement("div");
    live.className = "live-status";
    live.textContent = "Checking…";
    section.append(title, summary, live, actions);
    root.appendChild(section);
  }
}

async function refresh() {
  try { render(await api("/api/instances")); }
  catch (error) {
    document.querySelector("#last-action").textContent = "Unable to read instances.";
    document.querySelector("#output").textContent = error.message;
  }
}

document.querySelector("#save-env").addEventListener("click", saveEnvironment);
document.querySelector("#edit-global-env").addEventListener("click", () => openEnvironment());
document.querySelector("#close-env").addEventListener("click", () => document.querySelector("#env-modal").close());
document.querySelector("#cancel-env").addEventListener("click", () => document.querySelector("#env-modal").close());
document.querySelector("#build-images").addEventListener("click", buildImages);
document.querySelector("#instance-form").addEventListener("submit", saveInstance);
document.querySelector("#instance-mode").addEventListener("change", syncTagField);
document.querySelector("#instance-tag").addEventListener("input", (event) => {
  if (event.target.value.trim() && document.querySelector("#instance-mode").value !== "tag") {
    document.querySelector("#instance-mode").value = "tag";
    syncTagField();
    event.target.focus();
  }
});
syncTagField();
document.querySelector("#cancel-instance").addEventListener("click", clearInstanceForm);
async function loadPage() {
  try {
    const instances = await api("/api/instances");
    render(instances);
    await refreshStatus();
  } catch (error) {
    document.querySelector("#last-action").textContent = "Unable to load developer environment.";
    document.querySelector("#output").textContent = error.message;
  }
}

async function refreshStatus() {
  try {
    const statuses = await api("/api/status");
    for (const status of statuses) {
      const card = document.querySelector("[data-instance-id='" + CSS.escape(status.id) + "']");
      if (!card) continue;
      const healthy = status.endpoint.state === "healthy";
      const statusNode = card.querySelector(".live-status");
      if (statusNode) {
        statusNode.textContent = healthy
          ? "Healthy"
          : "Stopped / unavailable";
        statusNode.classList.toggle("healthy", healthy);
        statusNode.classList.toggle("unhealthy", !healthy);
      }
      card.classList.toggle("is-healthy", healthy);
      const deploy = card.querySelector("[data-action='start']");
      const stop = card.querySelector("[data-action='stop']");
      if (deploy) deploy.hidden = healthy;
      if (stop) stop.hidden = !healthy;
    }
  } catch (error) {
    document.querySelector("#output").textContent = "Status check failed: " + error.message;
  }
}

loadPage();
setInterval(refreshStatus, 5000);
