async function renderEmby() {
  const root = $("#view");
  root.innerHTML = `<div class="empty">正在读取 Emby 看板...</div>`;
  const data = await api("/api/emby/dashboard");
  const movieCount = data.movie_count ?? data.counts?.MovieCount ?? 0;
  const seriesCount = data.series_count ?? data.counts?.SeriesCount ?? 0;
  root.innerHTML = `
    ${data.error ? `<div class="empty">Emby 数据获取失败：${data.error}</div>` : ""}
    <section class="emby-console">
      <aside class="emby-overview-panel">
        <span class="eyebrow">EMBY</span>
        <h1>媒体库看板</h1>
        <p>查看媒体体量、媒体库封面和最近播放记录。</p>
        <div class="stats">
          <div class="stat"><span>媒体总数</span><b>${data.media_count || 0}</b></div>
          <div class="stat"><span>电视剧</span><b>${seriesCount}</b></div>
          <div class="stat"><span>电影</span><b>${movieCount}</b></div>
          <div class="stat"><span>媒体库</span><b>${(data.libraries || []).length}</b></div>
          <div class="stat"><span>用户</span><b>${(data.users || []).length}</b></div>
          <div class="stat"><span>观看记录</span><b>${(data.history || []).length}</b></div>
        </div>
      </aside>
      <div class="emby-content-stack">
        <section class="section emby-library-section"><div class="section-heading"><h3>媒体库</h3><span>${(data.libraries || []).length} 个</span></div>${embyGrid(data.libraries, "暂无媒体库数据", "library")}</section>
        <section class="section emby-history-section"><div class="section-heading"><h3>观看历史</h3><span>${(data.history || []).length} 条</span></div>${embyGrid(data.history, "暂无观看历史", "history")}</section>
        <section class="section emby-user-section"><div class="section-heading"><h3>用户</h3><span>${(data.users || []).length} 个</span></div>${embyGrid(data.users, "暂无用户数据", "user")}</section>
      </div>
      <aside class="emby-webhook-card" id="embyWebhookCard">
        <div class="section-heading"><h3>Emby Webhook</h3><span>实时回写入库状态 · 自动订阅新媒体</span></div>
        <div id="embyWebhookBody"><div class="empty">加载中…</div></div>
      </aside>
    </section>
  `;
  loadEmbyWebhookCard();
}

async function loadEmbyWebhookCard() {
  const body = document.getElementById("embyWebhookBody");
  if (!body) return;
  const status = await apiQuick("/api/emby/webhook/status", { ok: true, config: {}, recent_events: [] });
  const cfg = status.config || {};
  const host = location.origin;
  body.innerHTML = `
    <p class="muted">将下方地址填入 Emby 的 Webhook 插件（通知类型选「项目添加 / Library.NewItem」）：</p>
    <code class="emby-webhook-url">${escapeHtml(host)}/api/emby/webhook</code>
    <label class="switch-row"><input type="checkbox" id="ewEnabled" ${cfg.enabled ? "checked" : ""}/> <span>启用 Webhook</span></label>
    <label class="switch-row"><input type="checkbox" id="ewAuto" ${cfg.auto_subscribe ? "checked" : ""}/> <span>新媒体自动创建订阅</span></label>
    <label class="switch-row sub"><input type="checkbox" id="ewMovies" ${cfg.auto_subscribe_movies !== false ? "checked" : ""}/> <span>自动订阅电影</span></label>
    <label class="switch-row sub"><input type="checkbox" id="ewSeries" ${cfg.auto_subscribe_series !== false ? "checked" : ""}/> <span>自动订阅剧集</span></label>
    <label class="switch-row"><input type="checkbox" id="ewMatch" ${cfg.match_existing !== false ? "checked" : ""}/> <span>回写已有订阅的入库状态</span></label>
    <label class="emby-webhook-token">共享密钥（可选，与 Emby Webhook 的 Token 字段一致）
      <input type="text" id="ewToken" placeholder="留空则不校验" value="${escapeHtml(cfg.token || "")}" />
    </label>
    <div class="inline-actions">
      <button type="button" id="ewSave">保存配置</button>
    </div>
    <div class="emby-webhook-events">
      <h4>最近事件</h4>
      ${(status.recent_events || []).slice(0, 6).map((e) => `<div class="event-row"><span class="tag ${e.action}">${e.action}</span> ${escapeHtml(e.title || "")}</div>`).join("") || '<div class="muted">暂无事件</div>'}
    </div>
  `;
  const save = document.getElementById("ewSave");
  if (save) save.addEventListener("click", saveEmbyWebhook);
}

async function saveEmbyWebhook() {
  const value = {
    enabled: document.getElementById("ewEnabled").checked,
    auto_subscribe: document.getElementById("ewAuto").checked,
    auto_subscribe_movies: document.getElementById("ewMovies").checked,
    auto_subscribe_series: document.getElementById("ewSeries").checked,
    match_existing: document.getElementById("ewMatch").checked,
    token: document.getElementById("ewToken").value.trim(),
  };
  await api("/api/emby/webhook/settings", { method: "PUT", body: JSON.stringify({ value }) });
  toast("Emby Webhook 配置已保存");
  loadEmbyWebhookCard();
}

function simpleList(items, empty) {
  if (!items || !items.length) return `<div class="empty">${empty}</div>`;
  return `<div class="grid">${items.map((item) => `<div class="card"><div class="card-body"><h3>${item.name || item.title || "项目"}</h3><p class="muted">${item.description || ""}</p></div></div>`).join("")}</div>`;
}

function embyGrid(items, empty, kind) {
  if (!items || !items.length) return `<div class="empty">${empty}</div>`;
  if (kind === "history") {
    return `<div class="emby-history-list">${items.slice(0, 20).map((item) => {
      const title = item.name || item.title || "项目";
      const date = item.date_played || item.description || "";
      const image = item.image_url
        ? `<img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(title)}" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'emby-history-thumb', textContent:'播放'}))" />`
        : `<div class="emby-history-thumb">播放</div>`;
      return `<article class="emby-history-item">
        ${image}
        <div>
          <h3>${escapeHtml(title)}</h3>
          ${date ? `<p>${escapeHtml(date)}</p>` : ""}
        </div>
      </article>`;
    }).join("")}</div>`;
  }
  return `<div class="emby-grid ${kind === "library" ? "emby-library-grid" : ""}">${items.map((item) => {
    const fallback = kind === "user" ? "" : `<div class="emby-placeholder">媒体</div>`;
    const image = kind === "user"
      ? ""
      : (item.image_url ? `<img class="library-image" src="${item.image_url}" alt="${item.name || item.title || "Emby"}" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'emby-placeholder', textContent:'媒体'}))" />` : fallback);
    const metaClass = kind === "library" ? "emby-library-meta" : "";
    const description = kind === "library" ? "" : (item.description || item.collection_type || item.date_played || "");
    return `<article class="emby-card ${kind === "library" ? "emby-library-card" : ""}">
      ${image}
      <div class="${metaClass}">
        <h3>${escapeHtml(item.name || item.title || "项目")}</h3>
        ${description ? `<p>${description}</p>` : ""}
      </div>
    </article>`;
  }).join("")}</div>`;
}
