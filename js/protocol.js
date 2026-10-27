export const PROTOCOL_VERSION = 2;
export const ROLES = ["UNO", "NANO"];
export const SENSOR_KEYS = ["hc", "pir", "radar", "lux", "sound"];
export const SENSOR_ORIGIN = { hc: "UNO", lux: "UNO", sound: "UNO", pir: "NANO", radar: "NANO" };
export const ALLOWED_PINS = Array.from({ length: 11 }, (_, i) => i + 2);
export const WIRE_HEADER = "origen,secuencia,tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado";
export const CSV_HEADER = `fecha_hora_recepcion,captura_id,${WIRE_HEADER}`;
export const INCIDENT_HEADER = "fecha_hora,origen,tipo,descripcion";
const PIN_ROLES = [
  ["hc", "hcTrigger", "Trigger"], ["hc", "hcEcho", "Echo"],
  ["pir", "pirPin", "PIR"], ["radar", "radarPin", "Radar"], ["sound", "soundPin", "Sonido DO"],
];

export function defaultConfig(origin) {
  if (!ROLES.includes(origin)) throw new Error("Origen desconocido.");
  return { origin, hcTrigger: 4, hcEcho: 5, pirPin: 6, radarPin: 7, soundPin: 8,
    enabled: Object.fromEntries(SENSOR_KEYS.map(key => [key, SENSOR_ORIGIN[key] === origin])) };
}

export function validateConfig(config) {
  const errors = [];
  if (!ROLES.includes(config?.origin)) return ["Origen desconocido."];
  for (const key of SENSOR_KEYS) {
    if (typeof config.enabled?.[key] !== "boolean") errors.push(`Estado invalido: ${key}.`);
    if (config.enabled?.[key] && SENSOR_ORIGIN[key] !== config.origin) errors.push(`${key} no pertenece a ${config.origin}.`);
  }
  const used = new Map();
  for (const [sensor, field, label] of PIN_ROLES) {
    if (!config.enabled?.[sensor]) continue;
    const pin = config[field];
    if (!ALLOWED_PINS.includes(pin)) errors.push(`${label} debe usar D2 a D12.`);
    if (used.has(pin)) errors.push(`D${pin} esta repetido en ${used.get(pin)} y ${label}.`);
    used.set(pin, label);
  }
  return errors;
}

export function serializeConfig(config) {
  const errors = validateConfig(config);
  if (errors.length) throw new Error(errors.join(" "));
  return ["CONFIG", config.hcTrigger, config.hcEcho, config.pirPin, config.radarPin, config.soundPin,
    ...SENSOR_KEYS.map(key => Number(config.enabled[key]))].join(",");
}

export function parseIdentity(line, expectedOrigin) {
  const tokens = line.split(",");
  if (tokens.length !== 4 || tokens[0] !== "@OK" || tokens[1] !== "INFO" || tokens[2] !== String(PROTOCOL_VERSION)) {
    throw new Error("Firmware incompatible: se requiere protocolo 2. Carga el sketch nuevo de esta placa.");
  }
  if (tokens[3] !== expectedOrigin) throw new Error(`Se esperaba ${expectedOrigin}; el firmware declara ${tokens[3]}. Selecciona el puerto correcto.`);
  return { origin: expectedOrigin, version: PROTOCOL_VERSION };
}

function unsigned(token, label, positive = false) {
  if (!/^\d+$/.test(token)) throw new Error(`${label} debe ser un entero no negativo.`);
  const value = Number(token);
  if (!Number.isSafeInteger(value) || value > 0xffffffff || (positive && value === 0)) throw new Error(`${label} fuera de rango.`);
  return value;
}

function parseValue(token, key, origin, enabled) {
  if (SENSOR_ORIGIN[key] !== origin || !enabled[key]) {
    if (token !== "NA") throw new Error(`${key} debe ser NA para este origen o sensor desactivado.`);
    return null;
  }
  if (token === "NA") return null;
  if (["pir", "radar", "sound"].includes(key)) {
    if (token !== "0" && token !== "1") throw new Error(`${key} debe ser 0 o 1.`);
    return Number(token);
  }
  if (!/^\d+(?:\.\d+)?$/.test(token)) throw new Error(`${key} no es un numero valido.`);
  const value = Number(token);
  if (!Number.isFinite(value) || (key === "hc" && (value < 2 || value > 400))) throw new Error(`${key} fuera de rango.`);
  return value;
}

export function parseSampleLine(line, config) {
  const tokens = line.split(",");
  if (tokens.length !== 8) throw new Error("La muestra debe contener ocho columnas.");
  const origin = tokens[0];
  if (!ROLES.includes(origin) || origin !== config.origin) throw new Error("Origen incorrecto en la muestra.");
  const values = SENSOR_KEYS.map((key, i) => parseValue(tokens[i + 3], key, origin, config.enabled));
  return { raw: line, origin, sequence: unsigned(tokens[1], "secuencia", true),
    timeMs: unsigned(tokens[2], "tiempo_ms"), distanceCm: values[0], pir: values[1], radar: values[2], lux: values[3], sound: values[4] };
}

function csvCell(value) {
  let text = String(value ?? "");
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function buildCsv(rows) {
  return [CSV_HEADER, ...rows.map(row => [csvCell(row.receivedAt), csvCell(row.captureId), row.raw].join(","))].join("\r\n");
}

export function buildIncidentCsv(incidents) {
  return [INCIDENT_HEADER, ...incidents.map(item => [item.at, item.origin, item.type, item.description].map(csvCell).join(","))].join("\r\n");
}
