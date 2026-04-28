"""WebUI server — configure presets and control the display from a browser.

Runs as a daemon thread alongside the main tkinter application.

Routes
------
GET  /                          Single-page HTML UI
GET  /api/status                Current app state (layout, feeds, uptime, MQTT)
GET  /api/presets               All presets from config.yaml (raw, pre-interpolation)
PUT  /api/presets/<name>        Create or update a preset  { layout, feeds: [...] }
DELETE /api/presets/<name>      Delete a preset
POST /api/command               Send any command to the app  { action, ... }
"""

import json
import logging
import os
import threading

import yaml

logger = logging.getLogger(__name__)

# Slot counts per layout name — must match LAYOUTS in app.py
SLOT_COUNTS = {"1x1": 1, "2x2": 4}

# ---------------------------------------------------------------------------
# Single-page HTML UI (embedded to avoid a separate templates directory)
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RTSP Display &mdash; Setup</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0a0a0a;
  --panel: #141414;
  --border: #2a2a2a;
  --accent: #00d4ff;
  --text: #e0e0e0;
  --muted: #666;
  --success: #00c851;
  --error: #ff4444;
  --warn: #ffaa00;
  --hover: #1c1c1c;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ---- Header ---- */
header {
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  padding: 10px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

header h1 {
  font-size: 15px;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 12px;
  background: #1a1a1a;
  border: 1px solid var(--border);
  font-size: 12px;
  white-space: nowrap;
}

.dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--muted);
  flex-shrink: 0;
}
.dot.playing  { background: var(--success); box-shadow: 0 0 5px var(--success); }
.dot.idle     { background: var(--accent); }
.dot.ok       { background: var(--success); }
.dot.err      { background: var(--error); }

.header-right { margin-left: auto; display: flex; gap: 10px; align-items: center; }

/* ---- Main layout ---- */
.main {
  display: grid;
  grid-template-columns: 270px 1fr;
  flex: 1;
  overflow: hidden;
}

/* ---- Sidebar ---- */
.sidebar {
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.section { border-bottom: 1px solid var(--border); }

.section-hdr {
  padding: 8px 14px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--muted);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* Status info grid */
.status-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 10px 14px;
}

.info-item { display: flex; flex-direction: column; gap: 2px; }
.info-lbl  { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
.info-val  { font-size: 13px; font-weight: 500; }

.feed-status-list { padding: 0 14px 10px; }
.feed-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  font-size: 12px;
}
.feed-dot {
  width: 6px; height: 6px; border-radius: 50%;
}
.feed-dot.playing    { background: var(--success); }
.feed-dot.stalled    { background: var(--warn); }
.feed-dot.restarting { background: var(--warn); }
.feed-dot.starting   { background: var(--accent); }
.feed-dot.stopped,
.feed-dot.error      { background: var(--muted); }

/* Presets list */
.preset-list {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #333 transparent;
}

.preset-item {
  display: flex;
  align-items: center;
  padding: 9px 14px;
  cursor: pointer;
  border-bottom: 1px solid #181818;
  transition: background 0.1s;
  gap: 8px;
}
.preset-item:hover  { background: var(--hover); }
.preset-item.active { background: #0b1d23; border-left: 2px solid var(--accent); }

.preset-name   { flex: 1; font-weight: 500; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preset-layout { font-size: 10px; color: var(--muted); background: #222; padding: 2px 6px; border-radius: 4px; flex-shrink: 0; }

.btn-icon {
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  padding: 3px 5px;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1;
  transition: color 0.1s, background 0.1s;
  flex-shrink: 0;
}
.btn-icon:hover        { color: var(--text); background: #2a2a2a; }
.btn-icon.danger:hover { color: var(--error); }

/* Live controls */
.live-ctrl { padding: 10px 14px; display: flex; flex-direction: column; gap: 6px; }

/* ---- Editor ---- */
.editor {
  padding: 28px 32px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #333 transparent;
}

.editor-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 10px;
  color: var(--muted);
  text-align: center;
}

.editor-title { font-size: 17px; font-weight: 600; margin-bottom: 22px; }

/* Form */
.form-group { margin-bottom: 18px; }

label {
  display: block;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

input[type="text"] {
  width: 100%;
  background: #181818;
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}
input[type="text"]:focus { border-color: var(--accent); }
input[type="text"]::placeholder { color: #444; }

/* Layout picker */
.layout-options { display: flex; gap: 10px; }

.layout-opt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  padding: 10px 18px;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  user-select: none;
}
.layout-opt:hover    { border-color: #444; background: var(--hover); }
.layout-opt.selected { border-color: var(--accent); background: #0b1d23; }

.layout-icon { display: grid; gap: 3px; }
.layout-icon.l1x1 { grid-template-columns: 1fr; }
.layout-icon.l2x2 { grid-template-columns: 1fr 1fr; }

.layout-cell {
  width: 22px; height: 15px;
  background: var(--border);
  border-radius: 2px;
}
.layout-opt.selected .layout-cell { background: var(--accent); opacity: 0.55; }
.layout-lbl { font-size: 12px; color: var(--muted); }

/* Slot URL grid */
.slot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.slot-grid.single { grid-template-columns: 1fr; }

.slot-lbl-row { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }
.slot-num {
  width: 18px; height: 18px;
  border-radius: 3px;
  background: #242424;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700; color: var(--muted);
  flex-shrink: 0;
}
.slot-pos { font-size: 11px; color: var(--muted); }

/* Buttons */
.btn {
  padding: 8px 16px;
  border-radius: 6px;
  border: none;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
  font-family: inherit;
  white-space: nowrap;
}
.btn:hover  { opacity: 0.82; }
.btn:active { opacity: 0.65; }

.btn-primary   { background: var(--accent);   color: #000; }
.btn-secondary { background: #282828;          color: var(--text); }
.btn-success   { background: var(--success);  color: #000; }
.btn-danger    { background: var(--error);    color: #fff; }
.btn-sm        { padding: 6px 12px; font-size: 12px; }
.btn-full      { width: 100%; }

.actions { display: flex; gap: 10px; margin-top: 24px; flex-wrap: wrap; align-items: center; }

hr.div { border: none; border-top: 1px solid var(--border); margin: 20px 0; }

/* Toast */
.toast {
  position: fixed;
  bottom: 20px; right: 20px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 9px 16px;
  font-size: 13px;
  z-index: 999;
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 0.25s, transform 0.25s;
  pointer-events: none;
}
.toast.show           { opacity: 1; transform: translateY(0); }
.toast.success        { border-color: var(--success); color: var(--success); }
.toast.error          { border-color: var(--error);   color: var(--error); }
</style>
</head>
<body>

<header>
  <h1>RTSP Display</h1>
  <div class="badge"><div class="dot" id="state-dot"></div><span id="state-text">...</span></div>
  <div class="badge"><div class="dot" id="mqtt-dot"></div><span id="mqtt-text">MQTT</span></div>
  <div class="header-right">
    <span style="color:var(--muted);font-size:12px" id="layout-badge"></span>
  </div>
</header>

<div class="main">

  <!-- Sidebar -->
  <aside class="sidebar">

    <div class="section">
      <div class="section-hdr">Status</div>
      <div class="status-grid">
        <div class="info-item"><span class="info-lbl">State</span><span class="info-val" id="inf-state">--</span></div>
        <div class="info-item"><span class="info-lbl">Layout</span><span class="info-val" id="inf-layout">--</span></div>
        <div class="info-item"><span class="info-lbl">Uptime</span><span class="info-val" id="inf-uptime">--</span></div>
        <div class="info-item"><span class="info-lbl">Device</span><span class="info-val" id="inf-device" style="font-size:11px">--</span></div>
      </div>
      <div class="feed-status-list" id="feed-status-list"></div>
    </div>

    <div class="section" style="flex:1;overflow:hidden;display:flex;flex-direction:column">
      <div class="section-hdr">
        Presets
        <button class="btn-icon" onclick="newPreset()" title="New preset">&#xFF0B;</button>
      </div>
      <div class="preset-list" id="preset-list"></div>
    </div>

    <div class="section">
      <div class="section-hdr">Quick Controls</div>
      <div class="live-ctrl">
        <button class="btn btn-secondary btn-sm btn-full" onclick="sendCommand({action:'clear'})">
          &#9646; Clear &mdash; return to idle
        </button>
        <button class="btn btn-secondary btn-sm btn-full" onclick="sendCommand({action:'ping'})">
          &#10003; Ping
        </button>
      </div>
    </div>

  </aside>

  <!-- Editor -->
  <main class="editor">

    <div class="editor-placeholder" id="editor-ph">
      <div style="font-size:40px;opacity:0.3">&#9707;</div>
      <div style="font-size:15px;font-weight:600;color:var(--text)">Select a preset to edit</div>
      <div>or click <strong>+</strong> to create a new one</div>
    </div>

    <div id="editor-form" style="display:none">

      <div class="editor-title" id="editor-title">Edit Preset</div>

      <div class="form-group">
        <label>Preset Name</label>
        <input type="text" id="f-name" placeholder="e.g. front_cameras" autocomplete="off" />
      </div>

      <div class="form-group">
        <label>Layout</label>
        <div class="layout-options">
          <div class="layout-opt selected" id="lo-1x1" onclick="selectLayout('1x1')">
            <div class="layout-icon l1x1"><div class="layout-cell"></div></div>
            <span class="layout-lbl">1&times;1</span>
          </div>
          <div class="layout-opt" id="lo-2x2" onclick="selectLayout('2x2')">
            <div class="layout-icon l2x2">
              <div class="layout-cell"></div><div class="layout-cell"></div>
              <div class="layout-cell"></div><div class="layout-cell"></div>
            </div>
            <span class="layout-lbl">2&times;2</span>
          </div>
        </div>
      </div>

      <div class="form-group">
        <label>Feed URLs</label>
        <div id="slot-inputs" class="slot-grid single"></div>
      </div>

      <hr class="div">

      <div class="actions">
        <button class="btn btn-primary"   onclick="savePreset()">Save</button>
        <button class="btn btn-success"   onclick="saveAndActivate()">Save &amp; Activate</button>
        <button class="btn btn-secondary" onclick="activateByName()">Activate</button>
        <button class="btn btn-danger"    id="delete-btn" onclick="deletePreset()" style="margin-left:auto;display:none">Delete</button>
      </div>

    </div>

  </main>
</div>

<div class="toast" id="toast"></div>

<script>
'use strict';

const SLOT_LABELS = {
  '1x1': ['Camera'],
  '2x2': ['Top-Left', 'Top-Right', 'Bottom-Left', 'Bottom-Right'],
};
const SLOT_COUNTS = { '1x1': 1, '2x2': 4 };

let presets = {};
let currentPreset = null;   // name string while editing existing, null while creating
let selectedLayout = '1x1';

// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------

async function pollStatus() {
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    if (s.error) {
      showApiError('Status error: ' + s.error);
    } else {
      renderStatus(s);
    }
  } catch (e) {
    showApiError('API unreachable');
  }
}

function showApiError(msg) {
  document.getElementById('state-dot').className = 'dot err';
  document.getElementById('state-text').textContent = 'error';
  document.getElementById('mqtt-dot').className = 'dot err';
  document.getElementById('mqtt-text').textContent = msg;
}

function renderStatus(s) {
  const state = s.state || 'unknown';

  // Header
  const sd = document.getElementById('state-dot');
  sd.className = 'dot ' + (state === 'playing' ? 'playing' : state === 'idle' ? 'idle' : '');
  document.getElementById('state-text').textContent = state;
  document.getElementById('layout-badge').textContent = s.layout ? s.layout.toUpperCase() : '';

  const md = document.getElementById('mqtt-dot');
  const mt = document.getElementById('mqtt-text');
  md.className = 'dot ' + (s.mqtt_connected ? 'ok' : 'err');
  mt.textContent = s.mqtt_connected ? 'MQTT connected' : 'MQTT offline';

  // Sidebar info
  document.getElementById('inf-state').textContent = state;
  document.getElementById('inf-layout').textContent = s.layout || '--';
  document.getElementById('inf-device').textContent = s.device_id || '--';

  if (typeof s.uptime_s === 'number') {
    const h = Math.floor(s.uptime_s / 3600);
    const m = Math.floor((s.uptime_s % 3600) / 60);
    const sc = s.uptime_s % 60;
    document.getElementById('inf-uptime').textContent =
      h > 0 ? h + 'h ' + m + 'm' : m > 0 ? m + 'm ' + sc + 's' : sc + 's';
  }

  const fl = document.getElementById('feed-status-list');
  if (s.feeds && s.feeds.length) {
    fl.innerHTML = s.feeds.map(f =>
      '<div class="feed-row">' +
        '<div class="feed-dot ' + f.status + '"></div>' +
        '<span>Slot ' + f.slot + '</span>' +
        '<span style="margin-left:auto;color:var(--muted)">' + f.status + '</span>' +
      '</div>'
    ).join('');
  } else {
    fl.innerHTML = '<div style="font-size:12px;color:var(--muted)">No active feeds</div>';
  }
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

async function loadPresets() {
  try {
    const r = await fetch('/api/presets');
    presets = await r.json();
    renderPresetList();
  } catch (_) {
    showToast('Could not load presets', 'error');
  }
}

function renderPresetList() {
  const el = document.getElementById('preset-list');
  const names = Object.keys(presets);
  if (!names.length) {
    el.innerHTML = '<div style="padding:14px;font-size:12px;color:var(--muted)">No presets yet &mdash; click + to add one.</div>';
    return;
  }
  el.innerHTML = names.map(name => {
    const p = presets[name];
    const active = currentPreset === name ? 'active' : '';
    return (
      '<div class="preset-item ' + active + '" onclick="editPreset(\'' + esc(name) + '\')">' +
        '<span class="preset-name">' + esc(name) + '</span>' +
        '<span class="preset-layout">' + (p.layout || '?') + '</span>' +
        '<button class="btn-icon" onclick="event.stopPropagation();activatePreset(\'' + esc(name) + '\')" title="Activate now">&#9654;</button>' +
      '</div>'
    );
  }).join('');
}

function editPreset(name) {
  currentPreset = name;
  const p = presets[name];

  showForm('Edit Preset', true);
  document.getElementById('f-name').value = name;

  const layout = p.layout || '1x1';
  selectedLayout = layout;
  updateLayoutUI();
  renderSlotInputs();

  const feeds = p.feeds || [];
  document.querySelectorAll('.slot-url').forEach((inp, i) => {
    inp.value = feeds[i] || '';
  });

  renderPresetList();
}

function newPreset() {
  currentPreset = null;
  showForm('New Preset', false);
  document.getElementById('f-name').value = '';
  selectedLayout = '1x1';
  updateLayoutUI();
  renderSlotInputs();
  renderPresetList();
}

function showForm(title, showDelete) {
  document.getElementById('editor-ph').style.display = 'none';
  document.getElementById('editor-form').style.display = 'block';
  document.getElementById('editor-title').textContent = title;
  document.getElementById('delete-btn').style.display = showDelete ? '' : 'none';
}

function selectLayout(layout) {
  selectedLayout = layout;
  updateLayoutUI();

  // Preserve existing URL values across the re-render
  const existing = Array.from(document.querySelectorAll('.slot-url')).map(i => i.value);
  renderSlotInputs();
  document.querySelectorAll('.slot-url').forEach((inp, i) => {
    inp.value = existing[i] || '';
  });
}

function updateLayoutUI() {
  ['1x1', '2x2'].forEach(l => {
    document.getElementById('lo-' + l).classList.toggle('selected', l === selectedLayout);
  });
}

function renderSlotInputs() {
  const count = SLOT_COUNTS[selectedLayout] || 1;
  const labels = SLOT_LABELS[selectedLayout] || [];
  const container = document.getElementById('slot-inputs');
  container.className = 'slot-grid' + (count === 1 ? ' single' : '');
  container.innerHTML = Array.from({length: count}, (_, i) =>
    '<div>' +
      '<div class="slot-lbl-row">' +
        '<div class="slot-num">' + i + '</div>' +
        '<span class="slot-pos">' + (labels[i] || 'Slot ' + i) + '</span>' +
      '</div>' +
      '<input type="text" class="slot-url" placeholder="rtsp://..." autocomplete="off" />' +
    '</div>'
  ).join('');
}

function formData() {
  const name = document.getElementById('f-name').value.trim();
  const feeds = Array.from(document.querySelectorAll('.slot-url')).map(i => i.value.trim());
  return { name, layout: selectedLayout, feeds };
}

async function savePreset() {
  const { name, layout, feeds } = formData();
  if (!name) { showToast('Preset name is required', 'error'); return false; }

  try {
    const r = await fetch('/api/presets/' + encodeURIComponent(name), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ layout, feeds }),
    });
    if (!r.ok) throw new Error(r.statusText);
    presets[name] = { layout, feeds };
    currentPreset = name;
    document.getElementById('delete-btn').style.display = '';
    document.getElementById('editor-title').textContent = 'Edit Preset';
    renderPresetList();
    showToast('Preset "' + name + '" saved', 'success');
    return true;
  } catch (e) {
    showToast('Save failed: ' + e.message, 'error');
    return false;
  }
}

async function saveAndActivate() {
  const ok = await savePreset();
  if (ok) await activatePreset(document.getElementById('f-name').value.trim());
}

async function activateByName() {
  const { name } = formData();
  if (!name) { showToast('Preset name is required', 'error'); return; }
  await activatePreset(name);
}

async function activatePreset(name) {
  await sendCommand({ action: 'show_preset', name });
}

async function deletePreset() {
  const name = currentPreset;
  if (!name) return;
  if (!confirm('Delete preset "' + name + '"?')) return;

  try {
    await fetch('/api/presets/' + encodeURIComponent(name), { method: 'DELETE' });
    delete presets[name];
    currentPreset = null;
    document.getElementById('editor-form').style.display = 'none';
    document.getElementById('editor-ph').style.display = 'flex';
    renderPresetList();
    showToast('Preset deleted', 'success');
  } catch (e) {
    showToast('Delete failed', 'error');
  }
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function sendCommand(payload) {
  try {
    const r = await fetch('/api/command', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(r.statusText);
    showToast('Command sent: ' + payload.action, 'success');
  } catch (e) {
    showToast('Command failed: ' + e.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

let _toastTimer;
function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (type || '');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { t.className = 'toast'; }, 3000);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

renderSlotInputs();
loadPresets();
pollStatus();
setInterval(pollStatus,  3000);
setInterval(loadPresets, 15000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# WebServer class
# ---------------------------------------------------------------------------


class WebServer:
    """Lightweight Flask web server running in a background daemon thread."""

    def __init__(self, config_path: str, command_handler, status_getter) -> None:
        """
        Args:
            config_path:     Absolute path to config.yaml (read/written for preset edits).
            command_handler: Callable accepting a dict payload; routes to the app's
                             command pipeline (thread-safe — queues to tkinter main thread).
            status_getter:   Callable returning a dict with current app state.
        """
        self._config_path = os.path.abspath(config_path)
        self._command_handler = command_handler
        self._status_getter = status_getter
        self._write_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Start the Flask server in a daemon thread (returns immediately)."""
        try:
            from flask import Flask, jsonify, request as flask_request
        except ImportError:
            logger.error(
                "Flask is not installed — WebUI disabled. "
                "Install with: pip install flask"
            )
            return

        app = Flask(__name__)

        # Silence Flask's request logs — the main app already has its own logger
        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.WARNING)

        @app.route("/")
        def index():
            return _HTML, 200, {
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": "no-store",
            }

        @app.route("/api/status")
        def api_status():
            try:
                data = self._status_getter()
                logger.debug("/api/status → %s", data.get("state"))
                return jsonify(data)
            except Exception as exc:
                logger.exception("Error in /api/status: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/presets", methods=["GET"])
        def api_presets_get():
            try:
                cfg = self._read_config()
                return jsonify(cfg.get("presets") or {})
            except Exception as exc:
                logger.exception("Error in /api/presets: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/presets/<name>", methods=["PUT"])
        def api_preset_put(name):
            data = flask_request.get_json(force=True, silent=True) or {}
            with self._write_lock:
                cfg = self._read_config()
                if not cfg.get("presets"):
                    cfg["presets"] = {}
                cfg["presets"][name] = {
                    "layout": data.get("layout", "1x1"),
                    "feeds": data.get("feeds", []),
                }
                self._write_config(cfg)
            return jsonify({"ok": True})

        @app.route("/api/presets/<name>", methods=["DELETE"])
        def api_preset_delete(name):
            with self._write_lock:
                cfg = self._read_config()
                presets = cfg.get("presets") or {}
                presets.pop(name, None)
                cfg["presets"] = presets
                self._write_config(cfg)
            return jsonify({"ok": True})

        @app.route("/api/command", methods=["POST"])
        def api_command():
            payload = flask_request.get_json(force=True, silent=True) or {}
            self._command_handler(payload)
            return jsonify({"ok": True})

        def _run():
            try:
                app.run(host=host, port=port, use_reloader=False, threaded=True)
            except Exception as exc:
                logger.exception("Flask server failed to start: %s", exc)

        thread = threading.Thread(target=_run, daemon=True, name="web-server")
        thread.start()
        logger.info("WebUI starting on http://%s:%d", host, port)

    # ------------------------------------------------------------------
    # Config I/O (raw YAML — preserves ${VAR} references)
    # ------------------------------------------------------------------

    def _read_config(self) -> dict:
        if os.path.exists(self._config_path):
            with open(self._config_path, "r") as fh:
                return yaml.safe_load(fh) or {}
        return {}

    def _write_config(self, cfg: dict) -> None:
        with open(self._config_path, "w") as fh:
            yaml.safe_dump(
                cfg,
                fh,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        logger.debug("Config written to %s", self._config_path)
