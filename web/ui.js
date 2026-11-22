const paths = {
  logo: '<path d="M4 19h16M6 15v-4m4 4V6m4 9V9m4 6V4" stroke-width="2.4"/>',
  overview: '<rect x="3" y="3" width="7" height="7" rx="1.4"/><rect x="14" y="3" width="7" height="7" rx="1.4"/><rect x="3" y="14" width="7" height="7" rx="1.4"/><rect x="14" y="14" width="7" height="7" rx="1.4"/>',
  box: '<path d="M12 3 3.5 7.5v9L12 21l8.5-4.5v-9L12 3Zm0 18V12m8.5-4.5L12 12 3.5 7.5M8 5.1l8 4.3"/>',
  pivot: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18m-12 0v11m6-11v11M3 14.5h18"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="m9.7 3-.7 2.4-2 .9-2.2-.9-2 3.5 1.8 1.6v2.3L2.8 14l2 3.5 2.3-.7 2 .9.6 2.3h4.2l.7-2.3 2-.9 2.2.7 2-3.5-1.8-1.5v-2.3l1.8-1.6-2-3.5-2.2.9-2-.9L13.9 3Z"/>',
  logout: '<path d="M10 4H5v16h5m5-12 4 4-4 4m-6-4h10"/>',
  "chevron-right": '<path d="m9 6 6 6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
  pin: '<path d="M19 10c0 5-7 10-7 10S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5Zm9 9-9 5-9-5m18 4-9 5-9-5"/>',
  dollar: '<path d="M12 3v18m4-14H9a3 3 0 1 0 0 6h6a3 3 0 1 1 0 6H7"/>',
  bag: '<path d="M5 8h14l1 12H4L5 8Zm4 0V6a3 3 0 0 1 6 0v2"/>',
  alert: '<path d="m10.3 4.7-7 12a2 2 0 0 0 1.7 3h14a2 2 0 0 0 1.7-3l-7-12a2 2 0 0 0-3.4 0ZM12 9v4m0 3h.01"/>',
  check: '<path d="m5 12 4 4 10-10"/>',
  refresh: '<path d="M20 4v6h-6m-10 10v-6h6M5 9a7 7 0 0 1 11-4l4 5M4 14l4 5a7 7 0 0 0 11-4"/>',
  swap: '<path d="M4 8h16m-4-4 4 4-4 4M20 16H4m4-4-4 4 4 4"/>',
  graph: '<path d="M4 4v16h16M8 15l4-5 3 3 5-7"/>',
  trend: '<path d="m3 16 7-7 4 4 7-7m-5 0h5v5"/>',
};
export function icon(name, size = 19) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ""}</svg>`;
}
export const $ = (selector, base = document) => base.querySelector(selector);
export const $$ = (selector, base = document) => [...base.querySelectorAll(selector)];
export function safe(text) {
  return String(text ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[char]);
}
const integer = new Intl.NumberFormat("en-CA");
const cad = new Intl.NumberFormat("en-CA", {style: "currency", currency: "CAD", maximumFractionDigits: 0});
const exactCad = new Intl.NumberFormat("en-CA", {style: "currency", currency: "CAD"});
const compactCad = new Intl.NumberFormat("en-CA", {style: "currency", currency: "CAD", notation: "compact", maximumFractionDigits: 1});
const day = new Intl.DateTimeFormat("en-CA", {month: "short", day: "numeric", year: "numeric", timeZone: "UTC"});
const month = new Intl.DateTimeFormat("en-CA", {month: "short", year: "numeric", timeZone: "UTC"});
export const number = value => integer.format(value);
export const money = value => exactCad.format(value);
export const kpiMoney = value => cad.format(value);
export const shortMoney = value => compactCad.format(value);
export const dateLabel = value => value ? day.format(new Date(value + "T00:00:00Z")) : "—";
export const monthLabel = value => month.format(new Date(value + "-01T00:00:00Z"));
export const capitalize = value => value.charAt(0).toUpperCase() + value.slice(1);

export function table(headers, rows, empty = "No records match these filters.") {
  if (!rows.length) return `<div class="empty">${safe(empty)}</div>`;
  return `<div class="table-scroll"><table><thead><tr>${headers.map(header => `<th scope="col">${safe(header)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

export function cardTitle(title, subtitle, extra = "") {
  return `<header class="card-heading"><div><h2>${safe(title)}</h2><p>${safe(subtitle)}</p></div>${extra}</header>`;
}

export function metric(label, value, detail, symbol, color, delta = null) {
  return `<article class="card metric"><div class="metric-top"><span>${safe(label)}</span><span class="metric-icon ${color}">${icon(symbol, 18)}</span></div>
    <strong class="metric-value">${safe(value)}</strong><div class="metric-detail">
    ${delta === null ? "" : `<span class="delta ${delta < 0 ? "negative" : ""}">${delta > 0 ? "+" : ""}${delta.toFixed(1)}%</span>`}
    ${safe(detail)}</div></article>`;
}
