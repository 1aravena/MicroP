import assert from 'node:assert/strict';
import test from 'node:test';
import { AccessPanel } from '../js/access.js';
import { ApiError, ApiClient } from '../js/api-client.js';

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function fixture() {
  const calls = [];
  const rows = Array.from({ length: 23 }, (_, i) => ({ id: String(23-i), cursor: 23-i, decision: 'allowed' }));
  const api = {
    accessStatus: async () => ({ active: true, ready: true }), mlStatus: async () => ({ state: 'no_model' }),
    accessAttempts: async ({after_id, limit}) => ({ items: rows.filter(row => !after_id || row.cursor < after_id).slice(0, limit) }),
    predictions: async () => ({ items: [] }),
    accessAttempt: async id => ({ id, decision: 'allowed', signal: 'confirmed' }),
    submitAccess: async body => { calls.push(['attempt', body.requestId]); return { id: body.requestId, decision: 'allowed' }; },
    accessMode: async action => { calls.push(['mode', action]); return {}; },
  };
  const model = new AccessPanel(api, { createId: () => 'request' });
  return { api, model, calls };
}

test('recarga recupera modo y ML sin solicitar acceso, iniciar capturas ni detener al cerrar', async () => {
  const { model, calls } = fixture();
  await model.refresh();
  assert.equal(model.status.active, true);
  assert.equal(model.ml.state, 'no_model');
  model.stop();
  assert.deepEqual(calls, []);
});

test('el PIN no queda en el estado serializable y un rechazo conserva la decision del servidor', async () => {
  const { api, model } = fixture();
  await model.refresh();
  const result = { id: 'request', decision: 'denied', authorization: 'deny', signal: 'confirmed' };
  api.submitAccess = async () => { throw new ApiError('PIN rechazado', { status: 403, data: { attempt: result } }); };
  await assert.rejects(model.attempt('123456'), /rechazado/);
  assert.deepEqual(model.lastResult, result);
  assert.equal(JSON.stringify(model).includes('123456'), false);
});

test('timeout consulta el identificador anterior sin repetir POST y bloquea doble envio', async () => {
  const { api, model, calls } = fixture();
  await model.refresh();
  const pending = deferred();
  api.submitAccess = async body => { calls.push(['attempt', body.requestId]); await pending.promise; throw new ApiError('Sin respuesta'); };
  const first = model.attempt('123456');
  await assert.rejects(model.attempt('123456'), /Espera/);
  pending.resolve();
  await assert.rejects(first, /Sin respuesta/);
  assert.equal(model.lastResult.decision, 'allowed');
  assert.deepEqual(calls, [['attempt', 'request']]);
});

test('una respuesta anterior a desactivar no restaura estado antiguo', async () => {
  const { api, model } = fixture();
  await model.refresh();
  const pending = deferred();
  api.accessStatus = () => pending.promise;
  const earlier = model.refresh();
  api.accessMode = async () => { api.accessStatus = async () => ({ active: false, ready: false }); return {}; };
  const stopping = model.mode('disable');
  pending.resolve({ active: true, ready: true });
  await Promise.all([earlier, stopping]);
  assert.equal(model.status.active, false);
});

test('historial pagina de veinte conservando el registro de anticipacion', async () => {
  const { model } = fixture();
  await model.refresh();
  assert.equal(model.attempts.at(-1).cursor, 4);
  await model.page('attempts', 1);
  assert.deepEqual(model.attempts.map(row => row.cursor), [3,2,1]);
});

test('cliente HTTP envia PIN solo en cuerpo POST y exporta sin credenciales', async () => {
  const calls = [];
  const api = new ApiClient({ fetchImpl: async (url, options) => { calls.push([url, options]); return new Response('{}'); } });
  await api.submitAccess({ requestId: 'r', pin: '123456' });
  assert.equal(calls[0][0], '/api/v1/access/attempts');
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(JSON.parse(calls[0][1].body).pin, '123456');
  assert.equal(api.accessExportUrl(), '/api/v1/access/export.csv');
});
