import { SENSOR_ORIGIN } from "./protocol.js";

const SENSOR_CONFIG = {
  hc: { field: "distanceCm", kind: "continuous", unit: "cm" },
  pir: { field: "pir", kind: "binary", active: "Detectado", inactive: "No detectado" },
  radar: { field: "radar", kind: "binary", active: "Detectado", inactive: "No detectado" },
  lux: { field: "lux", kind: "continuous", unit: "lux" },
  sound: { field: "sound", kind: "binary", active: "Nivel alto DO", inactive: "Nivel bajo DO" },
};

const numberFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 2 });
const CHART_PADDING = { left: 54, right: 12, top: 14, bottom: 28 };

function sensorConfig(sensor) {
  const config = SENSOR_CONFIG[sensor];
  if (!config) throw new Error(`Sensor desconocido: ${sensor}`);
  return config;
}

export function rowsForSensor(rows, sensor) {
  return rows.filter(row => row.origin === undefined || row.origin === SENSOR_ORIGIN[sensor]);
}

export function buildSeriesSegments(rows, sensor) {
  rows = rowsForSensor(rows, sensor);
  const { field } = sensorConfig(sensor);
  const segments = [];
  let current = [];

  rows.forEach((row, index) => {
    const value = row[field];
    if (value === null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      if (current.length && row.timeMs - current.at(-1).timeMs > 3500) {
        segments.push(current);
        current = [];
      }
      current.push({ index, timeMs: row.timeMs, value });
    }
  });
  if (current.length) segments.push(current);
  return segments;
}

export function calculateSensorStats(rows, sensor) {
  rows = rowsForSensor(rows, sensor);
  const { field, kind } = sensorConfig(sensor);
  if (kind === "continuous") {
    let min = Infinity;
    let max = -Infinity;
    let count = 0;
    for (const row of rows) {
      const value = row[field];
      if (value === null) continue;
      min = Math.min(min, value);
      max = Math.max(max, value);
      count += 1;
    }
    return { count, min: count ? min : null, max: count ? max : null };
  }

  let count = 0;
  let episodes = 0;
  let previous = 0;
  for (const row of rows) {
    const value = row[field];
    if (value === null) {
      previous = 0;
      continue;
    }
    count += 1;
    if (value === 1 && previous !== 1) episodes += 1;
    previous = value;
  }
  return { count, episodes };
}

// A bucket keeps both extrema, so brief peaks and 0/1 events remain visible.
export function downsampleSegment(segment, firstTime, lastTime, pixelWidth) {
  const bucketsCount = Math.max(1, Math.floor(pixelWidth));
  if (segment.length <= bucketsCount * 4) return segment;

  const span = Math.max(1, lastTime - firstTime);
  const buckets = new Map();
  for (const point of segment) {
    const bucketIndex = Math.max(0, Math.min(bucketsCount - 1,
      Math.floor(((point.timeMs - firstTime) / span) * bucketsCount)));
    const bucket = buckets.get(bucketIndex);
    if (!bucket) {
      buckets.set(bucketIndex, { first: point, min: point, max: point, last: point });
      continue;
    }
    if (point.value < bucket.min.value) bucket.min = point;
    if (point.value > bucket.max.value) bucket.max = point;
    bucket.last = point;
  }

  const result = [];
  for (const bucket of buckets.values()) {
    const selected = [bucket.first, bucket.min, bucket.max, bucket.last];
    const unique = [...new Map(selected.map((point) => [point.index, point])).values()];
    unique.sort((a, b) => a.index - b.index);
    result.push(...unique);
  }
  return result;
}

export function formatElapsedTime(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  const base = `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  return hours ? `${String(hours).padStart(2, "0")}:${base}` : base;
}

export function formatChartTime(milliseconds, mode = "elapsed") {
  return mode === "received" ? new Date(milliseconds).toLocaleTimeString("es-CL", { hour12: false }) : formatElapsedTime(milliseconds);
}

function formatValue(value, sensor, enabled) {
  if (value === null) return enabled === false ? "Desactivado" : "Lectura no disponible";
  const config = sensorConfig(sensor);
  if (config.kind === "continuous") return `${numberFormat.format(value)} ${config.unit}`;
  return `${value} · ${value ? config.active : config.inactive}`;
}

function color(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function nearestRowIndex(rows, timeMs) {
  let left = 0;
  let right = rows.length - 1;
  while (left < right) {
    const middle = Math.floor((left + right) / 2);
    if (rows[middle].timeMs < timeMs) left = middle + 1;
    else right = middle;
  }
  if (left > 0 && Math.abs(rows[left - 1].timeMs - timeMs) <= Math.abs(rows[left].timeMs - timeMs)) {
    return left - 1;
  }
  return left;
}

export class SensorCharts {
  constructor({ timeMode = "elapsed" } = {}) {
    this.timeMode = timeMode;
    this.rows = [];
    this.cards = Object.keys(SENSOR_CONFIG).map((sensor) => ({
      sensor,
      canvas: document.querySelector(`#${sensor}-chart`),
      empty: document.querySelector(`#${sensor}-chart-empty`),
      detail: document.querySelector(`#${sensor}-chart-detail`),
      stats: document.querySelector(`#${sensor}-stats`),
      selectedIndex: null,
      rows: [],
    }));
    this.frameRequested = false;

    for (const card of this.cards) {
      card.canvas.addEventListener("pointermove", (event) => this.selectFromPointer(card, event));
      card.canvas.addEventListener("pointerdown", (event) => this.selectFromPointer(card, event));
      card.canvas.addEventListener("keydown", (event) => this.selectFromKeyboard(card, event));
      card.canvas.addEventListener("focus", () => {
        card.detail.setAttribute("aria-live", "polite");
        if (card.rows.length && card.selectedIndex === null) this.select(card, card.rows.length - 1);
      });
      card.canvas.addEventListener("blur", () => card.detail.setAttribute("aria-live", "off"));
    }

    if ("ResizeObserver" in window) {
      this.resizeObserver = new ResizeObserver(() => this.requestDraw());
      for (const card of this.cards) this.resizeObserver.observe(card.canvas.parentElement);
    } else {
      window.addEventListener("resize", () => this.requestDraw());
    }
    this.setRows([]);
  }

  setRows(rows, { resetSelection = false } = {}) {
    this.rows = rows;
    for (const card of this.cards) {
      const previousCapture = card.rows.at(-1)?.captureId;
      card.rows = rowsForSensor(rows, card.sensor);
      if (resetSelection || previousCapture !== card.rows.at(-1)?.captureId || !card.rows.length || card.selectedIndex >= card.rows.length) card.selectedIndex = null;
      const stats = calculateSensorStats(card.rows, card.sensor);
      const config = sensorConfig(card.sensor);
      card.stats.textContent = !stats.count ? "—" : config.kind === "continuous"
        ? `Mín ${numberFormat.format(stats.min)} · Máx ${numberFormat.format(stats.max)}`
        : `${stats.episodes} ${card.sensor === "sound" ? "cambios 0→1" : "episodios"}`;
      card.empty.textContent = card.rows.length ? "Sin lecturas disponibles" : "Sin datos";
      this.updateDetail(card);
    }
    this.requestDraw();
  }

  redraw() {
    this.requestDraw();
  }

  requestDraw() {
    if (this.frameRequested) return;
    this.frameRequested = true;
    requestAnimationFrame(() => {
      this.frameRequested = false;
      for (const card of this.cards) this.draw(card);
    });
  }

  selectFromPointer(card, event) {
    if (!card.rows.length) return;
    const rect = card.canvas.getBoundingClientRect();
    const plotWidth = Math.max(1, rect.width - CHART_PADDING.left - CHART_PADDING.right);
    const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left - CHART_PADDING.left) / plotWidth));
    const firstTime = this.rows[0].timeMs;
    const lastTime = this.rows[this.rows.length - 1].timeMs;
    this.select(card, nearestRowIndex(card.rows, firstTime + fraction * (lastTime - firstTime)));
  }

  selectFromKeyboard(card, event) {
    const moves = { ArrowLeft: -1, ArrowRight: 1 };
    if (!(event.key in moves) && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    if (!card.rows.length) return;
    const lastIndex = card.rows.length - 1;
    const next = event.key === "Home" ? 0 : event.key === "End" ? lastIndex
      : Math.max(0, Math.min(lastIndex, (card.selectedIndex ?? lastIndex) + moves[event.key]));
    this.select(card, next);
  }

  select(card, index) {
    if (card.selectedIndex === index) return;
    card.selectedIndex = index;
    this.updateDetail(card);
    this.requestDraw();
  }

  updateDetail(card) {
    if (card.selectedIndex === null || !card.rows[card.selectedIndex]) {
      card.detail.textContent = "";
      card.detail.hidden = true;
      return;
    }
    card.detail.hidden = false;
    const row = card.rows[card.selectedIndex];
    const value = row[sensorConfig(card.sensor).field];
    const reception = this.timeMode === "received" ? new Date(row.timeMs).toLocaleString("es-CL") : `+${formatElapsedTime(row.timeMs)}`;
    card.detail.textContent = `${row.origin ?? ""} · muestra ${row.sequence ?? card.selectedIndex + 1} · recepción ${reception} · ${formatValue(value, card.sensor, row.enabled?.[card.sensor])}`;
  }

  draw(card) {
    const canvas = card.canvas;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dpr = window.devicePixelRatio || 1;
    const bitmapWidth = Math.round(rect.width * dpr);
    const bitmapHeight = Math.round(rect.height * dpr);
    if (canvas.width !== bitmapWidth || canvas.height !== bitmapHeight) {
      canvas.width = bitmapWidth;
      canvas.height = bitmapHeight;
    }
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, rect.width, rect.height);

    const segments = buildSeriesSegments(card.rows, card.sensor);
    card.empty.hidden = segments.length > 0;
    if (!segments.length) return;

    const config = sensorConfig(card.sensor);
    const stats = calculateSensorStats(card.rows, card.sensor);
    const left = CHART_PADDING.left;
    const right = rect.width - CHART_PADDING.right;
    const top = CHART_PADDING.top;
    const bottom = rect.height - CHART_PADDING.bottom;
    const plotWidth = Math.max(1, right - left);
    const plotHeight = Math.max(1, bottom - top);
    const firstTime = this.rows[0].timeMs;
    const lastTime = this.rows[this.rows.length - 1].timeMs;
    const timeSpan = Math.max(1, lastTime - firstTime);
    const valueRange = config.kind === "binary" ? { min: -0.15, max: 1.15 } : (() => {
      const padding = Math.max(1, (stats.max - stats.min) * 0.08, stats.max === stats.min ? stats.max * 0.1 : 0);
      return { min: Math.max(0, stats.min - padding), max: stats.max + padding };
    })();
    const valueSpan = Math.max(0.001, valueRange.max - valueRange.min);
    const x = (timeMs) => left + ((timeMs - firstTime) / timeSpan) * plotWidth;
    const y = (value) => bottom - ((value - valueRange.min) / valueSpan) * plotHeight;

    context.font = "12px Inter, system-ui, sans-serif";
    context.fillStyle = color("--chart-axis");
    context.strokeStyle = color("--chart-grid");
    context.lineWidth = 1;
    context.textAlign = "right";
    context.textBaseline = "middle";
    const axisValues = config.kind === "binary" ? [1, 0] : [valueRange.max, valueRange.min];
    for (const value of axisValues) {
      const axisY = y(value);
      context.beginPath();
      context.moveTo(left, axisY);
      context.lineTo(right, axisY);
      context.stroke();
      const label = config.kind === "binary" ? (card.sensor === "sound" ? `${value} DO` : value ? "1 Sí" : "0 No") : numberFormat.format(value);
      context.fillText(label, left - 7, axisY);
    }
    context.textBaseline = "alphabetic";
    context.textAlign = "left";
    context.fillText(formatChartTime(firstTime, this.timeMode), left, rect.height - 7);
    if (lastTime !== firstTime) {
      context.textAlign = "right";
      context.fillText(formatChartTime(lastTime, this.timeMode), right, rect.height - 7);
    }

    context.strokeStyle = color("--chart-line");
    context.fillStyle = color("--chart-line");
    context.lineWidth = 2;
    context.lineJoin = "round";
    for (const segment of segments) {
      const visible = downsampleSegment(segment, firstTime, lastTime, plotWidth);
      context.beginPath();
      context.moveTo(x(visible[0].timeMs), y(visible[0].value));
      for (let index = 1; index < visible.length; index += 1) {
        const previous = visible[index - 1];
        const point = visible[index];
        if (config.kind === "binary") context.lineTo(x(point.timeMs), y(previous.value));
        context.lineTo(x(point.timeMs), y(point.value));
      }
      context.stroke();
      if (visible.length === 1) {
        context.beginPath();
        context.arc(x(visible[0].timeMs), y(visible[0].value), 3, 0, Math.PI * 2);
        context.fill();
      }
    }

    if (card.selectedIndex !== null) {
      const row = card.rows[card.selectedIndex];
      const selectedValue = row[config.field];
      context.strokeStyle = color("--chart-marker");
      context.setLineDash([4, 4]);
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(x(row.timeMs), top);
      context.lineTo(x(row.timeMs), bottom);
      context.stroke();
      context.setLineDash([]);
      if (selectedValue !== null) {
        context.fillStyle = color("--chart-marker");
        context.beginPath();
        context.arc(x(row.timeMs), y(selectedValue), 4, 0, Math.PI * 2);
        context.fill();
      }
    }
  }
}
