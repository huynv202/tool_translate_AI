const imageInput = document.querySelector('#storyImages');
const imagePreview = document.querySelector('#storyImagePreview');
const toast = document.querySelector('#toast');
const settingsDialog = document.querySelector('#storySettingsDialog');

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.setTimeout(() => toast.classList.remove('show'), 2800);
}

function renderImages(files) {
  imagePreview.innerHTML = '';
  if (!files.length) {
    imagePreview.innerHTML = '<div class="empty-image-state"><span>0</span><p>Ảnh tải lên sẽ xuất hiện tại đây</p></div>';
    return;
  }
  [...files].slice(0, 12).forEach((file, index) => {
    const item = document.createElement('figure');
    const image = document.createElement('img');
    image.src = URL.createObjectURL(file);
    image.alt = `Ảnh tham chiếu ${index + 1}`;
    item.append(image, Object.assign(document.createElement('figcaption'), {textContent: `IMG ${String(index + 1).padStart(2, '0')}`}));
    imagePreview.appendChild(item);
  });
}

imageInput.addEventListener('change', () => renderImages(imageInput.files));
document.querySelector('#storySettings').addEventListener('click', () => {
  document.querySelector('#storyRouterKey').value = sessionStorage.getItem('routerKey') || '';
  document.querySelector('#storyRouterUrl').value = localStorage.getItem('routerUrl') || 'http://localhost:20128/v1';
  const model = localStorage.getItem('scriptModel') || '';
  const select = document.querySelector('#storyScriptModel');
  if (model && ![...select.options].some((option) => option.value === model)) select.add(new Option(model, model));
  select.value = model;
  document.querySelector('#geminiMediaKey').value = sessionStorage.getItem('geminiMediaKey') || '';
  document.querySelector('#geminiImageModel').value = localStorage.getItem('geminiImageModel') || 'imagen-4.0-generate-001';
  document.querySelector('#geminiVideoModel').value = localStorage.getItem('geminiVideoModel') || '';
  settingsDialog.showModal();
});
document.querySelector('#storyLoadModels').addEventListener('click', async () => {
  const status = document.querySelector('#storyRouterStatus');
  status.querySelector('span').textContent = 'Đang tải danh sách model...';
  try {
    const response = await fetch('/api/router/models', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({api_key: document.querySelector('#storyRouterKey').value, base_url: document.querySelector('#storyRouterUrl').value})
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Không tải được model');
    const select = document.querySelector('#storyScriptModel');
    select.innerHTML = '<option value="">Chọn model viết kịch bản</option>';
    payload.models.filter((item) => /gpt|claude|gemini/i.test(item.id)).forEach((item) => select.add(new Option(`[${item.provider}] ${item.id}`, item.id)));
    status.querySelector('span').textContent = `Đã tải ${select.options.length - 1} model.`;
  } catch (error) { status.querySelector('span').textContent = error.message; }
});
document.querySelector('#storySettingsForm').addEventListener('submit', (event) => {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault();
  sessionStorage.setItem('routerKey', document.querySelector('#storyRouterKey').value);
  localStorage.setItem('routerUrl', document.querySelector('#storyRouterUrl').value);
  localStorage.setItem('scriptModel', document.querySelector('#storyScriptModel').value);
  sessionStorage.setItem('geminiMediaKey', document.querySelector('#geminiMediaKey').value);
  localStorage.setItem('geminiImageModel', document.querySelector('#geminiImageModel').value);
  localStorage.setItem('geminiVideoModel', document.querySelector('#geminiVideoModel').value);
  settingsDialog.close(); showToast('Đã lưu cấu hình AI storytelling');
});
document.querySelector('#manualNarrationToggle').addEventListener('change', (event) => {
  document.querySelector('#manualNarrationField').hidden = !event.target.checked;
});
document.querySelector('#storyLaunchButton').addEventListener('click', async () => {
  const context = document.querySelector('#storyContext').value.trim();
  if (!context) {
    showToast('Hãy nhập cốt truyện hoặc bối cảnh trước');
    document.querySelector('#storyContext').focus();
    return;
  }
  const apiKey = sessionStorage.getItem('routerKey'); const model = localStorage.getItem('scriptModel');
  if (!apiKey || !model) { document.querySelector('#storySettings').click(); showToast('Hãy cấu hình AI trước'); return; }
  const button = document.querySelector('#storyLaunchButton'); button.disabled = true; button.textContent = 'AI ĐANG VIẾT STORYBOARD...';
  try {
    const response = await fetch('/api/storytelling/storyboard', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        api_key: apiKey, base_url: localStorage.getItem('routerUrl') || 'http://localhost:20128/v1', model,
        context, manual_narration: document.querySelector('#manualNarrationToggle').checked ? document.querySelector('#storyNarration').value.trim() : '',
        duration_seconds: Number(document.querySelector('#storyDuration').value), tone: document.querySelector('#storyTone').value,
        visual_style: document.querySelector('#storyStyle').value, aspect_ratio: document.querySelector('#storyRatio').value,
        director_prompt: document.querySelector('#directorPrompt').value.trim(),
        asset_mode: document.querySelector('input[name="assetMode"]:checked').value,
        image_names: [...imageInput.files].map((file) => file.name)
      })
    });
    const storyboard = await response.json();
    if (!response.ok) throw new Error(storyboard.detail || 'Không tạo được storyboard');
    renderStoryboard(storyboard);
    showToast(`Đã tạo ${storyboard.scenes.length} scene`);
  } catch (error) { showToast(error.message); }
  finally { button.disabled = false; button.innerHTML = 'TẠO STORYBOARD <b>↗</b>'; }
});

function renderStoryboard(storyboard) {
  document.querySelector('#storyboardPreview').hidden = false;
  document.querySelector('.storyboard-heading h2').textContent = storyboard.title;
  const bible = storyboard.visual_bible;
  document.querySelector('#storyboardLane').innerHTML = `<div class="visual-bible"><b>VISUAL BIBLE</b><p>${escapeHtml([bible.characters, bible.world, bible.palette, bible.style].filter(Boolean).join(' · '))}</p></div><div class="story-scene-grid">${storyboard.scenes.map((scene) => `<article><div class="scene-number">${String(scene.id).padStart(2, '0')}</div><span>${scene.needs_generation ? 'AI IMAGE' : escapeHtml(scene.uploaded_image || 'UPLOAD')}</span><h3>${escapeHtml(scene.narration)}</h3><p>${escapeHtml(scene.image_prompt)}</p><footer>${scene.duration_seconds.toFixed(1)}s · ${escapeHtml(scene.composition)} · ${escapeHtml(scene.transition)}</footer></article>`).join('')}</div>`;
  document.querySelector('#storyboardPreview').scrollIntoView({behavior: 'smooth'});
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
}
