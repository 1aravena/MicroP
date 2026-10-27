import assert from "node:assert/strict";
import test from "node:test";
import { defaultConfig, validateConfig, serializeConfig, parseIdentity, parseSampleLine, buildCsv, buildIncidentCsv, CSV_HEADER } from "../js/protocol.js";

test("configura exclusivamente los sensores propios de cada placa", () => {
  assert.deepEqual(validateConfig(defaultConfig("UNO")), []);
  assert.equal(serializeConfig(defaultConfig("UNO")), "CONFIG,4,5,6,7,8,1,0,0,1,1");
  assert.equal(serializeConfig(defaultConfig("NANO")), "CONFIG,4,5,6,7,8,0,1,1,0,0");
  const bad = defaultConfig("NANO"); bad.enabled.lux = true;
  assert.match(validateConfig(bad).join(), /no pertenece/);
});
test("valida pines activos por placa y permite compartir numeros entre placas", () => {
  const uno = defaultConfig("UNO"); uno.soundPin = 4;
  assert.match(validateConfig(uno).join(), /repetido/);
  uno.enabled.sound = false;
  assert.deepEqual(validateConfig(uno), []);
  const nano = defaultConfig("NANO"); nano.pirPin = uno.hcTrigger;
  assert.deepEqual(validateConfig(nano), []);
  nano.pirPin = 0;
  assert.throws(() => serializeConfig(nano), /D2 a D12/);
});
test("identificacion rechaza versiones antiguas, roles equivocados y respuestas incompletas", () => {
  assert.deepEqual(parseIdentity("@OK,INFO,2,UNO", "UNO"), { origin: "UNO", version: 2 });
  assert.throws(() => parseIdentity("@OK,INFO,1,UNO", "UNO"), /incompatible/);
  assert.throws(() => parseIdentity("@OK,INFO,2,NANO", "UNO"), /puerto correcto/);
  assert.throws(() => parseIdentity("@OK,INFO,2,UNO,EXTRA", "UNO"), /incompatible/);
});
test("interpreta ambas placas conservando mediciones parciales", () => {
  const sample = parseSampleLine("UNO,1,1000,NA,NA,NA,0.00,1", defaultConfig("UNO"));
  assert.equal(sample.distanceCm, null);
  assert.equal(sample.lux, 0);
  assert.equal(sample.sound, 1);
  assert.equal(sample.pir, null);
  const nano = parseSampleLine("NANO,4,987,NA,1,0,NA,NA", defaultConfig("NANO"));
  assert.equal(nano.pir, 1);
  assert.equal(nano.sequence, 4);
});
test("rechaza columnas, fuentes, numeros y estados digitales invalidos", () => {
  const config = defaultConfig("UNO");
  for (const line of ["1000,4,0,0,20,1", "UNO,0,1000,20,NA,NA,100,0", "UNO,1,,20,NA,NA,100,0",
    "NANO,1,1000,NA,1,0,NA,NA", "UNO,1,1000,0,NA,NA,100,0", "UNO,1,1000,20,1,NA,100,0",
    "UNO,1,1000,20,NA,NA,,0", "UNO,1,1000,20,NA,NA,0x20,0", "UNO,1,1000,20,NA,NA,NaN,0",
    "UNO,1,1000,20,NA,NA,100,2", "UNO,1,4294967296,20,NA,NA,100,0"]) {
    assert.throws(() => parseSampleLine(line, config), undefined, line);
  }
});
test("un sensor desactivado debe enviar NA", () => {
  const config = defaultConfig("UNO"); config.enabled.sound = false;
  assert.throws(() => parseSampleLine("UNO,1,1000,20,NA,NA,100,0", config), /desactivado/);
  assert.equal(parseSampleLine("UNO,1,1000,20,NA,NA,100,NA", config).sound, null);
});
test("exporta el mensaje original y los metadatos sin fusionar valores de placas", () => {
  const raw = "NANO,1,1000,NA,1,0,NA,NA";
  const csv = buildCsv([{ raw, receivedAt: "2026-10-27T01:00:00.000Z", captureId: "captura-1" }]);
  assert.equal(csv, `${CSV_HEADER}\r\n2026-10-27T01:00:00.000Z,captura-1,${raw}`);
});
test("exporta incidencias escapando comas, comillas y texto recibido por USB", () => {
  const csv = buildIncidentCsv([{ at: "fecha", origin: "UNO", type: "DEVICE", description: '@ERR,"dato"' }]);
  assert.ok(csv.includes('"\'@ERR,""dato"""'));
});
