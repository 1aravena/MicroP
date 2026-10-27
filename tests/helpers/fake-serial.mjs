// Solo pruebas. Nunca se importa desde la pagina ni representa captura fisica.
export class FakePort {
  constructor(origin, { reply = true, version = 2, onCommand } = {}) {
    Object.assign(this, { origin, reply, version, onCommand });
    this.commands = [];
    this.opened = false;
  }
  async open() {
    if (this.opened) throw new Error("Puerto ocupado");
    this.opened = true;
    this.readable = new ReadableStream({ start: controller => { this.input = controller; } });
    this.writable = new WritableStream({ write: bytes => {
      const command = new TextDecoder().decode(bytes).trim();
      this.commands.push(command);
      if (this.onCommand?.(command, this) === false || !this.reply) return;
      const [kind, sensor, flag] = command.split(",");
      this.emit(kind === "INFO" ? `@OK,INFO,${this.version},${this.origin}\n`
        : kind === "ENABLE" ? `@OK,ENABLE,${sensor},${flag}\n` : `@OK,${kind}\n`);
    } });
  }
  emit(text) { this.input.enqueue(new TextEncoder().encode(text)); }
  async close() { this.opened = false; this.readable = null; this.writable = null; }
}

export class FakeSerial {
  constructor(...ports) { this.ports = ports; this.listeners = []; }
  addEventListener(name, listener) { if (name === "disconnect") this.listeners.push(listener); }
  async requestPort() {
    if (!this.ports.length) throw new DOMException("Seleccion cancelada", "NotFoundError");
    return this.ports.shift();
  }
  unplug(port) { for (const listener of this.listeners) listener({ port }); }
}
export const tick = () => new Promise(resolve => setTimeout(resolve, 0));
