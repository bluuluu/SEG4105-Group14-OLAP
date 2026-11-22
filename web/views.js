import {capitalize, cardTitle, dateLabel, icon, kpiMoney, metric, money, monthLabel, number, safe, table} from "./ui.js";

export const axes = {
  year: "Year", quarter: "Quarter", month: "Month", day: "Day", region: "Region",
  store: "Store", category: "Category", product: "Product",
};
export const measures = {
  net_sales: "Net sales", units_sold: "Units sold", sales_lines: "Sales lines",
  stock: "Stock on hand", below_reorder: "Below reorder point", out_of_stock: "Out of stock",
};
export const metricKeys = {
  sales: ["net_sales", "units_sold", "sales_lines"],
  inventory: ["stock", "below_reorder", "out_of_stock"],
};
export const children = {year: "quarter", quarter: "month", month: "day", region: "store", category: "product"};
export const parents = Object.fromEntries(Object.entries(children).map(([parent, child]) => [child, parent]));
export const timeAxes = ["year", "quarter", "month", "day"];

function change(value, previous) {
  return previous ? (value / previous - 1) * 100 : null;
}

function bar(value, max, color) {
  return `<div class="bar-track"><span class="${color}" style="width:${max ? value / max * 100 : 0}%"></span></div>`;
}

function snapshotLabel(day) {
  return day ? `As of ${dateLabel(day)}` : "No snapshot in this period";
}

export function overview(data) {
  const {totals, previous, trend, regions, categories} = data;
  const [high, second] = [regions[0]?.net_sales || 0, totals.net_sales];
  return `
    <div class="metrics">
      ${metric("Net sales", kpiMoney(totals.net_sales), previous?.net_sales ? "vs. prior period" : "CAD · selected period",
        "dollar", "violet", change(totals.net_sales, previous?.net_sales))}
      ${metric("Units sold", number(totals.units_sold), previous?.units_sold ? "vs. prior period" : "Selected period",
        "bag", "blue", change(totals.units_sold, previous?.units_sold))}
      ${metric("Stock on hand", totals.positions ? number(totals.stock) : "—", snapshotLabel(totals.snapshot_date), "box", "teal")}
      ${metric("Below reorder point", totals.positions ? number(totals.below_reorder) : "—",
        "Product–store positions", "alert", "orange")}
    </div>
    <div class="charts">
      <section class="card chart-panel">
        ${cardTitle("Sales trend", "Monthly net sales across selected stores", '<span class="legend"><i></i> Net sales</span>')}
        ${trend.length ? `<div class="chart-wrap"><canvas id="sales-chart" role="img" aria-label="Line chart of monthly net sales"></canvas>
          <div class="chart-tooltip" id="chart-tooltip" hidden></div></div>
          <details class="chart-details"><summary>View monthly values</summary>
          ${table(["Month", "Net sales", "Units sold"], trend.map(row =>
            [safe(monthLabel(row.period)), money(row.net_sales), number(row.units_sold)]))}</details>`
          : '<div class="empty">No sales in the selected period.</div>'}
      </section>
      <section class="card region-panel">
        ${cardTitle("Sales by region", "Net sales contribution")}
        <div class="region-bars">${regions.length ? regions.map((row, index) => `
          <div class="region-row">
            <div><button class="text-button region-name" data-scope="region" data-value="${safe(row.region)}">${safe(row.region)}</button>
              <strong>${kpiMoney(row.net_sales)}</strong></div>
            ${bar(row.net_sales, high, `shade-${index % 4}`)}
            <small>${second ? (row.net_sales / second * 100).toFixed(1) : "0.0"}% of net sales</small>
          </div>`).join("") : '<div class="empty">No regions in this selection.</div>'}</div>
      </section>
    </div>
    <section class="card table-card">
      ${cardTitle("Category performance", "Sales and product activity by category")}
      ${table(["Category", "Products sold", "Units sold", "Sales lines", "Net sales", "Explore"], categories.map(row => [
        `<span class="table-label">${safe(row.category)}</span>`, number(row.products), number(row.units_sold),
        number(row.sales_lines), money(row.net_sales), `<button class="text-button" data-scope="category"
        data-value="${safe(row.category)}" aria-label="Explore ${safe(row.category)}">View products</button>`
      ]))}
    </section>`;
}

export function inventory({totals, categories, exceptions}) {
  const value = metricName => totals.positions ? number(totals[metricName]) : "—";
  const maxStock = Math.max(...categories.map(row => row.stock), 0);
  return `<div class="metrics">
    ${metric("Stock on hand", value("stock"), snapshotLabel(totals.snapshot_date), "box", "violet")}
    ${metric("Below reorder point", value("below_reorder"), "Stock under the reorder threshold", "alert", "orange")}
    ${metric("Out of stock", value("out_of_stock"), "Positions with zero units", "bag", "blue")}
    ${metric("Tracked positions", number(totals.positions), "Product–store pairs in the snapshot", "layers", "teal")}
  </div>
  <section class="card table-card">
    ${cardTitle("Reorder exceptions", `Product–store positions below threshold · ${snapshotLabel(totals.snapshot_date)}`,
      totals.below_reorder > 100 ? '<span class="tag neutral">Top 100 by shortage</span>' : "")}
    ${table(["Product", "Store", "On hand", "Reorder point", "Shortage"], exceptions.map(row => [
      `<span class="table-label">${safe(row.product_name)}</span><small class="table-sub">${safe(row.category)}</small>`,
      `<span class="table-label">${safe(row.store_name)}</span><small class="table-sub">${safe(row.region)}</small>`,
      number(row.stock_on_hand), number(row.reorder_point), `<span class="tag warning">${number(row.shortage)} units</span>`,
    ]), totals.positions ? "No positions are below their reorder point." : "No inventory positions match this selection.")}
  </section>
  <section class="card table-card inventory-category">
    ${cardTitle("Stock by category", "On-hand units by product category")}
    ${table(["Category", "Distribution", "Units on hand", "Below reorder point"], categories.map((row, index) => [
      `<span class="table-label">${safe(row.category)}</span>`, bar(row.stock, maxStock, `shade-${index % 4}`),
      number(row.stock), number(row.below_reorder),
    ]))}
  </section>`;
}

function options(items, selected) {
  return items.map(([value, label]) =>
    `<option value="${safe(value)}"${selected === value ? " selected" : ""}>${safe(label)}</option>`).join("");
}

export function select(name, label, items, value) {
  return `<label class="select-field">${label}<select name="${name}">${options(items, value)}</select></label>`;
}

export function cubeControls(config, history) {
  const axisOptions = Object.entries(axes).filter(([key]) => config.fact === "sales" || !timeAxes.includes(key));
  return `<section class="card cube-controls">
    ${cardTitle("Query setup", "Choose a measure and one or two dimensions.")}
    <div class="cube-fields">
      ${select("fact", "Dataset", [["sales", "Sales"], ["inventory", "Inventory snapshot"]], config.fact)}
      ${select("metric", "Measure", metricKeys[config.fact].map(key => [key, measures[key]]), config.metric)}
      ${select("rows", "Rows", axisOptions.filter(([key]) => key !== config.columns), config.rows)}
      ${select("columns", "Columns", [["", "None"], ...axisOptions.filter(([key]) => key !== config.rows)], config.columns)}
      <button class="button secondary" data-action="swap" ${config.columns ? "" : "disabled"}>${icon("swap", 16)} Swap axes</button>
      <button class="button secondary" data-action="roll" ${history.length || parents[config.rows] ? "" : "disabled"}>Roll up</button>
    </div>
    ${history.length ? `<div class="drill-trail"><span>Drill path</span>
      ${history.map((entry, index) => `<button class="text-button" data-undo="${index}">${safe(entry.label)}</button>`).join(icon("chevron-right", 13))}
      ${icon("chevron-right", 13)}<strong>${axes[config.rows]}</strong></div>` : ""}
  </section>`;
}

function axisLabel(axis, key, label) {
  return axis === "month" ? monthLabel(key) : axis === "day" ? dateLabel(key) : label;
}

export function cubeResults({cells, snapshot_date}, config) {
  const columns = new Map(), groups = new Map();
  for (const cell of cells) {
    if (!groups.has(cell.row_key)) groups.set(cell.row_key, {label: cell.row_label, values: new Map()});
    const columnKey = cell.column_key ?? "";
    if (!columns.has(columnKey)) columns.set(columnKey, cell.column_label);
    groups.get(cell.row_key).values.set(columnKey, cell.value);
  }
  const format = config.metric === "net_sales" ? money : number;
  const columnKeys = [...columns.keys()].sort((a, b) => config.columns && !timeAxes.includes(config.columns)
    ? columns.get(a).localeCompare(columns.get(b)) || a.localeCompare(b) : a.localeCompare(b));
  const columnTotals = new Map(columnKeys.map(key => [key, 0]));
  let total = 0;

  const rows = [...groups].map(([key, row]) => {
    const label = axisLabel(config.rows, key, row.label);
    const name = children[config.rows]
      ? `<button class="text-button" data-drill="${safe(key)}" data-label="${safe(label)}">${safe(label)} ${icon("chevron-right", 13)}</button>`
      : `<span class="table-label" title="${safe(key)}">${safe(label)}</span>`;
    let rowTotal = 0;
    const values = columnKeys.map(column => {
      const value = row.values.get(column);
      if (value === undefined) return "—";
      rowTotal += value;
      columnTotals.set(column, columnTotals.get(column) + value);
      return format(value);
    });
    total += rowTotal;
    return [name, ...values, ...(config.columns ? [`<strong>${format(rowTotal)}</strong>`] : [])];
  });
  const headers = [axes[config.rows], ...(config.columns
    ? columnKeys.map(key => axisLabel(config.columns, key, columns.get(key))).concat("Total")
    : [measures[config.metric]])];
  if (rows.length) {
    rows.push(["<strong>Total</strong>", ...columnKeys.map(key => `<strong>${format(columnTotals.get(key))}</strong>`),
      ...(config.columns ? [`<strong>${format(total)}</strong>`] : [])]);
  }

  const description = config.fact === "inventory" ? snapshotLabel(snapshot_date)
    : children[config.rows] ? `Select a ${axes[config.rows].toLowerCase()} to drill down.` : "Sales for the selected date range.";
  return `<section class="card table-card cube-results">
    ${cardTitle(measures[config.metric], description, config.columns ? '<span class="tag neutral">Pivot table</span>' : "")}
    ${table(headers, rows)}
  </section>`;
}

const runLabels = {loaded: "Loaded", loaded_with_rejects: "With rejects", failed: "Failed", running: "Running"};
const dateTime = value => value ? new Date(value).toLocaleString("en-CA", {dateStyle: "medium", timeStyle: "short"}) : "—";

export function adminView(runs, users, editing, currentUsername) {
  return `<section class="card table-card">
    ${cardTitle("Batch history", "Recent warehouse loads, rejected rows, and reconciliation.")}
    ${table(["Batch", "Status", "Finished", "Sales lines", "Snapshots", "Rejected", "Details"], runs.map(run => {
      const row = run.summary?.reconciliation;
      const details = Object.entries(run.summary?.sources || {}).map(([source, counts]) =>
        `<li>${safe(capitalize(source))} · ${number(counts.extracted)} extracted · ${number(counts.accepted)} accepted · ${number(counts.rejected)} rejected</li>`
      ).join("");
      return [
        `<span class="table-label">${safe(run.batch_id)}</span><small class="table-sub">Run ${safe(run.run_id)}</small>`,
        `<span class="tag ${run.status === "loaded" ? "success" : run.status === "running" ? "neutral" : "warning"}">
          ${safe(runLabels[run.status])}</span>`, safe(dateTime(run.finished_at)),
        row ? number(row.sales_rows) : "—", row ? number(row.inventory_rows) : "—",
        row ? number(run.summary.rejected) : "—",
        details || run.error ? `<details><summary>View</summary><div class="run-detail">
          <p>Started ${safe(dateTime(run.started_at))}</p>
          ${run.error ? `<p>${safe(run.error)}</p>` : `<ul>${details}</ul><p>Reconciled net sales ${money(row.net_sales)}</p>`}</div></details>` : "—"
      ];
    }), "No batch runs have been recorded.")}
  </section>
  <section class="card table-card users-card">
    ${cardTitle("User access", "Manage dashboard and administrator accounts.",
      '<button class="button primary" data-edit="">Add user</button>')}
    ${table(["Username", "Role", "Status", "Access"], users.map(user => [
      `<span class="table-label">${safe(user.username)}</span>`, safe(capitalize(user.role)),
      `<span class="tag ${user.enabled ? "success" : "neutral"}">${user.enabled ? "Enabled" : "Disabled"}</span>`,
      `<button class="text-button" data-edit="${safe(user.username)}">Edit</button>`
    ]))}
    ${editing === null ? "" : userForm(users.find(user => user.username === editing), currentUsername)}
  </section>`;
}

function userForm(user, currentUsername) {
  const own = user?.username === currentUsername;
  return `<form id="user-form" class="user-form">
    <h3>${user ? `Edit ${safe(user.username)}` : "Create account"}</h3>
    <div>
      ${user ? "" : '<label>Username<input name="username" pattern="[a-z][a-z0-9_.\\-]{2,39}" required autocomplete="off"></label>'}
      ${own ? "" : select("role", "Role", [["manager", "Manager"], ["admin", "Administrator"]], user?.role || "manager")}
      <label>${user ? "New password (optional)" : "Password"}<input type="password" name="password"
        minlength="12" maxlength="128" autocomplete="new-password" ${user ? "" : "required"}></label>
      ${user && !own ? `<label class="checkbox"><input type="checkbox" name="enabled"${user.enabled ? " checked" : ""}> Account enabled</label>` : ""}
    </div>
    <p class="form-message" role="alert"></p>
    <button type="submit" class="button primary">Save account</button>
    <button type="button" class="button secondary" data-action="cancel-edit">Cancel</button>
  </form>`;
}
