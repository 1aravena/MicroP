import { defaultConfig, ROLES } from "../../js/protocol.js";
import { ApiError } from "../../js/api-client.js";

export function snapshot(origin, values = {}) {
  return { origin, phase: "configured", connected: true, configured: true, busy: false,
    config: defaultConfig(origin), captureId: null, sampleCount: 0, latestSample: null,
    lastReceivedAt: null, ageMs: null, stale: false, lastError: null, port: `${origin}_PORT`, ...values };
}

export function sample(origin, captureId, id, sequence = id) {
  return { origin, captureId, id, sequence, timeMs: sequence * 1000,
    receivedAt: new Date(Date.UTC(2026, 9, 27, 12, 0, 0) + id * 1000).toISOString(),
    distanceCm: origin === "UNO" ? 20 : null, lux: origin === "UNO" ? 100 : null,
    pir: origin === "NANO" ? 1 : null, radar: origin === "NANO" ? 0 : null,
    sound: origin === "UNO" ? 0 : null, enabled: defaultConfig(origin).enabled };
}

export function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

// Solo pruebas. No existe fábrica simulada en el frontend de producción.
export class FakeApi {
  constructor() {
    this.states = ROLES.map(origin => snapshot(origin));
    this.rows = [];
    this.captureRows = [];
    this.events = [];
    this.controls = [];
    this.queries = [];
    this.offline = false;
    this.healthData = { ok: true, storage: { ok: true } };
  }
  async boards() {
    if (this.offline) throw new ApiError("Sin red");
    return { items: structuredClone(this.states) };
  }
  async ports() { return { items: [{ device: "UNO_PORT" }, { device: "NANO_PORT" }] }; }
  async health() {
    if (!this.healthData.ok) throw new ApiError("Fallo SQLite", { status: 503, data: this.healthData });
    return structuredClone(this.healthData);
  }
  async incidents() { return { items: structuredClone(this.events.slice(-15).reverse()) }; }
  async captures(query) {
    const items = this.captureRows.filter(item => (!query.origin || item.origin === query.origin)
      && (!query.after_id || item.cursor < query.after_id)).sort((a, b) => b.cursor - a.cursor).slice(0, query.limit);
    return { items: structuredClone(items), nextCursor: items.at(-1)?.cursor ?? query.after_id ?? 0 };
  }
  async samples(query) {
    this.queries.push(structuredClone(query));
    const desc = query.order === "desc";
    const items = this.rows.filter(item => item.captureId === query.capture_id && item.origin === query.origin
      && (!query.after_id || (desc ? item.id < query.after_id : item.id > query.after_id)))
      .sort((a, b) => desc ? b.id - a.id : a.id - b.id).slice(0, query.limit);
    return { items: structuredClone(items), nextCursor: items.at(-1)?.id ?? query.after_id ?? 0 };
  }
  async control(origin, action, body) {
    this.controls.push({ origin, action, body: structuredClone(body) });
    const state = this.states.find(item => item.origin === origin);
    if (action === "config") state.config = structuredClone(body);
    if (action === "start") {
      if (state.phase === "capturing") throw new ApiError("Ya capturando", { status: 409 });
      Object.assign(state, { phase: "capturing", captureId: `${origin}-nuevo`, sampleCount: 0, latestSample: null });
    }
    if (action === "stop") state.phase = "configured";
    if (action === "disconnect") Object.assign(state, { phase: "disconnected", connected: false });
    return structuredClone(state);
  }
}
