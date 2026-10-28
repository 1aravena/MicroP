import { ROLES, SENSOR_KEYS, defaultConfig, validateConfig } from "./protocol.js";

const configFields = ["origin", "hcTrigger", "hcEcho", "pirPin", "radarPin", "soundPin"];
export function sameConfig(a, b) {
  return Boolean(a && b && configFields.every(key => a[key] === b[key]) && SENSOR_KEYS.every(key => a.enabled?.[key] === b.enabled?.[key]));
}

function initialBoard(origin) {
  const config = defaultConfig(origin);
  return { snapshot: { origin, phase: "disconnected", connected: false, configured: false, busy: false, config,
    captureId: null, sampleCount: 0, latestSample: null, ageMs: null, stale: false, lastError: null, port: null },
    draft: structuredClone(config), dirty: false, pending: null, verifying: false, revision: 0, error: "", sampleError: "",
    rows: [], cursor: 0, windowCaptureId: null, windowReady: false, samplesAt: 0 };
}

export function readingFor(snapshot, key, online) {
  if (!online) return "Sin comunicación";
  if (snapshot.phase === "storage_error") return "Error de almacenamiento";
  if (!snapshot.connected) return "Sin conexión";
  if (!snapshot.configured) return "Configuración pendiente";
  if (!snapshot.config.enabled[key]) return "Desactivado";
  if (snapshot.phase !== "capturing") return "Detenido";
  if (snapshot.stale) return "Sin datos recientes";
  if (!snapshot.latestSample) return "Esperando muestra";
  const field = { hc: "distanceCm", lux: "lux", sound: "sound", pir: "pir", radar: "radar" }[key];
  const value = snapshot.latestSample[field];
  if (value == null) return "Lectura no disponible";
  return key === "hc" ? `${value.toFixed(2)} cm` : key === "lux" ? `${value.toFixed(2)} lux`
    : key === "sound" ? `DO = ${value}` : value ? "Movimiento (1)" : "Sin detección (0)";
}

// No abre puertos ni crea capturas: sincroniza exclusivamente datos del backend.
export class RemotePanel {
  constructor(api, { onChange = () => {}, now = () => Date.now(), interval = 1000,
    schedule = (task, delay) => globalThis.setTimeout(task, delay), cancel = timer => globalThis.clearTimeout(timer) } = {}) {
    Object.assign(this, { api, onChange, now, interval, schedule, cancel });
    this.boards = Object.fromEntries(ROLES.map(origin => [origin, initialBoard(origin)]));
    this.online = false;
    this.health = null;
    this.ports = [];
    this.portsLoaded = false;
    this.portsBusy = false;
    this.portsRequest = 0;
    this.errors = { connection: "", health: "", ports: "", captures: "", incidents: "" };
    this.captures = [];
    this.incidents = [];
    this.captureOrigin = "";
    this.captureCursors = [0];
    this.capturePage = 0;
    this.captureNext = 0;
    this.captureHasMore = false;
    this.captureBusy = false;
    this.captureRequest = 0;
    this.metadataAt = null;
    this.inFlight = null;
    this.running = false;
    this.disposed = false;
    this.timer = null;
    this.connectionVersion = 0;
    this.gatewayPending = null;
  }

  emit() { if (!this.disposed) this.onChange(this); }
  get storageOK() { return this.health?.ok === true; }

  applySnapshot(snapshot, { confirmedConfig = false } = {}) {
    const board = this.boards[snapshot.origin];
    if (!board) return;
    const serverChanged = !sameConfig(board.snapshot.config, snapshot.config);
    if (confirmedConfig || !board.dirty || serverChanged || ["capturing", "starting"].includes(snapshot.phase)) {
      if (board.dirty && !confirmedConfig && !sameConfig(board.draft, snapshot.config)) {
        board.error = "El estado cambió en la Raspberry. Se actualizó la configuración mostrada.";
      }
      board.draft = structuredClone(snapshot.config);
      board.dirty = false;
    }
    if (snapshot.captureId && snapshot.captureId !== board.windowCaptureId) {
      board.rows = [];
      board.cursor = 0;
      board.windowReady = false;
      board.windowCaptureId = snapshot.captureId;
    }
    board.snapshot = snapshot;
    board.verifying = false;
  }

  editConfig(origin, edit) {
    const board = this.boards[origin];
    if (!this.online || board.pending || board.verifying || board.snapshot.busy || !board.snapshot.connected || board.snapshot.phase === "capturing") {
      throw new Error("Espera o detén la captura antes de editar la configuración.");
    }
    const next = structuredClone(board.draft);
    edit(next);
    board.draft = next;
    board.dirty = !sameConfig(next, board.snapshot.config);
    board.error = "";
    this.emit();
  }

  async refreshPorts() {
    const request = ++this.portsRequest;
    this.portsBusy = true;
    this.emit();
    try {
      const data = await this.api.ports();
      if (this.disposed || request !== this.portsRequest) return;
      this.ports = data.items;
      this.portsLoaded = true;
      this.errors.ports = "";
    } catch (error) { if (request === this.portsRequest) this.errors.ports = error.message; }
    finally {
      if (request === this.portsRequest) { this.portsBusy = false; this.emit(); }
    }
  }

  async loadCaptures() {
    const request = ++this.captureRequest;
    const query = { origin: this.captureOrigin, after_id: this.captureCursors[this.capturePage], order: "desc", limit: 21 };
    this.captureBusy = true;
    this.emit();
    try {
      const data = await this.api.captures(query);
      if (this.disposed || request !== this.captureRequest) return;
      this.captures = data.items.slice(0, 20);
      this.captureHasMore = data.items.length > 20;
      this.captureNext = this.captures.at(-1)?.cursor ?? query.after_id;
      this.errors.captures = "";
    } catch (error) { if (request === this.captureRequest) this.errors.captures = error.message; }
    finally {
      if (request === this.captureRequest) { this.captureBusy = false; this.emit(); }
    }
  }

  async setCaptureOrigin(origin) {
    if (origin && !ROLES.includes(origin)) throw new Error("Origen desconocido.");
    this.captureOrigin = origin;
    this.captureCursors = [0];
    this.capturePage = 0;
    this.captures = [];
    this.captureHasMore = false;
    return this.loadCaptures();
  }

  async changeCapturePage(direction) {
    if (this.captureBusy) return;
    if (direction === 1 && this.captureHasMore) {
      this.captureCursors = this.captureCursors.slice(0, this.capturePage + 1);
      this.captureCursors.push(this.captureNext);
      this.capturePage += 1;
    } else if (direction === -1 && this.capturePage > 0) this.capturePage -= 1;
    else return;
    return this.loadCaptures();
  }

  async loadHealth() {
    try {
      const data = await this.api.health();
      if (this.disposed) return;
      this.health = data;
      this.errors.health = "";
    } catch (error) {
      if (error.data?.storage) this.health = error.data;
      else this.health = null;
      this.errors.health = error.message;
    }
  }

  async loadIncidents() {
    try {
      const data = await this.api.incidents({ order: "desc", limit: 15 });
      if (this.disposed) return;
      this.incidents = data.items;
      this.errors.incidents = "";
    } catch (error) { this.errors.incidents = error.message; }
  }

  async loadSamples(origin, revision, recover) {
    const board = this.boards[origin];
    const captureId = board.snapshot.captureId;
    if (!captureId || board.pending) return;
    const current = () => !this.disposed && revision === board.revision && board.snapshot.captureId === captureId && !board.pending;
    const tail = recover || !board.windowReady || this.now() - board.samplesAt > 5000;
    if (!tail && (board.snapshot.latestSample?.id ?? 0) <= board.cursor) return;
    try {
      const query = { origin, capture_id: captureId, limit: 300, order: tail ? "desc" : "asc", after_id: tail ? 0 : board.cursor };
      let data = await this.api.samples(query);
      if (!current()) return;
      // Si la pestaña estuvo suspendida, saltar a la ventana reciente; el CSV conserva todo.
      let replace = tail;
      if (!tail && data.items.length === 300) {
        data = await this.api.samples({ origin, capture_id: captureId, limit: 300, order: "desc" });
        if (!current()) return;
        replace = true;
      }
      const rows = data.items.filter(item => item.captureId === captureId && item.origin === origin);
      const unique = new Map((replace ? [] : board.rows).map(item => [item.id, item]));
      for (const item of rows) unique.set(item.id, item);
      board.rows = [...unique.values()].sort((a, b) => a.id - b.id).slice(-300);
      board.cursor = board.rows.at(-1)?.id ?? 0;
      board.windowReady = true;
      board.samplesAt = this.now();
      board.sampleError = "";
    } catch (error) { if (current()) board.sampleError = `Gráfico: ${error.message}`; }
  }

  refresh(force = false) {
    if (this.disposed) return Promise.resolve();
    if (this.inFlight) return this.inFlight;
    this.inFlight = this.poll(force).finally(() => { this.inFlight = null; });
    return this.inFlight;
  }

  async poll(force) {
    const revisions = Object.fromEntries(ROLES.map(origin => [origin, this.boards[origin].revision]));
    const connectionVersion = this.connectionVersion;
    const wasOnline = this.online;
    let snapshots;
    try {
      const data = await this.api.boards();
      if (this.disposed || connectionVersion !== this.connectionVersion) return;
      snapshots = data.items;
      if (!Array.isArray(snapshots) || ROLES.some(origin => !snapshots.some(item => item.origin === origin && item.config))) {
        throw new Error("El servidor no entregó los estados de ambas placas.");
      }
      this.online = true;
      this.errors.connection = "";
    } catch (error) {
      if (!this.disposed && connectionVersion === this.connectionVersion) {
        this.online = false;
        this.errors.connection = error.message;
        this.emit();
      }
      return;
    }
    const accepted = [];
    for (const snapshot of snapshots) {
      const board = this.boards[snapshot.origin];
      if (board && revisions[snapshot.origin] === board.revision && !board.pending) {
        this.applySnapshot(snapshot);
        accepted.push(snapshot.origin);
      }
    }
    this.emit();
    const work = accepted.map(origin => this.loadSamples(origin, revisions[origin], !wasOnline || force));
    if (!this.portsLoaded || !wasOnline) work.push(this.refreshPorts());
    if (force || !wasOnline || this.metadataAt === null || this.now() - this.metadataAt >= 5000) {
      this.metadataAt = this.now();
      work.push(this.loadHealth(), this.loadIncidents());
      if (force || this.capturePage === 0) work.push(this.loadCaptures());
    }
    await Promise.allSettled(work);
    this.emit();
  }

  async command(origin, action, body) {
    const board = this.boards[origin];
    if (!board) throw new Error("Origen desconocido.");
    if (!this.online || !this.storageOK) throw new Error("Comprueba la comunicación y el almacenamiento antes de controlar las placas.");
    if (board.pending || board.verifying || board.snapshot.busy) throw new Error("Espera a que termine la operación y se verifique el estado de esta placa.");
    if (action === "start" && board.dirty) throw new Error("Aplica los cambios de configuración antes de iniciar.");
    if (action === "config") {
      const errors = validateConfig(body);
      if (errors.length) throw new Error(errors.join(" "));
    }
    board.pending = action;
    board.revision += 1;
    board.error = "";
    const revision = board.revision;
    this.emit();
    try {
      const snapshot = await this.api.control(origin, action, body);
      if (!this.disposed && board.revision === revision) this.applySnapshot(snapshot, { confirmedConfig: action === "config" });
      return snapshot;
    } catch (error) {
      board.error = error.message;
      board.verifying = true;
      if (error.status === 0) {
        this.connectionVersion += 1;
        this.online = false;
        this.errors.connection = error.message;
      }
      throw error;
    } finally {
      board.pending = null;
      board.revision += 1;
      this.emit();
      // Esperar un ciclo anterior y luego leer de nuevo, sin reproducir comandos.
      if (this.inFlight) await this.inFlight;
      await this.refresh(true);
    }
  }

  async gatewayCommand(action, port) {
    if (!this.online || (action === 'connect' && !this.storageOK)) throw new Error('Comprueba el backend y el almacenamiento.');
    if (this.gatewayPending || ROLES.some(origin => this.boards[origin].pending || this.boards[origin].verifying)) {
      throw new Error('Espera a que se verifique la operacion anterior del maestro.');
    }
    this.gatewayPending = action;
    for (const origin of ROLES) { this.boards[origin].revision += 1; this.boards[origin].pending = action; }
    this.emit();
    try {
      return await this.api.gatewayControl(action, action === 'connect' ? { port } : undefined);
    } catch (error) {
      for (const origin of ROLES) { this.boards[origin].verifying = true; this.boards[origin].error = error.message; }
      throw error;
    } finally {
      this.gatewayPending = null;
      for (const origin of ROLES) { this.boards[origin].pending = null; this.boards[origin].revision += 1; }
      if (this.inFlight) await this.inFlight;
      await this.refresh(true);
    }
  }

  get chartRows() {
    return ROLES.flatMap(origin => this.boards[origin].rows.map(row => ({ ...row,
      deviceTimeMs: row.timeMs, timeMs: Date.parse(row.receivedAt) })))
      .filter(row => Number.isFinite(row.timeMs)).sort((a, b) => a.timeMs - b.timeMs || a.id - b.id);
  }

  start() {
    if (this.running || this.disposed) return this.inFlight ?? Promise.resolve();
    this.running = true;
    const loop = async () => {
      await this.refresh();
      if (this.running) this.timer = this.schedule(loop, this.interval);
    };
    return loop();
  }

  stop() {
    this.running = false;
    this.disposed = true;
    this.cancel(this.timer);
    // Detener la vista nunca envia STOP a los Arduino.
  }
}
