const state = {
  activeConfig: "prompt",
  currentJobId: "",
  pollTimer: null,
  lastOutputDir: "",
  latestScanId: "",
  pendingItems: [],
  selectedPaths: new Set(),
  runningItems: [],
};

const JOB_STORAGE_KEY = "ScriptAnalysis.currentJobId";
const $ = (id) => document.getElementById(id);

function bytes(value) {
  if (!value && value !== 0) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(value);
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!response.ok) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function shortPath(path) {
  const text = String(path || "");
  const marker = "/带货/带货/";
  const index = text.indexOf(marker);
  if (index === -1) return text;
  return `带货/${text.slice(index + marker.length)}`;
}

function setPathInput(id, fullPath) {
  const input = $(id);
  input.dataset.fullPath = fullPath || "";
  input.value = shortPath(fullPath);
  input.title = fullPath || "";
}

function getPathInput(id) {
  const input = $(id);
  const fullPath = input.dataset.fullPath || "";
  return fullPath && input.value === shortPath(fullPath) ? fullPath : input.value;
}

function getBatchLimit() {
  const value = $("batchLimitInput").value.trim();
  if (!value) return 0;
  const limit = Number.parseInt(value, 10);
  if (!Number.isFinite(limit) || limit < 1) {
    throw new Error("单次处理条数必须为空，或填写大于等于 1 的整数");
  }
  return limit;
}

function setJobBadge(status) {
  const badge = $("jobStatus");
  badge.className = "badge";
  if (status === "running" || status === "queued") {
    badge.classList.add("running");
    badge.textContent = "运行中";
  } else if (status === "completed") {
    badge.classList.add("done");
    badge.textContent = "完成";
  } else if (status === "failed") {
    badge.classList.add("failed");
    badge.textContent = "失败";
  } else {
    badge.classList.add("idle");
    badge.textContent = "待机";
  }
}

function isActiveJob(job) {
  return job && job.id && (job.status === "queued" || job.status === "running");
}

function setCurrentJobId(jobId) {
  state.currentJobId = jobId || "";
  if (state.currentJobId) {
    localStorage.setItem(JOB_STORAGE_KEY, state.currentJobId);
  } else {
    localStorage.removeItem(JOB_STORAGE_KEY);
  }
}

function startJobPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => pollJob().catch(showError), 1500);
}

function makeItem(item, options = {}) {
  const node = document.createElement("div");
  node.className = `item ${options.className || ""}`.trim();
  const title = document.createElement("div");
  title.className = "item-title";
  title.textContent = item.relative_path || item.name || item.path;
  const meta = document.createElement("div");
  meta.className = "item-meta";
  const parts = [];
  if (item.product) parts.push(item.product);
  if (item.video_id) parts.push(`ID ${item.video_id}`);
  if (item.size || item.size === 0) parts.push(bytes(item.size));
  if (item.status) parts.push(item.status);
  if (options.status) parts.push(options.status);
  meta.textContent = parts.join(" · ") || "-";
  node.append(title, meta);
  if (item.duplicate_script) {
    const duplicate = document.createElement("div");
    duplicate.className = "item-meta";
    duplicate.textContent = `命中脚本: ${item.duplicate_script}`;
    node.appendChild(duplicate);
  }
  if (item.target_path) {
    const target = document.createElement("div");
    target.className = "item-meta";
    target.textContent = `保存到: ${item.target_path}`;
    node.appendChild(target);
  }
  return node;
}

function renderQueueList(id, items, emptyText, options = {}) {
  const box = $(id);
  box.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = emptyText;
    box.appendChild(empty);
    return;
  }
  for (const item of items) {
    box.appendChild(makeItem(item, options));
  }
}

function groupedByProduct(items) {
  const groups = new Map();
  for (const item of items) {
    const product = item.product || "未分类";
    if (!groups.has(product)) groups.set(product, []);
    groups.get(product).push(item);
  }
  return Array.from(groups.entries()).map(([product, groupItems]) => ({ product, items: groupItems }));
}

function updateSelectionState() {
  const validPaths = new Set(state.pendingItems.map((item) => item.path));
  state.selectedPaths = new Set(Array.from(state.selectedPaths).filter((path) => validPaths.has(path)));
  $("selectedCount").textContent = `已选 ${state.selectedPaths.size}`;
  $("selectionTools").hidden = !state.pendingItems.length;
  $("processBtn").disabled = !state.selectedPaths.size;
}

function setSelectedPaths(paths) {
  state.selectedPaths = new Set(paths);
  renderPendingList();
}

function toggleProductSelection(product, checked) {
  const next = new Set(state.selectedPaths);
  for (const item of state.pendingItems) {
    if ((item.product || "未分类") === product) {
      if (checked) next.add(item.path);
      else next.delete(item.path);
    }
  }
  state.selectedPaths = next;
  renderPendingList();
}

function toggleItemSelection(path, checked) {
  if (checked) state.selectedPaths.add(path);
  else state.selectedPaths.delete(path);
  renderPendingList();
}

function renderPendingList() {
  const box = $("pendingList");
  box.innerHTML = "";
  if (!state.pendingItems.length) {
    box.innerHTML = '<div class="muted">暂无待拆解</div>';
    updateSelectionState();
    return;
  }

  for (const group of groupedByProduct(state.pendingItems)) {
    const selectedInGroup = group.items.filter((item) => state.selectedPaths.has(item.path)).length;
    const groupNode = document.createElement("div");
    groupNode.className = "product-queue";

    const head = document.createElement("label");
    head.className = "product-select";
    const productCheckbox = document.createElement("input");
    productCheckbox.type = "checkbox";
    productCheckbox.checked = selectedInGroup === group.items.length;
    productCheckbox.indeterminate = selectedInGroup > 0 && selectedInGroup < group.items.length;
    productCheckbox.addEventListener("change", () => toggleProductSelection(group.product, productCheckbox.checked));
    const title = document.createElement("span");
    title.textContent = `${group.product} · ${group.items.length} 条待拆解`;
    head.append(productCheckbox, title);
    groupNode.appendChild(head);

    for (const item of group.items) {
      const row = document.createElement("label");
      row.className = "video-select";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.selectedPaths.has(item.path);
      checkbox.addEventListener("change", () => toggleItemSelection(item.path, checkbox.checked));
      const body = document.createElement("span");
      body.className = "video-select-body";
      body.innerHTML = `
        <span class="item-title">${item.name}</span>
        <span class="item-meta">ID ${item.video_id || "-"} · ${bytes(item.size)}</span>
      `;
      row.append(checkbox, body);
      groupNode.appendChild(row);
    }

    box.appendChild(groupNode);
  }
  updateSelectionState();
}

function renderScan(scan) {
  if (!scan || !scan.id) {
    state.latestScanId = "";
    state.pendingItems = [];
    state.selectedPaths = new Set();
    state.runningItems = [];
    $("queueSummary").hidden = true;
    $("queueSummary").textContent = "";
    renderPendingList();
    renderQueueList("skippedList", [], "暂无重复项");
    renderQueueList("missingIdList", [], "暂无无法识别项");
    return;
  }

  state.latestScanId = scan.id;
  state.pendingItems = scan.pending || [];
  state.selectedPaths = new Set();
  state.runningItems = [];
  const summary = scan.summary || {};
  $("queueSummary").hidden = false;
  $("queueSummary").textContent =
    `扫描 ${summary.total || 0} 个视频；待拆解 ${summary.pending || 0} 个；` +
    `重复跳过 ${summary.skipped || 0} 个；无法识别 ID ${summary.missing_id || 0} 个`;
  renderPendingList();
  renderQueueList("skippedList", scan.skipped || [], "暂无重复项", { className: "skipped" });
  renderQueueList("missingIdList", scan.missing_id || [], "暂无无法识别项", { className: "missing" });
}

function renderScanResults(scan) {
  const files = [];
  for (const item of scan.skipped || []) {
    if (item.duplicate_script) {
      files.push({
        name: item.duplicate_script.split("/").pop(),
        path: item.duplicate_script,
        meta: `${item.product || "脚本"} · ID ${item.video_id || "-"}`,
      });
    }
  }
  for (const item of scan.pending || []) {
    if (item.target_path) {
      files.push({
        name: item.target_path.split("/").pop(),
        path: item.target_path,
        meta: `待拆解保存目标 · ${item.product || "脚本"} · ID ${item.video_id || "-"}`,
        pending: true,
      });
    }
  }
  renderFileResults(files);
}

function renderFileResults(files) {
  const box = $("outputList");
  box.innerHTML = "";
  if (!files.length) {
    box.innerHTML = '<div class="muted">暂无脚本结果</div>';
    return;
  }
  for (const file of files) {
    const node = document.createElement("div");
    node.className = `file-result ${file.pending ? "pending" : ""}`.trim();
    node.innerHTML = `
      <div class="item-title">${file.name}</div>
      <div class="run-meta">${file.meta || ""}</div>
    `;
    box.appendChild(node);
  }
}

function renderScriptsByProduct(groups) {
  const box = $("outputList");
  box.innerHTML = "";
  if (!groups.length) {
    box.innerHTML = '<div class="muted">暂无脚本</div>';
    return;
  }
  for (const group of groups) {
    const node = document.createElement("div");
    node.className = "run";
    node.innerHTML = `
      <div class="item-title">${group.product}</div>
      <div class="run-meta">${group.count || 0} 个脚本</div>
    `;
    for (const file of group.files || []) {
      const fileNode = document.createElement("div");
      fileNode.className = "file-button";
      const countryMeta = file.needs_country_prefix_update
        ? `建议国家码: ${file.country_code} · 建议名: ${file.suggested_name}`
        : `国家码: ${file.country_code || file.current_country_code || "-"}`;
      fileNode.innerHTML = `
        <div class="file-name">${escapeHtml(file.name)}</div>
        <div class="file-meta ${file.needs_country_prefix_update ? "warn" : ""}">${escapeHtml(countryMeta)}</div>
      `;
      node.appendChild(fileNode);
    }
    box.appendChild(node);
  }
}

async function refreshStatus() {
  const data = await api("/api/status");
  $("rootPath").textContent = "Gemini 视频拆解 · 查重队列 · Markdown 脚本归档";
  $("rootPath").title = data.skill_root || "";
  $("modelBadge").textContent = data.settings.model || "未设置模型";
  $("keyBadge").textContent = data.settings.api_key_hint || "API";
  $("modelInput").value = data.settings.model || "";
  $("baseUrlInput").value = data.settings.base_url || "";
  setPathInput("videoDirInput", data.queue_defaults.video_dir || "");
  setPathInput("scriptDirInput", data.queue_defaults.script_dir || "");
  renderScriptsByProduct(data.scripts_by_product || []);
  renderScan(data.latest_scan || {});
  if (isActiveJob(data.active_job)) {
    setCurrentJobId(data.active_job.id);
    state.lastOutputDir = data.active_job.output_dir || "";
    state.runningItems = data.active_job.items || [];
    renderJobState(data.active_job);
    $("scanBtn").disabled = true;
    $("processBtn").disabled = true;
    startJobPolling();
  }
}

async function scanQueue() {
  $("scanBtn").disabled = true;
  $("processBtn").disabled = true;
  $("logPane").textContent = "正在扫描视频目录并查重...";
  try {
    const scan = await api("/api/scan-queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_dir: getPathInput("videoDirInput"),
        script_dir: getPathInput("scriptDirInput"),
      }),
    });
    renderScan(scan);
    $("logPane").textContent =
      `扫描完成: 待拆解 ${scan.summary.pending} 个，重复跳过 ${scan.summary.skipped} 个。请选择要处理的视频。`;
    return scan;
  } finally {
    $("scanBtn").disabled = false;
    updateSelectionState();
  }
}

async function startRun(scanId = state.latestScanId, paths = []) {
  if (!scanId || !paths.length) return null;
  state.runningItems = state.pendingItems.filter((item) => paths.includes(item.path));
  const limit = getBatchLimit();
  const limitedPaths = limit ? paths.slice(0, limit) : paths;
  state.runningItems = limit ? state.runningItems.slice(0, limit) : state.runningItems;
  $("scanBtn").disabled = true;
  $("processBtn").disabled = true;
  $("logPane").textContent = "队列任务提交中...";
  const job = await api("/api/run-queue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scan_id: scanId, paths: limitedPaths }),
  });
  setCurrentJobId(job.id);
  state.lastOutputDir = job.output_dir || "";
  state.runningItems = job.items || state.runningItems;
  setJobBadge(job.status);
  pollJob().catch(showError);
  startJobPolling();
  return job;
}

async function processQueue() {
  if (!state.latestScanId) {
    throw new Error("请先扫描查重，再选择要处理的视频");
  }
  const paths = Array.from(state.selectedPaths);
  if (!paths.length) {
    throw new Error("请选择至少一个待拆解视频");
  }
  const limit = getBatchLimit();
  const runCount = limit ? Math.min(limit, paths.length) : paths.length;
  $("logPane").textContent =
    `本次处理 ${runCount}/${paths.length} 个已选视频。处理方式: 逐条串行处理，非并发。`;
  await startRun(state.latestScanId, paths);
}

function renderJobItems(items) {
  if (!items || !items.length) return;
  const baseItems = state.runningItems.length ? state.runningItems : items;
  const merged = baseItems.map((item, index) => ({
    ...item,
    ...(items[index] || {}),
    status: items[index]?.status || item.status || "queued",
  }));
  renderQueueList("pendingList", merged, "暂无待拆解", {
    status: "",
  });
}

function renderProgressPanel(job) {
  const panel = $("progressPanel");
  if (!job || !job.id) {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }
  const items = job.items || [];
  const total = Number(job.total || items.length || 0);
  const completed = Number(job.completed || items.filter((item) => item.status === "completed").length || 0);
  const failed = Number(job.failed || items.filter((item) => item.status === "failed").length || 0);
  const runningItem = items.find((item) => item.status === "running");
  const queued = Math.max(total - completed - failed - (runningItem ? 1 : 0), 0);
  const doneCount = completed + failed;
  const percent = total ? Math.min(100, Math.round((doneCount / total) * 100)) : 0;
  const currentName =
    runningItem?.relative_path || runningItem?.name || (job.status === "queued" ? "等待开始" : "暂无正在处理的视频");

  panel.hidden = false;
  panel.innerHTML = `
    <div class="progress-top">
      <div class="progress-title">${job.status === "running" ? "正在逐条拆解" : "队列状态"}</div>
      <div class="progress-count">${doneCount}/${total || 0} · ${percent}%</div>
    </div>
    <div class="progress-track"><div class="progress-fill" style="width: ${percent}%"></div></div>
    <div class="progress-meta-grid">
      <div class="progress-meta"><span>完成</span><strong>${completed}</strong></div>
      <div class="progress-meta"><span>失败</span><strong>${failed}</strong></div>
      <div class="progress-meta"><span>处理中</span><strong>${runningItem ? 1 : 0}</strong></div>
      <div class="progress-meta"><span>等待</span><strong>${queued}</strong></div>
    </div>
    <div class="progress-current">当前: ${escapeHtml(currentName)}</div>
  `;
}

function renderJobState(job) {
  setJobBadge(job.status);
  renderProgressPanel(job);
  const progress =
    job.total || job.completed || job.failed
      ? `进度: ${job.completed || 0}/${job.total || 0}，失败 ${job.failed || 0}\n\n`
      : "";
  $("logPane").textContent = progress + ((job.logs || []).join("\n") || "等待日志...");
  $("logPane").scrollTop = $("logPane").scrollHeight;
  state.runningItems = job.items || state.runningItems;
  renderJobItems(job.items || []);
  if (job.final_outputs && job.final_outputs.length) {
    renderScriptsByProduct(job.scripts_by_product || []);
  }
}

async function pollJob() {
  if (!state.currentJobId) return;
  const job = await api(`/api/jobs/${state.currentJobId}`);
  renderJobState(job);
  if (job.status === "completed" || job.status === "failed") {
    clearInterval(state.pollTimer);
    setCurrentJobId("");
    $("scanBtn").disabled = false;
    $("processBtn").disabled = false;
    await refreshStatus();
  }
}

async function loadConfig(name) {
  const data = await api(`/api/config-file?name=${encodeURIComponent(name)}`);
  $("configEditor").value = data.content || "";
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.config === name);
  });
  state.activeConfig = name;
}

async function saveConfig() {
  await api("/api/config-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: state.activeConfig, content: $("configEditor").value }),
  });
  await refreshStatus();
}

async function saveSettings() {
  const payload = {
    model: $("modelInput").value,
    base_url: $("baseUrlInput").value,
    api_key: $("apiKeyInput").value,
  };
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  $("apiKeyInput").value = "";
  await refreshStatus();
}

async function openLastOutput() {
  const targetPath = getPathInput("scriptDirInput");
  const result = await api("/api/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: targetPath }),
  });
  $("logPane").textContent = `已打开目录: ${result.path || targetPath}`;
}

function bindEvents() {
  $("scanBtn").addEventListener("click", () => scanQueue().catch(showError));
  $("processBtn").addEventListener("click", () => processQueue().catch(showError));
  $("selectAllBtn").addEventListener("click", () => setSelectedPaths(state.pendingItems.map((item) => item.path)));
  $("clearSelectionBtn").addEventListener("click", () => setSelectedPaths([]));
  $("saveConfigBtn").addEventListener("click", saveConfig);
  $("saveSettingsBtn").addEventListener("click", saveSettings);
  $("openOutputBtn").addEventListener("click", openLastOutput);
  $("openConfigBtn").addEventListener("click", () => {
    $("editorModal").hidden = false;
  });
  $("closeConfigBtn").addEventListener("click", () => {
    $("editorModal").hidden = true;
  });
  $("editorModal").addEventListener("click", (event) => {
    if (event.target === $("editorModal")) $("editorModal").hidden = true;
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => loadConfig(tab.dataset.config).catch(showError));
  });
}

function showError(error) {
  $("logPane").textContent = `错误: ${error.message || error}`;
  renderProgressPanel(null);
  setJobBadge("failed");
  $("scanBtn").disabled = false;
  $("processBtn").disabled = false;
  updateSelectionState();
}

async function boot() {
  bindEvents();
  setJobBadge("idle");
  renderScan({});
  renderProgressPanel(null);
  await refreshStatus();
  if (!state.currentJobId) {
    const savedJobId = localStorage.getItem(JOB_STORAGE_KEY);
    if (savedJobId) {
      setCurrentJobId(savedJobId);
      try {
        await pollJob();
        if (state.currentJobId) startJobPolling();
      } catch {
        setCurrentJobId("");
        setJobBadge("idle");
      }
    }
  }
  await loadConfig("prompt");
}

boot().catch(showError);
