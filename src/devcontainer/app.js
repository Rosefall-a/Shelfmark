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
    document.querySelector("#last-action").textContent = "Environment saved. Rebuild/restart a stack to apply it.";
  } catch (error) {
    document.querySelector("#env-state").textContent = "Save failed";
    document.querySelector("#output").textContent = error.message;
  } finally {
    setBusy(b, false, "Save environment");
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

function editInstance(instance) {
  document.querySelector("#instance-id").value = instance.id;
  document.querySelector("#instance-name").value = instance.name;
  document.querySelector("#instance-env").value = instance.environment;
  document.querySelector("#instance-project").value = instance.project;
  document.querySelector("#instance-port").value = instance.port;
  document.querySelector("#instance-mode").value = instance.build_mode || "source";
  document.querySelector("#instance-tag").value = instance.tag || "main";
  document.querySelector("#save-instance").textContent = "Save instance";
  
}

function clearInstanceForm() {
  document.querySelector("#instance-form").reset();
  document.querySelector("#instance-id").value = "";
  document.querySelector("#instance-tag").value = "main";
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
      id: value("#instance-id") || value("#instance-project"),
      name: value("#instance-name"),
      environment: value("#instance-env"),
      project: value("#instance-project"),
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

function actionButton(instance, action, label) {
  const b = document.createElement("button");
  b.textContent = label;
  b.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    setBusy(b, true, label);
    document.querySelector("#last-action").textContent = label + " " + instance.name + "…";
    document.querySelector("#output").textContent = "Docker is working. A fresh build can take a while.";
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
    [["start","Start"],["rebuild","Rebuild & restart"],["stop","Stop"],["reset","Reset"],["status","Status"],["health","Health"],["logs","Logs"]]
      .forEach(([action, label]) => actions.appendChild(actionButton(instance, action, label)));
    const edit = document.createElement("button");
    edit.textContent = "Edit";
    edit.addEventListener("click", () => editInstance(instance));
    actions.appendChild(edit);
    const remove = document.createElement("button");
    remove.textContent = "Remove";
    remove.addEventListener("click", () => deleteInstance(instance.id));
    actions.appendChild(remove);
    section.append(title, summary, actions);
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

function toggleImageFields() {
  const prod = value("#instance-env") === "prod";
  const remote = value("#instance-mode") === "image";
  document.querySelector("#image-field").hidden = !prod;
  document.querySelector("#backend-image-field").hidden = prod || !remote;
  document.querySelector("#frontend-image-field").hidden = prod || !remote;
  document.querySelector("#instance-image").required = prod && remote;
  document.querySelector("#instance-backend-image").required = !prod && remote;
  document.querySelector("#instance-frontend-image").required = !prod && remote;
}

document.querySelector("#save-env").addEventListener("click", saveEnvironment);
document.querySelector("#build-images").addEventListener("click", buildImages);
document.querySelector("#instance-form").addEventListener("submit", saveInstance);
document.querySelector("#cancel-instance").addEventListener("click", clearInstanceForm);
document.querySelector("#instance-env").addEventListener("change", toggleImageFields);

Promise.all([api("/api/environment"), api("/api/instances")]).then(([env, instances]) => {
  loadEnvironment(env);
  render(instances);
}).catch(error => { document.querySelector("#output").textContent = error.message; });
setInterval(refresh, 5000);
