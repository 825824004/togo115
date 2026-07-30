function renderSettings() {
  const tabs = [
    ["credentials", "账号安全"],
    ["delivery", "推送方式"],
    ["115", "115 网盘"],
    ["telegram", "Telegram"],
    ["tmdb", "TMDB"],
    ["proxy", "代理设置"],
    ["rss_sources", "订阅源"],
    ["tg_bot", "TG Bot"],
    ["emby", "媒体库"],
    ["backup", "备份恢复"],
  ];
  const tabMeta = {
    credentials: ["账号安全", "修改后台登录账号和密码，留空新密码则保持原密码。"],
    delivery: ["推送方式", "统一设置资源命中后的处理方式，所有订阅都会使用这里的全局配置。"],
    115: ["115 网盘", "维护扫码登录状态、Cookie 和默认转存目录。"],
    telegram: ["Telegram", "配置账号登录、群组/频道选择和历史消息搜索范围。"],
    tmdb: ["TMDB", "配置 TMDB API Key，用于榜单、搜索、封面和剧集信息。"],
    proxy: ["代理设置", "填写一个代理地址，并勾选需要走代理的模块。"],
    rss_sources: ["订阅源", "管理 RSS、Torznab、站点插件和海搜官方 API 订阅源。Telegram 未命中后作为补充来源；海搜按次计费。"],
    tg_bot: ["TG Bot", "配置机器人命令入口和允许操作的聊天范围。"],
    emby: ["媒体库", "配置 Emby 服务地址、API Key，以及 Webhook（实时回写入库状态、自动订阅新媒体）。"],
    backup: ["备份恢复", "导出或导入系统配置、订阅和订阅源数据。"],
  };
  const [currentTitle, currentDescription] = tabMeta[state.settingsTab] || tabMeta.credentials;
  const cards = {
    credentials: settingsCard("账号安全", "credentials", [
      ["username", "账号", state.user.username],
      ["password", "新密码", "", "password"],
    ]),
    delivery: settingsCard("推送方式", "delivery", [["mode", "全局推送方式"]]),
    115: settingsCard("115 网盘", "115", [["cookie", "Cookie"], ["target_path", "默认转存目录"], ["qr_login", "扫码登录状态"]]),
    telegram: settingsCard("Telegram", "telegram", [["api_id", "API ID"], ["api_hash", "API HASH"], ["sources", "群组/频道"], ["history_limit", "历史搜索条数"]]),
    tmdb: settingsCard("TMDB", "tmdb", [["api_key", "API Key"]]),
    proxy: settingsCard("代理设置", "proxy", [["url", "代理地址"], ["modules", "启用代理的模块"]]),
    rss_sources: rssSourcesCard(),
    tg_bot: settingsCard("TG Bot", "tg_bot", [["bot_token", "监听 Bot Token"], ["bot_username", "转发目标机器人用户名"], ["allowed_chat_id", "允许的 Chat ID"]]),
    emby: settingsCard("媒体库", "emby", [["server_url", "Emby 地址"], ["api_key", "API Key"]]) + embyWebhookCard(),
    backup: backupCard(),
  };
  $("#view").innerHTML = `
    <section class="settings-workbench">
      <nav class="settings-tabs">
        ${tabs.map(([key, label]) => `<button class="${state.settingsTab === key ? "active" : ""}" data-settings-tab="${key}">${label}</button>`).join("")}
      </nav>
      <div class="settings-content">
        <header class="settings-panel-heading">
          <span class="eyebrow">SETTINGS</span>
          <h2>${currentTitle}</h2>
          <p>${currentDescription}</p>
        </header>
        <div class="settings settings-single settings-${state.settingsTab}">${cards[state.settingsTab]}</div>
      </div>
    </section>
  `;
  document.querySelectorAll("[data-settings-tab]").forEach((btn) => btn.addEventListener("click", () => {
    state.settingsTab = btn.dataset.settingsTab;
    localStorage.setItem("settingsTab", state.settingsTab);
    renderSettings();
  }));
  document.querySelectorAll("[data-save-settings]").forEach((form) => form.addEventListener("submit", saveSettings));
  document.querySelector("[data-save-rss-sources]")?.addEventListener("submit", saveRssSources);
  $("#addRssSource")?.addEventListener("click", addRssSource);
  document.querySelectorAll("[data-toggle-builtin-source]").forEach((btn) => btn.addEventListener("click", toggleBuiltinRssSource));
  document.querySelectorAll("[data-toggle-rss-source]").forEach((btn) => btn.addEventListener("click", toggleRssSource));
  document.querySelectorAll("[data-remove-rss-source]").forEach((btn) => btn.addEventListener("click", removeRssSource));
  document.querySelectorAll("[data-test-rss-source]").forEach((btn) => btn.addEventListener("click", testRssSource));
  document.querySelectorAll(".rss-source-type").forEach((select) => select.addEventListener("change", syncRssSourceTypeUi));
  document.querySelectorAll(".rss-source-plugin").forEach((select) => select.addEventListener("change", syncRssSourceTypeUi));
  $("#exportBackup")?.addEventListener("click", exportBackup);
  $("#importBackup")?.addEventListener("click", importBackup);
  enhanceIntegrationCards();
  if (document.getElementById("embyWebhookSettings")) loadEmbyWebhookSettings();
}

function settingsCard(title, key, fields) {
  const value = state.settings[key]?.value || {};
  return `<form class="card form-grid" data-save-settings="${key}">
    <h3>${title}</h3>
    ${fields.map(([name, label, fallback = "", type = "text"]) => fieldHtml(key, name, label, value[name] || fallback || "", type)).join("")}
    <button type="submit">保存</button>
  </form>`;
}

function backupCard() {
  return `<section class="card form-grid backup-card">
    <h3>备份恢复</h3>
    <p class="muted">导出设置、订阅和订阅源配置；导入时会合并到现有数据，不会清空当前订阅。</p>
    <div class="inline-actions">
      <button type="button" id="exportBackup">导出备份</button>
      <button type="button" class="secondary" id="importBackup">导入备份</button>
    </div>
    <textarea id="backupText" rows="14" placeholder="导出的备份 JSON 会显示在这里，也可以粘贴备份 JSON 后导入。">${escapeHtml(state.backupText || "")}</textarea>
  </section>`;
}

function fieldHtml(key, name, label, current, type = "text") {
  if (key === "115" && name === "target_path") {
    const cid = state.settings["115"]?.value?.target_cid || "0";
    const path = current || "/";
    state.panFolder = { cid: String(cid), path };
    return `<fieldset class="folder-picker"><legend>${label}</legend>
      <div class="folder-current" id="panFolderCurrent">${escapeHtml(path)}</div>
      <input type="hidden" name="target_path" id="panTargetPath" value="${escapeHtml(path)}" />
      <input type="hidden" name="target_cid" id="panTargetCid" value="${escapeHtml(cid)}" />
      <div class="inline-actions">
        <button type="button" class="secondary" id="panFolderRoot">根目录</button>
        <button type="button" class="secondary" id="loadPanFolders">选择目录</button>
      </div>
      <div class="dialog-list folder-list" id="panFolderList"></div>
    </fieldset>`;
  }
  if (key === "115" && name === "qr_login") {
    const status = current || (state.settings["115"]?.value?.cookie ? "已登录" : "未登录");
    return `<label>${label}<input type="text" name="${name}" value="${status}" readonly /></label>`;
  }
  if (key === "delivery" && name === "mode") {
    const selected = current || "115";
    return `<label>${label}<select name="mode">
      <option value="115" ${selected === "115" ? "selected" : ""}>转存到 115</option>
      <option value="telegram_bot" ${selected === "telegram_bot" ? "selected" : ""}>发送到 TG Bot</option>
    </select></label>`;
  }
  if (key === "proxy" && name === "modules") {
    const selected = Array.isArray(current) ? current : String(current || "").split(",").filter(Boolean);
    const options = [["tmdb", "TMDB"], ["telegram", "Telegram"], ["pan115", "115 网盘"], ["haisou", "海搜"], ["emby", "Emby"]];
    return `<fieldset class="check-group"><legend>${label}</legend>
      ${options.map(([value, text]) => `<label><input type="checkbox" name="modules" value="${value}" ${selected.includes(value) ? "checked" : ""} /> ${text}</label>`).join("")}
    </fieldset>`;
  }
  if (key === "telegram" && name === "sources") {
    const selected = String(current || "").split(",").filter(Boolean);
    const labels = telegramDialogLabels();
    const selectedSummary = selected.length
      ? `<div class="selected-sources">${selected.map((source) => `<span class="source-chip" title="${escapeHtml(source)}">${escapeHtml(labels[source] || source)}</span>`).join("")}</div>
        ${selected.map((source) => `<input type="hidden" name="sources" value="${escapeHtml(source)}" />`).join("")}`
      : `<div class="muted">登录 Telegram 后点击加载列表，然后勾选要监控的群组/频道。</div>`;
    const buttonText = selected.length ? "重新选择群组/频道" : "加载群组/频道";
    const listClass = selected.length ? "dialog-list hidden" : "dialog-list";
    return `<fieldset class="check-group" id="telegramSources"><legend>${label}</legend>
      ${selectedSummary}
      <button type="button" class="secondary" id="loadTelegramDialogs">${buttonText}</button>
      <div class="${listClass}" id="telegramDialogList" data-selected="${escapeHtml(selected.join(","))}"></div>
    </fieldset>`;
  }
  return `<label>${label}<input type="${type}" name="${name}" value="${current}" /></label>`;
}

function embyWebhookCard() {
  return `<section class="card form-grid" id="embyWebhookSettings">
    <h3>Emby Webhook</h3>
    <p class="muted">将下方地址填入 Emby 的 Webhook 插件（通知类型选「项目添加 / Library.NewItem」）：</p>
    <code class="emby-webhook-url" id="ewWebhookUrl">加载中…</code>
    <label class="switch-row"><input type="checkbox" id="ewEnabled" /> <span>启用 Webhook</span></label>
    <label class="switch-row"><input type="checkbox" id="ewAuto" /> <span>新媒体自动创建订阅</span></label>
    <label class="switch-row sub"><input type="checkbox" id="ewMovies" /> <span>自动订阅电影</span></label>
    <label class="switch-row sub"><input type="checkbox" id="ewSeries" /> <span>自动订阅剧集</span></label>
    <label class="switch-row"><input type="checkbox" id="ewMatch" /> <span>回写已有订阅的入库状态</span></label>
    <label class="emby-webhook-token">共享密钥（可选，与 Emby Webhook 的 Token 字段一致）
      <input type="text" id="ewToken" placeholder="留空则不校验" />
    </label>
    <div class="inline-actions"><button type="button" id="ewSave">保存配置</button></div>
    <div class="emby-webhook-events">
      <h4>最近事件</h4>
      <div id="ewEvents"><div class="muted">暂无事件</div></div>
    </div>
  </section>`;
}

async function loadEmbyWebhookSettings() {
  const root = document.getElementById("embyWebhookSettings");
  if (!root) return;
  const status = await apiQuick("/api/emby/webhook/status", { ok: true, config: {}, recent_events: [] });
  const cfg = status.config || {};
  document.getElementById("ewWebhookUrl").textContent = `${location.origin}/api/emby/webhook`;
  document.getElementById("ewEnabled").checked = !!cfg.enabled;
  document.getElementById("ewAuto").checked = !!cfg.auto_subscribe;
  document.getElementById("ewMovies").checked = cfg.auto_subscribe_movies !== false;
  document.getElementById("ewSeries").checked = cfg.auto_subscribe_series !== false;
  document.getElementById("ewMatch").checked = cfg.match_existing !== false;
  document.getElementById("ewToken").value = cfg.token || "";
  const eventsBox = document.getElementById("ewEvents");
  if (eventsBox) {
    eventsBox.innerHTML = (status.recent_events || []).slice(0, 6).map((e) =>
      `<div class="event-row"><span class="tag ${e.action}">${escapeHtml(e.action)}</span> ${escapeHtml(e.title || "")}</div>`
    ).join("") || '<div class="muted">暂无事件</div>';
  }
  const save = document.getElementById("ewSave");
  if (save) save.addEventListener("click", saveEmbyWebhookSettings);
}

async function saveEmbyWebhookSettings() {
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
  loadEmbyWebhookSettings();
}
