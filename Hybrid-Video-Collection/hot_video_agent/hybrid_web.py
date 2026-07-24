from __future__ import annotations

import importlib.util

from . import web
from .config import CONFIG_PATH, init_config, read_config_file
from .paths import ProjectPaths


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>混剪参考视频采集智能体</title>
  <style>
    :root { --bg:#f7f4ec; --surface:#fffdf7; --soft:#f1eee5; --ink:#101010; --muted:#625f57; --line:#151515; --accent:#d9ff63; --red:#b32125; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }
    header { min-height:76px; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 22px; border-bottom:1px solid var(--line); background:var(--surface); }
    h1 { margin:0; font-size:24px; }
    .sub,.hint,.path { color:var(--muted); font-size:12px; line-height:1.5; }
    .badge { padding:7px 11px; border:1px solid var(--line); background:var(--accent); font-size:12px; font-weight:750; }
    .badge.error { color:#fff; background:var(--red); }
    main { display:grid; grid-template-columns:minmax(340px,480px) 1fr; gap:16px; padding:16px; }
    section { border:1px solid var(--line); background:var(--surface); box-shadow:8px 8px 0 rgba(16,16,16,.08); }
    .head { display:flex; align-items:center; justify-content:space-between; padding:12px 14px; border-bottom:1px solid var(--line); background:var(--soft); }
    h2 { margin:0; font-size:14px; }
    .body { padding:14px; }
    label { display:block; margin:11px 0 5px; color:var(--muted); font-size:12px; font-weight:750; }
    input,select,textarea,button { width:100%; border:1px solid var(--line); border-radius:0; background:#fff; color:var(--ink); font:inherit; padding:10px; }
    textarea { min-height:190px; resize:vertical; line-height:1.5; }
    button { width:auto; cursor:pointer; font-weight:780; }
    button.primary { width:100%; margin-top:14px; background:var(--accent); }
    button:disabled { opacity:.5; cursor:not-allowed; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .kv { margin-top:12px; padding:10px; border:1px solid rgba(16,16,16,.2); background:#fff; }
    .kv strong { display:block; margin-bottom:4px; font-size:12px; }
    .checks { display:grid; gap:8px; margin-bottom:12px; }
    .check { padding:9px 10px; border-left:4px solid var(--accent); background:var(--soft); font-size:12px; }
    .check.error { border-color:var(--red); }
    pre { min-height:260px; max-height:55vh; margin:0; padding:12px; overflow:auto; background:#111; color:#f6f3e8; white-space:pre-wrap; font-size:12px; line-height:1.5; }
    .outputs { display:grid; gap:8px; margin-top:12px; }
    .output { padding:9px; border:1px solid rgba(16,16,16,.2); font-size:12px; overflow-wrap:anywhere; }
    @media (max-width:900px) { main { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <div><h1>混剪参考视频采集智能体</h1><div class="sub">TikTok URL 下载 · 类型与产品归档 · 独立任务状态</div></div>
    <span id="jobBadge" class="badge">空闲</span>
  </header>
  <main>
    <section>
      <div class="head"><h2>下载设置</h2><button id="refreshProductsBtn">刷新产品</button></div>
      <div class="body">
        <div class="row">
          <div>
            <label for="material_type">参考视频类型</label>
            <select id="material_type">
              <option value="混剪-钩子">混剪-钩子</option>
              <option value="混剪-CTA">混剪-CTA</option>
            </select>
          </div>
          <div>
            <label for="name">产品名称</label>
            <input id="name" list="productOptions" placeholder="选择或输入产品名称" />
            <datalist id="productOptions"></datalist>
          </div>
        </div>
        <label for="direct_urls">TikTok 视频 URL</label>
        <textarea id="direct_urls" placeholder="每行一个 TikTok 视频链接，也可以用空格分隔"></textarea>
        <label for="download_limit">下载上限</label>
        <input id="download_limit" type="number" min="0" value="0" />
        <div class="hint">0 表示下载本次输入的全部URL。不会运行FastMoss采集。</div>
        <div class="kv"><strong>输出目录</strong><div id="outputPath" class="path"></div></div>
        <button class="primary" id="runBtn">开始 URL 下载</button>
      </div>
    </section>
    <section>
      <div class="head"><h2>运行状态</h2><button id="refreshBtn">刷新</button></div>
      <div class="body">
        <div id="checks" class="checks"></div>
        <pre id="logs">暂无运行日志</pre>
        <div id="outputs" class="outputs"></div>
      </div>
    </section>
  </main>
  <script>
    const $ = id => document.getElementById(id);
    let outputRoot = '';
    let pollTimer = null;

    async function api(path, options={}) {
      const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
      const text = await response.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = {error:text}; }
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    }

    function safeName(value) {
      return String(value || '').trim().replace(/[\\/:*?"<>|]+/g, '_').replace(/\s+/g, '_').replace(/_+/g, '_').replace(/^[ ._]+|[ ._]+$/g, '') || 'product';
    }

    function payload() {
      return {
        material_type: $('material_type').value,
        name: $('name').value.trim(),
        download_limit: $('download_limit').value,
        direct_urls: $('direct_urls').value
      };
    }

    function updateOutputPreview() {
      const product = $('name').value.trim();
      $('outputPath').textContent = product ? `${outputRoot}/${$('material_type').value}/${safeName(product)}` : '请先选择或输入产品名称';
    }

    function fillState(data) {
      const config = data.config || {};
      const hybrid = config.hybrid || {};
      const product = config.product || {};
      const download = config.download || {};
      outputRoot = data.paths?.hot_video_root || '';
      $('material_type').value = hybrid.material_type || '混剪-钩子';
      $('name').value = product.name || '';
      $('download_limit').value = download.limit || 0;
      $('productOptions').innerHTML = (data.product_options || []).map(item => `<option value="${escapeHtml(item.name || '')}"></option>`).join('');
      updateOutputPreview();
    }

    function renderChecks(checks=[]) {
      $('checks').innerHTML = checks.map(item => `<div class="check ${escapeHtml(item.level || '')}"><strong>${escapeHtml(item.message || '')}</strong><div>${escapeHtml(item.detail || '')}</div></div>`).join('');
    }

    function renderJob(job) {
      const status = {idle:'空闲',running:'运行中',completed:'已完成',failed:'失败'}[job.status] || job.status || '空闲';
      $('jobBadge').textContent = status;
      $('jobBadge').className = `badge ${job.status === 'failed' ? 'error' : ''}`;
      $('runBtn').disabled = !!job.running;
      $('logs').textContent = job.logs || job.error || '暂无运行日志';
      $('outputs').innerHTML = (job.outputs || []).map(item => `<div class="output"><strong>${escapeHtml(item.name || '')}</strong><div>${escapeHtml(item.path || '')}</div></div>`).join('');
    }

    async function inspect() {
      const data = await api('/api/inspect');
      renderChecks(data.checks || []);
    }

    async function saveSettings() {
      const data = await api('/api/settings', {method:'POST', body:JSON.stringify(payload())});
      fillState(data);
    }

    async function run() {
      if (!$('name').value.trim()) throw new Error('请先选择或输入产品名称');
      if (!$('direct_urls').value.trim()) throw new Error('请先粘贴TikTok视频URL');
      await saveSettings();
      const job = await api('/api/run', {method:'POST', body:JSON.stringify({...payload(), mode:'url_download'})});
      renderJob(job);
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(refreshJob, 1200);
    }

    async function refreshJob() {
      const job = await api('/api/job');
      renderJob(job);
      if (!job.running && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
        fillState(await api('/api/state'));
        await inspect();
      }
    }

    async function refreshProducts() {
      const selected = $('name').value;
      const data = await api('/api/products/refresh', {method:'POST', body:'{}'});
      fillState(data);
      if (selected) $('name').value = selected;
      updateOutputPreview();
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }

    $('material_type').addEventListener('change', updateOutputPreview);
    $('name').addEventListener('input', updateOutputPreview);
    $('runBtn').addEventListener('click', () => run().catch(error => renderChecks([{level:'error',message:'无法开始任务',detail:error.message}])));
    $('refreshBtn').addEventListener('click', () => refreshJob().catch(error => renderChecks([{level:'error',message:'刷新失败',detail:error.message}])));
    $('refreshProductsBtn').addEventListener('click', () => refreshProducts().catch(error => renderChecks([{level:'error',message:'刷新产品失败',detail:error.message}])));

    async function boot() {
      fillState(await api('/api/state'));
      await inspect();
      await refreshJob();
    }
    boot().catch(error => renderChecks([{level:'error',message:'页面初始化失败',detail:error.message}]));
  </script>
</body>
</html>"""


def inspect_config() -> dict:
    init_config(CONFIG_PATH)
    config = read_config_file(CONFIG_PATH)
    paths = ProjectPaths(web.ROOT, config)
    hybrid = config.get("hybrid") or {}
    product = config.get("product") or {}
    checks = []
    material_type = str(hybrid.get("material_type") or "")
    checks.append({
        "level": "ok" if material_type in {"混剪-钩子", "混剪-CTA"} else "error",
        "message": "参考视频类型",
        "detail": material_type or "未配置",
    })
    product_name = str(product.get("name") or "").strip()
    checks.append({
        "level": "ok" if product_name else "warn",
        "message": "产品名称",
        "detail": product_name or "运行前请选择或输入产品名称",
    })
    checks.append({
        "level": "ok" if importlib.util.find_spec("playwright") else "error",
        "message": "下载环境",
        "detail": "Playwright 已安装" if importlib.util.find_spec("playwright") else "请安装 requirements.txt",
    })
    checks.append({"level": "ok", "message": "输出目录", "detail": paths.hot_video_dir().as_posix()})
    return {"checks": checks, "ready": not any(item["level"] == "error" for item in checks)}


web.HTML = HTML
web.DEFAULT_PORT = 10001
web.inspect_config = inspect_config


def main(argv: list[str] | None = None) -> None:
    web.main(argv)


if __name__ == "__main__":
    main()
