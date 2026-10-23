const auth = document.getElementById("auth");
const list = document.getElementById("list");
const projectScreen = document.getElementById("project");
const authForm = document.getElementById("auth-form");
const authTitle = document.getElementById("auth-title");
const authSwitch = document.getElementById("auth-switch");
let registering = false;
let current = null;
let files = [];

authSwitch.addEventListener("click", () => {
  registering = !registering;
  authTitle.textContent = registering ? "Новый аккаунт" : "Вход";
  authForm.querySelector("button").textContent = registering ? "Создать и войти" : "Войти";
  authSwitch.textContent = registering ? "У меня уже есть аккаунт" : "Создать аккаунт";
});

document.getElementById("show-token").addEventListener("change", (event) => {
  document.querySelector("#create-form [name=token]").type = event.target.checked ? "text" : "password";
});

document.getElementById("logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST", body: "{}" });
  showAuth();
});

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(authForm));
  try {
    await api(registering ? "/api/register" : "/api/login", { method: "POST", body: JSON.stringify(body) });
    await showList();
  } catch (error) {
    document.getElementById("auth-error").textContent = error.message;
  }
});

document.getElementById("create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const body = Object.fromEntries(new FormData(form));
  document.getElementById("create-error").textContent = "Сохраняю и читаю структуру…";
  try {
    const project = await api("/api/projects", { method: "POST", body: JSON.stringify(body) });
    form.reset();
    document.querySelector("#create-form [name=token]").type = "password";
    document.getElementById("create-error").textContent = "";
    await openProject(project.id);
  } catch (error) {
    document.getElementById("create-error").textContent = error.message;
  }
});

document.getElementById("back").addEventListener("click", () => showList());

document.getElementById("replace-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = new FormData(event.target).get("token");
  if (!token) {
    return;
  }
  try {
    current = await api(`/api/projects/${current.id}`, {
      method: "PATCH",
      body: JSON.stringify({ token }),
    });
    event.target.reset();
    renderProject();
  } catch (error) {
    document.getElementById("project-error").textContent = error.message;
  }
});

document.getElementById("filter").addEventListener("input", () => renderTree());

document.getElementById("entry-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const entry = new FormData(event.target).get("entry");
  await saveEntry(String(entry || ""));
});

document.getElementById("trace").addEventListener("click", async () => {
  document.getElementById("project-error").textContent = "Строю карту. Для этого код скачивается целиком.";
  try {
    await api(`/api/projects/${current.id}/trace`, { method: "POST", body: "{}" });
    window.location.href = `/p/${current.id}/viewer/`;
  } catch (error) {
    document.getElementById("project-error").textContent = error.message;
  }
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function showAuth() {
  auth.hidden = false;
  list.hidden = true;
  projectScreen.hidden = true;
  document.getElementById("who").textContent = "";
  document.getElementById("logout").hidden = true;
}

async function showList() {
  const me = await api("/api/me");
  document.getElementById("who").textContent = me.username;
  document.getElementById("logout").hidden = false;
  const payload = await api("/api/projects");
  const box = document.getElementById("projects");
  box.replaceChildren();
  payload.projects.forEach((project) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = project.name;
    button.addEventListener("click", () => openProject(project.id));
    item.append(button);
    box.append(item);
  });
  auth.hidden = true;
  projectScreen.hidden = true;
  list.hidden = false;
}

async function openProject(id) {
  current = await api(`/api/projects/${id}`);
  document.getElementById("project-error").textContent = "Загружаю список файлов…";
  try {
    const tree = await api(`/api/projects/${id}/tree`, { method: "POST", body: "{}" });
    files = tree.files;
    document.getElementById("project-error").textContent = "";
  } catch (error) {
    files = [];
    document.getElementById("project-error").textContent = error.message;
  }
  renderProject();
  auth.hidden = true;
  list.hidden = true;
  projectScreen.hidden = false;
}

function renderProject() {
  document.getElementById("project-name").textContent = current.name;
  document.getElementById("project-url").textContent = current.url;
  document.getElementById("token-state").textContent = current.has_token
    ? "Токен сохранён. Повторно его не показать, можно только заменить."
    : "Токен не задан.";
  const entry = current.entries[0] || "";
  document.querySelector("#entry-form [name=entry]").value = entry;
  document.getElementById("entry-state").textContent = entry ? `Текущая точка: ${entry}` : "Точка входа ещё не выбрана.";
  document.getElementById("code").replaceChildren();
  document.getElementById("file-title").textContent = "Файл";
  renderTree();
}

function renderTree() {
  const query = document.getElementById("filter").value.trim().toLowerCase();
  const visible = files.filter((file) => file.toLowerCase().includes(query));
  const root = { dirs: {}, files: [] };
  visible.forEach((file) => {
    const parts = file.split("/");
    let node = root;
    parts.slice(0, -1).forEach((part) => {
      node.dirs[part] = node.dirs[part] || { dirs: {}, files: [] };
      node = node.dirs[part];
    });
    node.files.push({ name: parts[parts.length - 1], path: file });
  });
  const box = document.getElementById("tree");
  box.replaceChildren(renderNode(root));
}

function renderNode(node) {
  const wrapper = document.createElement("div");
  Object.keys(node.dirs).sort().forEach((name) => {
    const details = document.createElement("details");
    details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = name;
    details.append(summary, renderNode(node.dirs[name]));
    wrapper.append(details);
  });
  node.files.forEach((file) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "file";
    button.textContent = file.name;
    button.addEventListener("click", () => loadFile(file.path));
    wrapper.append(button);
  });
  return wrapper;
}

async function loadFile(path) {
  document.getElementById("file-title").textContent = path;
  document.getElementById("project-error").textContent = "";
  try {
    const payload = await api(`/api/projects/${current.id}/file?path=${encodeURIComponent(path)}`);
    const code = document.getElementById("code");
    code.replaceChildren();
    payload.text.split("\n").forEach((line, index) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "line";
      row.textContent = line.length ? line : " ";
      row.addEventListener("click", async () => {
        document.querySelectorAll(".line.active").forEach((item) => item.classList.remove("active"));
        row.classList.add("active");
        await saveEntry(`${path}:${index + 1}`);
      });
      code.append(row);
    });
  } catch (error) {
    document.getElementById("project-error").textContent = error.message;
  }
}

async function saveEntry(entry) {
  try {
    current = await api(`/api/projects/${current.id}/entry`, {
      method: "PUT",
      body: JSON.stringify({ entry }),
    });
    document.querySelector("#entry-form [name=entry]").value = current.entries[0] || "";
    document.getElementById("entry-state").textContent = `Текущая точка: ${current.entries[0] || ""}`;
    document.getElementById("project-error").textContent = "";
  } catch (error) {
    document.getElementById("project-error").textContent = error.message;
  }
}

showList().catch(() => showAuth());
