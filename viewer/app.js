const NODE_COLORS = {
  ENTRY_POINT: '#e11d48',
  VIEW: '#2563eb',
  SERVICE: '#7c3aed',
  METHOD: '#0891b2',
  FUNCTION: '#0d9488',
  ORM: '#ca8a04',
  DATABASE: '#374151',
  TABLE: '#6b7280',
  EXTERNAL_API: '#dc2626',
  QUEUE: '#ea580c',
  CACHE: '#65a30d',
  UNKNOWN: '#9ca3af',
};

const NODE_WIDTH = 200;
const NODE_HEIGHT = 72;
const COMPACT_BODY_LIMIT = 72;

let cy = null;
let rawData = null;
let activeTypes = new Set(Object.keys(NODE_COLORS));
let expandedNodeId = null;
let currentGraphFingerprint = null;
let persistDraftTimer = null;

const LAYOUT_DRAFT_PREFIX = 'peg-layout-draft:';
const LAYOUT_NAME_RE = /^[a-zA-Z0-9_-]{1,64}$/;

function simpleHash(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(i)) | 0;
  }
  return (hash >>> 0).toString(16);
}

function graphFingerprint(data) {
  const meta = data?.meta || {};
  const nodeIds = (data?.nodes || []).map((node) => node.id).sort().join('\n');
  const roots = (meta.processed_roots || []).join(',') || 'all';
  return `${roots}:${data?.nodes?.length || 0}:${simpleHash(nodeIds)}`;
}

function localDraftKey() {
  return `${LAYOUT_DRAFT_PREFIX}${currentGraphFingerprint || 'unknown'}`;
}

function collectLayoutState() {
  if (!cy) {
    return null;
  }
  const positions = {};
  cy.nodes().forEach((node) => {
    const pos = node.position();
    positions[node.id()] = { x: pos.x, y: pos.y };
  });
  const pan = cy.pan();
  return {
    graph: {
      fingerprint: currentGraphFingerprint,
      processed_roots: rawData?.meta?.processed_roots || [],
      node_count: rawData?.nodes?.length || 0,
    },
    saved_at: new Date().toISOString(),
    positions,
    pan: { x: pan.x, y: pan.y },
    zoom: cy.zoom(),
  };
}

function applyLayoutState(layout) {
  if (!cy || !layout?.positions) {
    return false;
  }
  let applied = 0;
  cy.nodes().forEach((node) => {
    const pos = layout.positions[node.id()];
    if (pos) {
      node.position(pos);
      applied += 1;
    }
  });
  if (layout.pan) {
    cy.pan(layout.pan);
  }
  if (typeof layout.zoom === 'number') {
    cy.zoom(layout.zoom);
  }
  refreshNodeVisuals();
  return applied > 0;
}

function updateDraftStatus(hasDraft) {
  const el = document.getElementById('layout-draft-status');
  if (!el) {
    return;
  }
  el.textContent = hasDraft
    ? 'Локальный черновик: есть (автосохранение)'
    : 'Локальный черновик: нет';
  el.classList.toggle('layout-draft-status--active', hasDraft);
}

function saveLocalDraftNow() {
  if (!currentGraphFingerprint) {
    return;
  }
  const layout = collectLayoutState();
  if (!layout) {
    return;
  }
  localStorage.setItem(localDraftKey(), JSON.stringify(layout));
  updateDraftStatus(true);
}

function saveLocalDraftDebounced() {
  if (persistDraftTimer) {
    clearTimeout(persistDraftTimer);
  }
  persistDraftTimer = setTimeout(() => {
    persistDraftTimer = null;
    saveLocalDraftNow();
  }, 300);
}

function loadLocalDraft() {
  if (!currentGraphFingerprint) {
    return null;
  }
  const raw = localStorage.getItem(localDraftKey());
  if (!raw) {
    updateDraftStatus(false);
    return null;
  }
  try {
    const layout = JSON.parse(raw);
    updateDraftStatus(true);
    return layout;
  } catch (err) {
    console.warn('Invalid local layout draft:', err);
    localStorage.removeItem(localDraftKey());
    updateDraftStatus(false);
    return null;
  }
}

function clearLocalDraft() {
  if (currentGraphFingerprint) {
    localStorage.removeItem(localDraftKey());
  }
  updateDraftStatus(false);
}

function sanitizeLayoutName(name) {
  const trimmed = name.trim();
  return LAYOUT_NAME_RE.test(trimmed) ? trimmed : null;
}

async function fetchSavedLayouts() {
  const response = await fetch('/layouts/');
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const data = await response.json();
  return data.layouts || [];
}

function populateSavedLayoutSelect(layouts) {
  const select = document.getElementById('saved-layout-select');
  select.innerHTML = '<option value="">Saved layouts…</option>';
  layouts.forEach((layout) => {
    const opt = document.createElement('option');
    opt.value = layout.name;
    const savedAt = layout.saved_at ? ` (${layout.saved_at})` : '';
    opt.textContent = `${layout.name}${savedAt}`;
    select.appendChild(opt);
  });
}

async function refreshSavedLayoutList() {
  try {
    const layouts = await fetchSavedLayouts();
    populateSavedLayoutSelect(layouts);
  } catch (err) {
    console.warn('Failed to load layout list:', err);
  }
}

async function saveLayoutToRepo(name) {
  const layout = collectLayoutState();
  if (!layout) {
    return;
  }
  layout.name = name;
  const response = await fetch(`/layouts/${encodeURIComponent(name)}.json`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(layout, null, 2),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  saveLocalDraftNow();
  await refreshSavedLayoutList();
  const select = document.getElementById('saved-layout-select');
  select.value = name;
  setLoadStatus(`Layout "${name}" saved.`);
}

async function loadLayoutFromRepo(name) {
  const response = await fetch(`/layouts/${encodeURIComponent(name)}.json`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const layout = await response.json();
  if (!applyLayoutState(layout)) {
    throw new Error('Layout has no matching node positions');
  }
  saveLocalDraftNow();
  setLoadStatus(`Layout "${name}" loaded.`);
}

function nodeTitle(name, qualifiedName) {
  return name || qualifiedName?.split('.').pop() || '(без имени)';
}

function compactBody(description) {
  const text = description?.trim() || '';
  if (!text) {
    return '—';
  }
  if (text.length <= COMPACT_BODY_LIMIT) {
    return text;
  }
  return `${text.slice(0, COMPACT_BODY_LIMIT - 1)}…`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function bodyTextForNode(data) {
  if (data.isExpanded) {
    return data.description?.trim() || '—';
  }
  return compactBody(data.description);
}

function nodeHtmlTpl(data) {
  const title = nodeTitle(data.name, data.qualified_name);
  const body = bodyTextForNode(data);
  const expandedClass = data.isExpanded ? ' pg-node__body--expanded' : '';
  const highlightedClass = data._highlighted ? ' pg-node__body--highlighted' : '';
  const color = data.color || '#9ca3af';
  return `<div class="pg-node" data-node-id="${escapeHtml(data.id)}">
    <div class="pg-node__title">${escapeHtml(title)}</div>
    <div class="pg-node__body${expandedClass}${highlightedClass}" style="background-color:${color}">${escapeHtml(body)}</div>
  </div>`;
}

function initHtmlLabels() {
  cy.nodeHtmlLabel([
    {
      query: 'node',
      halign: 'center',
      valign: 'center',
      halignBox: 'center',
      valignBox: 'center',
      tpl: nodeHtmlTpl,
    },
  ], { enablePointerEvents: true });
}

function refreshNodeVisuals() {
  cy.nodes().forEach((node) => {
    const highlighted = node.hasClass('highlighted');
    node.data('_highlighted', highlighted);
  });
  cy.nodes().trigger('position');
}

function findNodeFromHtmlEvent(event) {
  const pgNode = event.target.closest('.pg-node');
  if (!pgNode?.dataset?.nodeId) {
    return null;
  }
  const node = cy.getElementById(pgNode.dataset.nodeId);
  return node.nonempty() ? node : null;
}

function bindHtmlPointerEvents() {
  const container = document.getElementById('cy');

  container.addEventListener('mousedown', (event) => {
    if (event.button !== 2) {
      return;
    }
    const node = findNodeFromHtmlEvent(event);
    if (!node) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    expandNode(node);
  });

  container.addEventListener('mouseup', (event) => {
    if (event.button !== 2) {
      return;
    }
    collapseExpandedNode();
  });

  container.addEventListener('contextmenu', (event) => {
    if (findNodeFromHtmlEvent(event)) {
      event.preventDefault();
    }
  });
}

function initCy() {
  cy = cytoscape({
    container: document.getElementById('cy'),
    style: [
      {
        selector: 'node',
        style: {
          shape: 'round-rectangle',
          label: '',
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          'background-opacity': 0,
          'border-width': 0,
        },
      },
      {
        selector: 'node.expanded',
        style: {
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          'z-index': 999,
        },
      },
      {
        selector: 'edge',
        style: {
          width: 1.5,
          'line-color': '#94a3b8',
          'target-arrow-color': '#94a3b8',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          label: 'data(type)',
          'font-size': 8,
          color: '#64748b',
        },
      },
      {
        selector: '.highlighted',
        style: {
          'line-color': '#f59e0b',
          'target-arrow-color': '#f59e0b',
          width: 3,
        },
      },
      { selector: '.dimmed', style: { opacity: 0.15 } },
    ],
    layout: { name: 'fcose', animate: false, randomize: true },
  });

  initHtmlLabels();
  bindHtmlPointerEvents();

  cy.on('tap', 'node', (evt) => showNodeDetails(evt.target.data()));

  cy.on('dragfree', 'node', () => saveLocalDraftDebounced());
  cy.on('layoutstop', () => saveLocalDraftDebounced());
  cy.on('pan zoom', () => saveLocalDraftDebounced());

  cy.on('mousedown', 'node', (evt) => {
    if (evt.originalEvent.button !== 2) {
      return;
    }
    evt.originalEvent.preventDefault();
    expandNode(evt.target);
  });

  window.addEventListener('mouseup', (event) => {
    if (event.button === 2) {
      collapseExpandedNode();
    }
  });
}

function expandNode(node) {
  collapseExpandedNode();
  expandedNodeId = node.id();
  node.addClass('expanded');
  node.data('isExpanded', true);
  node.raise();
  refreshNodeVisuals();
}

function collapseExpandedNode() {
  if (!expandedNodeId || !cy) {
    return;
  }
  const node = cy.getElementById(expandedNodeId);
  if (node.nonempty()) {
    node.removeClass('expanded');
    node.data('isExpanded', false);
  }
  expandedNodeId = null;
  refreshNodeVisuals();
}

function loadGraph(data) {
  rawData = data;
  currentGraphFingerprint = graphFingerprint(data);
  collapseExpandedNode();
  const elements = [];
  for (const node of data.nodes || []) {
    elements.push({
      data: {
        id: node.id,
        type: node.type,
        color: NODE_COLORS[node.type] || '#9ca3af',
        isExpanded: false,
        _highlighted: false,
        ...node,
      },
    });
  }
  for (const edge of data.edges || []) {
    elements.push({
      data: {
        id: `${edge.from}-${edge.to}-${edge.type}`,
        source: edge.from,
        target: edge.to,
        type: edge.type,
      },
    });
  }
  cy.elements().remove();
  cy.add(elements);
  applyFilters();
  populateEntrySelect(data.nodes || []);

  const localDraft = loadLocalDraft();
  if (!localDraft || !applyLayoutState(localDraft)) {
    updateDraftStatus(false);
    cy.layout({ name: 'fcose', animate: false, randomize: true }).run();
  }
  refreshNodeVisuals();
  refreshSavedLayoutList();
}

function rootLabel(node) {
  const meta = node.metadata || {};
  if (meta.root_id) {
    return meta.root_id;
  }
  if (meta.resolved_qualified_name) {
    return meta.resolved_qualified_name;
  }
  if (meta.http_method || meta.url) {
    return `${meta.http_method || ''} ${meta.url || ''}`.trim();
  }
  return node.name || node.qualified_name;
}

function populateEntrySelect(nodes) {
  const select = document.getElementById('entry-select');
  select.innerHTML = '<option value="">All trace roots</option>';
  nodes.filter((n) => n.type === 'ENTRY_POINT').forEach((n) => {
    const opt = document.createElement('option');
    opt.value = n.id;
    opt.textContent = rootLabel(n);
    select.appendChild(opt);
  });
}

function applyFilters() {
  if (!cy) return;
  cy.elements().removeClass('dimmed highlighted');
  cy.nodes().forEach((n) => {
    const visible = activeTypes.has(n.data('type'));
    n.style('display', visible ? 'element' : 'none');
  });
  cy.edges().forEach((e) => {
    const show = e.source().style('display') !== 'none' && e.target().style('display') !== 'none';
    e.style('display', show ? 'element' : 'none');
  });
  refreshNodeVisuals();
}

function highlightSubgraph(entryId) {
  if (!entryId) {
    cy.elements().removeClass('dimmed highlighted');
    refreshNodeVisuals();
    return;
  }
  const reachable = new Set([entryId]);
  let frontier = [entryId];
  for (let d = 0; d < 15; d++) {
    const next = [];
    for (const id of frontier) {
      cy.$('#' + CSS.escape(id)).outgoers('edge').forEach((e) => {
        const t = e.target().id();
        if (!reachable.has(t)) {
          reachable.add(t);
          next.push(t);
        }
      });
    }
    if (!next.length) break;
    frontier = next;
  }
  cy.elements().addClass('dimmed');
  reachable.forEach((id) => {
    cy.$('#' + CSS.escape(id)).removeClass('dimmed').addClass('highlighted');
  });
  cy.elements().forEach((el) => {
    if (el.isEdge()) {
      if (reachable.has(el.source().id()) && reachable.has(el.target().id())) {
        el.removeClass('dimmed').addClass('highlighted');
      }
    }
  });
  refreshNodeVisuals();
}

function showNodeDetails(data) {
  const el = document.getElementById('node-details');
  const lines = [
    `Type: ${data.type}`,
    `Name: ${data.name}`,
    `Description: ${data.description || '(не задано)'}`,
    `Qualified: ${data.qualified_name}`,
    `Source: ${data.source_file || '-'}:${data.line_start || '-'}`,
  ];
  if (data.metadata && Object.keys(data.metadata).length) {
    lines.push('Metadata:', JSON.stringify(data.metadata, null, 2));
  }
  if (data.source_file) {
    const link = `cursor://file/${data.source_file}:${data.line_start || 1}`;
    lines.push('', `Open: ${link}`);
  }
  el.textContent = lines.join('\n');
}

function buildTypeFilters() {
  const container = document.getElementById('type-filters');
  Object.keys(NODE_COLORS).forEach((type) => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.dataset.type = type;
    cb.addEventListener('change', () => {
      if (cb.checked) activeTypes.add(type);
      else activeTypes.delete(type);
      applyFilters();
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(` ${type}`));
    container.appendChild(label);
  });
}

document.getElementById('file-input').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => loadGraph(JSON.parse(reader.result));
  reader.readAsText(file);
});

function setLoadStatus(message, isError = false) {
  const el = document.getElementById('load-status');
  if (!el) return;
  el.textContent = message;
  el.classList.toggle('load-status--error', isError);
}

function autoLoadDefaultGraph() {
  fetch('/output/execution_graph.json')
    .then((response) => {
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      return response.json();
    })
    .then((data) => {
      loadGraph(data);
      setLoadStatus('');
    })
    .catch((err) => {
      setLoadStatus(
        'Граф не найден. Запустите .\\run.ps1 build или выберите JSON вручную.',
        true,
      );
      console.warn('Auto-load failed:', err);
    });
}

document.getElementById('search').addEventListener('input', (e) => {
  const q = e.target.value.toLowerCase();
  if (!q) {
    cy.elements().removeClass('dimmed highlighted');
    refreshNodeVisuals();
    return;
  }
  cy.elements().addClass('dimmed');
  cy.nodes().forEach((n) => {
    const d = n.data();
    const haystack = [d.name, d.qualified_name, d.description].filter(Boolean).join(' ').toLowerCase();
    if (haystack.includes(q)) {
      n.removeClass('dimmed').addClass('highlighted');
    }
  });
  refreshNodeVisuals();
});

document.getElementById('entry-select').addEventListener('change', (e) => {
  highlightSubgraph(e.target.value);
});

document.getElementById('layout-btn').addEventListener('click', () => {
  cy.layout({ name: 'fcose', animate: true, randomize: false }).run();
});

document.getElementById('load-layout-btn').addEventListener('click', async () => {
  const name = document.getElementById('saved-layout-select').value;
  if (!name) {
    setLoadStatus('Select a saved layout first.', true);
    return;
  }
  try {
    await loadLayoutFromRepo(name);
  } catch (err) {
    setLoadStatus(`Load layout failed: ${err.message}`, true);
  }
});

document.getElementById('save-layout-btn').addEventListener('click', async () => {
  const name = sanitizeLayoutName(document.getElementById('layout-name').value);
  if (!name) {
    setLoadStatus('Layout name: letters, digits, _ and - only (max 64).', true);
    return;
  }
  try {
    await saveLayoutToRepo(name);
  } catch (err) {
    setLoadStatus(`Save layout failed: ${err.message}`, true);
  }
});

document.getElementById('discard-draft-btn').addEventListener('click', () => {
  clearLocalDraft();
  cy.layout({ name: 'fcose', animate: true, randomize: false }).run();
  setLoadStatus('Local draft discarded, re-layout applied.');
});

initCy();
buildTypeFilters();
autoLoadDefaultGraph();
