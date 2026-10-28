import { qualityReason } from './experiments-view.js';

const decisions = { allowed: 'Permitido', denied: 'Rechazado', blocked: 'Bloqueado temporalmente',
  pending: 'En proceso', unavailable: 'No disponible', unconfirmed: 'Sin confirmar' };
const states = { inactive: 'Modo inactivo', waiting: 'Esperando una ventana completa de 10 s', no_model: 'Sin modelo',
  ready: 'Disponible', insufficient_data: 'Ventana sin clasificar', stale: 'Resultado antiguo', error: 'Error de ML' };
const cell = text => { const node = document.createElement('td'); node.textContent = String(text); return node; };

export class AccessView {
  constructor(model, api, { onChange = () => {} } = {}) {
    Object.assign(this, { model, api, onChange });
    this.$ = selector => document.querySelector(selector);
    this.keys = {};
    this.$('#access-section').innerHTML = `
      <div class="section-heading"><div><h2>Acceso y ML</h2><p>PIN de demostración · LED del Nano · Clasificación independiente</p></div></div>
      <p id="access-error" class="message" role="status" hidden></p>
      <section class="control-panel" aria-labelledby="access-mode-title">
        <h3 id="access-mode-title">Modo de acceso</h3><p id="access-mode-status" role="status">Comprobando backend…</p>
        <p id="access-mode-reason" class="hint"></p><p id="access-source" class="hint"></p>
        <div class="board-actions"><button id="access-enable" type="button" disabled>Activar acceso y ML</button><button id="access-disable" class="secondary" type="button" disabled>Desactivar modo</button></div>
        <p>En Sensores, inicia ambas capturas con los cinco sensores habilitados. La distancia sin eco puede ser NA. Termina el ensayo de recolección antes de activar este modo.</p>
        <p class="hint">Configura un PIN de prueba en la terminal con <code>python -m backend.credentials</code> y reinicia el backend. No hay PIN predeterminado. Este PIN no inicia una sesión de usuario.</p>
      </section>
      <section class="control-panel" aria-labelledby="pin-title">
        <h3 id="pin-title">Solicitar acceso de prueba</h3>
        <form id="access-form" class="experiment-form"><label>PIN de prueba<input id="access-pin" type="password" inputmode="numeric" autocomplete="off" minlength="6" maxlength="6" pattern="[0-9]{6}" required disabled /></label><button type="submit" disabled>Validar PIN y señalizar</button></form>
        <p id="access-lockout" class="hint" role="status"></p><p id="access-result" role="status">Sin solicitudes en esta pestaña.</p>
        <p class="hint">LED: un segundo encendido = permitido; tres destellos = rechazo; cinco = falla señalizable. El LED termina su patrón automáticamente. Una confirmación de comando no sustituye la comprobación física.</p>
        <p class="hint">Usa una credencial exclusiva de la maqueta en una red local de confianza. HTTP local no cifra el PIN.</p>
      </section>
      <section class="control-panel" aria-labelledby="ml-title"><h3 id="ml-title">Análisis ML</h3>
        <div class="dataset-metrics"><p><span>Modelo</span><strong id="ml-state">Sin consultar</strong></p><p><span>Última clasificación</span><strong id="ml-label">Sin consultar</strong></p><p><span>Puntaje anómalo</span><strong id="ml-score">—</strong></p></div>
        <p id="ml-details" class="hint capture-id"></p><p>El modelo clasifica ventanas de sensores. La decisión del PIN conserva su regla, incluso cuando ML no está disponible.</p>
      </section>
      <section class="control-panel" aria-labelledby="access-history-title"><div class="section-heading"><h3 id="access-history-title">Intentos registrados</h3><a id="access-download" class="download-link" aria-disabled="true">Accesos CSV</a></div>
        <div class="table-scroll"><table class="capture-table"><thead><tr><th>Fecha</th><th>Decisión</th><th>Señal</th><th>Motivo</th></tr></thead><tbody id="access-attempts"></tbody></table></div>
        <div class="pagination"><button id="attempts-prev" class="secondary" type="button">Más recientes</button><span id="attempts-page"></span><button id="attempts-next" class="secondary" type="button">Más antiguos</button></div>
      </section>
      <section class="control-panel" aria-labelledby="prediction-history-title"><h3 id="prediction-history-title">Ventanas de inferencia</h3>
        <p class="hint">Las predicciones y los descartes no son etiquetas del dataset. Una ventana sin modelo o sin calidad suficiente conserva sus motivos.</p>
        <div class="table-scroll"><table class="capture-table"><thead><tr><th>Inicio UTC</th><th>Resultado</th><th>Puntaje</th><th>Calidad / motivo</th></tr></thead><tbody id="access-predictions"></tbody></table></div>
        <div class="pagination"><button id="predictions-prev" class="secondary" type="button">Más recientes</button><span id="predictions-page"></span><button id="predictions-next" class="secondary" type="button">Más antiguas</button></div>
      </section>`;
    this.$('#access-enable').addEventListener('click', () => void this.perform(() => model.mode('enable')));
    for (const id of ['access-disable', 'active-access-stop']) this.$(`#${id}`).addEventListener('click', () => void this.perform(() => model.mode('disable')));
    this.$('#access-form').addEventListener('submit', event => {
      event.preventDefault();
      const pin = this.$('#access-pin').value;
      this.$('#access-pin').value = '';
      void this.perform(() => model.attempt(pin));
    });
    for (const kind of ['attempts', 'predictions']) for (const [suffix, direction] of [['prev', -1], ['next', 1]]) {
      this.$(`#${kind}-${suffix}`).addEventListener('click', () => void model.page(kind, direction));
    }
    this.$('#access-download').href = api.accessExportUrl();
    this.$('#access-download').download = 'accesos.csv';
    this.$('#access-download').addEventListener('click', event => { if (!model.online) event.preventDefault(); });
  }
  async perform(action) {
    try { await action(); } catch (error) { this.model.error = error.message; }
    this.render(this.model);
  }
  render(state) {
    const online = state.online;
    const ready = state.canControl;
    const mode = state.status;
    const error = [state.connectionError, state.error].filter(Boolean).join(' ');
    this.$('#access-error').textContent = error;
    this.$('#access-error').hidden = !error;
    this.$('#active-access-bar').hidden = !mode.active;
    this.$('#active-access-state').textContent = online ? 'Placas reservadas para acceso y análisis ML.' : 'Sin verificar: enlace perdido con el backend.';
    this.$('#active-access-stop').disabled = !ready;
    this.$('#access-mode-status').textContent = !online ? 'Sin consultar' : mode.active ? 'Activo' : mode.phase === 'suspended' ? 'Suspendido por falla' : 'Inactivo';
    this.$('#access-mode-reason').textContent = [mode.reason, mode.pinError, mode.issue].filter(Boolean).join(' ');
    this.$('#access-source').textContent = mode.acquisitionMode === 'simulated' ? 'PERIFÉRICOS SIMULADOS: esta sesión no acredita un montaje real.' : 'Autoridad de estado: backend del equipo receptor.';
    this.$('#access-enable').disabled = !ready || !mode.canEnable;
    this.$('#access-disable').disabled = !ready || !mode.active;
    for (const field of this.$('#access-form').elements) field.disabled = !ready || !mode.ready;
    this.$('#access-lockout').textContent = state.verifying ? 'Verificando la solicitud anterior; no se repetirá el envío.' : mode.retryAfter ? `Bloqueo temporal. Espera hasta ${mode.retryAfter} s.` : 'Cinco PIN incorrectos en 60 s bloquean nuevos intentos durante 60 s.';
    const result = state.lastResult;
    this.$('#access-result').textContent = result ? `${decisions[result.decision]} · Regla PIN: ${result.authorization === 'allow' ? 'permitido' : result.authorization === 'deny' ? 'rechazado' : 'sin evaluar'} · Señal: ${result.signal === 'confirmed' ? 'confirmada' : 'sin confirmar o no enviada'} · ${result.reason}` : state.lastRequestId ? `Solicitud ${state.lastRequestId}: resultado sin confirmar.` : 'Sin solicitudes en esta pestaña.';
    const ml = state.ml;
    const current = online && mode.active && ml.state === 'ready' && ml.latest?.label;
    this.$('#ml-state').textContent = !online ? 'Sin consultar' : states[ml.modelState ?? ml.state] ?? ml.modelState ?? ml.state;
    this.$('#ml-label').textContent = current ? ml.latest.label === 'anomalo' ? 'Anómalo' : 'Normal' : 'Sin resultado actual';
    this.$('#ml-score').textContent = current ? ml.latest.score.toFixed(3) : '—';
    this.$('#ml-details').textContent = [states[ml.state], ml.error, ml.processingError, ml.modelId ? `Modelo ${ml.modelId} · ${ml.source}` : '', current ? `Ventana terminada ${ml.latest.endedAt}` : ''].filter(Boolean).join(' · ');
    this.$('#access-download').setAttribute('aria-disabled', String(!online));
    for (const [kind, values] of [['attempts', state.attempts], ['predictions', state.predictions]]) {
      const key = JSON.stringify(values);
      if (this.keys[kind] !== key) {
        this.keys[kind] = key;
        const rows = values.map(value => {
          const tr = document.createElement('tr');
          const texts = kind === 'attempts'
            ? [new Date(value.at).toLocaleString('es-CL'), decisions[value.decision] ?? value.decision, value.signal === 'confirmed' ? 'Confirmada' : 'Sin confirmar / no enviada', value.reason]
            : [value.startedAt, value.label === 'anomalo' ? 'Anómalo' : value.label === 'normal' ? 'Normal' : 'Sin clasificar', value.score?.toFixed(3) ?? '—', value.reasons.length ? value.reasons.map(qualityReason).join(', ') : 'Ventana aceptada'];
          tr.append(...texts.map(cell)); return tr;
        });
        if (!rows.length) { const tr = document.createElement('tr'); const td = cell('Sin registros consultados en esta página.'); td.colSpan = 4; tr.append(td); rows.push(tr); }
        this.$(kind === 'attempts' ? '#access-attempts' : '#access-predictions').replaceChildren(...rows);
      }
      const page = state.pages[kind];
      this.$(`#${kind}-prev`).disabled = !ready || !page.index;
      this.$(`#${kind}-next`).disabled = !ready || !page.more;
      this.$(`#${kind}-page`).textContent = `Página ${page.index + 1}`;
    }
    this.onChange();
  }
}
