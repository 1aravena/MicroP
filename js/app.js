import { ROLES, SENSOR_ORIGIN, defaultConfig, validateConfig, buildCsv, buildIncidentCsv } from "./protocol.js";
import { SerialConnection } from "./serial.js";
import { BoardController } from "./board.js";
import { SensorCharts } from "./charts.js";

import { sensors, mountSensorUI, setupTheme } from "./sensor-ui.js";

mountSensorUI();
const drafts = Object.fromEntries(ROLES.map(origin => [origin, defaultConfig(origin)]));
const charts = new SensorCharts();
setupTheme(() => charts.redraw());

const epoch = performance.now();
const boards = {};
const incidents = [];
let ready = false;
let downloadedRows = 0;
function showMessage(message, level = "info") {
  const element = document.querySelector("#message");
  element.textContent = message;
  element.dataset.level = level;
  element.hidden = !message;
}
function recordIncident(item) {
  incidents.push(item);
  const list = document.querySelector("#incidents");
  list.replaceChildren(...incidents.slice(-15).reverse().map(incident => {
    const li = document.createElement("li");
    li.textContent = `${new Date(incident.at).toLocaleTimeString("es-CL")} · ${incident.origin} · ${incident.type}: ${incident.description}`;
    return li;
  }));
  render(false);
}
for (const origin of ROLES) {
  boards[origin] = new BoardController(origin, {
    epoch, transportFactory: handlers => new SerialConnection(handlers),
    onChange: () => render(), onIncident: recordIncident,
  });
}

function rowsForExport() { return ROLES.flatMap(origin => boards[origin].allRows).sort((a, b) => a.timeMs - b.timeMs); }
const phaseLabels = { disconnected: "Desconectado", connecting: "Identificando…", unconfigured: "Revisar configuración", configured: "Configurado · detenido", starting: "Iniciando…", capturing: "Capturando" };
const sensorFields = { hc: "distanceCm", lux: "lux", sound: "sound", pir: "pir", radar: "radar" };
function render(updateCharts = true) {
  if (!ready) return;
  for (const origin of ROLES) {
    const board = boards[origin];
    const status = document.querySelector(`#${origin}-status`);
    const stale = board.phase === "capturing" && performance.now() - (board.lastReceived ?? board.currentCapture.startedClock) > 3500;
    status.textContent = stale ? "Captura · sin datos recientes" : phaseLabels[board.phase];
    status.dataset.phase = stale ? "stopped" : board.phase;
    document.querySelector(`#${origin}-connect`).disabled = board.busy || board.connected || !SerialConnection.isSupported();
    document.querySelector(`#${origin}-disconnect`).disabled = board.busy || !board.connected;
    document.querySelector(`#${origin}-configure`).disabled = board.busy || !board.connected || board.phase === "capturing";
    document.querySelector(`#${origin}-start`).disabled = board.busy || !board.connected || !board.configured || board.phase === "capturing";
    document.querySelector(`#${origin}-stop`).disabled = board.busy || !board.connected || !["capturing", "unconfigured"].includes(board.phase);
    document.querySelector(`#${origin}-count`).textContent = `${board.rows.length} lecturas`;
    document.querySelector(`#${origin}-age`).textContent = board.lastReceived === null ? "Sin datos" : `Hace ${Math.floor((performance.now() - board.lastReceived) / 1000)} s`;
    const captureLabel = document.querySelector(`#${origin}-capture`);
    captureLabel.hidden = !board.currentCapture;
    captureLabel.textContent = board.currentCapture ? `Captura ${board.captures.length}` : "";
  }
  for (const [key, sensor] of Object.entries(sensors)) {
    const origin = SENSOR_ORIGIN[key];
    const board = boards[origin];
    const draft = drafts[origin];
    const toggle = document.querySelector(`#${key}-enabled`);
    toggle.checked = draft.enabled[key];
    toggle.disabled = board.busy || !board.connected;
    for (const [field] of sensor.pins) {
      const select = document.querySelector(`#${field}`);
      select.value = String(draft[field]);
      select.disabled = board.busy || board.phase === "capturing" || !board.connected;
    }
    let value = "Sin conexión";
    if (board.connected) {
      if (!board.configured) value = "Configuración pendiente";
      else if (!board.config.enabled[key]) value = "Desactivado";
      else if (board.phase !== "capturing") value = "Detenido";
      else if (board.lastReceived === null) value = performance.now() - board.currentCapture.startedClock > 3500 ? "Sin datos recientes" : "Esperando muestra";
      else if (performance.now() - board.lastReceived > 3500) value = "Sin datos recientes";
      else {
        const reading = board.rows.at(-1)?.[sensorFields[key]];
        value = reading == null ? "Lectura no disponible" : key === "hc" ? `${reading.toFixed(2)} cm`
          : key === "lux" ? `${reading.toFixed(2)} lux` : key === "sound" ? `DO = ${reading}` : reading ? "Movimiento (1)" : "Sin detección (0)";
      }
    }
    document.querySelector(`#${key}-value`).textContent = value;
  }
  const count = ROLES.reduce((sum, origin) => sum + boards[origin].allRows.length, 0);
  const captureCount = ROLES.reduce((sum, origin) => sum + boards[origin].captures.length, 0);
  document.querySelector("#archive-count").textContent = `${count} lecturas · ${captureCount} capturas · ${incidents.length} eventos`;
  document.querySelector("#download-data").disabled = count === 0;
  document.querySelector("#download-incidents").disabled = incidents.length === 0;
  if (updateCharts) charts.setRows(ROLES.flatMap(origin => boards[origin].rows).sort((a, b) => a.timeMs - b.timeMs));
}

async function execute(origin, operation) {
  try { await operation(); showMessage(""); }
  catch (error) { if (error.name !== "NotFoundError") showMessage(`${origin}: ${error.message}`, "error"); }
  render();
}
for (const origin of ROLES) {
  const board = boards[origin];
  for (const action of ["connect", "disconnect", "start", "stop"]) {
    document.querySelector(`#${origin}-${action}`).addEventListener("click", () => execute(origin, () => board[action]()));
  }
  document.querySelector(`#${origin}-configure`).addEventListener("click", () => {
    const errors = validateConfig(drafts[origin]);
    if (errors.length) { showMessage(`${origin}: ${errors.join(" ")}`, "error"); return; }
    void execute(origin, () => board.configure(drafts[origin]));
  });
}
function markPending(origin) {
  const board = boards[origin];
  if (board.connected) { board.configured = false; board.phase = "unconfigured"; }
  showMessage(`${origin}: aplica la configuración.`);
  render();
}
for (const [key, sensor] of Object.entries(sensors)) {
  const origin = SENSOR_ORIGIN[key];
  for (const [field] of sensor.pins) document.querySelector(`#${field}`).addEventListener("change", event => {
    drafts[origin][field] = Number(event.target.value); markPending(origin);
  });
  document.querySelector(`#${key}-enabled`).addEventListener("change", async event => {
    const enabled = event.target.checked;
    drafts[origin].enabled[key] = enabled;
    if (boards[origin].phase === "capturing") {
      await execute(origin, () => boards[origin].enable(key, enabled));
      drafts[origin] = structuredClone(boards[origin].config);
      render();
    } else markPending(origin);
  });
}
function download(contents, name) {
  const url = URL.createObjectURL(new Blob(["\uFEFF", contents], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url; link.download = `${name}-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.querySelector("#download-data").addEventListener("click", () => {
  const rows = rowsForExport(); download(buildCsv(rows), "mediciones-uno-nano"); downloadedRows = rows.length;
});
document.querySelector("#download-incidents").addEventListener("click", () => download(buildIncidentCsv(incidents), "incidencias-uno-nano"));
window.addEventListener("beforeunload", event => {
  if (rowsForExport().length > downloadedRows) { event.preventDefault(); event.returnValue = ""; }
});
ready = true;
render();
setInterval(() => render(false), 500);
if (!SerialConnection.isSupported()) showMessage("Web Serial no disponible. Abre la página en Chrome de escritorio mediante localhost o HTTPS.", "error");
