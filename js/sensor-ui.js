import { ROLES, ALLOWED_PINS, SENSOR_ORIGIN } from "./protocol.js";

export const sensors = {
  hc: { title: "HC-SR04", type: "Distancia · cm", pins: [["hcTrigger", "Trigger"], ["hcEcho", "Echo"]] },
  lux: { title: "BH1750", type: "Luz · lux", pins: [], hint: "I²C · SDA y SCL" },
  sound: { title: "Sonido · DO", type: "Digital · 0/1", pins: [["soundPin", "Pin DO"]], hint: "Verifica la polaridad de DO." },
  pir: { title: "HC-SR501", type: "Movimiento · PIR", pins: [["pirPin", "Pin OUT"]] },
  radar: { title: "RCWL-0516", type: "Movimiento · radar", pins: [["radarPin", "Pin OUT"]] },
};

// Solo estructura visual compartida: cada entrada conserva su propio controlador.
export function mountSensorUI({ remote = false } = {}) {
  const boardContainer = document.querySelector("#boards");
  const sensorContainer = document.querySelector("#sensors");
  for (const origin of ROLES) {
    boardContainer.insertAdjacentHTML("beforeend", `<article class="control-panel board-panel" id="${origin}-panel">
      <div class="control-heading"><div><p class="sensor-code">${origin === "UNO" ? "DISTANCIA · LUZ · SONIDO" : "PIR · MICROONDAS"}</p><h2>Arduino ${origin === "UNO" ? "Uno" : "Nano"}</h2></div><span id="${origin}-status" class="status-badge" role="status">Desconectado</span></div>
      ${remote ? `<label class="port-field">Puerto en Raspberry<select id="${origin}-port" aria-label="Puerto ${origin}" disabled><option value="">Sin puertos disponibles</option></select></label>` : ""}
      <div class="button-row"><button id="${origin}-connect" type="button"${remote ? " disabled" : ""}>Conectar ${origin}</button><button id="${origin}-disconnect" class="secondary" type="button" disabled>Desconectar</button></div>
      <div class="button-row"><button id="${origin}-configure" class="secondary" type="button" disabled>Aplicar configuración</button><button id="${origin}-start" type="button" disabled>Iniciar captura</button><button id="${origin}-stop" class="secondary" type="button" disabled>Detener</button></div>
      <div class="board-summary"><div><span>Captura actual</span><strong id="${origin}-count">0 lecturas</strong></div><div><span>Recepción</span><strong id="${origin}-age">Sin datos</strong></div></div>
      <p class="hint" id="${origin}-capture" hidden></p>${remote ? `<p class="hint board-error" id="${origin}-error" role="status" hidden></p>` : ""}</article>`);
  }
  for (const [key, sensor] of Object.entries(sensors)) {
    const origin = SENSOR_ORIGIN[key];
    sensorContainer.insertAdjacentHTML("beforeend", `<article class="sensor-card" data-origin="${origin}">
      <div class="sensor-heading"><div><p class="sensor-code">${origin} · ${sensor.type}</p><h2>${sensor.title}</h2></div><label class="toggle"><input id="${key}-enabled" type="checkbox" aria-label="Usar ${sensor.title}" checked /><span>Usar</span></label></div>
      ${sensor.pins.length ? `<div class="pin-row">${sensor.pins.map(([field, label]) => `<label>${label}<select id="${field}" class="pin-select" aria-label="${origin} ${label}">${ALLOWED_PINS.map(pin => `<option value="${pin}">D${pin}</option>`).join("")}</select></label>`).join("")}</div>` : ""}
      ${sensor.hint ? `<p class="hint">${sensor.hint}</p>` : ""}<p class="reading"><span>Lectura</span><strong id="${key}-value">Sin conexión</strong></p>
      <div class="sensor-chart"><div class="chart-heading"><span id="${key}-chart-label">${remote ? "Datos recientes" : "Historial"}</span><strong id="${key}-stats">—</strong></div><div class="chart-frame"><canvas id="${key}-chart" class="chart-canvas" tabindex="0" role="img" aria-label="Historial ${sensor.title}; consulta con flechas" aria-describedby="${key}-chart-detail"></canvas><p id="${key}-chart-empty" class="chart-empty">Sin datos</p></div><p id="${key}-chart-detail" class="chart-detail" hidden></p></div>
    </article>`);
  }
}

export function setupTheme(onChange) {
  const theme = document.querySelector("#theme-switch");
  try { theme.checked = localStorage.getItem("microp-theme") === "mono"; } catch { /* Preferencia opcional. */ }
  const apply = () => { document.documentElement.dataset.theme = theme.checked ? "mono" : "color"; };
  apply();
  theme.addEventListener("change", () => {
    apply();
    try { localStorage.setItem("microp-theme", theme.checked ? "mono" : "color"); } catch { /* Preferencia opcional. */ }
    onChange();
  });
}
