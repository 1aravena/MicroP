import assert from "node:assert/strict";
import test from "node:test";
import { CSV_HEADER, buildCsv, parseSampleLine, serializeConfig, validateConfig } from "../js/protocol.js";

const validConfig = {
  hcTrigger: 4,
  hcEcho: 5,
  pirPin: 6,
  radarPin: 7,
  soundPin: 8,
  enabled: { hc: true, pir: true, radar: true, lux: true, sound: true },
};

test("acepta una configuracion sin pines repetidos", () => {
  assert.deepEqual(validateConfig(validConfig), []);
  assert.equal(serializeConfig(validConfig), "CONFIG,4,5,6,7,8,1,1,1,1,1");
});

test("rechaza pines repetidos solo entre funciones activas", () => {
  const repeated = structuredClone(validConfig);
  repeated.radarPin = 6;
  assert.match(validateConfig(repeated)[0], /D6 esta repetido/);
  repeated.enabled.radar = false;
  assert.deepEqual(validateConfig(repeated), []);
});

test("parsea una fila estable y respeta NA", () => {
  const enabled = { hc: false, pir: true, radar: false, lux: false, sound: true };
  const sample = parseSampleLine("1000,NA,1,NA,NA,0", enabled);
  assert.equal(sample.timeMs, 1000);
  assert.equal(sample.distanceCm, null);
  assert.equal(sample.pir, 1);
  assert.equal(buildCsv([sample]), `${CSV_HEADER}\r\n1000,NA,1,NA,NA,0`);
});

test("descarta columnas o estados invalidos", () => {
  const enabled = validConfig.enabled;
  assert.throws(() => parseSampleLine("1000,1,0", enabled), /seis columnas/);
  assert.throws(() => parseSampleLine("1000,10.2,2,0,80.1,0", enabled), /0 o 1/);
});
