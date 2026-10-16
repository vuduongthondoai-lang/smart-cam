(() => {
  const config = window.DASHBOARD_CONFIG || {};
  const $ = (id) => document.getElementById(id);
  const state = { events: [], cameraOn: false, lastRefresh: null, cameraLoadTimeout: null };

  const els = {
    dbStatus: $('dbStatus'), dbDetail: $('dbDetail'), eventCount: $('eventCount'), videoCount: $('videoCount'),
    cameraStatus: $('cameraStatus'), cameraBadge: $('cameraBadge'), cameraFeed: $('cameraFeed'),
    cameraPlaceholder: $('cameraPlaceholder'), cameraError: $('cameraError'), toggleCameraButton: $('toggleCameraButton'),
    eventsBody: $('eventsBody'), tableSummary: $('tableSummary'), lastRefresh: $('lastRefresh'),
    searchInput: $('searchInput'), playerPanel: $('playerPanel'), videoPlayer: $('videoPlayer'), playerTitle: $('playerTitle'), playbackHint: $('playbackHint')
  };

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[ch]);

  function formatDate(value) {
    if (!value) return '—';
    const normalized = String(value).replace(' ', 'T');
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('vi-VN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function formatDuration(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) return '—';
    return `${seconds.toFixed(1)} giây`;
  }

  function setBadge(element, text, mode) {
    element.textContent = text;
    element.className = `badge ${mode}`;
  }

  async function refreshStatus() {
    try {
      const response = await fetch('/api/status', { cache: 'no-store' });
      const data = await response.json();
      if (data.sql_connected) {
        els.dbStatus.textContent = 'Đã kết nối';
        els.dbStatus.style.color = '#178969';
        els.dbDetail.textContent = `${data.server} · ${data.database}`;
      } else {
        els.dbStatus.textContent = 'Mất kết nối';
        els.dbStatus.style.color = '#bf4c5b';
        els.dbDetail.textContent = data.sql_error ? 'Kiểm tra cấu hình SQL/ODBC' : 'SQL Server';
      }
      els.videoCount.textContent = data.recording_dir_exists ? 'Thư mục sẵn sàng' : 'Không tìm thấy';
      els.videoCount.style.fontSize = '17px';
    } catch (error) {
      els.dbStatus.textContent = 'Không truy cập được';
      els.dbStatus.style.color = '#bf4c5b';
      els.dbDetail.textContent = 'Kiểm tra Flask';
    }
  }

  function renderEvents(events) {
    const query = els.searchInput.value.trim().toLocaleLowerCase('vi');
    const filtered = events.filter((event) => String(event.video_filename || '').toLocaleLowerCase('vi').includes(query));
    if (!filtered.length) {
      els.eventsBody.innerHTML = `<tr><td colspan="6" class="table-message">${events.length ? 'Không có video khớp nội dung tìm kiếm.' : 'Chưa có sự kiện hoặc chưa kết nối được SQL Server.'}</td></tr>`;
    } else {
      els.eventsBody.innerHTML = filtered.map((event) => {
        const exists = Boolean(event.video_exists && event.video_url);
        const play = exists
          ? `<button class="play-link" type="button" data-play-url="${escapeHtml(event.video_url)}" data-filename="${escapeHtml(event.video_filename)}">▶ Phát video</button>`
          : `<span class="file-missing">Không tìm thấy MP4</span>`;
        return `<tr>
          <td>#${escapeHtml(event.id)}</td>
          <td>${escapeHtml(formatDate(event.event_start))}</td>
          <td>${escapeHtml(formatDate(event.last_detected_at))}</td>
          <td>${escapeHtml(formatDuration(event.video_duration_seconds))}</td>
          <td>${escapeHtml(event.detected_frames ?? '—')}</td>
          <td>${play}</td>
        </tr>`;
      }).join('');
    }
    els.tableSummary.textContent = `Hiển thị ${filtered.length} / ${events.length} sự kiện gần nhất`;
    els.eventCount.textContent = String(state.total ?? events.length);
    els.videoCount.textContent = String(events.filter((item) => item.video_exists).length);
    els.videoCount.style.fontSize = '22px';
  }

  async function refreshEvents() {
    try {
      const response = await fetch('/api/events?limit=100', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'Không đọc được lịch sử');
      state.events = data.events || [];
      state.total = data.total || 0;
      renderEvents(state.events);
      state.lastRefresh = new Date();
      els.lastRefresh.textContent = `Cập nhật ${state.lastRefresh.toLocaleTimeString('vi-VN')}`;
    } catch (error) {
      els.eventsBody.innerHTML = `<tr><td colspan="6" class="table-message">Không tải được dữ liệu SQL Server: ${escapeHtml(error.message)}</td></tr>`;
      els.tableSummary.textContent = 'Chưa đồng bộ được dữ liệu';
    }
  }

  function startCamera() {
    if (state.cameraLoadTimeout) window.clearTimeout(state.cameraLoadTimeout);
    els.cameraError.hidden = true;
    els.cameraPlaceholder.hidden = true;
    els.cameraFeed.hidden = false;
    // Flask proxies the local relay from tracking.py, never a second ESP32-CAM connection.
    const streamUrl = config.cameraProxyUrl || config.cameraStreamUrl;
    els.cameraFeed.src = `${streamUrl}${streamUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
    state.cameraOn = true;
    state.cameraLoadTimeout = window.setTimeout(() => {
      if (!state.cameraOn) return;
      // MJPEG image load events vary by browser; naturalWidth is a better signal
      // that at least one frame has actually arrived.
      if (els.cameraFeed.naturalWidth > 0) {
        els.cameraStatus.textContent = 'Đang bật';
        setBadge(els.cameraBadge, 'Đang bật', 'badge-success');
        return;
      }
      els.cameraError.textContent = 'Chưa nhận được hình ảnh từ tracking.py. Hãy chạy tracking.py trước và kiểm tra relay http://127.0.0.1:8765/stream trên chính máy tính.';
      els.cameraError.hidden = false;
      els.cameraStatus.textContent = 'Chưa nhận được hình ảnh';
      setBadge(els.cameraBadge, 'Cần kiểm tra kết nối', 'badge-error');
    }, 8000);
    els.toggleCameraButton.textContent = 'Tắt luồng trực tiếp';
    els.cameraStatus.textContent = 'Đang yêu cầu luồng';
    els.cameraStatus.style.fontSize = '17px';
    setBadge(els.cameraBadge, 'Đang bật', 'badge-success');
  }

  function stopCamera() {
    if (state.cameraLoadTimeout) window.clearTimeout(state.cameraLoadTimeout);
    state.cameraLoadTimeout = null;
    els.cameraFeed.removeAttribute('src');
    els.cameraFeed.hidden = true;
    els.cameraPlaceholder.hidden = false;
    els.cameraError.hidden = true;
    state.cameraOn = false;
    els.toggleCameraButton.textContent = 'Mở luồng trực tiếp';
    els.cameraStatus.textContent = 'Đang tắt';
    els.cameraStatus.style.fontSize = '22px';
    setBadge(els.cameraBadge, 'Đang tắt', 'badge-neutral');
  }

  els.toggleCameraButton.addEventListener('click', () => state.cameraOn ? stopCamera() : startCamera());
  els.cameraFeed.addEventListener('error', () => {
    if (state.cameraLoadTimeout) window.clearTimeout(state.cameraLoadTimeout);
    state.cameraLoadTimeout = null;
    els.cameraError.textContent = 'Không tải được luồng chia sẻ. Hãy chạy tracking.py trước, rồi kiểm tra lỗi trong terminal tracking.py và Flask.';
    els.cameraError.hidden = false;
    els.cameraStatus.textContent = 'Không tải được';
    setBadge(els.cameraBadge, 'Lỗi kết nối', 'badge-error');
  });
  els.cameraFeed.addEventListener('load', () => {
    if (state.cameraLoadTimeout) window.clearTimeout(state.cameraLoadTimeout);
    state.cameraLoadTimeout = null;
    if (state.cameraOn) {
      els.cameraStatus.textContent = 'Đang bật';
      setBadge(els.cameraBadge, 'Đang bật', 'badge-success');
    }
  });

  els.eventsBody.addEventListener('click', (event) => {
    const button = event.target.closest('[data-play-url]');
    if (!button) return;
    const url = button.getAttribute('data-play-url');
    const filename = button.getAttribute('data-filename') || 'Video sự kiện';
    els.videoPlayer.pause();
    els.videoPlayer.src = url;
    els.playerTitle.textContent = filename;
    els.playbackHint.textContent = 'Đang chuẩn bị video để phát. Lần đầu có thể mất thêm thời gian để chuyển mã tương thích trình duyệt.';
    els.playerPanel.hidden = false;
    els.playerPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    els.videoPlayer.load();
    els.videoPlayer.play().catch(() => {
      // Some browsers block autoplay; controls remain available for manual playback.
      els.playbackHint.textContent = 'Video đã được tải yêu cầu. Nhấn nút Phát trên trình phát nếu video chưa tự chạy.';
    });
  });


  els.videoPlayer.addEventListener('loadedmetadata', () => {
    const duration = Number.isFinite(els.videoPlayer.duration)
      ? `${els.videoPlayer.duration.toFixed(1)} giây` : 'đã tải metadata';
    els.playbackHint.textContent = `Video đã sẵn sàng (${duration}).`;
  });
  els.videoPlayer.addEventListener('error', () => {
    const mediaError = els.videoPlayer.error;
    const code = mediaError ? mediaError.code : 0;
    const reasons = {
      1: 'Việc tải video đã bị hủy.',
      2: 'Lỗi mạng khi tải video.',
      3: 'Trình duyệt không giải mã được video. Dashboard sẽ tạo bản H.264; kiểm tra terminal Flask nếu vẫn lỗi.',
      4: 'Định dạng video không được trình duyệt hỗ trợ hoặc máy chủ không trả về được video.'
    };
    els.playbackHint.textContent = reasons[code] || 'Không phát được video. Kiểm tra terminal Flask để xem lỗi chuyển đổi MP4.';
  });

  $('closePlayerButton').addEventListener('click', () => {
    els.videoPlayer.pause();
    els.videoPlayer.removeAttribute('src');
    els.videoPlayer.load();
    els.playerPanel.hidden = true;
  });
  $('refreshButton').addEventListener('click', async () => {
    await Promise.all([refreshStatus(), refreshEvents()]);
  });
  $('loadMoreButton').addEventListener('click', refreshEvents);
  els.searchInput.addEventListener('input', () => renderEvents(state.events));

  stopCamera();
  Promise.all([refreshStatus(), refreshEvents()]);
  window.setInterval(() => { refreshStatus(); refreshEvents(); }, config.refreshIntervalMs || 10000);
})();
