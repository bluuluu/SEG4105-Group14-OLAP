import {$, $$, capitalize, dateLabel, icon, safe} from "./ui.js";
import {salesChart} from "./charts.js";
import {adminView, axes, children, cubeControls, cubeResults, inventory, metricKeys, overview, parents, timeAxes} from "./views.js";

const pages = {
  sales: ["Overview", "Sales overview", "Monitor sales performance and inventory across your retail network."],
  inventory: ["Inventory", "Inventory", "Review stock levels and product–store positions below their reorder point."],
  cube: ["OLAP explorer", "OLAP explorer", "Slice, compare, and drill into sales or inventory across dimensions."],
  admin: ["Administration", "Administration", "Review data refreshes and manage account access."],
};
const dimensions = {region: "Region", category: "Category", store: "Store", product: "Product"};
const allValues = {region: "All regions", category: "All categories", store: "All stores", product: "All products"};
const defaultCube = {fact: "sales", metric: "net_sales", rows: "month", columns: ""};
const state = {
  user: null, page: "sales", metadata: null, filters: null, cube: {...defaultCube},
  history: [], editing: null, users: [], runs: [],
};
let pending;
let stopChart = () => {};

async function api(path, options = {}) {
  const {method, body, signal} = options;
  const response = await fetch(path, {
    method, signal,
    headers: body ? {"Content-Type": "application/json"} : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 204) return;
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && state.user) showLogin("Your session ended. Sign in again to continue.");
    const message = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(" ") : data.detail;
    const error = new Error(message || "The request could not be completed.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function showLogin(message = "") {
  pending?.abort();
  stopChart();
  state.user = null;
  state.metadata = null;
  state.filters = null;
  state.editing = null;
  state.history = [];
  state.users = [];
  state.runs = [];
  state.cube = {...defaultCube};
  $("#view").replaceChildren();
  $("#filters").replaceChildren();
  $("#workspace").hidden = true;
  $("#startup").hidden = true;
  $("#login").hidden = false;
  $("#login-form").reset();
  $("#login-form .form-message").textContent = message;
  $("#login-form [name='username']").focus();
}

async function showWorkspace(user) {
  state.user = user;
  $("#startup").hidden = true;
  $("#login").hidden = true;
  $("#workspace").hidden = false;
  $("#username").textContent = user.username;
  $("#role").textContent = user.role === "admin" ? "Administrator" : "Manager";
  $("#avatar").textContent = user.username[0].toUpperCase();
  $("#admin-label").hidden = $("#admin-nav").hidden = user.role !== "admin";
  openPage("sales");
  await loadMetadata();
}

function defaultFilters(metadata) {
  if (!metadata.last_date) return null;
  const end = new Date(metadata.last_date + "T00:00:00Z");
  const start = new Date(end);
  start.setUTCDate(1);
  start.setUTCMonth(start.getUTCMonth() - (end.getUTCDate() === 1 ? 12 : 11));
  return {start: start.toISOString().slice(0, 10) < metadata.first_date ? metadata.first_date : start.toISOString().slice(0, 10),
    end: metadata.last_date, region: [], category: [], store: [], product: []};
}

async function loadMetadata() {
  try {
    const loaded = await api("/api/metadata");
    if (!state.user) return;
    state.metadata = loaded;
    if (!state.filters) state.filters = defaultFilters(loaded);
    const batches = Object.values(loaded.refresh);
    const refreshTimes = batches.map(batch => new Date(batch.finished_at).getTime());
    const fresh = batches.length === 2 && Date.now() - Math.min(...refreshTimes) < 24 * 3600 * 1000;
    const hasRejects = batches.some(batch => batch.status === "loaded_with_rejects");
    let status = "Awaiting data";
    if (batches.length === 1) status = "Partial refresh";
    if (batches.length === 2) status = fresh ? (hasRejects ? "Refreshed with rejects" : "Warehouse refreshed") : "Refresh overdue";
    $("#data-status").innerHTML = `${loaded.demo ? '<span class="demo-label">Demo data</span>' : ""}
      <span class="status ${fresh && !hasRejects ? "fresh" : "stale"}" title="${safe(batches.length
        ? batches.map(batch => `${capitalize(batch.name)} ${new Date(batch.finished_at).toLocaleString("en-CA")}`).join(" · ")
        : "The warehouse has no completed data load")}">
        <i></i>${status}</span>`;
    renderPage();
  } catch (error) {
    if (state.user) $("#view").innerHTML = `<div class="error-card"><p>${safe(error.message)}</p>
      <button class="button secondary" data-action="reload-data">Retry</button></div>`;
  }
}

function openPage(page) {
  if (page === "admin" && state.user?.role !== "admin") return;
  state.page = page;
  state.editing = null;
  const [crumb, title, description] = pages[page];
  $("#breadcrumb").textContent = crumb;
  $("#page-title").textContent = title;
  $("#page-description").textContent = description;
  for (const item of $$("[data-nav]")) {
    if (item.dataset.nav === page) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  $("#page-actions").innerHTML = ({
    sales: '<button class="button primary" data-explore="sales">Explore sales</button>',
    inventory: '<button class="button primary" data-explore="inventory">Explore inventory</button>',
    cube: "",
    admin: `<button class="button secondary" data-action="reload-admin">${icon("refresh", 16)} Refresh status</button>`,
  })[page];
  renderPage();
}

function dimensionBox(name, choices, values, symbol) {
  const count = values.length;
  return `<details class="facet" data-dimension="${name}">
    <summary>${icon(symbol, 16)}<span data-facet-label>${count ? `${count} selected` : allValues[name]}</span>${icon("down", 13)}</summary>
    <div class="facet-options"><strong>${dimensions[name]}</strong>${choices.length ? choices.map(([key, label]) => `
      <label><input type="checkbox" name="${name}" value="${safe(key)}" ${values.includes(key) ? "checked" : ""}>
      <span>${safe(label)}</span></label>`).join("") : '<small>No values available</small>'}</div>
    </details>`;
}

function renderFilters() {
  const target = $("#filters");
  const filters = state.filters;
  if (state.page === "admin" || !filters) {
    target.replaceChildren();
    return;
  }
  const m = state.metadata;
  target.innerHTML = `<form id="filter-form" class="card filters">
    <div class="date-range">
      <span class="field-caption">${icon("calendar", 16)} Date range</span>
      <div><input aria-label="Start date" type="date" name="start" value="${safe(filters.start)}" required>
        <span>to</span><input aria-label="End date" type="date" name="end" value="${safe(filters.end)}" required></div>
    </div>
    <div class="filter-field"><span class="field-caption">Region</span>
      ${dimensionBox("region", m.regions.map(value => [value, value]), filters.region, "pin")}</div>
    <div class="filter-field"><span class="field-caption">Category</span>
      ${dimensionBox("category", m.categories.map(value => [value, value]), filters.category, "layers")}</div>
    <div class="filter-actions">
      <button class="button secondary" type="button" data-action="reset-filters">Reset</button>
      <button class="button primary" type="submit">Apply filters</button>
    </div>
    <details class="more-filters" ${filters.store.length || filters.product.length ? "open" : ""}>
      <summary>Store and product filters ${icon("down", 13)}</summary>
      <div class="more-fields">
        <div class="filter-field"><span class="field-caption">Store</span>
          ${dimensionBox("store", m.stores.map(item => [item.id, item.name]), filters.store, "pin")}</div>
        <div class="filter-field"><span class="field-caption">Product</span>
          ${dimensionBox("product", m.products.map(item => [item.id, item.name]), filters.product, "box")}</div>
      </div>
    </details>
    <p class="form-message" role="alert"></p>
  </form>`;
}

function queryParams() {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(state.filters)) {
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  if (state.page === "cube") {
    for (const [key, value] of Object.entries(state.cube)) if (value) query.set(key, value);
  }
  return query;
}

async function renderPage({keepFilters = false} = {}) {
  const focusedControl = document.activeElement?.closest(".cube-controls select")?.name;
  pending?.abort();
  stopChart();
  const current = new AbortController();
  pending = current;
  const {signal} = current;
  if (!keepFilters) renderFilters();
  const view = $("#view");
  const page = state.page;
  if (page !== "admin" && !state.filters) {
    view.innerHTML = state.metadata
      ? '<div class="empty card data-empty"><h2>No data loaded yet</h2><p>Load a batch to open the analytics views.</p><button class="button secondary" data-action="reload-data">Check for data</button></div>'
      : '<div class="loading"><i></i> Opening the warehouse…</div>';
    return;
  }
  view.innerHTML = (page === "cube" ? cubeControls(state.cube, state.history) : "")
    + '<div id="result"><div class="loading"><i></i> Loading data…</div></div>';
  if (keepFilters && focusedControl) $(`.cube-controls select[name="${focusedControl}"]`)?.focus();
  try {
    if (page === "admin") {
      const [runs, users] = await Promise.all([api("/api/admin/runs", {signal}), api("/api/admin/users", {signal})]);
      if (signal.aborted) return;
      state.runs = runs;
      state.users = users;
      renderAdmin();
      return;
    }
    const data = await api(`/api/${page}?${queryParams()}`, {signal});
    if (signal.aborted) return;
    $("#result").innerHTML = page === "sales" ? overview(data) : page === "inventory"
      ? inventory(data) : cubeResults(data, state.cube);
    if (page === "sales" && $("#sales-chart")) {
      stopChart = salesChart($("#sales-chart"), $("#chart-tooltip"), data.trend);
    }
  } catch (error) {
    if (!signal.aborted) $("#result").innerHTML = `<div class="error-card"><p>${safe(error.message)}</p>
      <button class="button secondary" data-action="retry-view">Retry</button></div>`;
  }
}

function renderAdmin() {
  $("#view").innerHTML = adminView(state.runs, state.users, state.editing, state.user.username);
}

function countLabel(facet) {
  const count = $$("input:checked", facet).length;
  $("[data-facet-label]", facet).textContent = count ? `${count} selected` : allValues[facet.dataset.dimension];
}

function rangeOf(axis, key) {
  if (axis === "day") return [key, key];
  const year = Number(key.slice(0, 4));
  let month = 1, length = 12;
  if (axis === "month") {
    month = Number(key.slice(5));
    length = 1;
  } else if (axis === "quarter") {
    month = 1 + 3 * (Number(key.slice(6)) - 1);
    length = 3;
  }
  const last = new Date(0);
  last.setUTCFullYear(year, month + length - 1, 0);
  return [`${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-01`, last.toISOString().slice(0, 10)];
}

function drill(axis, key, label) {
  const child = children[axis];
  if (!child) return;
  state.history.push({cube: {...state.cube}, filters: {...state.filters}, label});
  if (timeAxes.includes(axis)) {
    const [start, end] = rangeOf(axis, key);
    state.filters.start = start > state.filters.start ? start : state.filters.start;
    state.filters.end = end < state.filters.end ? end : state.filters.end;
  } else {
    state.filters[axis] = [key];
  }
  state.cube.rows = child;
  if (state.cube.columns === child) state.cube.columns = "";
}

function unwind(index) {
  const step = state.history[index];
  state.history = state.history.slice(0, index);
  state.cube = step.cube;
  state.filters = step.filters;
}

function explore(fact) {
  state.cube = fact === "sales" ? {...defaultCube} : {fact, metric: "stock", rows: "category", columns: ""};
  state.history = [];
}

for (const item of $$("[data-icon]")) item.innerHTML = icon(item.dataset.icon);

$("#login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = $("button", form), message = $(".form-message", form);
  const data = Object.fromEntries(new FormData(form));
  data.username = data.username.trim().toLowerCase();
  button.disabled = true;
  message.textContent = "";
  try {
    await showWorkspace(await api("/api/login", {method: "POST", body: data}));
    form.reset();
  } catch (error) {
    if (!state.user) message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("#sign-out").addEventListener("click", async () => {
  const button = $("#sign-out");
  button.disabled = true;
  try {
    await api("/api/logout", {method: "POST"});
    showLogin();
  } catch (error) {
    button.title = error.message;
  } finally {
    button.disabled = false;
  }
});

$("#workspace").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.target;
  const fields = new FormData(form);
  const message = $(".form-message", form);
  if (form.id === "filter-form") {
    const start = fields.get("start"), end = fields.get("end");
    if (start > end) {
      message.textContent = "Start date must be on or before end date.";
      return;
    }
    state.filters = {start, end, ...Object.fromEntries(Object.keys(dimensions).map(name => [name, fields.getAll(name)]))};
    state.history = [];
    renderPage();
  } else if (form.id === "user-form") {
    const name = state.editing;
    const own = name === state.user.username;
    const body = {role: own ? "admin" : fields.get("role")};
    if (name) body.enabled = own || fields.has("enabled");
    else body.username = fields.get("username");
    if (fields.get("password")) body.password = fields.get("password");
    const button = $("[type='submit']", form);
    button.disabled = true;
    message.textContent = "";
    try {
      await api(name ? `/api/admin/users/${encodeURIComponent(name)}` : "/api/admin/users",
        {method: name ? "PUT" : "POST", body});
      if (own && body.password) showLogin("Password updated. Sign in with your new password.");
      else if (state.page === "admin" && state.user) {
        state.editing = null;
        renderPage();
      }
    } catch (error) {
      message.textContent = error.message;
      button.disabled = false;
    }
  }
});

$("#workspace").addEventListener("change", event => {
  const {target} = event;
  const facet = target.closest(".facet");
  if (facet) countLabel(facet);
  if (!target.closest(".cube-controls")) return;
  const name = target.name;
  state.cube[name] = target.value;
  if (name === "fact") {
    state.cube.metric = metricKeys[target.value][0];
    if (target.value === "inventory") {
      if (timeAxes.includes(state.cube.rows)) state.cube.rows = "category";
      if (timeAxes.includes(state.cube.columns) || state.cube.columns === state.cube.rows) state.cube.columns = "";
    }
  }
  if (name === "fact" || name === "rows") state.history = [];
  if (name === "metric") {
    for (const entry of state.history) entry.cube.metric = state.cube.metric;
  }
  if (name === "columns") {
    for (const entry of state.history) entry.cube.columns = state.cube.columns !== entry.cube.rows ? state.cube.columns : "";
  }
  renderPage({keepFilters: true});
});

$("#workspace").addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  const {nav, action, drill: drillKey, label, undo, explore: dataset, scope, value, edit} = button.dataset;
  if (nav) {
    openPage(nav);
  } else if ((dataset || scope) && state.filters) {
    explore(dataset || "sales");
    if (scope) {
      state.cube.rows = scope;
      drill(scope, value, value);
    }
    openPage("cube");
  } else if (edit !== undefined) {
    state.editing = edit;
    renderAdmin();
    $("#user-form input")?.focus();
  } else if (action === "cancel-edit") {
    state.editing = null;
    renderAdmin();
  } else if (action === "reload-data") {
    loadMetadata();
  } else if (action === "reload-admin" || action === "retry-view") {
    if (action === "reload-admin") loadMetadata();
    else renderPage();
  } else if (action === "reset-filters") {
    state.filters = defaultFilters(state.metadata);
    state.history = [];
    renderPage();
  } else if (action === "swap") {
    [state.cube.rows, state.cube.columns] = [state.cube.columns, state.cube.rows];
    renderPage({keepFilters: true});
  } else if (action === "roll" || undo !== undefined || drillKey !== undefined) {
    if (drillKey !== undefined) drill(state.cube.rows, drillKey, label);
    else if (state.history.length) unwind(undo === undefined ? state.history.length - 1 : Number(undo));
    else state.cube.rows = parents[state.cube.rows];
    if (state.cube.columns === state.cube.rows) state.cube.columns = "";
    renderPage();
  }
});

document.addEventListener("click", event => {
  for (const popover of $$(".facet[open]")) if (!popover.contains(event.target)) popover.open = false;
});
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  for (const popover of $$(".facet[open]")) {
    popover.open = false;
    $("summary", popover).focus();
  }
});

try {
  await showWorkspace(await api("/api/me"));
} catch (error) {
  showLogin(error.status === 401 ? "" : error.message);
}
