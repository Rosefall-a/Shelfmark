let token = document.querySelector('meta[name="devcontainer-token"]').content;

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
      "X-Devcontainer-Token": token
    }
  });
  return response.json();
}

function button(environment, action, label) {
  const b = document.createElement("button");
  b.textContent = label;
  b.addEventListener("click", async () => {
    const result = await api("/api/action", {
      method: "POST",
      body: JSON.stringify({environment, action})
    });
    document.querySelector("#last-action").textContent =
      result.ok === false ? "Action failed." : "Action completed.";
    document.querySelector("#output").textContent = result.output || result.error || "";
    await refresh();
  });
  return b;
}

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
  render(await api("/api/status"));
}

refresh();
setInterval(refresh, 5000);
