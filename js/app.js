import { ROLES, ALLOWED_PINS, SENSOR_ORIGIN, defaultConfig, validateConfig, buildCsv, buildIncidentCsv } from "./protocol.js";
import { SerialConnection } from "./serial.js";
import { BoardController } from "./board.js";
import { SensorCharts } from "./charts.js";

const sensors = {
  hc: { title: "HC-SR04", type: "Distancia · cm", pins: [["hcTrigger", "Trigger"], ["hcEcho", "Echo"]] },
  lux: { title: "BH1750", type: "Luz · lux", pins: [], hint: "I²C · SDA y SCL" },
  sound: { title: "Sonido · DO", type: "Digital · 0/1", pins: [["soundPin", "Pin DO"]], hint: "Verifica la polaridad de DO." },
  pir: { title: "HC-SR501", type: "Movimiento · PIR", pins: [["pirPin", "Pin OUT"]] },
  radar: { title: "RCWL-0516", type: "Movimiento · radar", pins: [["radarPin", "Pin OUT"]] },
};
const boardContainer = document.querySelector("#boards");
const sensorContainer = document.querySelector("#sensors");
for (const origin of ROLES) {
  boardContainer.insertAdjacentHTML("beforeend", `<article class="control-panel board-panel" id="${origin}-panel">
    <div class="control-heading"><div><p class="sensor-code">${origin === "UNO" ? "DISTANCIA · LUZ · SONIDO" : "PIR · MICROONDAS"}</p><h2>Arduino ${origin === "UNO" ? "Uno" : "Nano"}</h2></div><span id="${origin}-status" class="status-badge">Desconectado</span></div>
    <div class="button-row"><button id="${origin}-connect" type="button">Conectar ${origin}</button><button id="${origin}-disconnect" class="secondary" type="button" disabled>Desconectar</button></div>
    <div class="button-row"><button id="${origin}-configure" class="secondary" type="button" disabled>Aplicar configuración</button><button id="${origin}-start" type="button" disabled>Iniciar captura</button><button id="${origin}-stop" class="secondary" type="button" disabled>Detener</button></div>
    <div class="board-summary"><div><span>Captura actual</span><strong id="${origin}-count">0 lecturas</strong></div><div><span>Recepción</span><strong id="${origin}-age">Sin datos</strong></div></div>
    <p class="hint" id="${origin}-capture" hidden></p></article>`);
}
const drafts = Object.fromEntries(ROLES.map(origin => [origin, defaultConfig(origin)]));
for (const [key, sensor] of Object.entries(sensors)) {
  const origin = SENSOR_ORIGIN[key];
  sensorContainer.insertAdjacentHTML("beforeend", `<article class="sensor-card" data-origin="${origin}">
    <div class="sensor-heading"><div><p class="sensor-code">${origin} · ${sensor.type}</p><h2>${sensor.title}</h2></div><label class="toggle"><input id="${key}-enabled" type="checkbox" aria-label="Usar ${sensor.title}" checked /><span>Usar</span></label></div>
    ${sensor.pins.length ? `<div class="pin-row">${sensor.pins.map(([field, label]) => `<label>${label}<select id="${field}" class="pin-select" aria-label="${origin} ${label}">${ALLOWED_PINS.map(pin => `<option value="${pin}">D${pin}</option>`).join("")}</select></label>`).join("")}</div>` : ""}
    ${sensor.hint ? `<p class="hint">${sensor.hint}</p>` : ""}<p class="reading"><span>Lectura</span><strong id="${key}-value">Sin conexión</strong></p>
    <div class="sensor-chart"><div class="chart-heading"><span>Historial</span><strong id="${key}-stats">—</strong></div><div class="chart-frame"><canvas id="${key}-chart" class="chart-canvas" tabindex="0" role="img" aria-label="Historial ${sensor.title}; consulta con flechas" aria-describedby="${key}-chart-detail"></canvas><p id="${key}-chart-empty" class="chart-empty">Sin datos</p></div><p id="${key}-chart-detail" class="chart-detail" hidden></p></div>
  </article>`);
}

const theme = document.querySelector("#theme-switch");
try { theme.checked = localStorage.getItem("microp-theme") === "mono"; } catch { /* Preferencia opcional. */ }
document.documentElement.dataset.theme = theme.checked ? "mono" : "color";
const charts = new SensorCharts();
theme.addEventListener("change", () => {
  document.documentElement.dataset.theme = theme.checked ? "mono" : "color";
  try { localStorage.setItem("microp-theme", theme.checked ? "mono" : "color"); } catch { /* Preferencia opcional. */ }
  charts.redraw();
});

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
