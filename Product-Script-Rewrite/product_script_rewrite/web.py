from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from opc_shared.global_ai import runtime_override_active, set_runtime_overrides
from opc_shared.vault_snapshot import cached_or_empty, refresh_snapshot

from product_script_rewrite import core


HOST = "127.0.0.1"
DEFAULT_PORT = 9997


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, status: int, value: str, content_type: str) -> None:
    body = value.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def request_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    size = int(handler.headers.get("Content-Length", "0") or "0")
    if not size:
        return {}
    data = json.loads(handler.rfile.read(size).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON object")
    return data


def safe_path(value: str, config: dict[str, Any] | None = None) -> Path:
    config = config or core.load_config()
    path = Path(value).expanduser().resolve()
    roots = [core.ROOT.resolve(), core.hot_scripts_root(config), core.product_info_root(config)]
    for root in roots:
        try:
            path.relative_to(root)
            return path
        except ValueError:
            continue
    raise ValueError("路径不在产品脚本改写智能体允许的目录内")


def state_payload(refresh: bool = False) -> dict[str, Any]:
    config = core.load_config()
    products = (
        refresh_snapshot("product-script-rewrite", "products", lambda: {"items": core.list_products(config)})
        if refresh
        else cached_or_empty("product-script-rewrite", "products", lambda: {"items": []})
    )
    return {
        "model": {
            "deepseek_base_url": config.get("deepseek_base_url", ""),
            "deepseek_model": config.get("deepseek_model", ""),
        },
        "paths": {
            "hot_scripts_root": core.hot_scripts_root(config).as_posix(),
            "product_info_root": core.product_info_root(config).as_posix(),
        },
        "products": products.get("items") or [],
        "has_api_key": bool(core.get_api_key(config)),
        "ai_settings_source": "本 Agent 临时覆盖" if runtime_override_active("text") else "8888 全局设置",
    }


def cached_scripts(product: str, refresh: bool = False) -> list[dict[str, Any]]:
    config = core.load_config()
    key = hashlib.sha256(product.encode("utf-8")).hexdigest()[:16]
    payload = (
        refresh_snapshot("product-script-rewrite-scripts", key, lambda: {"items": core.list_scripts(config, product)})
        if refresh
        else cached_or_empty("product-script-rewrite-scripts", key, lambda: {"items": []})
    )
    return payload.get("items") or []


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    base_url = str(payload.get("deepseek_base_url") or "").strip()
    model_name = str(payload.get("deepseek_model") or "").strip()
    api_key = str(payload.get("deepseek_api_key") or "").strip()
    set_runtime_overrides(
        "text",
        {"base_url": base_url, "model": model_name, "api_key": api_key},
    )
    return state_payload()


def output_items(target_product: str, source_path: str = "") -> dict[str, Any]:
    config = core.load_config()
    target = core.validate_product_name(config, target_product)
    folder = core.hot_scripts_root(config) / target
    if not source_path:
        return {"root": folder.as_posix(), "status": "unselected", "outputs": []}
    canonical = core.output_path_for(config, source_path, target)
    matches = core.matching_rewrite_outputs(config, source_path, target)
    items: list[dict[str, Any]] = []
    for path in matches:
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "path": path.as_posix(),
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                "size": stat.st_size,
            }
        )
    status = "missing" if not items else "existing" if len(items) == 1 else "duplicate"
    return {
        "root": folder.as_posix(),
        "status": status,
        "canonical_name": canonical.name,
        "outputs": items,
    }


def open_local_path(value: str) -> dict[str, str]:
    path = safe_path(value)
    if not path.exists():
        raise ValueError("文件或目录不存在")
    subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"path": path.as_posix()}


class RewriteJob:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = False
        self.status = "idle"
        self.logs: list[str] = []
        self.error = ""
        self.output: dict[str, str] | None = None
        self.started_at = 0.0
        self.finished_at = 0.0

    def append(self, message: str) -> None:
        with self.lock:
            self.logs.append(message)
            self.logs = self.logs[-100:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "status": self.status,
                "logs": "\n".join(self.logs),
                "error": self.error,
                "output": self.output,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def start(self, source_path: str, target_product: str) -> dict[str, Any]:
        config = core.load_config()
        matches = core.matching_rewrite_outputs(config, source_path, target_product)
        with self.lock:
            if self.running:
                raise RuntimeError("已有改写任务正在运行")
            self.running = True
            self.status = "running"
            self.logs = ["开始重新改写，成功后覆盖原结果" if matches else "开始产品脚本改写"]
            self.error = ""
            self.output = None
            self.started_at = time.time()
            self.finished_at = 0.0
        threading.Thread(target=self._run, args=(source_path, target_product), daemon=True).start()
        return self.snapshot()

    def _run(self, source_path: str, target_product: str) -> None:
        try:
            output = core.run_rewrite(source_path, target_product, log=self.append)
            with self.lock:
                self.output = {"name": output.name, "path": output.as_posix()}
                self.status = "completed"
        except Exception as exc:  # noqa: BLE001 - surface the task error in the local UI.
            self.append(traceback.format_exc())
            with self.lock:
                self.error = str(exc)
                self.status = "failed"
        finally:
            with self.lock:
                self.running = False
                self.finished_at = time.time()


JOB = RewriteJob()


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>产品脚本改写智能体</title>
  <style>
    :root {
      color-scheme:light;
      --bg:#f7f4ec; --surface:#fffdf7; --soft:#f1eee5; --ink:#101010;
      --muted:#5f5b52; --subtle:#8b867a; --line:#151515; --line-soft:rgba(16,16,16,.16);
      --accent:#d9ff63; --green:#1f7a42; --amber:#8b5e00; --red:#b32125;
      --shadow:0 14px 0 rgba(16,16,16,.08);
    }
    * { box-sizing:border-box; }
    html, body { height:100%; }
    body {
      margin:0; overflow:hidden; color:var(--ink);
      background:
        linear-gradient(rgba(16,16,16,.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(16,16,16,.035) 1px, transparent 1px), var(--bg);
      background-size:28px 28px;
      font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Arial,"PingFang SC","Microsoft YaHei",sans-serif;
      letter-spacing:0;
    }
    header {
      height:72px; padding:0 22px; display:flex; align-items:center; justify-content:space-between; gap:16px;
      background:rgba(255,253,247,.86); border-bottom:1px solid var(--line); backdrop-filter:blur(14px);
    }
    h1 { margin:0; font-size:24px; line-height:1; font-weight:820; letter-spacing:0; }
    .sub { margin-top:7px; color:var(--muted); font-size:12px; }
    .statusBar, .actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    .badge { border:1px solid var(--line); padding:6px 10px; font-size:11px; font-weight:780; background:var(--surface); box-shadow:3px 3px 0 rgba(16,16,16,.12); white-space:nowrap; }
    .badge.ok { background:var(--accent); }
    .badge.warn { background:#fff3c7; color:var(--amber); }
    main { height:calc(100vh - 72px); padding:14px; display:grid; grid-template-columns:290px minmax(390px,1fr) 390px; gap:14px; overflow:hidden; }
    section { min-width:0; min-height:0; display:flex; flex-direction:column; background:var(--surface); border:1px solid var(--line); box-shadow:var(--shadow); overflow:hidden; }
    .panelHead { min-height:50px; padding:10px 12px; display:flex; align-items:center; justify-content:space-between; gap:8px; background:var(--soft); border-bottom:1px solid var(--line); }
    h2 { margin:0; font-size:12px; font-weight:820; }
    .panelBody { padding:10px; flex:1; min-height:0; overflow:auto; }
    label { display:block; margin:10px 0 4px; color:var(--muted); font-size:11px; font-weight:780; }
    input, select { width:100%; min-height:34px; padding:7px 9px; border:1px solid var(--line); border-radius:0; background:#fff; color:var(--ink); font:inherit; font-size:13px; outline:none; }
    input:focus, select:focus { box-shadow:4px 4px 0 var(--accent); }
    button { border:1px solid var(--line); border-radius:0; padding:8px 12px; color:var(--ink); background:#fff; font-size:12px; font-weight:820; cursor:pointer; box-shadow:3px 3px 0 rgba(16,16,16,.13); }
    button:hover { background:var(--accent); }
    button:active { transform:translate(2px,2px); box-shadow:1px 1px 0 rgba(16,16,16,.2); }
    button.primary { background:var(--ink); color:#fff; box-shadow:4px 4px 0 var(--accent); }
    #runBtn { min-width:132px; }
    button:disabled { opacity:.5; cursor:not-allowed; transform:none; }
    .path { color:var(--muted); font-size:11px; overflow-wrap:anywhere; line-height:1.45; }
    .configBlock { padding-bottom:10px; border-bottom:1px solid var(--line-soft); }
    .configBlock:last-child { border-bottom:0; }
    .settingsBody { display:flex; flex-direction:column; }
    .settingsLog { margin-top:12px; flex:1 0 170px; min-height:170px; display:flex; flex-direction:column; }
    .settingsLog label { margin-top:0; }
    .pair { margin-top:10px; padding:8px; border:1px solid var(--line); background:#fbffe8; display:grid; gap:5px; }
    .pairRow { display:grid; grid-template-columns:52px minmax(0,1fr); gap:6px; font-size:11px; }
    .pairRow span:first-child { color:var(--muted); }
    .libraryTools { padding:10px; display:grid; grid-template-columns:minmax(0,1fr) minmax(150px,.72fr); gap:8px; border-bottom:1px solid var(--line); }
    .libraryTools label { margin:0 0 4px; }
    .scriptList { padding:6px; display:flex; flex-direction:column; gap:6px; overflow:auto; flex:1; min-height:0; }
    .scriptItem { width:100%; min-height:46px; padding:7px 8px; display:grid; grid-template-columns:18px minmax(0,1fr) auto; gap:7px; align-items:start; border:1px solid var(--line-soft); background:#fff; text-align:left; box-shadow:none; font-weight:550; }
    .scriptItem:hover, .scriptItem.active { border-color:var(--line); background:#f4ffd1; }
    .scriptItem input { width:auto; min-height:0; margin:2px 0 0; accent-color:var(--ink); }
    .scriptName { font-size:11px; line-height:1.4; overflow-wrap:anywhere; word-break:break-word; }
    .scriptMeta { color:var(--muted); font-size:10px; white-space:nowrap; }
    .marker { display:inline-block; margin-top:4px; padding:1px 5px; background:#efede5; color:var(--muted); font-size:9px; font-weight:750; }
    .taskBody { display:flex; flex-direction:column; gap:8px; overflow:hidden; }
    .filename { border:1px solid var(--line); padding:8px; min-height:50px; background:#fff; font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; overflow-wrap:anywhere; }
    .jobBox { border:1px solid var(--line); padding:8px; background:#fbffe8; display:grid; gap:5px; }
    .jobTop { display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:11px; font-weight:750; }
    pre { margin:0; padding:10px; border:1px solid var(--line); background:#111; color:#f7f4ec; white-space:pre-wrap; word-break:break-word; font:11px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; overflow:auto; }
    #logs { flex:1; min-height:140px; max-height:none; }
    .outputHead { display:flex; align-items:center; justify-content:space-between; gap:8px; }
    .outputList { min-height:70px; max-height:130px; overflow:auto; display:flex; flex-direction:column; gap:5px; }
    .outputItem { padding:7px 8px; border:1px solid var(--line-soft); background:#fff; cursor:pointer; }
    .outputItem:hover { border-color:var(--line); background:#f4ffd1; }
    .outputItem strong { display:block; font-size:11px; overflow-wrap:anywhere; }
    .outputItem small { color:var(--muted); font-size:10px; }
    .outputNotice { padding:8px; border:1px solid var(--amber); background:#fff3c7; color:var(--amber); font-size:11px; line-height:1.45; }
    .preview { flex:1 1 220px; min-height:180px; display:flex; flex-direction:column; border:1px solid var(--line); }
    .previewHead { min-height:34px; padding:5px 7px 5px 9px; background:var(--soft); border-bottom:1px solid var(--line); font-size:11px; display:flex; align-items:center; justify-content:space-between; gap:8px; }
    .previewHead span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .previewHead button { flex:0 0 auto; padding:4px 8px; font-size:10px; box-shadow:none; }
    .preview pre { flex:1; min-height:0; border:0; }
    .empty { padding:18px 10px; color:var(--muted); font-size:12px; text-align:center; }
    .error { color:var(--red); }
    dialog { width:min(430px,calc(100vw - 32px)); padding:0; border:1px solid var(--line); border-radius:0; background:var(--surface); color:var(--ink); box-shadow:10px 10px 0 rgba(16,16,16,.22); }
    dialog::backdrop { background:rgba(16,16,16,.48); }
    .dialogBody { padding:18px; display:grid; gap:14px; }
    .dialogBody strong { font-size:15px; }
    .dialogBody p { margin:0; color:var(--muted); font-size:12px; line-height:1.6; }
    .dialogBody .actions { justify-content:flex-end; }
    @media (max-width:1050px) { html,body { height:auto; overflow:auto; } main { height:auto; grid-template-columns:280px minmax(0,1fr); overflow:visible; } section.task { grid-column:1/-1; min-height:680px; } }
    @media (max-width:720px) { header { height:auto; padding:13px; align-items:flex-start; flex-direction:column; } main { grid-template-columns:1fr; padding:10px; } section.task { grid-column:auto; } .libraryTools { grid-template-columns:1fr; } .scriptList { max-height:62vh; } }
  </style>
</head>
<body>
  <header>
    <div><h1>产品脚本改写智能体</h1><div class="sub">爆款脚本库 · 产品信息库 · DeepSeek</div></div>
    <div class="statusBar"><span id="apiBadge" class="badge">API Key</span><span id="jobBadge" class="badge">空闲</span></div>
  </header>
  <main>
    <section>
      <div class="panelHead"><h2>改写设置</h2><button id="saveBtn">保存</button></div>
      <div class="panelBody settingsBody">
        <div class="configBlock">
          <label for="baseUrl">DeepSeek Base URL</label><input id="baseUrl" />
          <label for="model">文本模型</label><input id="model" />
          <label for="apiKey">API Key</label><input id="apiKey" type="password" autocomplete="off" />
        </div>
        <div class="configBlock">
          <label for="targetProduct">目标产品</label><select id="targetProduct"></select>
          <div id="targetInfoPath" class="path"></div>
          <div class="actions" style="margin-top:8px"><button id="previewInfoBtn">预览产品信息</button><button id="openInfoBtn">打开文件</button></div>
        </div>
        <div class="pair">
          <div class="pairRow"><span>来源</span><strong id="pairSource">未选择</strong></div>
          <div class="pairRow"><span>目标</span><strong id="pairTarget">未选择</strong></div>
        </div>
        <label>脚本库</label><div id="scriptsRoot" class="path"></div>
        <label>产品信息库</label><div id="infoRoot" class="path"></div>
        <div class="settingsLog"><label>运行日志</label><pre id="logs">暂无运行日志</pre></div>
      </div>
    </section>
    <section>
      <div class="panelHead"><h2>来源爆款脚本</h2><span id="scriptCount" class="badge">0 条</span></div>
      <div class="libraryTools">
        <div><label for="sourceProduct">来源产品</label><select id="sourceProduct"></select></div>
        <div><label for="search">筛选文件名</label><input id="search" placeholder="国家、账号或视频 ID" /></div>
      </div>
      <div id="scriptList" class="scriptList"></div>
    </section>
    <section class="task">
      <div class="panelHead"><h2>改写任务与输出</h2><button id="openOutputBtn">打开目录</button></div>
      <div class="panelBody taskBody">
        <label>输出文件名</label><div id="filename" class="filename">选择来源脚本后生成</div>
        <div class="actions"><button id="runBtn" class="primary" disabled>开始改写</button><button id="refreshBtn">扫描资料库</button></div>
        <div class="jobBox"><div class="jobTop"><span id="jobText">暂无任务</span><span id="jobTime"></span></div><div id="jobError" class="path error"></div></div>
        <div class="outputHead"><strong>当前脚本改写结果</strong><span id="outputCount" class="path">未选择</span></div>
        <div id="outputList" class="outputList"></div>
        <div class="preview"><div class="previewHead"><span id="previewTitle">文件预览</span><button id="openPreviewFileBtn" disabled>打开文件</button></div><pre id="previewText">选择来源脚本、产品信息或输出文件进行预览</pre></div>
      </div>
    </section>
  </main>
  <dialog id="overwriteDialog" aria-labelledby="overwriteDialogTitle">
    <div class="dialogBody">
      <strong id="overwriteDialogTitle">确认重新改写</strong>
      <p id="overwriteDialogText"></p>
      <div class="actions"><button id="cancelRewriteBtn">取消</button><button id="confirmRewriteBtn" class="primary">确认重新改写</button></div>
    </div>
  </dialog>
  <script>
    const $ = id => document.getElementById(id);
    let state = null;
    let scripts = [];
    let selectedPath = '';
    let outputRoot = '';
    let pollTimer = null;
    let activePreview = null;
    let previewRequestToken = 0;
    let outputRequestToken = 0;
    let outputStatus = 'unselected';
    let jobRunning = false;

    async function api(path, options={}) {
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    }
    function esc(value) { return String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
    function productOptions(products, requireInfo=false) {
      return products.filter(p => !requireInfo || p.has_product_info).map(p => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
    }
    function selectedScript() { return scripts.find(item => item.path === selectedPath); }
    function targetName() { return $('targetProduct').value; }
    function sourceName() { return $('sourceProduct').value; }
    function infoPath() { return `${state.paths.product_info_root}/${targetName()}-产品信息.md`; }

    async function loadState(scan=false) {
      state = await api(scan ? '/api/state?refresh=1' : '/api/state');
      $('baseUrl').value = state.model.deepseek_base_url || '';
      $('model').value = state.model.deepseek_model || '';
      $('apiKey').placeholder = state.has_api_key ? '已配置；输入新密钥可替换' : '请输入 API Key';
      $('apiBadge').textContent = `${state.has_api_key ? 'API Key 已就绪' : '缺少 API Key'} · ${state.ai_settings_source || '8888 全局设置'}`;
      $('apiBadge').className = `badge ${state.has_api_key ? 'ok' : 'warn'}`;
      $('sourceProduct').innerHTML = productOptions(state.products);
      $('targetProduct').innerHTML = productOptions(state.products, true);
      $('scriptsRoot').textContent = state.paths.hot_scripts_root;
      $('infoRoot').textContent = state.paths.product_info_root;
      keepProductsDifferent();
      syncTarget();
      await loadScripts(scan);
      await refreshJob();
      await refreshOutputs();
    }
    function keepProductsDifferent() {
      if (sourceName() !== targetName()) return;
      const candidate = state.products.find(item => item.has_product_info && item.name !== sourceName());
      if (candidate) $('targetProduct').value = candidate.name;
    }
    function syncTarget() {
      $('pairSource').textContent = sourceName() || '未选择';
      $('pairTarget').textContent = targetName() || '未选择';
      $('targetInfoPath').textContent = targetName() ? infoPath() : '';
      updateFilename();
    }
    async function loadScripts(scan=false) {
      selectedPath = '';
      outputStatus = 'unselected';
      resetPreview();
      const product = sourceName();
      const data = await api(`/api/scripts?product=${encodeURIComponent(product)}${scan ? '&refresh=1' : ''}`);
      scripts = data.scripts || [];
      $('search').value = '';
      renderScripts();
      syncSelection();
    }
    function renderScripts() {
      const query = $('search').value.trim().toLowerCase();
      const visible = scripts.filter(item => item.name.toLowerCase().includes(query));
      $('scriptCount').textContent = `${visible.length} 条`;
      $('scriptList').innerHTML = visible.length ? visible.map(item => `
        <button class="scriptItem ${item.path === selectedPath ? 'active' : ''}" data-path="${esc(item.path)}">
          <input type="radio" tabindex="-1" ${item.path === selectedPath ? 'checked' : ''} />
          <span class="scriptName">${esc(item.name)}${item.rewritten ? '<span class="marker">已含来源标记</span>' : ''}</span>
          <span class="scriptMeta">${esc(item.modified)}</span>
        </button>`).join('') : '<div class="empty">没有匹配的 Markdown 脚本</div>';
      document.querySelectorAll('.scriptItem').forEach(button => button.addEventListener('click', () => {
        selectedPath = button.dataset.path || '';
        outputStatus = 'checking';
        renderScripts();
        syncSelection();
        preview(selectedPath).catch(error => showPreviewError(error));
        refreshOutputs().catch(error => $('jobError').textContent = error.message);
      }));
    }
    function syncRunButton() {
      const actionable = ['missing', 'existing', 'duplicate'].includes(outputStatus);
      $('runBtn').disabled = jobRunning || !selectedScript() || sourceName() === targetName() || !actionable;
      $('runBtn').textContent = outputStatus === 'existing' ? '重新改写' : outputStatus === 'duplicate' ? '重新改写并保留一份' : '开始改写';
    }
    function syncSelection() {
      syncRunButton();
      updateFilename();
    }
    async function updateFilename() {
      if (!selectedPath || !targetName()) { $('filename').textContent = '选择来源脚本后生成'; return; }
      try {
        const data = await api('/api/preview-name', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source_path:selectedPath, target_product:targetName()})});
        $('filename').textContent = data.name;
        $('filename').className = 'filename';
      } catch (error) {
        $('filename').textContent = error.message;
        $('filename').className = 'filename error';
      }
    }
    function resetPreview() {
      previewRequestToken += 1;
      activePreview = null;
      $('previewTitle').textContent = '文件预览';
      $('previewText').textContent = '选择来源脚本、产品信息或输出文件进行预览';
      $('openPreviewFileBtn').disabled = true;
    }
    function showPreviewError(error) {
      activePreview = null;
      $('previewTitle').textContent = '预览失败';
      $('previewText').textContent = error.message || String(error);
      $('openPreviewFileBtn').disabled = true;
    }
    async function preview(path) {
      const token = ++previewRequestToken;
      $('previewTitle').textContent = '正在加载...';
      $('previewText').textContent = '正在读取文件';
      const data = await api(`/api/file?path=${encodeURIComponent(path)}`);
      if (token !== previewRequestToken) return null;
      activePreview = data;
      $('previewTitle').textContent = data.name;
      $('previewText').textContent = data.text;
      $('openPreviewFileBtn').disabled = false;
      return data;
    }
    async function saveSettings() {
      state = await api('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({deepseek_base_url:$('baseUrl').value, deepseek_model:$('model').value, deepseek_api_key:$('apiKey').value})});
      $('apiKey').value = '';
      $('apiKey').placeholder = state.has_api_key ? '已配置；输入新密钥可替换' : '请输入 API Key';
      $('apiBadge').textContent = `${state.has_api_key ? 'API Key 已就绪' : '缺少 API Key'} · ${state.ai_settings_source || '8888 全局设置'}`;
      $('apiBadge').className = `badge ${state.has_api_key ? 'ok' : 'warn'}`;
    }
    function requestRewrite() {
      if (outputStatus === 'existing' || outputStatus === 'duplicate') {
        $('overwriteDialogText').textContent = outputStatus === 'duplicate'
          ? '检测到历史重复结果。新脚本通过质量校验后，将写入规范全称文件名并只保留一份；校验失败时原文件保持不动。'
          : '当前脚本已有一份改写结果。新脚本通过质量校验后将覆盖原文件；校验失败时原文件保持不动。';
        $('overwriteDialog').showModal();
        return;
      }
      runRewrite();
    }
    async function runRewrite() {
      jobRunning = true;
      $('jobError').textContent = '';
      syncRunButton();
      try {
        const job = await api('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source_path:selectedPath, target_product:targetName()})});
        renderJob(job);
        pollTimer = setInterval(refreshJob, 1000);
      } catch (error) {
        jobRunning = false;
        $('jobError').textContent = error.message;
        await refreshOutputs().catch(() => {});
        syncRunButton();
      }
    }
    function renderJob(job) {
      const labels = {idle:'空闲',running:'改写中',completed:'已完成',failed:'失败'};
      $('jobBadge').textContent = labels[job.status] || job.status;
      $('jobBadge').className = `badge ${job.status === 'completed' ? 'ok' : job.status === 'failed' ? 'warn' : ''}`;
      $('jobText').textContent = job.status === 'idle' ? '暂无任务' : `任务状态：${labels[job.status] || job.status}`;
      $('jobError').textContent = job.error || '';
      $('logs').textContent = job.logs || '暂无运行日志';
      $('jobTime').textContent = job.running && job.started_at ? `${Math.max(0, Math.round(Date.now()/1000 - job.started_at))}s` : '';
      jobRunning = !!job.running;
      syncRunButton();
      if (job.output) preview(job.output.path).catch(() => {});
    }
    async function refreshJob() {
      const job = await api('/api/job');
      renderJob(job);
      if (!job.running && pollTimer) {
        clearInterval(pollTimer); pollTimer = null;
        await refreshOutputs();
      }
    }
    async function refreshOutputs() {
      const token = ++outputRequestToken;
      const source = selectedPath;
      const target = targetName();
      if (!target) return;
      outputRoot = `${state.paths.hot_scripts_root}/${target}`;
      if (!source) {
        outputStatus = 'unselected';
        $('outputCount').textContent = '未选择';
        $('outputCount').className = 'path';
        $('outputList').innerHTML = '<div class="empty">选择来源脚本后检查改写结果</div>';
        syncRunButton();
        return;
      }
      outputStatus = 'checking';
      $('outputCount').textContent = '检查中';
      $('outputCount').className = 'path';
      syncRunButton();
      let data;
      try {
        data = await api(`/api/outputs?product=${encodeURIComponent(target)}&source_path=${encodeURIComponent(source)}`);
      } catch (error) {
        if (token === outputRequestToken) {
          outputStatus = 'error';
          $('outputCount').textContent = '检查失败';
          $('outputCount').className = 'path error';
          $('outputList').innerHTML = `<div class="empty error">${esc(error.message)}</div>`;
          syncRunButton();
        }
        throw error;
      }
      if (token !== outputRequestToken || source !== selectedPath || target !== targetName()) return;
      outputRoot = data.root || '';
      outputStatus = data.status || 'error';
      const outputs = data.outputs || [];
      const labels = {missing:'未改写', existing:'已改写', duplicate:`发现重复 ${outputs.length} 份`};
      $('outputCount').textContent = labels[outputStatus] || '状态异常';
      $('outputCount').className = `path ${outputStatus === 'duplicate' ? 'error' : ''}`;
      const notice = outputStatus === 'duplicate' ? '<div class="outputNotice">检测到历史重复文件。重新改写成功后，将写入规范全称文件名并只保留一份。</div>' : '';
      const items = outputs.map(item => `<div class="outputItem" data-path="${esc(item.path)}"><strong>${esc(item.name)}</strong><small>${esc(item.modified)} · ${item.size} bytes</small></div>`).join('');
      const empty = outputStatus === 'missing' ? '<div class="empty">当前来源脚本尚未改写为该目标产品</div>' : '';
      $('outputList').innerHTML = notice + items + empty;
      document.querySelectorAll('.outputItem').forEach(item => item.addEventListener('click', () => preview(item.dataset.path).catch(error => showPreviewError(error))));
      syncRunButton();
    }
    async function openPath(path) { await api('/api/open', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({path})}); }

    $('saveBtn').addEventListener('click', () => saveSettings().catch(error => $('jobError').textContent = error.message));
    $('sourceProduct').addEventListener('change', async () => { keepProductsDifferent(); syncTarget(); await loadScripts(); await refreshOutputs(); });
    $('targetProduct').addEventListener('change', async () => { outputStatus = selectedPath ? 'checking' : 'unselected'; syncTarget(); syncSelection(); await refreshOutputs(); });
    $('search').addEventListener('input', renderScripts);
    $('previewInfoBtn').addEventListener('click', () => targetName() && preview(infoPath()).catch(error => showPreviewError(error)));
    $('openPreviewFileBtn').addEventListener('click', () => activePreview?.path && openPath(activePreview.path));
    $('openInfoBtn').addEventListener('click', () => targetName() && openPath(infoPath()));
    $('openOutputBtn').addEventListener('click', () => outputRoot && openPath(outputRoot));
    $('runBtn').addEventListener('click', requestRewrite);
    $('cancelRewriteBtn').addEventListener('click', () => $('overwriteDialog').close());
    $('confirmRewriteBtn').addEventListener('click', () => { $('overwriteDialog').close(); runRewrite(); });
    $('refreshBtn').addEventListener('click', () => loadState(true).catch(error => $('jobError').textContent = error.message));
    loadState().catch(error => { $('jobError').textContent = error.message; $('previewText').textContent = error.message; });
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/":
                text_response(self, 200, HTML, "text/html; charset=utf-8")
            elif parsed.path == "/health":
                json_response(self, 200, {"status": "ok"})
            elif parsed.path == "/api/state":
                query = urllib.parse.parse_qs(parsed.query)
                json_response(self, 200, state_payload(query.get("refresh", [""])[0] == "1"))
            elif parsed.path == "/api/job":
                json_response(self, 200, JOB.snapshot())
            elif parsed.path == "/api/scripts":
                query = urllib.parse.parse_qs(parsed.query)
                product = query.get("product", [""])[0]
                json_response(self, 200, {"scripts": cached_scripts(product, query.get("refresh", [""])[0] == "1")})
            elif parsed.path == "/api/outputs":
                query = urllib.parse.parse_qs(parsed.query)
                product = query.get("product", [""])[0]
                source_path = query.get("source_path", [""])[0]
                json_response(self, 200, output_items(product, source_path))
            elif parsed.path == "/api/file":
                value = urllib.parse.parse_qs(parsed.query).get("path", [""])[0]
                path = safe_path(value)
                if not path.is_file():
                    raise ValueError("文件不存在")
                json_response(self, 200, {"name": path.name, "path": path.as_posix(), "text": path.read_text(encoding="utf-8", errors="ignore")[:400000]})
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - convert local API errors to JSON.
            json_response(self, 400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = request_json(self)
            if parsed.path == "/api/settings":
                json_response(self, 200, update_settings(payload))
            elif parsed.path == "/api/preview-name":
                config = core.load_config()
                source_path = str(payload.get("source_path") or "")
                target_product = str(payload.get("target_product") or "")
                output = core.output_path_for(config, source_path, target_product)
                matches = core.matching_rewrite_outputs(config, source_path, target_product)
                status = "missing" if not matches else "existing" if len(matches) == 1 else "duplicate"
                json_response(
                    self,
                    200,
                    {
                        "name": output.name,
                        "path": output.as_posix(),
                        "exists": bool(matches),
                        "status": status,
                        "existing_outputs": [path.as_posix() for path in matches],
                    },
                )
            elif parsed.path == "/api/run":
                json_response(self, 200, JOB.start(str(payload.get("source_path") or ""), str(payload.get("target_product") or "")))
            elif parsed.path == "/api/open":
                json_response(self, 200, open_local_path(str(payload.get("path") or "")))
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - convert local API errors to JSON.
            json_response(self, 400, {"error": str(exc)})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the product script rewrite agent web UI.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"产品脚本改写智能体 Web 界面: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
