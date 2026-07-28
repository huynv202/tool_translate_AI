const $ = (selector) => document.querySelector(selector);
const form = $('#studioForm');
const dialog = $('#settingsDialog');
const videoInput = $('#videoFile');
let pollTimer = null;
let currentJobId = null;
let currentDialogue = [];
let currentVideoUrl = null;
let batchDirectoryHandle = null;
let selectedCueIndex = 0;
let updatingCueId = null;

function updateProjectAssetLinks(assets = {}) {
  const links = [
    ['#downloadProjectVideo', assets.video],
    ['#downloadProjectVoice', assets.voice],
    ['#downloadProjectSubtitles', assets.subtitles]
  ];
  links.forEach(([selector, url]) => {
    const link = $(selector);
    if (url) {
      link.href = url; link.classList.remove('disabled'); link.setAttribute('aria-disabled', 'false');
    } else {
      link.removeAttribute('href'); link.classList.add('disabled'); link.setAttribute('aria-disabled', 'true');
    }
  });
}

function toast(message) {
  const node = $('#toast'); node.textContent = message; node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 2600);
}

function setRouterStatus(message, state = '') {
  const status = $('#routerStatus');
  status.className = `router-status ${state}`.trim();
  status.querySelector('span').textContent = message;
}

function loadConfig() {
  const savedWhisper = localStorage.getItem('whisperModel');
  const whisperModel = ['base', 'small', 'medium'].includes(savedWhisper) ? savedWhisper : 'small';
  if (savedWhisper !== whisperModel) localStorage.setItem('whisperModel', whisperModel);
  $('#routerKey').value = sessionStorage.getItem('routerKey') || '';
  $('#routerUrl').value = localStorage.getItem('routerUrl') || 'http://localhost:20128/v1';
  const storedModel = localStorage.getItem('textModel') || '';
  const savedModel = storedModel.toLowerCase().includes('gemini') ? storedModel : '';
  if (storedModel && !savedModel) localStorage.removeItem('textModel');
  const modelSelect = $('#textModel');
  if (savedModel && ![...modelSelect.options].some((item) => item.value === savedModel)) {
    modelSelect.add(new Option(savedModel, savedModel));
  }
  modelSelect.value = savedModel;
  const storedScriptModel = localStorage.getItem('scriptModel') || '';
  const scriptModel = /gpt|claude/i.test(storedScriptModel) ? storedScriptModel : '';
  if (storedScriptModel && !scriptModel) localStorage.removeItem('scriptModel');
  const scriptSelect = $('#scriptModel');
  if (scriptModel && ![...scriptSelect.options].some((item) => item.value === scriptModel)) {
    scriptSelect.add(new Option(scriptModel, scriptModel));
  }
  scriptSelect.value = scriptModel;
  $('#whisperModel').value = whisperModel;
}

$('#openSettings').addEventListener('click', () => {
  loadConfig(); setRouterStatus('Sẵn sàng kiểm tra kết nối 9Router.'); dialog.showModal();
});
$('#routerForm').addEventListener('submit', (event) => {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault();
  sessionStorage.setItem('routerKey', $('#routerKey').value);
  localStorage.setItem('routerUrl', $('#routerUrl').value);
  localStorage.setItem('textModel', $('#textModel').value);
  localStorage.setItem('scriptModel', $('#scriptModel').value);
  localStorage.setItem('whisperModel', $('#whisperModel').value);
  setRouterStatus('Đã lưu cấu hình Gemini, model kịch bản và Whisper thành công.', 'success');
  setTimeout(() => { dialog.close(); toast('Đã lưu kết nối 9Router'); }, 650);
});

$('#probeRouter').addEventListener('click', async () => {
  const button = $('#probeRouter');
  if (!$('#routerKey').value || !$('#routerUrl').value) { setRouterStatus('Hãy nhập API key và Base URL.', 'error'); return; }
  button.disabled = true; button.textContent = 'ĐANG KẾT NỐI...';
  setRouterStatus('Đang kết nối và tải danh sách model từ 9Router...', 'loading');
  try {
    const response = await fetch('/api/router/models', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: $('#routerKey').value, base_url: $('#routerUrl').value })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Không tải được model');
    const select = $('#textModel'); const previous = localStorage.getItem('textModel');
    select.innerHTML = '<option value="">Chọn model đã được auth</option>';
    const geminiModels = payload.models.filter((model) => model.id.toLowerCase().includes('gemini'));
    const availableModels = geminiModels.length ? geminiModels : payload.models;
    const priority = { gc: 0, ag: 1, gh: 2, gemini: 9 };
    availableModels.sort((a, b) => (priority[a.provider] ?? 5) - (priority[b.provider] ?? 5));
    availableModels.forEach((model) => select.add(new Option(`[${model.provider}] ${model.id}`, model.id)));
    if (availableModels.some((model) => model.id === previous)) select.value = previous;
    const scriptSelect = $('#scriptModel'); const previousScript = localStorage.getItem('scriptModel');
    const scriptModels = payload.models.filter((model) => /gpt|claude/i.test(model.id));
    const scriptPriority = { cx: 0, gh: 1, claude: 2, anthropic: 3, openai: 9 };
    scriptModels.sort((a, b) => (scriptPriority[a.provider] ?? 5) - (scriptPriority[b.provider] ?? 5));
    scriptSelect.innerHTML = '<option value="">Chọn GPT hoặc Claude đã được auth</option>';
    scriptModels.forEach((model) => scriptSelect.add(new Option(`[${model.provider}] ${model.id}`, model.id)));
    if (scriptModels.some((model) => model.id === previousScript)) scriptSelect.value = previousScript;
    setRouterStatus(`Kết nối thành công: ${geminiModels.length} Gemini · ${scriptModels.length} model kịch bản.`, 'success');
  } catch (error) { setRouterStatus(error.message, 'error'); }
  finally { button.disabled = false; button.textContent = 'TẢI DANH SÁCH MODEL'; }
});

$('#testRouterModel').addEventListener('click', async () => {
  const models = [$('#textModel').value, $('#scriptModel').value]; const button = $('#testRouterModel');
  if (models.some((model) => !model)) { setRouterStatus('Hãy chọn Gemini và model viết kịch bản trước khi test.', 'error'); return; }
  button.disabled = true; button.textContent = 'ĐANG TEST MODEL...';
  setRouterStatus('Đang gửi yêu cầu thử tới Gemini và model viết kịch bản...', 'loading');
  try {
    for (const model of models) {
      const response = await fetch('/api/router/test-model', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: $('#routerKey').value, base_url: $('#routerUrl').value, model })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(`${model}: ${payload.detail || 'test thất bại'}`);
    }
    setRouterStatus('Gemini và model viết kịch bản đều hoạt động. Bạn có thể lưu cấu hình.', 'success');
  } catch (error) { setRouterStatus(error.message, 'error'); }
  finally { button.disabled = false; button.textContent = 'TEST 2 MODEL'; }
});

document.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach((item) => item.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach((item) => item.classList.remove('active'));
  tab.classList.add('active'); $(`#${tab.dataset.tab}Pane`).classList.add('active');
}));

const dropzone = $('#dropzone');
['dragenter', 'dragover'].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add('drag'); }));
['dragleave', 'drop'].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove('drag'); }));
dropzone.addEventListener('drop', (event) => { videoInput.files = event.dataTransfer.files; showVideos(); });
videoInput.addEventListener('change', showVideos);

function showVideos() {
  const files = [...videoInput.files];
  if (!files.length) return;
  if (files.length > 1) { videoInput.value = ''; toast('Hiện tại mỗi project chỉ nhận một video'); return; }
  const file = files[0];
  $('#fileTitle').textContent = file.name;
  $('#fileMeta').textContent = `${(file.size / 1048576).toFixed(1)} MB · sẽ upload an toàn theo từng phần`;
  $('#previewName').textContent = file.name;
  $('#sourcePreview').src = URL.createObjectURL(file);
  $('#miniPreview').hidden = false;
}

$('#removeVideo').addEventListener('click', () => {
  videoInput.value = ''; $('#miniPreview').hidden = true;
  $('#fileTitle').textContent = 'KÉO 1 VIDEO VÀO ĐÂY';
  $('#fileMeta').textContent = 'MP4, MOV, WEBM · mỗi project dùng một video';
  $('#batchList').innerHTML = '<div class="batch-empty">Chưa có video trong hàng đợi</div>';
});

function renderBatchList(items) {
  $('#batchList').innerHTML = items.map((item, index) => `<div class="batch-item ${item.status}" data-batch-index="${index}"><b>${String(index + 1).padStart(2, '0')}</b><span>${item.name}</span><small>${item.message}</small></div>`).join('');
}

function updateBatchItem(index, status, message) {
  const item = document.querySelector(`[data-batch-index="${index}"]`);
  if (!item) return; item.className = `batch-item ${status}`; item.querySelector('small').textContent = message;
}

async function chooseDraftFolder() {
  if (!('showDirectoryPicker' in window)) return null;
  batchDirectoryHandle = await window.showDirectoryPicker({mode: 'readwrite'});
  $('#draftFolderStatus').textContent = `Bản nháp sẽ tự lưu vào: ${batchDirectoryHandle.name}`;
  return batchDirectoryHandle;
}

$('#chooseDraftFolder').addEventListener('click', async () => {
  try { await chooseDraftFolder(); } catch (error) { if (error.name !== 'AbortError') toast(error.message); }
});

document.querySelectorAll('input[type=range]').forEach((input) => input.addEventListener('input', () => {
  const output = $(`#${input.dataset.output}`); const value = Number(input.value);
  if (input.dataset.format === 'percentZoom') output.value = `${Math.round((value - 1) * 100)}%`;
  if (input.dataset.format === 'percent') output.value = `${Math.round(value * 100)}%`;
  if (input.dataset.format === 'seconds') output.value = `${value.toFixed(1)}s`;
}));

$('input[name=music_file]').addEventListener('change', (event) => {
  $('#musicName').textContent = event.target.files[0]?.name || 'Không bắt buộc';
});
$('input[name=logo_file]').addEventListener('change', (event) => {
  $('#logoName').textContent = event.target.files[0]?.name || 'PNG nền trong suốt';
});
$('input[name=voice_reference]').addEventListener('change', (event) => {
  $('#voiceReferenceName').textContent = event.target.files[0]?.name || 'Không bắt buộc · âm thanh sạch, một người nói';
});

$('#targetLanguage').addEventListener('change', updateVoices);
$('#contentMode').addEventListener('change', (event) => {
  if (event.target.value === 'creator-analysis') toast('Chế độ này tạo lời kể phân tích, không dịch sát lời thoại gốc');
});
$('#fillEditorialSample').addEventListener('click', async () => {
  const topic = $('#editorialTopic').value.trim();
  if (!topic) { toast('Hãy nhập chủ đề video trước'); $('#editorialTopic').focus(); return; }
  const apiKey = sessionStorage.getItem('routerKey');
  const model = localStorage.getItem('scriptModel');
  if (!apiKey || !model) { loadConfig(); dialog.showModal(); toast('Hãy cấu hình 9Router và model biên tập trước'); return; }
  const button = $('#fillEditorialSample'); button.disabled = true; button.textContent = 'ĐANG XÂY BRIEF...';
  try {
    const response = await fetch('/api/editorial/brief', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        api_key: apiKey,
        base_url: localStorage.getItem('routerUrl') || 'http://localhost:20128/v1',
        model,
        topic,
        description: $('#editorialDescription').value.trim()
      })
    });
    const brief = await response.json();
    if (response.status === 404) throw new Error('Server đang chạy bản cũ. Hãy khởi động lại Viet Transform Studio rồi thử lại.');
    if (!response.ok) throw new Error(brief.detail || 'Không tạo được brief biên tập');
    $('#contentMode').value = 'creator-analysis';
    $('#editorialThesis').value = brief.thesis;
    $('#vietnamAngle').value = brief.vietnam_angle;
    const result = $('#editorialBriefResult'); result.hidden = false;
    result.innerHTML = `<div><span>HOOK ĐỀ XUẤT</span><strong>${escapeHtml(brief.hook)}</strong></div><div><span>CẤU TRÚC BIÊN TẬP</span><ol>${brief.structure.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ol></div><div><span>CẦN NGHIÊN CỨU</span><ul>${brief.research_queries.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul><small>Hãy tìm nguồn thật cho các câu hỏi này và dán URL vào ô Nguồn nghiên cứu.</small></div>`;
    toast('Đã tạo DNA biên tập theo chủ đề');
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = 'TẠO LẠI DNA BIÊN TẬP'; }
});
$('#ttsVoice').addEventListener('change', syncVoiceEngine);
function updateVoices() {
  const language = $('#targetLanguage').value; const voices = [...$('#ttsVoice').options];
  voices.forEach((option) => { option.hidden = option.dataset.lang !== language; });
  const first = voices.find((option) => option.dataset.lang === language);
  if (first) $('#ttsVoice').value = first.value;
  syncVoiceEngine();
}

function syncVoiceEngine() {
  const option = $('#ttsVoice').selectedOptions[0];
  if (option?.dataset.engine) $('#ttsEngine').value = option.dataset.engine;
  const hints = {
    quality: 'Mặc định tốt nhất: XTTS v2 khi đã cài và chấp thuận license, tự fallback Piper.',
    piper: 'Giọng local ổn định cho video dài; lần đầu có thể cần tải model.',
    edge: 'Giọng online tự nhiên hơn nhưng có thể bị giới hạn khi video quá dài.'
  };
  $('#voiceHint').textContent = hints[option?.dataset.engine] || hints.piper;
}

$('#previewVoice').addEventListener('click', async () => {
  const option = $('#ttsVoice').selectedOptions[0]; const button = $('#previewVoice');
  button.disabled = true; button.textContent = 'ĐANG TẠO GIỌNG MẪU...';
  try {
    const response = await fetch('/api/voices/preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({engine: option.dataset.engine, voice: option.value, speaker: option.dataset.speaker ? Number(option.dataset.speaker) : null})});
    if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Không tạo được giọng mẫu'); }
    const audio = $('#voiceAudio'); audio.src = URL.createObjectURL(await response.blob()); audio.hidden = false; await audio.play();
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = '▶ NGHE THỬ GIỌNG'; }
});

async function uploadLargeVideo(file, onProgress) {
  const init = await fetch('/api/uploads', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({filename: file.name, size: file.size, content_type: file.type || 'video/mp4'})});
  const upload = await init.json(); if (!init.ok) throw new Error(upload.detail || 'Không khởi tạo được upload');
  const total = Math.ceil(file.size / upload.chunk_size);
  for (let index = 0; index < total; index += 1) {
    const chunk = file.slice(index * upload.chunk_size, Math.min(file.size, (index + 1) * upload.chunk_size));
    let lastError;
    for (let attempt = 0; attempt < 4; attempt += 1) {
      try {
        const response = await fetch(`/api/uploads/${upload.upload_id}/${index}`, {method: 'PUT', body: chunk});
        if (!response.ok) { const error = await response.json(); throw new Error(error.detail || `Chunk ${index + 1} lỗi`); }
        lastError = null; break;
      } catch (error) { lastError = error; await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1))); }
    }
    if (lastError) throw lastError;
    onProgress(Math.round((index + 1) / total * 100));
  }
  const completed = await fetch(`/api/uploads/${upload.upload_id}/complete`, {method: 'POST'});
  const result = await completed.json(); if (!completed.ok) throw new Error(result.detail || 'Không ghép được file upload');
  return upload.upload_id;
}

function copyFormData(source) {
  const copy = new FormData();
  for (const [key, value] of source.entries()) copy.append(key, value);
  return copy;
}

async function createVideoJob(file, baseData, index) {
  const data = copyFormData(baseData); data.delete('video_file'); data.delete('source_url');
  const uploadId = await uploadLargeVideo(file, (percent) => updateBatchItem(index, 'running', `Đang upload ${percent}%`));
  data.set('upload_id', uploadId);
  const response = await fetch('/api/jobs', {method: 'POST', body: data});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Không thể tạo job');
  return payload.job_id;
}

async function waitForBatchJob(jobId, index) {
  while (true) {
    const response = await fetch(`/api/jobs/${jobId}`); const job = await response.json();
    if (!response.ok) throw new Error(job.detail || 'Không đọc được trạng thái job');
    $('#progressNumber').textContent = `${job.progress}%`; $('#progressBar').style.width = `${job.progress}%`;
    $('#stageList').innerHTML = Object.entries(job.stages).map(([name, status]) => `<div class="stage ${status}"><i></i><span>${name.toUpperCase()}</span></div>`).join('');
    updateBatchItem(index, 'running', `${job.active_stage} · ${job.progress}%`);
    if (job.status === 'completed' || job.status === 'failed') return job;
    await new Promise((resolve) => setTimeout(resolve, 1800));
  }
}

async function retryBatchJob(jobId, index) {
  let job = await waitForBatchJob(jobId, index);
  for (let retry = 1; job.status === 'failed' && retry <= 5; retry += 1) {
    updateBatchItem(index, 'running', `Lỗi · đang thử lại ${retry}/5`);
    const response = await fetch(`/api/jobs/${jobId}/retry`, {method: 'POST'}); const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `Không thể retry lần ${retry}`);
    job = await waitForBatchJob(jobId, index);
  }
  return job;
}

async function saveBatchDraft(videoUrl, filename) {
  if (!batchDirectoryHandle) return false;
  const fileHandle = await batchDirectoryHandle.getFileHandle(filename, {create: true});
  const response = await fetch(videoUrl);
  if (!response.ok || !response.body) throw new Error('Không tải được video bản nháp');
  const writable = await fileHandle.createWritable();
  try { await response.body.pipeTo(writable); }
  catch (error) { await writable.abort(); throw error; }
  return true;
}

async function processBatch(files, baseData) {
  batchRunning = true; $('#production').hidden = false; $('#resultGrid').hidden = true; $('#errorBox').hidden = true;
  $('#production').scrollIntoView({behavior: 'smooth'});
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index]; $('#jobId').textContent = `VIDEO ${index + 1}/${files.length}`;
    try {
      updateBatchItem(index, 'running', 'Đang chuẩn bị upload');
      const jobId = await createVideoJob(file, baseData, index); currentJobId = jobId;
      const job = await retryBatchJob(jobId, index);
      if (job.status !== 'completed') {
        updateBatchItem(index, 'failed paused', 'Đã lỗi sau 5 lần retry · hàng đợi tạm dừng');
        $('#errorBox').hidden = false; $('#errorMessage').textContent = `Video ${file.name} vẫn lỗi sau 5 lần thử lại: ${job.error}`;
        toast('Hàng đợi đã dừng tại video bị lỗi'); break;
      }
      const draftName = `${String(index + 1).padStart(2, '0')}-${file.name.replace(/\.[^.]+$/, '')}-draft.mp4`;
      const saved = await saveBatchDraft(job.video_url, draftName);
      updateBatchItem(index, 'completed', saved ? 'Hoàn tất · đã lưu bản nháp vào máy' : 'Hoàn tất · bản nháp đang giữ trên server');
      currentVideoUrl = job.video_url;
    } catch (error) {
      updateBatchItem(index, 'failed paused', `Hàng đợi dừng · ${error.message}`);
      $('#errorBox').hidden = false; $('#errorMessage').textContent = error.message; break;
    }
  }
  batchRunning = false; resetButton();
}

$('#scriptEditor').addEventListener('input', updateWordCount);
function updateWordCount() {
  const words = $('#scriptEditor').value.trim().split(/\s+/).filter(Boolean).length;
  $('#wordCount').textContent = `${words} từ`;
}

document.querySelectorAll('.editor-tab').forEach((tab) => tab.addEventListener('click', () => {
  document.querySelectorAll('.editor-tab').forEach((item) => item.classList.remove('active'));
  document.querySelectorAll('.editor-pane').forEach((item) => item.classList.remove('active'));
  tab.classList.add('active');
  document.querySelector(`[data-editor-pane="${tab.dataset.editorTab}"]`).classList.add('active');
}));

const editorRanges = [
  ['editSubtitleSize', 'editSizeOut', (v) => v],
  ['editSubtitleMargin', 'editMarginOut', (v) => v],
  ['editCaptionOpacity', 'editCaptionOut', (v) => `${Math.round(v * 100)}%`],
  ['editLogoWidth', 'editLogoWidthOut', (v) => `${Math.round(v * 100)}%`],
  ['editLogoOpacity', 'editLogoOpacityOut', (v) => `${Math.round(v * 100)}%`],
  ['editMusicVolume', 'editMusicOut', (v) => `${Math.round(v * 100)}%`],
  ['editBrightness', 'editBrightnessOut', (v) => v.toFixed(2)],
  ['editContrast', 'editContrastOut', (v) => v.toFixed(2)],
  ['editSaturation', 'editSaturationOut', (v) => v.toFixed(2)],
  ['editHue', 'editHueOut', (v) => `${Math.round(v)}°`],
  ['editBlur', 'editBlurOut', (v) => v.toFixed(1)],
  ['editVignette', 'editVignetteOut', (v) => `${Math.round(v * 100)}%`],
  ['editVoiceVolume', 'editVoiceOut', (v) => `${Math.round(v * 100)}%`],
  ['editFadeIn', 'editFadeInOut', (v) => `${v.toFixed(2)}s`],
  ['editFadeOut', 'editFadeOutOut', (v) => `${v.toFixed(2)}s`]
];
editorRanges.forEach(([inputId, outputId, format]) => $(`#${inputId}`).addEventListener('input', (event) => {
  $(`#${outputId}`).value = format(Number(event.target.value));
}));

const colorPresets = {
  original: [0, 1, 1, 0, 0, 0],
  cinematic: [-0.05, 1.22, 0.82, -8, 0, 0.28],
  warm: [0.04, 1.08, 1.18, -12, 0, 0.12],
  cool: [-0.02, 1.1, 0.92, 14, 0, 0.1],
  mono: [0, 1.18, 0, 0, 0, 0.2],
  vivid: [0.03, 1.2, 1.45, 4, 0, 0.08]
};

function updateLivePreview() {
  const brightness = Math.max(0, 1 + Number($('#editBrightness').value));
  const contrast = Number($('#editContrast').value);
  const saturation = Number($('#editSaturation').value);
  const hue = Number($('#editHue').value);
  const blur = Number($('#editBlur').value);
  $('#resultVideo').style.filter = `brightness(${brightness}) contrast(${contrast}) saturate(${saturation}) hue-rotate(${hue}deg) blur(${blur}px)`;
  $('#previewVignette').style.opacity = Number($('#editVignette').value);

  const subtitle = $('#subtitlePreview');
  const colors = {white: '#fff', yellow: '#ffe65a', cyan: '#61efff'};
  subtitle.style.color = colors[$('#editSubtitleColor').value] || '#fff';
  subtitle.style.fontFamily = $('#editFont').value;
  subtitle.style.fontSize = `${Math.max(14, Number($('#editSubtitleSize').value) * 1.55)}px`;
  subtitle.style.bottom = `${Math.max(3, Number($('#editSubtitleMargin').value) / 19.2)}%`;
  subtitle.style.background = `rgba(0,0,0,${Number($('#editCaptionOpacity').value)})`;
  $('#editorSaveState').textContent = 'Preview đã cập nhật · cần xuất để tạo MP4';
}

['editBrightness', 'editContrast', 'editSaturation', 'editHue', 'editBlur', 'editVignette', 'editSubtitleSize', 'editSubtitleMargin', 'editCaptionOpacity'].forEach((id) => {
  $(`#${id}`).addEventListener('input', () => { if (id.startsWith('editB') || ['editContrast', 'editSaturation', 'editHue', 'editBlur', 'editVignette'].includes(id)) $('#editColorPreset').value = 'custom'; updateLivePreview(); });
});
['editFont', 'editSubtitleColor'].forEach((id) => $(`#${id}`).addEventListener('change', updateLivePreview));
$('#editColorPreset').addEventListener('change', (event) => {
  const preset = colorPresets[event.target.value]; if (!preset) return;
  ['editBrightness', 'editContrast', 'editSaturation', 'editHue', 'editBlur', 'editVignette'].forEach((id, index) => {
    $(`#${id}`).value = preset[index]; $(`#${id}`).dispatchEvent(new Event('input'));
  });
  event.target.value = Object.keys(colorPresets).find((name) => colorPresets[name] === preset) || 'custom';
  updateLivePreview();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const key = sessionStorage.getItem('routerKey');
  if (!key) { loadConfig(); dialog.showModal(); toast('Hãy cấu hình 9Router trước'); return; }
  if (!videoInput.files[0] && !$('#sourceUrl').value.trim()) { toast('Hãy chọn video hoặc nhập URL'); return; }
  const data = new FormData(form);
  data.set('router_api_key', key);
  data.set('router_base_url', localStorage.getItem('routerUrl') || 'http://localhost:20128/v1');
  const textModel = localStorage.getItem('textModel');
  if (!textModel) { loadConfig(); dialog.showModal(); toast('Hãy tải và chọn text model'); resetButton(); return; }
  data.set('text_model', textModel);
  const scriptModel = localStorage.getItem('scriptModel');
  if (!scriptModel) { loadConfig(); dialog.showModal(); toast('Hãy chọn GPT hoặc Claude viết kịch bản'); resetButton(); return; }
  data.set('script_model', scriptModel);
  const savedWhisper = localStorage.getItem('whisperModel');
  data.set('local_whisper_model', ['base', 'small', 'medium'].includes(savedWhisper) ? savedWhisper : 'small');
  data.set('flip', String($('input[name=flip]').checked));
  data.set('cover_source_subtitles', String($('input[name=cover_source_subtitles]').checked));
  const voiceOption = $('#ttsVoice').selectedOptions[0];
  if (voiceOption?.dataset.speaker) data.set('tts_speaker', voiceOption.dataset.speaker);
  const button = $('#launchButton'); button.disabled = true; button.querySelector('span').textContent = 'ĐANG KHỞI TẠO...';
  try {
    if (videoInput.files[0]) {
      button.querySelector('span').textContent = 'ĐANG UPLOAD 0%';
      const uploadId = await uploadLargeVideo(videoInput.files[0], (percent) => { button.querySelector('span').textContent = `ĐANG UPLOAD ${percent}%`; $('#fileMeta').textContent = `${(videoInput.files[0].size / 1048576).toFixed(1)} MB · ${percent}%`; });
      data.delete('video_file'); data.set('upload_id', uploadId);
      button.querySelector('span').textContent = 'ĐANG KHỞI TẠO...';
    }
    const response = await fetch('/api/jobs', { method: 'POST', body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Không thể tạo job');
    startProduction(payload.job_id);
  } catch (error) {
    toast(error.message); button.disabled = false; button.querySelector('span').textContent = 'BẮT ĐẦU SẢN XUẤT';
  }
});

function startProduction(jobId) {
  currentJobId = jobId;
  $('#production').hidden = false; $('#jobId').textContent = jobId.toUpperCase();
  $('#resultGrid').hidden = true; $('#errorBox').hidden = true;
  $('#production').scrollIntoView({ behavior: 'smooth' });
  pollTimer = setInterval(() => updateJob(jobId), 1800); updateJob(jobId);
}

async function updateJob(jobId) {
  try {
    const response = await fetch(`/api/jobs/${jobId}`); const job = await response.json();
    $('#progressNumber').textContent = `${job.progress}%`; $('#progressBar').style.width = `${job.progress}%`;
    const stages = Object.entries(job.stages).filter((_, index) => job.phase !== 'prepare' || index < 6);
    $('#stageList').innerHTML = stages.map(([name, status]) => `<div class="stage ${status}"><i></i><span>${name.toUpperCase()}</span></div>`).join('');
    renderJobLogs(job.logs || []);
    if (job.status === 'running' && job.phase === 'render') {
      $('#applyEditorButton').disabled = true;
      $('#applyEditorButton').textContent = `ĐANG XUẤT · ${job.progress}%`;
    }
    if (job.status === 'failed') {
      clearInterval(pollTimer); $('#errorBox').hidden = false; $('#errorMessage').textContent = job.error;
      $('#applyEditorButton').disabled = false; $('#applyEditorButton').textContent = 'THỬ XUẤT LẠI';
      if (updatingCueId !== null) {
        const row = document.querySelector(`.cue-editor-row[data-cue-id="${updatingCueId}"]`);
        row?.classList.remove('loading'); row?.classList.add('dirty');
        const cueButton = row?.querySelector('.cue-apply-button');
        if (cueButton) { cueButton.disabled = false; cueButton.textContent = 'THỬ LẠI CUE'; }
        updatingCueId = null;
        toast(`Không thể cập nhật cue: ${job.error}`);
      }
      resetButton();
    }
    if (job.status === 'ready' || job.status === 'completed') {
      clearInterval(pollTimer); $('#resultGrid').hidden = false;
      currentVideoUrl = job.video_url;
      const previewUrl = job.preview_url || job.video_url;
      if ($('#resultVideo').dataset.previewUrl !== previewUrl) {
        $('#resultVideo').src = previewUrl;
        $('#resultVideo').dataset.previewUrl = previewUrl;
      }
      if (job.voice_url && $('#voicePreviewAudio').dataset.voiceUrl !== job.voice_url) {
        $('#voicePreviewAudio').src = job.voice_url;
        $('#voicePreviewAudio').dataset.voiceUrl = job.voice_url;
      }
      $('#scriptEditor').value = job.artifacts.script || '';
      currentDialogue = job.artifacts.dialogue || [];
      const cueWasUpdated = updatingCueId !== null;
      updatingCueId = null;
      buildTimeline(currentDialogue);
      buildCueEditor();
      updateWordCount();
      const rendered = job.status === 'completed';
      $('#editorProjectName').textContent = $('#previewName').textContent || `Project ${job.id}`;
      if (job.editorial?.content_mode) {
        $('#contentMode').value = job.editorial.content_mode;
        $('#editorialThesis').value = job.editorial.editorial_thesis || '';
        $('#vietnamAngle').value = job.editorial.vietnam_angle || '';
        $('#researchSources').value = (job.editorial.research_sources || []).join('\n');
      }
      $('#editorSaveState').textContent = rendered ? 'Đã có bản xuất · preview vẫn dùng project gốc' : 'Cue đã sẵn sàng để chỉnh sửa';
      $('#downloadButton').disabled = !rendered;
      $('#downloadButton').innerHTML = rendered ? 'LƯU VIDEO VỀ MÁY <span>↓</span>' : 'CHƯA CÓ BẢN RENDER <span>↓</span>';
      updateProjectAssetLinks(job.capcut_assets);
      $('#applyEditorButton').textContent = rendered ? 'XUẤT LẠI VIDEO' : 'XUẤT VIDEO';
      updateLivePreview();
      loadReadinessAnswers();
      if (cueWasUpdated) toast('Cue đã được tạo lại giọng và đồng bộ phụ đề');
      resetButton(); $('#resultGrid').scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  } catch (error) { clearInterval(pollTimer); toast(`Mất kết nối: ${error.message}`); resetButton(); }
}

$('#retryJobButton').addEventListener('click', async () => {
  if (!currentJobId) return;
  const button = $('#retryJobButton'); button.disabled = true; button.textContent = 'ĐANG KHỞI ĐỘNG LẠI...';
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/retry`, { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Không thể retry job');
    $('#errorBox').hidden = true; pollTimer = setInterval(() => updateJob(currentJobId), 1800); updateJob(currentJobId);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = 'THỬ LẠI TỪ BLOCK ĐÃ DỪNG'; }
});

function buildTimeline(lines) {
  const lane = $('#cueTimeline'); lane.innerHTML = '';
  const total = Math.max(...lines.map((line) => line.end), 1);
  lines.forEach((line, index) => {
    const cue = document.createElement('button'); cue.className = 'cue-block';
    cue.style.left = `${line.start / total * 100}%`;
    cue.style.width = `${Math.max((line.end - line.start) / total * 100, 0.8)}%`;
    cue.textContent = line.translation; cue.title = `${formatTime(line.start)} → ${formatTime(line.end)} · ${line.translation}`;
    cue.addEventListener('click', () => selectCue(index, cue)); lane.appendChild(cue);
  });
}

function selectCue(index, cue) {
  selectedCueIndex = index;
  document.querySelectorAll('.cue-block').forEach((item) => item.classList.remove('active')); cue.classList.add('active');
  const video = $('#resultVideo'); video.currentTime = currentDialogue[index].start; video.play();
  document.querySelector('[data-editor-tab="content"]').click();
  document.querySelectorAll('.cue-editor-row').forEach((item, rowIndex) => item.classList.toggle('active', rowIndex === index));
  document.querySelectorAll('.cue-editor-row')[index]?.scrollIntoView({block: 'nearest'});
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
}

function renderJobLogs(logs) {
  const list = $('#jobLogList');
  if (!logs.length) { list.innerHTML = '<p>Chưa có log.</p>'; return; }
  const stickToBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
  list.innerHTML = logs.map((entry) => {
    const time = new Date(entry.time).toLocaleTimeString('vi-VN');
    return `<div class="job-log-entry ${escapeHtml(entry.level)}"><time>${time}</time><b>${escapeHtml(entry.stage || 'SYSTEM')}</b><span>${escapeHtml(entry.message)}</span></div>`;
  }).join('');
  if (stickToBottom) list.scrollTop = list.scrollHeight;
}

function toggleLog(force) {
  const panel = $('#jobLogPanel'); panel.hidden = typeof force === 'boolean' ? !force : !panel.hidden;
  $('#toggleLogButton').textContent = panel.hidden ? 'XEM LOG' : 'ẨN LOG';
}
$('#toggleLogButton').addEventListener('click', () => toggleLog());
$('#closeLogButton').addEventListener('click', () => toggleLog(false));

function voiceOptions(selected) {
  return [...$('#ttsVoice').options].filter((option) => option.dataset.lang === $('#targetLanguage').value)
    .map((option) => `<option value="${option.value}" data-speaker="${option.dataset.speaker || ''}" ${option.value === selected ? 'selected' : ''}>${option.textContent}</option>`).join('');
}

function syncScriptFromCues() {
  $('#scriptEditor').value = currentDialogue.map((line) => line.translation).join('\n');
  $('#editorSaveState').textContent = 'Có cue chưa xác nhận';
  updateWordCount(); buildTimeline(currentDialogue); updateSubtitleAtCurrentTime();
}

async function applyCueUpdate(line, row) {
  if (!currentJobId || updatingCueId !== null) return;
  const button = row.querySelector('.cue-apply-button');
  updatingCueId = line.id;
  row.classList.remove('dirty'); row.classList.add('loading');
  button.disabled = true; button.textContent = 'ĐANG TẠO GIỌNG...';
  $('#editorSaveState').textContent = `Đang cập nhật cue ${line.id}`;
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/cues/${line.id}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        start: Number(line.start), end: Number(line.end),
        translation: line.translation, voice: line.voice || null,
        speaker: line.speaker ?? null
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Không thể cập nhật cue');
    clearInterval(pollTimer);
    pollTimer = setInterval(() => updateJob(currentJobId), 900);
    updateJob(currentJobId);
  } catch (error) {
    updatingCueId = null;
    row.classList.remove('loading'); row.classList.add('dirty');
    button.disabled = false; button.textContent = 'THỬ LẠI CUE';
    $('#editorSaveState').textContent = 'Cue chưa được cập nhật';
    toast(error.message);
  }
}

function buildCueEditor() {
  const list = $('#cueEditorList'); list.innerHTML = '';
  currentDialogue.forEach((line, index) => {
    const row = document.createElement('div'); row.className = `cue-editor-row${index === selectedCueIndex ? ' active' : ''}`;
    row.dataset.cueId = line.id;
    row.innerHTML = `<button type="button" class="cue-index">${String(index + 1).padStart(3, '0')}</button><div class="cue-time"><label>IN<input type="number" min="0" step="0.1" value="${line.start.toFixed(2)}"></label><label>OUT<input type="number" min="0.4" step="0.1" value="${line.end.toFixed(2)}"></label></div><textarea>${escapeHtml(line.translation)}</textarea><select>${voiceOptions(line.voice || $('#ttsVoice').value)}</select><button type="button" class="cue-apply-button">XÁC NHẬN CUE</button>`;
    const [startInput, endInput] = row.querySelectorAll('input'); const text = row.querySelector('textarea'); const voice = row.querySelector('select');
    const markDirty = () => row.classList.add('dirty');
    row.querySelector('.cue-index').addEventListener('click', () => selectCue(index, document.querySelectorAll('.cue-block')[index]));
    startInput.addEventListener('change', () => { line.start = Number(startInput.value); markDirty(); syncScriptFromCues(); });
    endInput.addEventListener('change', () => { line.end = Number(endInput.value); markDirty(); syncScriptFromCues(); });
    text.addEventListener('input', () => { line.translation = text.value; markDirty(); syncScriptFromCues(); });
    voice.addEventListener('change', () => { line.voice = voice.value; line.speaker = Number(voice.selectedOptions[0].dataset.speaker) || null; markDirty(); syncScriptFromCues(); });
    row.querySelector('.cue-apply-button').addEventListener('click', () => applyCueUpdate(line, row));
    list.appendChild(row);
  });
  $('#scriptEditor').value = currentDialogue.map((line) => line.translation).join('\n');
  updateWordCount(); updateSubtitleAtCurrentTime();
}

$('#addCueButton').addEventListener('click', () => {
  const previous = currentDialogue[selectedCueIndex] || currentDialogue.at(-1);
  const start = previous ? previous.end : 0; const cue = {id: Date.now(), start, end: start + 2, source: '', translation: 'Nội dung mới', voice: $('#ttsVoice').value, speaker: null};
  currentDialogue.splice(selectedCueIndex + 1, 0, cue); selectedCueIndex += 1; buildCueEditor();
});

$('#splitCueButton').addEventListener('click', () => {
  const cue = currentDialogue[selectedCueIndex]; if (!cue || cue.end - cue.start < 0.8) { toast('Cue quá ngắn để tách'); return; }
  const midpoint = (cue.start + cue.end) / 2; const words = cue.translation.split(/\s+/); const split = Math.max(1, Math.floor(words.length / 2));
  const next = {...cue, id: Date.now(), start: midpoint, translation: words.slice(split).join(' ') || cue.translation};
  cue.end = midpoint; cue.translation = words.slice(0, split).join(' '); currentDialogue.splice(selectedCueIndex + 1, 0, next); buildCueEditor();
});

$('#deleteCueButton').addEventListener('click', () => {
  if (currentDialogue.length <= 1) { toast('Timeline phải còn ít nhất một cue'); return; }
  currentDialogue.splice(selectedCueIndex, 1); selectedCueIndex = Math.max(0, selectedCueIndex - 1); buildCueEditor();
});

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60); const secs = Math.floor(seconds % 60);
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function updateSubtitleAtCurrentTime() {
  const video = $('#resultVideo');
  const cue = currentDialogue.find((line) => video.currentTime >= line.start && video.currentTime < line.end);
  $('#subtitlePreview').textContent = cue?.translation || '';
  $('#subtitlePreview').hidden = !cue;
}

$('#resultVideo').addEventListener('timeupdate', (event) => {
  $('#editorTime').textContent = `${formatTime(event.target.currentTime)} / ${formatTime(event.target.duration || 0)}`;
  updateSubtitleAtCurrentTime();
});
$('#resultVideo').addEventListener('play', async (event) => {
  const audio = $('#voicePreviewAudio'); if (!audio.src) return;
  audio.currentTime = event.target.currentTime;
  try { await audio.play(); } catch (error) { if (error.name !== 'AbortError') toast('Không phát được voice preview'); }
});
$('#resultVideo').addEventListener('pause', () => $('#voicePreviewAudio').pause());
$('#resultVideo').addEventListener('seeking', (event) => {
  const audio = $('#voicePreviewAudio'); if (audio.src) audio.currentTime = event.target.currentTime;
});
$('#editVoiceVolume').addEventListener('input', (event) => {
  $('#voicePreviewAudio').volume = Math.min(1, Number(event.target.value));
});

$('#applyEditorButton').addEventListener('click', async () => {
  if (!currentJobId) return;
  const payload = {
    cues: currentDialogue,
    font_name: $('#editFont').value,
    subtitle_font_size: Number($('#editSubtitleSize').value),
    subtitle_margin: Number($('#editSubtitleMargin').value),
    subtitle_color: $('#editSubtitleColor').value,
    caption_opacity: Number($('#editCaptionOpacity').value),
    cover_source_subtitles: true,
    music_volume: Number($('#editMusicVolume').value),
    logo_position: $('#editLogoPosition').value,
    logo_width: Number($('#editLogoWidth').value),
    logo_opacity: Number($('#editLogoOpacity').value),
    brightness: Number($('#editBrightness').value),
    contrast: Number($('#editContrast').value),
    saturation: Number($('#editSaturation').value),
    hue: Number($('#editHue').value),
    blur: Number($('#editBlur').value),
    vignette: Number($('#editVignette').value),
    voice_volume: Number($('#editVoiceVolume').value),
    audio_fade_in: Number($('#editFadeIn').value),
    audio_fade_out: Number($('#editFadeOut').value)
  };
  const button = $('#applyEditorButton'); button.disabled = true; button.textContent = 'ĐANG XUẤT VIDEO...';
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/render`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Không thể render video');
    $('#editorSaveState').textContent = 'Đang xuất video · bạn vẫn có thể xem preview';
    pollTimer = setInterval(() => updateJob(currentJobId), 1800); updateJob(currentJobId);
  } catch (error) { toast(error.message); button.disabled = false; button.textContent = 'XUẤT VIDEO'; }
});

$('#regenerateButton').addEventListener('click', async () => {
  const script = currentDialogue.map((line) => line.translation).join(' ').trim();
  const words = script.split(/\s+/).filter(Boolean).length;
  if (!currentJobId || words < 10 || words > 3000) { toast('Kịch bản cần từ 10 đến 3000 từ'); return; }
  const button = $('#regenerateButton'); button.disabled = true; button.textContent = 'ĐANG TẠO LẠI...';
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/timeline`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({cues: currentDialogue})
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Không thể tạo lại video');
    $('#resultGrid').hidden = true; $('#errorBox').hidden = true;
    pollTimer = setInterval(() => updateJob(currentJobId), 1800); updateJob(currentJobId);
  } catch (error) { toast(error.message); button.disabled = false; button.innerHTML = 'TẠO LẠI TỪ KỊCH BẢN NÀY <span>↻</span>'; }
});

function resetButton() {
  const button = $('#launchButton'); button.disabled = false; button.querySelector('span').textContent = 'TẠO PROJECT MỚI';
}

$('#downloadButton').addEventListener('click', async () => {
  if (!currentVideoUrl || !currentJobId) { toast('Video chưa sẵn sàng để tải'); return; }
  const button = $('#downloadButton');
  const original = button.innerHTML;
  try {
    if ('showSaveFilePicker' in window) {
      const handle = await window.showSaveFilePicker({
        suggestedName: `viet-transform-${currentJobId}.mp4`,
        types: [{description: 'Video MP4', accept: {'video/mp4': ['.mp4']}}]
      });
      button.innerHTML = 'ĐANG LƯU VIDEO... <span>···</span>';
      button.disabled = true;
      const response = await fetch(currentVideoUrl);
      if (!response.ok || !response.body) throw new Error('Không tải được dữ liệu video');
      const writable = await handle.createWritable();
      try { await response.body.pipeTo(writable); }
      catch (error) { await writable.abort(); throw error; }
      toast('Đã lưu video vào thư mục bạn chọn');
      return;
    }

    const link = document.createElement('a');
    link.href = currentVideoUrl;
    link.download = `viet-transform-${currentJobId}.mp4`;
    document.body.appendChild(link); link.click(); link.remove();
    toast('Trình duyệt đang tải video vào thư mục Downloads');
  } catch (error) {
    if (error.name !== 'AbortError') toast(`Lưu video thất bại: ${error.message}`);
  } finally {
    button.disabled = false; button.innerHTML = original;
  }
});

const readinessFields = [
  'rightsBasis', 'evidenceSaved', 'originalCommentary', 'multipleSources', 'factChecked',
  'syntheticDisclosure', 'advertiserReview', 'thumbnailAccurate', 'metadataReady', 'endScreenReady'
];

function readinessStorageKey() { return currentJobId ? `youtube-readiness-${currentJobId}` : ''; }

function readinessPayload() {
  return {
    rights_basis: $('#rightsBasis').value,
    evidence_saved: $('#evidenceSaved').checked,
    original_commentary: $('#originalCommentary').checked,
    multiple_sources: $('#multipleSources').checked,
    fact_checked: $('#factChecked').checked,
    synthetic_disclosure_reviewed: $('#syntheticDisclosure').checked,
    advertiser_friendly_reviewed: $('#advertiserReview').checked,
    thumbnail_accurate: $('#thumbnailAccurate').checked,
    metadata_ready: $('#metadataReady').checked,
    end_screen_ready: $('#endScreenReady').checked
  };
}

function saveReadinessAnswers() {
  const key = readinessStorageKey(); if (key) localStorage.setItem(key, JSON.stringify(readinessPayload()));
}

function loadReadinessAnswers() {
  const key = readinessStorageKey(); if (!key) return;
  const saved = JSON.parse(localStorage.getItem(key) || '{}');
  $('#rightsBasis').value = saved.rights_basis || 'unknown';
  const mapping = {
    evidenceSaved: 'evidence_saved', originalCommentary: 'original_commentary',
    multipleSources: 'multiple_sources', factChecked: 'fact_checked',
    syntheticDisclosure: 'synthetic_disclosure_reviewed', advertiserReview: 'advertiser_friendly_reviewed',
    thumbnailAccurate: 'thumbnail_accurate', metadataReady: 'metadata_ready', endScreenReady: 'end_screen_ready'
  };
  Object.entries(mapping).forEach(([id, field]) => { $(`#${id}`).checked = Boolean(saved[field]); });
}

readinessFields.forEach((id) => $(`#${id}`).addEventListener('change', saveReadinessAnswers));

function renderReadiness(result) {
  $('#readinessScore strong').textContent = result.score;
  $('#readinessScore').className = `readiness-score ${result.verdict}`;
  $('#readinessVerdict').textContent = result.verdict_label;
  const gates = ['rights', 'transform', 'editorial', 'publish'];
  gates.forEach((gate) => {
    const checks = result.checks.filter((item) => item.gate === gate);
    const node = document.querySelector(`[data-readiness-gate="${gate}"]`);
    node.classList.toggle('blocked', checks.some((item) => item.status === 'blocker'));
    node.classList.toggle('passed', checks.length > 0 && checks.every((item) => item.status === 'pass'));
  });
  $('#readinessResults').innerHTML = result.checks.map((item) => `<article class="readiness-result ${item.status}"><i>${item.status === 'pass' ? '✓' : item.status === 'blocker' ? '!' : '·'}</i><div><strong>${escapeHtml(item.label)}</strong><p>${escapeHtml(item.action)}</p></div><b>${item.points}/${item.max_points}</b></article>`).join('') + `<div class="policy-links">${result.sources.map((source) => `<a href="${source.url}" target="_blank" rel="noreferrer">${escapeHtml(source.label)} ↗</a>`).join('')}</div>`;
  $('#readinessDisclaimer').textContent = result.disclaimer;
}

$('#checkReadinessButton').addEventListener('click', async () => {
  if (!currentJobId) return;
  const button = $('#checkReadinessButton'); button.disabled = true; button.textContent = 'ĐANG KIỂM TRA...';
  saveReadinessAnswers();
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/youtube-readiness`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(readinessPayload())
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Không kiểm tra được project');
    renderReadiness(result);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = 'KIỂM TRA LẠI PROJECT'; }
});

loadConfig(); updateVoices();
