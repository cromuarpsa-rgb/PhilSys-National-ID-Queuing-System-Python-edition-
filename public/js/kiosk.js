(function () {
  const POLL_MS = 6000;
  const VIDEO_ROTATE_MS = 90 * 1000; // how long each AVP video plays before switching
  // NOTE: Drive's embedded player runs in a cross-origin iframe, so the page
  // can't detect when a clip actually finishes — it rotates on a timer instead.
  // For frame-accurate looping, host the AVP as direct MP4 files instead.

  let lastQueue = null;
  let videos = [];
  let videoIndex = 0;
  let videoTimer = null;

  function fmtClock() {
    const now = new Date();
    const time = new Intl.DateTimeFormat('en-PH', {
      timeZone: 'Asia/Manila',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    }).format(now);
    const date = new Intl.DateTimeFormat('en-PH', {
      timeZone: 'Asia/Manila',
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    }).format(now);
    document.getElementById('clockTime').textContent = time;
    document.getElementById('clockDate').textContent = date;
  }
  setInterval(fmtClock, 1000);
  fmtClock();

  function renderVideo() {
    const frame = document.getElementById('videoFrame');
    if (!videos.length) {
      frame.innerHTML = '<div class="video-empty">No AVP videos found yet.<br>Add MP4s to the shared Drive folder.</div>';
      return;
    }
    const v = videos[videoIndex % videos.length];
    frame.innerHTML =
      '<iframe src="' + v.embedUrl + '?autoplay=1" allow="autoplay" allowfullscreen title="AVP"></iframe>' +
      '<div class="video-caption">' + escapeHtml(v.name) + '</div>';
  }

  function startVideoRotation() {
    if (videoTimer) clearInterval(videoTimer);
    videoTimer = setInterval(() => {
      videoIndex = (videoIndex + 1) % Math.max(videos.length, 1);
      renderVideo();
    }, VIDEO_ROTATE_MS);
  }

  function pulse(el) {
    el.classList.remove('pulse');
    // force reflow so the animation can retrigger
    void el.offsetWidth;
    el.classList.add('pulse');
  }

  function renderQueue(queue) {
    const regEl = document.getElementById('regServing');
    const verEl = document.getElementById('verServing');
    const regServing = String(queue.registration.serving).padStart(3, '0');
    const verServing = String(queue.verification.serving).padStart(3, '0');

    if (!lastQueue || lastQueue.registration.serving !== queue.registration.serving) pulse(regEl);
    if (!lastQueue || lastQueue.verification.serving !== queue.verification.serving) pulse(verEl);

    regEl.textContent = regServing;
    verEl.textContent = verServing;
    document.getElementById('regTicket').textContent =
      'Latest ticket: R-' + String(queue.registration.ticket).padStart(3, '0');
    document.getElementById('verTicket').textContent =
      'Latest ticket: V-' + String(queue.verification.ticket).padStart(3, '0');
    document.getElementById('queueDate').textContent =
      'Sequence for ' + queue.date + ' · resets automatically at midnight';

    lastQueue = queue;
  }

  function renderRequirements(list) {
    const primary = list.find((r) => r.category.toLowerCase() === 'primary');
    const secondary = list.find((r) => r.category.toLowerCase() === 'secondary');
    document.getElementById('primaryReq').textContent = primary ? primary.text : 'See list below';
    document.getElementById('secondaryReq').textContent = secondary ? secondary.text : 'See list below';

    const ul = document.getElementById('reqMarquee');
    if (!list.length) {
      ul.innerHTML = '';
      ul.parentElement.innerHTML = '<div class="requirements-empty">Requirements list is empty. Add rows to the Requirements sheet.</div>';
      return;
    }
    // duplicate the list so the upward scroll can loop seamlessly at -50%
    const doubled = list.concat(list);
    ul.innerHTML = doubled
      .map((r) => '<li><span class="tag">' + escapeHtml(r.category) + '</span><span>' + escapeHtml(r.text) + '</span></li>')
      .join('');
    const seconds = Math.max(list.length * 2.6, 10);
    ul.style.animationDuration = seconds + 's';
  }

  function renderSchedule(list) {
    const wrap = document.getElementById('scheduleWrap');
    if (!list.length) {
      wrap.innerHTML = '<div class="schedule-empty">No mobile registration dates posted yet.</div>';
      return;
    }
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Manila' }).format(new Date()); // yyyy-mm-dd
    let markedUpcoming = false;
    const rows = list
      .map((r) => {
        let cls = '';
        if (!markedUpcoming && r.date >= today) {
          cls = 'upcoming';
          markedUpcoming = true;
        }
        return (
          '<tr class="' + cls + '">' +
          '<td>' + escapeHtml(prettyDate(r.date)) + (r.day ? '<br><span style="color:#8b93b6">' + escapeHtml(r.day) + '</span>' : '') + '</td>' +
          '<td>' + escapeHtml(r.venue) + (r.notes ? '<br><span style="color:#8b93b6">' + escapeHtml(r.notes) + '</span>' : '') + '</td>' +
          '<td>' + escapeHtml(r.timeStart) + (r.timeEnd ? '–' + escapeHtml(r.timeEnd) : '') + '</td>' +
          '<td>' + escapeHtml(r.slots) + '</td>' +
          '</tr>'
        );
      })
      .join('');
    wrap.innerHTML =
      '<table class="schedule"><thead><tr><th>Date</th><th>Venue</th><th>Time</th><th>Slots</th></tr></thead><tbody>' +
      rows +
      '</tbody></table>';
  }

  function prettyDate(iso) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
    const d = new Date(iso + 'T00:00:00+08:00');
    return new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', month: 'short', day: 'numeric', year: 'numeric' }).format(d);
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c]));
  }

  async function refresh() {
    try {
      const res = await fetch('/api/data');
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Unknown error');

      renderQueue(data.queue);
      renderRequirements(data.requirements || []);
      renderSchedule(data.schedule || []);

      const newVideos = data.videos || [];
      const changed = JSON.stringify(newVideos.map((v) => v.id)) !== JSON.stringify(videos.map((v) => v.id));
      videos = newVideos;
      if (changed) {
        videoIndex = 0;
        renderVideo();
        startVideoRotation();
      }
    } catch (err) {
      console.error('Kiosk refresh failed:', err);
    }
  }

  refresh();
  setInterval(refresh, POLL_MS);
})();
