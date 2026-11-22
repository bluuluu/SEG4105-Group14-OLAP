import {money, monthLabel, number, shortMoney} from "./ui.js";

export function salesChart(canvas, tooltip, trend) {
  const context = canvas.getContext("2d");
  const wrap = canvas.parentElement;
  const values = trend.map(row => row.net_sales);
  let active = null;
  let points = [];
  let bounds;

  function draw() {
    const {width, height} = wrap.getBoundingClientRect();
    if (!width || !height) return;
    const pixelRatio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.scale(pixelRatio, pixelRatio);
    const left = 58, right = width - 13, top = 13, bottom = height - 32;
    bounds = {top, bottom};
    const peak = Math.max(...values, 1);
    const stepMagnitude = 10 ** Math.floor(Math.log10(peak / 4));
    const step = Math.ceil(peak / 4 / stepMagnitude) * stepMagnitude;
    const scale = step * 4;
    context.font = "12px system-ui";
    for (let tick = 0; tick <= 4; tick++) {
      const y = bottom - (bottom - top) * tick / 4;
      context.strokeStyle = "#e8eaf2";
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(right, y);
      context.stroke();
      context.fillStyle = "#657189";
      context.textAlign = "right";
      context.textBaseline = "middle";
      context.fillText(shortMoney(step * tick), left - 9, y);
    }
    points = values.map((value, index) => ({
      x: values.length === 1 ? (left + right) / 2 : left + (right - left) * index / (values.length - 1),
      y: bottom - (bottom - top) * value / scale,
    }));

    const labelEvery = Math.max(1, Math.ceil((points.length - 1) / Math.max(1, Math.floor((right - left) / 46))));
    points.forEach((point, index) => {
      if (index % labelEvery !== 0 && index !== points.length - 1) return;
      if (index % labelEvery !== 0 && index % labelEvery < labelEvery / 2) return;
      context.textBaseline = "top";
      context.textAlign = index === 0 ? "left" : index === points.length - 1 ? "right" : "center";
      context.fillText(monthLabel(trend[index].period).split(" ")[0], point.x, bottom + 12);
    });

    const gradient = context.createLinearGradient(0, top, 0, bottom);
    gradient.addColorStop(0, "rgba(97, 76, 226, .24)");
    gradient.addColorStop(1, "rgba(97, 76, 226, .025)");
    const first = points[0], last = points.at(-1);
    function trace() {
      context.beginPath();
      context.moveTo(first.x, first.y);
      for (let index = 1; index < points.length; index++) {
        const previous = points[index - 1], next = points[index];
        const mid = (previous.x + next.x) / 2;
        context.bezierCurveTo(mid, previous.y, mid, next.y, next.x, next.y);
      }
    }
    trace();
    context.lineTo(last.x, bottom);
    context.lineTo(first.x, bottom);
    context.closePath();
    context.fillStyle = gradient;
    context.fill();
    trace();
    context.lineWidth = 2.8;
    context.strokeStyle = "#604be4";
    context.stroke();

    if (points.length === 1 || active !== null) {
      const point = points[active ?? 0];
      if (active !== null) {
        context.beginPath();
        context.setLineDash([4, 4]);
        context.lineWidth = 1;
        context.strokeStyle = "#9a8cef";
        context.moveTo(point.x, top);
        context.lineTo(point.x, bottom);
        context.stroke();
        context.setLineDash([]);
      }
      context.beginPath();
      context.arc(point.x, point.y, 4.5, 0, 2 * Math.PI);
      context.fillStyle = "#604be4";
      context.fill();
      context.lineWidth = 2;
      context.strokeStyle = "white";
      context.stroke();
    }
  }

  function pointTo(event) {
    const box = canvas.getBoundingClientRect();
    const x = event.clientX - box.left;
    if (!bounds || !points.length) return;
    active = points.reduce((best, point, index) =>
      Math.abs(point.x - x) < Math.abs(points[best].x - x) ? index : best, 0);
    const row = trend[active];
    tooltip.textContent = `${monthLabel(row.period)} · ${money(row.net_sales)} · ${number(row.units_sold)} units`;
    tooltip.hidden = false;
    const point = points[active];
    tooltip.style.left = `${Math.max(4, Math.min(point.x + 10, box.width - tooltip.offsetWidth - 4))}px`;
    tooltip.style.top = `${Math.max(0, point.y - 30)}px`;
    draw();
  }

  const observer = new ResizeObserver(draw);
  observer.observe(wrap);
  canvas.addEventListener("pointermove", pointTo);
  canvas.addEventListener("pointerleave", () => {
    active = null;
    tooltip.hidden = true;
    draw();
  });
  draw();
  return () => observer.disconnect();
}
