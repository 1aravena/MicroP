export const CSV_HEADER = "tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado";
export const ALLOWED_PINS = Array.from({ length: 11 }, (_, index) => index + 2);

const ACTIVE_PIN_ROLES = [
  ["hc", "hcTrigger", "HC-SR04 Trigger"],
  ["hc", "hcEcho", "HC-SR04 Echo"],
  ["pir", "pirPin", "HC-SR501"],
  ["radar", "radarPin", "RCWL-0516"],
  ["sound", "soundPin", "LM393 sonido"],
];

export function validateConfig(config) {
  const errors = [];
  const pinFields = [
    ["hcTrigger", "HC-SR04 Trigger"],
    ["hcEcho", "HC-SR04 Echo"],
    ["pirPin", "HC-SR501"],
    ["radarPin", "RCWL-0516"],
    ["soundPin", "LM393 sonido"],
  ];

  for (const [field, label] of pinFields) {
    if (!ALLOWED_PINS.includes(config[field])) {
      errors.push(`${label} debe usar un pin entre D2 y D12.`);
    }
  }

  const usedPins = new Map();
  for (const [sensor, field, label] of ACTIVE_PIN_ROLES) {
    if (!config.enabled[sensor]) continue;
    const pin = config[field];
    if (usedPins.has(pin)) {
      errors.push(`D${pin} esta repetido en ${usedPins.get(pin)} y ${label}.`);
    } else {
      usedPins.set(pin, label);
    }
  }

  return errors;
}

export function serializeConfig(config) {
  const flag = (value) => (value ? 1 : 0);
  return [
    "CONFIG",
    config.hcTrigger,
    config.hcEcho,
    config.pirPin,
    config.radarPin,
    config.soundPin,
    flag(config.enabled.hc),
    flag(config.enabled.pir),
    flag(config.enabled.radar),
    flag(config.enabled.lux),
    flag(config.enabled.sound),
  ].join(",");
}

function parseNumber(token, label) {
  if (token.trim() === "") throw new Error(`${label} esta vacio.`);
  const value = Number(token);
  if (!Number.isFinite(value) || value < 0) throw new Error(`${label} no es valido.`);
  return value;
}

function parseState(token, label) {
  if (token !== "0" && token !== "1") throw new Error(`${label} debe ser 0 o 1.`);
  return Number(token);
}

function parseField(token, active, label, parser) {
  if (!active) {
    if (token !== "NA") throw new Error(`${label} debe ser NA cuando el sensor esta desactivado.`);
    return null;
  }
  if (token === "NA") throw new Error(`${label} falta para un sensor activo.`);
  return parser(token, label);
}

export function parseSampleLine(line, enabled) {
  const tokens = line.trim().split(",");
  if (tokens.length !== 6) throw new Error("La muestra no contiene exactamente seis columnas.");
  if (!/^\d+$/.test(tokens[0])) throw new Error("tiempo_ms debe ser un entero no negativo.");

  return {
    raw: tokens.join(","),
    timeMs: Number(tokens[0]),
    distanceCm: parseField(tokens[1], enabled.hc, "distancia_cm", parseNumber),
    pir: parseField(tokens[2], enabled.pir, "pir_estado", parseState),
    radar: parseField(tokens[3], enabled.radar, "radar_estado", parseState),
    lux: parseField(tokens[4], enabled.lux, "lux", parseNumber),
    sound: parseField(tokens[5], enabled.sound, "sonido_estado", parseState),
  };
}

export function buildCsv(rows) {
  return [CSV_HEADER, ...rows.map((row) => row.raw)].join("\r\n");
}
