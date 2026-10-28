// Solo estado remoto: nunca conserva el PIN, repite un POST ni crea capturas.
export class AccessPanel {
  constructor(api, { onChange = () => {}, interval = 2000, createId = () => globalThis.crypto.randomUUID(),
    schedule = (fn, delay) => globalThis.setTimeout(fn, delay), cancel = id => globalThis.clearTimeout(id) } = {}) {
    Object.assign(this, { api, onChange, interval, createId, schedule, cancel });
    this.online = false;
    this.busy = false;
    this.verifying = false;
    this.status = { active: false, ready: false, pinConfigured: false, reason: 'Comprobando backend…' };
    this.ml = { state: 'no_model', latest: null };
    this.error = '';
    this.connectionError = '';
    this.lastResult = null;
    this.lastRequestId = null;
    this.pages = Object.fromEntries(['attempts', 'predictions'].map(kind => [kind, { cursors: [0], index: 0, more: false, next: 0 }]));
    this.attempts = [];
    this.predictions = [];
    this.revision = 0;
    this.inFlight = null;
    this.running = false;
    this.disposed = false;
  }
  emit() { if (!this.disposed) this.onChange(this); }
  get canControl() { return this.online && !this.busy && !this.verifying; }
  refresh() {
    if (this.disposed) return Promise.resolve();
    if (this.inFlight) return this.inFlight;
    this.inFlight = this.poll().finally(() => { this.inFlight = null; });
    return this.inFlight;
  }
  async poll() {
    const revision = this.revision;
    try {
      const [status, ml, attempts, predictions, verified] = await Promise.all([
        this.api.accessStatus(), this.api.mlStatus(),
        this.api.accessAttempts({ after_id: this.pages.attempts.cursors[this.pages.attempts.index], limit: 21 }),
        this.api.predictions({ after_id: this.pages.predictions.cursors[this.pages.predictions.index], limit: 21 }),
        this.verifying && this.lastRequestId ? this.api.accessAttempt(this.lastRequestId).catch(error => ({ lookupError: error })) : null,
      ]);
      if (revision !== this.revision || this.disposed) return;
      Object.assign(this, { online: true, status, ml, connectionError: '' });
      for (const [kind, result] of [['attempts', attempts], ['predictions', predictions]]) {
        this[kind] = result.items.slice(0, 20);
        this.pages[kind].more = result.items.length > 20;
        this.pages[kind].next = this[kind].at(-1)?.cursor ?? this[kind].at(-1)?.id ?? 0;
      }
      if (verified && !verified.lookupError) {
        this.lastResult = verified;
        this.verifying = verified.decision === 'pending';
      } else if (verified?.lookupError.status === 404) {
        this.verifying = false;
        this.error = 'El servidor no registra esa solicitud. No se ha reenviado; revisa el estado antes de un nuevo intento.';
      }
      this.emit();
    } catch (error) {
      if (revision === this.revision && !this.disposed) { this.online = false; this.connectionError = error.message; this.emit(); }
    }
  }
  async reload() { if (this.inFlight) await this.inFlight; return this.refresh(); }
  async operation(action) {
    if (!this.canControl) throw new Error('Espera la operacion o recupera el enlace con el backend.');
    this.busy = true; this.error = ''; this.revision += 1; this.emit();
    try { return await action(); }
    catch (error) { this.error = error.message; throw error; }
    finally {
      this.revision += 1;
      await this.reload();
      this.busy = false; this.emit();
    }
  }
  mode(action) { return this.operation(() => this.api.accessMode(action)); }
  attempt(pin) {
    return this.operation(async () => {
      const requestId = this.createId();
      this.lastRequestId = requestId;
      this.lastResult = null;
      try {
        this.lastResult = await this.api.submitAccess({ requestId, pin });
        return this.lastResult;
      } catch (error) {
        if (error.data?.attempt) this.lastResult = error.data.attempt;
        else if (error.status === 0 || error.status === 504) this.verifying = true;
        throw error;
      }
    });
  }
  async page(kind, direction) {
    if (!this.canControl || this.inFlight) return;
    const page = this.pages[kind];
    if (direction === 1 && page.more) {
      page.cursors = page.cursors.slice(0, page.index + 1); page.cursors.push(page.next); page.index += 1;
    } else if (direction === -1 && page.index > 0) page.index -= 1;
    else return;
    this.revision += 1; return this.refresh();
  }
  start() {
    if (this.running || this.disposed) return this.inFlight ?? Promise.resolve();
    this.running = true;
    const loop = async () => { await this.refresh(); if (this.running) this.timer = this.schedule(loop, this.interval); };
    return loop();
  }
  stop() { this.running = false; this.disposed = true; this.cancel(this.timer); }
}
