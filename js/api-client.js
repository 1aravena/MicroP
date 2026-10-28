export class ApiError extends Error {
  constructor(message, { status = 0, data = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

const statusMessages = {
  403: 'La solicitud ha sido rechazada.',
  429: 'Se alcanzo el limite temporal de intentos.',
  404: "El registro solicitado no existe.",
  409: "La operación no es compatible con el estado actual del sistema.",
  422: "Revisa los datos enviados.",
  503: "El transporte o el almacenamiento no están disponibles.",
  504: "La placa no confirmó la operación. Comprueba su estado antes de repetirla.",
};

export class ApiClient {
  constructor({ base = "/api/v1", fetchImpl = globalThis.fetch.bind(globalThis),
    queryTimeout = 5000, commandTimeout = 30000 } = {}) {
    Object.assign(this, { base, fetchImpl, queryTimeout, commandTimeout });
  }

  url(path, query = {}) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      for (const item of Array.isArray(value) ? value : [value]) {
        if (item !== undefined && item !== null && item !== "") params.append(key, item);
      }
    }
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
  scenarios() { return this.request("/scenarios"); }
  sessions(query) { return this.request("/sessions", { query }); }
  session(id) { return this.request(`/sessions/${encodeURIComponent(id)}`); }
  createSession(body) { return this.request("/sessions", { method: "POST", body }); }
  closeSession(id) { return this.request(`/sessions/${encodeURIComponent(id)}/close`, { method: "POST" }); }
  trials(query) { return this.request("/trials", { query }); }
  trial(id) { return this.request(`/trials/${encodeURIComponent(id)}`); }
  activeTrial() { return this.request("/trials/active"); }
  createTrial(id, body) { return this.request(`/sessions/${encodeURIComponent(id)}/trials`, { method: "POST", body }); }
  trialAction(id, action, body) { return this.request(`/trials/${encodeURIComponent(id)}/${action}`, { method: "POST", body }); }
  datasetSummary() { return this.request("/dataset/summary"); }
  datasetExportUrl(ids) { return this.url("/dataset/export.zip", { session_id: ids }); }
  accessStatus() { return this.request('/access/status'); }
  accessMode(action) { return this.request(`/access/${action}`, { method: 'POST' }); }
  accessAttempt(id) { return this.request(`/access/attempts/${encodeURIComponent(id)}`); }
  submitAccess(body) { return this.request('/access/attempts', { method: 'POST', body }); }
  accessAttempts(query) { return this.request('/access/attempts', { query }); }
  accessExportUrl() { return this.url('/access/export.csv'); }
  mlStatus() { return this.request('/ml/status'); }
  predictions(query) { return this.request('/ml/predictions', { query }); }
  gatewayControl(action, body) { return this.request(`/gateway/${action}`, { method: 'POST', body }); }

  control(origin, action, body) {
    return this.request(`/boards/${encodeURIComponent(origin)}/${action}`, {
      method: action === "config" || action.startsWith("sensors/") ? "PUT" : "POST", body,
    });
  }

  captureExportUrl(id) { return this.url(`/captures/${encodeURIComponent(id)}/export.csv`); }
  incidentExportUrl(query) { return this.url("/incidents/export.csv", query); }
}
