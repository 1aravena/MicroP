import assert from "node:assert/strict";
import test from "node:test";
import { Experiments } from "../js/experiments.js";
import { ApiClient } from "../js/api-client.js";

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const session = (id, source = "simulated") => ({ id, cursor: Number(id) || 1, name: id, partition: "train", source, status: "closed" });
function fixture() {
  const calls = [];
  const sessions = Array.from({ length: 25 }, (_, index) => session(String(25 - index)));
  const api = {
    scenarios: async () => ({ items: [], acquisitionMode: "simulated" }),
    activeTrial: async () => ({ trial: null }),
    datasetSummary: async () => ({ groups: [], real: { train: 0, test: 0 } }),
    sessions: async ({ after_id = 0, limit = 21 }) => ({ items: sessions.filter(row => !after_id || row.cursor < after_id).slice(0, limit) }),
    session: async id => session(id),
    trials: async () => ({ items: [] }),
    trial: async id => ({ id, sessionId: "25" }),
    createSession: async data => { calls.push(["create", data]); return session("26"); },
    createTrial: async (id, data) => { calls.push(["prepare", id, data]); return { id: "trial", sessionId: id }; },
    trialAction: async (id, action, data) => { calls.push([action, id, data]); return { id, sessionId: "25" }; },
    closeSession: async id => { calls.push(["close", id]); return session(id); },
  };
  return { api, calls, model: new Experiments(api) };
}

test("recupera contexto del ensayo activo sin crear capturas ni detener al cerrar", async () => {
  const { api, model, calls } = fixture();
  api.activeTrial = async () => ({ trial: { id: "trial", sessionId: "25", status: "running" } });
  await model.refresh();
  assert.equal(model.selectedSessionId, "25");
  await model.refresh();
  assert.equal(model.selectedTrial.id, "trial");
  assert.equal(model.reserved, true);
  model.stop();
  assert.deepEqual(calls, []);
});

test("sesiones paginan de veinte sin saltar el registro de anticipación", async () => {
  const { model } = fixture();
  await model.refresh();
  assert.equal(model.sessions.length, 20);
  assert.equal(model.sessions.at(-1).id, "6");
  assert.equal(model.sessionPage.more, true);
  await model.page("sessions", 1);
  assert.deepEqual(model.sessions.map(row => row.id), ["5", "4", "3", "2", "1"]);
  await model.page("sessions", -1);
  assert.equal(model.sessions[0].id, "25");
});

test("una selección nueva descarta la respuesta anterior y comparte consultas simultáneas", async () => {
  const { api, model } = fixture();
  const pending = deferred();
  api.session = id => id === "old" ? pending.promise : Promise.resolve(session(id));
  model.selectedSessionId = "old";
  const old = model.refresh();
  assert.equal(model.refresh(), old);
  const changed = model.selectSession("new");
  pending.resolve(session("old"));
  await changed;
  assert.equal(model.selectedSession.id, "new");
});

test("un timeout de START consulta estado sin repetir el comando y bloquea doble envío", async () => {
  const { api, model, calls } = fixture();
  await model.refresh();
  const pending = deferred();
  api.trialAction = async (id, action) => { calls.push([action, id]); await pending.promise; throw new Error("Timeout; verificar estado"); };
  const first = model.action("trial", "start");
  assert.equal(model.busy, true);
  await assert.rejects(model.action("trial", "start"), /Espera la operación/);
  pending.resolve();
  await assert.rejects(first, /Timeout/);
  assert.deepEqual(calls, [["start", "trial"]]);
  assert.equal(model.busy, false);
  assert.match(model.actionError, /Timeout/);
});

test("selección de exportación persiste y exige sesiones cerradas de una sola procedencia", async () => {
  const { model } = fixture();
  model.toggleExport(session("25"), true);
  await model.refresh(); await model.page("sessions", 1);
  assert.deepEqual(model.exportIds, ["25"]);
  assert.throws(() => model.toggleExport(session("24", "real"), true), /paquetes separados/);
  assert.throws(() => model.toggleExport({ ...session("23"), status: "open" }, true), /cerradas/);
  model.toggleExport(session("25"), false);
  assert.equal(model.exportIds.length, 0);
});

test("pérdida de conexión conserva los datos visibles y permite recuperarse sin comandos", async () => {
  const { api, model, calls } = fixture();
  await model.refresh();
  api.activeTrial = async () => { throw new Error("Sin comunicación"); };
  await model.refresh();
  assert.equal(model.online, false);
  assert.equal(model.sessions.length, 20);
  await assert.rejects(model.action("trial", "start"), /comunicación/);
  api.activeTrial = async () => ({ trial: null });
  await model.refresh();
  assert.equal(model.canControl, true);
  assert.deepEqual(calls, []);
});

test("cliente de ensayos usa cuerpos y parámetros repetidos para el ZIP", async () => {
  const calls = [];
  const api = new ApiClient({ fetchImpl: async (url, options) => { calls.push([url, options]); return new Response("{}"); } });
  await api.createSession({ name: "A", partition: "train", source: "simulated" });
  await api.createTrial("id", { scenario: "zona_vacia" });
  await api.trialAction("trial", "review", { confirmed: false, notes: "No realizado" });
  assert.equal(calls[0][0], "/api/v1/sessions");
  assert.equal(calls[1][0], "/api/v1/sessions/id/trials");
  assert.equal(calls[2][1].method, "POST");
  assert.equal(JSON.parse(calls[2][1].body).confirmed, false);
  assert.equal(api.datasetExportUrl(["one", "two"]), "/api/v1/dataset/export.zip?session_id=one&session_id=two");
});
