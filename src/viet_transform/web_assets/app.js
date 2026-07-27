const $ = (selector) => document.querySelector(selector);
const form = $('#studioForm');
const dialog = $('#settingsDialog');
const videoInput = $('#videoFile');
let pollTimer = null;
let currentJobId = null;
let currentDialogue = [];
let currentVideoUrl = null;
let batchDirectoryHandle = null;
let batchRunning = false;
let selectedCueIndex = 0;

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
  if (files.length > 10) { videoInput.value = ''; toast('Mỗi hàng đợi chỉ được chọn tối đa 10 video'); return; }
  const file = files[0];
  $('#fileTitle').textContent = file.name;
  $('#fileMeta').textContent = files.length === 1 ? `${(file.size / 1048576).toFixed(1)} MB · sẽ upload an toàn theo từng phần` : `${files.length} video · sẽ render tuần tự`;
  $('#previewName').textContent = file.name;
  $('#sourcePreview').src = URL.createObjectURL(file);
  $('#miniPreview').hidden = false;
  renderBatchList(files.map((item, index) => ({name: item.name, status: 'pending', message: `Chờ xử lý · ${(item.size / 1048576).toFixed(1)} MB`, index})));
}

$('#removeVideo').addEventListener('click', () => {
  videoInput.value = ''; $('#miniPreview').hidden = true;
  $('#fileTitle').textContent = 'KÉO TỐI ĐA 10 VIDEO VÀO ĐÂY';
  $('#fileMeta').textContent = 'MP4, MOV, WEBM · nguồn bạn có quyền sử dụng';
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
  ['editVoiceVolume', 'editVoiceOut', (v) => `${Math.round(v * 100)}%`],
  ['editFadeIn', 'editFadeInOut', (v) => `${v.toFixed(2)}s`],
  ['editFadeOut', 'editFadeOutOut', (v) => `${v.toFixed(2)}s`]
];
editorRanges.forEach(([inputId, outputId, format]) => $(`#${inputId}`).addEventListener('input', (event) => {
  $(`#${outputId}`).value = format(Number(event.target.value));
}));

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
    const selectedFiles = [...videoInput.files];
    if (selectedFiles.length > 1) {
      if ('showDirectoryPicker' in window && !batchDirectoryHandle) {
        try { await chooseDraftFolder(); }
        catch (error) { if (error.name !== 'AbortError') throw error; }
      }
      await processBatch(selectedFiles, data); return;
    }
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
    $('#stageList').innerHTML = Object.entries(job.stages).map(([name, status]) => `<div class="stage ${status}"><i></i><span>${name.toUpperCase()}</span></div>`).join('');
    renderJobLogs(job.logs || []);
    if (job.status === 'failed') {
      clearInterval(pollTimer); $('#errorBox').hidden = false; $('#errorMessage').textContent = job.error;
      resetButton();
    }
    if (job.status === 'completed') {
      clearInterval(pollTimer); $('#resultGrid').hidden = false;
      currentVideoUrl = job.video_url;
      $('#resultVideo').src = job.video_url;
      $('#scriptEditor').value = job.artifacts.script || '';
      currentDialogue = job.artifacts.dialogue || [];
      buildTimeline(currentDialogue);
      buildCueEditor();
      updateWordCount();
      $('#regenerateButton').disabled = false;
      $('#regenerateButton').innerHTML = 'TẠO LẠI TỪ KỊCH BẢN NÀY <span>↻</span>';
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
  updateWordCount(); buildTimeline(currentDialogue);
}

function buildCueEditor() {
  const list = $('#cueEditorList'); list.innerHTML = '';
  currentDialogue.forEach((line, index) => {
    const row = document.createElement('div'); row.className = `cue-editor-row${index === selectedCueIndex ? ' active' : ''}`;
    row.innerHTML = `<button type="button" class="cue-index">${String(index + 1).padStart(3, '0')}</button><div class="cue-time"><label>IN<input type="number" min="0" step="0.1" value="${line.start.toFixed(2)}"></label><label>OUT<input type="number" min="0.4" step="0.1" value="${line.end.toFixed(2)}"></label></div><textarea>${line.translation}</textarea><select>${voiceOptions(line.voice || $('#ttsVoice').value)}</select>`;
    const [startInput, endInput] = row.querySelectorAll('input'); const text = row.querySelector('textarea'); const voice = row.querySelector('select');
    row.querySelector('.cue-index').addEventListener('click', () => selectCue(index, document.querySelectorAll('.cue-block')[index]));
    startInput.addEventListener('change', () => { line.start = Number(startInput.value); syncScriptFromCues(); });
    endInput.addEventListener('change', () => { line.end = Number(endInput.value); syncScriptFromCues(); });
    text.addEventListener('input', () => { line.translation = text.value; syncScriptFromCues(); });
    voice.addEventListener('change', () => { line.voice = voice.value; line.speaker = Number(voice.selectedOptions[0].dataset.speaker) || null; });
    list.appendChild(row);
  });
  syncScriptFromCues();
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

$('#resultVideo').addEventListener('timeupdate', (event) => {
  $('#editorTime').textContent = `${formatTime(event.target.currentTime)} / ${formatTime(event.target.duration || 0)}`;
});

$('#applyEditorButton').addEventListener('click', async () => {
  if (!currentJobId) return;
  const payload = {
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
    voice_volume: Number($('#editVoiceVolume').value),
    audio_fade_in: Number($('#editFadeIn').value),
    audio_fade_out: Number($('#editFadeOut').value)
  };
  const button = $('#applyEditorButton'); button.disabled = true; button.textContent = 'ĐANG RENDER...';
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/render-settings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Không thể render lại');
    $('#resultGrid').hidden = true; pollTimer = setInterval(() => updateJob(currentJobId), 1800); updateJob(currentJobId);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = 'ÁP DỤNG & RENDER LẠI'; }
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
  const button = $('#launchButton'); button.disabled = false; button.querySelector('span').textContent = 'TẠO VIDEO MỚI';
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

loadConfig(); updateVoices();
