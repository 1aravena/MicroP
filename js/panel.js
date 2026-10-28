import { ApiClient } from "./api-client.js";
import { RemotePanel, readingFor } from "./remote-panel.js";
import { ROLES, SENSOR_ORIGIN } from "./protocol.js";
import { SensorCharts } from "./charts.js";
import { sensors, mountSensorUI, setupTheme } from "./sensor-ui.js";
import { Experiments } from "./experiments.js";
import { ExperimentsView } from "./experiments-view.js";
import { AccessPanel } from './access.js';
import { AccessView } from './access-view.js';

mountSensorUI({ remote: true });
const api = new ApiClient();
const charts = new SensorCharts({ timeMode: "received" });
setupTheme(() => charts.redraw());
const panel = new RemotePanel(api, { onChange: render });
const experiments = new Experiments(api, { onChange: state => experimentsView.render(state) });
const experimentsView = new ExperimentsView(experiments, api, { onChange: () => render(panel) });
const access = new AccessPanel(api, { onChange: state => accessView.render(state) });
const accessView = new AccessView(access, api, { onChange: () => {
  experiments.accessReserved = access.status.active;
  experimentsView.render(experiments);
} });
const $ = selector => document.querySelector(selector);
// Pages solo publica archivos. data-hosting permite identificar otros hosts estaticos.
const staticHosting = location.hostname.endsWith(".github.io") || document.documentElement.dataset.hosting === "static";
const phaseLabels = { disconnected: "Desconectado", connecting: "Identificando…", unconfigured: "Revisar configuración",
  configured: "Configurado · detenido", starting: "Iniciando…", capturing: "Capturando", storage_error: "Error de almacenamiento" };
const operationLabels = { connect: "Identificando…", disconnect: "Desconectando…", config: "Aplicando configuración…", start: "Iniciando…", stop: "Deteniendo…" };
let portsKey = "";
let capturesKey = "";
let incidentsKey = "";
let chartsKey = "";

function message(text = "", level = "info") {
  $("#message").textContent = text;
  $("#message").dataset.level = level;
  $("#message").hidden = !text;
}

function inlineError(selector, text) {
  $(selector).textContent = text;
  $(selector).hidden = !text;
}

function renderPorts(state) {
  const gateway = state.health?.transport?.mode === 'gateway';
  const key = JSON.stringify([state.ports, gateway, ROLES.map(origin => state.boards[origin].snapshot.port)]);
  if (key === portsKey) return;
  portsKey = key;
  for (const origin of ROLES) {
    const select = $(`#${origin}-port`);
    const selected = state.boards[origin].snapshot.port ?? select.value;
    const entries = [...state.ports];
    if (selected && !entries.some(item => item.device === selected) && state.boards[origin].snapshot.connected) {
      entries.push({ device: selected, description: "Puerto conectado" });
    }
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = entries.length ? "Selecciona un puerto" : "Sin puertos disponibles";
    select.replaceChildren(placeholder, ...entries.map(port => {
      const option = document.createElement("option");
      option.value = port.device;
      option.textContent = `${port.device}${port.description ? ` · ${port.description}` : ""}`;
      option.disabled = !gateway && ROLES.some(other => other !== origin && state.boards[other].snapshot.port === port.device);
      return option;
    }));
    if ([...select.options].some(option => option.value === selected && !option.disabled)) select.value = selected;
  }
}

function render(state) {
  $("#service-status").textContent = staticHosting ? "Requiere backend" : state.online ? "Disponible" : state.errors.connection ? "Sin comunicación" : "Conectando…";
  $("#storage-status").textContent = staticHosting ? "Sin consultar" : !state.online ? "Sin verificar" : !state.health ? "Comprobando…" : state.storageOK ? "Disponible" : "Error";
  $("#refresh-ports").disabled = !state.online || state.portsBusy;
  inlineError("#service-error", [...new Set([state.errors.connection, state.errors.health, state.errors.ports].filter(Boolean))].join(" "));
  renderPorts(state);
  const transport = state.health?.transport;
  const gateway = transport?.mode === 'gateway';
  $('#gateway-panel').hidden = !gateway;
  const runtime = state.health?.runtime;
  $('#backend-location').textContent = runtime ? `Backend: ${runtime.hostname} (${runtime.platform}) · Datos: ${runtime.database} · ${gateway ? 'UART con Uno maestro' : 'USB independiente'}` : '';
  if (gateway) {
    const select = $('#gateway-port');
    if (select.options[0]?.value !== transport.port) {
      const option = document.createElement('option'); option.value = transport.port; option.textContent = transport.port;
      select.replaceChildren(option);
    }
    const snapshots = ROLES.map(origin => state.boards[origin].snapshot);
    const reserved = snapshots.some(item => item.trialId) || Boolean(experiments.active);
    const busy = state.gatewayPending || transport.busy || snapshots.some(item => item.busy) || reserved || experiments.busy || access.busy;
    $('#gateway-connect').disabled = !state.online || !state.storageOK || busy || access.status.active || snapshots.every(item => item.connected) || ROLES.some(origin => state.boards[origin].verifying);
    $('#gateway-disconnect').disabled = !state.online || busy || !transport.connected;
    $('#gateway-state').textContent = [state.gatewayPending ? 'Comprobando enlace…' : `${snapshots.filter(item => item.connected).length}/2 placas conectadas`, transport.lastError].filter(Boolean).join(' · ');
  }
  for (const origin of ROLES) {
    const board = state.boards[origin];
    const snapshot = board.snapshot;
    $(`#${origin}-port`).closest('label').hidden = gateway;
    $(`#${origin}-connect`).hidden = gateway;
    $(`#${origin}-disconnect`).hidden = gateway;
    $(`#${origin}-panel h2`).textContent = gateway ? (origin === 'UNO' ? 'Uno R3 · maestro' : 'Nano 33 BLE · esclavo') : `Arduino ${origin === 'UNO' ? 'Uno' : 'Nano'}`;
    const accessReserved = Boolean(snapshot.accessReserved || access.status.active);
    const trialReserved = Boolean(snapshot.trialId || experiments.active);
    const ready = state.online && state.storageOK && !board.pending && !board.verifying && !snapshot.busy && !trialReserved && !experiments.busy && !access.busy;
    const capturing = ["capturing", "starting"].includes(snapshot.phase);
    const status = $(`#${origin}-status`);
    status.textContent = !state.online ? "Sin comunicación" : trialReserved ? "Reservado por ensayo · detener desde Ensayos" : accessReserved ? 'Modo Acceso y ML activo' : board.pending ? operationLabels[board.pending] ?? "Actualizando sensor…"
      : board.verifying ? "Verificando estado…" : snapshot.busy ? "Operación en curso…" : snapshot.stale ? "Captura · sin datos recientes"
        : board.dirty ? "Cambios por aplicar" : phaseLabels[snapshot.phase] ?? "Estado desconocido";
    status.dataset.phase = !state.online || snapshot.stale ? "stopped" : snapshot.phase;
    $(`#${origin}-port`).disabled = !ready || accessReserved || snapshot.connected;
    $(`#${origin}-connect`).disabled = !ready || accessReserved || snapshot.connected || !$(`#${origin}-port`).value;
    $(`#${origin}-disconnect`).disabled = !ready || !snapshot.connected;
    $(`#${origin}-configure`).disabled = !ready || accessReserved || !snapshot.connected || capturing;
    $(`#${origin}-start`).disabled = !ready || accessReserved || !snapshot.connected || !snapshot.configured || board.dirty || snapshot.phase !== "configured";
    $(`#${origin}-stop`).disabled = !ready || !snapshot.connected || !["capturing", "unconfigured"].includes(snapshot.phase);
    $(`#${origin}-count`).textContent = `${snapshot.sampleCount} lecturas`;
    $(`#${origin}-age`).textContent = !state.online ? "Sin verificar" : !snapshot.lastReceivedAt ? "Sin datos" : `Hace ${Math.floor((snapshot.ageMs ?? 0) / 1000)} s`;
    const capture = $(`#${origin}-capture`);
    capture.hidden = !snapshot.captureId;
    capture.textContent = snapshot.captureId ? `Captura ${snapshot.captureId}` : "";
    inlineError(`#${origin}-error`, [board.error || snapshot.lastError, board.sampleError].filter(Boolean).join(" "));
    for (const [key, sensor] of Object.entries(sensors).filter(([key]) => SENSOR_ORIGIN[key] === origin)) {
      const toggle = $(`#${key}-enabled`);
      toggle.checked = board.draft.enabled[key];
      toggle.disabled = !ready || accessReserved || !snapshot.connected || snapshot.phase === "starting";
      for (const [field] of sensor.pins) {
        for (const option of $(`#${field}`).options) option.disabled = gateway && origin === 'UNO' && [2, 3].includes(Number(option.value));
        $(`#${field}`).value = String(board.draft[field]);
        $(`#${field}`).disabled = !ready || !snapshot.connected || capturing;
      }
      $(`#${key}-value`).textContent = readingFor(snapshot, key, state.online);
      $(`#${key}-chart-label`).textContent = state.online && snapshot.phase === "capturing" && !snapshot.stale ? "Datos recientes" : "Historial reciente";
    }
  }
  const nextChartsKey = JSON.stringify(ROLES.map(origin => {
    const board = state.boards[origin];
    return [board.windowCaptureId, board.rows[0]?.id, board.rows.at(-1)?.id, board.rows.length];
  }));
  if (nextChartsKey !== chartsKey) { chartsKey = nextChartsKey; charts.setRows(state.chartRows); }
  renderCaptures(state);
  renderIncidents(state);
}

function renderCaptures(state) {
  inlineError("#capture-error", state.errors.captures);
  $("#capture-origin").disabled = !state.online || state.captureBusy;
  $("#captures-previous").disabled = !state.online || state.captureBusy || state.capturePage === 0;
  $("#captures-next").disabled = !state.online || state.captureBusy || !state.captureHasMore;
  $("#capture-page").textContent = `Página ${state.capturePage + 1}${state.captureBusy ? " · Actualizando…" : ""}`;
  const key = JSON.stringify([state.captures, state.online]);
  if (key === capturesKey) return;
  capturesKey = key;
  const rows = state.captures.map(capture => {
    const tr = document.createElement("tr");
    const values = [capture.origin, new Date(capture.startedAt).toLocaleString("es-CL"),
      { capturing: "Capturando", stopped: "Detenida", interrupted: "Interrumpida" }[capture.status] ?? capture.status,
      String(capture.sampleCount)];
    for (const value of values) { const td = document.createElement("td"); td.textContent = value; tr.append(td); }
    tr.title = `Captura ${capture.id}${capture.endReason ? ` · ${capture.endReason}` : ""}`;
    const td = document.createElement("td");
    const link = document.createElement("a");
    link.textContent = "CSV";
    link.className = "download-link";
    link.href = api.captureExportUrl(capture.id);
    link.download = `mediciones-${capture.id}.csv`;
    link.setAttribute("aria-label", `Descargar captura ${capture.origin} del ${new Date(capture.startedAt).toLocaleString("es-CL")}`);
    link.setAttribute("aria-disabled", String(!state.online));
    link.addEventListener("click", event => { if (!panel.online) { event.preventDefault(); message("Recupera la comunicación con la Raspberry para descargar.", "error"); } });
    td.append(link); tr.append(td);
    return tr;
  });
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.textContent = "Sin capturas guardadas en esta página.";
    tr.append(td); rows.push(tr);
  }
  $("#captures").replaceChildren(...rows);
}

function renderIncidents(state) {
  inlineError("#incident-error", state.errors.incidents);
  $("#download-incidents").disabled = !state.online;
  const key = JSON.stringify(state.incidents);
  if (key === incidentsKey) return;
  incidentsKey = key;
  const items = state.incidents.map(incident => {
    const li = document.createElement("li");
    li.textContent = `${new Date(incident.at).toLocaleString("es-CL")} · ${incident.origin} · ${incident.type}: ${incident.description}`;
    return li;
  });
  if (!items.length) { const li = document.createElement("li"); li.textContent = "Sin eventos."; items.push(li); }
  $("#incidents").replaceChildren(...items);
}

async function perform(origin, action, body) {
  try {
    message("");
    await panel.command(origin, action, body);
  } catch (error) { message(`${origin}: ${error.message}`, "error"); }
}

for (const action of ['connect', 'disconnect']) $('#gateway-' + action).addEventListener('click', async () => {
  try { message(''); await panel.gatewayCommand(action, $('#gateway-port').value); }
  catch (error) { message(error.message, 'error'); }
});

for (const origin of ROLES) {
  $(`#${origin}-port`).addEventListener("change", () => render(panel));
  $(`#${origin}-connect`).addEventListener("click", () => perform(origin, "connect", { port: $(`#${origin}-port`).value }));
  for (const action of ["disconnect", "start", "stop"]) $(`#${origin}-${action}`).addEventListener("click", () => perform(origin, action));
  $(`#${origin}-configure`).addEventListener("click", () => perform(origin, "config", structuredClone(panel.boards[origin].draft)));
}
for (const [key, sensor] of Object.entries(sensors)) {
  const origin = SENSOR_ORIGIN[key];
  for (const [field] of sensor.pins) $(`#${field}`).addEventListener("change", event => {
    try { panel.editConfig(origin, draft => { draft[field] = Number(event.target.value); }); }
    catch (error) { message(error.message, "error"); render(panel); }
  });
  $(`#${key}-enabled`).addEventListener("change", event => {
    const enabled = event.target.checked;
    if (panel.boards[origin].snapshot.phase === "capturing") void perform(origin, `sensors/${key}`, { enabled });
    else {
      try { panel.editConfig(origin, draft => { draft.enabled[key] = enabled; }); }
      catch (error) { message(error.message, "error"); render(panel); }
    }
  });
}
$("#refresh-ports").addEventListener("click", () => panel.refreshPorts());
$("#capture-origin").addEventListener("change", event => panel.setCaptureOrigin(event.target.value));
$("#captures-previous").addEventListener("click", () => panel.changeCapturePage(-1));
$("#captures-next").addEventListener("click", () => panel.changeCapturePage(1));
$("#download-incidents").addEventListener("click", () => {
  if (!panel.online) return;
  const link = document.createElement("a");
  link.href = api.incidentExportUrl(); link.download = "incidencias.csv";
  document.body.append(link); link.click(); link.remove();
});
window.addEventListener("pagehide", () => { panel.stop(); experiments.stop(); access.stop(); });
// Volver desde la caché de navegación carga una vista nueva, nunca otra captura.
window.addEventListener("pageshow", event => { if (event.persisted) location.reload(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden && !staticHosting) { void panel.refresh(true); void experiments.refresh(); void access.refresh(); } });
function showSection(section) {
  $('#open-connected-panel').href = `http://127.0.0.1:8001/#${['ensayos', 'acceso'].includes(section) ? section : 'sensores'}`;
  const sensors = !['ensayos', 'acceso'].includes(section);
  $("#sensor-section").hidden = !sensors;
  $("#experiment-section").hidden = section !== 'ensayos';
  $('#access-section').hidden = section !== 'acceso';
  $("#show-sensors").setAttribute("aria-pressed", String(sensors));
  $("#show-experiments").setAttribute("aria-pressed", String(section === 'ensayos'));
  $('#show-access').setAttribute('aria-pressed', String(section === 'acceso'));
  $("#show-sensors").classList.toggle("secondary", !sensors);
  $("#show-experiments").classList.toggle("secondary", section !== 'ensayos');
  $('#show-access').classList.toggle('secondary', section !== 'acceso');
  if (sensors) charts.redraw();
}
for (const [id, hash] of [["show-sensors", "sensores"], ["show-experiments", "ensayos"], ['show-access', 'acceso']]) {
  $(`#${id}`).addEventListener("click", () => { location.hash = hash; showSection(hash); });
}
window.addEventListener("hashchange", () => showSection(location.hash.slice(1)));
showSection(location.hash.slice(1));
experimentsView.render(experiments);
accessView.render(access);
render(panel);
if (staticHosting) {
  $("#static-hosting-notice").hidden = false;
  for (const id of ["dataset-train", "dataset-test", "dataset-minimum"]) $(`#${id}`).textContent = "Sin consultar";
} else {
  void panel.start();
  void experiments.start();
  void access.start();
}
