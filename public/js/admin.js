(function () {
  const gate = document.getElementById('gate');
  const consoleEl = document.getElementById('console');
  const keyInput = document.getElementById('keyInput');
  const unlockBtn = document.getElementById('unlockBtn');
  const gateErr = document.getElementById('gateErr');
  const statusNote = document.getElementById('statusNote');

  let adminKey = sessionStorage.getItem('nid_admin_key') || '';
  let pollTimer = null;

  if (adminKey) tryUnlock(adminKey, true);

  unlockBtn.addEventListener('click', () => tryUnlock(keyInput.value.trim(), false));
  keyInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') tryUnlock(keyInput.value.trim(), false);
  });

  async function tryUnlock(key, silent) {
    if (!key) return;
    gateErr.textContent = '';
    try {
      const res = await fetch('/api/admin/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error('bad key');

      adminKey = key;
      sessionStorage.setItem('nid_admin_key', key);
      gate.hidden = true;
      consoleEl.hidden = false;
      refresh();
      refreshRequirements();
      refreshSchedule();
      refreshVideos();
      clearInterval(pollTimer);
      pollTimer = setInterval(refresh, 5000);
    } catch (err) {
      sessionStorage.removeItem('nid_admin_key');
      if (!silent) gateErr.textContent = "Wrong passcode, or the server isn't reachable.";
    }
  }

  document.querySelectorAll('.line-card button[data-action]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const { line, action } = btn.dataset;
      btn.disabled = true;
      try {
        const res = await fetch('/api/admin/' + action, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ line, key: adminKey }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'Failed');
        renderQueue(data.queue);
        statusNote.textContent = '';
      } catch (err) {
        statusNote.textContent = 'Error: ' + err.message;
      } finally {
        btn.disabled = false;
      }
    });
  });

  document.getElementById('resetBtn').addEventListener('click', async () => {
    if (!confirm("Reset both queues back to 000 for today? This can't be undone.")) return;
    try {
      const res = await fetch('/api/admin/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: adminKey }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed');
      renderQueue(data.queue);
    } catch (err) {
      statusNote.textContent = 'Error: ' + err.message;
    }
  });

  async function refresh() {
    try {
      const res = await fetch('/api/data');
      const data = await res.json();
      if (!data.ok) throw new Error(data.error);
      renderQueue(data.queue);
    } catch (err) {
      statusNote.textContent = 'Could not refresh: ' + err.message;
    }
  }

  function renderQueue(queue) {
    document.getElementById('regServing').textContent = String(queue.registration.serving).padStart(3, '0');
    document.getElementById('regTicket').textContent = String(queue.registration.ticket).padStart(3, '0');
    document.getElementById('verServing').textContent = String(queue.verification.serving).padStart(3, '0');
    document.getElementById('verTicket').textContent = String(queue.verification.ticket).padStart(3, '0');
    document.getElementById('consoleDate').textContent = 'Queue date: ' + queue.date;
  }

  // -------------------- Requirements panel --------------------

  const reqForm = document.getElementById('reqForm');
  const reqList = document.getElementById('reqList');

  async function refreshRequirements() {
    try {
      const res = await fetch('/api/admin/requirements?key=' + encodeURIComponent(adminKey));
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to load');
      renderRequirements(data.items);
    } catch (err) {
      reqList.innerHTML = '<li class="empty">Could not load: ' + escapeHtml(err.message) + '</li>';
    }
  }

  function renderRequirements(items) {
    reqList.innerHTML = '';
    if (!items.length) {
      reqList.innerHTML = '<li class="empty">No requirements yet.</li>';
      return;
    }
    items.forEach((item) => {
      const li = document.createElement('li');
      li.className = 'item-row';
      li.innerHTML =
        '<span class="badge">' + escapeHtml(item.category || '—') + '</span>' +
        '<span class="main">' + escapeHtml(item.text) +
        '<span class="sub">Order ' + escapeHtml(String(item.order)) + '</span></span>' +
        '<button class="del" type="button">Delete</button>';
      li.querySelector('.del').addEventListener('click', () => deleteRequirement(item.row, li));
      reqList.appendChild(li);
    });
  }

  reqForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const submitBtn = reqForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    try {
      const res = await fetch('/api/admin/requirements', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          key: adminKey,
          category: document.getElementById('reqCategory').value,
          text: document.getElementById('reqText').value.trim(),
          order: document.getElementById('reqOrder').value || 0,
        }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to add');
      renderRequirements(data.items);
      reqForm.reset();
    } catch (err) {
      statusNote.textContent = 'Error: ' + err.message;
    } finally {
      submitBtn.disabled = false;
    }
  });

  async function deleteRequirement(row, li) {
    if (!confirm('Delete this requirement?')) return;
    const btn = li.querySelector('.del');
    btn.disabled = true;
    try {
      const res = await fetch('/api/admin/requirements/' + row + '/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: adminKey }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to delete');
      renderRequirements(data.items);
    } catch (err) {
      statusNote.textContent = 'Error: ' + err.message;
      btn.disabled = false;
    }
  }

  // -------------------- Schedule panel --------------------

  const schedForm = document.getElementById('schedForm');
  const schedList = document.getElementById('schedList');

  async function refreshSchedule() {
    try {
      const res = await fetch('/api/admin/schedule?key=' + encodeURIComponent(adminKey));
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to load');
      renderSchedule(data.items);
    } catch (err) {
      schedList.innerHTML = '<li class="empty">Could not load: ' + escapeHtml(err.message) + '</li>';
    }
  }

  function renderSchedule(items) {
    schedList.innerHTML = '';
    if (!items.length) {
      schedList.innerHTML = '<li class="empty">No mobile registration dates yet.</li>';
      return;
    }
    items.forEach((item) => {
      const li = document.createElement('li');
      li.className = 'item-row';
      const timeRange = [item.timeStart, item.timeEnd].filter(Boolean).join(' – ');
      const subParts = [item.day, timeRange, item.slots ? item.slots + ' slots' : '', item.notes].filter(Boolean);
      li.innerHTML =
        '<span class="badge">' + escapeHtml(item.date) + '</span>' +
        '<span class="main">' + escapeHtml(item.venue) +
        '<span class="sub">' + escapeHtml(subParts.join(' · ')) + '</span></span>' +
        '<button class="del" type="button">Delete</button>';
      li.querySelector('.del').addEventListener('click', () => deleteSchedule(item.row, li));
      schedList.appendChild(li);
    });
  }

  schedForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const submitBtn = schedForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    try {
      const res = await fetch('/api/admin/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          key: adminKey,
          date: document.getElementById('schedDate').value.trim(),
          day: document.getElementById('schedDay').value.trim(),
          venue: document.getElementById('schedVenue').value.trim(),
          timeStart: document.getElementById('schedStart').value.trim(),
          timeEnd: document.getElementById('schedEnd').value.trim(),
          slots: document.getElementById('schedSlots').value.trim(),
          notes: document.getElementById('schedNotes').value.trim(),
        }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to add');
      renderSchedule(data.items);
      schedForm.reset();
    } catch (err) {
      statusNote.textContent = 'Error: ' + err.message;
    } finally {
      submitBtn.disabled = false;
    }
  });

  async function deleteSchedule(row, li) {
    if (!confirm('Delete this schedule entry?')) return;
    const btn = li.querySelector('.del');
    btn.disabled = true;
    try {
      const res = await fetch('/api/admin/schedule/' + row + '/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: adminKey }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to delete');
      renderSchedule(data.items);
    } catch (err) {
      statusNote.textContent = 'Error: ' + err.message;
      btn.disabled = false;
    }
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // -------------------- AVP videos panel --------------------

  const videoForm = document.getElementById('videoForm');
  const videoFile = document.getElementById('videoFile');
  const videoList = document.getElementById('videoList');
  const uploadProgress = document.getElementById('uploadProgress');
  const uploadFill = document.getElementById('uploadFill');
  const uploadPct = document.getElementById('uploadPct');

  async function refreshVideos() {
    try {
      const res = await fetch('/api/admin/videos?key=' + encodeURIComponent(adminKey));
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to load');
      renderVideos(data.items);
    } catch (err) {
      videoList.innerHTML = '<li class="empty">Could not load: ' + escapeHtml(err.message) + '</li>';
    }
  }

  function formatSize(bytes) {
    if (!bytes && bytes !== 0) return '';
    const mb = bytes / (1024 * 1024);
    return mb >= 1 ? mb.toFixed(1) + ' MB' : Math.round(bytes / 1024) + ' KB';
  }

  function renderVideos(items) {
    videoList.innerHTML = '';
    if (!items.length) {
      videoList.innerHTML = '<li class="empty">No AVP videos uploaded yet.</li>';
      return;
    }
    items.forEach((item) => {
      const li = document.createElement('li');
      li.className = 'item-row';
      const uploaded = item.createdTime ? new Date(item.createdTime).toLocaleDateString() : '';
      const subParts = [formatSize(item.size), uploaded].filter(Boolean);
      li.innerHTML =
        '<input class="name-input" type="text" value="' + escapeHtml(item.name) + '" />' +
        '<span class="main"><span class="sub">' + escapeHtml(subParts.join(' · ')) + '</span></span>' +
        '<button class="rename" type="button">Rename</button>' +
        '<button class="del" type="button">Delete</button>';
      const nameInput = li.querySelector('.name-input');
      li.querySelector('.rename').addEventListener('click', () => renameVideo(item.id, nameInput, li));
      li.querySelector('.del').addEventListener('click', () => deleteVideo(item.id, item.name, li));
      videoList.appendChild(li);
    });
  }

  videoForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const file = videoFile.files[0];
    if (!file) return;
    uploadVideo(file);
  });

  async function uploadVideo(file) {
    const submitBtn = videoForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    videoFile.disabled = true;
    uploadProgress.hidden = false;
    uploadFill.style.width = '0%';
    uploadPct.textContent = '0%';

    try {
      // 1) ask our server to open a Drive resumable-upload session (small,
      //    fast JSON round-trip — no file bytes involved yet)
      const initRes = await fetch('/api/admin/videos/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          key: adminKey,
          filename: file.name,
          mimetype: file.type || 'video/mp4',
          size: file.size,
        }),
      });
      const initData = await initRes.json();
      if (!initData.ok) throw new Error(initData.error || 'Could not start upload');

      // 2) PUT the file straight to Drive using that session URL — this is
      //    the part that used to go through our server and made uploads
      //    slow; now it goes browser -> Drive directly.
      await putDirectToDrive(initData.uploadUrl, file);

      // 3) tell our server the upload is done so it refreshes its cache
      const confirmRes = await fetch('/api/admin/videos/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: adminKey }),
      });
      const confirmData = await confirmRes.json();
      if (!confirmData.ok) throw new Error(confirmData.error || 'Upload finished but list refresh failed');
      renderVideos(confirmData.items);
      videoForm.reset();
    } catch (err) {
      statusNote.textContent = 'Error: ' + err.message;
    } finally {
      uploadProgress.hidden = true;
      submitBtn.disabled = false;
      videoFile.disabled = false;
    }
  }

  function putDirectToDrive(uploadUrl, file) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', uploadUrl);
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
      xhr.upload.addEventListener('progress', (e) => {
        if (!e.lengthComputable) return;
        const pct = Math.round((e.loaded / e.total) * 100);
        uploadFill.style.width = pct + '%';
        uploadPct.textContent = pct + '%';
      });
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(new Error('Drive upload failed (status ' + xhr.status + ')'));
        }
      };
      xhr.onerror = () => reject(new Error('Network error while uploading to Drive'));
      xhr.send(file);
    });
  }

  async function renameVideo(id, nameInput, li) {
    const name = nameInput.value.trim();
    if (!name) return;
    const btn = li.querySelector('.rename');
    btn.disabled = true;
    nameInput.disabled = true;
    try {
      const res = await fetch('/api/admin/videos/' + id + '/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: adminKey, name }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to rename');
      renderVideos(data.items);
    } catch (err) {
      statusNote.textContent = 'Error: ' + err.message;
      btn.disabled = false;
      nameInput.disabled = false;
    }
  }

  async function deleteVideo(id, name, li) {
    if (!confirm('Delete "' + name + '"? This removes it from Drive permanently.')) return;
    const btn = li.querySelector('.del');
    btn.disabled = true;
    try {
      const res = await fetch('/api/admin/videos/' + id + '/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: adminKey }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to delete');
      renderVideos(data.items);
    } catch (err) {
      statusNote.textContent = 'Error: ' + err.message;
      btn.disabled = false;
    }
  }
})();
