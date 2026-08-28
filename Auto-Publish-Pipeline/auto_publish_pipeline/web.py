from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from opc_shared.ui_theme import send_theme_css
from opc_shared.vault_snapshot import cached_or_empty, refresh_snapshot

from .domain import (
    COUNTRY_DEFAULT_LANGUAGES,
    build_task_spec,
    infer_product_name,
    infer_script_country,
    match_product_code,
)
from .runner import PipelineRunner, RESULT_PREFIX
from .store import TaskStore


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
DATA_ROOT = ROOT / "data"
DB_PATH = DATA_ROOT / "pipeline.sqlite3"
VAULT_ROOT = Path(os.environ.get("OPC_VAULT_ROOT") or "/__OPC_VAULT_ROOT_NOT_CONFIGURED__").expanduser()
CLONE_ROOT = Path(os.environ.get("PRODUCT_SCRIPT_ROOT", VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "03产品脚本")).expanduser()
REFERENCE_ROOT = Path(os.environ.get("REFERENCE_ROOT", VAULT_ROOT / "wiki" / "产品" / "产品底图")).expanduser()
STORE = TaskStore(DB_PATH)
RUNNER = PipelineRunner(STORE, WORKSPACE_ROOT)


def component_python(component: str) -> str:
    path = WORKSPACE_ROOT / component / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(path) if path.is_file() else sys.executable


def bridge(*arguments: str) -> dict:
    command = [
        component_python("Finished-Video-Manager"), "-m",
        "finished_video_manager.pipeline_bridge", *arguments,
    ]
    completed = subprocess.run(
        command,
        cwd=WORKSPACE_ROOT / "Finished-Video-Manager",
        env=os.environ.copy(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    result = None
    for line in reversed((completed.stdout or "").splitlines()):
        if line.startswith(RESULT_PREFIX):
            result = json.loads(line[len(RESULT_PREFIX) :])
            break
    if completed.returncode or not result or result.get("error"):
        raise RuntimeError(str((result or {}).get("error") or "读取成品管理配置失败"))
    return result


def catalog_payload() -> dict:
    publish = bridge("catalog")
    libraries = publish.get("libraries") or []
    scripts = []
    if CLONE_ROOT.is_dir():
        for path in sorted(CLONE_ROOT.rglob("复刻-*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
            product_name = infer_product_name(path)
            country = infer_script_country(path)
            scripts.append(
                {
                    "path": str(path.resolve()),
                    "name": path.name,
                    "product_name": product_name,
                    "product_code": match_product_code(product_name, libraries),
                    "country": country,
                    "default_language": COUNTRY_DEFAULT_LANGUAGES.get(country, ""),
                }
            )
    images = []
    if REFERENCE_ROOT.is_dir():
        images = [
            {"path": str(path.resolve()), "name": path.relative_to(REFERENCE_ROOT).as_posix()}
            for path in sorted(REFERENCE_ROOT.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
    countries = sorted(
        {
            str(country.get("code") or "")
            for library in libraries for country in library.get("country_libraries") or []
            if country.get("code")
        }
    )
    available_paths = {str(item.get("path") or "") for item in publish.get("videos") or []}
    reusable = []
    for task in STORE.list():
        for path in task["artifacts"].get("reserve_videos") or []:
            if path in available_paths and Path(path).is_file():
                reusable.append(
                    {
                        "path": path,
                        "clone_path": task["spec"].get("clone_path"),
                        "product_code": task["spec"].get("product_code"),
                        "country": task["spec"].get("country"),
                        "name": Path(path).name,
                    }
                )
    return {
        "scripts": scripts,
        "images": images,
        "profiles": publish.get("profiles") or [],
        "videos": publish.get("videos") or [],
        "reusable_videos": reusable,
        "libraries": [{"code": item.get("code"), "key": item.get("key"), "name": item.get("name")} for item in libraries],
        "countries": countries,
        "warnings": publish.get("warnings") or [],
        "clone_root": str(CLONE_ROOT),
        "reference_root": str(REFERENCE_ROOT),
    }


def create_task(payload: dict) -> dict:
    publish_catalog = bridge("catalog")

    def resolve_mapping(profile_id: str, product_code: str, country: str) -> dict:
        return bridge(
            "mapping", "--profile-id", profile_id,
            "--product-code", product_code, "--country", country,
        )

    spec = build_task_spec(payload, publish_catalog, resolve_mapping)
    task = STORE.create(spec)
    RUNNER.wake()
    return task


def public_task(task: dict) -> dict:
    spec = task["spec"]
    return {
        **task,
        "summary": {
            "product": spec.get("product_name"),
            "country": spec.get("country"),
            "model": spec.get("video_model"),
            "account_count": len(spec.get("profile_ids") or []),
            "variant_count": spec.get("variant_count"),
            "publish_count": spec.get("publish_count"),
            "candidate_budget": spec.get("candidate_budget"),
            "generation_count": spec.get("generation_count"),
            "auto_publish": spec.get("auto_publish"),
            "start_mode": spec.get("start_mode"),
            "scheduled_at": spec.get("scheduled_at"),
        },
    }


INDEX_HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>10005 · 自动发布流水线</title>
<style>:root{color-scheme:dark;--bg:#0b0d10;--panel:#151a21;--line:#2b3440;--text:#f4f7fa;--muted:#9ca7b4;--blue:#72a8ff;--green:#63d29b;--red:#ff8e8e}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#192331,#0b0d10 45%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1080px;margin:auto;padding:42px 22px 80px}header{display:flex;justify-content:space-between;gap:20px;align-items:start;margin-bottom:24px}h1{font-size:38px;margin:0 0 8px}p,.muted{color:var(--muted)}a,button{border:1px solid var(--line);border-radius:10px;background:#202834;color:var(--text);padding:10px 14px;text-decoration:none;font:inherit;cursor:pointer}button.primary{background:#edf3fa;color:#111820;border-color:#edf3fa}button:disabled{opacity:.5}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.panel{border:1px solid var(--line);border-radius:17px;background:linear-gradient(145deg,#181e26,#11161c);padding:20px}.wide{grid-column:1/-1}.title{font-size:18px;font-weight:720;margin-bottom:14px}.field{margin:12px 0}label{display:block;font-size:13px;color:var(--muted);margin-bottom:6px}select,input{width:100%;border:1px solid var(--line);border-radius:9px;background:#0d1218;color:var(--text);padding:10px}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.accounts{display:grid;gap:8px;max-height:260px;overflow:auto}.account{display:flex;align-items:center;gap:9px;padding:10px;border:1px solid var(--line);border-radius:10px}.account input{width:auto}.order{color:var(--blue);font-weight:700}.summary{padding:14px;border:1px solid var(--line);border-radius:11px;background:#0d1218;line-height:1.7}.message{margin-top:12px;color:var(--muted)}.message.error{color:var(--red)}.tasks{display:grid;gap:10px}.task{padding:14px;border:1px solid var(--line);border-radius:11px;background:#0d1218}.taskHead{display:flex;justify-content:space-between;gap:12px}.status{color:var(--green)}pre{white-space:pre-wrap;color:var(--muted);font-size:12px;max-height:180px;overflow:auto}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}@media(max-width:760px){.grid,.row{grid-template-columns:1fr}.wide{grid-column:auto}header{flex-direction:column}}</style>
<link rel="stylesheet" href="/opc-theme.css?v=20260828"></head>
<body class="opc-agent"><main><header><div><h1>10005 · 自动发布流水线</h1><p>独立完成脚本裂变、适配、片段产出、合成与串行发布，不要求9993–9995处于启动状态。</p></div><div class="actions"><button id="scanCatalog">扫描资料库</button><a class="opc-home-link" href="http://127.0.0.1:8888/">返回控制台</a></div></header>
<section class="grid"><div class="panel wide"><div class="title">1 · 选择已复刻脚本</div><div class="field"><label>复刻脚本</label><select id="script"></select></div><div class="row"><div class="field"><label>识别到的产品标题库</label><select id="product"></select></div><div class="field"><label>产品参考图</label><select id="image"></select></div></div></div>
<div class="panel wide"><div class="title">2 · 优先使用已有成品</div><p class="muted">同一复刻脚本由10005留下的备用成片会自动勾选；手动Agent生成的同产品、同国家成片需要你确认后勾选。</p><div id="existing" class="accounts"></div></div>
<div class="panel"><div class="title">3 · 市场与模型</div><div class="row"><div class="field"><label>国家/地区（由复刻脚本自动识别）</label><input id="country" readonly></div><div class="field"><label>目标语言（自动匹配，也可改选）</label><select id="language"><option>英语</option><option>法语</option><option>德语</option><option>西班牙语</option><option>意大利语</option><option>葡萄牙语</option><option>越南语</option><option>菲律宾语</option><option>泰语</option><option>马来语</option><option>孟加拉语</option><option>尼泊尔语</option><option>印尼语</option></select></div></div><div class="row"><div class="field"><label>视频模型</label><select id="model"><option value="omni">Omni</option><option value="grok">Grok</option></select></div><div class="field"><label>片段生成并发数</label><input id="concurrency" type="number" min="1" max="20" value="3"></div></div><div class="field"><label>字幕模式</label><select id="caption"><option value="none">无字幕</option><option value="karaoke">卡拉OK字幕</option></select></div></div>
<div class="panel"><div class="title">4 · 发布账号（点击顺序就是发布顺序）</div><div id="accounts" class="accounts"></div></div>
<div class="panel"><div class="title">5 · 发布方式</div><div class="field"><label>是否自动发布</label><select id="auto"><option value="yes">是</option><option value="no">否，成片后等待人工发布</option></select></div><div id="timing"><div class="field"><label>开始方式</label><select id="startMode"><option value="immediate">立即开始</option><option value="scheduled">定时开始</option></select></div><div class="field" id="scheduleField" hidden><label>首次发布时间</label><input id="scheduled" type="datetime-local"></div></div><div class="muted">全部任务串行执行，相邻视频发布完成后固定等待10秒。</div></div>
<div class="panel"><div class="title">6 · 执行确认</div><div class="summary" id="summary">请选择账号。</div><button class="primary" id="create">创建并执行流水线</button><div class="message" id="message"></div></div>
<div class="panel wide"><div class="title">流水线任务</div><div id="tasks" class="tasks">正在读取…</div></div></section></main>
<script>const $=id=>document.getElementById(id);let catalog={scripts:[],images:[],profiles:[],libraries:[],videos:[],reusable_videos:[]},order=[],existing=[];const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function fill(select,items,value,label){select.innerHTML=items.map(x=>`<option value="${esc(value(x))}">${esc(label(x))}</option>`).join('')}
function selectedScript(){return catalog.scripts.find(x=>x.path===$('script').value)}
function scriptChanged(){const item=selectedScript();if(item?.product_code)$('product').value=item.product_code;$('country').value=item?.country||'无法识别';if(item?.default_language)$('language').value=item.default_language;order=[];existing=catalog.reusable_videos.filter(v=>v.clone_path===$('script').value&&v.country===item?.country).map(v=>v.path);renderAccounts();renderExisting();renderSummary()}
function renderExisting(){const product=$('product').value,country=$('country').value,exact=new Set(catalog.reusable_videos.filter(v=>v.clone_path===$('script').value&&v.country===country).map(v=>v.path));const rows=catalog.videos.filter(v=>v.product_code===product&&(v.countries||[]).includes(country));$('existing').innerHTML=rows.map(v=>`<label class="account"><input type="checkbox" value="${esc(v.path)}" ${existing.includes(v.path)?'checked':''} ${exact.has(v.path)?'disabled':''}><span>${exact.has(v.path)?'10005备用 · ':'手动成品 · '}${esc(v.name)}</span></label>`).join('')||'<span class="muted">当前没有可复用的未发布成品，将按150%预算新生产。</span>';$('existing').querySelectorAll('input:not(:disabled)').forEach(input=>input.onchange=()=>{if(input.checked&&!existing.includes(input.value))existing.push(input.value);if(!input.checked)existing=existing.filter(x=>x!==input.value);renderSummary()})}
function renderAccounts(){const country=$('country').value;$('accounts').innerHTML=catalog.profiles.filter(p=>p.country===country).map(p=>`<label class="account"><input type="checkbox" value="${esc(p.id)}" ${order.includes(p.id)?'checked':''}><span class="order">${order.includes(p.id)?order.indexOf(p.id)+1:''}</span><span>${esc(p.name)}</span></label>`).join('')||'<span class="muted">该国家没有可用发布账号。</span>';$('accounts').querySelectorAll('input').forEach(input=>input.onchange=()=>{if(input.checked&&!order.includes(input.value))order.push(input.value);if(!input.checked)order=order.filter(x=>x!==input.value);renderAccounts();renderSummary()})}
function renderSummary(){const n=order.length,need=n*3,budget=Math.ceil(need*1.5),used=Math.min(existing.length,budget),generate=Math.max(0,budget-used);$('summary').innerHTML=`账号：${n}个<br>发布配额：${need}条 · 150%候选预算：${budget}条<br>优先复用已有成片：${used}条 · 计划新产出：${generate}条<br>账号顺序：${order.map(id=>catalog.profiles.find(p=>p.id===id)?.name||id).map(esc).join(' → ')||'尚未选择'}<br>视频间隔：10秒 · 串行执行`}
function timing(){const auto=$('auto').value==='yes';$('timing').hidden=!auto;$('scheduleField').hidden=!auto||$('startMode').value!=='scheduled'}
async function loadCatalog(scan=false){const r=await fetch(scan?'/api/catalog?refresh=1':'/api/catalog');const d=await r.json();if(!r.ok)throw Error(d.error||'目录读取失败');catalog=d;fill($('script'),d.scripts,x=>x.path,x=>`${x.name} · ${x.product_name}`);fill($('product'),d.libraries,x=>x.code||x.key,x=>`${x.code||x.key} · ${x.name}`);fill($('image'),d.images,x=>x.path,x=>x.name);$('script').onchange=scriptChanged;$('product').onchange=()=>{existing=[];renderExisting();renderSummary()};scriptChanged()}
async function createTask(){const button=$('create');button.disabled=true;$('message').className='message';$('message').textContent='正在校验并创建任务…';try{const payload={clone_path:$('script').value,product_code:$('product').value,target_language:$('language').value,video_model:$('model').value,reference_image:$('image').value,concurrency:Number($('concurrency').value),caption_mode:$('caption').value,profile_ids:order,existing_video_paths:existing,auto_publish:$('auto').value==='yes',start_mode:$('startMode').value,scheduled_at:$('scheduled').value};const r=await fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok)throw Error(d.error||'创建失败');$('message').textContent=`任务 ${d.id} 已创建并开始执行。`;await loadTasks()}catch(e){$('message').className='message error';$('message').textContent=e.message}finally{button.disabled=false}}
async function taskAction(id,action,payload={}){const r=await fetch(`/api/tasks/${id}/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok)alert(d.error||'操作失败');loadTasks()}
async function loadTasks(){const r=await fetch('/api/tasks');const d=await r.json();$('tasks').innerHTML=(d.tasks||[]).map(t=>`<article class="task"><div class="taskHead"><strong>${esc(t.id)} · ${esc(t.summary.product)}</strong><span class="status">${esc(t.status)} / ${esc(t.stage)}</span></div><div class="muted">${esc(t.summary.country)} · ${esc(t.summary.model)} · 发布${t.summary.publish_count}条 · 候选预算${t.summary.candidate_budget}条 · 新产出${t.summary.generation_count}条</div>${t.error?`<div class="message error">${esc(t.error)}</div>`:''}<div class="actions">${t.status==='failed'?`<button onclick="taskAction('${t.id}','retry')">从失败阶段继续</button>`:''}${t.status==='publish_ready'?`<button onclick="taskAction('${t.id}','publish',{start_mode:'immediate'})">立即发布</button>`:''}${t.status==='needs_review'?`<button onclick="taskAction('${t.id}','review',{published:true})">确认已发布并继续</button><button onclick="taskAction('${t.id}','review',{published:false})">确认未发布并重试</button>`:''}</div><pre>${esc((t.logs||[]).slice(-8).map(x=>x.message).join('\n'))}</pre></article>`).join('')||'<span class="muted">暂无任务。</span>'}
$('auto').onchange=timing;$('startMode').onchange=timing;$('create').onclick=createTask;$('scanCatalog').onclick=()=>loadCatalog(true).catch(e=>{$('message').className='message error';$('message').textContent=e.message});timing();Promise.all([loadCatalog(),loadTasks()]).catch(e=>{$('message').className='message error';$('message').textContent=e.message});setInterval(loadTasks,4000);</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                body = INDEX_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/opc-theme.css":
                send_theme_css(self)
            elif path == "/health":
                self.send_json(200, {"status": "ok"})
            elif path == "/api/catalog":
                refresh = parse_qs(parsed.query).get("refresh", [""])[0] == "1"
                payload = (
                    refresh_snapshot("auto-publish-pipeline", "catalog", catalog_payload)
                    if refresh
                    else cached_or_empty(
                        "auto-publish-pipeline",
                        "catalog",
                        lambda: {"scripts": [], "images": [], "profiles": [], "videos": [], "reusable_videos": [], "libraries": [], "countries": [], "warnings": [], "clone_root": str(CLONE_ROOT), "reference_root": str(REFERENCE_ROOT)},
                    )
                )
                self.send_json(200, payload)
            elif path == "/api/tasks":
                self.send_json(200, {"tasks": [public_task(task) for task in STORE.list()]})
            elif path == "/api/state":
                self.send_json(200, {"ok": True, "task_count": len(STORE.list()), "port": 10005})
            else:
                self.send_json(404, {"error": "not found"})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/tasks":
                self.send_json(201, public_task(create_task(payload)))
                return
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["api", "tasks"]:
                task_id, action = parts[2], parts[3]
                if action == "publish":
                    mode = str(payload.get("start_mode") or "immediate")
                    scheduled_at = float(payload.get("scheduled_at") or 0)
                    self.send_json(200, public_task(RUNNER.request_publish(task_id, mode, scheduled_at)))
                    return
                if action == "review":
                    self.send_json(200, public_task(RUNNER.resolve_publish_review(task_id, bool(payload.get("published")))))
                    return
                if action == "retry":
                    self.send_json(200, public_task(RUNNER.retry(task_id)))
                    return
            self.send_json(404, {"error": "not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def log_message(self, *_args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="10005 automatic publish pipeline Agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10005)
    args = parser.parse_args()
    RUNNER.start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"自动发布流水线: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    finally:
        RUNNER.stop()
        server.server_close()


if __name__ == "__main__":
    main()
