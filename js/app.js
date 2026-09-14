import { ALLOWED_PINS, buildCsv, parseSampleLine, serializeConfig, validateConfig } from "./protocol.js";
import { SerialConnection } from "./serial.js";

const TARGET_RECORDS = 300;
const SENSOR_IDS = {
  "hc-enabled": "HC",
  "pir-enabled": "PIR",
  "radar-enabled": "RADAR",
  "lux-enabled": "LUX",
  "sound-enabled": "SOUND",
};
const SENSOR_KEYS = { HC: "hc", PIR: "pir", RADAR: "radar", LUX: "lux", SOUND: "sound" };

const elements = {
  connectionStatus: document.querySelector("#connection-status"),
  phaseStatus: document.querySelector("#phase-status"),
  message: document.querySelector("#message"),
  connect: document.querySelector("#connect-btn"),
  apply: document.querySelector("#apply-btn"),
  start: document.querySelector("#start-btn"),
  stop: document.querySelector("#stop-btn"),
  download: document.querySelector("#download-btn"),
  count: document.querySelector("#records-count"),
  elapsed: document.querySelector("#elapsed-time"),
  target: document.querySelector("#target-message"),
  pinSelects: [...document.querySelectorAll(".pin-select")],
  toggles: [...document.querySelectorAll(".toggle input")],
  values: {
    hc: document.querySelector("#hc-value"),
    pir: document.querySelector("#pir-value"),
    radar: document.querySelector("#radar-value"),
    lux: document.querySelector("#lux-value"),
    sound: document.querySelector("#sound-value"),
  },
};

const state = {
  connected: false,
  configured: false,
  capturing: false,
  commandBusy: false,
  phase: "disconnected",
  rows: [],
  appliedEnabled: { hc: true, pir: true, radar: true, lux: true, sound: true },
  captureStartedAt: 0,
  stoppedElapsedMs: 0,
};

for (const select of elements.pinSelects) {
  for (const pin of ALLOWED_PINS) select.add(new Option(`D${pin}`, String(pin)));
  select.value = select.dataset.default;
}

const serial = new SerialConnection({
  onLine: handleSerialLine,
  onDisconnect: () => setDisconnected("Arduino desconectado. La captura fue detenida de forma segura."),
  onError: (error) => showMessage(`Error Serial: ${friendlyError(error)}`, "error"),
});

function getConfig() {
  return {
    hcTrigger: Number(document.querySelector("#hc-trigger").value),
    hcEcho: Number(document.querySelector("#hc-echo").value),
    pirPin: Number(document.querySelector("#pir-pin").value),
    radarPin: Number(document.querySelector("#radar-pin").value),
    soundPin: Number(document.querySelector("#sound-pin").value),
    enabled: {
      hc: document.querySelector("#hc-enabled").checked,
      pir: document.querySelector("#pir-enabled").checked,
      radar: document.querySelector("#radar-enabled").checked,
      lux: document.querySelector("#lux-enabled").checked,
      sound: document.querySelector("#sound-enabled").checked,
    },
  };
}

function render() {
  elements.connectionStatus.textContent = state.connected ? "Conectado" : "Desconectado";
  elements.phaseStatus.textContent = phaseLabel(state.phase);
  elements.phaseStatus.dataset.phase = state.phase;

  elements.connect.disabled = state.connected || state.commandBusy || !SerialConnection.isSupported();
  elements.apply.disabled = !state.connected || state.capturing || state.commandBusy;
  elements.start.disabled = !state.connected || !state.configured || state.capturing || state.commandBusy;
  elements.stop.disabled = !state.connected || !state.capturing || state.commandBusy;
  elements.download.disabled = state.rows.length === 0;

  for (const select of elements.pinSelects) select.disabled = state.capturing || state.commandBusy;
  for (const toggle of elements.toggles) toggle.disabled = !state.connected || state.commandBusy;

  elements.count.textContent = `${state.rows.length} / ${TARGET_RECORDS}`;
  const remaining = Math.max(0, TARGET_RECORDS - state.rows.length);
  elements.target.textContent = remaining === 0 ? "✓ Minimo de 300 registros alcanzado" : `Faltan ${remaining} registros`;
  elements.target.classList.toggle("reached", remaining === 0);
  renderElapsed();
}

function phaseLabel(phase) {
  return {
    disconnected: "Desconectado",
    connected: "Conectado",
    configured: "Configurado",
    capturing: "Capturando",
    stopped: "Detenido",
  }[phase];
}

function showMessage(text, level = "info") {
  elements.message.textContent = text;
  elements.message.dataset.level = level;
}

function friendlyError(error) {
  const message = error?.message || String(error);
  const serialErrors = {
    "@ERR,CONFIG,FORMAT": "el comando de configuracion tiene un formato invalido.",
    "@ERR,CONFIG,PIN_RANGE": "Arduino rechazo un pin fuera de D2-D12.",
    "@ERR,CONFIG,DUPLICATE_PIN": "Arduino detecto un pin repetido entre funciones activas.",
    "@ERR,CONFIG,BH1750_NOT_FOUND": "no se detecto el BH1750 en el bus I2C.",
    "@ERR,STATE,NOT_CONFIGURED": "primero debes aplicar una configuracion valida.",
    "@ERR,STATE,CAPTURE_ACTIVE": "deten la captura antes de cambiar la configuracion.",
    "@ERR,ENABLE,FORMAT": "el comando para activar el sensor es invalido.",
    "@ERR,COMMAND,TOO_LONG": "Arduino descarto un comando demasiado largo.",
    "@ERR,READ,BH1750": "fallo una lectura del BH1750; la fila incompleta no fue registrada.",
    "@ERR,COMMAND,UNKNOWN": "Arduino no reconoce el comando enviado.",
  };
  return serialErrors[message] || message;
}

function markConfigurationPending() {
  if (!state.connected || state.capturing) return;
  state.configured = false;
  state.phase = "connected";
  showMessage("Hay cambios pendientes. Aplica la configuracion antes de iniciar.");
  render();
}

function setReadingsWaiting(enabled) {
  elements.values.hc.textContent = enabled.hc ? "Esperando muestra" : "Desactivado";
  elements.values.pir.textContent = enabled.pir ? "Esperando muestra" : "Desactivado";
  elements.values.radar.textContent = enabled.radar ? "Esperando muestra" : "Desactivado";
  elements.values.lux.textContent = enabled.lux ? "Esperando muestra" : "Desactivado";
  elements.values.sound.textContent = enabled.sound ? "Esperando muestra" : "Desactivado";
}

function updateReadings(sample) {
  elements.values.hc.textContent = sample.distanceCm === null ? "Desactivado" : `${sample.distanceCm.toFixed(2)} cm`;
  elements.values.pir.textContent = sample.pir === null ? "Desactivado" : sample.pir ? "Detectado" : "No detectado";
  elements.values.radar.textContent = sample.radar === null ? "Desactivado" : sample.radar ? "Detectado" : "No detectado";
  elements.values.lux.textContent = sample.lux === null ? "Desactivado" : `${sample.lux.toFixed(2)} lux`;
  elements.values.sound.textContent = sample.sound === null ? "Desactivado" : sample.sound ? "Evento detectado" : "Sin evento";
}

function handleSerialLine(line) {
  if (line.startsWith("@")) {
    if (line.startsWith("@OK,ENABLE,")) {
      const [, , sensor, value] = line.split(",");
      if (SENSOR_KEYS[sensor] && (value === "0" || value === "1")) {
        state.appliedEnabled[SENSOR_KEYS[sensor]] = value === "1";
      }
    }
    if (line.startsWith("@ERR") && !state.commandBusy) showMessage(`Arduino: ${friendlyError(new Error(line))}`, "error");
    return;
  }
  if (!state.capturing) return;

  try {
    const sample = parseSampleLine(line, state.appliedEnabled);
    state.rows.push(sample);
    updateReadings(sample);
    render();
  } catch (error) {
    showMessage(`Linea Serial ignorada: ${error.message}`, "error");
  }
}

async function runCommand(action) {
  state.commandBusy = true;
  render();
  try {
    return await action();
  } finally {
    state.commandBusy = false;
    render();
  }
}

elements.connect.addEventListener("click", async () => {
  try {
    showMessage("Selecciona el puerto del Arduino. La placa puede reiniciarse al conectar.");
    await runCommand(() => serial.connect());
    state.connected = true;
    state.configured = false;
    state.phase = "connected";
    showMessage("Arduino conectado. Revisa los pines y aplica la configuracion.", "success");
  } catch (error) {
    if (error.name !== "NotFoundError") showMessage(`No fue posible abrir el puerto: ${friendlyError(error)}`, "error");
  }
  render();
});

elements.apply.addEventListener("click", async () => {
  const config = getConfig();
  const errors = validateConfig(config);
  if (errors.length) {
    showMessage(errors.join(" "), "error");
    return;
  }

  try {
    await runCommand(() => serial.sendCommand(serializeConfig(config)));
    state.configured = true;
    state.appliedEnabled = { ...config.enabled };
    state.phase = "configured";
    setReadingsWaiting(state.appliedEnabled);
    showMessage("Configuracion aceptada por Arduino.", "success");
  } catch (error) {
    state.configured = false;
    state.phase = "connected";
    showMessage(`No se pudo aplicar: ${friendlyError(error)}`, "error");
  }
  render();
});

elements.start.addEventListener("click", async () => {
  if (!state.configured) {
    showMessage("Primero aplica una configuracion valida.", "error");
    return;
  }
  try {
    await runCommand(() => serial.sendCommand("START"));
    state.rows = [];
    state.capturing = true;
    state.phase = "capturing";
    state.captureStartedAt = performance.now();
    state.stoppedElapsedMs = 0;
    setReadingsWaiting(state.appliedEnabled);
    showMessage("Captura iniciada: una muestra conjunta por segundo.", "success");
  } catch (error) {
    showMessage(`No se pudo iniciar: ${friendlyError(error)}`, "error");
  }
  render();
});

elements.stop.addEventListener("click", async () => {
  try {
    await runCommand(() => serial.sendCommand("STOP"));
    stopCaptureState();
    showMessage("Captura detenida. Puedes descargar el CSV o cambiar la configuracion.", "success");
  } catch (error) {
    showMessage(`No se pudo detener: ${friendlyError(error)}`, "error");
  }
  render();
});

function stopCaptureState() {
  if (state.capturing) state.stoppedElapsedMs = performance.now() - state.captureStartedAt;
  state.capturing = false;
  state.phase = state.connected ? "stopped" : "disconnected";
}

function setDisconnected(message) {
  stopCaptureState();
  state.connected = false;
  state.configured = false;
  state.phase = "disconnected";
  showMessage(message, "error");
  render();
}

for (const select of elements.pinSelects) select.addEventListener("change", markConfigurationPending);

for (const toggle of elements.toggles) {
  toggle.addEventListener("change", async () => {
    if (!state.capturing) {
      markConfigurationPending();
      return;
    }

    const requestedValue = toggle.checked;
    const sensor = SENSOR_IDS[toggle.id];
    const config = getConfig();
    const errors = validateConfig(config);
    if (errors.length) {
      toggle.checked = !requestedValue;
      showMessage(errors.join(" "), "error");
      return;
    }

    try {
      await runCommand(() => serial.sendCommand(`ENABLE,${sensor},${requestedValue ? 1 : 0}`));
      state.appliedEnabled[SENSOR_KEYS[sensor]] = requestedValue;
      setReadingsWaiting(state.appliedEnabled);
      showMessage(`${sensor} ${requestedValue ? "activado" : "desactivado"} durante la captura.`, "success");
    } catch (error) {
      toggle.checked = !requestedValue;
      showMessage(`No se pudo cambiar ${sensor}: ${friendlyError(error)}`, "error");
    }
    render();
  });
}

elements.download.addEventListener("click", () => {
  const blob = new Blob([buildCsv(state.rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  link.href = url;
  link.download = `muestras-arduino-${timestamp}.csv`;
  link.click();
  URL.revokeObjectURL(url);
});

function renderElapsed() {
  const elapsedMs = state.capturing ? performance.now() - state.captureStartedAt : state.stoppedElapsedMs;
  const totalSeconds = Math.floor(elapsedMs / 1000);
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  elements.elapsed.textContent = `${minutes}:${seconds}`;
}

setInterval(renderElapsed, 250);

if (!SerialConnection.isSupported()) {
  showMessage("Web Serial no esta disponible. Usa Google Chrome de escritorio o un navegador Chromium compatible.", "error");
}
render();
