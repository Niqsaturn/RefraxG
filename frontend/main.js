const MAP_PROVIDER_CONFIG = {
  provider: {
    name: window.ANTENNAMAP_MAP_PROVIDER_NAME || 'osm',
    token: window.ANTENNAMAP_MAP_PROVIDER_TOKEN || '',
    styleBaseUrl: window.ANTENNAMAP_MAP_PROVIDER_STYLE_BASE_URL || '',
  },
  defaultMode: 'dark',
  storageKey: 'antennamap.basemap.mode',
};

const BASEMAP_DEFS = {
  dark: {
    osm: { tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors', paint: { 'raster-opacity': 0.55, 'raster-saturation': -0.7, 'raster-brightness-min': 0.05 } },
    provider: { stylePath: 'dark', fallbackToOsm: true },
  },
  streets: {
    osm: { tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors' },
    provider: { stylePath: 'streets', fallbackToOsm: true },
  },
  satellite: {
    osm: { tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors', paint: { 'raster-opacity': 0.6, 'raster-saturation': -0.6 } },
    provider: { stylePath: 'satellite', fallbackToOsm: true },
  },
};

function _getProviderStyleUrl(mode) {
  const { token, styleBaseUrl } = MAP_PROVIDER_CONFIG.provider;
  const stylePath = BASEMAP_DEFS[mode]?.provider?.stylePath;
  if (!token || !styleBaseUrl || !stylePath) return null;
  return `${styleBaseUrl.replace(/\/$/, '')}/${stylePath}?token=${encodeURIComponent(token)}`;
}

function _buildRasterStyle(mode) {
  const def = BASEMAP_DEFS[mode] || BASEMAP_DEFS[MAP_PROVIDER_CONFIG.defaultMode];
  return {
    version: 8,
    name: `basemap-${mode}`,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: { basemap: { type: 'raster', tiles: def.osm.tiles, tileSize: def.osm.tileSize, attribution: def.osm.attribution } },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#0f172a' } },
      { id: 'basemap', type: 'raster', source: 'basemap', paint: def.osm.paint || {} },
    ],
  };
}

function _resolveMapStyle(mode) {
  return _getProviderStyleUrl(mode) || _buildRasterStyle(mode);
}

const map = new maplibregl.Map({
  container: 'map',
  style: _resolveMapStyle(currentBasemapMode()),
  projection: { type: 'globe' },
  center: [0, 20], zoom: 1.8, pitch: 0, bearing: 0, antialias: true,
});

const _oneShotDiagnostics = new Set();
function _diagOnce(key, message, err = null) {
  if (_oneShotDiagnostics.has(key)) return;
  _oneShotDiagnostics.add(key);
  if (err) console.warn(message, err);
  else console.warn(message);
}

// Globe slow-spin - paused while user interacts
let _spinActive = true;
let _spinResumeTimer = null;
let _globeSpinSupported = false;
function _spinGlobe() {
  if (!_globeSpinSupported) return;
  try {
    if (_spinActive && map.getZoom() < 5) {
      map.setCenter([map.getCenter().lng + 0.06, map.getCenter().lat]);
    }
  } catch (e) {
    _globeSpinSupported = false;
    _diagOnce('spin-runtime', 'Globe spin disabled due to runtime map capability mismatch.', e);
  }
  requestAnimationFrame(_spinGlobe);
}

// Pause spin on user interaction
['mousedown', 'touchstart', 'wheel'].forEach((evt) =>
  map.on(evt, () => {
    _spinActive = false;
    clearTimeout(_spinResumeTimer);
    _spinResumeTimer = setTimeout(() => { _spinActive = true; }, 3000);
  })
);

// ── DOM refs ───────────────────────────────────────────────────────────────
const details         = document.getElementById('details');
const infraToggle     = document.getElementById('infraToggle');
const estToggle       = document.getElementById('estToggle');
const spectToggle     = document.getElementById('spectToggle');
const rayToggle       = document.getElementById('rayToggle');
const sectorToggle    = document.getElementById('sectorToggle');
const confidenceToggle= document.getElementById('confidenceToggle');
const rangeBandToggle = document.getElementById('rangeBandToggle');
const coverageToggle  = document.getElementById('coverageToggle');
const basemapModeSelect = document.getElementById('basemapMode');
const satelliteToggle = document.getElementById('satelliteToggle');
const bayesToggle     = document.getElementById('bayesToggle');
const timeRange       = document.getElementById('timeRange');
const timeLabel       = document.getElementById('timeLabel');
const loopStatus        = document.getElementById('loopStatus');
const loopDebugStatus   = document.getElementById('loopDebugStatus');
const sdrStatus         = document.getElementById('sdrStatus');
const coverageStatus    = document.getElementById('coverageStatus');
const calibrationStatus = document.getElementById('calibrationStatus');
const featureHealthStatus = document.getElementById('featureHealthStatus');
const renderHealthStatus = document.getElementById('renderHealthStatus');
const sdrEventStatus = document.getElementById('sdrEventStatus');
const modelDropdown   = document.getElementById('modelSelect');
const satGroupSelect  = document.getElementById('satGroup');
const loopIntervalEl  = document.getElementById('loopInterval');
const analysisLog     = document.getElementById('analysisLog');
const logHeader       = document.getElementById('analysisLogHeader');
const goToLatLon      = document.getElementById('goToLatLon');
const goToBtn         = document.getElementById('goToBtn');

if (basemapModeSelect) {
  basemapModeSelect.value = currentBasemapMode();
  basemapModeSelect.addEventListener('change', () => setBasemapMode(basemapModeSelect.value));
}

let sortedTimes = [];
let sourcesInitialized = false;
let selectedModel = '';
let _lastLoopMetrics = null;
function currentBasemapMode() {
  try {
    const m = localStorage.getItem(MAP_PROVIDER_CONFIG.storageKey);
    return BASEMAP_DEFS[m] ? m : MAP_PROVIDER_CONFIG.defaultMode;
  } catch (_) {
    return MAP_PROVIDER_CONFIG.defaultMode;
  }
}

function setBasemapMode(mode) {
  const previousMode = currentBasemapMode();
  const safeMode = BASEMAP_DEFS[mode] ? mode : MAP_PROVIDER_CONFIG.defaultMode;
  try { localStorage.setItem(MAP_PROVIDER_CONFIG.storageKey, safeMode); } catch (_) {}
  if (basemapModeSelect) basemapModeSelect.value = safeMode;
  if (safeMode !== previousMode) window.location.reload();
}
const health = {
  lastFeatureFetchOkAt: null,
  lastFeaturePayloadGeneratedAt: null,
  counts: { infrastructure: 0, estimate: 0, speculative: 0, fox_targets: 0 },
  render: { features: 'pending', speculative: 'pending', satellites: 'pending', fox_targets: 'pending' },
};


function _addBearingArrowIcon() {
  return new Promise((resolve) => {
    if (map.hasImage('bearing-arrow')) { resolve(); return; }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">
      <polygon points="14,2 22,24 14,19 6,24" fill="#4ade80" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;
    const img = new Image(28, 28);
    img.onload = () => { map.addImage('bearing-arrow', img); resolve(); };
    img.onerror = resolve;
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  });
}

function _hasValidGlyphs() {
  try {
    const styleGlyphs = map.getStyle && map.getStyle()?.glyphs;
    const configuredGlyphs = _buildRasterStyle('dark')?.glyphs;
    const glyphs = styleGlyphs || configuredGlyphs;
    return typeof glyphs === 'string' && glyphs.includes('{fontstack}') && glyphs.includes('{range}');
  } catch (_) {
    return false;
  }
}

function _safeSetSourceData(sourceId, data, statusKey) {
  try {
    const src = map.getSource(sourceId);
    if (!src) throw new Error(`source ${sourceId} missing`);
    src.setData(data);
    if (statusKey) health.render[statusKey] = 'ok';
    return true;
  } catch (err) {
    if (statusKey) health.render[statusKey] = `error: ${err.message}`;
    return false;
  }
}

function _renderHealth() {
  if (featureHealthStatus) {
    const lastOk = health.lastFeatureFetchOkAt ? new Date(health.lastFeatureFetchOkAt).toLocaleTimeString() : 'never';
    const generatedAt = health.lastFeaturePayloadGeneratedAt
      ? new Date(health.lastFeaturePayloadGeneratedAt).toLocaleTimeString()
      : 'unknown';
    featureHealthStatus.innerHTML =
      `<strong>Features:</strong> last OK ${lastOk} · generated ${generatedAt}<br>` +
      `infra ${health.counts.infrastructure} · estimate ${health.counts.estimate} · speculative ${health.counts.speculative} · fox ${health.counts.fox_targets}`;
  }
  if (renderHealthStatus) {
    renderHealthStatus.innerHTML =
      `<strong>Render:</strong> features ${health.render.features}<br>` +
      `spec ${health.render.speculative} · sats ${health.render.satellites} · fox ${health.render.fox_targets}`;
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────
const formatFreqHz = (hz) => `${(hz / 1_000_000).toFixed(3)} MHz`;

function asFeature(siteFeature, geometry, overlayType) {
  if (!geometry) return null;
  return { type: 'Feature', geometry, properties: { ...siteFeature.properties, overlay_type: overlayType } };
}

function cutoffFromSlider() {
  if (!sortedTimes.length) return null;  // no timestamps → no filter
  const idx = Math.min(
    Math.floor((Number(timeRange.value) / 100) * (sortedTimes.length - 1)),
    sortedTimes.length - 1
  );
  return sortedTimes[idx] ?? null;
}

const popupHtml = (p) => {
  const conf = p.confidence != null ? `<br>Confidence: ${(p.confidence * 100).toFixed(0)}%` : '';
  const overlayAssumptions = `<br>Assumptions: range from RSSI/SNR + propagation model; single-source geometry shown as likelihood, not fixed point.`;
  const count = p.analysis_count != null ? ` (${p.analysis_count} obs)` : '';
  const source = p.source ? `<br>Source: ${p.source}` : '';
  const notes = p.notes ? `<br>Notes: ${p.notes}` : '';
  const confirmRow = p.kind === 'speculative'
    ? `<div class="confirm-row"><button onclick="confirmFeature('${p.id}',true)">Confirm</button> <button onclick="confirmFeature('${p.id}',false)">Dismiss</button></div>`
    : '';
  return `<strong>${p.name || p.id}</strong><br>Kind: ${p.kind}${conf}${count}` +
    `<br>Freq: ${p.freq_band || '-'}<br>Type: ${p.antenna_type || p.structure_type || '-'}` +
    `<br>Azimuth: ${p.azimuth_deg ?? '-'}°${source}${notes}${overlayAssumptions}${confirmRow}`;
};

// ── SDR Status ─────────────────────────────────────────────────────────────
async function refreshSdrStatus() {
  if (!sdrStatus) return;
  try {
    const data = await fetch('/api/sdr/capabilities').then((r) => r.json());
    const active = data.active_config;
    const modelMeta = (data.capabilities.models || {})[active.model] || {};
    sdrStatus.innerHTML =
      `<strong>Device:</strong> ${modelMeta.label || active.model}<br>` +
      `<strong>Center:</strong> ${formatFreqHz(active.center_freq_hz)}<br>` +
      `<strong>Rate:</strong> ${active.sample_rate_sps.toLocaleString()} sps · ` +
      `<strong>Gain:</strong> ${active.gain_db} dB`;
  } catch (_) {
    if (sdrStatus) sdrStatus.textContent = 'SDR: unavailable';
  }
}

// ── Loop Status ────────────────────────────────────────────────────────────
async function refreshLoopStatus() {
  try {
    const s = await fetch('/api/loop/status').then((r) => r.json());
    const last = s.last_run?.last_successful_run_at ?? 'never';
    const m = s.cycle_metrics || {};
    _lastLoopMetrics = s.last_cycle_feature_write_metrics || null;
    loopStatus.innerHTML =
      `<strong>Loop:</strong> ${s.active ? 'running' : 'paused'} · ` +
      `<strong>Provider:</strong> ${s.config.provider} · ` +
      `<strong>Model:</strong> ${s.config.model || '-'}<br>` +
      `<strong>Interval:</strong> ${s.config.interval_seconds}s · ` +
      `<strong>Last OK:</strong> ${last.slice(0, 19).replace('T', ' ')}`;
    if (loopDebugStatus) {
      const reasons = (m.solver_failure_reasons || []).slice(0, 3).join(', ') || 'none';
      const frameAgeSec = Number.isFinite(m.last_waterfall_frame_age_ms) ? (m.last_waterfall_frame_age_ms / 1000).toFixed(1) : '-';
      loopDebugStatus.innerHTML =
        `<strong>Cycle:</strong> #${m.cycle_index ?? '-'} · phase ${m.cycle_phase || '-'}<br>` +
        `<strong>Waterfall:</strong> ${m.live_frame_rate_fps ?? 0} fps · age ${frameAgeSec}s<br>` +
        `<strong>Counts:</strong> det ${m.detections ?? 0} · cand ${m.candidates ?? 0} · tracks ${m.tracks ?? 0}<br>` +
        `<strong>Solver:</strong> attempts ${m.solver_attempts ?? 0} · ok ${m.solver_successes ?? 0} · fail ${m.solver_failures ?? 0} (${reasons})<br>` +
        `<strong>AI corrections:</strong> applied ${m.ai_corrections_applied ?? 0} · rejected ${m.ai_corrections_rejected ?? 0}<br>` +
        `<strong>Map publish:</strong> ${m.map_publish_count ?? 0} · p50 ${m.map_publish_latency_ms_p50 ?? 0}ms · p95 ${m.map_publish_latency_ms_p95 ?? 0}ms`;
      if (_lastLoopMetrics?.timestamp) {
        loopDebugStatus.innerHTML +=
          `<br><strong>Last write:</strong> det ${_lastLoopMetrics.detections_count ?? 0} · ` +
          `spec ${_lastLoopMetrics.speculative_written ?? 0} · ` +
          `est ${_lastLoopMetrics.estimate_updated ?? 0} · ` +
          `total ${_lastLoopMetrics.features_total_after_write ?? 0}`;
      }
    }
  } catch (_) { loopStatus.textContent = 'Loop: unavailable'; }
}

async function refreshSystemStatus() {
  if (!sdrEventStatus) return;
  try {
    const s = await fetch('/api/status').then((r) => r.json());
    const stats = s.sdr_events || {};
    const last = stats.last_frame_timestamp ? stats.last_frame_timestamp.slice(0, 19).replace('T', ' ') : 'never';
    sdrEventStatus.innerHTML =
      `<strong>SDR events:</strong> ${stats.frames_emitted ?? 0} emitted · ` +
      `${stats.schema_rejects ?? 0} rejected<br><strong>Last frame:</strong> ${last}`;
  } catch (_) {
    sdrEventStatus.textContent = 'SDR events: unavailable';
  }
}

// ── Model Dropdown ─────────────────────────────────────────────────────────
function _modelLabel(entry) {
  if (entry.display) return entry.display;
  const backend = entry.backend || '';
  const name = entry.name || '';
  if (backend === 'llama_cpp') return `llama.cpp: ${name}`;
  if (backend === 'transformers') return `HuggingFace: ${name}`;
  if (backend === 'python_triangulation') return 'Triangulation Baseline (built-in)';
  return `Local: ${name}`;
}

async function populateModelDropdown() {
  if (!modelDropdown) return;
  try {
    const data = await fetch('/api/models/discover').then((r) => r.json());
    const options = [{ value: '', label: '— Select a model —', disabled: false }];
    const detailed = data.python_local_detailed || [];
    if (detailed.length > 0) {
      detailed.forEach((entry) => {
        const runnable = entry.importable === 'true' && !entry.reason_unusable;
        const label = `${_modelLabel(entry)}${runnable ? '' : ' (unavailable)'}`;
        options.push({ value: `python_local/${entry.name}`, label, disabled: !runnable });
      });
    } else {
      (data.python_local || []).forEach((m) => options.push({ value: `python_local/${m}`, label: `Local: ${m}`, disabled: false }));
    }
    if (options.length === 1) {
      options.push({ value: '', label: '— No local Python LLMs detected —', disabled: true });
    }
    modelDropdown.innerHTML = options.map((o) => `<option value="${o.value}" ${o.disabled ? 'disabled' : ''}>${o.label}</option>`).join('');
    if (selectedModel) modelDropdown.value = selectedModel;
  } catch (_) {
    if (modelDropdown) modelDropdown.innerHTML = '<option value="">— unavailable —</option>';
  }
}

async function applyModelSelection(value) {
  selectedModel = value;
  if (!value) return;
  const [provider, ...rest] = value.split('/');
  const model = rest.join('/') || 'baseline-v1';
  const interval = parseInt(loopIntervalEl?.value || '60', 10);
  const resp = await fetch(
    `/api/loop/config?provider=${encodeURIComponent(provider)}&model=${encodeURIComponent(model)}&interval_seconds=${interval}`,
    { method: 'POST' }
  ).catch(() => null);
  if (!resp && loopStatus) loopStatus.textContent = 'Model apply failed: backend unreachable';
  if (resp && !resp.ok && loopStatus) {
    const body = await resp.text();
    loopStatus.textContent = `Model apply failed: ${body}`;
    return;
  }
  await _deterministicFeatureRefreshSequence();
}




async function waitForMapStoreMigrationReadiness(options = {}) {
  const timeoutMs = options.timeoutMs ?? 6000;
  const pollMs = options.pollMs ?? 500;
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const healthResp = await fetch('/api/health');
      if (healthResp.ok) {
        const health = await healthResp.json();
        if (health.map_store_migration_ready) return health;
      }
    } catch (_) {}
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
  return null;
}

async function ensureMapDataLoadedAfterMigration() {
  if (details) details.textContent = 'Loading map data…';
  const ready = await waitForMapStoreMigrationReadiness({ timeoutMs: 7000, pollMs: 500 });
  if (ready?.map_store_migration_ready) {
    if (details) details.textContent = ready.migration_error
      ? `Map data loaded with migration warning: ${ready.migration_error}`
      : 'Map data loaded.';
    return ready;
  }
  if (details) details.textContent = 'Loading map data… continuing with partial data; refreshing shortly.';
  const intervalId = setInterval(async () => {
    const next = await waitForMapStoreMigrationReadiness({ timeoutMs: 1200, pollMs: 400 });
    if (next?.map_store_migration_ready) {
      clearInterval(intervalId);
      await _deterministicFeatureRefreshSequence();
      if (details) details.textContent = next.migration_error
        ? `Map data refreshed after migration warning: ${next.migration_error}`
        : 'Map data refreshed after startup migration.';
    }
  }, 1500);
  return null;
}

async function _deterministicFeatureRefreshSequence() {
  await refreshLoopStatus();
  await refreshSource();
  await refreshSpeculative();
}

// ── Main site + overlay source refresh ────────────────────────────────────
async function refreshSource() {
  if (!sourcesInitialized) return;
  try {
    const cutoff = cutoffFromSlider();
    if (timeLabel) timeLabel.textContent = `Cutoff: ${cutoff ? cutoff.slice(0, 19).replace('T', ' ') : 'all'}`;

    const url = cutoff
      ? `/api/features?timestamp_lte=${encodeURIComponent(cutoff)}`
      : '/api/features';
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    health.lastFeatureFetchOkAt = new Date().toISOString();
    health.lastFeaturePayloadGeneratedAt = data.generated_at || null;
    const allFeatures = data.features || [];
    const totalFetched = allFeatures.length;
    health.counts.infrastructure = allFeatures.filter((f) => f.properties.kind === 'infrastructure').length;
    health.counts.estimate = allFeatures.filter((f) => f.properties.kind === 'estimate').length;
    const visibleSites = (data.features || []).filter((f) =>
      (f.properties.kind === 'infrastructure' && infraToggle?.checked) ||
      (f.properties.kind === 'estimate' && estToggle?.checked)
    );

  const rays = [], sectors = [], confidence = [], rangeBands = [], uncertaintyPolygons = [];
  visibleSites.forEach((f) => {
    const o = f.properties.overlay_geometries || {};
    const ray = asFeature(f, o.direction_ray, 'direction_ray');
    const sector = asFeature(f, o.sector_wedge, 'sector_wedge');
    const ellipse = asFeature(f, o.confidence_ellipse, 'confidence_ellipse');
    const rangeBand = asFeature(f, o.range_likely_band, 'range_likely_band');
    const uncertainty = asFeature(f, o.uncertainty_polygon, 'uncertainty_polygon');
    if (ray) rays.push(ray);
    if (sector) sectors.push(sector);
    if (ellipse) confidence.push(ellipse);
    if (rangeBand) rangeBands.push(rangeBand);
    if (uncertainty) uncertaintyPolygons.push(uncertainty);
  });

    _safeSetSourceData('sites', { type: 'FeatureCollection', features: visibleSites }, 'features');
    _safeSetSourceData('rays', { type: 'FeatureCollection', features: rayToggle?.checked ? rays : [] }, 'features');
    _safeSetSourceData('sectors', { type: 'FeatureCollection', features: sectorToggle?.checked ? sectors : [] }, 'features');
    _safeSetSourceData('confidence', { type: 'FeatureCollection', features: confidenceToggle?.checked ? confidence : [] }, 'features');
    _safeSetSourceData('range-bands', { type: 'FeatureCollection', features: rangeBandToggle?.checked ? rangeBands : [] }, 'features');
    _safeSetSourceData('uncertainty-polygons', { type: 'FeatureCollection', features: confidenceToggle?.checked ? uncertaintyPolygons : [] }, 'features');
    if (_lastLoopMetrics?.timestamp && Number.isFinite(_lastLoopMetrics.features_total_after_write)) {
      const expected = Number(_lastLoopMetrics.features_total_after_write);
      if (expected !== totalFetched) {
        const warning = `Feature count mismatch: backend=${expected}, fetched=${totalFetched}`;
        loopStatus.innerHTML += `<br><span style="color:#f59e0b">${warning}</span>`;
        health.render.features = warning;
      }
    }
    _renderHealth();
  } catch (err) {
    health.render.features = `error: ${err.message}`;
    _renderHealth();
    console.warn('refreshSource error:', err.message);
  }
}

// ── Speculative layer ──────────────────────────────────────────────────────
async function refreshSpeculative() {
  if (!sourcesInitialized) return;
  try {
    const bounds = map.getBounds();
    const url = `/api/map/features?kind=speculative` +
      `&lat_min=${bounds.getSouth().toFixed(4)}&lat_max=${bounds.getNorth().toFixed(4)}` +
      `&lon_min=${bounds.getWest().toFixed(4)}&lon_max=${bounds.getEast().toFixed(4)}&limit=300`;
    const data = await fetch(url).then((r) => r.json());
    health.counts.speculative = (data.features || []).length;

    const rays = [], sectors = [], ellipses = [], rangeBands = [], uncertaintyPolygons = [];
    (data.features || []).forEach((f) => {
      const o = f.properties.overlay_geometries || {};
      if (o.direction_ray) rays.push(asFeature(f, o.direction_ray, 'direction_ray'));
      if (o.sector_wedge) sectors.push(asFeature(f, o.sector_wedge, 'sector_wedge'));
      if (o.confidence_ellipse) ellipses.push(asFeature(f, o.confidence_ellipse, 'confidence_ellipse'));
      if (o.range_likely_band) rangeBands.push(asFeature(f, o.range_likely_band, 'range_likely_band'));
      if (o.uncertainty_polygon) uncertaintyPolygons.push(asFeature(f, o.uncertainty_polygon, 'uncertainty_polygon'));
    });

    _safeSetSourceData('speculative', {
      type: 'FeatureCollection',
      features: spectToggle?.checked ? (data.features || []) : [],
    }, 'speculative');
    _safeSetSourceData('spec-rays', { type: 'FeatureCollection', features: rayToggle?.checked ? rays : [] }, 'speculative');
    _safeSetSourceData('spec-sectors', { type: 'FeatureCollection', features: sectorToggle?.checked ? sectors : [] }, 'speculative');
    _safeSetSourceData('spec-ellipses', { type: 'FeatureCollection', features: confidenceToggle?.checked ? ellipses : [] }, 'speculative');
    _safeSetSourceData('spec-range-bands', { type: 'FeatureCollection', features: rangeBandToggle?.checked ? rangeBands : [] }, 'speculative');
    _safeSetSourceData('spec-uncertainty-polygons', { type: 'FeatureCollection', features: confidenceToggle?.checked ? uncertaintyPolygons : [] }, 'speculative');
  } catch (err) {
    health.render.speculative = `error: ${err.message}`;
  } finally { _renderHealth(); }
}

// ── Coverage layer ─────────────────────────────────────────────────────────
async function refreshCoverage() {
  if (!sourcesInitialized || !coverageToggle?.checked) return;
  try {
    const data = await fetch('/api/map/coverage').then((r) => r.json());
    map.getSource('coverage').setData(data);
    const prog = await fetch('/api/usmap/progress').then((r) => r.json());
    if (coverageStatus) {
      coverageStatus.textContent =
        `Coverage: ${prog.percent_analyzed ?? 0}% analyzed · ${prog.percent_seeded ?? 0}% seeded`;
    }
  } catch (_) {}
}

// ── Satellite layer ────────────────────────────────────────────────────────
async function refreshSatellites() {
  if (!sourcesInitialized || !satelliteToggle?.checked) return;
  try {
    const group = satGroupSelect?.value || 'geo';
    const data = await fetch(`/api/satellites/positions?group=${group}&limit=40`).then((r) => r.json());
    _safeSetSourceData('satellites', data.geojson || { type: 'FeatureCollection', features: [] }, 'satellites');
  } catch (err) {
    health.render.satellites = `error: ${err.message}`;
  } finally { _renderHealth(); }
}

// ── Analysis Log ───────────────────────────────────────────────────────────
async function refreshAnalysisLog() {
  try {
    const data = await fetch('/api/analysis/log?limit=5').then((r) => r.json());
    if (!analysisLog) return;
    if (!data.entries?.length) { analysisLog.innerHTML = '<span class="muted">No analyses yet.</span>'; return; }
    analysisLog.innerHTML = data.entries.map((e) => {
      const ts = (e.timestamp || '').slice(0, 19).replace('T', ' ');
      return `<div class="log-entry"><span class="log-ts">${ts}</span> ` +
        `<strong>${e.model || '-'}</strong> · ${e.detections_count} detection(s)<br>` +
        `<span class="muted">${e.input_summary || ''}</span></div>`;
    }).join('');
  } catch (_) { if (analysisLog) analysisLog.innerHTML = '<span class="muted">unavailable</span>'; }
}

// ── Viewport auto-seed (fires when user pans map to a new area) ────────────
let _lastSeedCenter = null;
let _lastSeedTime = 0;

function _haversineKm(a, b) {
  const R = 6371, toRad = (d) => d * Math.PI / 180;
  const dLat = toRad(b.lat - a.lat), dLon = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(h));
}

function _autoSeedViewport() {
  const center = map.getCenter();
  const shifted = !_lastSeedCenter || _haversineKm(center, _lastSeedCenter) > 50;
  const throttled = Date.now() - _lastSeedTime < 30000;
  if (!shifted || throttled) return;
  _lastSeedCenter = center;
  _lastSeedTime = Date.now();
  fetch(`/api/map/seed?lat=${center.lat.toFixed(5)}&lon=${center.lng.toFixed(5)}&radius_km=50`, { method: 'POST' })
    .then((r) => r.json())
    .then((d) => { if (d.features_added > 0) { refreshSpeculative(); refreshSites(); } })
    .catch(() => {});
}

// ── Feature confirm/dismiss (called from popup HTML) ──────────────────────
window.confirmFeature = async function(featureId, confirmed) {
  const body = { feature_id: featureId, confirmed };
  if (confirmed) {
    const center = map.getCenter();
    body.true_lat = center.lat;
    body.true_lon = center.lng;
  }
  try {
    await fetch('/api/map/confirm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    await refreshSpeculative();
    if (details) details.textContent = confirmed ? 'Detection confirmed.' : 'Detection dismissed.';
  } catch (_) {}
};

// ── Calibration status ─────────────────────────────────────────────────────
async function refreshCalibration() {
  if (!calibrationStatus) return;
  try {
    const d = await fetch('/api/analysis/calibration').then((r) => r.json());
    if (d.count === 0) {
      calibrationStatus.textContent = 'Calibration: no confirmed features yet';
    } else {
      calibrationStatus.innerHTML =
        `<strong>Calibration:</strong> ${d.count} confirmed · ` +
        `mean error ${d.mean_error_m != null ? d.mean_error_m.toFixed(0) : '-'} m · ` +
        `median ${d.median_error_m != null ? d.median_error_m.toFixed(0) : '-'} m`;
    }
  } catch (_) { if (calibrationStatus) calibrationStatus.textContent = 'Calibration: -'; }
}

// ── Uncertain features ─────────────────────────────────────────────────────
async function refreshUncertain() {
  if (!sourcesInitialized) return;
  try {
    const d = await fetch('/api/analysis/uncertain?limit=10').then((r) => r.json());
    const count = d.count || 0;
    if (analyzeBtn) {
      analyzeBtn.textContent = count > 0 ? `Analyze Now (${count} need review)` : 'Analyze Now';
    }
    // Update uncertain-ring source with features needing confirmation
    const src = map.getSource('speculative-uncertain');
    if (src) src.setData({ type: 'FeatureCollection', features: d.features || [] });
  } catch (_) {}
}



function parseLatLon(input) {
  if (!input) return null;
  const parts = input.split(',').map((part) => Number(part.trim()));
  if (parts.length !== 2 || parts.some((n) => Number.isNaN(n))) return null;
  const [lat, lon] = parts;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}

function setupGoToLatLon() {
  const go = () => {
    const parsed = parseLatLon(goToLatLon?.value || '');
    if (!parsed) {
      if (details) details.textContent = 'Invalid lat/lon. Use format: lat, lon (e.g. 37.7749, -122.4194).';
      return;
    }
    map.flyTo({ center: [parsed.lon, parsed.lat], zoom: Math.max(map.getZoom(), 9), speed: 0.8 });
    if (details) details.textContent = `Moved map to ${parsed.lat.toFixed(5)}, ${parsed.lon.toFixed(5)}.`;
  };
  goToBtn?.addEventListener('click', go);
  goToLatLon?.addEventListener('keydown', (evt) => {
    if (evt.key === 'Enter') go();
  });
}
// ── Map load ───────────────────────────────────────────────────────────────
map.on('load', async () => {
  // Setup globe fog/spin only when capabilities are available.
  const canGetProjection = typeof map.getProjection === 'function';
  const canSetFog = typeof map.setFog === 'function';
  const projection = typeof map.getProjection === 'function' ? map.getProjection() : null;
  const projectionName = projection && typeof projection === 'object' ? projection.name : null;
  const isGlobeProjection = projectionName === 'globe';
  const fogCompatibleProjection = !projectionName || isGlobeProjection;

  if (canSetFog && fogCompatibleProjection) {
    try {
      map.setFog({
        color: 'rgba(15,23,42,0.85)',
        'high-color': '#1e3a5f',
        'horizon-blend': 0.04,
        'space-color': '#0f172a',
        'star-intensity': 0.35,
      });
    } catch (err) {
      _diagOnce('fog-runtime', 'Fog unsupported at runtime; continuing without fog.', err);
    }
  } else {
    _diagOnce(
      'fog-capability',
      `Fog unavailable (setFog=${canSetFog}, projection=${projectionName || 'unknown'}); continuing without fog.`
    );
  }

  _globeSpinSupported = canGetProjection && isGlobeProjection;
  if (_globeSpinSupported) {
    requestAnimationFrame(_spinGlobe);
  } else {
    _diagOnce(
      'spin-capability',
      `Globe spin unavailable (getProjection=${canGetProjection}, projection=${projectionName || 'unknown'}); continuing without globe spin.`
    );
  }

  map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
  map.addControl(new maplibregl.GeolocateControl({
    positionOptions: { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    trackUserLocation: true,
    showUserHeading: true,
  }), 'bottom-right');
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-left');
  map.addControl(new maplibregl.FullscreenControl(), 'top-right');
  setupGoToLatLon();

  await ensureMapDataLoadedAfterMigration();

  // Seed GeoJSON features from API
  const seed = await fetch('/api/features').then((r) => r.json()).catch(() => ({ features: [] }));
  sortedTimes = [...new Set(seed.features.map((f) => f.properties.timestamp))].filter(Boolean).sort();

  // ── Sources ──────────────────────────────────────────────────────────────
  map.addSource('sites',      { type: 'geojson', data: seed });
  map.addSource('rays',       { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('sectors',    { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('confidence', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('range-bands', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('uncertainty-polygons', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('speculative',{ type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('spec-rays',  { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('spec-sectors',{ type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('spec-ellipses',{ type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('spec-range-bands',{ type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('spec-uncertainty-polygons',{ type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('coverage',             { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('satellites',           { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addSource('speculative-uncertain',{ type: 'geojson', data: { type: 'FeatureCollection', features: [] } });

  const canRenderSymbolText = _hasValidGlyphs();

  // ── Layers - base ────────────────────────────────────────────────────────
  map.addLayer({ id: 'infra-layer',    type: 'circle', source: 'sites',
    filter: ['==', ['get', 'kind'], 'infrastructure'],
    paint: { 'circle-radius': 7, 'circle-color': '#4ea8ff', 'circle-stroke-width': 1, 'circle-stroke-color': '#fff' } });
  map.addLayer({ id: 'estimate-layer', type: 'circle', source: 'sites',
    filter: ['==', ['get', 'kind'], 'estimate'],
    paint: { 'circle-radius': 9, 'circle-color': '#ff8459', 'circle-opacity': 0.85, 'circle-stroke-width': 1, 'circle-stroke-color': '#fff' } });
  map.addLayer({ id: 'ray-layer',       type: 'line', source: 'rays',
    paint: { 'line-color': '#88d8ff', 'line-width': 2 } });
  map.addLayer({ id: 'sector-layer',    type: 'fill', source: 'sectors',
    paint: { 'fill-color': '#7ac37a', 'fill-opacity': 0.2 } });
  map.addLayer({ id: 'confidence-layer',type: 'fill', source: 'confidence',
    paint: { 'fill-color': '#ffc857', 'fill-opacity': 0.2 } });
  map.addLayer({ id: 'range-band-layer',type: 'fill', source: 'range-bands',
    paint: { 'fill-color': '#38bdf8', 'fill-opacity': 0.12 } });
  map.addLayer({ id: 'uncertainty-polygon-layer',type: 'line', source: 'uncertainty-polygons',
    paint: { 'line-color': '#f59e0b', 'line-width': 1.5, 'line-dasharray': [2, 2] } });

  // ── Layers - speculative ─────────────────────────────────────────────────
  map.addLayer({ id: 'spec-sector-layer', type: 'fill', source: 'spec-sectors',
    paint: { 'fill-color': '#c084fc', 'fill-opacity': 0.15 } });
  map.addLayer({ id: 'spec-ellipse-layer', type: 'fill', source: 'spec-ellipses',
    paint: { 'fill-color': '#c084fc', 'fill-opacity': 0.12 } });
  map.addLayer({ id: 'spec-range-band-layer', type: 'fill', source: 'spec-range-bands',
    paint: { 'fill-color': '#a78bfa', 'fill-opacity': 0.1 } });
  map.addLayer({ id: 'spec-uncertainty-polygon-layer', type: 'line', source: 'spec-uncertainty-polygons',
    paint: { 'line-color': '#e879f9', 'line-width': 1.2, 'line-dasharray': [2, 2] } });
  map.addLayer({ id: 'spec-ray-layer', type: 'line', source: 'spec-rays',
    paint: { 'line-color': '#c084fc', 'line-width': 1.5, 'line-dasharray': [4, 2] } });
  map.addLayer({ id: 'speculative-layer', type: 'circle', source: 'speculative',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'confidence'], 0, 5, 1, 9],
      'circle-color': '#c084fc', 'circle-opacity': 0.8,
      'circle-stroke-width': 1, 'circle-stroke-color': '#fff',
    } });

  // ── Layers - coverage grid ───────────────────────────────────────────────
  map.addLayer({ id: 'coverage-fill', type: 'fill', source: 'coverage',
    paint: {
      'fill-color': [
        'match', ['get', 'status'],
        'analyzed', '#22c55e', 'seeded', '#eab308', '#6b7280',
      ],
      'fill-opacity': 0.15,
    } });
  map.addLayer({ id: 'coverage-outline', type: 'line', source: 'coverage',
    paint: { 'line-color': '#374151', 'line-width': 0.5, 'line-opacity': 0.4 } });

  // ── Layers - satellites ──────────────────────────────────────────────────
  // ── Layer - uncertain features (pulsing outer ring) ─────────────────────
  map.addLayer({ id: 'uncertain-ring', type: 'circle', source: 'speculative-uncertain',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'confidence'], 0, 14, 1, 18],
      'circle-color': 'transparent',
      'circle-stroke-width': 2,
      'circle-stroke-color': '#facc15',  // amber ring = needs review
      'circle-opacity': 0.85,
    } });

  // ── Layers - satellites ──────────────────────────────────────────────────
  map.addLayer({ id: 'satellite-layer', type: 'circle', source: 'satellites',
    paint: { 'circle-radius': 5, 'circle-color': '#ffffff', 'circle-stroke-width': 1.5, 'circle-stroke-color': '#60a5fa' } });
  if (canRenderSymbolText) {
    map.addLayer({ id: 'satellite-label', type: 'symbol', source: 'satellites',
      layout: { 'text-field': ['get', 'name'], 'text-font': ['Noto Sans Regular'], 'text-size': 9, 'text-offset': [0, 1.2] },
      paint: { 'text-color': '#ffffff', 'text-halo-color': '#000', 'text-halo-width': 1 } });
  } else {
    console.warn('Map style glyphs unavailable; skipping satellite symbol labels.');
  }

  sourcesInitialized = true;

  // ── Click handlers ───────────────────────────────────────────────────────
  ['infra-layer', 'estimate-layer', 'speculative-layer', 'satellite-layer'].forEach((layer) => {
    map.on('click', layer, (e) => {
      const f = e.features?.[0];
      if (f) details.innerHTML = popupHtml(f.properties);
    });
    map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
  });

  // ── Toggle listeners ─────────────────────────────────────────────────────
  [infraToggle, estToggle, rayToggle, sectorToggle, confidenceToggle, rangeBandToggle, timeRange].forEach(
    (el) => el?.addEventListener('input', refreshSource)
  );
  spectToggle?.addEventListener('change', refreshSpeculative);
  coverageToggle?.addEventListener('change', () => {
    const vis = coverageToggle.checked ? 'visible' : 'none';
    ['coverage-fill', 'coverage-outline'].forEach((l) => map.setLayoutProperty(l, 'visibility', vis));
    if (coverageToggle.checked) refreshCoverage();
  });
  satelliteToggle?.addEventListener('change', () => {
    const vis = satelliteToggle.checked ? 'visible' : 'none';
    ['satellite-layer', ...(map.getLayer('satellite-label') ? ['satellite-label'] : [])].forEach((l) => map.setLayoutProperty(l, 'visibility', vis));
    if (satelliteToggle.checked) refreshSatellites();
  });
  satGroupSelect?.addEventListener('change', refreshSatellites);

  // ── Viewport auto-seed on map pan ─────────────────────────────────────────
  map.on('moveend', _autoSeedViewport);

  // ── Loop interval config ──────────────────────────────────────────────────
  loopIntervalEl?.addEventListener('change', async () => {
    const interval = parseInt(loopIntervalEl.value, 10);
    if (selectedModel) await applyModelSelection(selectedModel);
    else await fetch(`/api/loop/config?interval_seconds=${interval}`, { method: 'POST' }).catch(() => {});
  });
  logHeader?.addEventListener('click', () => {
    if (analysisLog) analysisLog.classList.toggle('collapsed');
  });

  // ── Initial data load ─────────────────────────────────────────────────────
  refreshSource();
  refreshLoopStatus();
  refreshSdrStatus();
  refreshSystemStatus();
  populateModelDropdown();
  refreshSpeculative();
  refreshAnalysisLog();
  refreshCalibration();
  refreshUncertain();

  // ── Polling intervals ─────────────────────────────────────────────────────
  setInterval(refreshLoopStatus, 10000);
  setInterval(refreshSdrStatus, 30000);
  setInterval(refreshSystemStatus, 10000);
  setInterval(refreshSpeculative, 15000);
  setInterval(refreshAnalysisLog, 30000);
  setInterval(refreshCoverage, 60000);
  setInterval(refreshCalibration, 60000);
  setInterval(refreshUncertain, 60000);
  // Refresh propagation layers every 90 s (they depend on feature store contents)
  setInterval(() => { if (propagationToggle?.checked) _loadPropagationFootprints(); }, 90000);
  setInterval(() => { if (interferenceToggle?.checked) _loadInterferenceZones(); }, 90000);
  setInterval(() => { if (vlfElfToggle?.checked) _loadVlfElfEmitters(); }, 90000);

  // ── Fox hunt / waterfall / SSE initialization ─────────────────────────────
  _addFoxSources();
  _initWaterfall();
  _refreshNodeList();
  _refreshFoxStatus();
  _connectSSE();
  setInterval(_refreshFoxStatus, 15000);
  setInterval(_refreshNodeList, 60000);
});

if (modelDropdown) {
  modelDropdown.addEventListener('change', () => applyModelSelection(modelDropdown.value));
}

// ═══════════════════════════════════════════════════════════════════════════
// ── FOX HUNT + WATERFALL + SSE ────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════

// ── DOM refs (fox panel) ──────────────────────────────────────────────────
const foxStateBadge  = document.getElementById('foxStateBadge');
const foxTargetBox   = document.getElementById('foxTargetBox');
const foxTargetFreq  = document.getElementById('foxTargetFreq');
const foxTargetMeta  = document.getElementById('foxTargetMeta');
const foxObsCount    = document.getElementById('foxObsCount');
const foxStart       = document.getElementById('foxStart');
const foxStop        = document.getElementById('foxStop');
const geoStatus      = document.getElementById('geoStatus');
const confirmedList  = document.getElementById('confirmedList');
const nodeList       = document.getElementById('nodeList');
const rediscoverBtn       = document.getElementById('rediscoverNodes');
const nodeDiscoveryStatus = document.getElementById('nodeDiscoveryStatus');
const waterfallCanvas= document.getElementById('waterfallCanvas');
const wfFreqAxis     = document.getElementById('waterfallFreqAxis');
const waterfallStatus = document.getElementById('waterfallStatus');
const peakList       = document.getElementById('peakList');
const foxToggle           = document.getElementById('foxToggle');
const bearingRayToggle    = document.getElementById('bearingRayToggle');
const waterfallHeader     = document.getElementById('waterfallHeader');
const waterfallContainer  = document.getElementById('waterfallContainer');
const peakListHeader      = document.getElementById('peakListHeader');
const autoHuntToggle      = document.getElementById('autoHuntToggle');
const autoPolicyPhase     = document.getElementById('autoPolicyPhase');
const emFieldToggle       = document.getElementById('emFieldToggle');
const beamPatternToggle   = document.getElementById('beamPatternToggle');
const propagationToggle   = document.getElementById('propagationToggle');
const skipZoneToggle      = document.getElementById('skipZoneToggle');
const interferenceToggle  = document.getElementById('interferenceToggle');
const vlfElfToggle        = document.getElementById('vlfElfToggle');
let _autoHuntEnabled = false;

// ── Waterfall state ───────────────────────────────────────────────────────
const WF_BINS = 1024;
const WF_ROWS = 120;   // pixel height
let _wfCtx = null;
let _wfImageData = null;
let _wfRowCount = 0;
let _wfBins = WF_BINS;
let _wfCenterFreqHz = null;
let _wfBandwidthHz = null;
let _wfLastFrameAt = 0;
let _wfDecodeMismatchCount = 0;
let _wfLastSeqByNode = new Map();
let _wfDroppedFrameCount = 0;
const _wfStaleTimeoutMs = 15000;

function _initWaterfall() {
  if (!waterfallCanvas) return;
  waterfallCanvas.width = _wfBins;
  waterfallCanvas.height = WF_ROWS;
  _wfCtx = waterfallCanvas.getContext('2d');
  _wfImageData = _wfCtx.createImageData(_wfBins, WF_ROWS);
  _wfImageData.data.fill(0);
  _renderWaterfallFreqAxis();
  _setWaterfallStatus('connected');
}

function _renderWaterfallFreqAxis() {
  if (!wfFreqAxis) return;
  if (!_wfCenterFreqHz || !_wfBandwidthHz) {
    wfFreqAxis.innerHTML = [0,5,10,15,20,25,30].map((f) => `<span>${f}</span>`).join('');
    return;
  }
  const steps = 7;
  const low = _wfCenterFreqHz - (_wfBandwidthHz / 2);
  const binBwHz = _wfBandwidthHz / Math.max(1, _wfBins);
  wfFreqAxis.innerHTML = Array.from({ length: steps }, (_, i) => {
    const frac = i / (steps - 1);
    const bin = frac * (_wfBins - 1);
    const hz = low + (bin * binBwHz);
    return `<span>${(hz / 1e6).toFixed(3)}</span>`;
  }).join('');
}

function _setWaterfallStatus(state, detail = '') {
  if (!waterfallStatus) return;
  waterfallStatus.className = 'waterfall-status';
  if (state === 'receiving') {
    waterfallStatus.classList.add('status-receiving');
    waterfallStatus.textContent = detail || 'Receiving data';
  } else if (state === 'mismatch') {
    waterfallStatus.classList.add('status-mismatch');
    waterfallStatus.textContent = detail || 'Decode/config mismatch';
  } else {
    waterfallStatus.classList.add('status-connected');
    waterfallStatus.textContent = detail || 'Connected · waiting for data';
  }
}

function _initVhfWaterfall(centerMhz, bwMhz) {
  if (!waterfallCanvasVhf) return;
  waterfallCanvasVhf.width = WF_BINS;
  waterfallCanvasVhf.height = WF_ROWS;
  waterfallCanvasVhf.style.display = 'block';
  if (vhfBandLabel) vhfBandLabel.style.display = 'block';
  if (wfFreqAxisVhf) wfFreqAxisVhf.style.display = 'flex';
  _wfVhfCtx = waterfallCanvasVhf.getContext('2d');
  _wfVhfImageData = _wfVhfCtx.createImageData(WF_BINS, WF_ROWS);
  _wfVhfImageData.data.fill(0);
  if (wfFreqAxisVhf && bwMhz) {
    const start = centerMhz - bwMhz / 2;
    const end = centerMhz + bwMhz / 2;
    const steps = 5;
    const labels = Array.from({ length: steps + 1 }, (_, i) =>
      `<span>${(start + (i * bwMhz) / steps).toFixed(0)}</span>`
    );
    wfFreqAxisVhf.innerHTML = labels.join('');
  }
}

function _renderMosaicFrame(segments) {
  if (!segments || !segments.length) return;
  const hf = segments.find((s) => s.center_freq_hz < 50e6);
  const vhf = segments.find((s) => s.center_freq_hz >= 50e6);
  if (hf && hf.bins_db && hf.bins_db.length >= 64) {
    _pushWaterfallRow(hf.bins_db);
  }
  if (vhf && vhf.bins_db && vhf.bins_db.length >= 64) {
    if (!_wfVhfCtx) {
      _initVhfWaterfall(vhf.center_freq_hz / 1e6, vhf.bandwidth_hz / 1e6);
    }
    _pushVhfWaterfallRow(vhf.bins_db);
  }
}

function _pushVhfWaterfallRow(bins) {
  if (!_wfVhfCtx || !_wfVhfImageData) return;
  const data = _wfVhfImageData.data;
  data.copyWithin(0, WF_BINS * 4);
  const baseIdx = (WF_ROWS - 1) * WF_BINS * 4;
  const srcBins = bins.length >= WF_BINS ? bins : _resampleBins(bins, WF_BINS);
  for (let i = 0; i < WF_BINS; i++) {
    const [r, g, b] = _dbToRgba(srcBins[i]);
    const idx = baseIdx + i * 4;
    data[idx] = r; data[idx + 1] = g; data[idx + 2] = b; data[idx + 3] = 255;
  }
  _wfVhfCtx.putImageData(_wfVhfImageData, 0, 0);
}

function _resampleBins(bins, targetLen) {
  const result = new Array(targetLen);
  for (let i = 0; i < targetLen; i++) {
    const srcIdx = (i / targetLen) * bins.length;
    const lo = Math.floor(srcIdx);
    const hi = Math.min(lo + 1, bins.length - 1);
    const t = srcIdx - lo;
    result[i] = bins[lo] * (1 - t) + bins[hi] * t;
  }
  return result;
}

// Map dB value to RGBA colour (dark blue → cyan → yellow → red)
function _dbToRgba(db) {
  // Normalise -127..−13 dBm → 0..1
  const t = Math.max(0, Math.min(1, (db + 127) / 114));
  let r, g, b;
  if (t < 0.25) {          // dark navy → blue
    const s = t / 0.25;
    r = 0; g = Math.round(s * 50); b = Math.round(50 + s * 150);
  } else if (t < 0.5) {   // blue → cyan
    const s = (t - 0.25) / 0.25;
    r = 0; g = Math.round(50 + s * 205); b = 200;
  } else if (t < 0.75) {  // cyan → yellow
    const s = (t - 0.5) / 0.25;
    r = Math.round(s * 255); g = 255; b = Math.round(200 * (1 - s));
  } else {                 // yellow → red
    const s = (t - 0.75) / 0.25;
    r = 255; g = Math.round(255 * (1 - s)); b = 0;
  }
  return [r, g, b];
}

function _pushWaterfallRow(bins) {
  if (!_wfCtx || !_wfImageData) return;
  const data = _wfImageData.data;
  data.copyWithin(0, _wfBins * 4);
  const baseIdx = (WF_ROWS - 1) * _wfBins * 4;
  const srcBins = bins.length >= _wfBins ? bins : _resampleBins(bins, _wfBins);
  for (let i = 0; i < _wfBins; i++) {
    const [r, g, b] = _dbToRgba(srcBins[i]);
    const idx = baseIdx + i * 4;
    data[idx] = r; data[idx + 1] = g; data[idx + 2] = b; data[idx + 3] = 255;
  }
  _wfCtx.putImageData(_wfImageData, 0, 0);
  _wfRowCount++;
}

// ── Local GeoJSON stores (replaces src._data private access) ─────────────
let _foxTargetsData = { type: 'FeatureCollection', features: [] };
let _emFieldsData   = { type: 'FeatureCollection', features: [] };

// ── Map sources & layers for fox hunt ────────────────────────────────────
let _foxSourcesAdded = false;

function _addFoxSources() {
  if (_foxSourcesAdded || !map.getStyle()) return;
  _foxSourcesAdded = true;
  const empty = { type: 'FeatureCollection', features: [] };
  map.addSource('fox-targets',  { type: 'geojson', data: empty });
  map.addSource('fox-ellipses', { type: 'geojson', data: empty });
  map.addSource('fox-bearings', { type: 'geojson', data: empty });
  map.addSource('bayes-field',  { type: 'geojson', data: empty });
  map.addSource('em-fields',             { type: 'geojson', data: empty });
  map.addSource('beam-patterns',         { type: 'geojson', data: empty });
  map.addSource('propagation-footprints',{ type: 'geojson', data: empty });
  map.addSource('interference-zones',    { type: 'geojson', data: empty });
  map.addSource('vlf-elf-emitters',      { type: 'geojson', data: empty });

  // Bayesian posterior heatmap (rendered below fox layers)
  map.addLayer({ id: 'bayes-fill', type: 'fill', source: 'bayes-field',
    layout: { visibility: 'none' },
    paint: {
      'fill-color': ['interpolate', ['linear'], ['get', 'probability'],
        0,      'rgba(59,130,246,0)',
        0.001,  'rgba(59,130,246,0.4)',
        0.01,   'rgba(245,158,11,0.55)',
        0.05,   'rgba(239,68,68,0.7)',
      ],
      'fill-opacity': 1,
    } });

  // EM field overlays
  map.addLayer({ id: 'em-fields-fill', type: 'fill', source: 'em-fields',
    layout: { visibility: 'none' },
    paint: { 'fill-color': 'rgba(251,191,36,0.12)', 'fill-outline-color': 'rgba(251,191,36,0.6)' } });

  // Beam pattern lines
  map.addLayer({ id: 'beam-patterns-line', type: 'line', source: 'beam-patterns',
    layout: { visibility: 'none' },
    paint: { 'line-color': '#fb923c', 'line-width': 1.5, 'line-dasharray': [4, 2] } });

  // ── Propagation footprints ───────────────────────────────────────────────
  // Soft fill coloured by frequency band
  map.addLayer({ id: 'propagation-fill', type: 'fill', source: 'propagation-footprints',
    layout: { visibility: 'none' },
    paint: { 'fill-color': ['get', 'band_color'], 'fill-opacity': 0.06 } });
  // Dashed outline at max-range boundary
  map.addLayer({ id: 'propagation-outline', type: 'line', source: 'propagation-footprints',
    layout: { visibility: 'none' },
    paint: {
      'line-color': ['get', 'band_color'],
      'line-width': ['case', ['get', 'is_global'], 2.5, 1.5],
      'line-opacity': 0.7,
      'line-dasharray': ['case', ['get', 'is_hf'], ['literal', [6, 3]], ['literal', [3, 2]]],
    } });
  // Distance label at centroid (only at zoom ≥ 4 to avoid clutter)
  map.addLayer({ id: 'propagation-label', type: 'symbol', source: 'propagation-footprints',
    layout: {
      visibility: 'none',
      'text-field': ['concat', ['get', 'mode'], '\n', ['to-string', ['get', 'max_range_km']], ' km'],
      'text-size': 10,
      'symbol-placement': 'point',
    },
    paint: { 'text-color': ['get', 'band_color'], 'text-halo-color': '#000', 'text-halo-width': 1.5 },
    minzoom: 3 });

  // ── Interference heatmap ─────────────────────────────────────────────────
  map.addLayer({ id: 'interference-heatmap', type: 'heatmap', source: 'interference-zones',
    layout: { visibility: 'none' },
    paint: {
      'heatmap-weight': ['interpolate', ['linear'], ['get', 'interference_ratio'], 0, 1, 1, 0, 2, 1],
      'heatmap-intensity': 1.2,
      'heatmap-color': [
        'interpolate', ['linear'], ['heatmap-density'],
        0,   'rgba(0,0,0,0)',
        0.2, 'rgba(239,68,68,0.35)',    // destructive — red
        0.5, 'rgba(107,114,128,0.2)',   // neutral — grey
        0.8, 'rgba(34,197,94,0.35)',    // constructive — green
        1.0, 'rgba(74,222,128,0.55)',
      ],
      'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 1, 60, 8, 20],
      'heatmap-opacity': 0.75,
    } });

  // ── VLF / ELF / UWB emitter markers ─────────────────────────────────────
  map.addLayer({ id: 'vlf-elf-layer', type: 'circle', source: 'vlf-elf-emitters',
    layout: { visibility: 'none' },
    paint: {
      'circle-radius': 10,
      'circle-color': '#7c3aed',
      'circle-stroke-width': 2.5,
      'circle-stroke-color': '#e9d5ff',
      'circle-opacity': 0.9,
    } });
  map.addLayer({ id: 'vlf-elf-label', type: 'symbol', source: 'vlf-elf-emitters',
    layout: {
      visibility: 'none',
      'text-field': ['concat', ['get', 'display_label'], ' · ', ['get', 'name']],
      'text-size': 10,
      'text-offset': [0, 1.4],
    },
    paint: { 'text-color': '#c4b5fd', 'text-halo-color': '#000', 'text-halo-width': 1.2 } });

  // ── Click handler for VLF/ELF emitters ──────────────────────────────────
  map.on('click', 'vlf-elf-layer', (e) => {
    const f = e.features?.[0];
    if (!f || !details) return;
    const p = f.properties;
    details.innerHTML = `<strong>${p.name || p.id}</strong><br>` +
      `Band: <strong>${p.display_label}</strong><br>` +
      `Freq: ${p.freq_mhz} MHz<br>` +
      `Mode: ${p.mode || '—'}<br>` +
      `Max range: ${p.max_range_km} km<br>` +
      `EIRP: ${p.eirp_dbm} dBm<br>` +
      `Kind: ${p.kind}`;
  });
  map.on('mouseenter', 'vlf-elf-layer', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'vlf-elf-layer', () => { map.getCanvas().style.cursor = ''; });

  // Uncertainty ellipses (fill + outline)
  map.addLayer({ id: 'fox-ellipse-fill', type: 'fill', source: 'fox-ellipses',
    paint: { 'fill-color': '#4ade80', 'fill-opacity': 0.1 } });
  map.addLayer({ id: 'fox-ellipse-outline', type: 'line', source: 'fox-ellipses',
    paint: { 'line-color': '#4ade80', 'line-width': 1.5, 'line-dasharray': [3, 2] } });

  // Bearing rays from observer positions
  map.addLayer({ id: 'fox-bearing-rays', type: 'line', source: 'fox-bearings',
    paint: { 'line-color': '#fbbf24', 'line-width': 1.5, 'line-opacity': 0.7 } });

  // Confirmed target circles
  map.addLayer({ id: 'fox-target-layer', type: 'circle', source: 'fox-targets',
    paint: {
      'circle-radius': 11,
      'circle-color': '#4ade80',
      'circle-stroke-width': 2.5,
      'circle-stroke-color': '#fff',
    } });

  // Directional bearing arrow overlay on confirmed targets
  // icon-rotate reads azimuth_deg from each feature's properties for real-time
  // rotation updates — MapLibre re-renders automatically when source data changes.
  _addBearingArrowIcon().then(() => {
    map.addLayer({
      id: 'fox-bearing-arrows',
      type: 'symbol',
      source: 'fox-targets',
      layout: {
        'icon-image': 'bearing-arrow',
        'icon-size': 1.2,
        'icon-rotate': ['coalesce', ['get', 'azimuth_deg'], 0],
        'icon-rotation-alignment': 'map',
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
      },
      filter: ['has', 'azimuth_deg'],
    });
  });

  if (_hasValidGlyphs()) {
    map.addLayer({ id: 'fox-target-label', type: 'symbol', source: 'fox-targets',
      layout: { 'text-field': ['get', 'freq_label'], 'text-font': ['Noto Sans Regular'], 'text-size': 9, 'text-offset': [0, 1.6] },
      paint: { 'text-color': '#4ade80', 'text-halo-color': '#000', 'text-halo-width': 1 } });
  } else {
    console.warn('Map style glyphs unavailable; skipping fox target symbol labels.');
  }

  // Click handler for fox targets
  map.on('click', 'fox-target-layer', (e) => {
    const f = e.features?.[0];
    if (!f || !details) return;
    const p = f.properties;
    const methods = typeof p.methods === 'string' ? JSON.parse(p.methods) : (p.methods || []);
    details.innerHTML = `<strong>${p.name}</strong><br>` +
      `Freq: ${p.freq_mhz} MHz<br>Band: ${p.band_label}<br>` +
      `Confidence: ${(p.confidence * 100).toFixed(0)}%<br>` +
      `Uncertainty: ±${p.uncertainty_m?.toFixed(0)} m<br>` +
      `Methods: ${methods.join(', ')}<br>` +
      `Bearings: ${p.bearing_obs_count} · RSSI: ${p.rssi_obs_count}`;
  });
  map.on('mouseenter', 'fox-target-layer', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'fox-target-layer', () => { map.getCanvas().style.cursor = ''; });
}

// Live bearing rays accumulator
const _bearingObs = [];   // {lat, lon, bearing_deg}

function _updateBearingRaySource() {
  const src = map.getSource('fox-bearings');
  if (!src) return;
  // For each observation draw a 30 km line in the bearing direction
  const RAY_M = 30_000;
  const lines = _bearingObs.map((o) => {
    const brRad = (o.bearing_deg * Math.PI) / 180;
    const dR = RAY_M / 6_371_000;
    const lat1 = (o.lat * Math.PI) / 180;
    const lon1 = (o.lon * Math.PI) / 180;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(dR) + Math.cos(lat1) * Math.sin(dR) * Math.cos(brRad));
    const lon2 = lon1 + Math.atan2(Math.sin(brRad) * Math.sin(dR) * Math.cos(lat1),
                                    Math.cos(dR) - Math.sin(lat1) * Math.sin(lat2));
    return {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [
        [o.lon, o.lat],
        [(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI],
      ]},
      properties: { bearing_deg: o.bearing_deg },
    };
  });
  src.setData({ type: 'FeatureCollection', features: lines });
}

// ── Fox hunt state badge ──────────────────────────────────────────────────
const STATE_CLASSES = {
  IDLE: 'state-idle', SCANNING: 'state-scanning', ACQUIRING: 'state-acquiring',
  COLLECTING: 'state-collecting', SOLVING: 'state-solving', CONFIRMED: 'state-confirmed',
};

function _setFoxState(state) {
  if (!foxStateBadge) return;
  foxStateBadge.textContent = state;
  foxStateBadge.className = `fox-state-badge ${STATE_CLASSES[state] || 'state-idle'}`;
}

// ── SSE event handler ─────────────────────────────────────────────────────
let _sseConnected = false;
let _sseSource = null;

function _connectSSE() {
  if (_sseConnected) return;
  _sseSource = new EventSource('/api/events');
  _sseSource.onopen = () => { _sseConnected = true; };
  _sseSource.onerror = () => {
    _sseConnected = false;
    setTimeout(_connectSSE, 5000);
  };
  _sseSource.onmessage = (e) => {
    let ev;
    try { ev = JSON.parse(e.data); } catch { return; }
    _handleSseEvent(ev);
  };
}

function _handleSseEvent(ev) {
  switch (ev.type) {
    case 'fox_state':
      _setFoxState(ev.state);
      if (ev.state === 'IDLE' || ev.state === 'SCANNING') {
        if (foxTargetBox) foxTargetBox.style.display = 'none';
      }
      break;

    case 'scan_results':
      _renderPeakList(ev.peaks || []);
      break;

    case 'rssi_acquired':
      // Update node RSSI display
      break;

    case 'bearing_added':
      _bearingObs.push({ lat: ev.lat, lon: ev.lon, bearing_deg: ev.bearing_deg });
      _updateBearingRaySource();
      if (foxObsCount)
        foxObsCount.textContent = `${ev.total_bearings} bearing(s) logged${ev.source ? ` · ${ev.source}` : ''}`;
      break;

    case 'estimate_updated': {
      // Update live ellipse on map
      const src = map.getSource('fox-ellipses');
      if (src && ev.lat && ev.lon) {
        const coords = _buildEllipseCoords(ev.lat, ev.lon, ev.ellipse_major_m || ev.uncertainty_m || 500, ev.ellipse_minor_m || ev.uncertainty_m * 0.6 || 300);
        src.setData({ type: 'FeatureCollection', features: [{
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [coords] },
          properties: { confidence: ev.confidence },
        }]});
      }
      break;
    }
    case 'analysis_cycle_success': {
      _deterministicFeatureRefreshSequence();
      refreshAnalysisLog();
      break;
    }

    case 'target_pinned': {
      const src = map.getSource('fox-targets');
      if (src && ev.feature) {
        ev.feature.properties.freq_label = `${(ev.freq_hz / 1e6).toFixed(2)} MHz`;
        _foxTargetsData.features.push(ev.feature);
        health.counts.fox_targets = _foxTargetsData.features.length;
        _safeSetSourceData('fox-targets', _foxTargetsData, 'fox_targets');
      }
      _addConfirmedItem(ev);
      _bearingObs.length = 0;
      _updateBearingRaySource();
      _renderHealth();
      break;
    }

    case 'sdr_frame': {
      const bins = ev.fft_bins || ev.bins || ev.bins_db;
      const provenance = ev.source_provenance || ev.provenance || 'unknown';
      const centerHz = Number(ev.center_freq_hz);
      const bwHz = Number(ev.span_hz || ev.bw_hz || ev.sample_rate_hz);
      const nodeKey = `${ev?.source?.host || ev.node || 'unknown'}:${ev?.source?.port || 8073}`;
      const frameSeq = Number(ev.frame_seq);
      if (!Array.isArray(bins) || bins.length < 4) {
        _wfDecodeMismatchCount += 1;
        _setWaterfallStatus('mismatch', 'Decode/config mismatch: missing waterfall bins');
        break;
      }
      if (_wfBins !== bins.length) {
        _wfBins = bins.length;
        _initWaterfall();
      }
      if (Number.isFinite(frameSeq)) {
        const prevSeq = _wfLastSeqByNode.get(nodeKey);
        if (Number.isFinite(prevSeq) && frameSeq > (prevSeq + 1)) {
          _wfDroppedFrameCount += (frameSeq - prevSeq - 1);
        }
        _wfLastSeqByNode.set(nodeKey, frameSeq);
      }
      if (Number.isFinite(centerHz) && Number.isFinite(bwHz) && bwHz > 0) {
        _wfCenterFreqHz = centerHz;
        _wfBandwidthHz = bwHz;
        _renderWaterfallFreqAxis();
      }
      _pushWaterfallRow(bins);
      _wfLastFrameAt = Date.now();
      _setWaterfallStatus(
        'receiving',
        `Receiving data (${provenance}) · ${_wfBins} bins · ${(centerHz/1e6).toFixed(3)} MHz center · ${(bwHz/1e3).toFixed(1)} kHz span · dropped ${_wfDroppedFrameCount}`
      );
      if (_wfDecodeMismatchCount > 0) {
        _wfDecodeMismatchCount = 0;
      }
      break;
    }

    case 'spectrum_mosaic':
      _renderMosaicFrame(ev.segments);
      break;

    case 'em_field_updated': {
      const src = map.getSource('em-fields');
      if (src && ev.geometry) {
        const newFeat = {
          type: 'Feature',
          geometry: ev.geometry,
          properties: { feature_id: ev.feature_id },
        };
        const idx = _emFieldsData.features.findIndex((f) => f.properties?.feature_id === ev.feature_id);
        if (idx >= 0) _emFieldsData.features[idx] = newFeat;
        else _emFieldsData.features.push(newFeat);
        src.setData(_emFieldsData);
      }
      break;
    }

    case 'feature_corrected': {
      const src = map.getSource('fox-targets');
      if (src && ev.lat && ev.lon) {
        const f = _foxTargetsData.features.find((ft) => ft.properties?.id === ev.feature_id);
        if (f) {
          f.geometry.coordinates = [ev.lon, ev.lat];
          src.setData(_foxTargetsData);
        }
      }
      break;
    }

  }
}

setInterval(() => {
  if (!_sseConnected) {
    _setWaterfallStatus('mismatch', 'Decode/config mismatch: SSE disconnected');
    return;
  }
  if (_wfLastFrameAt === 0 || (Date.now() - _wfLastFrameAt) > _wfStaleTimeoutMs) {
    const staleMs = _wfLastFrameAt === 0 ? null : (Date.now() - _wfLastFrameAt);
    const staleNote = staleMs == null ? 'waiting for data' : `stale stream timeout (${Math.round(staleMs / 1000)}s)`;
    _setWaterfallStatus('connected', `Connected · ${staleNote} · dropped ${_wfDroppedFrameCount}`);
  }
}, 3000);

// ── Ellipse polygon helper ────────────────────────────────────────────────
function _buildEllipseCoords(lat, lon, majorM, minorM, angleDeg = 0, steps = 48) {
  const cosA = Math.cos((angleDeg * Math.PI) / 180);
  const sinA = Math.sin((angleDeg * Math.PI) / 180);
  const cosLat = Math.cos((lat * Math.PI) / 180);
  const coords = [];
  for (let i = 0; i <= steps; i++) {
    const theta = (2 * Math.PI * i) / steps;
    const x = majorM * Math.cos(theta);
    const y = minorM * Math.sin(theta);
    const xe = x * cosA - y * sinA;
    const yn = x * sinA + y * cosA;
    coords.push([
      lon + xe / (111_320 * Math.max(cosLat, 0.001)),
      lat + yn / 111_320,
    ]);
  }
  return coords;
}

// ── Confirmed target panel item ───────────────────────────────────────────
function _addConfirmedItem(ev) {
  if (!confirmedList) return;
  const item = document.createElement('div');
  item.className = 'confirmed-item';
  const freqMhz = (ev.freq_hz / 1e6).toFixed(3);
  const conf = ev.confidence != null ? `${(ev.confidence * 100).toFixed(0)}%` : '-';
  item.innerHTML = `<span class="confirmed-freq">${freqMhz} MHz</span><span class="confirmed-conf">${conf}</span>`;
  item.onclick = () => {
    if (ev.feature?.geometry?.coordinates) {
      map.flyTo({ center: ev.feature.geometry.coordinates, zoom: 14 });
    }
  };
  confirmedList.insertBefore(item, confirmedList.firstChild);
}

// ── Peak list renderer ────────────────────────────────────────────────────
function _renderPeakList(peaks) {
  if (!peakList) return;
  peakList.innerHTML = peaks.slice(0, 20).map((p) => {
    const mhz = (p.freq_hz / 1e6).toFixed(3);
    return `<div class="peak-item" onclick="_tuneToFreq(${p.freq_hz})">
      <span class="peak-freq">${mhz} MHz</span>
      <span class="peak-snr">${p.snr_db?.toFixed(1)} dB</span>
      <span class="peak-mod">${p.modulation_hint || ''}</span>
    </div>`;
  }).join('');
}

window._tuneToFreq = function(freqHz) {
  // Pan map to nearest confirmed feature at that frequency if one exists
  const feat = _foxTargetsData.features.find(
    (f) => Math.abs((f.properties.freq_hz || 0) - freqHz) < 50_000
  );
  if (feat?.geometry?.coordinates) {
    map.flyTo({ center: feat.geometry.coordinates, zoom: 13 });
  }
};

// ── Node list renderer ────────────────────────────────────────────────────
async function _refreshNodeList() {
  const data = await fetch('/api/sdr/nodes').then((r) => r.json()).catch(() => ({ nodes: [] }));
  const nodes = data.nodes || [];
  if (nodeDiscoveryStatus && nodes.length > 0) {
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    nodeDiscoveryStatus.textContent = `${nodes.length} nodes · updated ${now}`;
  }
  if (!nodeList) return;
  nodeList.innerHTML = nodes.map((n) =>
    `<div class="node-item" data-hostport="${n.host}:${n.port}">
       <span class="node-dot unknown"></span>
       <span class="node-label">${n.host}:${n.port}${n.description ? ' · ' + n.description : ''}</span>
     </div>`
  ).join('') || '<div style="color:#475569;font-size:11px;padding:4px">Discovering…</div>';
}

// ── Fox hunt button handlers ──────────────────────────────────────────────
function _startFoxHuntAuto() {
  const _doStart = async (lat, lon) => {
    await fetch('/api/foxhunt/auto/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat, lon }),
    }).catch(() => {});
    _setFoxState('SCANNING');
    if (foxTargetBox) foxTargetBox.style.display = 'block';
  };

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        if (geoStatus) geoStatus.textContent = `Position: ${lat.toFixed(4)}, ${lon.toFixed(4)}`;
        _doStart(lat, lon);
      },
      () => {
        if (geoStatus) geoStatus.textContent = 'Position: using SDR node centroid';
        _doStart(0, 0);
      },
      { timeout: 5000 }
    );
  } else {
    if (geoStatus) geoStatus.textContent = 'Position: using SDR node centroid';
    _doStart(0, 0);
  }
}

foxStart?.addEventListener('click', _startFoxHuntAuto);

foxStop?.addEventListener('click', async () => {
  await fetch('/api/foxhunt/auto/stop', { method: 'POST' }).catch(() => {});
  _setFoxState('IDLE');
});

autoHuntToggle?.addEventListener('click', () => {
  if (!_autoHuntEnabled) {
    const _doAutoHunt = async (lat, lon) => {
      await fetch('/api/foxhunt/autonomous/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat, lon }),
      }).catch(() => {});
      _autoHuntEnabled = true;
      if (autoHuntToggle) autoHuntToggle.textContent = 'Auto Hunt: ON';
    };
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (geoStatus) geoStatus.textContent = `Position: ${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`;
          _doAutoHunt(pos.coords.latitude, pos.coords.longitude);
        },
        () => {
          if (geoStatus) geoStatus.textContent = 'Position: using SDR node centroid';
          _doAutoHunt(0, 0);
        },
        { timeout: 5000 }
      );
    } else {
      _doAutoHunt(0, 0);
    }
  } else {
    fetch('/api/foxhunt/autonomous/stop', { method: 'POST' }).catch(() => {});
    _autoHuntEnabled = false;
    if (autoHuntToggle) autoHuntToggle.textContent = 'Auto Hunt: OFF';
  }
});


rediscoverBtn?.addEventListener('click', async () => {
  if (rediscoverBtn) rediscoverBtn.textContent = '↺ Discovering…';
  const data = await fetch('/api/sdr/nodes/discover', { method: 'POST' })
    .then((r) => r.json()).catch(() => null);
  if (nodeDiscoveryStatus && data) {
    nodeDiscoveryStatus.textContent = `+${data.added} discovered · ${data.total} total`;
  }
  if (rediscoverBtn) rediscoverBtn.textContent = '↺ Rediscover';
  await _refreshNodeList();
});

// Toggle visibility of fox layers
foxToggle?.addEventListener('change', () => {
  const vis = foxToggle.checked ? 'visible' : 'none';
  ['fox-target-layer', 'fox-target-label', 'fox-ellipse-fill',
   'fox-ellipse-outline'].forEach((l) => {
    try { map.setLayoutProperty(l, 'visibility', vis); } catch {}
  });
});

bearingRayToggle?.addEventListener('change', () => {
  const vis = bearingRayToggle.checked ? 'visible' : 'none';
  try { map.setLayoutProperty('fox-bearing-rays', 'visibility', vis); } catch {}
});

bayesToggle?.addEventListener('change', () => {
  const vis = bayesToggle.checked ? 'visible' : 'none';
  try { map.setLayoutProperty('bayes-fill', 'visibility', vis); } catch {}
  if (bayesToggle.checked) refreshBayesField();
});

emFieldToggle?.addEventListener('change', () => {
  const vis = emFieldToggle.checked ? 'visible' : 'none';
  try { map.setLayoutProperty('em-fields-fill', 'visibility', vis); } catch {}
  if (emFieldToggle.checked) _loadEmFields();
});

beamPatternToggle?.addEventListener('change', () => {
  const vis = beamPatternToggle.checked ? 'visible' : 'none';
  try { map.setLayoutProperty('beam-patterns-line', 'visibility', vis); } catch {}
});

propagationToggle?.addEventListener('change', () => {
  const vis = propagationToggle.checked ? 'visible' : 'none';
  ['propagation-fill', 'propagation-outline', 'propagation-label'].forEach((l) => {
    try { map.setLayoutProperty(l, 'visibility', vis); } catch {}
  });
  if (propagationToggle.checked) _loadPropagationFootprints();
});

skipZoneToggle?.addEventListener('change', () => {
  // Skip zones are encoded as donut polygons within propagation-footprints;
  // toggling this filters the layer to show only HF donuts
  const vis = skipZoneToggle.checked ? 'visible' : 'none';
  try {
    map.setFilter('propagation-fill',    skipZoneToggle.checked ? null : ['!', ['get', 'is_hf']]);
    map.setFilter('propagation-outline', skipZoneToggle.checked ? null : null);
    map.setLayoutProperty('propagation-fill',    'visibility', vis);
    map.setLayoutProperty('propagation-outline', 'visibility', vis);
  } catch {}
  if (skipZoneToggle.checked) _loadPropagationFootprints();
});

interferenceToggle?.addEventListener('change', () => {
  const vis = interferenceToggle.checked ? 'visible' : 'none';
  try { map.setLayoutProperty('interference-heatmap', 'visibility', vis); } catch {}
  if (interferenceToggle.checked) _loadInterferenceZones();
});

vlfElfToggle?.addEventListener('change', () => {
  const vis = vlfElfToggle.checked ? 'visible' : 'none';
  ['vlf-elf-layer', 'vlf-elf-label'].forEach((l) => {
    try { map.setLayoutProperty(l, 'visibility', vis); } catch {}
  });
  if (vlfElfToggle.checked) _loadVlfElfEmitters();
});

async function _loadEmFields() {
  try {
    const data = await fetch('/api/em_fields').then((r) => r.json());
    const src = map.getSource('em-fields');
    if (src) src.setData(data);
  } catch {}
}

async function _loadPropagationFootprints() {
  try {
    const b = map.getBounds();
    const url = `/api/propagation/footprints?lat_min=${b.getSouth().toFixed(3)}&lat_max=${b.getNorth().toFixed(3)}&lon_min=${b.getWest().toFixed(3)}&lon_max=${b.getEast().toFixed(3)}`;
    const data = await fetch(url).then((r) => r.json());
    const src = map.getSource('propagation-footprints');
    if (src) src.setData(data);
  } catch {}
}

async function _loadInterferenceZones() {
  try {
    const b = map.getBounds();
    const url = `/api/propagation/interference?lat_min=${b.getSouth().toFixed(3)}&lat_max=${b.getNorth().toFixed(3)}&lon_min=${b.getWest().toFixed(3)}&lon_max=${b.getEast().toFixed(3)}`;
    const data = await fetch(url).then((r) => r.json());
    const src = map.getSource('interference-zones');
    if (src) src.setData(data);
  } catch {}
}

async function _loadVlfElfEmitters() {
  try {
    const data = await fetch('/api/features/vlf-elf').then((r) => r.json());
    const src = map.getSource('vlf-elf-emitters');
    if (src) src.setData(data);
  } catch {}
}

async function refreshBayesField() {
  if (!bayesToggle?.checked) return;
  try {
    const c = map.getCenter();
    const url = `/api/bayes/field?center_lat=${c.lat.toFixed(4)}&center_lon=${c.lng.toFixed(4)}`;
    const data = await fetch(url).then((r) => r.json());
    const src = map.getSource('bayes-field');
    if (src) src.setData(data);
  } catch {}
}

// Collapsible sections in fox panel
waterfallHeader?.addEventListener('click', () => {
  waterfallContainer?.classList.toggle('collapsed');
});
peakListHeader?.addEventListener('click', () => {
  peakList?.classList.toggle('collapsed');
});

// Poll fox hunt status to sync UI when SSE is unavailable
async function _refreshFoxStatus() {
  try {
    const s = await fetch('/api/foxhunt/auto/status').then((r) => r.json());
    _setFoxState(s.state || 'IDLE');
    if (s.target && foxTargetBox) {
      foxTargetBox.style.display = 'block';
      if (foxTargetFreq) foxTargetFreq.textContent = `${(s.target.freq_hz / 1e6).toFixed(3)} MHz`;
      if (foxTargetMeta) foxTargetMeta.textContent = `${s.target.band_label} · ${s.target.modulation_hint}`;
      if (foxObsCount) foxObsCount.textContent = `${s.target.bearing_obs_count} bearing(s) · ${s.target.rssi_obs_count} RSSI`;
    }
    if (_autoHuntEnabled) {
      const cycle = await fetch('/api/foxhunt/autonomous/cycle', { method: 'POST' }).then((r) => r.json()).catch(() => null);
      if (cycle?.phase && autoPolicyPhase) autoPolicyPhase.textContent = `Policy phase: ${cycle.phase}`;
    }
    const auto = await fetch('/api/foxhunt/autonomous/status').then((r) => r.json()).catch(() => null);
    if (auto?.policy) {
      _autoHuntEnabled = Boolean(auto.policy.running);
      if (autoHuntToggle) autoHuntToggle.textContent = `Auto Hunt: ${_autoHuntEnabled ? 'ON' : 'OFF'}`;
      if (autoPolicyPhase) autoPolicyPhase.textContent = `Policy phase: ${auto.policy.phase || 'IDLE'}`;
    }
  } catch {}
}
