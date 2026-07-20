#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT.parent
HOST = os.environ.get("KESAI_APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("KESAI_APP_PORT", "8888"))
def service_url(env_name: str, default: str) -> str:
    return os.environ.get(env_name, default)


def service_port(url: str, fallback: int) -> int:
    try:
        return int(urlparse(url).port or fallback)
    except (TypeError, ValueError):
        return fallback


def agent_python(agent_dir: Path) -> str:
    candidate = agent_dir / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else "python3"


VIDEO_COLLECTION_DIR = WORKSPACE_ROOT / "Video-Collection"
SCRIPT_ANALYSIS_DIR = WORKSPACE_ROOT / "Script-Analysis"
SCRIPT_GENERATION_DIR = WORKSPACE_ROOT / "Script-Generation"
SCRIPT_ADAPTATION_DIR = WORKSPACE_ROOT / "Script-Adaptation"
SCRIPT_ADAPTATION_APP_DIR = SCRIPT_ADAPTATION_DIR / "software" / "Script-Adaptation-app"
VIDEO_GENERATION_DIR = WORKSPACE_ROOT / "Video-Generation"
FINISHED_VIDEO_MANAGER_DIR = WORKSPACE_ROOT / "Finished-Video-Manager"
PRODUCT_SCRIPT_REWRITE_DIR = WORKSPACE_ROOT / "Product-Script-Rewrite"
VIDEO_ASSEMBLY_DIR = WORKSPACE_ROOT / "Video-Assembly-hd"


def build_services() -> dict[str, dict]:
    urls = {
        "collect": service_url("OPC_HOT_VIDEO_AGENT_URL", "http://127.0.0.1:9991/"),
        "analyze": service_url("OPC_VIDEO_TEARDOWN_AGENT_URL", "http://127.0.0.1:9992/"),
        "script": service_url("OPC_SCRIPT_PRODUCTION_AGENT_URL", "http://127.0.0.1:9993/"),
        "adapt": service_url("OPC_SCRIPT_ADAPTATION_AGENT_URL", "http://127.0.0.1:9994/"),
        "assemble": service_url("OPC_VIDEO_OUTPUT_AGENT_URL", "http://127.0.0.1:9995/"),
        "finished": service_url("OPC_FINISHED_VIDEO_MANAGER_URL", "http://127.0.0.1:9996/"),
        "rewrite": service_url("OPC_PRODUCT_SCRIPT_REWRITE_URL", "http://127.0.0.1:9997/"),
        "compose": service_url("OPC_VIDEO_ASSEMBLY_AGENT_URL", "http://127.0.0.1:9998/"),
    }
    services = {
        "collect": {
            "label": "视频采集",
            "description": "采集 FastMoss 商品关联视频并下载 TikTok 素材",
            "url": urls["collect"],
            "cwd": VIDEO_COLLECTION_DIR,
            "command": [agent_python(VIDEO_COLLECTION_DIR), "-m", "hot_video_agent", "web", "--host", "127.0.0.1", "--port", str(service_port(urls["collect"], 9991))],
        },
        "analyze": {
            "label": "脚本解析",
            "description": "把本地短视频拆解成结构化 Markdown",
            "url": urls["analyze"],
            "cwd": SCRIPT_ANALYSIS_DIR,
            "command": [agent_python(SCRIPT_ANALYSIS_DIR), str(SCRIPT_ANALYSIS_DIR / "scripts" / "web_app.py"), "--host", "127.0.0.1", "--port", str(service_port(urls["analyze"], 9992))],
        },
        "script": {
            "label": "脚本产出",
            "description": "根据产品资料和爆款参考生成带货脚本",
            "url": urls["script"],
            "cwd": SCRIPT_GENERATION_DIR,
            "command": [agent_python(SCRIPT_GENERATION_DIR), "-m", "opc_engine.features.script_generation.script_generation_agent_web", "--port", str(service_port(urls["script"], 9993))],
        },
        "adapt": {
            "label": "脚本适配",
            "description": "生成视频模型需要的分镜、图片提示词和任务表",
            "url": urls["adapt"],
            "cwd": SCRIPT_ADAPTATION_DIR,
            "launch_cwd": SCRIPT_ADAPTATION_APP_DIR,
            "command": [agent_python(SCRIPT_ADAPTATION_DIR), "-m", "opc_engine.features.script_adaptation.script_adaptation_agent_web", "--port", str(service_port(urls["adapt"], 9994))],
        },
        "assemble": {
            "label": "视频产出",
            "description": "生成人物图、故事版和视频片段",
            "url": urls["assemble"],
            "cwd": VIDEO_GENERATION_DIR,
            "command": [agent_python(VIDEO_GENERATION_DIR), "-m", "uvicorn", "agent.app:app", "--host", "127.0.0.1", "--port", str(service_port(urls["assemble"], 9995))],
        },
        "finished": {
            "label": "成品管理",
            "description": "查看成品、维护发布记录并处理 TikTok 发布",
            "url": urls["finished"],
            "cwd": FINISHED_VIDEO_MANAGER_DIR,
            "command": [agent_python(FINISHED_VIDEO_MANAGER_DIR), "-m", "finished_video_manager.web", "web", "--host", "127.0.0.1", "--port", str(service_port(urls["finished"], 9996))],
        },
        "rewrite": {
            "label": "产品脚本改写",
            "description": "把爆款脚本改写成目标产品版本",
            "url": urls["rewrite"],
            "cwd": PRODUCT_SCRIPT_REWRITE_DIR,
            "command": [agent_python(PRODUCT_SCRIPT_REWRITE_DIR), "-m", "product_script_rewrite.web", "--port", str(service_port(urls["rewrite"], 9997))],
        },
        "compose": {
            "label": "片段合成",
            "description": "离线拼接片段、校验成品并清理已用素材",
            "url": urls["compose"],
            "cwd": VIDEO_ASSEMBLY_DIR,
            "command": [agent_python(VIDEO_ASSEMBLY_DIR), str(VIDEO_ASSEMBLY_DIR / "app" / "server.py"), "--host", "127.0.0.1", "--port", str(service_port(urls["compose"], 9998))],
        },
    }
    for service_id, service in services.items():
        service["launch_agent_label"] = f"com.kesai.opc-agent.{service_id}"
    return services


SERVICES = build_services()


def service_running(service: dict) -> bool:
    try:
        request = urllib.request.Request(service["url"], method="GET")
        with urllib.request.urlopen(request, timeout=1.2) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def service_status(service_id: str) -> dict:
    service = SERVICES[service_id]
    running = service_running(service)
    return {
        "id": service_id,
        "label": service["label"],
        "description": service["description"],
        "url": service["url"],
        "running": running,
        "process_running": running,
    }


def services_payload() -> dict:
    return {"services": [service_status(service_id) for service_id in SERVICES]}


def start_service(service_id: str) -> dict:
    if service_id not in SERVICES:
        raise ValueError("未知 Agent 服务")
    service = SERVICES[service_id]
    if service_running(service):
        return service_status(service_id) | {"started": False, "message": "服务已运行"}

    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{service['launch_agent_label']}"
    registration = subprocess.run(
        ["launchctl", "print", target],
        capture_output=True,
        text=True,
        check=False,
    )
    if registration.returncode:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{service['launch_agent_label']}.plist"
        if not plist_path.is_file():
            raise RuntimeError(f"Agent LaunchAgent 配置不存在：{plist_path}")
        bootstrap = subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if bootstrap.returncode:
            detail = bootstrap.stderr.strip() or bootstrap.stdout.strip() or "launchctl bootstrap 失败"
            raise RuntimeError(f"Agent LaunchAgent 注册失败：{detail}")

    result = subprocess.run(
        ["launchctl", "kickstart", "-k", target],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "launchctl kickstart 失败"
        raise RuntimeError(f"Agent LaunchAgent 未安装或无法启动：{detail}")
    return service_status(service_id) | {"started": True, "message": "已发送启动命令"}


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OPC 内容量化增长引擎</title>
<style>
:root{color-scheme:dark;--bg:#0b0d10;--panel:#15191f;--line:#29313b;--text:#f3f5f7;--muted:#98a2ad;--green:#66d19e;--blue:#70a7ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#18202b 0,#0b0d10 42%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:auto;padding:64px 24px 80px}header{display:flex;justify-content:space-between;gap:32px;align-items:end;margin-bottom:36px}h1{font-size:clamp(32px,5vw,58px);line-height:1.03;margin:0 0 14px;letter-spacing:-.04em}header p{max-width:700px;color:var(--muted);font-size:17px;line-height:1.7;margin:0}.summary{white-space:nowrap;color:var(--muted);padding:10px 14px;border:1px solid var(--line);border-radius:999px;background:#11151a}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}.card{display:flex;flex-direction:column;min-height:220px;padding:22px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#181d24,#11151a);box-shadow:0 16px 48px #0005}.top{display:flex;justify-content:space-between;gap:16px;align-items:center}.step{font-size:12px;color:var(--blue);letter-spacing:.12em}.status{font-size:12px;color:var(--muted)}.status::before{content:"";display:inline-block;width:8px;height:8px;margin-right:7px;border-radius:50%;background:#59636e}.status.on{color:var(--green)}.status.on::before{background:var(--green);box-shadow:0 0 12px var(--green)}h2{font-size:22px;margin:28px 0 8px}.desc{color:var(--muted);line-height:1.55;margin:0 0 24px;flex:1}.actions{display:flex;gap:9px}button,a.button{appearance:none;border:1px solid var(--line);background:#202733;color:var(--text);padding:10px 14px;border-radius:10px;font:inherit;text-decoration:none;cursor:pointer}button.primary{background:#e7edf5;color:#11161d;border-color:#e7edf5}button:disabled{opacity:.45;cursor:wait}.note{margin-top:30px;color:var(--muted);font-size:13px;text-align:center}
@media(max-width:700px){main{padding-top:38px}header{align-items:start;flex-direction:column}.summary{white-space:normal}}
</style>
</head>
<body><main><header><div><h1>OPC 内容量化增长引擎</h1><p>总控制台只负责 8 个独立 Agent 的启动、检测与导航。业务参数、模型调用和产物管理均在对应 Agent 中完成。</p></div><div class="summary" id="summary">正在检测服务…</div></header><section class="grid" id="grid"></section><p class="note">控制台端口 8888 · Agent 端口 9991–9998</p></main>
<script>
const grid=document.querySelector('#grid'),summary=document.querySelector('#summary');
let services=[];
const startingServices=new Set();
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function render(){grid.innerHTML=services.map((s,i)=>{const starting=startingServices.has(s.id)&&!s.running;return `<article class="card"><div class="top"><span class="step">STEP ${String(i+1).padStart(2,'0')}</span><span class="status ${s.running?'on':''}">${s.running?'运行中':starting?'启动中…':'未启动'}</span></div><h2>${esc(s.label)}</h2><p class="desc">${esc(s.description)}</p><div class="actions"><button class="primary" onclick="startService('${esc(s.id)}')" ${s.running||starting?'disabled':''}>${s.running?'已启动':starting?'启动中…':'启动'}</button><a class="button" href="${esc(s.url)}" target="_blank" rel="noreferrer">打开</a></div></article>`}).join('');const count=services.filter(s=>s.running).length;summary.textContent=`${count} / ${services.length} 个 Agent 运行中`;}
async function refresh(){try{const r=await fetch('/api/agent-services');const data=await r.json();services=data.services;render()}catch(e){summary.textContent='服务状态读取失败'}}
async function waitForService(id){const deadline=Date.now()+30000;while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,1000));await refresh();if(services.some(s=>s.id===id&&s.running))return true}return false}
async function startService(id){startingServices.add(id);render();try{const r=await fetch('/api/agent-services/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});const data=await r.json();if(!r.ok)throw new Error(data.error||'启动失败');if(!await waitForService(id))throw new Error('Agent 启动超时，请检查对应运行日志')}catch(e){alert(e.message)}finally{startingServices.delete(id);await refresh()}}
refresh();setInterval(refresh,4000);
</script></body></html>"""


ROUTE_TO_SERVICE = {
    "/collect": "collect",
    "/analyze": "analyze",
    "/script": "script",
    "/adapt": "adapt",
    "/assemble": "assemble",
    "/finished": "finished",
    "/rewrite": "rewrite",
    "/compose": "compose",
}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path in ROUTE_TO_SERVICE:
            self.send_response(302)
            self.send_header("Location", SERVICES[ROUTE_TO_SERVICE[path]]["url"])
            self.end_headers()
        elif path in {"/api/agent-services", "/api/status"}:
            self.send_json(200, services_payload())
        elif path == "/health":
            self.send_json(200, {"ok": True, "service": "OPC-Console"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/agent-services/start":
                payload = self.read_json()
                self.send_json(200, start_service(str(payload.get("id", ""))))
            else:
                self.send_json(404, {"error": "Not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def log_message(self, *_args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"OPC 内容量化增长引擎已启动: {url}", flush=True)
    if os.environ.get("KESAI_APP_NO_OPEN") != "1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
