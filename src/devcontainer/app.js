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

function button(environment, action, label) {
  const b = document.createElement("button");
  b.textContent = label;
  b.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    setBusy(b, true, label);
    document.querySelector("#last-action").textContent =
      `${label} ${environment === "prod" ? "Production-like" : "Development"}…`;
    document.querySelector("#output").textContent = "The Docker operation is running. Please wait…";
    try {
      const result = await api("/api/action", {
        method: "POST",
        body: JSON.stringify({environment, action})
      });
      document.querySelector("#last-action").textContent = result.ok === false ? "Action failed." : "Action completed.";
      document.querySelector("#output").textContent = result.output || result.error || "";
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

function value(id) { return document.querySelector(id).value; }

function loadEnvironment(env) {
  document.querySelector("#env-db-user").value = env.db_user || "";
  document.querySelector("#env-db-password").value = env.db_password || "";
  document.querySelector("#env-db-name").value = env.db_name || "";
  document.querySelector("#env-secret").value = env.secret_key || "";
  document.querySelector("#env-admin-user").value = env.admin_username || "";
  document.querySelector("#env-admin-email").value = env.admin_email || "";
  document.querySelector("#env-admin-password").value = env.admin_password || "";
  document.querySelector("#env-secure").value = String(env.auth_cookie_secure);
  document.querySelector("#env-state").textContent = "Loaded";
}

async function loadConfig() {
  loadEnvironment(await api("/api/environment"));
}

async function saveEnvironment() {
  const b = document.querySelector("#save-env");
  setBusy(b, true, "Save environment");
  document.querySelector("#env-state").textContent = "Saving…";
  try {
    const result = await api("/api/environment", {
      method: "PUT",
      body: JSON.stringify({
        db_user: value("#env-db-user"), db_password: value("#env-db-password"),
        db_name: value("#env-db-name"), secret_key: value("#env-secret"),
        admin_username: value("#env-admin-user"), admin_email: value("#env-admin-email"),
        admin_password: value("#env-admin-password"), auth_cookie_secure: value("#env-secure") === "true"
      })
    });
    loadEnvironment(result);
    document.querySelector("#last-action").textContent = "Environment saved. Restart a stack to apply it.";
  } catch (error) {
    document.querySelector("#env-state").textContent = "Save failed";
    document.querySelector("#last-action").textContent = "Environment save failed.";
    document.querySelector("#output").textContent = error.message;
  } finally {
    setBusy(b, false, "Save environment");
  }
}

document.querySelector("#save-env").addEventListener("click", saveEnvironment);

function render(data) {
  const root = document.querySelector("#stacks");
  root.replaceChildren();
  for (const [environment, stack] of Object.entries(data)) {
    const section = document.createElement("section");
    section.className = "stack";
    const title = document.createElement("h2");
    title.textContent = stack.name;
    const summary = document.createElement("div");
    summary.className = "status";
    summary.textContent =
      "Compose: " + (stack.compose_valid ? "valid" : "failed") +
      "\nEndpoint: " + stack.endpoint.state +
      "\nURL: " + stack.endpoint_url +
      "\nProject: " + stack.project;
    const actions = document.createElement("div");
    actions.className = "actions";
    for (const [action, label] of [
      ["start", "Start"], ["stop", "Stop"], ["reset", "Reset"],
      ["status", "Status"], ["health", "Health"], ["logs", "Logs"]
    ]) actions.appendChild(button(environment, action, label));
    section.append(title, summary, actions);
    root.appendChild(section);
  }
}

async function refresh() {
  try { render(await api("/api/status")); }
  catch (error) {
    document.querySelector("#last-action").textContent = "Unable to read environment status.";
    document.querySelector("#output").textContent = error.message;
  }
}

loadConfig();
refresh();
setInterval(refresh, 5000);
