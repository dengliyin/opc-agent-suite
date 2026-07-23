const state = {
  config: null,
  catalog: null,
  selectedIndex: 0,
  selectedScriptPaths: new Set(),
  jobs: [],
  globalJobs: {},
  activeJobId: null,
  lastCatalogRefreshAt: 0,
  lastGlobalStatusAt: 0,
  lastTerminalCatalogJobKey: "",
  pollingJobs: false,
  showArchived: false,
  expansionMode: "",
  expandedProducts: new Set(),
  selectedReferenceByProduct: new Map(),
};

const API_BASE = window.AGENT_API_BASE || "/api";
const PROVIDERS = [
  { key: "omni", label: "Omni" },
  { key: "grok", label: "Grok" },
];
const DEFAULT_SCRIPT_CONCURRENCY_CHOICES = [1, 2, 3, 5, 8, 12, 16, 20];

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_) {
      // Keep the browser status text.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function refreshAll() {
  const [config, catalog, jobs, globalJobs] = await Promise.all([
    api("/config"),
    api("/catalog"),
    api("/jobs"),
    loadGlobalJobs(),
  ]);
  state.config = config;
  state.catalog = catalog;
  state.jobs = jobs.jobs || [];
  state.globalJobs = globalJobs;
  state.lastTerminalCatalogJobKey = terminalJobKey(state.jobs[0]);
  state.lastCatalogRefreshAt = Date.now();
  state.lastGlobalStatusAt = Date.now();
  render();
}

function render() {
  renderConfig();
  renderGlobalStatus();
  renderCatalog();
  renderSegments();
  renderJobs();
}

function renderConfig() {
  if (!state.config) return;
  renderConcurrencySelect();
  const ready = state.config.provider_ready ? `${state.config.provider_label} 已配置` : `${state.config.provider_label} 未配置`;
  const concurrency = ` · 脚本并发 ${selectedScriptConcurrency()}`;
  $("#configLine").textContent = `${ready} · 图片 ${state.config.image_display_summary} · 视频 ${state.config.video_display_summary}${concurrency}`;
}

function concurrencyStorageKey() {
  return `fragment-output-agent:${API_BASE}:scriptConcurrency`;
}

function concurrencyChoices() {
  const raw = state.config?.script_concurrency_choices || DEFAULT_SCRIPT_CONCURRENCY_CHOICES;
  const values = raw.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item >= 1);
  return [...new Set(values)].sort((a, b) => a - b);
}

function savedScriptConcurrency() {
  try {
    const value = Number(localStorage.getItem(concurrencyStorageKey()));
    return Number.isFinite(value) && value >= 1 ? value : null;
  } catch (_) {
    return null;
  }
}

function storeScriptConcurrency(value) {
  try {
    localStorage.setItem(concurrencyStorageKey(), String(value));
  } catch (_) {
    // The selected value is still used for this page session.
  }
}

function selectedScriptConcurrency() {
  const select = $("#concurrencySelect");
  const selected = Number(select?.value);
  if (Number.isFinite(selected) && selected >= 1) return selected;
  const active = activeRunningJob();
  if (active?.script_concurrency) return Number(active.script_concurrency);
  return Number(state.config?.script_concurrency || DEFAULT_SCRIPT_CONCURRENCY_CHOICES[2]);
}

function renderConcurrencySelect() {
  const select = $("#concurrencySelect");
  if (!select) return;
  const choices = concurrencyChoices();
  const choiceKey = choices.join(",");
  const active = activeRunningJob();
  const preferred = Number(active?.script_concurrency || select.value || savedScriptConcurrency() || state.config?.script_concurrency || choices[0]);
  const selected = choices.includes(preferred) ? preferred : choices[0];
  if (select.dataset.choiceKey !== choiceKey) {
    select.innerHTML = choices.map((value) => `<option value="${value}">${value}</option>`).join("");
    select.dataset.choiceKey = choiceKey;
  }
  select.value = String(selected);
  select.onchange = handleConcurrencyChange;
}

async function handleConcurrencyChange() {
  const value = selectedScriptConcurrency();
  storeScriptConcurrency(value);
  const active = activeRunningJob();
  if (!active) {
    renderConfig();
    return;
  }

  active.script_concurrency = value;
  renderConfig();
  renderJobs();
  try {
    const updated = await api("/jobs/concurrency", {
      method: "POST",
      body: JSON.stringify({ job_id: active.id, script_concurrency: value }),
    });
    state.jobs = state.jobs.map((job) => (job.id === updated.id ? updated : job));
    render();
  } catch (error) {
    alert(`调整并发失败：${error.message}`);
    await pollJobs();
  }
}

async function loadGlobalJobs() {
  const result = {};
  await Promise.all(
    PROVIDERS.map(async (provider) => {
      try {
        const response = await fetch(`/${provider.key}/api/jobs`, { headers: { "Content-Type": "application/json" } });
        if (!response.ok) throw new Error(response.statusText);
        const body = await response.json();
        result[provider.key] = { jobs: body.jobs || [], ok: true };
      } catch (error) {
        result[provider.key] = { jobs: [], ok: false, error: error.message };
      }
    }),
  );
  return result;
}

function renderGlobalStatus() {
  const target = $("#globalAgentStatus");
  if (!target) return;
  const updatedAt = state.lastGlobalStatusAt ? `更新 ${new Date(state.lastGlobalStatusAt).toLocaleTimeString("zh-CN", { hour12: false })}` : "更新 --";
  const chips = PROVIDERS.map((provider) => {
    const data = state.globalJobs?.[provider.key] || { jobs: [], ok: true };
    const job = activeOrLatestJob(data.jobs || []);
    if (!data.ok) {
      return `<span class="agent-status-chip error">${provider.label} 状态读取失败</span>`;
    }
    if (!job) {
      return `<span class="agent-status-chip idle">${provider.label} 空闲</span>`;
    }
    const percent = job.total ? Math.round(((job.done || 0) / job.total) * 100) : 0;
    const isActive = ["running", "queued"].includes(job.status);
    const className = isActive ? "running" : job.status === "failed" ? "error" : job.status === "canceled" ? "warn" : "idle";
    const errorText = job.errors?.length ? ` · ${job.errors.length}错` : "";
    return `<span class="agent-status-chip ${className}">${provider.label} ${statusLabel(job.status)} · ${stageLabel(job.stage)} · ${job.done || 0}/${job.total || 0} · ${percent}%${errorText}</span>`;
  }).join("");
  target.innerHTML = `${chips}<span class="agent-status-time">${updatedAt}</span>`;
}

function renderCatalog() {
  const scripts = state.catalog?.scripts || [];
  syncSelectedScriptPaths(scripts);
  syncProductReferenceSelections(scripts);
  const visibleScripts = visibleCatalogScripts(scripts);
  ensureSelectedScriptVisible(scripts, visibleScripts);
  ensureInitialExpansion(visibleScripts);
  renderArchiveControls();
  const runningContexts = currentJobContexts();
  const summary = state.catalog?.summary;
  if (summary) {
    const exported = Number(summary.exported_scripts || 0);
    const complete = Number(summary.complete_scripts || 0);
    const exportedText = exported ? ` · 已导出 ${exported}` : "";
    const modeText = state.showArchived ? "归档" : "任务";
    $("#summaryLine").textContent = `${summary.products} 产品 · ${summary.scripts} 脚本 · ${summary.segments} 片段 · 完整 ${complete}${exportedText} · ${modeText}已选 ${state.selectedScriptPaths.size}`;
  }

  const list = $("#scriptList");
  const previousScrollTop = list.scrollTop;
  const feedbackJob = activeOrLatestJob(state.jobs || []);
  const scriptStatuses = feedbackJob?.script_statuses || {};
  if (!visibleScripts.length) {
    list.innerHTML = `<div class="empty-state">${state.showArchived ? "没有已导出的归档脚本" : "没有可执行脚本"}</div>`;
    return;
  }

  list.innerHTML = groupVisibleScripts(visibleScripts)
    .map((product) => renderProductGroup(product, scripts, runningContexts, scriptStatuses))
    .join("");
  list.scrollTop = previousScrollTop;

  $$(".product-toggle").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleProductExpansion(button.dataset.productName || "");
      render();
    });
  });

  $$(".product-select").forEach((checkbox) => {
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => {
      const productName = checkbox.dataset.productName || "";
      const paths = visibleScripts.filter((script) => script.product_name === productName).map((script) => script.md_path);
      setPathSelection(paths, checkbox.checked);
      render();
    });
  });

  $$(".product-reference-select").forEach((select) => {
    select.addEventListener("change", () => {
      const productName = select.dataset.productName || "";
      if (select.value) state.selectedReferenceByProduct.set(productName, select.value);
      else state.selectedReferenceByProduct.delete(productName);
      render();
    });
  });

  $$(".script-item").forEach((item) => {
    item.addEventListener("click", () => {
      state.selectedIndex = Number(item.dataset.index);
      render();
    });
    item.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      state.selectedIndex = Number(item.dataset.index);
      render();
    });
  });

  $$(".script-select").forEach((checkbox) => {
    checkbox.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    checkbox.addEventListener("change", () => {
      const script = (state.catalog?.scripts || []).find((item) => item.md_path === checkbox.dataset.path);
      if (!isScriptSelectable(script)) {
        checkbox.checked = false;
        state.selectedScriptPaths.delete(checkbox.dataset.path);
        return;
      }
      if (checkbox.checked) {
        state.selectedScriptPaths.add(checkbox.dataset.path);
      } else {
        state.selectedScriptPaths.delete(checkbox.dataset.path);
      }
      render();
    });
  });
}

function renderProductGroup(product, scripts, runningContexts, scriptStatuses) {
  const paths = product.scripts.map((script) => script.md_path);
  const checked = paths.length > 0 && paths.every((path) => state.selectedScriptPaths.has(path));
  const selected = paths.filter((path) => state.selectedScriptPaths.has(path)).length;
  const expanded = isProductExpanded(product.name);
  const references = productReferenceOptions(product);
  const selectedReference = state.selectedReferenceByProduct.get(product.name) || "";
  const selectedOption = references.find((item) => item.path === selectedReference);
  const referenceSummary = !references.length
    ? "缺产品参考图"
    : references.length === 1
      ? `参考图：${references[0].label}（自动）`
      : selectedOption
        ? `SKU：${selectedOption.label}`
        : `${references.length} 个 SKU · 待选择`;
  return `
    <div class="product-group ${expanded ? "expanded" : "collapsed"}">
      <div class="product-group-head">
        <button class="collapse-toggle product-toggle" type="button" data-product-name="${escapeHtml(product.name)}" aria-expanded="${expanded ? "true" : "false"}" aria-label="${expanded ? "收起产品" : "展开产品"}">${expanded ? "▾" : "▸"}</button>
        <label class="miniCheck" title="选择该产品下当前视图的全部脚本">
          <input class="product-select" type="checkbox" data-product-name="${escapeHtml(product.name)}" ${checked ? "checked" : ""} />
        </label>
        <div>
          <strong>${escapeHtml(product.name)}</strong>
          <span>${product.scripts.length} 脚本 · ${product.segments} 片段 · 已选 ${selected}<br>${escapeHtml(referenceSummary)}</span>
        </div>
      </div>
      ${expanded ? renderProductReferencePicker(product.name, references, selectedReference) : ""}
      ${expanded ? `<div class="product-scripts">${product.scripts.map((script) => renderScriptCard(script, scripts, runningContexts, scriptStatuses)).join("")}</div>` : ""}
    </div>
  `;
}

function renderScriptCard(script, scripts, runningContexts, scriptStatuses) {
  const index = scripts.findIndex((item) => item.md_path === script.md_path);
  const segments = script.segments || [];
  const characters = segments.filter((segment) => segment.character_exists).length;
  const staleCharacters = segments.filter((segment) => segment.character_stale).length;
  const storyboards = segments.filter((segment) => segment.storyboard_exists).length;
  const staleStoryboards = segments.filter((segment) => segment.storyboard_stale).length;
  const videos = segments.filter((segment) => segment.video_exists).length;
  const complete = isScriptComplete(script);
  const exported = isScriptExported(script);
  const references = script.reference_images || [];
  const selectedReference = state.selectedReferenceByProduct.get(script.product_name) || "";
  const selectedOption = references.find((item) => item.path === selectedReference);
  const refClass = references.length && (references.length === 1 || selectedOption) ? "ok" : references.length ? "warn" : "error";
  const refLabel = !references.length ? "缺参考图" : references.length === 1 ? "参考图自动" : selectedOption ? `SKU ${selectedOption.label}` : "SKU待选择";
  const checked = state.selectedScriptPaths.has(script.md_path);
  const runningContext = contextForScript(script, runningContexts);
  const running = Boolean(runningContext);
  const feedback = feedbackForScript(script, scriptStatuses);
  const runningBadge = running ? `<span class="chip running-badge">${escapeHtml(currentContextLabel(runningContext))}</span>` : "";
  const feedbackBadge = feedback ? renderScriptFeedbackBadge(feedback) : "";
  const completeBadge = complete ? `<span class="chip ok">完整</span>` : "";
  const exportedBadge = exported ? `<span class="chip exported-chip">已导出</span>` : "";
  const archiveStatusBadge = exported && script.media_cleaned
    ? `<span class="chip warn">已清理</span>`
    : exported && script.upload_status && script.upload_status !== "未记录"
      ? `<span class="chip">${escapeHtml(script.upload_status)}</span>`
      : "";
  return `
    <div class="script-item ${index === state.selectedIndex ? "active" : ""} ${checked ? "checked" : ""} ${running ? "running-now" : ""} ${exported ? "exported" : ""} ${feedback ? `feedback-${feedback.status}` : ""}" data-index="${index}" data-path="${escapeHtml(script.md_path)}" role="button" tabindex="0">
      <label class="script-check" title="${exported ? "勾选恢复生成" : "勾选执行/导出"}">
        <input class="script-select" type="checkbox" data-path="${escapeHtml(script.md_path)}" ${checked ? "checked" : ""} />
      </label>
      <div class="script-body">
        <div class="script-name">${escapeHtml(script.md_name)}</div>
        <div class="script-meta">
          ${runningBadge}
          ${feedbackBadge}
          ${exportedBadge}
          ${archiveStatusBadge}
          ${completeBadge}
          <span class="chip ${refClass}">${refLabel}</span>
          <span class="chip">${segments.length} 片段</span>
          <span class="chip ${characters === segments.length ? "ok" : "warn"}">人物 ${characters}/${segments.length}</span>
          ${staleCharacters ? `<span class="chip warn">人物需重做 ${staleCharacters}</span>` : ""}
          <span class="chip ${storyboards === segments.length ? "ok" : "warn"}">故事 ${storyboards}/${segments.length}</span>
          ${staleStoryboards ? `<span class="chip warn">故事需重做 ${staleStoryboards}</span>` : ""}
          <span class="chip ${videos === segments.length ? "ok" : "warn"}">视频 ${videos}/${segments.length}</span>
        </div>
      </div>
    </div>
  `;
}

function visibleCatalogScripts(scripts) {
  return (scripts || []).filter((script) => state.showArchived ? isScriptExported(script) : !isScriptExported(script));
}

function ensureSelectedScriptVisible(scripts, visibleScripts) {
  if (!visibleScripts.length) return;
  const current = scripts[state.selectedIndex];
  if (current && visibleScripts.some((script) => script.md_path === current.md_path)) return;
  state.selectedIndex = scripts.findIndex((script) => script.md_path === visibleScripts[0].md_path);
}

function selectedVisibleScript(visibleScripts) {
  const scripts = state.catalog?.scripts || [];
  const current = scripts[state.selectedIndex];
  if (current && visibleScripts.some((script) => script.md_path === current.md_path)) return current;
  return visibleScripts[0] || null;
}

function expansionModeKey() {
  return `${API_BASE}:${state.showArchived ? "archive" : "active"}`;
}

function ensureInitialExpansion(visibleScripts) {
  const mode = expansionModeKey();
  if (state.expansionMode === mode) return;
  state.expandedProducts.clear();
  const script = selectedVisibleScript(visibleScripts);
  if (script) {
    state.expandedProducts.add(productExpansionKey(script.product_name));
  }
  state.expansionMode = mode;
}

function productExpansionKey(productName) {
  return String(productName || "");
}

function isProductExpanded(productName) {
  return state.expandedProducts.has(productExpansionKey(productName));
}

function toggleProductExpansion(productName) {
  const key = productExpansionKey(productName);
  if (state.expandedProducts.has(key)) {
    state.expandedProducts.delete(key);
  } else {
    state.expandedProducts.add(key);
  }
}

function groupVisibleScripts(scripts) {
  const products = [];
  const productMap = new Map();
  scripts.forEach((script) => {
    let product = productMap.get(script.product_name);
    if (!product) {
      product = { name: script.product_name, scripts: [], segments: 0 };
      productMap.set(script.product_name, product);
      products.push(product);
    }
    product.scripts.push(script);
    product.segments += (script.segments || []).length;
  });
  return products;
}

function productReferenceOptions(product) {
  return product.scripts[0]?.reference_images || [];
}

function syncProductReferenceSelections(scripts) {
  const available = new Map();
  scripts.forEach((script) => {
    if (!available.has(script.product_name)) available.set(script.product_name, script.reference_images || []);
  });
  for (const [productName, references] of available.entries()) {
    const selected = state.selectedReferenceByProduct.get(productName);
    if (references.length === 1) {
      state.selectedReferenceByProduct.set(productName, references[0].path);
    } else if (selected && !references.some((item) => item.path === selected)) {
      state.selectedReferenceByProduct.delete(productName);
    }
  }
  for (const productName of Array.from(state.selectedReferenceByProduct.keys())) {
    if (!available.has(productName)) state.selectedReferenceByProduct.delete(productName);
  }
}

function renderProductReferencePicker(productName, references, selectedReference) {
  if (!references.length) {
    return `<div class="product-reference-picker error">没有找到与产品名匹配的参考图</div>`;
  }
  if (references.length === 1) {
    const reference = references[0];
    return `
      <div class="product-reference-picker selected">
        <img src="${escapeHtml(reference.url)}" alt="" />
        <div><strong>本次产品参考图</strong><span>${escapeHtml(reference.label)}（唯一参考图，自动选择）</span></div>
      </div>
    `;
  }
  const selected = references.find((item) => item.path === selectedReference);
  return `
    <div class="product-reference-picker ${selected ? "selected" : "required"}">
      ${selected ? `<img src="${escapeHtml(selected.url)}" alt="" />` : ""}
      <div>
        <strong>本批脚本使用的产品 SKU</strong>
        <select class="product-reference-select" data-product-name="${escapeHtml(productName)}">
          <option value="">请选择产品参考图</option>
          ${references.map((reference) => `<option value="${escapeHtml(reference.path)}" ${reference.path === selectedReference ? "selected" : ""}>${escapeHtml(reference.label)}</option>`).join("")}
        </select>
        <span>${selected ? "本次所选脚本将统一使用此参考图" : `检测到 ${references.length} 张参考图，执行前必须选择`}</span>
      </div>
    </div>
  `;
}

function renderArchiveControls() {
  const exportButton = $("#exportSelectedButton");
  const restoreButton = $("#restoreSelectedButton");
  const deleteButton = $("#deleteSelectedScriptsButton");
  const completeButton = $("#selectCompletedScriptsButton");
  const archiveButton = $("#archiveToggleButton");
  if (exportButton) exportButton.hidden = state.showArchived;
  if (restoreButton) restoreButton.hidden = !state.showArchived;
  if (deleteButton) {
    deleteButton.hidden = state.showArchived;
    deleteButton.disabled = state.selectedScriptPaths.size === 0;
  }
  if (completeButton) completeButton.hidden = state.showArchived;
  if (archiveButton) archiveButton.textContent = state.showArchived ? "返回任务" : "查看归档";
}

function setPathSelection(paths, checked) {
  paths.forEach((path) => {
    if (checked) state.selectedScriptPaths.add(path);
    else state.selectedScriptPaths.delete(path);
  });
}

function renderSegments() {
  const script = selectedScript();
  if (!script) {
    $("#selectedTitle").textContent = "片段状态";
    $("#selectedMeta").textContent = "";
    $("#segmentTable").innerHTML = `<div class="empty-state">请选择脚本</div>`;
    return;
  }

  $("#selectedTitle").textContent = script.product_name;
  $("#selectedMeta").textContent = script.md_name;
  const runningContext = contextForScript(script, currentJobContexts());
  const selectedScriptIsRunning = Boolean(runningContext);
  const rows = script.segments
    .map((segment) => {
      const reuse = segment.reuses_character ? `<span class="chip">复用 ${segment.referenced_character_index || 1}</span>` : "";
      const runningSegment = selectedScriptIsRunning && runningContext?.segmentIndex === Number(segment.index);
      const runningChip = runningSegment ? `<span class="chip running-badge">运行中</span><br>` : "";
      const missingMediaLabel = script.exported ? "已清理" : "未生成";
      const activeCell = (stage) => {
        const runningStage = runningContext?.stage;
        const matches = runningStage === stage || (stage === "videos" && runningStage === "direct_videos");
        return runningSegment && matches ? ` class="running-cell"` : "";
      };
      return `
        <tr class="${runningSegment ? "running-segment" : ""}">
          <td class="segment-index">片段 ${segment.index}<br>${runningChip}<span class="muted">${escapeHtml(segment.time_range)}</span></td>
          <td${activeCell("characters")}>${renderAsset(segment.character_exists, segment.character_url, "人物图", false, segment.character_stale ? (segment.character_stale_reason || "需重做") : missingMediaLabel, segment.character_path)}${reuse}</td>
          <td${activeCell("storyboards")}>${renderAsset(segment.storyboard_exists, segment.storyboard_url, "故事版", false, segment.storyboard_stale ? (segment.storyboard_stale_reason || "需重做") : missingMediaLabel, segment.storyboard_path)}</td>
          <td${activeCell("videos")}>${renderAsset(segment.video_exists, segment.video_url, state.config?.video_label || "视频", true, missingMediaLabel, segment.video_path)}</td>
        </tr>
      `;
    })
    .join("");

  $("#segmentTable").innerHTML = `
    <table>
      <thead>
        <tr>
          <th class="segment-index">片段</th>
          <th>人物图</th>
          <th>故事版</th>
          <th>视频</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderAsset(exists, url, label, isVideo = false, missingLabel = "未生成", path = "") {
  if (!exists || !url) {
    const deleteButton = path && missingLabel !== "未生成" && missingLabel !== "已清理"
      ? `<button class="asset-delete-button inline" type="button" data-delete-asset-path="${escapeHtml(path)}" data-delete-asset-label="${escapeHtml(label)}" title="删除${escapeHtml(label)}">删除</button>`
      : "";
    return `<span class="chip warn" title="${escapeHtml(missingLabel)}">${escapeHtml(missingLabel)}</span>${deleteButton}`;
  }
  const media = isVideo
    ? `<video class="thumb" muted playsinline preload="metadata" src="${url}"></video>`
    : `<img class="thumb" src="${url}" alt="${label}" loading="lazy" />`;
  const deleteButton = path
    ? `<button class="asset-delete-button" type="button" data-delete-asset-path="${escapeHtml(path)}" data-delete-asset-label="${escapeHtml(label)}" title="删除${escapeHtml(label)}">删除</button>`
    : "";
  return `
    <div class="asset-stack">
      ${media}
      <div class="asset-actions">
        <a class="asset-link" href="${url}" target="_blank" rel="noreferrer">${label}</a>
        ${deleteButton}
      </div>
    </div>
  `;
}

async function handleArtifactDeleteClick(event) {
  const button = event.target.closest("[data-delete-asset-path]");
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  const path = button.dataset.deleteAssetPath;
  const label = button.dataset.deleteAssetLabel || "资源";
  if (!path) return;
  const ok = confirm(`确定删除这个${label}吗？\n\n${path}`);
  if (!ok) return;
  button.disabled = true;
  try {
    await api("/artifact", {
      method: "DELETE",
      body: JSON.stringify({ path }),
    });
    await refreshAll();
  } catch (error) {
    alert(`删除失败：${error.message}`);
    button.disabled = false;
  }
}

function renderJobs() {
  const jobs = state.jobs || [];
  const activeJob = activeOrLatestJob(jobs);
  if (!activeJob) {
    $("#jobState").textContent = "无任务";
    $("#jobProgress span").style.width = "0%";
    $("#jobLogs").innerHTML = `<div class="empty-state">暂无日志</div>`;
    updateToolbarState(null);
    return;
  }

  const percent = activeJob.total ? Math.round((activeJob.done / activeJob.total) * 100) : 0;
  const errorSuffix = activeJob.errors?.length ? ` · ${activeJob.errors.length} 错误` : "";
  $("#jobState").textContent = `${jobStatusLabel(activeJob)} · 处理 ${activeJob.done}/${activeJob.total} · ${percent}%${errorSuffix}`;
  $("#jobProgress span").style.width = `${Math.min(100, percent)}%`;
  updateToolbarState(activeJob);
  const activeDetails = renderActiveJobDetails(activeJob);
  const jobRows = jobs
    .slice(0, 10)
    .map(
      (job) => `
        <div class="job-row ${job.status}">
          <span>${stageLabel(job.stage)}</span>
          <strong>${jobStatusLabel(job)}</strong>
          <span>${job.done}/${job.total}</span>
          <span>${job.errors?.length || 0} 错误</span>
        </div>
      `,
    )
    .join("");
  const allLogs = jobs
    .flatMap((job) => {
      const logs = (job.logs || []).map((entry) => ({
        ...entry,
        stage: job.stage,
        jobStatus: job.status,
      }));
      const loggedErrors = new Set(logs.filter((entry) => entry.level === "error").map((entry) => entry.message));
      const errorLogs = (job.errors || [])
        .filter((message) => !loggedErrors.has(message))
        .map((message, index) => ({
        ts: job.finished_at || job.started_at || job.created_at || 0,
        level: "error",
        message,
        stage: job.stage,
        jobStatus: job.status,
        syntheticIndex: index,
      }));
      return [...logs, ...errorLogs];
    })
    .sort((a, b) => {
      const timeDelta = (b.ts || 0) - (a.ts || 0);
      if (timeDelta !== 0) return timeDelta;
      return (b.syntheticIndex || 0) - (a.syntheticIndex || 0);
    })
    .slice(0, 120);
  const logRows = allLogs.length
    ? allLogs
        .map(
          (entry) =>
            `<div class="log-row ${entry.level}">[${formatTime(entry.ts)}] ${stageLabel(entry.stage)} · ${escapeHtml(entry.message)}</div>`,
        )
        .join("")
    : `<div class="empty-state">暂无日志</div>`;
  $("#jobLogs").innerHTML = `${activeDetails}${jobRows ? `<div class="job-list">${jobRows}</div>` : ""}<div class="log-feed">${logRows}</div>`;
}

function renderActiveJobDetails(job) {
  const logs = job.logs || [];
  const lastLog = logs[logs.length - 1] || null;
  const current = extractCurrentTask(logs);
  const outcomes = jobOutcomeCounts(job);
  const generatedLabel = job.stats ? "成功生成" : "近期生成日志";
  const skippedLabel = job.stats ? "跳过" : "近期跳过日志";
  const elapsed = formatDuration((job.finished_at || Date.now() / 1000) - (job.started_at || job.created_at || Date.now() / 1000));
  const remaining = Math.max(0, (job.total || 0) - (job.done || 0));
  const handledPercent = job.total ? Math.round((job.done / job.total) * 100) : 0;
  const catalog = catalogAssetSummary();
  const currentStage = inferCurrentStage(job);
  const activeAsset = activeAssetSummary(currentStage, catalog);
  const selectedCount = Array.isArray(job.script_paths) ? job.script_paths.length : state.selectedScriptPaths.size;
  const scriptConcurrency = job.script_concurrency || selectedScriptConcurrency();
  const scriptSummary = scriptStatusSummary(job);
  const scriptQueue = renderScriptQueue(job);
  const latestText = lastLog ? lastLog.message : "暂无日志";
  const currentParts = [
    current.segment ? `<span>${escapeHtml(current.segment)}</span>` : "",
    current.taskId ? `<span>task ${escapeHtml(current.taskId)}</span>` : "",
    current.status ? `<span>${escapeHtml(current.status)}</span>` : "",
  ].filter(Boolean);
  return `
    <div class="job-detail">
      <div class="job-detail-grid">
        <div class="metric">
          <span>任务类型</span>
          <strong>${stageLabel(job.stage)}</strong>
        </div>
        <div class="metric">
          <span>当前功能</span>
          <strong>${stageLabel(currentStage)}</strong>
        </div>
        <div class="metric">
          <span>处理进度</span>
          <strong>${job.done || 0}/${job.total || 0}</strong>
        </div>
        <div class="metric">
          <span>处理比例</span>
          <strong>${handledPercent}%</strong>
        </div>
        <div class="metric">
          <span>${generatedLabel}</span>
          <strong>${outcomes.generated}</strong>
        </div>
        <div class="metric ${outcomes.skipped ? "warn" : ""}">
          <span>${skippedLabel}</span>
          <strong>${outcomes.skipped}</strong>
        </div>
        <div class="metric ${job.errors?.length ? "error" : ""}">
          <span>错误</span>
          <strong>${job.errors?.length || 0}</strong>
        </div>
        <div class="metric">
          <span>脚本进度</span>
          <strong>${scriptSummary.total ? `${scriptSummary.finished}/${scriptSummary.total}` : "--"}</strong>
        </div>
        <div class="metric ${scriptSummary.running ? "" : "warn"}">
          <span>正在脚本</span>
          <strong>${scriptSummary.running || 0}</strong>
        </div>
      </div>
      <div class="job-current">
        <div>
          <span class="muted">当前平台任务</span>
          <div class="current-line">${currentParts.length ? currentParts.join("") : `<span>${escapeHtml(job.status)}</span>`}</div>
        </div>
        <div>
          <span class="muted">最近日志</span>
          <div class="current-message">${escapeHtml(latestText)}</div>
        </div>
      </div>
      ${scriptQueue}
      <div class="asset-summary">
        <span>已选 ${selectedCount}</span>
        <span>脚本并发 ${scriptConcurrency}</span>
        <span>剩余处理 ${remaining}</span>
        <span>已运行 ${elapsed}</span>
        <span>当前功能产物 ${activeAsset.label} ${activeAsset.done}/${activeAsset.total}</span>
        <span>人物 ${catalog.characters}/${catalog.segments}</span>
        <span>故事 ${catalog.storyboards}/${catalog.segments}</span>
        <span>视频 ${catalog.videos}/${catalog.segments}</span>
        <span>完整脚本 ${catalog.completeScripts}/${catalog.runnableScripts}</span>
      </div>
    </div>
  `;
}

function jobOutcomeCounts(job) {
  if (job.stats) {
    return {
      generated: Number(job.stats.generated || 0),
      skipped: Number(job.stats.skipped || 0),
    };
  }
  const logs = job.logs || [];
  return {
    generated: logs.filter((entry) => /：已生成$/.test(entry.message || "")).length,
    skipped: logs.filter((entry) => /：已存在，跳过$/.test(entry.message || "")).length,
  };
}

function extractCurrentTask(logs) {
  const result = { segment: "", taskId: "", status: "" };
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const message = logs[index]?.message || "";
    const segmentMatch = message.match(/(片段\d+[^：]*)/);
    const taskMatch = message.match(/任务\s+([A-Za-z0-9_-]+)\s+状态：([A-Z_]+)/i);
    if (!result.segment && segmentMatch) result.segment = segmentMatch[1];
    if (!result.taskId && taskMatch) {
      result.taskId = taskMatch[1];
      result.status = taskMatch[2].toUpperCase();
    }
    if (result.segment && result.taskId) break;
  }
  return result;
}

function extractCurrentScript(logs) {
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const message = logs[index]?.message || "";
    const match = message.match(/处理\s+(.+?)\s+\/\s+(.+?\.md)(?:\s|$)/);
    if (match) return { productName: match[1], mdName: match[2], logIndex: index };
  }
  return { productName: "", mdName: "", logIndex: -1 };
}

function extractSegmentIndex(segmentText) {
  const match = String(segmentText || "").match(/片段\s*(\d+)/);
  return match ? Number(match[1]) : null;
}

function currentJobContexts() {
  const job = activeOrLatestJob(state.jobs || []);
  if (!job || !["running", "queued"].includes(job.status)) return [];
  const activeScripts = Object.values(job.active_scripts || {});
  if (activeScripts.length) {
    return activeScripts.map((item) => ({
      job,
      stage: item.stage || inferCurrentStage(job),
      productName: item.product_name || "",
      scriptName: item.md_name || "",
      scriptPath: item.md_path || "",
      segmentIndex: item.segment_index ? Number(item.segment_index) : null,
      segmentLabel: item.segment_label || "",
    }));
  }
  const logs = job.logs || [];
  const currentScript = extractCurrentScript(logs);
  const scopedLogs = currentScript.logIndex >= 0 ? logs.slice(currentScript.logIndex) : logs;
  const currentTask = extractCurrentTask(scopedLogs);
  const context = {
    job,
    stage: inferCurrentStage(job),
    productName: currentScript.productName,
    scriptName: currentScript.mdName,
    scriptPath: "",
    segmentIndex: extractSegmentIndex(currentTask.segment),
    segmentLabel: currentTask.segment,
  };
  return context.scriptName ? [context] : [];
}

function currentJobContext() {
  return currentJobContexts()[0] || null;
}

function contextForScript(script, contexts) {
  return (contexts || []).find((context) => isContextScript(script, context)) || null;
}

function isContextScript(script, context) {
  if (!script || !context || !context.scriptName) return false;
  if (context.scriptPath && script.md_path === context.scriptPath) return true;
  if (script.md_name === context.scriptName) return true;
  return script.product_name === context.productName && script.md_name === context.scriptName;
}

function currentContextLabel(context) {
  if (!context) return "";
  const parts = [statusLabel(context.job?.status), stageLabel(context.stage)];
  if (context.segmentIndex) parts.push(`片段${context.segmentIndex}`);
  return parts.filter(Boolean).join(" · ");
}

function feedbackForScript(script, statuses) {
  if (!script || !statuses) return null;
  if (statuses[script.md_path]) return statuses[script.md_path];
  return Object.values(statuses).find((item) => {
    if (!item) return false;
    if (item.md_path && item.md_path === script.md_path) return true;
    return item.product_name === script.product_name && item.md_name === script.md_name;
  }) || null;
}

function scriptFeedbackLabel(status) {
  return {
    pending: "等待",
    running: "运行中",
    done: "完成",
    failed: "失败",
    canceled: "已停止",
    retry: "重试",
  }[status] || status || "未知";
}

function renderScriptFeedbackBadge(feedback) {
  const status = feedback.status || "pending";
  const parts = [scriptFeedbackLabel(status)];
  if (feedback.stage) parts.push(stageLabel(feedback.stage));
  if (feedback.segment_label) parts.push(feedback.segment_label);
  if (status === "failed") {
    const failureLabel = shortFailureLabel(feedback.message || feedback.errors?.[feedback.errors.length - 1] || "");
    if (failureLabel && !parts.includes(failureLabel)) parts.push(failureLabel);
  }
  return `<span class="chip script-feedback ${status}" title="${escapeHtml(feedback.message || "")}">${escapeHtml(parts.join(" · "))}</span>`;
}

function shortFailureLabel(message) {
  const match = String(message || "").match(/(片段\s*\d+\s*[^：:，,]*)/);
  return match ? match[1].replace(/\s+/g, "") : "";
}

function scriptStatusSummary(job) {
  const items = Object.values(job?.script_statuses || {});
  const summary = { total: items.length, pending: 0, running: 0, done: 0, failed: 0, canceled: 0, retry: 0 };
  items.forEach((item) => {
    const key = item.status || "pending";
    summary[key] = (summary[key] || 0) + 1;
  });
  summary.finished = summary.done + summary.failed + summary.canceled;
  return summary;
}

function renderScriptQueue(job) {
  const items = Object.values(job?.script_statuses || {});
  if (!items.length) return "";
  const order = { running: 0, retry: 1, failed: 2, pending: 3, canceled: 4, done: 5 };
  const sorted = [...items].sort((a, b) => {
    const statusDelta = (order[a.status] ?? 9) - (order[b.status] ?? 9);
    if (statusDelta !== 0) return statusDelta;
    return (b.updated_at || 0) - (a.updated_at || 0);
  });
  const visible = sorted.slice(0, 18);
  const hiddenCount = Math.max(0, sorted.length - visible.length);
  const rows = visible.map((item) => {
    const detailParts = [];
    if (item.stage) detailParts.push(stageLabel(item.stage));
    if (item.segment_label) detailParts.push(item.segment_label);
    const latestError = Array.isArray(item.errors) && item.errors.length ? item.errors[item.errors.length - 1] : "";
    if (latestError) detailParts.push(latestError);
    else if (item.message) detailParts.push(item.message);
    const detail = detailParts.join(" · ");
    return `
      <div class="script-run-row ${item.status || "pending"}">
        <span class="script-run-state">${escapeHtml(scriptFeedbackLabel(item.status))}</span>
        <span class="script-run-name">${escapeHtml(item.product_name || "")} / ${escapeHtml(item.md_name || "")}</span>
        <span class="script-run-detail">${escapeHtml(detail)}</span>
      </div>
    `;
  }).join("");
  return `
    <div class="script-run-list">
      <div class="script-run-heading">
        <strong>脚本队列</strong>
        <span>${sorted.length} 条${hiddenCount ? ` · 另有 ${hiddenCount} 条` : ""}</span>
      </div>
      ${rows}
    </div>
  `;
}

function catalogAssetSummary() {
  const scripts = state.catalog?.scripts || [];
  const summary = { segments: 0, characters: 0, storyboards: 0, videos: 0, completeScripts: 0, runnableScripts: 0 };
  scripts.forEach((script) => {
    if (isScriptExported(script)) return;
    const segments = script.segments || [];
    if (!segments.length) return;
    summary.runnableScripts += 1;
    let scriptComplete = true;
    segments.forEach((segment) => {
      summary.segments += 1;
      if (segment.character_exists) summary.characters += 1;
      if (segment.storyboard_exists) summary.storyboards += 1;
      if (segment.video_exists) summary.videos += 1;
      if (!segment.character_exists || !segment.storyboard_exists || !segment.video_exists) scriptComplete = false;
    });
    if (scriptComplete) summary.completeScripts += 1;
  });
  return summary;
}

function activeAssetSummary(stage, catalog) {
  if (stage === "characters") return { label: "目录人物", done: catalog.characters, total: catalog.segments };
  if (stage === "storyboards") return { label: "目录故事", done: catalog.storyboards, total: catalog.segments };
  if (stage === "videos") return { label: "目录视频", done: catalog.videos, total: catalog.segments };
  return { label: "目录视频", done: catalog.videos, total: catalog.segments };
}

function inferCurrentStage(job) {
  if (job.stage && !["all", "repair", "smart"].includes(job.stage)) return job.stage;
  const logs = job.logs || [];
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const message = logs[index]?.message || "";
    if (message.includes("功能3") || message.includes("视频")) return "videos";
    if (message.includes("功能2") || message.includes("故事版")) return "storyboards";
    if (message.includes("功能1") || message.includes("人物图")) return "characters";
  }
  if (job.stage === "repair" || job.stage === "smart") return job.stage;
  return job.stage || "all";
}

function activeOrLatestJob(jobs) {
  return (
    (jobs || []).find((job) => job.status === "running") ||
    (jobs || []).find((job) => job.status === "queued") ||
    (jobs || [])[0] ||
    null
  );
}

function activeRunningJob() {
  return (state.jobs || []).find((job) => job.status === "running") || (state.jobs || []).find((job) => job.status === "queued") || null;
}

function selectedScript() {
  const scripts = state.catalog?.scripts || [];
  return scripts[state.selectedIndex] || null;
}

function isScriptComplete(script) {
  if (script?.complete !== undefined) return Boolean(script.complete);
  const segments = script?.segments || [];
  return Boolean(segments.length) && segments.every((segment) => segment.character_exists && segment.storyboard_exists && segment.video_exists);
}

function isScriptVideoComplete(script) {
  const segments = script?.segments || [];
  return Boolean(segments.length) && segments.every((segment) => segment.video_exists);
}

function isScriptExported(script) {
  return Boolean(script?.exported);
}

function isScriptRunnable(script) {
  return script && !isScriptExported(script);
}

function isScriptSelectable(script) {
  if (!script) return false;
  return state.showArchived ? isScriptExported(script) : isScriptRunnable(script);
}

async function runStage(stage) {
  setRunButtonsDisabled(true);
  try {
    const overwrite = stage === "repair" ? false : $("#overwriteToggle").checked;
    const available = new Set((state.catalog?.scripts || []).filter(isScriptRunnable).map((script) => script.md_path));
    const scriptPaths = Array.from(state.selectedScriptPaths).filter((path) => available.has(path));
    if (!scriptPaths.length) {
      alert("请先勾选要执行的未导出脚本");
      return;
    }
    const selectedScripts = (state.catalog?.scripts || []).filter((script) => scriptPaths.includes(script.md_path));
    const selectedProducts = [...new Set(selectedScripts.map((script) => script.product_name))];
    const referenceImages = {};
    if (stage !== "characters") {
      for (const productName of selectedProducts) {
        const script = selectedScripts.find((item) => item.product_name === productName);
        const references = script?.reference_images || [];
        if (!references.length) {
          alert(`${productName} 缺少产品参考图`);
          return;
        }
        const selectedReference = state.selectedReferenceByProduct.get(productName);
        if (references.length > 1 && !selectedReference) {
          state.expandedProducts.add(productExpansionKey(productName));
          render();
          alert(`${productName} 有 ${references.length} 张产品参考图，请先选择本批脚本使用的 SKU`);
          return;
        }
        referenceImages[productName] = selectedReference || references[0].path;
      }
    }
    const job = await api("/run", {
      method: "POST",
      body: JSON.stringify({ stage, overwrite, script_paths: scriptPaths, script_concurrency: selectedScriptConcurrency(), reference_images: referenceImages }),
    });
    state.activeJobId = job.id;
    await refreshAll();
  } catch (error) {
    alert(`启动失败：${error.message}`);
  } finally {
    updateToolbarState(activeRunningJob());
  }
}

async function cancelActiveJob() {
  const active = activeRunningJob();
  if (!active) return;
  if (!confirm("确定停止当前任务吗？当前已经提交到外部平台的单个请求可能无法撤回，但本地不会继续处理后续片段。")) {
    return;
  }
  const button = $("#cancelButton");
  if (button) button.disabled = true;
  try {
    await api("/cancel", {
      method: "POST",
      body: JSON.stringify({ job_id: active.id }),
    });
    await refreshAll();
  } catch (error) {
    alert(`停止失败：${error.message}`);
  }
}

function syncSelectedScriptPaths(scripts) {
  const available = new Set(scripts.filter(isScriptSelectable).map((script) => script.md_path));
  for (const path of Array.from(state.selectedScriptPaths)) {
    if (!available.has(path)) state.selectedScriptPaths.delete(path);
  }
}

async function exportSelectedCompleted() {
  const scripts = state.catalog?.scripts || [];
  const scriptByPath = new Map(scripts.map((script) => [script.md_path, script]));
  const exportablePaths = Array.from(state.selectedScriptPaths).filter((path) => {
    const script = scriptByPath.get(path);
    return script && !isScriptExported(script) && isScriptVideoComplete(script);
  });
  if (!exportablePaths.length) {
    alert("当前没有勾选“所有片段视频已生成且未导出”的脚本");
    return;
  }
  const ok = confirm(`准备导出 ${exportablePaths.length} 个有视频的脚本：脚本会复制到归档目录，人物图、故事版图和视频会移动到归档目录；原脚本目录仍保留脚本。继续吗？`);
  if (!ok) return;
  const button = $("#exportSelectedButton");
  if (button) button.disabled = true;
  try {
    const result = await api("/export-completed", {
      method: "POST",
      body: JSON.stringify({ script_paths: exportablePaths }),
    });
    const skippedText = result.skipped?.length ? `，跳过 ${result.skipped.length} 个` : "";
    alert(`导出完成：${result.exported?.length || 0} 个${skippedText}\n导出目录：${result.export_root}`);
    state.selectedScriptPaths.clear();
    await refreshAll();
  } catch (error) {
    alert(`导出失败：${error.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

async function restoreSelectedArchived() {
  const scripts = state.catalog?.scripts || [];
  const scriptByPath = new Map(scripts.map((script) => [script.md_path, script]));
  const restorePaths = Array.from(state.selectedScriptPaths).filter((path) => isScriptExported(scriptByPath.get(path)));
  if (!restorePaths.length) {
    alert("当前没有勾选已导出的归档脚本");
    return;
  }
  const ok = confirm(`准备恢复 ${restorePaths.length} 个归档脚本到可生成状态：脚本和图片会移回原脚本目录；视频默认不搬回。继续吗？`);
  if (!ok) return;
  const button = $("#restoreSelectedButton");
  if (button) button.disabled = true;
  try {
    const result = await api("/restore-exported", {
      method: "POST",
      body: JSON.stringify({ script_paths: restorePaths, restore_videos: false }),
    });
    const skippedText = result.skipped?.length ? `，跳过 ${result.skipped.length} 个` : "";
    alert(`恢复完成：${result.restored?.length || 0} 个${skippedText}`);
    state.selectedScriptPaths.clear();
    state.showArchived = false;
    await refreshAll();
  } catch (error) {
    alert(`恢复失败：${error.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

async function deleteSelectedScripts() {
  const scripts = state.catalog?.scripts || [];
  const scriptByPath = new Map(scripts.map((script) => [script.md_path, script]));
  const deletePaths = Array.from(state.selectedScriptPaths).filter((path) => {
    const script = scriptByPath.get(path);
    return script && !isScriptExported(script);
  });
  if (!deletePaths.length) {
    alert("请先勾选要删除的未归档脚本");
    return;
  }
  const names = deletePaths
    .slice(0, 8)
    .map((path) => `• ${scriptByPath.get(path)?.md_name || path}`)
    .join("\n");
  const remaining = deletePaths.length > 8 ? `\n• 另有 ${deletePaths.length - 8} 个脚本` : "";
  const ok = confirm(
    `确定永久删除以下 ${deletePaths.length} 个脚本吗？\n\n${names}${remaining}\n\n将同步删除这些脚本的人物图、故事版图、视频和产物元数据；不会删除产品参考图。此操作无法撤销。`,
  );
  if (!ok) return;
  const button = $("#deleteSelectedScriptsButton");
  if (button) button.disabled = true;
  try {
    const result = await api("/scripts", {
      method: "DELETE",
      body: JSON.stringify({ script_paths: deletePaths }),
    });
    alert(`删除完成：${result.scripts_deleted || 0} 个脚本，共 ${result.files_deleted || 0} 个文件`);
    state.selectedScriptPaths.clear();
    await refreshAll();
  } catch (error) {
    alert(`删除失败：${error.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

async function pollJobs() {
  if (state.pollingJobs) return;
  state.pollingJobs = true;
  try {
    const [jobs, globalJobs] = await Promise.all([api("/jobs"), loadGlobalJobs()]);
    state.jobs = jobs.jobs || [];
    state.globalJobs = globalJobs;
    state.lastGlobalStatusAt = Date.now();
    renderGlobalStatus();
    renderCatalog();
    renderSegments();
    renderJobs();
    const latest = state.jobs[0];
    const active = activeRunningJob();
    if (active && Date.now() - state.lastCatalogRefreshAt > 30000) {
      state.catalog = await api("/catalog");
      state.lastCatalogRefreshAt = Date.now();
      renderCatalog();
      renderSegments();
      renderJobs();
      return;
    }
    const terminalKey = terminalJobKey(latest);
    if (terminalKey && terminalKey !== state.lastTerminalCatalogJobKey) {
      state.lastTerminalCatalogJobKey = terminalKey;
      state.catalog = await api("/catalog");
      state.lastCatalogRefreshAt = Date.now();
      renderCatalog();
      renderSegments();
      renderJobs();
    }
  } catch (_) {
    // Polling should not interrupt the dashboard.
  } finally {
    state.pollingJobs = false;
  }
}

function terminalJobKey(job) {
  if (!job || !["completed", "failed", "canceled"].includes(job.status)) return "";
  return `${job.id || ""}:${job.status}:${job.finished_at || ""}`;
}

function setButtonsDisabled(disabled) {
  setRunButtonsDisabled(disabled);
  const refreshButton = $("#refreshButton");
  if (refreshButton) refreshButton.disabled = disabled;
}

function setRunButtonsDisabled(disabled) {
  $$(".run-button").forEach((button) => {
    button.disabled = disabled;
  });
}

function updateToolbarState(activeJob) {
  const isActive = activeJob && ["running", "queued"].includes(activeJob.status);
  setRunButtonsDisabled(false);
  const cancelButton = $("#cancelButton");
  if (cancelButton) cancelButton.disabled = !isActive;
  const concurrencySelect = $("#concurrencySelect");
  if (concurrencySelect) concurrencySelect.disabled = false;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatTime(ts) {
  if (!ts) return "--:--:--";
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour12: false });
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${hours}时${String(minutes).padStart(2, "0")}分`;
  if (minutes) return `${minutes}分${String(secs).padStart(2, "0")}秒`;
  return `${secs}秒`;
}

function stageLabel(stage) {
  return {
    all: "全流程",
    characters: "功能1",
    storyboards: "功能2",
    videos: "功能3",
    direct_videos: "功能4 快速模式",
    repair: "补漏模式",
    smart: "功能5 完整模式",
    canceled: "已停止",
  }[stage] || stage;
}

function statusLabel(status) {
  return {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    canceled: "已停止",
  }[status] || status || "未知";
}

function jobStatusLabel(job) {
  if (job?.status !== "queued") return statusLabel(job?.status);
  const queuedAhead = Math.max(0, Number(job.queued_ahead) || 0);
  return queuedAhead ? `排队中 · 前方 ${queuedAhead} 个` : "排队中 · 即将执行";
}

$("#refreshButton").addEventListener("click", refreshAll);
$("#selectAllScriptsButton").addEventListener("click", () => {
  const scripts = visibleCatalogScripts(state.catalog?.scripts || []);
  scripts.filter(isScriptSelectable).forEach((script) => state.selectedScriptPaths.add(script.md_path));
  render();
});
$("#selectCompletedScriptsButton")?.addEventListener("click", () => {
  const scripts = state.catalog?.scripts || [];
  state.selectedScriptPaths.clear();
  scripts
    .filter((script) => isScriptRunnable(script) && isScriptVideoComplete(script))
    .forEach((script) => state.selectedScriptPaths.add(script.md_path));
  render();
});
$("#exportSelectedButton")?.addEventListener("click", exportSelectedCompleted);
$("#restoreSelectedButton")?.addEventListener("click", restoreSelectedArchived);
$("#deleteSelectedScriptsButton")?.addEventListener("click", deleteSelectedScripts);
$("#archiveToggleButton")?.addEventListener("click", () => {
  state.showArchived = !state.showArchived;
  state.expansionMode = "";
  state.expandedProducts.clear();
  state.selectedScriptPaths.clear();
  render();
});
$("#clearScriptSelectionButton").addEventListener("click", () => {
  state.selectedScriptPaths.clear();
  render();
});
$$(".run-button").forEach((button) => {
  button.addEventListener("click", () => runStage(button.dataset.stage));
});
$("#cancelButton")?.addEventListener("click", cancelActiveJob);
document.addEventListener("click", handleArtifactDeleteClick);

refreshAll().catch((error) => {
  alert(`初始化失败：${error.message}`);
}).finally(() => {
  setInterval(pollJobs, 4000);
});
