const $ = selector => document.querySelector(selector);
const state = { library: null, plan: null, taskStatus: "idle" };
const els = {
  summary: $("#summary"), product: $("#product"), model: $("#model"), hook: $("#hook"),
  audio: $("#audio"), cta: $("#cta"), count: $("#count"), seed: $("#seed"),
  minClip: $("#minClip"), maxClip: $("#maxClip"), originality: $("#originality"),
  message: $("#message"), plan: $("#plan"), planEmpty: $("#planEmpty"),
  planButton: $("#planButton"), renderButton: $("#renderButton"),
  refreshButton: $("#refreshButton"), taskStatus: $("#taskStatus"),
  taskMessage: $("#taskMessage"), logs: $("#logs"), outputs: $("#outputs"), paths: $("#paths")
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]
  ));
}

function optionList(items, placeholder) {
  return `<option value="">${esc(placeholder)}</option>` + items.map(
    item => `<option value="${esc(item.path ?? item.name)}">${esc(item.name)}</option>`
  ).join("");
}

function currentProduct() {
  return state.library?.products.find(item => item.name === els.product.value);
}

function updateProduct() {
  const product = currentProduct();
  const models = product ? Object.keys(product.models).map(name => ({name})) : [];
  els.model.innerHTML = optionList(
    models,
    models.length ? "请选择已生成片段来源" : "未找到9995生成的钩子/CTA视频"
  );
  els.audio.innerHTML = optionList(
    product?.audio ?? [],
    product?.audio.length ? "请选择产品介绍音频" : "未找到产品介绍音频"
  );
  els.hook.innerHTML = optionList([], models.length ? "请先选择片段来源" : "9995尚未产出钩子视频");
  els.cta.innerHTML = optionList([], models.length ? "请先选择片段来源" : "9995尚未产出CTA视频");
  if (models.length === 1) {
    els.model.value = models[0].name;
    updateModel();
    return;
  }
  updateReady();
}

function updateModel() {
  const model = currentProduct()?.models[els.model.value];
  const hooks = model?.hooks ?? [];
  const ctas = model?.ctas ?? [];
  els.hook.innerHTML = optionList(hooks, hooks.length ? "请选择钩子视频" : "该来源尚无钩子视频");
  els.cta.innerHTML = optionList(ctas, ctas.length ? "请选择 CTA 视频" : "该来源尚无CTA视频");
  if (hooks.length === 1) els.hook.value = hooks[0].path;
  if (ctas.length === 1) els.cta.value = ctas[0].path;
  updateReady();
}

function updateReady() {
  const product = currentProduct();
  const selected = els.product.value && els.model.value && els.hook.value && els.audio.value && els.cta.value;
  els.planButton.disabled = !selected || state.taskStatus === "running";
  if (product) {
    els.message.className = "message";
    const modelCount = Object.keys(product.models).length;
    els.message.textContent = modelCount
      ? `已生成片段来源 ${modelCount} 个 · 实拍池：展示 ${product.display.length} 条 · 使用 ${product.usage.length} 条`
      : "当前产品还没有钩子/CTA视频。请先在9999完成适配，再到9995生成混剪钩子与CTA片段。";
  }
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败");
  return data;
}

async function loadLibrary() {
  els.refreshButton.disabled = true;
  try {
    const data = await api("/api/library");
    state.library = data;
    const s = data.summary;
    els.summary.textContent = `产品 ${s.products} · 可直接生产 ${s.ready_products} · 钩子 ${s.hooks} · CTA ${s.ctas} · 音频 ${s.audio} · 展示 ${s.display} · 使用 ${s.usage}`;
    els.product.innerHTML = optionList(data.products.map(item => ({name: item.name})), "请选择产品");
    const p = data.paths;
    els.paths.textContent = `输入：${p.ai_clip_root} ｜ ${p.audio_root} ｜ ${p.real_root}　工作区：${p.work_root}　成品：${p.output_root}`;
    updateProduct();
  } catch (error) {
    els.summary.textContent = `扫描失败：${error.message}`;
  } finally {
    els.refreshButton.disabled = false;
  }
}

function renderPlan(plan) {
  els.planEmpty.hidden = true;
  els.plan.innerHTML = plan.variants.map(variant => `
    <article class="variant">
      <div class="variant-head">
        <strong>变体 ${variant.index}</strong>
        <span><span class="badge">${variant.total_duration.toFixed(2)} 秒</span> · seed ${variant.seed}</span>
      </div>
      <table class="timeline">
        <thead><tr><th>顺序</th><th>类型</th><th>素材</th><th>时长</th></tr></thead>
        <tbody>${variant.segments.map((segment, index) => `
          <tr>
            <td>${index + 1}</td><td>${esc(segment.role)}</td><td>${esc(segment.name)}</td>
            <td>${Number(segment.duration).toFixed(2)}s${segment.technical_tail_trimmed ? " · 已裁技术黑屏" : ""}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </article>`).join("");
}

async function createPlan() {
  els.planButton.disabled = true;
  els.renderButton.disabled = true;
  els.message.className = "message";
  els.message.textContent = "正在分析素材并生成时间线…";
  const payload = {
    product: els.product.value, model: els.model.value, hook_path: els.hook.value,
    audio_path: els.audio.value, cta_path: els.cta.value, count: Number(els.count.value),
    min_clip: Number(els.minClip.value), max_clip: Number(els.maxClip.value),
    originality: els.originality.value, seed: els.seed.value ? Number(els.seed.value) : null
  };
  try {
    const data = await api("/api/plan", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
    });
    state.plan = data.plan;
    renderPlan(data.plan);
    els.renderButton.disabled = false;
    els.message.textContent = `方案已保存：${data.plan.plan_path}`;
  } catch (error) {
    els.message.className = "message error";
    els.message.textContent = error.message;
  } finally {
    updateReady();
  }
}

async function renderCurrentPlan() {
  if (!state.plan) return;
  els.renderButton.disabled = true;
  try {
    await api("/api/render", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({plan_path: state.plan.plan_path})
    });
    await pollTask();
  } catch (error) {
    els.message.className = "message error";
    els.message.textContent = error.message;
  }
}

async function pollTask() {
  try {
    const data = await api("/api/task");
    const task = data.task;
    state.taskStatus = task.status;
    els.taskStatus.textContent = ({idle: "空闲", running: "渲染中", completed: "已完成", failed: "失败"})[task.status] || task.status;
    els.taskMessage.textContent = task.message || "";
    els.logs.textContent = task.logs.length ? task.logs.join("\n") : "暂无运行日志";
    els.renderButton.disabled = task.status === "running" || !state.plan;
    updateReady();
    if (task.status === "completed") await loadOutputs();
  } catch (error) {
    els.taskMessage.textContent = error.message;
  }
}

async function loadOutputs() {
  try {
    const data = await api("/api/outputs");
    els.outputs.className = data.outputs.length ? "" : "empty";
    els.outputs.innerHTML = data.outputs.length ? data.outputs.map(item => `
      <div class="output"><div><strong>${esc(item.name)}</strong><br><small>${esc(item.path)}</small></div><small>${esc(item.modified)}</small></div>
    `).join("") : "暂无 AI＋实拍混剪成片";
  } catch (error) {
    els.outputs.textContent = error.message;
  }
}

els.product.addEventListener("change", updateProduct);
els.model.addEventListener("change", updateModel);
[els.hook, els.audio, els.cta].forEach(element => element.addEventListener("change", updateReady));
els.refreshButton.addEventListener("click", loadLibrary);
els.planButton.addEventListener("click", createPlan);
els.renderButton.addEventListener("click", renderCurrentPlan);
loadLibrary();
loadOutputs();
pollTask();
setInterval(pollTask, 2000);
