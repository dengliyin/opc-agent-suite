const $ = selector => document.querySelector(selector);
const HOOK_PAGE_SIZE = 10;
const state = {
  library: null,
  plan: null,
  taskStatus: "idle",
  hookPage: 1,
  selectedHookPaths: new Set(),
  reservedHookPaths: new Set()
};
const els = {
  summary: $("#summary"), product: $("#product"), market: $("#market"),
  includeCta: $("#includeCta"), randomDeduplication: $("#randomDeduplication"),
  useSubtitles: $("#useSubtitles"), subtitleSummary: $("#subtitleSummary"),
  deduplicationOptions: [...document.querySelectorAll("#deduplicationOptions input")],
  footageSummary: $("#footageSummary"), hookSummary: $("#hookSummary"),
  audioSummary: $("#audioSummary"), ctaSummary: $("#ctaSummary"),
  message: $("#message"), hookPreview: $("#hookPreview"),
  hookPreviewSummary: $("#hookPreviewSummary"),
  hookResultCount: $("#hookResultCount"), hookPager: $("#hookPager"),
  selectAllHooksButton: $("#selectAllHooksButton"),
  deleteSelectedHooksButton: $("#deleteSelectedHooksButton"),
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

function currentMarket() {
  return currentProduct()?.markets[els.market.value];
}

function automaticModel() {
  const market = currentMarket();
  for (const [name, model] of Object.entries(market?.models ?? {})) {
    if (model.hooks.some(hook => !hook.used_count && !state.reservedHookPaths.has(hook.path))) return name;
  }
  return "";
}

function selectedDeduplicationOptions() {
  return els.deduplicationOptions.filter(input => input.checked).map(input => input.value);
}

function hookItems(market) {
  return Object.entries(market?.models ?? {}).flatMap(([model, items]) => (
    items.hooks.map(hook => ({...hook, model}))
  ));
}

function hookAvailability(market) {
  const hooks = hookItems(market);
  const used = hooks.filter(hook => hook.used_count).length;
  const reserved = hooks.filter(
    hook => !hook.used_count && state.reservedHookPaths.has(hook.path)
  ).length;
  return {hooks, used, reserved, available: hooks.length - used - reserved};
}

function updateHookAvailabilitySummary() {
  const market = currentMarket();
  if (!market) {
    els.hookSummary.textContent = "选择国家后显示钩子素材数量";
    return;
  }
  const counts = hookAvailability(market);
  els.hookSummary.textContent = (
    `AI 钩子素材池　可用 ${counts.available} 条`
    + ` / 任务占用 ${counts.reserved} 条`
    + ` / 总数 ${counts.hooks.length} 条　·　本次可编排 ${counts.available} 条`
  );
}

function resetHookBrowser() {
  state.hookPage = 1;
  state.selectedHookPaths.clear();
}

function renderHookPager(pageCount) {
  if (pageCount <= 1) {
    els.hookPager.innerHTML = "";
    return;
  }
  els.hookPager.innerHTML = `
    <button type="button" data-hook-page="-1" ${state.hookPage <= 1 ? "disabled" : ""}>上一页</button>
    <span>第 ${state.hookPage} / ${pageCount} 页</span>
    <button type="button" data-hook-page="1" ${state.hookPage >= pageCount ? "disabled" : ""}>下一页</button>
  `;
}

function renderHookPreview() {
  const market = currentMarket();
  els.hookPreviewSummary.className = "hook-preview-summary";
  if (!els.product.value || !market) {
    state.selectedHookPaths.clear();
    els.hookPreviewSummary.textContent = "选择产品和国家后显示钩子视频";
    els.hookResultCount.textContent = "0 个结果";
    els.selectAllHooksButton.disabled = true;
    els.deleteSelectedHooksButton.disabled = true;
    els.hookPager.innerHTML = "";
    els.hookPreview.innerHTML = '<div class="empty">选择产品和国家后，可在这里预览对应的 AI 钩子素材。</div>';
    return;
  }
  const counts = hookAvailability(market);
  const hooks = counts.hooks;
  const knownPaths = new Set(hooks.map(hook => hook.path));
  for (const path of state.selectedHookPaths) {
    if (!knownPaths.has(path)) state.selectedHookPaths.delete(path);
  }
  els.hookPreviewSummary.textContent = (
    `${market.label} · 钩子 ${hooks.length} 条`
    + ` · 可用 ${counts.available} 条`
    + ` · 任务占用 ${counts.reserved} 条`
    + ` · 已使用 ${counts.used} 条`
  );
  const pageCount = Math.max(1, Math.ceil(hooks.length / HOOK_PAGE_SIZE));
  state.hookPage = Math.min(Math.max(1, state.hookPage), pageCount);
  const selectedCount = state.selectedHookPaths.size;
  els.hookResultCount.textContent = `${hooks.length} 个结果${selectedCount ? ` · 已选 ${selectedCount}` : ""} · 第 ${state.hookPage}/${pageCount} 页`;
  els.selectAllHooksButton.disabled = !hooks.length;
  els.deleteSelectedHooksButton.disabled = !selectedCount;
  if (!hooks.length) {
    els.hookPager.innerHTML = "";
    els.hookPreview.innerHTML = `<div class="empty">${esc(market.label)} 暂无 AI 钩子素材。</div>`;
    return;
  }
  const start = (state.hookPage - 1) * HOOK_PAGE_SIZE;
  const pageHooks = hooks.slice(start, start + HOOK_PAGE_SIZE);
  els.hookPreview.innerHTML = pageHooks.map(hook => {
    const reserved = !hook.used_count && state.reservedHookPaths.has(hook.path);
    const status = hook.used_count ? "已使用" : (reserved ? "任务占用" : "可用");
    const statusClass = hook.used_count ? "used" : (reserved ? "reserved" : "available");
    return `
    <article class="hook-video-card ${statusClass} ${state.selectedHookPaths.has(hook.path) ? "selected" : ""}">
      <div class="hook-status ${statusClass}">${status}</div>
      <label class="hook-select-control" title="勾选钩子">
        <input type="checkbox" data-hook-select-path="${esc(hook.path)}" ${state.selectedHookPaths.has(hook.path) ? "checked" : ""}>
      </label>
      <video
        src="/api/hook-video?path=${encodeURIComponent(hook.path)}"
        preload="metadata"
        muted
        playsinline
        controls
      ></video>
      <div class="hook-video-info">
        <strong title="${esc(hook.name)}">${esc(hook.name)}</strong>
        <div class="hook-chips">
          <span>${esc(market.label)}</span>
          <span class="model">${esc(hook.model)}</span>
          <span>${hook.used_count ? `已使用 ${hook.used_count} 次` : (reserved ? "当前任务已占用" : "尚未使用")}</span>
          <button class="hook-delete-button" type="button" data-hook-delete-path="${esc(hook.path)}">删除</button>
        </div>
      </div>
    </article>
  `;
  }).join("");
  renderHookPager(pageCount);
}

function updateDeduplicationMode() {
  els.deduplicationOptions.forEach(input => {
    if (els.randomDeduplication.checked) input.checked = false;
    input.disabled = els.randomDeduplication.checked;
  });
  updateReady();
}

function updateProduct() {
  resetHookBrowser();
  const product = currentProduct();
  const availableDisplay = product?.display.filter(item => item.used_count < 100).length ?? 0;
  const availableUsage = product?.usage.filter(item => item.used_count < 100).length ?? 0;
  els.footageSummary.textContent = product
    ? `实拍素材池　展示可用 ${availableDisplay}/${product.display.length} 条　｜　使用可用 ${availableUsage}/${product.usage.length} 条`
    : "选择产品后显示实拍素材数量";
  const markets = product ? Object.values(product.markets).map(
    item => ({name: item.label, path: item.code})
  ) : [];
  els.market.innerHTML = optionList(
    markets,
    markets.length ? "请选择国家" : "当前产品没有可识别国家的素材"
  );
  els.hookSummary.textContent = "选择国家后显示钩子素材数量";
  els.audioSummary.textContent = "选择国家后显示混剪音频数量";
  els.ctaSummary.textContent = "选择国家后显示 CTA 素材数量";
  els.subtitleSummary.textContent = "选择国家后检测本地字幕文件";
  els.includeCta.checked = false;
  els.includeCta.disabled = true;
  renderHookPreview();
  if (markets.length === 1) {
    els.market.value = markets[0].path;
    updateMarket();
    return;
  }
  updateReady();
}

function updateMarket() {
  resetHookBrowser();
  const market = currentMarket();
  const model = automaticModel();
  const ctaCount = market?.models[model]?.ctas.length ?? 0;
  updateHookAvailabilitySummary();
  els.audioSummary.textContent = market
    ? `混剪音频素材池　${market.audio.length} 条`
    : "选择国家后显示混剪音频数量";
  els.ctaSummary.textContent = market
    ? `AI CTA 素材池　${ctaCount} 条`
    : "选择国家后显示 CTA 素材数量";
  els.subtitleSummary.textContent = market
    ? `混剪音频 ${market.audio.length} 条　｜　本地字幕已匹配 ${market.subtitle_count} 条　｜　缺失 ${market.missing_subtitle_count} 条`
    : "选择国家后检测本地字幕文件";
  els.includeCta.checked = false;
  els.includeCta.disabled = ctaCount === 0;
  renderHookPreview();
  updateReady();
}

function updateReady() {
  const product = currentProduct();
  const market = currentMarket();
  const model = automaticModel();
  const counts = hookAvailability(market);
  const availableHookCount = counts.available;
  const hasDeduplication = els.randomDeduplication.checked || selectedDeduplicationOptions().length;
  const selected = (
    els.product.value && els.market.value && model && availableHookCount
    && market?.audio.length && hasDeduplication
  );
  els.planButton.disabled = !selected || state.taskStatus === "running";
  if (product) {
    els.message.className = "message";
    const ctaCount = model ? market.models[model].ctas.length : 0;
    els.message.textContent = market
      ? (
          state.taskStatus === "running"
            ? `当前渲染任务运行中，${counts.reserved} 条钩子已标记为任务占用，任务完成后才能重新编排`
            : hasDeduplication
            ? `${market.label} · 本次自动生成 ${availableHookCount} 条成片 · CTA ${ctaCount} 条（可选）`
            : "请至少选择一项去重处理，或选择随机去重"
        )
      : "请选择国家";
  }
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败");
  return data;
}

async function loadLibrary(preserveSelection = false) {
  const previousProduct = preserveSelection ? els.product.value : "";
  const previousMarket = preserveSelection ? els.market.value : "";
  els.refreshButton.disabled = true;
  try {
    const data = await api("/api/library");
    state.library = data;
    const s = data.summary;
    els.summary.textContent = `产品 ${s.products} · 国家 ${s.markets} · 可生产国家 ${s.ready_markets} · 可用钩子 ${s.available_hooks}/${s.hooks} · CTA ${s.ctas} · 音频 ${s.audio} · 展示可用 ${s.available_display}/${s.display} · 使用可用 ${s.available_usage}/${s.usage}`;
    els.product.innerHTML = optionList(data.products.map(item => ({name: item.name})), "请选择产品");
    const p = data.paths;
    els.paths.textContent = `AI片段归档：${p.delivery_archive_root}　其他输入：${p.audio_root} ｜ ${p.real_root}　工作区：${p.work_root}　成品：${p.output_root}`;
    if (previousProduct && data.products.some(item => item.name === previousProduct)) {
      els.product.value = previousProduct;
    }
    updateProduct();
    if (previousMarket && [...els.market.options].some(option => option.value === previousMarket)) {
      els.market.value = previousMarket;
      updateMarket();
    }
  } catch (error) {
    els.summary.textContent = `扫描失败：${error.message}`;
  } finally {
    els.refreshButton.disabled = false;
  }
}

async function deleteHookPaths(paths) {
  const hooksByPath = new Map(hookItems(currentMarket()).map(hook => [hook.path, hook]));
  const targets = [...new Set(paths)].filter(path => hooksByPath.has(path));
  if (!targets.length) return;
  const preview = targets.slice(0, 8).map(path => `- ${hooksByPath.get(path).name}`).join("\n");
  const more = targets.length > 8 ? `\n... 还有 ${targets.length - 8} 个` : "";
  const prompt = targets.length === 1
    ? `确认删除这个钩子视频？\n\n${hooksByPath.get(targets[0]).name}`
    : `确认批量删除 ${targets.length} 个钩子视频？\n删除后文件会从本地钩子目录移除。\n\n${preview}${more}`;
  if (!window.confirm(prompt)) return;
  els.selectAllHooksButton.disabled = true;
  els.deleteSelectedHooksButton.disabled = true;
  try {
    const result = await api("/api/hook-video/delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({hook_paths: targets})
    });
    state.plan = null;
    state.selectedHookPaths.clear();
    els.renderButton.disabled = true;
    await loadLibrary(true);
    els.message.className = "message";
    els.message.textContent = `已删除 ${result.deleted_count} 个钩子视频。`;
  } catch (error) {
    renderHookPreview();
    els.hookPreviewSummary.classList.add("error");
    els.hookPreviewSummary.textContent = `删除失败：${error.message}`;
  }
}

function deleteSelectedHooks() {
  return deleteHookPaths([...state.selectedHookPaths]);
}

async function createPlan() {
  els.planButton.disabled = true;
  els.renderButton.disabled = true;
  els.message.className = "message";
  els.message.textContent = "正在分析素材并生成时间线…";
  const payload = {
    product: els.product.value, market: els.market.value, model: automaticModel(),
    include_cta: els.includeCta.checked,
    use_subtitles: els.useSubtitles.checked,
    random_deduplication: els.randomDeduplication.checked,
    deduplication_options: selectedDeduplicationOptions()
  };
  try {
    const data = await api("/api/plan", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
    });
    state.plan = data.plan;
    els.renderButton.disabled = false;
    els.message.textContent = `编排方案已生成，共 ${data.plan.variants.length} 条成片；确认后可开始渲染。`;
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
    const previousStatus = state.taskStatus;
    state.taskStatus = task.status;
    state.reservedHookPaths = new Set(task.reserved_hook_paths ?? []);
    els.taskStatus.textContent = ({idle: "空闲", running: "渲染中", completed: "已完成", failed: "失败"})[task.status] || task.status;
    els.taskMessage.textContent = task.message || "";
    els.logs.textContent = task.logs.length ? task.logs.join("\n") : "暂无运行日志";
    els.renderButton.disabled = task.status === "running" || !state.plan;
    updateHookAvailabilitySummary();
    renderHookPreview();
    updateReady();
    if (task.status === "completed" && previousStatus !== "completed") {
      state.plan = null;
      els.renderButton.disabled = true;
      await loadLibrary(true);
      await loadOutputs();
    } else if (task.status === "failed" && previousStatus !== "failed") {
      await loadLibrary(true);
    }
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
els.market.addEventListener("change", updateMarket);
els.includeCta.addEventListener("change", updateReady);
els.randomDeduplication.addEventListener("change", updateDeduplicationMode);
els.deduplicationOptions.forEach(input => input.addEventListener("change", updateReady));
els.useSubtitles.addEventListener("change", updateReady);
els.refreshButton.addEventListener("click", () => loadLibrary(true));
els.selectAllHooksButton.addEventListener("click", () => {
  hookItems(currentMarket()).forEach(hook => state.selectedHookPaths.add(hook.path));
  renderHookPreview();
});
els.deleteSelectedHooksButton.addEventListener("click", deleteSelectedHooks);
els.hookPreview.addEventListener("change", event => {
  const input = event.target.closest("[data-hook-select-path]");
  if (!input) return;
  if (input.checked) state.selectedHookPaths.add(input.dataset.hookSelectPath);
  else state.selectedHookPaths.delete(input.dataset.hookSelectPath);
  renderHookPreview();
});
els.hookPreview.addEventListener("click", event => {
  const button = event.target.closest("[data-hook-delete-path]");
  if (!button) return;
  deleteHookPaths([button.dataset.hookDeletePath]);
});
els.hookPager.addEventListener("click", event => {
  const button = event.target.closest("[data-hook-page]");
  if (!button || button.disabled) return;
  state.hookPage += Number(button.dataset.hookPage);
  renderHookPreview();
});
els.planButton.addEventListener("click", createPlan);
els.renderButton.addEventListener("click", renderCurrentPlan);
loadLibrary();
loadOutputs();
pollTask();
updateDeduplicationMode();
setInterval(pollTask, 2000);
