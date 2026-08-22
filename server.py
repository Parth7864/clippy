import json
import logging
import socket
import sys
import threading
import time
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

logger = logging.getLogger(__name__)

from .clipboard import ClipboardManager
from .core import (
    FILE, add, load, delete_indices, update, toggle_favorite, clear, search, top,
    stats, count, backup, export_history, parse_range, get_favorites,
)

BASE_PATH = ""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>clippy</title>
<style>
  :root { --bg:#0f0f12; --card:#1a1a20; --text:#e6e6e6; --muted:#9a9aa0; --accent:#8ab4f8; --input:#16161a; --pill:#23232a; }
  [data-theme="light"] { --bg:#f4f4f5; --card:#ffffff; --text:#18181b; --muted:#71717a; --accent:#3b82f6; --input:#ffffff; --pill:#e4e4e7; }
  * { box-sizing:border-box; }
  html { scrollbar-gutter: stable; }
  body {
    margin:0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    background:var(--bg); color:var(--text); line-height:1.5;
    transition: background-color .35s ease, color .35s ease;
  }
  .wrap { max-width:760px; margin:0 auto; padding:28px 20px 60px; }
  .top { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
  .top h1 { font-size:17px; font-weight:600; letter-spacing:-0.02em; margin:0; }
  .theme-btn {
    background:var(--card); color:var(--muted); border:0; border-radius:999px;
    width:38px; height:38px; cursor:pointer; display:grid; place-items:center; font-size:15px;
    transition: transform .2s ease, background-color .25s ease, color .25s ease;
  }
  .theme-btn:hover { transform: rotate(15deg) scale(1.05); color:var(--text); }
  .theme-btn:active { transform: scale(0.95); }
  .stats { font-family: ui-monospace, monospace; font-size:12px; color:var(--muted); display:flex; gap:14px; flex-wrap:wrap; margin-bottom:18px; }
  .stats b { color:var(--text); font-weight:600; }
  .card { background:var(--card); border:0; border-radius:18px; padding:18px; margin-bottom:14px; transition: transform .25s ease, background-color .35s ease; }
  .card:hover { transform: translateY(-1px); }
  .card h2 { font-size:11px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:var(--muted); margin:0 0 12px; }
  textarea, input {
    background:var(--input); color:var(--text); border:0; border-radius:12px;
    padding:10px 12px; width:100%; font:13px ui-monospace, monospace;
    transition: background-color .25s ease, box-shadow .2s ease;
  }
  textarea:focus, input:focus { outline:none; box-shadow: 0 0 0 2px var(--accent); }
  textarea { min-height:84px; resize:vertical; }
  .btn {
    font-size:13px; font-weight:500; background:var(--text); color:var(--bg);
    border:0; border-radius:999px; padding:8px 16px; cursor:pointer;
    transition: opacity .2s ease, transform .2s cubic-bezier(.2,.8,.2,1), background-color .25s ease;
  }
  .btn:hover { opacity:0.9; transform: translateY(-1px); }
  .btn:active { transform: translateY(0) scale(0.98); }
  .btn.secondary { background:var(--pill); color:var(--text); }
  .btn.danger { background: transparent; color:#ef4444; }
  .btn.danger:hover { background: rgba(239,68,68,0.1); }
  .status { margin-top:10px; font:12px ui-monospace, monospace; color:var(--muted); white-space:pre-wrap; word-break:break-word; min-height:1em; transition: color .25s ease; }
  ul.list { list-style:none; padding:0; margin:0; display:grid; gap:8px; }
  li.item {
    background:var(--card); border:0; border-radius:14px; padding:12px 14px;
    display:flex; gap:10px; align-items:flex-start;
    opacity:0; animation: in .35s cubic-bezier(.2,.8,.2,1) forwards;
    transition: transform .2s ease, background-color .25s ease;
  }
  li.item:hover { transform: translateY(-1px) scale(1.005); }
  @keyframes in { from { opacity:0; transform: translateY(6px); } to { opacity:1; transform:none; } }
  li.item .num { font:11px ui-monospace, monospace; color:var(--muted); min-width:28px; text-align:right; padding-top:2px; }
  li.item .num.fav { color:#eab308; }
  li.item .body { flex:1; min-width:0; }
  li.item .txt { font:13px ui-monospace, monospace; white-space:pre-wrap; cursor:pointer; }
  li.item .meta { font:11px ui-monospace, monospace; color:var(--muted); margin-top:4px; }
  li.item .actions { display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
  li.item button {
    font:11px ui-monospace, monospace; padding:5px 10px; border-radius:999px;
    border:0; cursor:pointer; background:var(--bg); color:var(--text);
    transition: transform .15s ease, opacity .15s ease;
  }
  li.item button:hover { transform: scale(1.04); opacity:1; }
  .toolbar { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
  .toolbar input { flex:1; min-width:160px; }
  .pill { font:11px ui-monospace, monospace; background:var(--pill); color:var(--muted); border-radius:999px; padding:5px 10px; cursor:pointer; border:0; transition: all .2s ease; }
  .pill.on { background:var(--text); color:var(--bg); }
  .pill:hover { transform: scale(1.03); }
  .toast {
    position:fixed; bottom:18px; left:50%; background:var(--text); color:var(--bg);
    font:12px ui-monospace, monospace; padding:9px 16px; border-radius:999px;
    opacity:0; transform:translateX(-50%) translateY(10px) scale(0.98);
    transition: all .35s cubic-bezier(.2,.8,.2,1); pointer-events:none;
  }
  .toast.show { opacity:1; transform:translateX(-50%) translateY(0) scale(1); }
  .empty { color:var(--muted); text-align:center; padding:24px; font-size:13px; }
</style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h1>clippy</h1>
      <button class="theme-btn" id="themeBtn" title="Toggle theme" onclick="toggleTheme()">◐</button>
    </div>
    <div class="stats">
      <span><b id="st_items">–</b> items</span>
      <span><b id="st_favs">–</b> favs</span>
      <span><b id="st_copies">–</b> copies</span>
      <span><b id="st_chars">–</b> chars</span>
    </div>
    <div class="card">
      <h2>clipboard</h2>
      <input id="set_clip" placeholder="type something…">
      <div style="margin-top:10px; display:flex; gap:8px;">
        <button class="btn" onclick="setClipboard()">Set</button>
        <button class="btn secondary" onclick="copyClipboard()">Copy</button>
      </div>
      <div class="status" id="clip_status"></div>
    </div>
    <div class="card">
      <h2>add</h2>
      <textarea id="add_text" placeholder="save text…"></textarea>
      <div style="margin-top:10px; display:flex; gap:8px;">
        <button class="btn" onclick="addItem()">Save</button>
        <button class="btn danger" onclick="clearAll()">Clear all</button>
      </div>
    </div>
    <div class="card">
      <h2>history <span id="hcount" class="pill" style="margin-left:8px">0</span></h2>
      <div class="toolbar">
        <input id="q" placeholder="filter…">
        <button class="btn secondary" onclick="doSearch()">Search</button>
        <button class="btn secondary" onclick="showAll()">All</button>
        <button class="pill" id="favtoggle" onclick="toggleFavs()">★</button>
      </div>
      <ul class="list" id="history"></ul>
      <div class="empty" id="empty" style="display:none">No items yet.</div>
    </div>
  </div>
  <div class="toast" id="toast"></div>

<script>
const Q = (s) => document.getElementById(s);
const fmt = (ts) => ts ? String(ts).replace('T', ' ').slice(0,16) : '';
let favsOnly = false;

async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  if (!res.ok) throw new Error(text || res.status);
  try { return JSON.parse(text); } catch { return text; }
}
function toast(msg) {
  const t = Q('toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 1600);
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('clippy-theme', next);
  Q('themeBtn').textContent = next === 'light' ? '◑' : '◐';
}
(function(){
  const saved = localStorage.getItem('clippy-theme');
  const prefersLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
  const init = saved || (prefersLight ? 'light' : 'dark');
  if(init === 'light') document.documentElement.setAttribute('data-theme','light');
  const btn = document.getElementById('themeBtn');
  if(btn) btn.textContent = init === 'light' ? '◑' : '◐';
})();
async function refreshClip() {
  try {
    const t = await api('/api/clipboard');
    Q('clip_status').textContent = t.clipboard || '(empty)';
  } catch (e) { Q('clip_status').textContent = e; }
}
async function setClipboard() {
  const v = Q('set_clip').value;
  const r = await api('/api/clipboard', {method:'POST', body: JSON.stringify({text: v}),
                           headers:{'Content-Type':'application/json'}});
  Q('set_clip').value = '';
  Q('clip_status').textContent = r.clipboard || '(empty)';
  toast('clipboard set');
  loadHistory(); refreshStats();
}
async function copyClipboard() {
  const t = await api('/api/clipboard');
  navigator.clipboard.writeText(t.clipboard || '').then(() => toast('copied clipboard'));
}
function esc(s) { return s.replace(/[&<>"/]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','/':'&#47;'}[c])); }
function render(list) {
  const ul = Q('history');
  Q('hcount').textContent = list.length;
  Q('empty').style.display = list.length ? 'none' : 'block';
  ul.innerHTML = '';
  for (let i = 0; i < list.length; i++) {
    const it = list[i];
    const li = document.createElement('li');
    li.className = 'item';
    const lines = it.text.split('\\n');
    const first = esc(lines[0]);
    const rest = lines.slice(1).map(esc).join('<br>');
    const numClass = it.favorite ? 'num fav' : 'num';
    li.innerHTML = `
      <div class="${numClass}">★ ${it.index}</div>
      <div class="body">
        <div class="txt" title="click to copy" onclick="copyItem(${it.index})">${first}${rest ? '<br>'+rest : ''}</div>
        <div class="meta">${fmt(it.time)} · ${it.count}x copied · ${it.text.length} chars</div>
        <div class="actions">
          <button class="btn" onclick="copyItem(${it.index})">copy</button>
          <button class="btn" onclick="favItem(${it.index})">${it.favorite ? 'unfavorite' : 'favorite'}</button>
          <button class="btn danger" onclick="delItem(${it.index})">delete</button>
        </div>
      </div>`;
    ul.appendChild(li);
  }
}
async function loadData() {
  const [hist, stats] = await Promise.all([api('/api/history'), api('/api/stats')]);
  let items = hist.items;
  if (favsOnly) items = items.filter(i => i.favorite);
  render(items);
  const s = stats.stats || {};
  Q('st_items').textContent = s.total ?? 0;
  Q('st_favs').textContent = s.favorites ?? 0;
  Q('st_copies').textContent = s.total_copies ?? 0;
  Q('st_chars').textContent = (s.total_chars ?? 0).toLocaleString();
}
const loadHistory = () => api('/api/history').then(r => render(favsOnly ? r.items.filter(i=>i.favorite) : r.items));
async function doSearch() {
  const q = Q('q').value;
  if (!q) return showAll();
  const r = await api('/api/search?q=' + encodeURIComponent(q));
  render(r.items);
}
function showAll() { Q('q').value = ''; favsOnly = false; Q('favtoggle').classList.remove('on'); loadHistory(); refreshStats(); }
function toggleFavs() {
  favsOnly = !favsOnly;
  Q('favtoggle').classList.toggle('on', favsOnly);
  loadHistory();
}
async function refreshStats() {
  const s = await api('/api/stats'); const d = s.stats || {};
  Q('st_items').textContent = d.total ?? 0; Q('st_favs').textContent = d.favorites ?? 0;
  Q('st_copies').textContent = d.total_copies ?? 0; Q('st_chars').textContent = (d.total_chars ?? 0).toLocaleString();
}
async function copyItem(i) {
  await api('/api/history/' + i + '/copy', {method:'POST'});
  toast('copied item ' + i); loadHistory(); refreshClip();
}
async function favItem(i) {
  await api('/api/history/' + i + '/favorite', {method:'POST'});
  loadHistory(); refreshStats();
}
async function delItem(i) {
  await api('/api/history/' + i, {method:'DELETE'});
  toast('deleted item ' + i); loadHistory(); refreshStats();
}
async function addItem() {
  const v = Q('add_text').value;
  if (!v.trim()) return;
  await api('/api/history', {method:'POST', body: JSON.stringify({text: v}),
              headers:{'Content-Type':'application/json'}});
  Q('add_text').value = ''; toast('saved'); loadHistory(); refreshStats();
}
async function clearAll() {
  if (!confirm('Clear all history?')) return;
  await api('/api/history', {method:'DELETE'});
  toast('history cleared'); loadHistory(); refreshStats();
}
Q('q').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
Q('add_text').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) addItem(); });
Q('set_clip').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) setClipboard(); });
setInterval(() => { refreshClip(); loadHistory(); refreshStats(); }, 3000);
refreshClip(); loadData();
try { const h = location.host; ['host','host2','footHost'].forEach(id => { const el = document.getElementById(id); if(el) el.textContent = h; }); } catch(e) {}
</script>
</body>
</html>
"""

API = [
    ("GET", f"{BASE_PATH}/api/history"),
    ("GET", f"{BASE_PATH}/api/history/<index>"),
    ("POST", f"{BASE_PATH}/api/history"),
    ("PUT", f"{BASE_PATH}/api/history/<index>"),
    ("DELETE", f"{BASE_PATH}/api/history"),
    ("DELETE", f"{BASE_PATH}/api/history/<index>"),
    ("POST", f"{BASE_PATH}/api/history/<index>/favorite"),
    ("POST", f"{BASE_PATH}/api/history/<index>/copy"),
    ("GET", f"{BASE_PATH}/api/search"),
    ("GET", f"{BASE_PATH}/api/top"),
    ("GET", f"{BASE_PATH}/api/stats"),
    ("GET", f"{BASE_PATH}/api/clipboard"),
    ("POST", f"{BASE_PATH}/api/clipboard"),
    ("GET", f"{BASE_PATH}/api/favorites"),
    ("GET", f"{BASE_PATH}/api/count"),
    ("GET", f"{BASE_PATH}/api/backup"),
    ("GET", f"{BASE_PATH}/api/export"),
    ("GET", f"{BASE_PATH}/api/status"),
    ("GET", f"{BASE_PATH}/api/health"),
    ("GET", f"{BASE_PATH}/api/openapi.json"),
    ("GET", f"{BASE_PATH}/api/docs"),
]

OPENAPI = {
    "openapi": "3.0.3",
    "info": {
        "title": "clippy REST API",
        "version": "2.3",
        "description": (
            "Self-hosted clipboard history server. Run `clippy serve` and talk to it "
            "over HTTP on localhost. All responses are JSON and allow cross-origin "
            "requests, so browser widgets and CLI tools can drive it directly."
        ),
    },
    "servers": [{"url": "{scheme}{host}:{port}/api", "variables": {
        "scheme": {"default": "http://"},
        "host": {"default": "127.0.0.1"},
        "port": {"default": "8765"},
    }}],
    "paths": {
        "/history": {
            "get": {"summary": "Full history", "responses": {"200": {"description": "List of items"}}},
            "post": {"summary": "Add an item", "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Text"}}}}, "responses": {"200": {"description": "Added"}}},
            "delete": {"summary": "Clear all history", "responses": {"200": {"description": "Cleared"}}},
        },
        "/history/{index}": {
            "parameters": [{"name": "index", "in": "path", "required": True, "schema": {"type": "integer"}}],
            "get": {"summary": "Get one item", "responses": {"200": {"description": "Item"}}},
            "put": {"summary": "Update one item", "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Text"}}}}, "responses": {"200": {"description": "Updated"}}},
            "delete": {"summary": "Delete one item", "responses": {"200": {"description": "Deleted"}}},
        },
        "/history/{index}/favorite": {
            "post": {"summary": "Toggle favorite", "parameters": [{"name": "index", "in": "path", "required": True, "schema": {"type": "integer"}}], "responses": {"200": {"description": "Toggled"}}},
        },
        "/history/{index}/copy": {
            "post": {"summary": "Copy item to clipboard", "parameters": [{"name": "index", "in": "path", "required": True, "schema": {"type": "integer"}}], "responses": {"200": {"description": "Copied"}}},
        },
        "/search": {
            "get": {"summary": "Search history", "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}], "responses": {"200": {"description": "Matching items"}}},
        },
        "/top": {
            "get": {"summary": "Most-copied items", "parameters": [{"name": "n", "in": "query", "schema": {"type": "integer"}}], "responses": {"200": {"description": "Ranked items"}}},
        },
        "/stats": {"get": {"summary": "Aggregate stats", "responses": {"200": {"description": "Stats"}}}},
        "/clipboard": {
            "get": {"summary": "Read current clipboard", "responses": {"200": {"description": "Clipboard text"}}},
            "post": {"summary": "Set the clipboard", "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Text"}}}}, "responses": {"200": {"description": "New clipboard"}}},
        },
        "/favorites": {"get": {"summary": "Favorite items", "responses": {"200": {"description": "Favorites"}}}},
        "/count": {"get": {"summary": "Number of items", "responses": {"200": {"description": "Count"}}}},
        "/backup": {"get": {"summary": "Create a timestamped backup", "responses": {"200": {"description": "Backup path"}}}},
        "/export": {
            "get": {"summary": "Export history", "parameters": [{"name": "format", "in": "query", "schema": {"type": "string", "enum": ["json", "txt", "md"]}}], "responses": {"200": {"description": "Exported content"}}},
        },
        "/status": {"get": {"summary": "Server status", "responses": {"200": {"description": "Status"}}}},
        "/health": {"get": {"summary": "Liveness probe", "responses": {"200": {"description": "Healthy"}}}},
    },
    "components": {
        "schemas": {"Text": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    },
}

DOCS_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>clippy — api</title>
<style>
  :root { --bg:#0f0f12; --card:#1a1a20; --text:#e6e6e6; --muted:#9a9aa0; --accent:#8ab4f8; --pill:#23232a; }
  [data-theme="light"] { --bg:#fafaf9; --card:#ffffff; --text:#18181b; --muted:#71717a; --accent:#3b82f6; --pill:#e4e4e7; }
  * { box-sizing:border-box; }
  body { margin:0; font-family: ui-sans-serif, system-ui, sans-serif; background:var(--bg); color:var(--text); line-height:1.6; transition: background-color .35s ease, color .35s ease; }
  .wrap { max-width:860px; margin:0 auto; padding:28px 20px 80px; }
  .top { display:flex; justify-content:space-between; align-items:center; margin-bottom:18px; }
  .top h1 { font-size:17px; font-weight:600; letter-spacing:-0.02em; margin:0; }
  .theme-btn { background:var(--card); color:var(--muted); border:0; border-radius:999px; width:38px; height:38px; cursor:pointer; display:grid; place-items:center; font-size:15px; transition: transform .2s ease, background-color .25s ease; }
  .theme-btn:hover { transform: rotate(15deg) scale(1.05); color:var(--text); }
  h2 { font-size:11px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:var(--muted); margin:22px 0 10px; }
  .route { background:var(--card); border:0; border-radius:14px; padding:12px 14px; margin-bottom:8px; display:flex; gap:12px; align-items:flex-start; opacity:0; animation: in .35s cubic-bezier(.2,.8,.2,1) forwards; transition: transform .2s ease, background-color .25s ease; }
  .route:hover { transform: translateY(-1px); }
  @keyframes in { from { opacity:0; transform: translateY(6px); } to { opacity:1; transform:none; } }
  .method { font:11px ui-monospace,monospace; font-weight:700; border-radius:999px; padding:4px 8px; color:var(--bg); background:var(--text); min-width:58px; text-align:center; }
  .get { background:#22c55e; color:white; } .post { background:var(--accent); color:white; } .put { background:#eab308; color:#18181b; } .delete { background:#ef4444; color:white; }
  code.path { font:12px ui-monospace,monospace; color:var(--text); font-weight:600; }
  .desc { font:12.5px ui-sans-serif, system-ui, sans-serif; color:var(--muted); margin:3px 0 0; }
  .desc code { font-family: ui-monospace, monospace; background:var(--bg); padding:1px 5px; border-radius:6px; }
  a { color:var(--accent); }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1>clippy — api</h1>
    <button class="theme-btn" id="themeBtn2" title="Toggle theme" onclick="toggleTheme()">◐</button>
  </div>
  <h2>endpoints</h2>
  <div id="routes"></div>
</div>
<script>
const ROUTES = {
  "GET /api/history": "Full clipboard history",
  "GET /api/history/{index}": "Fetch a single item by index",
  "POST /api/history": "Add an item  — body <code>{\"text\": \"...\"}</code>",
  "PUT /api/history/{index}": "Update an item — body <code>{\"text\": \"...\"}</code>",
  "DELETE /api/history": "Clear all history",
  "DELETE /api/history/{index}": "Delete one item",
  "POST /api/history/{index}/favorite": "Toggle an item's favorite flag",
  "POST /api/history/{index}/copy": "Copy an item's text to the clipboard",
  "GET /api/search?q=...": "Search history",
  "GET /api/top?n=10": "Most-copied items",
  "GET /api/stats": "Aggregate statistics",
  "GET /api/favorites": "Favorite items",
  "GET /api/count": "Total number of saved items",
  "GET /api/clipboard": "Read the current clipboard",
  "POST /api/clipboard": "Set the clipboard — body <code>{\"text\": \"...\"}</code>",
  "GET /api/backup": "Create a timestamped backup of the data file",
  "GET /api/export?format=json|txt|md": "Export history as json, txt, or markdown",
  "GET /api/status": "Server status, version, item count, data path",
  "GET /api/health": "Liveness probe — returns <code>{\"status\":\"ok\"}</code>",
};

const m = document.getElementById('routes');
const methodColor = {GET:'get', POST:'post', PUT:'put', DELETE:'delete'};
let idx=0;
for (const [route, desc] of Object.entries(ROUTES)) {
  const [method, path] = route.match(/^(\\S+)\\s+(.*)$/).slice(1);
  const el = document.createElement('div');
  el.className = 'route';
  el.style.animationDelay = (idx++ * 0.03)+'s';
  el.innerHTML = '<span class="method ' + methodColor[method] + '">' + method + '</span>' +
                 '<div><code class="path">' + path + '</code><p class="desc">' + desc + '</p></div>';
  m.appendChild(el);
}
function toggleTheme(){
  const cur=document.documentElement.getAttribute('data-theme');
  const next=cur==='light'?'dark':'light';
  if(next==='light') document.documentElement.setAttribute('data-theme','light');
  else document.documentElement.removeAttribute('data-theme');
  localStorage.setItem('clippy-theme',next);
  const b=document.getElementById('themeBtn2'); if(b) b.textContent = next==='light'?'◑':'◐';
}
(function(){
  const saved=localStorage.getItem('clippy-theme');
  const prefersLight=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches;
  const init=saved||(prefersLight?'light':'dark');
  if(init==='light') document.documentElement.setAttribute('data-theme','light');
  const b=document.getElementById('themeBtn2'); if(b) b.textContent = init==='light'?'◑':'◐';
})();
</script>
</body>
</html>
"""


def _send_json(handler, obj, status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(json.dumps(obj).encode())))
    handler.end_headers()
    handler.wfile.write(json.dumps(obj).encode())


def _send_text(handler, text, status=200, ctype="text/plain; charset=utf-8"):
    body = text.encode()
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler):
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        warnings.warn("clippy server: invalid Content-Length header", UserWarning)
        length = 0
    if length <= 0:
        return {}
    if length > 1_000_000:
        warnings.warn(f"clippy server: large request body {length} bytes — may be abusive", UserWarning)
        _send_json(handler, {"error": "payload too large (max 1MB)"}, 413)
        return {}
    try:
        raw = handler.rfile.read(length).decode("utf-8", errors="ignore")
    except Exception as e:
        warnings.warn(f"clippy server: failed to read body: {e}", RuntimeWarning)
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        if len(raw) > 500_000:
            warnings.warn(f"clippy server: raw body very large ({len(raw)} chars)", UserWarning)
        return {"text": raw}


def _index(params):
    try:
        return int(params.get("index", [""])[0])
    except (ValueError, IndexError):
        return -1


class ClippyRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _route(self):
        parts = urlparse(self.path)
        path = parts.path
        query = parse_qs(parts.query)
        method = self.command

        if path in (BASE_PATH, BASE_PATH + "/", BASE_PATH + "/index.html") and method == "GET":
            _send_text(self, PAGE, ctype="text/html; charset=utf-8")
            return True

        match = None
        for route in API:
            rmethod, rpath = route
            if rmethod != method:
                continue
            if "<index>" in rpath:
                prefix, p = rpath.split("<index>", 1)
                if path.startswith(prefix) and path.endswith(p):
                    idx = path[len(prefix):-len(p)] if p else path[len(prefix):]
                    match = (rpath, idx)
                    break
            elif rpath == path:
                match = (rpath, "")
                break

        if not match:
            _send_json(self, {"error": "not found", "path": path}, 404)
            return True
        rpath, raw_index = match
        params = dict(query)
        if raw_index:
            params["index"] = [raw_index]
        return self._handle(rpath, method, params)

    def _handle(self, rpath, method, params):
        try:
            return self._dispatch(rpath, method, params)
        except Exception as e:
            warnings.warn(f"clippy server: handler for {rpath} {method} crashed: {e}", RuntimeWarning)
            logger.error(f"dispatch failed {rpath} {method}: {e}", exc_info=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            try:
                _send_json(self, {"error": str(e), "hint": "run `clippy doctor` for diagnostics"}, 500)
            except Exception:
                pass
        return True

    def _dispatch(self, rpath, method, params):
        manager = self.server.clipboard

        if rpath == f"{BASE_PATH}/api/history":
            if method == "GET":
                _send_json(self, {"items": _history_payload(load())})
            elif method == "POST":
                body = _read_body(self)
                text = (body.get("text") or "").strip()
                if not text:
                    _send_json(self, {"error": "text required"}, 400)
                else:
                    add(text)
                    _send_json(self, {"added": True, "text": text})
            elif method == "DELETE":
                clear()
                _send_json(self, {"cleared": True})
            return True

        if rpath == f"{BASE_PATH}/api/history/<index>":
            i = _index(params)
            items = load()
            if i < 0 or i >= len(items):
                _send_json(self, {"error": "out of range"}, 404)
                return True
            if method == "GET":
                _send_json(self, {"index": i, "item": items[i]})
            elif method == "PUT":
                body = _read_body(self)
                text = (body.get("text") or "").strip()
                if not text:
                    _send_json(self, {"error": "text required"}, 400)
                else:
                    update(i, text)
                    _send_json(self, {"updated": True, "index": i, "text": text})
            elif method == "DELETE":
                delete_indices([i])
                _send_json(self, {"deleted": True, "index": i})
            return True

        if rpath == f"{BASE_PATH}/api/history/<index>/favorite":
            i = _index(params)
            items = load()
            if i < 0 or i >= len(items):
                _send_json(self, {"error": "out of range"}, 404)
                return True
            toggle_favorite(i)
            _send_json(self, {"index": i,
                              "favorite": load()[i]["favorite"] if i < len(load()) else False})
            return True

        if rpath == f"{BASE_PATH}/api/history/<index>/copy":
            i = _index(params)
            items = load()
            if i < 0 or i >= len(items):
                _send_json(self, {"error": "out of range"}, 404)
                return True
            text = items[i]["text"]
            manager.set(text)
            _send_json(self, {"copied": True, "index": i, "clipboard": text})
            return True

        if rpath == f"{BASE_PATH}/api/search":
            q = (params.get("q", [""])[0] or "").lower()
            hits = [{"index": i, **item} for i, item in search(q)]
            _send_json(self, {"q": q, "count": len(hits), "items": hits})
            return True

        if rpath == f"{BASE_PATH}/api/top":
            try:
                n = int(params.get("n", [""])[0] or 10)
            except ValueError:
                n = 10
            _send_json(self, {"items": top(n)})
            return True

        if rpath == f"{BASE_PATH}/api/stats":
            _send_json(self, {"stats": stats()})
            return True

        if rpath == f"{BASE_PATH}/api/favorites":
            favs = get_favorites()
            items = load()
            _send_json(self, {"items": [{"index": i, **items[i]} for i in favs]})
            return True

        if rpath == f"{BASE_PATH}/api/count":
            _send_json(self, {"count": count()})
            return True

        if rpath == f"{BASE_PATH}/api/backup":
            path = backup()
            _send_json(self, {"backup": path})
            return True

        if rpath == f"{BASE_PATH}/api/export":
            fmt = (params.get("format", [""])[0] or "json").lower()
            if fmt not in ("json", "txt", "md", "markdown"):
                _send_json(self, {"error": "format must be json, txt or md"}, 400)
            else:
                ext, content = export_history(fmt)
                _send_json(self, {"format": ext, "content": content})
            return True

        if rpath == f"{BASE_PATH}/api/clipboard":
            if method == "GET":
                _send_json(self, {"clipboard": manager.get()})
            elif method == "POST":
                body = _read_body(self)
                text = body.get("text") if isinstance(body, dict) else body
                manager.set(text or "")
                _send_json(self, {"clipboard": manager.get()})
            return True

        if rpath == f"{BASE_PATH}/api/status":
            s = stats()
            _send_json(self, {
                "status": "ok",
                "version": self.server.version,
                "items": s.get("total", 0),
                "clipboard": manager.get(),
                "data": self.server.data_file,
            })
            return True

        if rpath == f"{BASE_PATH}/api/health":
            _send_json(self, {"status": "ok", "version": self.server.version})
            return True

        if rpath == f"{BASE_PATH}/api/openapi.json":
            _send_json(self, OPENAPI)
            return True

        if rpath == f"{BASE_PATH}/api/docs":
            _send_text(self, DOCS_PAGE, ctype="text/html; charset=utf-8")
            return True

        _send_json(self, {"error": "unhandled route"}, 500)
        return True

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def do_PUT(self):
        self._route()

    def do_DELETE(self):
        self._route()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _history_payload(items):
    return [{"index": i, **item} for i, item in enumerate(items)]


def find_free_port(preferred):
    if preferred:
        if not isinstance(preferred, int) or not (1 <= preferred <= 65535):
            warnings.warn(f"clippy: invalid preferred port {preferred!r} — using free port", UserWarning)
        elif preferred < 1024:
            warnings.warn(f"clippy: port {preferred} is privileged (<1024) — may need sudo", UserWarning)
        return preferred
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    except OSError as e:
        warnings.warn(f"clippy: cannot find free port: {e}", RuntimeWarning)
        raise
    finally:
        s.close()
    return port


class ClippyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, data_file, version):
        super().__init__(addr, handler)
        self.clipboard = ClipboardManager()
        self.data_file = data_file
        self.version = version


def serve(host="127.0.0.1", port=None, version="2.3"):
    port = find_free_port(port)
    try:
        server = ClippyServer((host, port), ClippyRequestHandler, FILE, version)
    except OSError as e:
        warnings.warn(f"clippy: cannot bind {host}:{port}: {e}", RuntimeWarning)
        if "already in use" in str(e).lower():
            print(f"clippy: port {port} already in use — try --port 0 or `lsof -i :{port}` / `netstat -tulpn`", file=sys.stderr)
        raise
    if host not in ("127.0.0.1", "localhost"):
        warnings.warn(f"clippy: serve on {host} exposes clipboard to network — only use on trusted networks", UserWarning)
        print(f"clippy: WARNING — serving on {host} exposes to network!", file=sys.stderr)
    print(f"clippy: serving on http://{host}:{port}  (Ctrl+C to stop)")
    print(f"clippy: web page    http://{host}:{port}/")
    print(f"clippy: API docs    http://{host}:{port}/api/docs")
    print(f"clippy: API spec    http://{host}:{port}/api/openapi.json")
    print(f"clippy: data file   {server.data_file}")
    print(f"clippy: try `clippy doctor` if anything looks wrong")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nclippy: server stopped.")
    finally:
        server.server_close()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="clippy serve", description="Run the clippy HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="port (default: a free port)")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
