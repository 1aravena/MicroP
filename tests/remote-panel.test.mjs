import assert from "node:assert/strict";
import test from "node:test";
import { RemotePanel, readingFor } from "../js/remote-panel.js";
import { ApiError } from "../js/api-client.js";
import { FakeApi, snapshot, sample, deferred } from "./helpers/fake-api.mjs";

function activeApi() {
  const api = new FakeApi();
  api.rows = Array.from({ length: 350 }, (_, i) => sample("UNO", "uno-activo", i + 1));
  api.rows.push(...Array.from({ length: 4 }, (_, i) => sample("NANO", "nano-activo", 1001 + i, i + 1)));
  api.states = [snapshot("UNO", { phase: "capturing", captureId: "uno-activo", sampleCount: 350, latestSample: api.rows[349] }),
    snapshot("NANO", { phase: "capturing", captureId: "nano-activo", sampleCount: 4, latestSample: api.rows.at(-1) })];
  return api;
}

test("rehidrata capturas del servidor, conserva 300 filas por placa y usa recepción común", async () => {
  const api = activeApi();
  const panel = new RemotePanel(api, { now: () => 1000 });
  await panel.refresh();
  const uno = panel.boards.UNO;
  assert.equal(uno.snapshot.captureId, "uno-activo");
  assert.equal(uno.snapshot.sampleCount, 350);
  assert.equal(uno.rows.length, 300);
  assert.equal(uno.rows[0].sequence, 51);
  assert.equal(uno.cursor, 350); // No usar el cursor descendente (51) para recibir nuevas muestras.
  assert.equal(panel.boards.NANO.rows.length, 4);
  assert.equal(api.controls.length, 0);
  assert.equal(panel.chartRows[0].deviceTimeMs, 51000);
  assert.equal(panel.chartRows[0].timeMs, Date.parse(uno.rows[0].receivedAt));
  const next = sample("UNO", "uno-activo", 351);
  api.rows.push(next);
  Object.assign(api.states[0], { sampleCount: 351, latestSample: next });
  await panel.refresh();
  assert.equal(uno.rows.length, 300);
  assert.equal(uno.rows[0].id, 52);
  assert.equal(uno.cursor, 351);
  assert.equal(api.queries.at(-1).after_id, 350);
});

test("otra captura reinicia únicamente la ventana de su placa", async () => {
  const api = activeApi();
  const panel = new RemotePanel(api, { now: () => 1000 });
  await panel.refresh();
  const nano = structuredClone(panel.boards.NANO.rows);
  Object.assign(api.states[0], { captureId: "uno-nuevo", latestSample: null, sampleCount: 0 });
  await panel.refresh();
  assert.deepEqual(panel.boards.UNO.rows, []);
  assert.deepEqual(panel.boards.NANO.rows, nano);
  assert.equal(panel.boards.UNO.snapshot.captureId, "uno-nuevo");
});

test("deduplica muestras repetidas y recupera una ventana reciente después de suspensión", async () => {
  const api = activeApi();
  let clock = 1000;
  const panel = new RemotePanel(api, { now: () => clock });
  await panel.refresh();
  api.rows.push(...Array.from({ length: 400 }, (_, i) => sample("UNO", "uno-activo", 351 + i)));
  api.rows.push(api.rows.at(-1));
  Object.assign(api.states[0], { sampleCount: 750, latestSample: api.rows.at(-1) });
  clock = 9000;
  await panel.refresh();
  assert.ok(panel.boards.UNO.rows.length <= 300);
  assert.equal(panel.boards.UNO.rows.at(-1).id, 750);
  assert.equal(new Set(panel.boards.UNO.rows.map(row => row.id)).size, panel.boards.UNO.rows.length);
});

test("borradores no alteran el servidor, sobreviven al polling y bloquean START", async () => {
  const api = new FakeApi();
  const panel = new RemotePanel(api);
  await panel.refresh();
  panel.editConfig("UNO", draft => { draft.hcTrigger = 9; });
  await panel.refresh();
  assert.equal(panel.boards.UNO.draft.hcTrigger, 9);
  assert.equal(panel.boards.UNO.snapshot.config.hcTrigger, 4);
  assert.equal(panel.boards.UNO.dirty, true);
  await assert.rejects(panel.command("UNO", "start"), /Aplica los cambios/);
  const bad = structuredClone(panel.boards.UNO.draft);
  bad.hcTrigger = bad.hcEcho;
  await assert.rejects(panel.command("UNO", "config", bad), /repetido/);
  assert.equal(api.controls.length, 0);
  await panel.command("UNO", "config", panel.boards.UNO.draft);
  assert.equal(panel.boards.UNO.dirty, false);
  assert.equal(panel.boards.UNO.snapshot.config.hcTrigger, 9);
});

test("un cambio desde otra pestaña reconcilia el borrador y el estado compartido", async () => {
  const api = new FakeApi();
  const panel = new RemotePanel(api);
  await panel.refresh();
  panel.editConfig("UNO", draft => { draft.hcTrigger = 9; });
  api.states[0].config.hcTrigger = 10;
  await panel.refresh();
  assert.equal(panel.boards.UNO.dirty, false);
  assert.equal(panel.boards.UNO.draft.hcTrigger, 10);
  assert.match(panel.boards.UNO.error, /estado cambió/);
});

test("una respuesta de polling anterior a STOP no restaura una captura antigua", async () => {
  const api = activeApi();
  const panel = new RemotePanel(api);
  await panel.refresh();
  const old = structuredClone(api.states);
  const gate = deferred();
  const boards = api.boards.bind(api);
  let once = true;
  api.boards = () => { if (once) { once = false; return gate.promise; } return boards(); };
  const poll = panel.refresh();
  const command = panel.command("UNO", "stop");
  await Promise.resolve();
  gate.resolve({ items: old });
  await Promise.all([poll, command]);
  assert.equal(panel.boards.UNO.snapshot.phase, "configured");
  assert.equal(panel.boards.NANO.snapshot.phase, "capturing");
});

test("control pendiente bloquea su placa pero permite operar la otra", async () => {
  const api = new FakeApi();
  const panel = new RemotePanel(api);
  await panel.refresh();
  const gate = deferred();
  const control = api.control.bind(api);
  api.control = async (origin, action, body) => {
    if (origin === "UNO") await gate.promise;
    return control(origin, action, body);
  };
  const uno = panel.command("UNO", "start");
  await assert.rejects(panel.command("UNO", "start"), /Espera/);
  await panel.command("NANO", "start");
  assert.equal(panel.boards.NANO.snapshot.phase, "capturing");
  assert.equal(panel.boards.UNO.pending, "start");
  gate.resolve(); await uno;
  assert.equal(api.controls.length, 2);
});

test("fallo de red no reproduce comandos y recuperar o cerrar la vista no detiene capturas", async () => {
  const api = activeApi();
  const panel = new RemotePanel(api);
  await panel.refresh();
  api.control = async (origin, action) => {
    api.controls.push({ origin, action });
    api.offline = true;
    throw new ApiError("Sin red");
  };
  await assert.rejects(panel.command("UNO", "stop"), /Sin red/);
  assert.equal(panel.online, false);
  api.offline = false;
  await panel.refresh(true);
  assert.equal(panel.online, true);
  assert.equal(panel.boards.UNO.snapshot.phase, "capturing");
  assert.equal(api.controls.length, 1);
  panel.stop();
  await panel.refresh();
  assert.equal(api.controls.length, 1);
});

test("fallo de almacenamiento bloquea controles y conserva el estado de servicio accesible", async () => {
  const api = new FakeApi();
  api.healthData = { ok: false, storage: { ok: false, error: "Disco lleno" } };
  const panel = new RemotePanel(api);
  await panel.refresh();
  assert.equal(panel.online, true);
  assert.equal(panel.storageOK, false);
  await assert.rejects(panel.command("UNO", "start"), /almacenamiento/);
  assert.equal(api.controls.length, 0);
});

test("un timeout bloquea nuevos controles hasta recibir un estado actualizado", async () => {
  const api = new FakeApi();
  const panel = new RemotePanel(api);
  await panel.refresh();
  const gate = deferred();
  api.boards = () => gate.promise;
  api.control = async () => { throw new ApiError("Sin ACK", { status: 504 }); };
  const first = panel.command("UNO", "start");
  // El comando ya falló, pero la comprobación HTTP sigue pendiente.
  await Promise.resolve(); await Promise.resolve();
  assert.equal(panel.boards.UNO.verifying, true);
  await assert.rejects(panel.command("UNO", "start"), /verifique el estado/);
  gate.resolve({ items: api.states });
  await assert.rejects(first, /Sin ACK/);
  assert.equal(panel.boards.UNO.verifying, false);
});

test("lista de 20 capturas pagina sin saltos ni mezclar UUID y cursor", async () => {
  const api = new FakeApi();
  api.captureRows = Array.from({ length: 45 }, (_, i) => ({ id: `uuid-${i + 1}`, cursor: i + 1, origin: i % 2 ? "NANO" : "UNO" }));
  const panel = new RemotePanel(api);
  await panel.refresh();
  assert.equal(panel.captures.length, 20);
  assert.equal(panel.captures[0].id, "uuid-45");
  assert.equal(panel.captureNext, 26);
  await panel.changeCapturePage(1);
  assert.equal(panel.captures[0].id, "uuid-25");
  await panel.changeCapturePage(1);
  assert.equal(panel.captures.length, 5);
  assert.equal(panel.captureHasMore, false);
  await panel.changeCapturePage(-1);
  assert.equal(panel.captures[0].id, "uuid-25");
  await panel.setCaptureOrigin("UNO");
  assert.equal(panel.capturePage, 0);
  assert.ok(panel.captures.every(item => item.origin === "UNO"));
});

test("filtro nuevo descarta una respuesta histórica que llega tarde", async () => {
  const api = new FakeApi();
  const panel = new RemotePanel(api);
  const first = deferred();
  api.captures = query => query.origin === "UNO" ? first.promise : Promise.resolve({ items: [{ id: "nano", cursor: 2, origin: "NANO" }] });
  const uno = panel.setCaptureOrigin("UNO");
  await panel.setCaptureOrigin("NANO");
  first.resolve({ items: [{ id: "uno", cursor: 1, origin: "UNO" }] });
  await uno;
  assert.equal(panel.captures[0].origin, "NANO");
});

test("refrescos simultáneos comparten un único ciclo", async () => {
  const api = new FakeApi();
  const gate = deferred();
  let calls = 0;
  api.boards = () => { calls += 1; return gate.promise; };
  const panel = new RemotePanel(api);
  const first = panel.refresh();
  const second = panel.refresh(true);
  assert.equal(first, second);
  gate.resolve({ items: api.states });
  await first;
  assert.equal(calls, 1);
});

test("el temporizador conserva el contexto global exigido por los navegadores", async () => {
  const original = globalThis.setTimeout;
  const api = new FakeApi();
  const panel = new RemotePanel(api);
  try {
    globalThis.setTimeout = function () {
      assert.equal(this, globalThis);
      return 12345;
    };
    await panel.start();
    assert.equal(panel.timer, 12345);
  } finally {
    globalThis.setTimeout = original;
    panel.stop();
  }
  assert.equal(api.controls.length, 0);
});

test("lecturas distinguen red, placa, almacenamiento, NA y muestra antigua", () => {
  const state = snapshot("UNO", { phase: "capturing", latestSample: sample("UNO", "x", 1) });
  assert.equal(readingFor(state, "hc", false), "Sin comunicación");
  assert.equal(readingFor({ ...state, connected: false }, "hc", true), "Sin conexión");
  assert.equal(readingFor({ ...state, stale: true }, "hc", true), "Sin datos recientes");
  assert.equal(readingFor({ ...state, phase: "configured" }, "hc", true), "Detenido");
  assert.equal(readingFor({ ...state, phase: "storage_error" }, "hc", true), "Error de almacenamiento");
  assert.equal(readingFor({ ...state, latestSample: { distanceCm: null } }, "hc", true), "Lectura no disponible");
  assert.equal(readingFor(state, "hc", true), "20.00 cm");
  assert.equal(readingFor(state, "sound", true), "DO = 0");
});
