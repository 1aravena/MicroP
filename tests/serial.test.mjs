import assert from "node:assert/strict";
import test from "node:test";
import { SerialConnection } from "../js/serial.js";
import { FakePort, FakeSerial, tick } from "./helpers/fake-serial.mjs";

test("reconstruye lineas fragmentadas y descarta por completo una linea demasiado larga", async () => {
  const port = new FakePort("UNO"); const lines = []; const errors = [];
  const connection = new SerialConnection({ serialApi: new FakeSerial(port), resetMs: 0, onLine: line => lines.push(line), onError: error => errors.push(error) });
  await connection.connect();
  port.emit("UNO,1,10"); port.emit("00,20,NA,NA,100,0\r\n");
  port.emit("x".repeat(600)); port.emit("INVALID_SUFFIX\n@OK,STOP\n");
  await tick();
  assert.deepEqual(lines, ["UNO,1,1000,20,NA,NA,100,0", "@OK,STOP"]);
  assert.equal(errors.length, 1);
  await connection.disconnect();
});
test("un puerto no puede asignarse a las dos placas", async () => {
  const port = new FakePort("UNO"); const api = new FakeSerial(port, port);
  const a = new SerialConnection({ serialApi: api, resetMs: 0 });
  const b = new SerialConnection({ serialApi: api, resetMs: 0 });
  await a.connect(); await assert.rejects(b.connect(), /ya esta asignado/);
  assert.equal(a.connected, true); await a.disconnect();
});
test("ENABLE solo acepta la respuesta de su sensor y valor; errores de lectura no cancelan comandos", async () => {
  const port = new FakePort("UNO", { reply: false }); const api = new FakeSerial(port);
  const connection = new SerialConnection({ serialApi: api, resetMs: 0, timeoutMs: 100 });
  await connection.connect(); const reply = connection.sendCommand("ENABLE,SOUND,0");
  port.emit("@OK,ENABLE,PIR,0\n@OK,ENABLE,SOUND,1\n@ERR,READ,BH1750\n"); await tick();
  assert.ok(connection.pendingCommand);
  port.emit("@OK,ENABLE,SOUND,0\n"); assert.equal(await reply, "@OK,ENABLE,SOUND,0");
  await connection.disconnect();
});
test("un timeout de Uno y su desconexion no afectan comandos del Nano", async () => {
  const uno = new FakePort("UNO", { reply: false }); const nano = new FakePort("NANO");
  const api = new FakeSerial(uno, nano); let lost = 0;
  const a = new SerialConnection({ serialApi: api, resetMs: 0, timeoutMs: 15, onDisconnect: () => lost++ });
  const b = new SerialConnection({ serialApi: api, resetMs: 0 });
  await a.connect(); await b.connect();
  await assert.rejects(a.sendCommand("START"), /no respondio/);
  api.unplug(uno); await tick();
  assert.equal(lost, 1); assert.equal(b.connected, true);
  assert.equal(await b.sendCommand("INFO"), "@OK,INFO,2,NANO");
  await a.disconnect(); await b.disconnect();
});
test("errores de control y reinicios rechazan el comando pendiente", async () => {
  const port = new FakePort("UNO", { reply: false });
  const connection = new SerialConnection({ serialApi: new FakeSerial(port), resetMs: 0 });
  await connection.connect();
  const config = connection.sendCommand("CONFIG"); const failed = assert.rejects(config, /@ERR,CONFIG/);
  port.emit("@ERR,CONFIG,FORMAT\n"); await failed;
  const start = connection.sendCommand("START"); const reset = assert.rejects(start, /reinicio/);
  port.emit("@READY,2,UNO\n"); await reset;
  await connection.disconnect();
});

test("un fallo tardio de escritura no rechaza el siguiente comando", async () => {
  const connection = new SerialConnection({ timeoutMs: 15 });
  let rejectFirst;
  let writes = 0;
  connection.connected = true;
  connection.writer = { write() { return ++writes === 1 ? new Promise((_, reject) => { rejectFirst = reject; }) : Promise.resolve(); } };
  await assert.rejects(connection.sendCommand("START"), /no respondio/);
  const next = connection.sendCommand("STOP");
  rejectFirst(new Error("fallo anterior")); await tick();
  assert.equal(connection.pendingCommand.kind, "STOP");
  connection.processLine("@OK,STOP"); assert.equal(await next, "@OK,STOP");
});
