// Formularios remotos. Los valores escritos nunca se sustituyen durante el sondeo.
const statusNames = { prepared: "Preparado", starting: "Iniciando", running: "En curso", stopping: "Deteniendo",
  completed: "Finalizado", interrupted: "Interrumpido", open: "Abierta", closed: "Cerrada" };
const sourceName = source => source === "real" ? "Real" : "Simulada";
const splitName = split => split === "train" ? "Entrenamiento" : "Prueba";
const reasonNames = { interrupted_trial: "Ensayo interrumpido", scenario_not_confirmed: "Escenario sin confirmar o rechazado",
  model_unavailable: 'Modelo no disponible', model_error: 'Error al calcular la clasificación',
  sensor_configuration_changed: "Configuración de sensores inconsistente", duplicate_or_out_of_order: "Secuencias duplicadas o desordenadas",
  clock_regression: "Retroceso del reloj de recepción", invalid_timestamp: "Fecha de recepción inválida",
  insufficient_rows_UNO: "Menos de 8 registros válidos de Uno", insufficient_rows_NANO: "Menos de 8 registros válidos de Nano",
  reception_gap_UNO: "Hueco de recepción mayor a 3,5 s en Uno", reception_gap_NANO: "Hueco de recepción mayor a 3,5 s en Nano",
  insufficient_lux: "Menos de 8 lecturas de luz", insufficient_sound: "Menos de 8 lecturas de sonido",
  insufficient_pir: "Menos de 8 lecturas PIR", insufficient_radar: "Menos de 8 lecturas de radar",
  invalid_distance: "Distancia inválida", invalid_lux: "Luz inválida", invalid_sound: "Sonido inválido",
  invalid_pir: "PIR inválido", invalid_radar: "Radar inválido" };
export const qualityReason = reason => reasonNames[reason] ?? 'Problema de calidad registrado';
const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};

export class ExperimentsView {
  constructor(model, api, { onChange = () => {} } = {}) {
    Object.assign(this, { model, api, onChange });
    this.$ = selector => document.querySelector(selector);
    this.keys = {};
    this.reviewId = null;
    this.$("#experiment-section").innerHTML = `
      <div class="section-heading"><div><h2>Ensayos y dataset</h2><p>Ventanas de 10 segundos · Etiquetado humano · Separación por sesión</p></div></div>
      <p id="experiment-error" class="message" role="status" hidden></p>
      <section class="control-panel" aria-labelledby="dataset-title">
        <h3 id="dataset-title">Composición del dataset</h3>
        <div class="dataset-metrics"><p><span>Entrenamiento real</span><strong id="dataset-train">0 / 200</strong></p><p><span>Prueba real</span><strong id="dataset-test">0 / 100</strong></p><p><span>Mínimo docente de prueba</span><strong id="dataset-minimum">Pendiente</strong></p></div>
        <p class="hint">Solo cuentan ventanas aceptadas de ensayos confirmados. Los datos simulados se muestran por separado y no acreditan recolección real.</p>
        <div class="table-scroll"><table class="capture-table"><caption class="sr-only">Distribución de ventanas por escenario y conjunto</caption><thead><tr><th>Procedencia</th><th>Conjunto</th><th>Escenario / clase</th><th>Aceptadas</th><th>Excluidas</th></tr></thead><tbody id="dataset-groups"></tbody></table></div>
      </section>
      <section class="control-panel" aria-labelledby="session-create-title">
        <h3 id="session-create-title">Nueva sesión de recolección</h3>
        <form id="session-form" class="experiment-form">
          <label>Nombre de sesión<input name="name" required maxlength="120" autocomplete="off" /></label>
          <label>Responsable<input name="responsible" required maxlength="120" autocomplete="name" /></label>
          <label>Conjunto<select name="partition"><option value="train">Entrenamiento</option><option value="test">Prueba independiente</option></select></label>
          <label>Procedencia<select name="source"><option value="real">Prototipo real</option><option value="simulated">Simulada · solo pruebas</option></select></label>
          <label class="wide-field">Condiciones y montaje<textarea name="conditions" required maxlength="2000" rows="2" placeholder="Disposición, iluminación, posiciones medidas, estabilización y configuración física"></textarea></label>
          <label class="wide-field">Notas de sesión<textarea name="notes" maxlength="2000" rows="2"></textarea></label>
          <p id="acquisition-mode" class="hint wide-field"></p>
          <button type="submit">Crear sesión</button>
        </form>
        <p class="hint">El conjunto y la procedencia quedan fijados al crear la sesión. Reserva otra sesión posterior para prueba.</p>
      </section>
      <section class="control-panel" aria-labelledby="session-list-title">
        <h3 id="session-list-title">Sesiones</h3>
        <div class="table-scroll"><table class="capture-table"><thead><tr><th>Sesión / responsable</th><th>Conjunto / procedencia</th><th>Estado</th><th>Abrir</th><th>Incluir en ZIP</th></tr></thead><tbody id="experiment-sessions"></tbody></table></div>
        <div class="pagination"><button id="sessions-prev" class="secondary" type="button">Más recientes</button><span id="sessions-page"></span><button id="sessions-next" class="secondary" type="button">Más antiguas</button></div>
        <div class="export-row"><p id="export-selection" class="hint">Selecciona sesiones cerradas para exportar.</p><a id="dataset-download" class="download-link" aria-disabled="true">Descargar dataset ZIP</a></div>
        <p class="hint">El paquete conserva fuentes, exclusiones, versiones y hashes. Una entrega sin las metas se identifica como parcial. Reales y simulados se exportan por separado.</p>
      </section>
      <section id="session-workspace" class="control-panel" aria-labelledby="selected-session-title" hidden>
        <div class="section-heading"><h3 id="selected-session-title"></h3><button id="session-close" class="secondary" type="button">Cerrar sesión</button></div>
        <p id="selected-session-description" class="hint"></p>
        <p id="selected-session-conditions"></p>
        <form id="trial-form" class="experiment-form">
          <label>Escenario<select name="scenario" required></select></label>
          <label>Notas del ensayo<input name="notes" maxlength="2000" /></label>
          <p id="scenario-procedure" class="hint wide-field"></p>
          <button type="submit">Preparar ensayo</button>
        </form>
        <p class="hint">Antes de iniciar: conectar y configurar ambas placas en Sensores, con todos sus sensores activos. Se aplicará la configuración confirmada del backend. La detención es manual; no cierres el escenario entre ventanas.</p>
        <div class="table-scroll"><table class="capture-table"><thead><tr><th>Escenario</th><th>Estado / revisión</th><th>Lecturas Uno / Nano</th><th>Ventanas aceptadas</th><th>Detalle</th></tr></thead><tbody id="experiment-trials"></tbody></table></div>
        <div class="pagination"><button id="trials-prev" class="secondary" type="button">Más recientes</button><span id="trials-page"></span><button id="trials-next" class="secondary" type="button">Más antiguos</button></div>
      </section>
      <section id="trial-workspace" class="control-panel" aria-labelledby="selected-trial-title" hidden>
        <h3 id="selected-trial-title"></h3><p id="selected-trial-state" role="status"></p>
        <p id="trial-identifiers" class="hint capture-id"></p>
        <div class="board-actions"><button id="trial-start" type="button">Iniciar ensayo</button><button id="trial-stop" class="secondary" type="button">Detener ensayo</button><button id="trial-cancel" class="secondary" type="button">Cancelar preparado</button></div>
        <div id="trial-review"><p>Al detener, confirma únicamente si se mantuvo el escenario previsto durante todo el ensayo. Una revisión confirmada o rechazada queda fijada; si hubo dudas, excluye y repite.</p>
          <label class="review-check"><input id="trial-confirm" type="checkbox" />Confirmo que el escenario se realizó correctamente</label>
          <label>Notas de revisión<textarea id="trial-review-notes" maxlength="2000" rows="2"></textarea></label>
          <div class="board-actions"><button id="trial-approve" type="button">Confirmar escenario</button><button id="trial-reject" class="secondary" type="button">Excluir ensayo</button><button id="trial-retry" class="secondary" type="button" hidden>Reintentar análisis</button></div>
        </div>
        <pre id="trial-quality" class="quality-report"></pre>
      </section>`;
    this.$("#session-form").addEventListener("submit", event => {
      event.preventDefault();
      const form = event.currentTarget;
      void this.perform(async () => {
        await model.createSession(Object.fromEntries(new FormData(form))); form.reset();
        if (model.catalog?.acquisitionMode === "simulated") form.elements.source.value = "simulated";
      });
    });
    this.$("#trial-form").addEventListener("submit", event => {
      event.preventDefault();
      const form = event.currentTarget;
      void this.perform(async () => { await model.createTrial(Object.fromEntries(new FormData(form))); form.elements.notes.value = ""; });
    });
    this.$('#trial-form [name="scenario"]').addEventListener("change", () => this.procedure());
    for (const kind of ["sessions", "trials"]) for (const [suffix, direction] of [["prev", -1], ["next", 1]]) {
      this.$(`#${kind}-${suffix}`).addEventListener("click", () => void model.page(kind, direction));
    }
    this.$("#session-close").addEventListener("click", () => void this.perform(() => model.closeSession()));
    for (const [selector, action] of [["#trial-start", "start"], ["#trial-stop", "stop"], ["#trial-cancel", "stop"]]) {
      this.$(selector).addEventListener("click", () => void this.perform(() => model.action(model.selectedTrialId, action)));
    }
    this.$("#active-trial-stop").addEventListener("click", () => void this.perform(() => model.action(model.active.id, "stop")));
    this.$("#trial-confirm").addEventListener("change", () => this.render(model));
    for (const [selector, confirmed] of [["#trial-approve", true], ["#trial-reject", false]]) {
      this.$(selector).addEventListener("click", () => void this.perform(() => model.action(model.selectedTrialId, "review", { confirmed, notes: this.$("#trial-review-notes").value })));
    }
    this.$("#trial-retry").addEventListener("click", () => void this.perform(() => model.action(model.selectedTrialId, "review", { confirmed: model.selectedTrial.reviewed, notes: model.selectedTrial.reviewNotes })));
    this.$("#dataset-download").addEventListener("click", event => {
      if (!model.online || !model.exportIds.length || model.busy) event.preventDefault();
    });
  }

  async perform(operation) {
    try { await operation(); }
    catch (error) { this.model.actionError = error.message; }
    this.render(this.model);
  }

  scenario(id) { return this.model.catalog?.items.find(item => item.id === id); }
  procedure() {
    const selected = this.scenario(this.$('#trial-form [name="scenario"]').value);
    this.$("#scenario-procedure").textContent = selected ? `${selected.procedure} Clase prevista: ${selected.label}.` : "";
  }
  cached(key, value, render) {
    const serialized = JSON.stringify(value);
    if (this.keys[key] !== serialized) { this.keys[key] = serialized; render(); }
  }
  row(values) {
    const row = el("tr");
    for (const value of values) { const cell = el("td"); cell.append(typeof value === "string" ? document.createTextNode(value) : value); row.append(cell); }
    return row;
  }
  table(selector, rows, empty) {
    this.$(selector).replaceChildren(...(rows.length ? rows : [this.row([empty])]));
    if (!rows.length) this.$(selector).firstChild.firstChild.colSpan = 5;
  }

  render(state) {
    const ready = state.canControl;
    const error = [state.connectionError, state.actionError].filter(Boolean).join(" ");
    this.$("#experiment-error").textContent = error;
    this.$("#experiment-error").hidden = !error;
    this.$("#active-trial-bar").hidden = !state.active;
    this.$("#active-trial-status").textContent = state.active
      ? `${this.scenario(state.active.scenario)?.name ?? state.active.scenario} · ${statusNames[state.active.status]} · ${Math.floor(state.active.elapsedSeconds ?? 0)} s · ${state.active.completeWindowsEstimate ?? 0} ventanas provisionales${state.online ? "" : " · Sin verificar: comunicación perdida"}` : "";
    this.$("#active-trial-stop").disabled = !ready || !state.active;
    this.$("#dataset-train").textContent = `${state.summary.real.train} / 200`;
    this.$("#dataset-test").textContent = `${state.summary.real.test} / 100`;
    this.$("#dataset-minimum").textContent = state.summary.minimumMet ? "100 alcanzadas" : "Pendiente";
    this.cached("groups", [state.summary.groups, state.catalog], () => this.table("#dataset-groups", state.summary.groups.map(group => this.row([
      sourceName(group.source), splitName(group.partition), `${this.scenario(group.scenario)?.name ?? group.scenario} / ${group.label}`,
      String(group.eligible), String(group.excluded),
    ])), "Aún no hay ventanas analizadas."));
    const simulated = state.catalog?.acquisitionMode === "simulated";
    const source = this.$('#session-form [name="source"]');
    source.querySelector('[value="real"]').disabled = simulated;
    if (simulated) source.value = "simulated";
    this.$("#acquisition-mode").textContent = simulated ? "Transporte SIMULADO: estos datos no cuentan para el dataset real." : "Registra la procedencia real del montaje y las condiciones antes de recolectar.";
    for (const field of this.$("#session-form").elements) field.disabled = !ready;
    if (simulated) source.querySelector('[value="real"]').disabled = true;
    this.cached("catalog", state.catalog, () => {
      const select = this.$('#trial-form [name="scenario"]');
      select.replaceChildren(...(state.catalog?.items ?? []).map(item => {
        const option = el("option", item.name); option.value = item.id; return option;
      }));
      this.procedure();
    });
    this.cached("sessions", [state.sessions, state.exportIds, ready, state.selectedSessionId], () => this.table("#experiment-sessions", state.sessions.map(session => {
      const button = el("button", "Abrir", "secondary"); button.type = "button"; button.disabled = !ready;
      button.setAttribute("aria-label", `Abrir sesión ${session.name}`);
      button.addEventListener("click", () => void state.selectSession(session.id));
      const check = el("input"); check.type = "checkbox"; check.checked = state.exportSelection.has(session.id); check.disabled = !ready || session.status !== "closed";
      check.setAttribute("aria-label", `Exportar sesión ${session.name}`);
      check.addEventListener("change", () => { try { state.toggleExport(session, check.checked); } catch (error) { check.checked = !check.checked; state.actionError = error.message; this.render(state); } });
      const row = this.row([`${session.name} · ${session.responsible}`, `${splitName(session.partition)} · ${sourceName(session.source)}`, statusNames[session.status], button, check]);
      if (session.id === state.selectedSessionId) row.className = "selected-row";
      return row;
    }), "Sin sesiones. Crea la primera cuando el montaje esté preparado."));
    for (const [kind, page] of [["sessions", state.sessionPage], ["trials", state.trialPage]]) {
      this.$(`#${kind}-prev`).disabled = !ready || !page.index;
      this.$(`#${kind}-next`).disabled = !ready || !page.more;
      this.$(`#${kind}-page`).textContent = `Página ${page.index + 1}`;
    }
    const download = this.$("#dataset-download");
    download.setAttribute("aria-disabled", String(!ready || !state.exportIds.length));
    download.href = state.exportIds.length ? this.api.datasetExportUrl(state.exportIds) : "#";
    download.download = "dataset-grupo-c.zip";
    this.$("#export-selection").textContent = state.exportIds.length
      ? `${state.exportIds.length} sesiones seleccionadas · ${sourceName([...state.exportSelection.values()][0].source)}` : "Selecciona sesiones cerradas para exportar.";
    const session = state.selectedSession;
    this.$("#session-workspace").hidden = !session;
    this.$("#session-close").disabled = !ready || !session || session.status !== "open" || Boolean(state.active?.sessionId === session.id);
    if (session) {
      this.$("#selected-session-title").textContent = session.name;
      this.$("#selected-session-description").textContent = `${session.responsible} · ${splitName(session.partition)} · ${sourceName(session.source)} · ${statusNames[session.status]} · ${session.trialCount} ensayos`;
      this.$("#selected-session-conditions").textContent = `${session.conditions}${session.notes ? ` · ${session.notes}` : ""}`;
    }
    for (const field of this.$("#trial-form").elements) field.disabled = !ready || !session || session.status !== "open";
    this.cached("trials", [state.trials, ready, state.selectedTrialId], () => this.table("#experiment-trials", state.trials.map(trial => {
      const button = el("button", "Ver ensayo", "secondary"); button.type = "button"; button.disabled = !ready;
      button.setAttribute("aria-label", `Ver ensayo ${this.scenario(trial.scenario)?.name ?? trial.scenario}`);
      button.addEventListener("click", () => void state.selectTrial(trial.id));
      const review = trial.reviewed === null ? "Por revisar" : trial.reviewed ? "Confirmado" : "Excluido";
      return this.row([this.scenario(trial.scenario)?.name ?? trial.scenario, `${statusNames[trial.status]} · ${review}`,
        `${trial.captureDetails.UNO?.sampleCount ?? 0} / ${trial.captureDetails.NANO?.sampleCount ?? 0}`,
        trial.analysisState === "ready" ? `${trial.eligibleCount} / ${trial.windowCount}` : trial.analysisState === "error" ? "Error de análisis" : "Pendientes", button]);
    }), "Sin ensayos en esta sesión."));
    this.renderTrial(state, ready);
    this.onChange();
  }

  renderTrial(state, ready) {
    const trial = state.selectedTrial;
    this.$("#trial-workspace").hidden = !trial;
    if (!trial) return;
    if (this.reviewId !== trial.id) {
      this.reviewId = trial.id;
      this.$("#trial-confirm").checked = false;
      this.$("#trial-review-notes").value = trial.reviewNotes ?? "";
    }
    this.$("#selected-trial-title").textContent = this.scenario(trial.scenario)?.name ?? trial.scenario;
    this.$("#selected-trial-state").textContent = `${statusNames[trial.status]} · ${Math.floor(trial.elapsedSeconds)} s · ${trial.completeWindowsEstimate} ventanas provisionales. ${trial.reviewed === null ? "Requiere confirmación al detener." : trial.reviewed ? "Escenario confirmado." : "Ensayo excluido."}`;
    this.$("#trial-identifiers").textContent = `Ensayo ${trial.id} · Uno ${trial.captures.UNO ?? "sin captura"} · Nano ${trial.captures.NANO ?? "sin captura"}`;
    this.$("#trial-start").hidden = trial.status !== "prepared";
    this.$("#trial-start").disabled = !ready || state.reserved;
    this.$("#trial-cancel").hidden = trial.status !== "prepared";
    this.$("#trial-cancel").disabled = !ready;
    this.$("#trial-stop").hidden = !["starting", "running", "stopping"].includes(trial.status);
    this.$("#trial-stop").disabled = !ready;
    const canReview = ready && trial.status === "completed" && trial.reviewed === null;
    this.$("#trial-review").hidden = !["completed", "interrupted"].includes(trial.status);
    this.$("#trial-confirm").disabled = !canReview;
    this.$("#trial-review-notes").disabled = !canReview;
    this.$("#trial-approve").disabled = !canReview || !this.$("#trial-confirm").checked;
    this.$("#trial-reject").disabled = !canReview;
    this.$("#trial-retry").hidden = trial.analysisState !== "error";
    this.$("#trial-retry").disabled = !ready || state.selectedSession?.status !== "open";
    const summary = trial.analysisSummary;
    this.$("#trial-quality").textContent = trial.analysisState === "ready"
      ? [`Validación definitiva: ${trial.eligibleCount} aceptadas de ${trial.windowCount} ventanas completas.`,
        `Intervalo común: ${summary.durationSeconds ?? 0} s. Fragmento final descartado: ${summary.trailingSeconds ?? 0} s.`,
        `Lecturas originales: Uno ${summary.rawCounts?.UNO ?? 0} · Nano ${summary.rawCounts?.NANO ?? 0}.`,
        "Cobertura de las ventanas completas:",
        ...Object.entries(summary.coverage ?? {}).map(([sensor, value]) => `${{ distance: "Distancia", lux: "Luz", sound: "Sonido", pir: "PIR", radar: "Radar" }[sensor]}: ${value.available}/${value.total} disponibles · ${value.missing ?? 0} ausentes.`),
        ...Object.entries(summary.exclusions ?? {}).map(([reason, count]) => `${reasonNames[reason] ?? reason}: ${count} ventanas.`),
        ...(summary.sourceIssues ?? []).map(reason => `Ensayo completo: ${reasonNames[reason] ?? reason}.`)].join("\n")
      : trial.analysisState === "error" ? `Error de análisis: ${trial.analysisError}. Se conservan las mediciones originales.`
        : trial.reviewed === null ? "El análisis comenzará después de detener y revisar el ensayo." : "Análisis en segundo plano…";
  }
}
