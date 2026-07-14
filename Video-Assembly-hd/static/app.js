const $ = (id) => document.getElementById(id);

let state = { report: null, job: null, checks: [], outputs: [], app_root: '' };
let activeStatus = 'missing';
let selected = new Set();
let cleanupSelected = new Set();
let pollTimer = null;
let lastJobStatus = 'idle';
let toastTimer = null;
let stickerLibrary = null;
let randomStickerMode = false;

const statusLabels = {
  missing: '待拼接',
  done: '已有成品',
  archived: '已归档',
  invalid: '异常',
};

const defaultSticker = Object.freeze({
  enabled: false,
  text: '',
  style: 'tiktok',
  position: 'top',
  timing: 'full',
  start: 0,
  end: 3,
});

const stickerStyleLabels = {
  serif: '粗体衬线',
  bubbly: '气泡卡通',
  tiktok: 'TikTok Sans',
  cinematic: '电影字幕',
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function basename(path) {
  return String(path || '').split('/').filter(Boolean).pop() || '';
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatScanTime(value) {
  if (!value) return '尚未扫描';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `扫描于 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
}

function normalizeSticker(value = {}) {
  const style = Object.hasOwn(stickerStyleLabels, value.style) ? value.style : defaultSticker.style;
  const position = ['top', 'center', 'bottom'].includes(value.position) ? value.position : defaultSticker.position;
  const timing = ['full', 'custom'].includes(value.timing) ? value.timing : defaultSticker.timing;
  return {
    enabled: value.enabled === true,
    text: String(value.text || '').replace(/\s+/g, ' ').trim().slice(0, 36),
    style,
    position,
    timing,
    start: Number.isFinite(Number(value.start)) ? Number(value.start) : defaultSticker.start,
    end: Number.isFinite(Number(value.end)) ? Number(value.end) : defaultSticker.end,
  };
}

function checkedValue(name, fallback) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value || fallback;
}

function setCheckedValue(name, value) {
  const input = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (input) input.checked = true;
}

function stickerFromForm() {
  return normalizeSticker({
    enabled: $('stickerEnabled').checked,
    text: $('stickerText').value,
    style: checkedValue('stickerStyle', defaultSticker.style),
    position: checkedValue('stickerPosition', defaultSticker.position),
    timing: checkedValue('stickerTiming', defaultSticker.timing),
    start: $('stickerStart').value,
    end: $('stickerEnd').value,
  });
}

function selectedStickerConfig() {
  const items = reportItems('missing').filter((item) => selected.has(item.script_dir));
  if (!items.length) return normalizeSticker(defaultSticker);
  const configs = items.map((item) => normalizeSticker(item.sticker));
  const first = JSON.stringify(configs[0]);
  return configs.every((config) => JSON.stringify(config) === first)
    ? configs[0]
    : normalizeSticker(defaultSticker);
}

function stickerFormIsValid(options = stickerFromForm()) {
  if (!options.enabled) return true;
  if (!options.text || options.text.length > 36) return false;
  if (options.timing === 'custom') {
    return options.start >= 0 && options.end - options.start >= 0.4;
  }
  return true;
}

function updateStickerDesigner() {
  const options = stickerFromForm();
  const enabled = options.enabled;
  $('stickerToggleState').textContent = enabled ? randomStickerMode ? '已启用 · 文案随机' : '已启用' : '已关闭';
  $('stickerText').disabled = !enabled;
  ['stickerStyleField', 'stickerPositionField', 'stickerTimingField'].forEach((id) => {
    $(id).disabled = !enabled;
  });
  const custom = enabled && options.timing === 'custom';
  $('stickerCustomTiming').hidden = !custom;
  $('stickerStart').disabled = !custom;
  $('stickerEnd').disabled = !custom;
  $('stickerTextCount').textContent = `${options.text.length} / 36`;
  $('stickerPreviewStyle').textContent = stickerStyleLabels[options.style];
  $('stickerPreviewFrame').classList.toggle('disabled', !enabled);
  $('stickerPreviewText').className = `stickerPreviewText preview-${options.style} preview-${options.position}`;
  $('stickerPreviewText').textContent = options.text || '文字贴纸';
  $('stickerPreviewText').style.fontSize = options.text.length > 28 ? '9px' : options.text.length > 18 ? '10px' : '12px';
  const valid = stickerFormIsValid(options);
  $('stickerText').setAttribute('aria-invalid', String(enabled && !options.text));
  $('stickerStart').setAttribute('aria-invalid', String(custom && !valid));
  $('stickerEnd').setAttribute('aria-invalid', String(custom && !valid));
  $('confirmRunBtn').disabled = !valid;
}

function applyStickerToForm(value) {
  const options = normalizeSticker(value);
  $('stickerEnabled').checked = options.enabled;
  $('stickerText').value = options.text;
  setCheckedValue('stickerStyle', options.style);
  setCheckedValue('stickerPosition', options.position);
  setCheckedValue('stickerTiming', options.timing);
  $('stickerStart').value = options.start;
  $('stickerEnd').value = options.end;
  updateStickerDesigner();
}

function replaceSelectOptions(select, options) {
  select.replaceChildren(...options.map(({ value, label }) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    return option;
  }));
}

function resetStickerLibrary(message = '请先选择同一产品') {
  stickerLibrary = null;
  setRandomStickerMode(false);
  $('stickerLibraryProduct').textContent = message;
  replaceSelectOptions($('stickerCountry'), [{ value: '', label: '暂无可选国家' }]);
  replaceSelectOptions($('stickerPreset'), [{ value: '', label: '手动输入' }]);
  $('stickerCountry').disabled = true;
  $('stickerPreset').disabled = true;
  $('randomStickerBtn').disabled = true;
  $('stickerPresetTranslation').textContent = '仍可在下方手动输入贴纸文字';
}

function currentStickerCountry() {
  return stickerLibrary?.countries?.find((country) => country.code === $('stickerCountry').value) || null;
}

function currentStickerPreset() {
  return currentStickerCountry()?.presets?.find((preset) => preset.id === $('stickerPreset').value) || null;
}

function populateStickerPresets(preferredText = '') {
  const country = currentStickerCountry();
  const presets = country?.presets || [];
  replaceSelectOptions($('stickerPreset'), [
    { value: '', label: '手动输入' },
    ...presets.map((preset) => ({ value: preset.id, label: `${preset.id} · ${preset.text}` })),
  ]);
  const matched = presets.find((preset) => preset.text === preferredText);
  $('stickerPreset').value = matched?.id || '';
  $('stickerPreset').disabled = presets.length === 0;
  $('randomStickerBtn').disabled = presets.length === 0;
  $('stickerPresetTranslation').textContent = matched?.translation || '选择预设后显示中文释义';
}

function setRandomStickerMode(enabled) {
  randomStickerMode = enabled;
  $('randomStickerBtn').classList.toggle('active', enabled);
  $('randomStickerBtn').textContent = enabled ? '已开启随机' : '随机分配';
}

async function loadStickerLibraryForSelection() {
  resetStickerLibrary('正在读取产品与国家…');
  try {
    const data = await api('/api/sticker-library', {
      method: 'POST',
      body: JSON.stringify({
        scan_id: state.report?.scan_id || '',
        script_dirs: [...selected],
      }),
    });
    if (!data.library?.available) {
      resetStickerLibrary(data.library?.reason || '该产品暂无文字贴纸库');
      return;
    }
    stickerLibrary = data.library;
    $('stickerLibraryProduct').textContent = stickerLibrary.product;
    replaceSelectOptions(
      $('stickerCountry'),
      stickerLibrary.countries.map((country) => ({
        value: country.code,
        label: `${country.name} (${country.code})`,
      })),
    );
    $('stickerCountry').disabled = false;
    const existingText = $('stickerText').value.trim();
    const matchedCountry = stickerLibrary.countries.find((country) => (
      country.presets.some((preset) => preset.text === existingText)
    ));
    $('stickerCountry').value = matchedCountry?.code || stickerLibrary.countries[0].code;
    populateStickerPresets(existingText);
  } catch (error) {
    resetStickerLibrary(error.message);
  }
}

function applyStickerPreset() {
  const preset = currentStickerPreset();
  if (!preset) {
    $('stickerPresetTranslation').textContent = '选择预设后显示中文释义';
    return;
  }
  $('stickerText').value = preset.text;
  $('stickerPresetTranslation').textContent = preset.translation;
  updateStickerDesigner();
}

function enableRandomStickerMode() {
  const presets = currentStickerCountry()?.presets || [];
  if (!presets.length) return;
  const currentId = $('stickerPreset').value;
  const candidates = presets.length > 1 ? presets.filter((preset) => preset.id !== currentId) : presets;
  const preview = candidates[Math.floor(Math.random() * candidates.length)];
  $('stickerPreset').value = preview.id;
  $('stickerEnabled').checked = true;
  setRandomStickerMode(true);
  applyStickerPreset();
  $('stickerPresetTranslation').textContent = `随机分配已开启：每条视频使用不同文案。当前预览：${preview.translation}`;
}

function handleStickerTextInput() {
  setRandomStickerMode(false);
  const preset = currentStickerPreset();
  if (preset && preset.text !== $('stickerText').value.trim()) {
    $('stickerPreset').value = '';
    $('stickerPresetTranslation').textContent = '已切换为手动输入';
  }
  updateStickerDesigner();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function showToast(message, isError = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').className = `toast show${isError ? ' error' : ''}`;
  toastTimer = setTimeout(() => { $('toast').className = 'toast'; }, 2600);
}

function reportItems(status = activeStatus) {
  return (state.report?.items || []).filter((item) => item.status === status);
}

function syncSelection() {
  const valid = new Set(reportItems('missing').map((item) => item.script_dir));
  selected = new Set([...selected].filter((path) => valid.has(path)));
  const validCleanup = new Set(
    reportItems('done').filter((item) => item.cleanup_eligible).map((item) => item.script_dir),
  );
  cleanupSelected = new Set([...cleanupSelected].filter((path) => validCleanup.has(path)));
}

function renderChecks() {
  const allReady = state.checks.length > 0 && state.checks.every((item) => item.ok);
  $('runtimeBadge').textContent = allReady ? '离线环境就绪' : '离线依赖缺失';
  $('runtimeBadge').className = `badge ${allReady ? 'ok' : 'error'}`;
  $('runtimeChecks').innerHTML = state.checks.map((item) => `
    <div class="checkRow ${item.ok ? '' : 'fail'}" title="${escapeHtml(item.path)}">
      <i class="checkDot"></i>
      <span>${escapeHtml(item.label)}</span>
      <code>${item.ok ? '就绪' : '缺失'}</code>
    </div>
  `).join('');
}

function renderCounts() {
  const counts = state.report?.by_status || {};
  $('missingCount').textContent = counts.missing || 0;
  $('doneCount').textContent = counts.done || 0;
  $('archivedCount').textContent = counts.archived || 0;
  $('invalidCount').textContent = counts.invalid || 0;
  document.querySelectorAll('.stat').forEach((button) => {
    button.classList.toggle('active', button.dataset.status === activeStatus);
  });
}

function groupedItems(items) {
  const groups = new Map();
  items.forEach((item) => {
    const key = `${item.model}/${item.date}/${item.product}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  return groups;
}

function taskRow(item) {
  const scriptName = basename(item.script_dir);
  const clips = (item.video_paths || []).length;
  const sticker = normalizeSticker(item.sticker);
  const stickerMeta = sticker.enabled ? ` · 贴纸 ${stickerStyleLabels[sticker.style]}` : '';
  const cleanupMode = item.status === 'done' && item.cleanup_eligible;
  const selectable = item.status === 'missing' || cleanupMode;
  const selectedAttr = (cleanupMode ? cleanupSelected : selected).has(item.script_dir) ? 'checked' : '';
  const checkbox = selectable
    ? `<input class="taskCheck" type="checkbox" data-mode="${cleanupMode ? 'cleanup' : 'assemble'}" data-script-dir="${escapeHtml(item.script_dir)}" ${selectedAttr} aria-label="选择 ${escapeHtml(scriptName)}" />`
    : '';
  const issue = (item.issues || []).join('、');
  const meta = item.status === 'missing'
    ? `${clips} 个片段 · ${basename(item.md_path)}${stickerMeta}`
    : item.status === 'done'
      ? `${basename(item.output_path)}${item.cleanup_eligible ? ` · 待清理 ${item.cleanup_file_count} 个文件 / ${formatBytes(item.cleanup_bytes)}` : ''}`
      : item.status === 'archived'
        ? '脚本保留，待拼接素材与成品均未匹配'
        : (issue || '目录结构不完整');
  const pillLabel = item.status === 'done'
    ? item.cleanup_eligible ? '待清理' : item.media_cleaned ? '已清理' : '已有成品'
    : statusLabels[item.status] || item.status;
  const pillClass = item.status === 'done'
    ? item.cleanup_eligible ? 'cleanup' : item.media_cleaned ? 'cleaned' : 'done'
    : item.status;
  return `
    <div class="taskRow ${selectable ? '' : 'readonly'}">
      ${checkbox}
      <div class="taskMain">
        <div class="taskName">${escapeHtml(scriptName)}</div>
        <div class="taskMeta"><span>${escapeHtml(meta)}</span></div>
      </div>
      <span class="statusPill ${pillClass}">${pillLabel}</span>
    </div>
  `;
}

function renderTasks() {
  const items = reportItems();
  if (!items.length) {
    const messages = {
      missing: '没有待拼接项目',
      done: '没有本地成品记录',
      archived: '没有已归档脚本',
      invalid: '没有异常项目',
    };
    $('taskList').innerHTML = `<div class="emptyState">${messages[activeStatus]}</div>`;
  } else {
    $('taskList').innerHTML = [...groupedItems(items)].map(([key, rows]) => {
      const parts = key.split('/');
      return `
        <div class="groupHead"><span>${escapeHtml(parts[2])}</span><span>${escapeHtml(parts[0])} · ${escapeHtml(parts[1])} · ${rows.length} 条</span></div>
        ${rows.map(taskRow).join('')}
      `;
    }).join('');
  }
  const selectableItems = activeStatus === 'missing'
    ? reportItems('missing')
    : activeStatus === 'done'
      ? reportItems('done').filter((item) => item.cleanup_eligible)
      : [];
  const selection = activeStatus === 'done' ? cleanupSelected : selected;
  const selectablePaths = selectableItems.map((item) => item.script_dir);
  const allSelected = selectablePaths.length > 0 && selectablePaths.every((path) => selection.has(path));
  $('selectAll').checked = allSelected;
  $('selectAll').indeterminate = selectablePaths.some((path) => selection.has(path)) && !allSelected;
  $('selectAll').disabled = selectablePaths.length === 0;
  $('selectionSummary').textContent = `已选择 ${activeStatus === 'missing' || activeStatus === 'done' ? selection.size : 0} 项`;
  $('scanMeta').textContent = formatScanTime(state.report?.scanned_at);
}

function renderQueueState() {
  const missing = Number(state.report?.by_status?.missing || 0);
  const cleanupAvailable = reportItems('done').filter((item) => item.cleanup_eligible).length;
  const running = Boolean(state.job?.running);
  if (running) {
    $('queueState').textContent = '拼接执行中';
    $('queueHint').textContent = '运行结束后会自动重新扫描';
  } else if (activeStatus === 'done' && cleanupAvailable > 0) {
    $('queueState').textContent = '等待成品确认';
    $('queueHint').textContent = `${cleanupAvailable} 个已拼接项目仍保留源素材，清理前需二次确认`;
  } else if (activeStatus === 'done') {
    $('queueState').textContent = '无待清理素材';
    $('queueHint').textContent = '已清理项目仅保留脚本、记录和成品';
  } else if (missing > 0) {
    $('queueState').textContent = '等待确认';
    $('queueHint').textContent = `发现 ${missing} 个待拼接项目，确认前不会执行`;
  } else {
    $('queueState').textContent = '队列已清空';
    $('queueHint').textContent = '当前没有需要拼接的片段';
  }
  const ffprobeReady = state.checks.some((item) => item.key === 'ffprobe' && item.ok);
  $('scanBtn').disabled = running;
  $('assembleBtn').hidden = activeStatus !== 'missing';
  $('assembleBtn').disabled = running || selected.size === 0 || !state.offline_ready;
  $('cleanupBtn').hidden = activeStatus !== 'done';
  $('cleanupBtn').disabled = running || cleanupSelected.size === 0 || !ffprobeReady;
  $('cancelBtn').disabled = !running;
}

function jobLabel(status) {
  return {
    idle: '空闲', queued: '排队中', running: '拼接中', cancelling: '终止中',
    completed: '已完成', cancelled: '已终止', failed: '失败',
  }[status] || status;
}

function renderJob() {
  const job = state.job || {};
  const percent = Number(job.percent || 0);
  $('jobBadge').textContent = jobLabel(job.status || 'idle');
  $('jobBadge').className = `badge ${job.status === 'completed' ? 'ok' : job.status === 'failed' ? 'error' : job.running ? 'warn' : ''}`;
  $('progressSummary').textContent = job.total ? `${jobLabel(job.status)}：${job.completed || 0} / ${job.total}` : '暂无任务';
  $('progressPercent').textContent = `${percent}%`;
  $('progressFill').style.width = `${Math.max(0, Math.min(100, percent))}%`;
  $('progressCurrent').textContent = job.error || job.current || (job.status === 'completed' ? '本次拼接已完成' : '等待确认');
  const logs = job.logs || [];
  $('logs').textContent = logs.length ? logs.join('\n') : '暂无运行日志';
  $('logs').classList.toggle('empty', logs.length === 0);
  $('logs').scrollTop = $('logs').scrollHeight;
  $('logState').textContent = job.running ? '实时更新' : '本地进程';
}

function renderOutputs() {
  const outputs = state.outputs || [];
  $('outputs').innerHTML = outputs.length ? outputs.map((item) => `
    <div class="outputItem">
      <div>
        <div class="outputName">${escapeHtml(item.name)}</div>
        <div class="outputMeta">${escapeHtml(item.relative)} · ${formatBytes(item.size)}</div>
      </div>
      <button class="iconButton small openPathBtn" type="button" title="打开成品" aria-label="打开成品" data-path="${escapeHtml(item.path)}">↗</button>
    </div>
  `).join('') : '<div class="emptyState compact">暂无成品记录</div>';
}

function render() {
  syncSelection();
  $('pendingPath').textContent = state.report?.pending_root || '未配置';
  $('outputPath').textContent = state.report?.output_root || '未配置';
  renderChecks();
  renderCounts();
  renderTasks();
  renderJob();
  renderOutputs();
  renderQueueState();
}

async function refreshState(showError = true) {
  try {
    state = await api('/api/state');
    render();
    managePolling();
  } catch (error) {
    if (showError) showToast(error.message, true);
  }
}

async function scan() {
  $('scanBtn').disabled = true;
  $('queueState').textContent = '正在扫描';
  try {
    const data = await api('/api/scan', { method: 'POST', body: '{}' });
    state.report = data.report;
    state.outputs = data.outputs || state.outputs;
    selected = new Set(reportItems('missing').map((item) => item.script_dir));
    activeStatus = 'missing';
    render();
    showToast(`扫描完成：${state.report.by_status?.missing || 0} 个待拼接项目`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    $('scanBtn').disabled = false;
  }
}

function openConfirmModal() {
  if (!selected.size) {
    showToast('请先选择待拼接项目', true);
    return;
  }
  $('confirmCount').textContent = selected.size;
  $('confirmOutputPath').textContent = state.report?.output_root || '';
  setRandomStickerMode(false);
  applyStickerToForm(selectedStickerConfig());
  $('confirmModal').hidden = false;
  void loadStickerLibraryForSelection();
  ($('stickerEnabled').checked ? $('stickerText') : $('confirmRunBtn')).focus();
}

function closeConfirmModal() {
  $('confirmModal').hidden = true;
}

function openCleanupModal() {
  if (!cleanupSelected.size) {
    showToast('请先选择已有成品且待清理的项目', true);
    return;
  }
  const items = reportItems('done').filter((item) => cleanupSelected.has(item.script_dir));
  const fileCount = items.reduce((sum, item) => sum + Number(item.cleanup_file_count || 0), 0);
  const bytes = items.reduce((sum, item) => sum + Number(item.cleanup_bytes || 0), 0);
  $('cleanupCount').textContent = items.length;
  $('cleanupFileSummary').textContent = `${fileCount} 个片段、图片或锁文件 · ${formatBytes(bytes)}`;
  $('cleanupVerified').checked = false;
  $('confirmCleanupBtn').disabled = true;
  $('cleanupModal').hidden = false;
  $('cleanupVerified').focus();
}

function closeCleanupModal() {
  $('cleanupModal').hidden = true;
  $('cleanupVerified').checked = false;
  $('confirmCleanupBtn').disabled = true;
}

async function cleanupMedia() {
  if (!$('cleanupVerified').checked) return;
  $('confirmCleanupBtn').disabled = true;
  try {
    const data = await api('/api/cleanup', {
      method: 'POST',
      body: JSON.stringify({
        confirmed: true,
        verified: true,
        scan_id: state.report?.scan_id || '',
        script_dirs: [...cleanupSelected],
      }),
    });
    state.report = data.report;
    state.outputs = data.outputs || state.outputs;
    cleanupSelected = new Set();
    closeCleanupModal();
    render();
    showToast(`清理完成：已删除 ${data.deleted_count || 0} 个素材文件`);
  } catch (error) {
    showToast(error.message, true);
    $('confirmCleanupBtn').disabled = !$('cleanupVerified').checked;
  }
}

async function startAssembly() {
  const sticker = stickerFromForm();
  if (!stickerFormIsValid(sticker)) {
    showToast(sticker.text ? '自定义显示时间至少需要 0.4 秒' : '请输入贴纸文字', true);
    return;
  }
  $('confirmRunBtn').disabled = true;
  try {
    const data = await api('/api/assemble', {
      method: 'POST',
      body: JSON.stringify({
        confirmed: true,
        scan_id: state.report?.scan_id || '',
        script_dirs: [...selected],
        sticker,
        sticker_random_country: randomStickerMode ? $('stickerCountry').value : '',
      }),
    });
    state.job = data.job;
    closeConfirmModal();
    renderJob();
    renderQueueState();
    managePolling();
    showToast('已确认，开始本地拼接');
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (!$('confirmModal').hidden) updateStickerDesigner();
  }
}

async function cancelJob() {
  try {
    const data = await api('/api/cancel', { method: 'POST', body: '{}' });
    state.job = data.job;
    renderJob();
    renderQueueState();
    showToast('正在终止拼接任务');
  } catch (error) {
    showToast(error.message, true);
  }
}

async function openPath(path) {
  if (!path) return;
  try {
    await api('/api/open', { method: 'POST', body: JSON.stringify({ path }) });
  } catch (error) {
    showToast(error.message, true);
  }
}

function managePolling() {
  const running = Boolean(state.job?.running);
  if (running && !pollTimer) {
    pollTimer = setInterval(async () => {
      try {
        const data = await api('/api/job');
        state.job = data.job;
        renderJob();
        renderQueueState();
        if (!state.job.running) {
          clearInterval(pollTimer);
          pollTimer = null;
          await refreshState(false);
          if (lastJobStatus === 'running' || lastJobStatus === 'queued' || lastJobStatus === 'cancelling') {
            showToast(state.job.status === 'completed' ? '拼接完成，扫描结果已更新' : jobLabel(state.job.status), state.job.status === 'failed');
          }
        }
        lastJobStatus = state.job.status;
      } catch (error) {
        clearInterval(pollTimer);
        pollTimer = null;
        showToast(error.message, true);
      }
    }, 1000);
  } else if (!running && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  lastJobStatus = state.job?.status || 'idle';
}

document.querySelector('.statStrip').addEventListener('click', (event) => {
  const button = event.target.closest('.stat');
  if (!button) return;
  activeStatus = button.dataset.status;
  renderCounts();
  renderTasks();
  renderQueueState();
});

$('taskList').addEventListener('change', (event) => {
  const checkbox = event.target.closest('.taskCheck');
  if (!checkbox) return;
  const selection = checkbox.dataset.mode === 'cleanup' ? cleanupSelected : selected;
  if (checkbox.checked) selection.add(checkbox.dataset.scriptDir);
  else selection.delete(checkbox.dataset.scriptDir);
  renderTasks();
  renderQueueState();
});

$('selectAll').addEventListener('change', (event) => {
  const items = activeStatus === 'done'
    ? reportItems('done').filter((item) => item.cleanup_eligible)
    : activeStatus === 'missing' ? reportItems('missing') : [];
  const selection = activeStatus === 'done' ? cleanupSelected : selected;
  items.forEach((item) => {
    if (event.target.checked) selection.add(item.script_dir);
    else selection.delete(item.script_dir);
  });
  renderTasks();
  renderQueueState();
});

$('outputs').addEventListener('click', (event) => {
  const button = event.target.closest('.openPathBtn');
  if (button) openPath(button.dataset.path);
});

$('scanBtn').addEventListener('click', scan);
$('assembleBtn').addEventListener('click', openConfirmModal);
$('cleanupBtn').addEventListener('click', openCleanupModal);
$('cancelBtn').addEventListener('click', cancelJob);
$('refreshBtn').addEventListener('click', () => refreshState());
$('closeModalBtn').addEventListener('click', closeConfirmModal);
$('cancelModalBtn').addEventListener('click', closeConfirmModal);
$('confirmRunBtn').addEventListener('click', startAssembly);
$('confirmModal').addEventListener('click', (event) => { if (event.target === $('confirmModal')) closeConfirmModal(); });
$('stickerEnabled').addEventListener('change', () => {
  if (!$('stickerEnabled').checked) setRandomStickerMode(false);
  updateStickerDesigner();
});
$('stickerText').addEventListener('input', handleStickerTextInput);
$('stickerCountry').addEventListener('change', () => {
  setRandomStickerMode(false);
  populateStickerPresets();
});
$('stickerPreset').addEventListener('change', () => {
  setRandomStickerMode(false);
  applyStickerPreset();
});
$('randomStickerBtn').addEventListener('click', enableRandomStickerMode);
$('stickerStart').addEventListener('input', updateStickerDesigner);
$('stickerEnd').addEventListener('input', updateStickerDesigner);
document.querySelectorAll('input[name="stickerStyle"], input[name="stickerPosition"], input[name="stickerTiming"]').forEach((input) => {
  input.addEventListener('change', updateStickerDesigner);
});
$('closeCleanupModalBtn').addEventListener('click', closeCleanupModal);
$('cancelCleanupModalBtn').addEventListener('click', closeCleanupModal);
$('cleanupVerified').addEventListener('change', (event) => { $('confirmCleanupBtn').disabled = !event.target.checked; });
$('confirmCleanupBtn').addEventListener('click', cleanupMedia);
$('cleanupModal').addEventListener('click', (event) => { if (event.target === $('cleanupModal')) closeCleanupModal(); });
$('pendingPath').addEventListener('click', () => openPath(state.report?.pending_root));
$('outputPath').addEventListener('click', () => openPath(state.report?.output_root));
$('openOutputBtn').addEventListener('click', () => openPath(state.report?.output_root));
$('openAppBtn').addEventListener('click', () => openPath(state.app_root));

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !$('confirmModal').hidden) closeConfirmModal();
  if (event.key === 'Escape' && !$('cleanupModal').hidden) closeCleanupModal();
});

refreshState();
