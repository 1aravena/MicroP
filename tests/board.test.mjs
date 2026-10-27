import assert from "node:assert/strict";
import test from "node:test";
import { BoardController } from "../js/board.js";
import { SerialConnection } from "../js/serial.js";
import { defaultConfig, buildCsv } from "../js/protocol.js";
import { FakePort, FakeSerial, tick } from "./helpers/fake-serial.mjs";

function setup(origin = "UNO", options = {}) {
  const port = new FakePort(options.firmwareOrigin ?? origin, options);
  const api = new FakeSerial(port); const incidents = []; let capture = 0; let clock = 1100;
  const board = new BoardController(origin, { transportFactory: handlers => new SerialConnection({ ...handlers, serialApi: api, resetMs: 0, timeoutMs: 30 }),
    epoch: 100, clock: () => clock++, now: () => new Date("2026-10-27T01:00:00Z"), id: () => `captura-${++capture}`,
    onIncident: incident => incidents.push(incident) });
  return { board, port, api, incidents };
}
async function capturing(board) { await board.connect(); await board.configure(defaultConfig(board.origin)); await board.start(); }

test("identifica y detiene antes de configurar; rechaza rol o version incorrectos", async () => {
  for (const options of [{ firmwareOrigin: "NANO" }, { version: 1 }]) {
    const { board } = setup("UNO", options);
    await assert.rejects(board.connect()); assert.equal(board.connected, false);
  }
  const { board, port } = setup(); await board.connect();
  assert.deepEqual(port.commands, ["INFO", "STOP"]);
  await assert.rejects(board.start(), /configuracion/);
  await board.disconnect();
});
test("conserva parciales, detecta duplicados/saltos y reinicio obliga a configurar", async () => {
  const { board, port, incidents } = setup(); await capturing(board);
  port.emit("UNO,1,1000,NA,NA,NA,100,0\nUNO,1,1000,20,NA,NA,100,0\nUNO,3,3000,25,NA,NA,100,1\n"); await tick();
  assert.equal(board.rows.length, 2); assert.equal(board.rows[0].distanceCm, null);
  assert.equal(board.rows[0].deviceTimeMs, 1000); assert.equal(board.rows[0].captureId, "captura-1");
  assert.ok(incidents.some(item => item.type === "GAP")); assert.ok(incidents.some(item => item.type === "INVALID"));
  port.emit("@READY,2,UNO\n"); await tick();
  assert.equal(board.configured, false); assert.equal(board.phase, "unconfigured");
  await assert.rejects(board.start()); await board.disconnect();
});
test("cada START conserva las capturas previas para exportacion", async () => {
  const { board, port } = setup(); await capturing(board);
  port.emit("UNO,1,1000,20,NA,NA,100,0\n"); await tick(); await board.stop(); await board.start();
  port.emit("UNO,1,1000,30,NA,NA,100,1\n"); await tick();
  assert.equal(board.rows.length, 1); assert.equal(board.allRows.length, 2);
  assert.deepEqual(board.allRows.map(row => row.captureId), ["captura-1", "captura-2"]);
  assert.match(buildCsv(board.allRows), /captura-1,UNO,1,1000,20/);
  await board.disconnect(); assert.equal(board.allRows.length, 2);
});
test("el ACK de ENABLE cambia la mascara antes de procesar la siguiente fila", async () => {
  const { board, port } = setup(); await capturing(board);
  port.onCommand = (command, device) => {
    if (command === "ENABLE,SOUND,0") {
      device.emit("UNO,1,1000,20,NA,NA,100,1\n@OK,ENABLE,SOUND,0\nUNO,2,2000,20,NA,NA,100,NA\n"); return false;
    }
  };
  await board.enable("sound", false); await tick();
  assert.equal(board.rows.length, 2); assert.equal(board.rows[0].enabled.sound, true);
  assert.equal(board.rows[1].enabled.sound, false); assert.equal(board.rows[1].sound, null);
  await board.disconnect();
});
test("un START sin ACK invalida el estado y permite recuperar mediante STOP y CONFIG", async () => {
  const { board, port } = setup(); await board.connect(); await board.configure(defaultConfig("UNO"));
  port.onCommand = command => command === "START" ? false : undefined;
  await assert.rejects(board.start(), /no respondio/);
  assert.equal(board.configured, false); assert.equal(board.captures.length, 0);
  await board.configure(defaultConfig("UNO")); assert.equal(board.configured, true);
  await board.disconnect();
});
test("un error CONFIG conserva la ultima configuracion confirmada", async () => {
  const { board, port } = setup(); await board.connect(); await board.configure(defaultConfig("UNO"));
  port.onCommand = (command, device) => {
    if (command.startsWith("CONFIG")) { device.emit("@ERR,CONFIG,BH1750_NOT_FOUND\n"); return false; }
  };
  const next = defaultConfig("UNO"); next.hcTrigger = 10;
  await assert.rejects(board.configure(next), /BH1750/); assert.equal(board.config.hcTrigger, 4);
  assert.equal(board.configured, false); await board.disconnect();
});
