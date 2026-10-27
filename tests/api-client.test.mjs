import assert from "node:assert/strict";
import test from "node:test";
import { ApiClient, ApiError } from "../js/api-client.js";

test("HTTP usa rutas relativas, filtros y cuerpos estrictos sin repetir comandos", async () => {
  const calls = [];
  const api = new ApiClient({ fetchImpl: async (url, options) => {
    calls.push({ url, ...options });
    return new Response(JSON.stringify({ items: [] }), { status: 200 });
  } });
  await api.samples({ capture_id: "uuid", order: "desc", limit: 300, origin: "" });
  await api.control("UNO", "connect", { port: "/dev/serial/by-id/placa 1" });
  await api.control("NANO", "sensors/pir", { enabled: false });
  await api.control("UNO", "start");
  assert.equal(calls[0].url, "/api/v1/samples?capture_id=uuid&order=desc&limit=300");
  assert.equal(calls[0].cache, "no-store");
  assert.equal(calls[1].method, "POST");
  assert.deepEqual(JSON.parse(calls[1].body), { port: "/dev/serial/by-id/placa 1" });
  assert.equal(calls[2].method, "PUT");
  assert.equal(calls[3].body, undefined);
  assert.equal(calls.length, 4);
  assert.equal(api.captureExportUrl("../extra"), "/api/v1/captures/..%2Fextra/export.csv");
  assert.equal(api.incidentExportUrl(), "/api/v1/incidents/export.csv");
});

for (const status of [404, 409, 422, 503, 504]) {
  test(`HTTP ${status} conserva el detalle y el código para la vista`, async () => {
    const data = { detail: "Detalle específico", storage: { ok: false } };
    const api = new ApiClient({ fetchImpl: async () => new Response(JSON.stringify(data), { status }) });
    await assert.rejects(api.boards(), error => error instanceof ApiError && error.status === status
      && error.message.includes("Detalle específico") && error.data.storage.ok === false);
  });
}

test("JSON de validación y respuesta HTML producen errores comprensibles", async () => {
  const api = new ApiClient({ fetchImpl: async () => new Response(JSON.stringify({ detail: [{ msg: "Pin inválido" }] }), { status: 422 }) });
  await assert.rejects(api.control("UNO", "config", {}), /Pin inválido/);
  api.fetchImpl = async () => new Response("<html>otro servidor</html>");
  await assert.rejects(api.health(), /JSON válida/);
});

test("timeout y pérdida de red abortan sin reintentar START", async () => {
  let calls = 0;
  const api = new ApiClient({ commandTimeout: 5, fetchImpl: async (_, { signal }) => {
    calls += 1;
    return new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
  } });
  await assert.rejects(api.control("UNO", "start"), error => error.status === 0 && /no respondió a tiempo/.test(error.message));
  assert.equal(calls, 1);
  api.fetchImpl = async () => { throw new TypeError("network"); };
  await assert.rejects(api.boards(), /red local/);
});
