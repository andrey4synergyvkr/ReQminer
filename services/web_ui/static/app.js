/* ReQminer UI — клиентская логика экранов.
   Без внешних зависимостей (vendor-скрипты: htmx, cytoscape — локальные). */

'use strict';

/* ---------------- уведомления ---------------- */
function toast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 3500);
}

/* ---------------- диалог фрагмента-источника ---------------- */
async function openFragment(fid, pkg) {
  const dlg = document.getElementById('fragment-dialog');
  if (!dlg) return;
  const body = dlg.querySelector('.dlg-body');
  const head = dlg.querySelector('.dlg-title');
  body.textContent = 'Загрузка...';
  try {
    const query = pkg ? `?package=${encodeURIComponent(pkg)}` : '';
    const r = await fetch(`/facts/${fid}/fragment${query}`);
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    head.textContent = data.title;
    body.textContent = data.text;
  } catch (e) {
    body.textContent = 'Не удалось загрузить фрагмент-источник.';
  }
  dlg.showModal();
}

/* ---------------- реестр пакетов (2.10) ---------------- */
function initPackages() {
  let selected = null;
  const tbody = document.querySelector('table tbody');
  if (!tbody || !document.getElementById('btn-open')) return;

  // строка, отмеченная сервером, считается выбранной сразу
  const preChecked = tbody.querySelector('tr input[type="checkbox"]:checked');
  if (preChecked) {
    preChecked.closest('tr').classList.add('selected');
    selected = preChecked.closest('tr').dataset.pkg;
  }

  tbody.addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-pkg]');
    if (!tr) return;
    tbody.querySelectorAll('tr').forEach((r) => r.classList.remove('selected'));
    tr.classList.add('selected');
    selected = tr.dataset.pkg;
    const cb = tr.querySelector('input[type="checkbox"]');
    if (cb && e.target !== cb) cb.checked = true;
    tbody.querySelectorAll('input[type="checkbox"]').forEach((c) => {
      if (c !== cb) c.checked = false;
    });
  });

  document.getElementById('btn-open').addEventListener('click', () => {
    if (!selected) return toast('Выберите пакет в реестре');
    location.href = `/packages/${selected}/run`;
  });

  document.getElementById('btn-analyze').addEventListener('click', async () => {
    if (!selected) return toast('Выберите пакет в реестре');
    const r = await fetch(`/packages/${selected}/analyze`, { method: 'POST' });
    if (r.status === 409) return toast('Прогон этого пакета уже выполняется');
    if (r.ok) location.reload();
  });
}

/* ---------------- приём пакета (2.11) ---------------- */
const DOC_TYPES = ['техническое задание', 'запрос на функциональность', 'фрагмент переписки', 'не определен'];
const ALLOWED_EXT = { '.md': 'markdown', '.markdown': 'markdown', '.txt': 'txt', '.csv': 'csv' };

function initUpload() {
  const input = document.getElementById('file-input');
  const tbody = document.getElementById('staged-rows');
  if (!input || !tbody) return;
  const form = document.getElementById('upload-form');

  function renderRows() {
    tbody.innerHTML = '';
    if (!input.files.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="hint">Файлы не выбраны — нажмите «Добавить файлы»</td></tr>';
      return;
    }
    [...input.files].forEach((file, i) => {
      const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
      const fmt = ALLOWED_EXT[ext];
      const tr = document.createElement('tr');
      const verdict = fmt
        ? '<span class="badge ok">пройден</span>'
        : '<span class="badge reject">отклонен: недопустимый формат</span>';
      const typeSel = DOC_TYPES.map(
        (t) => `<option ${t === 'не определен' ? 'selected' : ''}>${t}</option>`
      ).join('');
      tr.innerHTML = `
        <td class="file">${file.name}</td>
        <td><select name="filetype-${i}">${typeSel}</select></td>
        <td>${fmt || ext.slice(1)}</td>
        <td>${verdict}</td>`;
      tbody.appendChild(tr);
    });
  }

  input.addEventListener('change', renderRows);
  document.getElementById('remove-files').addEventListener('click', () => {
    input.value = '';
    renderRows();
  });

  form.addEventListener('submit', (e) => {
    const files = [...input.files];
    if (!files.length) {
      e.preventDefault();
      toast('Добавьте хотя бы один файл');
      return;
    }
    if (!files.some((f) => ALLOWED_EXT['.' + (f.name.split('.').pop() || '').toLowerCase()])) {
      e.preventDefault();
      toast('Все файлы отклонены: допустимы только txt, csv, markdown');
    }
  });
}

/* ---------------- результаты прогона (2.16) ---------------- */
async function openPreview(path, title) {
  const dlg = document.getElementById('preview-dialog');
  if (!dlg) return;
  const pkg = document.getElementById('report-package')?.dataset.package || '';
  const query = new URLSearchParams();
  if (pkg) query.set('package', pkg);
  if (path) query.set('path', path);
  dlg.querySelector('.dlg-title').textContent = title;
  const body = dlg.querySelector('.doc-preview');
  body.textContent = 'Загрузка...';
  try {
    const r = await fetch(`/report/preview?${query}`);
    if (!r.ok) throw new Error(r.status);
    body.innerHTML = await r.text();
  } catch (e) {
    body.textContent = 'Не удалось загрузить документ.';
  }
  dlg.showModal();
}

function initReport() {
  const preview = document.getElementById('btn-preview');
  if (preview) preview.addEventListener('click', () =>
    openPreview('', 'Каркас технической документации'));
  const pkg = document.getElementById('report-package')?.dataset.package || '';
  const query = pkg ? `?package=${encodeURIComponent(pkg)}` : '';
  const md = document.getElementById('btn-export-md');
  if (md) md.addEventListener('click', () => { location.href = '/report/export/md' + query; });
  const docx = document.getElementById('btn-export-docx');
  if (docx) docx.addEventListener('click', () =>
    toast('Экспорт в docx будет доступен после подключения модуля Builder'));
  const dl = document.getElementById('btn-download-report');
  if (dl) dl.addEventListener('click', () => { location.href = '/report/download' + query; });
}

/* ---------------- граф требований (2.15) ---------------- */
const TYPE_COLORS = {
  epic: { bg: '#efe7fb', border: '#7e57c2', text: '#4a2f7d' },
  feature: { bg: '#e7f0fa', border: '#1a5fb4', text: '#123f76' },
  us: { bg: '#e6f4ea', border: '#1e7e34', text: '#14572a' },
  nfr: { bg: '#fff4e0', border: '#b26a00', text: '#7d4d05' },
  constraint: { bg: '#fdecea', border: '#c0392b', text: '#8c2820' },
  term: { bg: '#e8edf1', border: '#546e7a', text: '#37474f' },
  vision: { bg: '#f0f7f4', border: '#2e7d5b', text: '#2e7d5b' },
  src: { bg: '#f4f6f8', border: '#d9dee5', text: '#6b7280' },
};

function initGraph() {
  const canvas = document.getElementById('graph-canvas');
  if (!canvas || typeof cytoscape === 'undefined' || !window.GRAPH) return;

  const shortTitle = (s, n = 30) => (s.length > n ? s.slice(0, n - 1) + '…' : s);
  const typeLabel = (key) => {
    const t = (window.FACT_TYPES || []).find((x) => x.key === key);
    return t ? t.label : key;
  };

  const elements = [];
  for (const n of window.GRAPH.nodes) {
    if (n.kind === 'fact') {
      const c = TYPE_COLORS[n.type] || TYPE_COLORS.src;
      elements.push({
        data: {
          id: n.id, kind: 'fact', ftype: n.type, title: n.title,
          doc: n.doc, frag: n.frag,
          label: `${typeLabel(n.type)}: ${shortTitle(n.title)}`,
          color: c.text, bg: c.bg, border: c.border,
        },
      });
    } else {
      elements.push({
        data: { id: n.id, kind: 'source', label: n.label, color: '#6b7280', bg: '#f4f6f8', border: '#d9dee5' },
      });
    }
  }
  for (const e of window.GRAPH.edges) {
    elements.push({
      data: {
        id: `${e.source}->${e.target}`, source: e.source, target: e.target,
        etype: e.type, trace: e.type === 'извлечен из',
      },
    });
  }

  const cy = cytoscape({
    container: canvas,
    elements,
    style: [
      {
        selector: 'node[kind = "fact"]',
        style: {
          shape: 'round-rectangle', width: 190, height: 32,
          'background-color': 'data(bg)', 'border-width': 2, 'border-color': 'data(border)',
          label: 'data(label)', color: 'data(color)', 'font-size': 11, 'font-family': 'Segoe UI',
          'text-valign': 'center', 'text-halign': 'center', 'text-wrap': 'ellipsis',
          'text-max-width': 180,
        },
      },
      {
        selector: 'node[kind = "source"]',
        style: {
          shape: 'round-rectangle', width: 130, height: 24,
          'background-color': 'data(bg)', 'border-width': 1, 'border-color': 'data(border)',
          label: 'data(label)', color: 'data(color)', 'font-size': 10, 'font-family': 'Segoe UI',
          'text-valign': 'center', 'text-halign': 'center',
        },
      },
      {
        selector: 'edge',
        style: {
          width: 1.4, 'line-color': '#9aa3ad', 'curve-style': 'bezier',
          label: 'data(etype)', 'font-size': 9, color: '#6b7280',
          'text-background-color': '#fff', 'text-background-opacity': 1,
          'text-background-padding': 2,
        },
      },
      {
        selector: 'edge[trace]',
        style: { 'line-style': 'dashed', width: 1.2 },
      },
      {
        selector: 'node.selected',
        style: { 'border-width': 4, 'border-color': '#1a5fb4' },
      },
      {
        selector: '.dimmed',
        style: { opacity: 0.15 },
      },
    ],
    layout: { name: 'cose', animate: false, nodeOverlap: 12, idealEdgeLength: 90 },
    wheelSensitivity: 0.2,
  });

  const panel = document.getElementById('node-panel');
  function showPanel(node) {
    if (!panel || !node) return;
    const d = node.data();
    if (d.kind === 'fact') {
      panel.querySelector('.head').innerHTML =
        `Выбранный узел: ${typeLabel(d.ftype)} «${d.title}» ` +
        `<span class="loc">(${d.doc}, фрагмент ${d.frag})</span>`;
      const links = cy.getElementById(d.id).connectedEdges()
        .map((e) => {
          const other = e.source().id() === d.id ? e.target() : e.source();
          const arrow = e.source().id() === d.id ? '→' : '←';
          const kindLabel = other.data('kind') === 'source' ? 'фрагмент' : typeLabel(other.data('ftype'));
          return `<b>${e.data('etype')}</b> ${arrow} ${kindLabel} «${shortTitle(other.data('title') || other.data('label'), 40)}»`;
        })
        .join(', ');
      panel.querySelector('.links').innerHTML = `Связи узла: ${links || 'нет'}`;
      panel.hidden = false;
    } else {
      panel.querySelector('.head').innerHTML = `Фрагмент-источник: ${d.label}`;
      panel.querySelector('.links').innerHTML = 'Составной узел трассировки';
      panel.hidden = false;
    }
    panel.dataset.node = d.id;
    panel.dataset.kind = d.kind;
  }

  cy.on('tap', 'node', (e) => {
    cy.nodes().removeClass('selected');
    cy.elements().removeClass('dimmed');
    const node = e.target;
    node.addClass('selected');
    showPanel(node);
  });
  cy.on('tap', (e) => {
    if (e.target === cy) {
      cy.nodes().removeClass('selected');
      cy.elements().removeClass('dimmed');
      if (panel) { panel.hidden = true; }
    }
  });

  /* фильтры */
  function applyFilters() {
    const onTypes = [...document.querySelectorAll('.types input:checked')].map((c) => c.value);
    const linkType = document.getElementById('f-link').value;
    const depth = document.getElementById('f-depth').value;
    const showSources = depth !== 'только требования';

    cy.batch(() => {
      cy.nodes().forEach((n) => {
        let show = true;
        if (n.data('kind') === 'fact') {
          show = onTypes.includes(n.data('ftype'));
          if (depth === 'до Feature' && ['us'].includes(n.data('ftype'))) show = false;
          if (depth === 'только эпики' && !['epic', 'feature'].includes(n.data('ftype'))) show = false;
        } else {
          show = showSources;
        }
        n.style('display', show ? 'element' : 'none');
      });
      cy.edges().forEach((e) => {
        const et = e.data('etype');
        const show = (linkType === 'все' || et === linkType) &&
          e.source().style('display') !== 'none' && e.target().style('display') !== 'none';
        e.style('display', show ? 'element' : 'none');
      });
    });
  }

  const applyBtn = document.getElementById('btn-apply-filters');
  if (applyBtn) applyBtn.addEventListener('click', applyFilters);
  const resetBtn = document.getElementById('btn-reset-filters');
  if (resetBtn) resetBtn.addEventListener('click', () => {
    document.querySelectorAll('.types input').forEach((c) => { c.checked = true; });
    document.getElementById('f-link').value = 'все';
    document.getElementById('f-depth').value = 'до User Story';
    cy.batch(() => cy.elements().style('display', 'element'));
    cy.elements().removeClass('dimmed');
    cy.fit(undefined, 30);
  });

  /* действия панели */
  const toSource = document.getElementById('btn-to-source');
  if (toSource) toSource.addEventListener('click', () => {
    if (!panel || !panel.dataset.node) return toast('Выберите узел графа');
    if (panel.dataset.kind !== 'fact') return toast('У фрагмента-источника нет своего источника');
    openFragment(panel.dataset.node, window.GRAPH && window.GRAPH.package);
  });
  const influence = document.getElementById('btn-influence');
  if (influence) influence.addEventListener('click', () => {
    if (!panel || !panel.dataset.node) return toast('Выберите узел графа');
    const node = cy.getElementById(panel.dataset.node);
    const nb = node.closedNeighborhood();
    cy.elements().addClass('dimmed');
    nb.removeClass('dimmed');
  });
  const exportBtn = document.getElementById('btn-export-graph');
  if (exportBtn) exportBtn.addEventListener('click', () => {
    const blob = cy.png({ full: true, bg: '#fff' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'requirements-graph.png';
    a.click();
    URL.revokeObjectURL(a.href);
  });

  /* узел, выбранный в контрольном примере (рис. 2.15) */
  const preset = cy.getElementById('F-008');
  if (preset.nonempty()) {
    preset.addClass('selected');
    showPanel(preset);
  }
  cy.fit(undefined, 30);
}

/* ---------------- инициализация ---------------- */
document.addEventListener('DOMContentLoaded', () => {
  initPackages();
  initUpload();
  initReport();
  initGraph();
});
