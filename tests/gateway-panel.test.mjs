import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiClient, ApiError } from '../js/api-client.js';
import { RemotePanel } from '../js/remote-panel.js';
import { FakeApi, deferred, snapshot } from './helpers/fake-api.mjs';

function setup() {
  const api = new FakeApi();
  api.states = ['UNO', 'NANO'].map(origin => snapshot(origin, { connected: false, configured: false, phase: 'disconnected', port: null }));
  api.healthData.transport = { mode: 'gateway', port: '/dev/serial0', connected: false };
  return [api, new RemotePanel(api)];
}

test('pasarela HTTP usa un solo control y no inicia capturas automaticamente', async () => {
  const calls = [];
  const api = new ApiClient({ fetchImpl: async (url, options) => {
    calls.push({ url, ...options });
    return new Response(JSON.stringify({ items: [] }));
  } });
  await api.gatewayControl('connect', { port: '/dev/serial0' });
  await api.gatewayControl('disconnect');
  assert.deepEqual(calls.map(item => item.url), ['/api/v1/gateway/connect', '/api/v1/gateway/disconnect']);
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].body), { port: '/dev/serial0' });
  assert.equal(calls[1].body, undefined);
});

test('una operacion del maestro bloquea ambas tarjetas y conserva configuracion explicita', async () => {
  const [api, panel] = setup();
  await panel.refresh();
  const pending = deferred(); let calls = 0;
  api.gatewayControl = async () => {
    calls += 1; await pending.promise;
    for (const state of api.states) Object.assign(state, { connected: true, phase: 'unconfigured', port: '/dev/serial0' });
  };
  const operation = panel.gatewayCommand('connect', '/dev/serial0');
  assert.equal(panel.boards.UNO.pending, 'connect');
  assert.equal(panel.boards.NANO.pending, 'connect');
  await assert.rejects(panel.command('UNO', 'start'), /Espera/);
  await assert.rejects(panel.gatewayCommand('connect', '/dev/serial0'), /Espera/);
  pending.resolve(); await operation;
  assert.equal(calls, 1);
  assert.ok(panel.boards.UNO.snapshot.connected && panel.boards.NANO.snapshot.connected);
  assert.equal(panel.boards.NANO.snapshot.configured, false);
  assert.equal(api.controls.length, 0);
  panel.stop(); assert.equal(calls, 1);
});

test('timeout del maestro consulta estados reales sin repetir la solicitud', async () => {
  const [api, panel] = setup(); await panel.refresh(); let calls = 0;
  api.gatewayControl = async () => {
    calls += 1;
    api.states[0].connected = true; api.states[0].phase = 'unconfigured';
    throw new ApiError('Respuesta perdida', { status: 0 });
  };
  await assert.rejects(panel.gatewayCommand('connect', '/dev/serial0'), /Respuesta perdida/);
  assert.equal(calls, 1);
  assert.equal(panel.boards.UNO.snapshot.connected, true);
  assert.equal(panel.boards.NANO.snapshot.connected, false);
  assert.equal(panel.boards.UNO.verifying, false);
  await panel.refresh(); assert.equal(calls, 1);
});
