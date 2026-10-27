const claimedPorts = new Set();

export class SerialConnection {
  constructor({ onLine = () => {}, onDisconnect = () => {}, onError = () => {},
    serialApi = globalThis.navigator?.serial, resetMs = 1500, timeoutMs = 4000 } = {}) {
    Object.assign(this, { onLine, onDisconnect, onError, serialApi, resetMs, timeoutMs });
    this.port = null;
    this.connected = false;
    this.pendingCommand = null;
    this.closing = null;
    serialApi?.addEventListener("disconnect", event => {
      if (this.port && (event.port === this.port || event.target === this.port)) this.handleUnexpectedDisconnect();
    });
  }

  static isSupported() { return Boolean(globalThis.navigator?.serial); }

  async connect() {
    if (!this.serialApi) throw new Error("Web Serial no disponible. Usa Chrome de escritorio y localhost o HTTPS.");
    if (this.port || this.closing) throw new Error("La conexion ya esta abierta o cerrandose.");
    const port = await this.serialApi.requestPort();
    if (claimedPorts.has(port)) throw new Error("Este puerto ya esta asignado a otra placa.");
    claimedPorts.add(port);
    this.port = port;
    try {
      await port.open({ baudRate: 115200 });
      this.reader = port.readable.getReader();
      this.writer = port.writable.getWriter();
      this.connected = true;
      this.readPromise = this.readLoop(this.reader);
      await new Promise(resolve => setTimeout(resolve, this.resetMs));
      if (!this.connected) throw new Error("La placa se desconecto durante la apertura.");
    } catch (error) { await this.disconnect(); throw error; }
  }

  sendCommand(command) {
    if (!this.connected || !this.writer) return Promise.reject(new Error("Placa no conectada."));
    if (this.pendingCommand) return Promise.reject(new Error("Hay otro comando en curso en esta placa."));
    const tokens = command.split(",");
    return new Promise((resolve, reject) => {
      const pending = { kind: tokens[0], tokens, resolve, reject };
      const fail = message => { if (this.pendingCommand === pending) this.rejectPending(message); };
      pending.timeout = setTimeout(() => fail("La placa no respondio al comando. Su estado debe verificarse."), this.timeoutMs);
      this.pendingCommand = pending;
      try {
        Promise.resolve(this.writer.write(new TextEncoder().encode(`${command}\n`)))
          .catch(error => fail(error.message));
      } catch (error) { fail(error.message); }
    });
  }

  processLine(line) {
    const tokens = line.split(",");
    const pending = this.pendingCommand;
    if (tokens[0] === "@READY") this.rejectPending("La placa se reinicio; vuelve a configurar.");
    if (pending && tokens[0] === "@ERR" && tokens[1] !== "READ") this.rejectPending(line);
    else if (pending && tokens[0] === "@OK" && tokens[1] === pending.kind) {
      const matches = pending.kind === "ENABLE"
        ? tokens.length === 4 && tokens[2] === pending.tokens[1] && tokens[3] === pending.tokens[2]
        : pending.kind === "INFO" ? tokens.length === 4 : tokens.length === 2;
      if (matches && this.pendingCommand === pending) {
        clearTimeout(pending.timeout);
        this.pendingCommand = null;
        pending.resolve(line);
      }
    }
    this.onLine(line);
  }

  async readLoop(reader) {
    const decoder = new TextDecoder();
    let buffer = "";
    let discarding = false;
    try {
      while (this.connected) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const char of decoder.decode(value, { stream: true })) {
          if (char === "\n") {
            if (!discarding && buffer.trim()) this.processLine(buffer.replace(/\r$/, ""));
            buffer = "";
            discarding = false;
          } else if (!discarding) {
            buffer += char;
            if (buffer.length > 512) {
              buffer = "";
              discarding = true;
              this.onError(new Error("Linea Serial demasiado larga; descartada hasta el siguiente salto de linea."));
            }
          }
        }
      }
    } catch (error) { if (this.connected) this.onError(error); }
    finally {
      reader.releaseLock();
      if (this.reader === reader) this.reader = null;
      if (this.connected) queueMicrotask(() => this.handleUnexpectedDisconnect());
    }
  }

  rejectPending(message) {
    const pending = this.pendingCommand;
    if (!pending) return;
    this.pendingCommand = null;
    clearTimeout(pending.timeout);
    pending.reject(new Error(message));
  }

  handleUnexpectedDisconnect() { void this.close(true); }
  disconnect() { return this.close(false); }

  close(unexpected) {
    if (this.closing) return this.closing;
    const port = this.port;
    const wasConnected = this.connected;
    this.connected = false;
    this.rejectPending("Conexion Serial cerrada.");
    if (unexpected && wasConnected) this.onDisconnect();
    this.closing = (async () => {
      try { await this.reader?.cancel(); } catch { /* USB retirado. */ }
      await this.readPromise;
      try { this.writer?.releaseLock(); } catch { /* Limpieza tras desconexion. */ }
      try { if (port?.readable || port?.writable) await port.close(); } catch { /* Puerto retirado. */ }
      claimedPorts.delete(port);
      this.port = null;
      this.writer = null;
      this.reader = null;
      this.readPromise = null;
    })().finally(() => { this.closing = null; });
    return this.closing;
  }
}
