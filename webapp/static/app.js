const statusEl = document.getElementById('service-status');
const printersEl = document.getElementById('printers');
const printerErrorEl = document.getElementById('printer-error');
const logFileEl = document.getElementById('log-file');
const logUpdatedEl = document.getElementById('log-updated');
const logSuccessEl = document.getElementById('log-success');
const logErrorsEl = document.getElementById('log-errors');
const webhookListEl = document.getElementById('webhook-events');
const webhookUpdatedEl = document.getElementById('webhook-updated');
const webhookCountEl = document.getElementById('webhook-count');
const cloneForm = document.getElementById('clone-form');
const cloneResult = document.getElementById('clone-result');
const toastEl = document.getElementById('toast');
const statsGrid = document.getElementById('print-stats');
const statsRangeEl = document.getElementById('stats-week-range');
const statsUpdatedEl = document.getElementById('stats-updated');
const statsTotalsEl = document.getElementById('stats-totals');
const statsErrorEl = document.getElementById('stats-error');
const statsChartCanvas = document.getElementById('stats-chart');
const originSummaryEl = document.getElementById('origin-summary');
const logoutBtn = document.getElementById('logout-btn');

const views = document.querySelectorAll('[data-view]');

const metrics = {
  services: document.querySelector('[data-metric="services"]'),
  printers: document.querySelector('[data-metric="printers"]'),
  errors: document.querySelector('[data-metric="errors"]'),
};

let errorCounter = 0;
let statsChart;
let activeView = 'dashboard';

function setMetric(name, value) {
  if (metrics[name]) {
    metrics[name].textContent = value;
  }
}

function renderOriginChips(container, origins, emptyMessage) {
  if (!container) return;
  container.innerHTML = '';
  const entries = Object.entries(origins || {});
  if (!entries.length) {
    const empty = document.createElement('p');
    empty.className = 'origin-empty';
    empty.textContent = emptyMessage;
    container.appendChild(empty);
    return;
  }
  entries
    .sort(([a], [b]) => a.localeCompare(b))
    .forEach(([origin, counts]) => {
      const chip = document.createElement('span');
      chip.className = 'origin-chip';
      const sent = counts?.sent ?? 0;
      const completed = counts?.completed ?? 0;
      chip.innerHTML = `
        <span class="origin-code">${origin}</span>
        <span class="origin-values">${sent} / ${completed}</span>
      `;
      container.appendChild(chip);
    });
}

function setActiveView(target) {
  if (!target) return;
  activeView = target;
  views.forEach((section) => {
    const isActive = section.dataset.view === target;
    section.classList.toggle('active', isActive);
    section.hidden = !isActive;
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showToast(message, type = 'info') {
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.dataset.type = type;
  toastEl.hidden = false;
  clearTimeout(showToast.timeoutId);
  showToast.timeoutId = setTimeout(() => {
    toastEl.hidden = true;
  }, 4000);
}

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    credentials: 'same-origin',
    ...options,
  });
  if (response.status === 401) {
    window.location.href = '/';
    return Promise.reject(new Error('No autorizado'));
  }
  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = data.detail;
    } catch (err) {
      detail = response.statusText;
    }
    throw new Error(detail || response.statusText || 'Error inesperado');
  }
  return response.json();
}

function renderServices(data) {
  statusEl.innerHTML = '';
  const template = document.getElementById('service-card-template');
  let activeCount = 0;
  Object.entries(data).forEach(([name, info]) => {
    const clone = template.content.cloneNode(true);
    const card = clone.querySelector('.service-card');
    clone.querySelector('h3').textContent = name.toUpperCase();
    const badge = clone.querySelector('.badge');
    const active = (info.ActiveState || '').toLowerCase() === 'active';
    if (active) activeCount += 1;
    badge.textContent = active ? 'Activo' : 'Inactivo';
    badge.classList.toggle('active', active);
    badge.classList.toggle('inactive', !active);
    const statusText = info.status_text || 'Sin datos';
    const statusTextEl = clone.querySelector('.status-text');
    statusTextEl.textContent = statusText;
    const normalized = statusText.toLowerCase();
    let severity = 'info';
    if (!active || normalized.includes('failed') || normalized.includes('inactive')) {
      severity = 'error';
    } else if (normalized.includes('warning') || normalized.includes('degraded')) {
      severity = 'warn';
    } else if (active) {
      severity = 'ok';
    }
    statusTextEl.dataset.state = severity;
    if (card) {
      card.dataset.state = severity;
    }
    statusEl.appendChild(clone);
  });
  setMetric('services', `${activeCount}/${Object.keys(data).length}`);
}

function renderPrinters(data) {
  const list = data.printers || [];
  printersEl.innerHTML = '';
  printerErrorEl.hidden = true;
  if (!list.length) {
    const empty = document.createElement('p');
    empty.textContent = 'No se detectaron impresoras. Verifica CUPS o los permisos de lpstat.';
    empty.className = 'alert';
    printersEl.appendChild(empty);
    setMetric('printers', '0');
    return;
  }

  const template = document.getElementById('printer-card-template');
  list.forEach((printer) => {
    const clone = template.content.cloneNode(true);
    clone.querySelector('h3').textContent = printer.name || 'Desconocido';
    clone.querySelector('.state').textContent = printer.state || '';
    const dl = clone.querySelector('dl');
    Object.entries(printer).forEach(([key, value]) => {
      if (['name', 'state'].includes(key)) return;
      const dt = document.createElement('dt');
      dt.textContent = key;
      const dd = document.createElement('dd');
      dd.textContent = value;
      dl.appendChild(dt);
      dl.appendChild(dd);
    });
    printersEl.appendChild(clone);
  });
  setMetric('printers', String(list.length));
}

function renderLogs(data) {
  if (logFileEl) {
    logFileEl.textContent = `Archivo: ${data.file}`;
  }
  const lines = data.lines || [];
  const successLines = [];
  const errorLines = [];
  lines.forEach((line) => {
    const normalized = line.toLowerCase();
    if (normalized.includes('impresión completada')) {
      successLines.push(line);
    } else if (
      normalized.includes('[error]') ||
      normalized.includes('moviendo a error') ||
      normalized.includes('falló') ||
      normalized.includes('timeout') ||
      normalized.includes('failed')
    ) {
      errorLines.push(line);
    }
  });
  if (logSuccessEl) {
    logSuccessEl.textContent = successLines.length
      ? successLines.join('\n')
      : 'Sin impresiones completadas recientes.';
  }
  if (logErrorsEl) {
    logErrorsEl.textContent = errorLines.length
      ? errorLines.join('\n')
      : 'Sin errores recientes.';
  }
  if (logUpdatedEl) {
    const now = new Date();
    logUpdatedEl.textContent = `Actualizado ${now.toLocaleTimeString()}`;
  }
}

function formatTimestamp(isoString) {
  if (!isoString) return '—';
  const parsed = new Date(isoString);
  if (Number.isNaN(parsed.getTime())) {
    return isoString;
  }
  return parsed.toLocaleString();
}

function renderWebhookEvents(data) {
  if (!webhookListEl) return;
  const events = data?.events || [];
  webhookListEl.innerHTML = '';

  if (webhookCountEl) {
    const countLabel = `${events.length} evento${events.length === 1 ? '' : 's'}`;
    webhookCountEl.textContent = countLabel;
  }

  if (webhookUpdatedEl) {
    webhookUpdatedEl.textContent = `Actualizado ${new Date().toLocaleTimeString()}`;
  }

  if (!events.length) {
    const empty = document.createElement('p');
    empty.className = 'origin-empty';
    empty.textContent = 'No hay notificaciones recientes.';
    webhookListEl.appendChild(empty);
    return;
  }

  events.forEach((item) => {
    const card = document.createElement('article');
    card.className = 'webhook-event';

    const stateLabel = (item.job_state_label || item.job_state || '—').toString();
    card.dataset.state = stateLabel.toUpperCase();

    const header = document.createElement('header');
    const headerInfo = document.createElement('div');
    const eventLabel = document.createElement('p');
    eventLabel.className = 'event-label';
    eventLabel.textContent = (item.event || 'Evento').toUpperCase();
    const jobName = document.createElement('p');
    jobName.className = 'event-name';
    jobName.textContent = item.job_name || 'Sin nombre';
    headerInfo.append(eventLabel, jobName);

    const stateEl = document.createElement('span');
    stateEl.className = 'event-state';
    stateEl.textContent = stateLabel;

    header.append(headerInfo, stateEl);
    card.appendChild(header);

    const metaRow = document.createElement('div');
    metaRow.className = 'event-meta';
    const metaRow2 = document.createElement('div');
    metaRow2.className = 'event-meta';

    const metaEntries = [
      ['Impresora', item.printer || '—'],
      ['Job ID', item.job_id ?? '—'],
      ['Usuario', item.username || '—'],
    ];
    const metaEntries2 = [
      ['Host', item.host || '—'],
      ['Secuencia', item.sequence ?? '—'],
      ['Evento', formatTimestamp(item.event_time || item.received_at)],
    ];

    metaEntries.forEach(([label, value]) => {
      const span = document.createElement('span');
      span.textContent = `${label}: ${value}`;
      metaRow.appendChild(span);
    });

    metaEntries2.forEach(([label, value]) => {
      const span = document.createElement('span');
      span.textContent = `${label}: ${value}`;
      metaRow2.appendChild(span);
    });

    card.append(metaRow, metaRow2);

    const reasons = Array.isArray(item.job_state_reasons)
      ? item.job_state_reasons.join(', ')
      : item.job_state_reasons;
    if (reasons) {
      const reasonEl = document.createElement('p');
      reasonEl.className = 'event-reasons';
      reasonEl.textContent = `Motivo: ${reasons}`;
      card.appendChild(reasonEl);
    }

    webhookListEl.appendChild(card);
  });
}

function formatShortDate(isoDate) {
  if (!isoDate) return '-';
  const [year, month, day] = isoDate.split('-');
  return `${day}/${month}/${year}`;
}

function formatDayLabel(isoDate) {
  if (!isoDate) return '-';
  const [year, month, day] = isoDate.split('-');
  return `${day}/${month}`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return '—';
  }
  const numeric = Number(seconds);
  if (Number.isNaN(numeric)) {
    return '—';
  }
  if (numeric >= 60) {
    const minutes = Math.floor(numeric / 60);
    const remaining = (numeric % 60).toFixed(1);
    return `${minutes}m ${remaining}s`;
  }
  return `${numeric.toFixed(1)} s`;
}

function renderPrintStats(data) {
  if (!statsGrid) return;
  if (statsErrorEl) {
    statsErrorEl.hidden = true;
  }
  statsGrid.innerHTML = '';
  const { range, days = [], totals = {}, generated_at: generatedAt } = data;
  if (statsRangeEl && range) {
    statsRangeEl.textContent = `Semana: ${formatShortDate(range.start)} - ${formatShortDate(range.end)}`;
  }
  if (statsUpdatedEl && generatedAt) {
    const updated = new Date(generatedAt);
    statsUpdatedEl.textContent = Number.isNaN(updated.getTime())
      ? 'Actualizado -'
      : `Actualizado ${updated.toLocaleString()}`;
  }
  if (statsTotalsEl) {
    statsTotalsEl.textContent = `Total: ${totals.sent ?? 0} enviadas / ${totals.completed ?? 0} completadas`;
  }
  if (originSummaryEl) {
    renderOriginChips(originSummaryEl, totals.origins || {}, 'Sin trabajos registrados esta semana.');
  }
  if (!days.length) {
    const empty = document.createElement('p');
    empty.textContent = 'No hay datos en los últimos 7 días.';
    statsGrid.appendChild(empty);
    return;
  }
  days.forEach((day) => {
    const card = document.createElement('article');
    card.className = 'day-card';
    const dateLabel = formatDayLabel(day.date);
    card.innerHTML = `
      <header>
        <p class="weekday">${day.weekday}</p>
        <p class="day-date">${dateLabel}</p>
      </header>
      <div class="counts">
        <div>
          <span class="label">Enviadas</span>
          <span class="value">${day.sent}</span>
        </div>
        <div>
          <span class="label">Completadas</span>
          <span class="value">${day.completed}</span>
        </div>
      </div>
      <dl>
        <dt>Min</dt><dd>${formatDuration(day.duration?.min_seconds)}</dd>
        <dt>Prom</dt><dd>${formatDuration(day.duration?.avg_seconds)}</dd>
        <dt>Max</dt><dd>${formatDuration(day.duration?.max_seconds)}</dd>
      </dl>
      <div class="origin-breakdown">
        <p class="label">Por origen</p>
        <div class="origin-chip-row"></div>
      </div>
    `;
    const originRow = card.querySelector('.origin-breakdown .origin-chip-row');
    renderOriginChips(originRow, day.origins || {}, 'Sin actividad registrada.');
    statsGrid.appendChild(card);
  });
  updateStatsChart(days);
}

function buildChartDatasets(days) {
  const labels = days.map((day) => `${day.weekday.slice(0, 3)} ${formatDayLabel(day.date)}`);
  const sent = days.map((day) => Number(day.sent) || 0);
  const completed = days.map((day) => Number(day.completed) || 0);
  const avgDurations = days.map((day) => {
    const raw = day.duration?.avg_seconds;
    return raw === null || raw === undefined ? 0 : Number(raw);
  });
  return { labels, sent, completed, avgDurations };
}

function updateStatsChart(days) {
  if (!statsChartCanvas || typeof Chart === 'undefined') return;
  const ctx = statsChartCanvas.getContext('2d');
  const { labels, sent, completed, avgDurations } = buildChartDatasets(days);

  const data = {
    labels,
    datasets: [
      {
        type: 'bar',
        label: 'Enviadas',
        backgroundColor: 'rgba(96, 165, 250, 0.6)',
        borderRadius: 6,
        data: sent,
        yAxisID: 'yCounts',
      },
      {
        type: 'bar',
        label: 'Completadas',
        backgroundColor: 'rgba(34, 197, 94, 0.6)',
        borderRadius: 6,
        data: completed,
        yAxisID: 'yCounts',
      },
      {
        type: 'line',
        label: 'Promedio (s)',
        borderColor: 'rgba(248, 196, 113, 1)',
        backgroundColor: 'rgba(248, 196, 113, 0.25)',
        borderWidth: 2,
        fill: false,
        tension: 0.35,
        data: avgDurations,
        yAxisID: 'yDuration',
      },
    ],
  };

  const options = {
    responsive: true,
    plugins: {
      legend: {
        labels: { color: '#e2e8f0' },
      },
      tooltip: {
        callbacks: {
          label(context) {
            if (context.dataset.label?.includes('Promedio')) {
              return `${context.dataset.label}: ${formatDuration(context.parsed.y)}`;
            }
            return `${context.dataset.label}: ${context.parsed.y}`;
          },
        },
      },
    },
    scales: {
      x: {
        ticks: { color: '#cbd5f5' },
        grid: { color: 'rgba(148, 163, 184, 0.2)' },
      },
      yCounts: {
        position: 'left',
        beginAtZero: true,
        ticks: { color: '#cbd5f5' },
        grid: { color: 'rgba(148, 163, 184, 0.15)' },
        title: {
          display: true,
          text: 'Archivos',
          color: '#94a3b8',
        },
      },
      yDuration: {
        position: 'right',
        beginAtZero: true,
        ticks: { color: '#fbbf24' },
        grid: { drawOnChartArea: false },
        title: {
          display: true,
          text: 'Duración promedio (s)',
          color: '#fbbf24',
        },
      },
    },
  };

  if (statsChart) {
    statsChart.data = data;
    statsChart.options = options;
    statsChart.update();
  } else {
    statsChart = new Chart(ctx, {
      type: 'bar',
      data,
      options,
    });
  }
}

async function refreshServices() {
  try {
    const data = await fetchJSON('/api/system/status');
    renderServices(data);
  } catch (err) {
    errorCounter += 1;
    setMetric('errors', String(errorCounter));
    showToast(`Servicios: ${err.message}`, 'error');
  }
}

async function refreshPrinters() {
  try {
    const data = await fetchJSON('/api/printers');
    renderPrinters(data);
  } catch (err) {
    errorCounter += 1;
    setMetric('errors', String(errorCounter));
    printerErrorEl.textContent = `No se pudo obtener lpstat: ${err.message}`;
    printerErrorEl.hidden = false;
    printersEl.innerHTML = '';
    showToast('Error consultando impresoras', 'error');
  }
}

async function refreshLogs() {
  try {
    const data = await fetchJSON('/api/logs/listener');
    renderLogs(data);
  } catch (err) {
    errorCounter += 1;
    setMetric('errors', String(errorCounter));
    showToast(`Logs: ${err.message}`, 'error');
  }
}

async function refreshWebhookEvents() {
  if (!webhookListEl) return;
  try {
    const data = await fetchJSON('/api/cups/events?limit=50');
    renderWebhookEvents(data);
  } catch (err) {
    errorCounter += 1;
    setMetric('errors', String(errorCounter));
    showToast(`Webhook: ${err.message}`, 'error');
  }
}

async function refreshStats() {
  if (!statsGrid) return;
  try {
    const data = await fetchJSON('/api/stats/prints');
    renderPrintStats(data);
  } catch (err) {
    errorCounter += 1;
    setMetric('errors', String(errorCounter));
    if (statsErrorEl) {
      statsErrorEl.textContent = `No se pudo obtener estadísticas: ${err.message}`;
      statsErrorEl.hidden = false;
    }
    if (statsGrid) {
      statsGrid.innerHTML = '';
    }
    showToast('Error consultando estadísticas', 'error');
  }
}

async function refreshAll() {
  await Promise.all([
    refreshServices(),
    refreshPrinters(),
    refreshLogs(),
    refreshStats(),
    refreshWebhookEvents(),
  ]);
}

async function restartService(service) {
  const button = document.querySelector(`button[data-service="${service}"]`);
  const original = button?.textContent || '';
  if (button) {
    button.disabled = true;
    button.textContent = 'Reiniciando…';
  }
  try {
    await fetchJSON(`/api/system/${service}/restart`, { method: 'POST', body: '{}' });
    showToast(`${service} reiniciado`);
    await refreshServices();
  } catch (err) {
    showToast(`No se pudo reiniciar ${service}: ${err.message}`, 'error');
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

if (cloneForm) {
  cloneForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formData = new FormData(cloneForm);
    const payload = {
      source: formData.get('source'),
      target: formData.get('target'),
      target_uri: formData.get('target_uri'),
      description: formData.get('description') || null,
      add_alias: formData.get('add_alias') === 'on',
    };
    cloneResult.textContent = 'Trabajando…';
    try {
      const result = await fetchJSON('/api/printers/clone', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      cloneResult.textContent = JSON.stringify(result, null, 2);
      showToast('Impresora clonada correctamente');
      await refreshPrinters();
    } catch (err) {
      cloneResult.textContent = `Error: ${err.message}`;
      showToast(`Clonado falló: ${err.message}`, 'error');
    }
  });
}

Array.from(document.querySelectorAll('button.restart')).forEach((button) => {
  button.addEventListener('click', () => {
    const service = button.dataset.service;
    if (service) restartService(service);
  });
});

const refreshButtons = [
  { id: 'refresh-all', handler: refreshAll },
  { id: 'refresh-printers', handler: refreshPrinters },
  { id: 'refresh-logs', handler: refreshLogs },
  { id: 'refresh-logs-page', handler: refreshLogs },
  { id: 'refresh-webhook', handler: refreshWebhookEvents },
  { id: 'refresh-stats', handler: refreshStats },
  { id: 'refresh-services', handler: refreshServices },
  { id: 'refresh-config', handler: refreshAll },
];

refreshButtons.forEach(({ id, handler }) => {
  const btn = document.getElementById(id);
  if (btn) {
    btn.addEventListener('click', () => handler());
  }
});

document.querySelectorAll('[data-nav-target]').forEach((element) => {
  element.addEventListener('click', () => {
    const target = element.dataset.navTarget;
    setActiveView(target || 'dashboard');
  });
});

if (logoutBtn) {
  logoutBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } catch (err) {
      console.warn('No se pudo cerrar sesión limpiamente:', err);
    } finally {
      window.location.href = '/';
    }
  });
}

setActiveView(activeView);
refreshAll();
setInterval(() => {
  refreshLogs();
  refreshWebhookEvents();
}, 15000);
