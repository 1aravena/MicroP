export class ApiError extends Error {
  constructor(message, { status = 0, data = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

const statusMessages = {
  404: "El registro solicitado no existe.",
  409: "La operación no es compatible con el estado actual de la placa.",
  422: "Revisa el puerto y la configuración enviados.",
  503: "El transporte o el almacenamiento no están disponibles.",
  504: "La placa no confirmó la operación. Comprueba su estado antes de repetirla.",
};

export class ApiClient {
  constructor({ base = "/api/v1", fetchImpl = globalThis.fetch.bind(globalThis),
    queryTimeout = 5000, commandTimeout = 30000 } = {}) {
    Object.assign(this, { base, fetchImpl, queryTimeout, commandTimeout });
  }

  url(path, query = {}) {
    const params = new URLSearchParams(Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== ""));
    return `${this.base}${path}${params.size ? `?${params}` : ""}`;
  }

  async request(path, { method = "GET", body, query } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), method === "GET" ? this.queryTimeout : this.commandTimeout);
    try {
      const response = await this.fetchImpl(this.url(path, query), {
        method, signal: controller.signal, cache: "no-store", credentials: "same-origin",
        headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      let data;
      try { data = await response.json(); }
      catch { throw new ApiError("El servidor no devolvió una respuesta JSON válida.", { status: response.status }); }
      if (!response.ok) {
        const detail = typeof data.detail === "string" ? data.detail
          : Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(" ") : "";
        throw new ApiError([statusMessages[response.status] ?? `Error HTTP ${response.status}.`, detail].filter(Boolean).join(" "),
          { status: response.status, data });
      }
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(controller.signal.aborted
        ? "La Raspberry no respondió a tiempo. Se consultará su estado; la operación no se repetirá automáticamente."
        : "No se pudo comunicar con la Raspberry. Revisa el servicio y la red local.");
    } finally { clearTimeout(timeout); }
  }

  health() { return this.request("/health"); }
  ports() { return this.request("/ports"); }
  boards() { return this.request("/boards"); }
  captures(query) { return this.request("/captures", { query }); }
  samples(query) { return this.request("/samples", { query }); }
  incidents(query) { return this.request("/incidents", { query }); }

  control(origin, action, body) {
    return this.request(`/boards/${encodeURIComponent(origin)}/${action}`, {
      method: action === "config" || action.startsWith("sensors/") ? "PUT" : "POST", body,
    });
  }

  captureExportUrl(id) { return this.url(`/captures/${encodeURIComponent(id)}/export.csv`); }
  incidentExportUrl(query) { return this.url("/incidents/export.csv", query); }
}
