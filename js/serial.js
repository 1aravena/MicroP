const COMMAND_TIMEOUT_MS = 4000;
const ARDUINO_RESET_MS = 1500;

export class SerialConnection {
  constructor({ onLine, onDisconnect, onError }) {
    this.onLine = onLine;
    this.onDisconnect = onDisconnect;
    this.onError = onError;
    this.port = null;
    this.reader = null;
    this.writer = null;
    this.connected = false;
    this.pendingCommand = null;

    if ("serial" in navigator) {
      navigator.serial.addEventListener("disconnect", (event) => {
        if (event.port === this.port || event.target === this.port) this.handleUnexpectedDisconnect();
      });
    }
  }

  static isSupported() {
    return "serial" in navigator;
  }

  async connect() {
    if (!SerialConnection.isSupported()) throw new Error("Web Serial no esta disponible en este navegador.");
    const selectedPort = await navigator.serial.requestPort();
    this.port = selectedPort;
    try {
      await selectedPort.open({ baudRate: 115200 });
      this.reader = selectedPort.readable.getReader();
      this.writer = selectedPort.writable.getWriter();
      this.connected = true;
      this.readPromise = this.readLoop();
      await new Promise((resolve) => setTimeout(resolve, ARDUINO_RESET_MS));
      if (!this.connected) throw new Error("Arduino se desconecto mientras se abria el puerto.");
    } catch (error) {
      this.connected = false;
      try {
        this.reader?.releaseLock();
        this.writer?.releaseLock();
        if (selectedPort.readable || selectedPort.writable) await selectedPort.close();
      } catch {
        // Conserva el error original de apertura o desconexion.
      }
      this.reader = null;
      this.writer = null;
      this.port = null;
      throw error;
    }
  }

  async sendCommand(command) {
    if (!this.connected || !this.writer) throw new Error("Arduino no conectado.");
    if (this.pendingCommand) throw new Error("Hay otro comando Serial en curso.");

    const expected = `@OK,${command.split(",")[0]}`;
    let resolvePending;
    let rejectPending;
    const response = new Promise((resolve, reject) => {
      resolvePending = resolve;
      rejectPending = reject;
    });
    const timeout = setTimeout(() => {
      if (!this.pendingCommand) return;
      this.pendingCommand = null;
      rejectPending(new Error("Arduino no respondio al comando."));
    }, COMMAND_TIMEOUT_MS);

    this.pendingCommand = { expected, resolve: resolvePending, reject: rejectPending, timeout };
    try {
      await this.writer.write(new TextEncoder().encode(`${command}\n`));
    } catch (error) {
      clearTimeout(timeout);
      this.pendingCommand = null;
      throw error;
    }
    return response;
  }

  async disconnect() {
    if (!this.port) return;
    this.connected = false;
    this.rejectPending("Conexion Serial cerrada.");
    try {
      await this.reader?.cancel();
      await this.readPromise;
    } catch {
      // El puerto puede desaparecer antes de completar el cierre.
    }
    try {
      this.writer?.releaseLock();
      await this.port.close();
    } finally {
      this.reader = null;
      this.writer = null;
      this.port = null;
    }
  }

  async readLoop() {
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (this.connected) {
        const { value, done } = await this.reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const rawLine of lines) {
          const line = rawLine.replace(/\r$/, "").trim();
          if (line) this.processLine(line);
        }
        if (buffer.length > 512) {
          buffer = "";
          this.onError(new Error("Linea Serial demasiado larga; fue descartada."));
        }
      }
    } catch (error) {
      if (this.connected) this.onError(error);
    } finally {
      try {
        this.reader?.releaseLock();
      } catch {
        // El bloqueo ya puede estar liberado tras una desconexion fisica.
      }
      this.reader = null;
      if (this.connected) this.handleUnexpectedDisconnect();
    }
  }

  processLine(line) {
    if (line.startsWith("@ERR")) {
      const asynchronousReadError = line.startsWith("@ERR,READ,");
      if (this.pendingCommand && !asynchronousReadError) {
        const pending = this.pendingCommand;
        this.pendingCommand = null;
        clearTimeout(pending.timeout);
        pending.reject(new Error(line));
      }
      this.onLine(line);
      return;
    }

    if (this.pendingCommand && line.startsWith(this.pendingCommand.expected)) {
      const pending = this.pendingCommand;
      this.pendingCommand = null;
      clearTimeout(pending.timeout);
      pending.resolve(line);
    }
    this.onLine(line);
  }

  rejectPending(message) {
    if (!this.pendingCommand) return;
    const pending = this.pendingCommand;
    this.pendingCommand = null;
    clearTimeout(pending.timeout);
    pending.reject(new Error(message));
  }

  handleUnexpectedDisconnect() {
    if (!this.connected) return;
    this.connected = false;
    this.rejectPending("Se perdio la conexion con Arduino.");
    try {
      this.writer?.releaseLock();
    } catch {
      // El sistema operativo puede haber retirado el puerto.
    }
    this.writer = null;
    this.port = null;
    this.onDisconnect();
  }
}
