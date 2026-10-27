import { defaultConfig, parseIdentity, parseSampleLine, serializeConfig } from "./protocol.js";

// Independiente del DOM y de Web Serial: el transporte se inyecta desde la aplicacion.
export class BoardController {
  constructor(origin, { transportFactory, onChange = () => {}, onIncident = () => {},
    now = () => new Date(), clock = () => performance.now(), id = () => crypto.randomUUID(), epoch = 0 }) {
    Object.assign(this, { origin, onChange, onIncident, now, clock, id, epoch });
    this.config = defaultConfig(origin);
    this.phase = "disconnected";
    this.connected = false;
    this.configured = false;
    this.busy = false;
    this.captures = [];
    this.currentCapture = null;
    this.lastReceived = null;
    this.buffered = [];
    this.revision = 0;
    this.transport = transportFactory({
      onLine: line => this.receive(line), onDisconnect: () => this.lost(),
      onError: error => this.incident("TRANSPORT", error.message),
    });
  }

  incident(type, description) {
    this.onIncident({ at: this.now().toISOString(), origin: this.origin, type, description });
  }

  async command(text) {
    const revision = this.revision;
    const response = await this.transport.sendCommand(text);
    if (revision !== this.revision || !this.transport.connected) throw new Error("El enlace cambio durante el comando; vuelve a configurar.");
    return response;
  }

  async action(operation) {
    if (this.busy) throw new Error("Espera a que termine el comando de esta placa.");
    this.busy = true;
    this.onChange();
    try { return await operation(); }
    catch (error) { if (error.name !== "NotFoundError") this.incident("CONTROL", error.message); throw error; }
    finally { this.busy = false; this.onChange(); }
  }

  connect() {
    return this.action(async () => {
      this.phase = "connecting";
      this.onChange();
      try {
        await this.transport.connect();
        let info;
        try { info = await this.command("INFO"); }
        catch (error) { throw new Error(`No se pudo identificar protocolo 2: ${error.message}`); }
        parseIdentity(info, this.origin);
        await this.command("STOP");
        if (!this.transport.connected) throw new Error("La placa se desconecto durante la identificacion.");
        this.connected = true;
        this.configured = false;
        this.phase = "unconfigured";
        this.lastReceived = null;
        this.incident("CONNECTED", "Protocolo 2 verificado. Revisa cableado y aplica configuracion.");
      } catch (error) { await this.transport.disconnect(); this.lost(false); throw error; }
    });
  }

  configure(config) {
    return this.action(async () => {
      if (!this.connected || this.phase === "capturing") throw new Error("Deten la captura antes de configurar.");
      if (config.origin !== this.origin) throw new Error("Configuracion de otra placa.");
      const command = serializeConfig(config);
      try {
        parseIdentity(await this.command("INFO"), this.origin);
        await this.command("STOP");
        await this.command(command);
        this.config = structuredClone(config);
        this.configured = true;
        this.phase = "configured";
        this.incident("CONFIGURED", command);
      } catch (error) { this.configured = false; this.phase = this.connected ? "unconfigured" : "disconnected"; throw error; }
    });
  }

  start() {
    return this.action(async () => {
      if (!this.connected || !this.configured || this.phase === "capturing") throw new Error("Aplica una configuracion valida antes de iniciar.");
      this.phase = "starting";
      this.buffered = [];
      this.onChange();
      try {
        await this.command("START");
        const capture = { id: this.id(), startedAt: this.now().toISOString(), startedClock: this.clock(), rows: [], lastSequence: 0, lastDeviceTime: 0,
          config: structuredClone(this.config), endedAt: null };
        this.captures.push(capture);
        this.currentCapture = capture;
        this.lastReceived = null;
        this.phase = "capturing";
        this.incident("START", `Captura ${capture.id}`);
        for (const packet of this.buffered) this.acceptSample(packet);
      } catch (error) { this.configured = false; this.phase = this.connected ? "unconfigured" : "disconnected"; throw error; }
      finally { this.buffered = []; }
    });
  }

  finishCapture() {
    if (this.currentCapture && !this.currentCapture.endedAt) this.currentCapture.endedAt = this.now().toISOString();
  }

  stop() {
    return this.action(async () => {
      if (!this.connected) throw new Error("Placa no conectada.");
      try {
        await this.command("STOP");
        this.finishCapture();
        this.phase = this.configured ? "configured" : "unconfigured";
        this.incident("STOP", "Captura detenida; datos conservados en memoria.");
      } catch (error) {
        this.finishCapture(); this.configured = false;
        this.phase = this.connected ? "unconfigured" : "disconnected";
        throw error;
      }
    });
  }

  enable(sensor, enabled) {
    return this.action(async () => {
      const next = structuredClone(this.config);
      next.enabled[sensor] = enabled;
      serializeConfig(next);
      if (!this.connected || !this.configured) throw new Error("Primero aplica la configuracion.");
      const names = { hc: "HC", pir: "PIR", radar: "RADAR", lux: "LUX", sound: "SOUND" };
      this.pendingEnabled = { enabled: next.enabled, ack: `@OK,ENABLE,${names[sensor]},${Number(enabled)}` };
      try {
        await this.command(`ENABLE,${names[sensor]},${Number(enabled)}`);
        this.config = next;
        this.incident("ENABLE", `${sensor}=${Number(enabled)}`);
      } catch (error) {
        this.finishCapture(); this.configured = false;
        this.phase = this.connected ? "unconfigured" : "disconnected";
        throw error;
      } finally { this.pendingEnabled = null; }
    });
  }

  disconnect() {
    return this.action(async () => {
      try { if (this.connected) await this.command("STOP"); }
      finally { await this.transport.disconnect(); this.lost(false); this.incident("DISCONNECTED", "Conexion cerrada por el usuario."); }
    });
  }

  lost(log = true) {
    this.revision += 1;
    this.finishCapture(); this.connected = false; this.configured = false; this.phase = "disconnected"; this.buffered = [];
    if (log) this.incident("DISCONNECTED", "Enlace perdido; las capturas anteriores se conservan.");
    this.onChange();
  }

  receive(line) {
    if (line.startsWith("@READY")) {
      if (this.connected) {
        this.revision += 1;
        this.finishCapture(); this.configured = false; this.phase = "unconfigured"; this.lastReceived = null;
        this.incident("RESET", "Reinicio detectado. Vuelve a aplicar configuracion."); this.onChange();
      }
      return;
    }
    if (line === this.pendingEnabled?.ack) this.config.enabled = { ...this.pendingEnabled.enabled };
    if (line.startsWith("@ERR")) { this.incident("DEVICE", line); return; }
    if (line.startsWith("@")) return;
    const packet = { line, receivedAt: this.now().toISOString(), receivedClock: this.clock() };
    if (this.phase === "starting") this.buffered.push(packet);
    else if (this.phase === "capturing") this.acceptSample(packet);
  }

  acceptSample({ line, receivedAt, receivedClock }) {
    try {
      const config = this.config;
      const sample = parseSampleLine(line, config);
      const capture = this.currentCapture;
      if (sample.sequence <= capture.lastSequence || sample.timeMs < capture.lastDeviceTime) throw new Error("Secuencia repetida, fuera de orden o reinicio sin identificar; muestra descartada.");
      if (sample.sequence !== capture.lastSequence + 1) this.incident("GAP", `Salto de secuencia: ${capture.lastSequence} -> ${sample.sequence}.`);
      const fields = { hc: "distanceCm", pir: "pir", radar: "radar", lux: "lux", sound: "sound" };
      const missing = Object.keys(fields).filter(key => config.enabled[key] && sample[fields[key]] === null);
      if (missing.length) this.incident("MISSING", `Lectura no disponible: ${missing.join(", ")}.`);
      capture.rows.push({ ...sample, receivedAt, captureId: capture.id, deviceTimeMs: sample.timeMs,
        timeMs: Math.max(0, receivedClock - this.epoch), enabled: { ...config.enabled } });
      capture.lastSequence = sample.sequence; capture.lastDeviceTime = sample.timeMs;
      this.lastReceived = receivedClock; this.onChange();
    } catch (error) { this.incident("INVALID", error.message); }
  }

  get rows() { return this.currentCapture?.rows ?? []; }
  get allRows() { return this.captures.flatMap(capture => capture.rows); }
}
