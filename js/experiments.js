// Estado de ensayos sin DOM, datos artificiales ni adquisicion local.
export class Experiments {
  constructor(api, { onChange = () => {}, interval = 2000,
    schedule = (task, delay) => globalThis.setTimeout(task, delay), cancel = id => globalThis.clearTimeout(id) } = {}) {
    Object.assign(this, { api, onChange, interval, schedule, cancel });
    this.catalog = null;
    this.online = false;
    this.connectionError = "";
    this.actionError = "";
    this.busy = false;
    this.active = null;
    this.sessions = [];
    this.trials = [];
    this.selectedSessionId = null;
    this.selectedSession = null;
    this.selectedTrialId = null;
    this.selectedTrial = null;
    this.summary = { groups: [], real: { train: 0, test: 0 }, minimumMet: false, targets: { train: 200, test: 100 } };
    this.sessionPage = { cursors: [0], index: 0, next: 0, more: false };
    this.trialPage = { cursors: [0], index: 0, next: 0, more: false };
    this.exportSelection = new Map();
    this.revision = 0;
    this.inFlight = null;
    this.running = false;
    this.disposed = false;
    this.timer = null;
  }

  emit() { if (!this.disposed) this.onChange(this); }
  get reserved() { return Boolean(this.active); }
  get canControl() { return this.online && !this.busy; }
  get exportIds() { return [...this.exportSelection.keys()]; }

  refresh() {
    if (this.disposed) return Promise.resolve();
    if (this.inFlight) return this.inFlight;
    this.inFlight = this.poll().finally(() => { this.inFlight = null; });
    return this.inFlight;
  }

  async poll() {
    const revision = this.revision;
    const sessionId = this.selectedSessionId;
    const trialId = this.selectedTrialId;
    try {
      const [catalog, active, summary, sessions, session, trials, trial] = await Promise.all([
        this.catalog ? Promise.resolve(this.catalog) : this.api.scenarios(),
        this.api.activeTrial(), this.api.datasetSummary(),
        this.api.sessions({ after_id: this.sessionPage.cursors[this.sessionPage.index], limit: 21 }),
        sessionId ? this.api.session(sessionId) : Promise.resolve(null),
        sessionId ? this.api.trials({ session_id: sessionId, after_id: this.trialPage.cursors[this.trialPage.index], limit: 21 }) : Promise.resolve({ items: [] }),
        trialId ? this.api.trial(trialId) : Promise.resolve(null),
      ]);
      if (this.disposed || revision !== this.revision) return;
      Object.assign(this, { catalog, active: active.trial, summary, selectedSession: session, selectedTrial: trial, online: true, connectionError: "" });
      this.sessions = sessions.items.slice(0, 20);
      this.sessionPage.next = this.sessions.at(-1)?.cursor ?? this.sessionPage.cursors[this.sessionPage.index];
      this.sessionPage.more = sessions.items.length > 20;
      this.trials = trials.items.slice(0, 20);
      this.trialPage.next = this.trials.at(-1)?.cursor ?? this.trialPage.cursors[this.trialPage.index];
      this.trialPage.more = trials.items.length > 20;
      // Al recargar recuperar contexto del ensayo activo sin enviar START.
      if (!sessionId && this.active) {
        this.selectedSessionId = this.active.sessionId;
        this.selectedTrialId = this.active.id;
      }
      this.emit();
    } catch (error) {
      if (!this.disposed && revision === this.revision) {
        this.online = false;
        this.connectionError = error.message;
        this.emit();
      }
    }
  }

  async reload() {
    if (this.inFlight) await this.inFlight;
    return this.refresh();
  }

  async selectSession(id) {
    if (this.busy) return;
    this.revision += 1;
    this.selectedSessionId = id;
    this.selectedSession = null;
    this.selectedTrialId = null;
    this.selectedTrial = null;
    this.trials = [];
    this.trialPage = { cursors: [0], index: 0, next: 0, more: false };
    this.emit();
    return this.reload();
  }

  async selectTrial(id) {
    if (this.busy) return;
    this.revision += 1;
    this.selectedTrialId = id;
    this.selectedTrial = null;
    this.emit();
    return this.reload();
  }

  async page(kind, direction) {
    if (this.busy || this.inFlight) return;
    const page = kind === "sessions" ? this.sessionPage : this.trialPage;
    if (direction === 1 && page.more) {
      page.cursors = page.cursors.slice(0, page.index + 1);
      page.cursors.push(page.next);
      page.index += 1;
    } else if (direction === -1 && page.index > 0) page.index -= 1;
    else return;
    this.revision += 1;
    return this.refresh();
  }

  async mutate(operation, apply = () => {}) {
    if (!this.canControl) throw new Error("Espera la operación o recupera la comunicación con la Raspberry.");
    this.busy = true;
    this.actionError = "";
    this.revision += 1;
    this.emit();
    try {
      const result = await operation();
      if (!this.disposed) apply(result);
      return result;
    } catch (error) {
      this.actionError = error.message;
      throw error;
    } finally {
      this.revision += 1;
      await this.reload();
      this.busy = false;
      this.emit();
    }
  }

  createSession(values) {
    return this.mutate(() => this.api.createSession(values), session => {
      this.selectedSessionId = session.id;
      this.selectedTrialId = null;
      this.selectedTrial = null;
      this.sessionPage = { cursors: [0], index: 0, next: 0, more: false };
      this.trialPage = { cursors: [0], index: 0, next: 0, more: false };
    });
  }

  createTrial(values) {
    if (!this.selectedSessionId) return Promise.reject(new Error("Selecciona una sesión."));
    return this.mutate(() => this.api.createTrial(this.selectedSessionId, values), trial => {
      this.selectedTrialId = trial.id;
      this.trialPage = { cursors: [0], index: 0, next: 0, more: false };
    });
  }

  action(id, action, body) {
    return this.mutate(() => this.api.trialAction(id, action, body), trial => {
      if (this.selectedSessionId !== trial.sessionId) this.trialPage = { cursors: [0], index: 0, next: 0, more: false };
      this.selectedTrialId = trial.id;
      this.selectedSessionId = trial.sessionId;
    });
  }

  closeSession() {
    if (!this.selectedSessionId) return Promise.reject(new Error("Selecciona una sesión."));
    return this.mutate(() => this.api.closeSession(this.selectedSessionId));
  }

  toggleExport(session, selected) {
    if (session.status !== "closed") throw new Error("Solo se exportan sesiones cerradas.");
    if (selected) {
      if (this.exportSelection.size >= 100 && !this.exportSelection.has(session.id)) throw new Error("Selecciona hasta cien sesiones por paquete.");
      if ([...this.exportSelection.values()].some(item => item.source !== session.source)) {
        throw new Error("Exporta datos reales y simulados en paquetes separados.");
      }
      this.exportSelection.set(session.id, session);
    } else this.exportSelection.delete(session.id);
    this.emit();
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

  stop() { this.running = false; this.disposed = true; this.cancel(this.timer); }
}
