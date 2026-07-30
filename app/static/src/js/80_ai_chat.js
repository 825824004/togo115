// AI 助手对话页：流式对话 + 工具调用可视化 + 内嵌设置
// 依赖全局 api / toast / escapeHtml / state（来自 00_state.js、10_shell.js）

const AI_TOOL_LABELS = {
  list_subscriptions: "查询订阅列表",
  create_subscription: "创建订阅",
  update_subscription_status: "更新订阅状态",
  cancel_subscription: "取消订阅",
  search_subscription: "触发单条搜索",
  search_all_subscriptions: "全量重搜订阅",
  search_tmdb: "TMDB 影视搜索",
  list_recent_resources: "查询资源记录",
  get_system_overview: "获取系统概览",
};

const AI_QUICK_PROMPTS = [
  "系统概览",
  "列出当前活跃订阅",
  "最近转存的资源",
  "在 TMDB 搜索《庆余年》并创建订阅",
];

function aiToolLabel(name) {
  return AI_TOOL_LABELS[name] || name;
}

async function renderAiChat() {
  if (!state.aiMessages) state.aiMessages = [];
  state.aiBusy = false;
  state._aiCurrent = null;

  const status = await apiQuick("/api/ai/status", { ok: true, ready: false, message: "加载中…" });

  $("#view").innerHTML = `
    <section class="ai-workbench">
      <header class="ai-banner ${status.ready ? "is-ready" : "is-off"}">
        <div class="ai-banner-main">
          <span class="ai-banner-dot"></span>
          <div>
            <strong>${status.ready ? "AI 助手已就绪" : "AI 助手未配置"}</strong>
            <p>${escapeHtml(status.message || (status.ready ? `模型 ${status.model} · ${status.base_url}` : "请在下方设置中填写 API Key 与模型"))}</p>
          </div>
        </div>
        <button type="button" class="secondary" id="aiSettingsToggle" aria-label="AI 设置">⚙ 设置</button>
      </header>

      <form class="ai-settings-panel hidden" id="aiSettingsPanel" data-save-settings="ai">
        <h3>AI 助手设置</h3>
        <label class="ai-settings-row">
          <span>启用 AI 助手</span>
          <input type="checkbox" name="enabled" ${state.settings?.ai?.value?.enabled === false ? "" : "checked"} />
        </label>
        <label>接口地址 <input name="base_url" placeholder="https://api.openai.com/v1" value="${escapeHtml(state.settings?.ai?.value?.base_url || "")}" /></label>
        <label>API Key
          <input type="password" name="api_key" placeholder="sk-…（留空则保持现有 Key）" autocomplete="off" />
        </label>
        <label>模型 <input name="model" placeholder="gpt-4o-mini" value="${escapeHtml(state.settings?.ai?.value?.model || "")}" /></label>
        <label>系统提示词 <textarea name="system_prompt" rows="4" placeholder="你是 ToGo115 的 AI 助手…">${escapeHtml(state.settings?.ai?.value?.system_prompt || "")}</textarea></label>
        <div class="ai-settings-grid">
          <label>温度 <input type="number" name="temperature" step="0.1" min="0" max="2" value="${state.settings?.ai?.value?.temperature ?? 0.3}" /></label>
          <label>最大 Token <input type="number" name="max_tokens" step="128" min="256" max="8192" value="${state.settings?.ai?.value?.max_tokens ?? 2048}" /></label>
        </div>
        <div class="inline-actions">
          <button type="submit">保存设置</button>
          <button type="button" class="secondary" id="aiSettingsClose">收起</button>
        </div>
      </form>

      <div class="ai-thread" id="aiThread"></div>

      <div class="ai-composer">
        <div class="ai-quick">
          ${AI_QUICK_PROMPTS.map((q) => `<button type="button" class="chip" data-quick="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join("")}
        </div>
        <form class="ai-input-row" id="aiForm">
          <textarea id="aiInput" rows="1" placeholder="问点什么，或让它帮你管理订阅…（Enter 发送，Shift+Enter 换行）"></textarea>
          <button type="submit" id="aiSend" aria-label="发送">发送</button>
        </form>
      </div>
    </section>
  `;

  renderAiThread();
  bindAiChat();
}

function renderAiThread() {
  const thread = $("#aiThread");
  if (!thread) return;
  if (!state.aiMessages.length) {
    thread.innerHTML = `
      <div class="ai-empty">
        <div class="ai-empty-mark">AI</div>
        <h3>和你的媒体管家聊聊</h3>
        <p>它可以查询订阅、搜索影视、触发追新，甚至帮你一键创建订阅。</p>
      </div>`;
    return;
  }
  thread.innerHTML = state.aiMessages.map(aiMessageHtml).join("");
  thread.scrollTop = thread.scrollHeight;
}

function aiMessageHtml(msg) {
  if (msg.role === "user") {
    return `<div class="ai-msg ai-msg-user"><div class="ai-bubble">${escapeHtml(msg.content)}</div></div>`;
  }
  const tools = (msg.tool_calls || []).map(aiToolCardHtml).join("");
  return `<div class="ai-msg ai-msg-bot">
    <div class="ai-avatar">AI</div>
    <div class="ai-bubble-group">
      ${tools ? `<div class="ai-tools">${tools}</div>` : ""}
      <div class="ai-bubble ai-assistant-text">${escapeHtml(msg.content || "")}</div>
    </div>
  </div>`;
}

function aiToolCardHtml(tool) {
  const args = tool.arguments ? JSON.stringify(tool.arguments, null, 2) : "";
  const result = tool.result ? JSON.stringify(tool.result, null, 2) : "";
  return `<details class="ai-tool" open>
    <summary>
      <span class="ai-tool-spin"></span>
      <span class="ai-tool-name">${escapeHtml(aiToolLabel(tool.name))}</span>
      <span class="ai-tool-tag">${escapeHtml(tool.name)}</span>
    </summary>
    ${args ? `<pre class="ai-tool-args">${escapeHtml(args)}</pre>` : ""}
    ${result ? `<pre class="ai-tool-result">${escapeHtml(result)}</pre>` : ""}
  </details>`;
}

function bindAiChat() {
  $("#aiSettingsToggle")?.addEventListener("click", () => {
    $("#aiSettingsPanel")?.classList.toggle("hidden");
  });
  $("#aiSettingsClose")?.addEventListener("click", () => {
    $("#aiSettingsPanel")?.classList.add("hidden");
  });
  $("#aiSettingsPanel")?.addEventListener("submit", saveAiSettings);

  const form = $("#aiForm");
  const input = $("#aiInput");
  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || state.aiBusy) return;
    input.value = "";
    input.style.height = "auto";
    aiSend(text);
  });
  input?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form?.requestSubmit();
    }
  });
  input?.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
  });
  document.querySelectorAll("[data-quick]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (state.aiBusy) return;
      aiSend(btn.dataset.quick);
    });
  });
}

async function saveAiSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const fd = new FormData(form);
  const value = {
    enabled: fd.get("enabled") === "on",
    base_url: String(fd.get("base_url") || "").trim(),
    model: String(fd.get("model") || "").trim(),
    system_prompt: String(fd.get("system_prompt") || "").trim(),
    temperature: parseFloat(fd.get("temperature")) || 0.3,
    max_tokens: parseInt(fd.get("max_tokens"), 10) || 2048,
  };
  const key = String(fd.get("api_key") || "").trim();
  if (key) value.api_key = key;
  try {
    await api("/api/settings/ai", { method: "PUT", body: JSON.stringify({ value }) });
    state.settings = await api("/api/settings");
    toast("AI 设置已保存");
    renderAiChat();
  } catch (error) {
    toast(error.message || "保存失败");
  }
}

async function aiSend(text) {
  if (state.aiBusy) return;
  state.aiBusy = true;
  $("#aiSend")?.setAttribute("disabled", "true");

  state.aiMessages.push({ role: "user", content: text });
  const assistant = { role: "assistant", content: "", tool_calls: [] };
  state.aiMessages.push(assistant);

  const thread = $("#aiThread");
  if (thread.querySelector(".ai-empty")) thread.innerHTML = "";
  appendAiUserBubble(text);
  const botNode = appendAiAssistantBubble();
  state._aiCurrent = { node: botNode, msg: assistant, pendingTool: null };

  const messages = state.aiMessages
    .filter((m) => m.role !== "assistant" || m.content || m.tool_calls?.length)
    .slice(-30)
    .map((m) => ({ role: m.role, content: m.content, tool_calls: m.tool_calls || undefined }));

  try {
    const res = await fetch("/api/ai/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, stream: true }),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(detail || `请求失败 ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        handleAiSseBlock(block);
      }
    }
  } catch (error) {
    appendAiError(error.message || "对话中断");
  } finally {
    state.aiBusy = false;
    $("#aiSend")?.removeAttribute("disabled");
    state._aiCurrent = null;
    const threadEl = $("#aiThread");
    if (threadEl) threadEl.scrollTop = threadEl.scrollHeight;
    if (!assistant.content && !assistant.tool_calls.length) {
      // 若完全无产出，移除空助手气泡
      state.aiMessages.pop();
      renderAiThread();
    }
  }
}

function handleAiSseBlock(block) {
  const lines = block.split("\n");
  let event = "message";
  const dataParts = [];
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataParts.push(line.slice(5).trim());
  }
  if (!dataParts.length) return;
  let data;
  try {
    data = JSON.parse(dataParts.join(""));
  } catch {
    return;
  }
  if (event === "delta") {
    appendAiDelta(data.text || "");
  } else if (event === "tool") {
    handleAiTool(data);
  } else if (event === "error") {
    appendAiError(data.message || "出错了");
  }
}

function appendAiUserBubble(text) {
  const thread = $("#aiThread");
  const el = document.createElement("div");
  el.className = "ai-msg ai-msg-user";
  el.innerHTML = `<div class="ai-bubble">${escapeHtml(text)}</div>`;
  thread.appendChild(el);
  thread.scrollTop = thread.scrollHeight;
}

function appendAiAssistantBubble() {
  const thread = $("#aiThread");
  const el = document.createElement("div");
  el.className = "ai-msg ai-msg-bot";
  el.innerHTML = `
    <div class="ai-avatar">AI</div>
    <div class="ai-bubble-group">
      <div class="ai-tools"></div>
      <div class="ai-bubble ai-assistant-text"><span class="ai-caret"></span></div>
    </div>`;
  thread.appendChild(el);
  thread.scrollTop = thread.scrollHeight;
  return el;
}

function appendAiDelta(text) {
  const cur = state._aiCurrent;
  if (!cur) return;
  cur.msg.content += text;
  const textEl = cur.node.querySelector(".ai-assistant-text");
  if (!textEl) return;
  const caret = textEl.querySelector(".ai-caret");
  textEl.insertAdjacentText("beforeend", text);
  if (caret) textEl.appendChild(caret);
  const thread = $("#aiThread");
  if (thread) thread.scrollTop = thread.scrollHeight;
}

function handleAiTool(data) {
  const cur = state._aiCurrent;
  if (!cur) return;
  const toolsEl = cur.node.querySelector(".ai-tools");
  if (!toolsEl) return;

  if (data.status === "running") {
    const card = document.createElement("details");
    card.className = "ai-tool is-running";
    card.open = true;
    card.innerHTML = `
      <summary>
        <span class="ai-tool-spin"></span>
        <span class="ai-tool-name">${escapeHtml(aiToolLabel(data.name))}</span>
        <span class="ai-tool-tag">${escapeHtml(data.name)}</span>
      </summary>`;
    toolsEl.appendChild(card);
    cur.pendingTool = { card, name: data.name, arguments: data.arguments };
    cur.msg.tool_calls.push({ name: data.name, arguments: data.arguments, result: null });
  } else if (data.status === "done") {
    const last = cur.msg.tool_calls[cur.msg.tool_calls.length - 1];
    if (last) last.result = data.result;
    const card = cur.pendingTool?.card;
    if (card) {
      card.classList.remove("is-running");
      card.classList.add("is-done");
      const args = cur.pendingTool.arguments ? JSON.stringify(cur.pendingTool.arguments, null, 2) : "";
      const result = data.result ? JSON.stringify(data.result, null, 2) : "";
      card.innerHTML = `
        <summary>
          <span class="ai-tool-check">✓</span>
          <span class="ai-tool-name">${escapeHtml(aiToolLabel(cur.pendingTool.name))}</span>
          <span class="ai-tool-tag">${escapeHtml(cur.pendingTool.name)}</span>
        </summary>
        ${args ? `<pre class="ai-tool-args">${escapeHtml(args)}</pre>` : ""}
        ${result ? `<pre class="ai-tool-result">${escapeHtml(result)}</pre>` : ""}`;
    }
    cur.pendingTool = null;
  }
  const thread = $("#aiThread");
  if (thread) thread.scrollTop = thread.scrollHeight;
}

function appendAiError(message) {
  const thread = $("#aiThread");
  const el = document.createElement("div");
  el.className = "ai-msg ai-msg-bot";
  el.innerHTML = `
    <div class="ai-avatar">AI</div>
    <div class="ai-bubble-group">
      <div class="ai-bubble ai-error">⚠ ${escapeHtml(message)}</div>
    </div>`;
  thread.appendChild(el);
  thread.scrollTop = thread.scrollHeight;
  if (state._aiCurrent) {
    state._aiCurrent.msg.content = state._aiCurrent.msg.content || `⚠ ${message}`;
  }
}
