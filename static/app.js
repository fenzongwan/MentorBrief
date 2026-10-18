const state = {
  conversations: [],
  moments: [],
  watchlist: [],
  settings: {},
  selectedConversation: null,
  messages: [],
  messagePage: {total: 0, limit: 200, offset: 0},
  lastSummary: null,
  showRealNames: false,
  todos: [],
  todoStatus: 'open',
  mentorReport: null,
  reportConversation: null,
  reportRange: 'all',
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function showToast(message, isError = false) {
  const toast = $('toast');
  toast.textContent = message;
  toast.style.background = isError ? '#b4261f' : '#20302a';
  toast.classList.remove('hidden');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add('hidden'), 3800);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

async function loadState() {
  const data = await api('/api/state');
  state.conversations = data.conversations;
  state.moments = data.moments;
  state.watchlist = data.watchlist;
  state.settings = data.settings;
  renderConversations();
  renderMoments();
  renderWatchlist();
  renderSettings();
  renderReportConversationOptions();
  updateMomentBadge(data.newMomentCount);
}

function renderConversations() {
  const keyword = $('conversationSearch').value.trim().toLowerCase();
  const list = state.conversations.filter((item) => {
    if (!keyword) return true;
    return item.title.toLowerCase().includes(keyword) || String(item.member_count).includes(keyword);
  });
  $('conversationList').innerHTML = list.map((item) => `
    <button class="conversation-item ${state.selectedConversation === item.id ? 'active' : ''}" data-id="${escapeHtml(item.id)}">
      <div class="conversation-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
      <div class="conversation-meta">${item.messageCount} 条 · ${item.member_count} 人 · ${escapeHtml(formatDate(item.lastMessageAt))}</div>
    </button>
  `).join('') || '<div class="conversation-meta">暂无会话，请先在设置页导入聊天记录。</div>';
  $('conversationList').querySelectorAll('.conversation-item').forEach((button) => {
    button.onclick = () => {
      state.selectedConversation = button.dataset.id;
      renderConversations();
      loadMessages();
    };
  });
}

function renderMessages(highlightIds = []) {
  const list = $('messageList');
  if (!Array.isArray(state.messages)) state.messages = [];
  const items = state.messages.map((message) => `
    <article class="message-item ${highlightIds.includes(message.id) ? 'highlight' : ''}" id="message-${escapeHtml(message.id)}">
      <div class="message-head">
        <span>${escapeHtml(displayName(message))} · ${escapeHtml(message.msg_type)}</span>
        <span>${escapeHtml(formatDate(message.sent_at))}</span>
      </div>
      <div class="message-body">${escapeHtml(message.content || (message.media_path ? '[媒体消息]' : '[空消息]'))}</div>
    </article>
  `).join('');
  list.innerHTML = items || '<div class="meta-line">该范围内没有消息。</div>';
  const loadEarlier = $('loadEarlierMessages');
  if (loadEarlier) loadEarlier.disabled = state.messages.length >= state.messagePage.total;
}

function displayName(message) {
  if (state.showRealNames) return message.original_name || message.sender_name;
  return message.sender_name;
}

function renderSummary(summary) {
  const container = $('summaryContent');
  container.classList.remove('empty');
  const sections = [
    ['highlights', '要点'],
    ['todos', '待办'],
    ['agreements', '约定'],
    ['links', '链接'],
  ];
  container.innerHTML = sections.map(([key, title]) => {
    const items = summary[key] || [];
    if (!items.length) return `<section class="summary-section"><h3>${title}</h3><div class="empty-result">无</div></section>`;
    return `<section class="summary-section"><h3>${title}</h3>${items.map((item) => `
      <div class="summary-item">
        <div>${escapeHtml(item.text || item.task || item.url)}</div>
        ${item.owner || item.deadline ? `<div class="meta-line">${escapeHtml(item.owner || '')}${item.deadline ? ' · ' + escapeHtml(item.deadline) : ''}</div>` : ''}
        ${(item.message_ids || []).map((id) => `<button class="ref" data-message-id="${escapeHtml(id)}">查看原文</button>`).join('')}
      </div>`).join('')}</section>`;
  }).join('');
  container.querySelectorAll('.ref').forEach((button) => {
    button.onclick = async () => {
      $('rawPanel').classList.remove('hidden');
      const reference = button.dataset.messageId;
      let message = state.messages.find((item) => item.id === reference)
        || state.messages.find((item) => item.sent_at === reference);
      if (!message) {
        try {
          message = await api(`/api/conversations/${encodeURIComponent(state.selectedConversation)}/messages/${encodeURIComponent(reference)}`);
          if (!state.messages.some((item) => item.id === message.id)) {
            state.messages.push(message);
          }
          state.messages.sort((a, b) => new Date(a.sent_at) - new Date(b.sent_at));
          state.messagePage.total = Math.max(state.messagePage.total, state.messages.length);
        } catch (error) {
          showToast(error.message || '没有找到对应的原始消息', true);
          return;
        }
      }
      renderMessages([message.id]);
      requestAnimationFrame(() => {
        const target = document.getElementById(`message-${message.id}`);
        if (!target) return showToast('原文已读取，但页面上没有找到对应位置', true);
        target.scrollIntoView({behavior: 'smooth', block: 'center'});
      });
    };
  });
}

function renderReportConversationOptions() {
  const select = $('reportConversationSelect');
  if (!select) return;
  const current = state.reportConversation || state.mentorReport?.conversation_id || select.value;
  const conversations = state.conversations || [];
  const preferred = conversations.find((item) => item.id === current)
    || conversations.find((item) => item.title.includes('导师'))
    || conversations[0];
  select.innerHTML = conversations.map((item) => `
    <option value="${escapeHtml(item.id)}">${escapeHtml(item.title)} · ${item.messageCount} 条</option>
  `).join('');
  select.disabled = conversations.length === 0;
  state.reportConversation = preferred ? preferred.id : null;
  select.value = state.reportConversation || '';
}

function renderEmptyMentorReport(message) {
  state.mentorReport = null;
  $('reportTitle').textContent = '沟通简报';
  $('reportMeta').textContent = '只整理你已收到的沟通，不上传原始聊天。';
  $('reportMetrics').innerHTML = '';
  const container = $('mentorReport');
  container.classList.add('empty');
  container.innerHTML = `<p>${escapeHtml(message)}</p>`;
}

async function loadMentorReport(conversationId = null) {
  const select = $('reportConversationSelect');
  if (!state.conversations.length) {
    renderEmptyMentorReport('还没有会话。请先在“消息总结”页导入聊天记录。');
    return;
  }
  renderReportConversationOptions();
  const targetId = conversationId || state.reportConversation || select.value;
  if (!targetId) {
    renderEmptyMentorReport('请先选择要整理的会话。');
    return;
  }
  state.reportConversation = targetId;
  select.value = targetId;
  const conversation = state.conversations.find((item) => item.id === targetId);
  try {
    const data = await api(`/api/reports/mentor?conversationId=${encodeURIComponent(targetId)}`);
    state.mentorReport = data;
    state.reportConversation = data.conversation_id;
    renderMentorReport(data);
    await renderReportMetrics(data);
    await loadReplyOutline(data.conversation_id);
  } catch (error) {
    renderEmptyMentorReport(
      `${conversation ? conversation.title : '当前会话'}还没有沟通简报。点击“生成沟通简报”开始整理。`,
    );
  }
}

async function renderReportMetrics(data) {
  const metrics = $('reportMetrics');
  try {
    const [appState, openTodos] = await Promise.all([
      api('/api/state'),
      api('/api/todos?status=open'),
    ]);
    const conversation = (appState.conversations || []).find((item) => item.id === data.conversation_id)
      || (appState.conversations || [])[0];
    const report = data.result || {};
    const items = [
      {value: conversation ? conversation.messageCount : '—', label: '导师消息', note: '已收到'},
      {value: openTodos.length, label: '待办', note: '待跟进'},
      {value: appState.newMomentCount || 0, label: '新动态', note: '关注对象'},
      {value: (report.actions || []).length, label: '行动项', note: '本次简报'},
    ];
    metrics.innerHTML = items.map((item) => `
      <div class="metric-card">
        <div class="metric-value">${escapeHtml(String(item.value))}</div>
        <div class="metric-label">${escapeHtml(item.label)}</div>
        <div class="metric-note">${escapeHtml(item.note)}</div>
      </div>
    `).join('');
    updateTodoBadge(openTodos.length);
  } catch (_) {
    metrics.innerHTML = '';
  }
}

function renderMentorReport(data) {
  const report = data.result || {};
  const container = $('mentorReport');
  container.classList.remove('empty');
  $('reportTitle').textContent = report.title || '沟通简报';
  $('reportMeta').textContent = [report.date, data.conversation_title, `生成于 ${formatDate(data.created_at)}`]
    .filter(Boolean)
    .join(' · ');

  const signals = (report.signals || []).map((item) => `
    <div class="report-item">
      <div class="report-item-head">
        <span class="tag">${escapeHtml(item.label || '')}</span>
        <span class="meta-line">${escapeHtml(item.source || '')}</span>
      </div>
      <p>${escapeHtml(item.text || '')}</p>
    </div>
  `).join('');

  const technical = (report.technicalConclusions || []).map((item) => `
    <div class="report-item">
      <strong>${escapeHtml(item.topic || '')}</strong>
      <p>${escapeHtml(item.conclusion || '')}</p>
    </div>
  `).join('');

  const actions = (report.actions || []).map((item) => `
    <div class="action-item">
      <div>
        <strong>${escapeHtml(item.task || '')}</strong>
        <div class="meta-line">${escapeHtml(item.owner || '')}${item.due ? ' · ' + escapeHtml(item.due) : ''}</div>
      </div>
      <span class="priority priority-${escapeHtml(item.priority || 'normal')}">${escapeHtml(item.priority || 'normal')}</span>
    </div>
  `).join('');

  const questions = (report.openQuestions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('');

  container.innerHTML = `
    <div class="report-hero">
      <div class="report-kicker">${escapeHtml(report.mentor || '导师')} · 今日关键信号</div>
      <h3>${escapeHtml(report.headline || '')}</h3>
      <div class="report-hero-note">${escapeHtml(report.privacyNote || '')}</div>
    </div>
    <div class="report-grid">
      <section class="report-card">
        <h3>关键信号</h3>
        ${signals || '<div class="empty-result">暂无</div>'}
      </section>
      <section class="report-card">
        <h3>技术结论</h3>
        ${technical || '<div class="empty-result">暂无</div>'}
      </section>
      <section class="report-card wide">
        <h3>下一步行动</h3>
        ${actions || '<div class="empty-result">暂无</div>'}
      </section>
      <section class="report-card">
        <h3>待确认</h3>
        ${questions ? `<ul class="question-list">${questions}</ul>` : '<div class="empty-result">暂无</div>'}
      </section>
      <section class="report-card">
        <h3>建议回复</h3>
        <p class="reply-text">${escapeHtml(report.suggestedReply || '')}</p>
        <button class="ghost" id="copyReply">复制回复</button>
      </section>
      <section class="report-card wide">
        <div class="panel-head">
          <h3>下次回复提纲</h3>
          <button class="ghost" id="generateOutline">生成提纲</button>
        </div>
        <div id="replyOutlineBody" class="outline-body">
          <div class="empty-result">点击“生成提纲”，按当前简报整理回复要点。</div>
        </div>
      </section>
    </div>
  `;

  const copyButton = $('copyReply');
  if (copyButton) {
    copyButton.onclick = async () => {
      try {
        await navigator.clipboard.writeText(report.suggestedReply || '');
        showToast('建议回复已复制');
      } catch (_) {
        showToast('复制失败，请手动选择文本', true);
      }
    };
  }

  const generateButton = $('generateOutline');
  if (generateButton) {
    generateButton.onclick = () => generateReplyOutline(data.conversation_id);
  }
}

async function generateMentorReport() {
  const conversationId = $('reportConversationSelect').value || state.reportConversation;
  if (!conversationId) return showToast('请先选择要整理的会话', true);
  const button = $('generateReport');
  const range = $('reportRangeSelect').value;
  state.reportConversation = conversationId;
  state.reportRange = range;
  button.disabled = true;
  button.textContent = '生成中...';
  const container = $('mentorReport');
  container.classList.add('empty');
  container.innerHTML = '<p>正在读取消息并生成沟通简报，通常需要几秒到一分钟。</p>';
  try {
    const data = await api('/api/reports/mentor', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({conversationId, range}),
    });
    state.mentorReport = data;
    state.reportConversation = data.conversation_id;
    $('reportConversationSelect').value = data.conversation_id;
    renderMentorReport(data);
    await renderReportMetrics(data);
    await loadReplyOutline(data.conversation_id);
    const providerLabel = data.provider === 'fallback_local' ? '（本地兜底）' : '';
    showToast(`沟通简报已生成${providerLabel} · ${data.messageCount} 条消息`);
  } catch (error) {
    renderEmptyMentorReport(`生成失败：${error.message}`);
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = '生成沟通简报';
  }
}

async function loadReplyOutline(conversationId) {
  const container = $('replyOutlineBody');
  if (!container) return;
  try {
    const data = await api(`/api/reply-outline?conversationId=${encodeURIComponent(conversationId)}`);
    renderReplyOutline(data.result);
  } catch (error) {
    container.innerHTML = `<div class="empty-result">${escapeHtml(error.message)}</div>`;
  }
}

async function generateReplyOutline(conversationId) {
  const button = $('generateOutline');
  if (button) {
    button.disabled = true;
    button.textContent = '生成中...';
  }
  try {
    const data = await api('/api/reply-outline', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({conversationId}),
    });
    renderReplyOutline(data.result);
    showToast('回复提纲已生成');
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = '生成提纲';
    }
  }
}

function renderReplyOutline(outline) {
  const container = $('replyOutlineBody');
  if (!container) return;
  const mustAnswer = (outline.mustAnswer || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  const structure = (outline.structure || []).map((section) => `
    <div class="outline-step">
      <div class="outline-step-title">${escapeHtml(section.section || '')}</div>
      <ul>${(section.points || []).map((point) => `<li>${escapeHtml(point)}</li>`).join('')}</ul>
    </div>
  `).join('');
  const keyPoints = (outline.keyPoints || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  const avoid = (outline.avoid || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('');

  container.innerHTML = `
    <div class="outline-goal">
      <span class="tag">目标</span>
      <p>${escapeHtml(outline.goal || '')}</p>
    </div>
    <div class="outline-columns">
      <section>
        <h4>必须回应</h4>
        ${mustAnswer ? `<ol>${mustAnswer}</ol>` : '<div class="empty-result">暂无</div>'}
      </section>
      <section>
        <h4>建议结构</h4>
        ${structure || '<div class="empty-result">暂无</div>'}
      </section>
      <section>
        <h4>关键要点</h4>
        ${keyPoints ? `<ul>${keyPoints}</ul>` : '<div class="empty-result">暂无</div>'}
      </section>
      <section>
        <h4>避免</h4>
        ${avoid ? `<ul>${avoid}</ul>` : '<div class="empty-result">暂无</div>'}
      </section>
    </div>
    <div class="outline-draft">
      <h4>可直接改写的草稿</h4>
      <p class="reply-text">${escapeHtml(outline.draft || '')}</p>
      <button class="ghost" id="copyOutline">复制草稿</button>
    </div>
  `;

  const copyButton = $('copyOutline');
  if (copyButton) {
    copyButton.onclick = async () => {
      try {
        await navigator.clipboard.writeText(outline.draft || '');
        showToast('回复草稿已复制');
      } catch (_) {
        showToast('复制失败，请手动选择文本', true);
      }
    };
  }
}

function renderMoments() {
  const list = $('momentList');
  list.innerHTML = state.moments.map((moment) => `
    <article class="moment-card ${moment.is_new ? 'new' : ''}">
      <div class="moment-head">
        <strong>${escapeHtml(moment.author_name)}</strong>
        <span>${moment.is_new ? '新增 · ' : ''}${escapeHtml(formatDate(moment.created_at))}</span>
      </div>
      <div class="moment-body">${escapeHtml(moment.content || '[无文字]')}</div>
      <div class="media-list">${(moment.media_paths || []).map((path) => `<div class="media-box" title="${escapeHtml(path)}">图片</div>`).join('')}</div>
    </article>
  `).join('') || '<div class="meta-line">暂无关注动态。请先添加关注名单，再导入朋友圈数据。</div>';
}

function renderWatchlist() {
  $('watchList').innerHTML = state.watchlist.map((item) => `
    <div class="watch-item">
      <div class="conversation-title">${escapeHtml(item.display_name)}</div>
      <div class="conversation-meta">${escapeHtml(item.author_id)}</div>
      <button class="ghost" style="margin-top:8px" data-id="${encodeURIComponent(item.author_id)}">删除</button>
    </div>
  `).join('') || '<div class="meta-line">暂无关注对象。</div>';
  $('watchList').querySelectorAll('button').forEach((button) => {
    button.onclick = async () => {
      try {
        await api(`/api/watchlist/${button.dataset.id}`, {method: 'DELETE'});
        showToast('已删除关注对象');
        await loadState();
      } catch (error) { showToast(error.message, true); }
    };
  });
}

function renderSettings() {
  $('provider').value = state.settings.provider || 'mock';
  $('apiBaseUrl').value = state.settings.apiBaseUrl || '';
  $('model').value = state.settings.model || '';
  $('apiKey').value = '';
  $('apiKey').placeholder = state.settings.apiKeyConfigured ? `已配置：${state.settings.apiKeyPreview}` : '未配置';
  $('requestTimeoutSeconds').value = state.settings.requestTimeoutSeconds || 45;
  $('maxMessagesPerRequest').value = state.settings.maxMessagesPerRequest || 500;
  $('maskNames').checked = Boolean(state.settings.maskNames);
  $('fallbackToLocal').checked = Boolean(state.settings.fallbackToLocal ?? true);
}

async function renderAudit() {
  const rows = await api('/api/audit');
  const header = `<div class="audit-row header"><div>时间</div><div>动作</div><div>条数</div><div>脱敏</div><div>对象 / 结果</div></div>`;
  $('auditTable').innerHTML = header + rows.map((row) => `
    <div class="audit-row">
      <div>${escapeHtml(formatDate(row.created_at))}</div>
      <div>${escapeHtml(row.action)}</div>
      <div>${row.item_count}</div>
      <div>${row.masked ? '是' : '否'}</div>
      <div><span class="${row.status === 'ok' ? 'status-ok' : 'status-error'}">${escapeHtml(row.status)}</span> · ${escapeHtml(row.target || '')}${row.provider ? ' · ' + escapeHtml(row.provider) : ''}</div>
    </div>`).join('');
}

function updateMomentBadge(count) {
  const badge = $('momentBadge');
  badge.textContent = count;
  badge.classList.toggle('hidden', !count);
  const alert = $('momentAlert');
  if (count) {
    alert.textContent = `检测到 ${count} 条新增朋友圈动态，请在时间线中查看。`;
    alert.classList.remove('hidden');
  } else {
    alert.classList.add('hidden');
  }
}

function formatDate(value) {
  if (!value) return '暂无时间';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {hour12: false});
}

async function loadMessages({append = false} = {}) {
  if (!state.selectedConversation) return;
  try {
    const conversation = state.conversations.find((item) => item.id === state.selectedConversation);
    $('summaryTitle').textContent = conversation ? conversation.title : '会话';
    const range = $('rangeSelect').value;
    const offset = append ? state.messages.length : 0;
    const data = await api(`/api/conversations/${encodeURIComponent(state.selectedConversation)}/messages?range=${range}&limit=200&offset=${offset}`);
    const incoming = Array.isArray(data) ? data : (data.messages || []);
    state.messages = append ? state.messages.concat(incoming) : incoming;
    state.messagePage = {
      total: Array.isArray(data) ? incoming.length : (data.total ?? incoming.length),
      limit: Array.isArray(data) ? incoming.length : (data.limit ?? incoming.length),
      offset: Array.isArray(data) ? 0 : (data.offset ?? 0),
    };
    renderMessages();
    const summaries = await api('/api/summaries');
    const latest = summaries.find((item) => item.conversation_id === state.selectedConversation);
    if (latest) {
      renderSummary(latest.result);
      $('summaryMeta').textContent = `最近一次总结：${latest.message_count} 条消息 · ${latest.provider} · ${latest.masked ? '已脱敏' : '未脱敏'}`;
    } else {
      $('summaryContent').classList.add('empty');
      $('summaryContent').innerHTML = '<p>还没有总结。点击右上角「一键总结」生成要点、待办、约定和链接。</p>';
      $('summaryMeta').textContent = `已读取 ${state.messages.length}/${data.total} 条消息 · ${$('rangeSelect').selectedOptions[0].text}`;
    }
    $('rawPanel').classList.remove('hidden');
  } catch (error) { showToast(error.message, true); }
}

async function createSummary() {
  if (!state.selectedConversation) return showToast('请先选择会话', true);
  const button = $('summarize');
  button.disabled = true;
  button.textContent = '总结中...';
  try {
    const data = await api('/api/summaries', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({conversationId: state.selectedConversation, range: $('rangeSelect').value}),
    });
    state.lastSummary = data.result;
    renderSummary(data.result);
    $('summaryMeta').textContent = `已总结 ${data.messageCount} 条消息 · ${data.provider} · ${data.masked ? '已脱敏' : '未脱敏'}`;
    showToast('总结完成');
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = '一键总结';
  }
}

async function importFile(file, endpoint) {
  const form = new FormData();
  form.append('file', file);
  return api(endpoint, {method: 'POST', body: form});
}

function updateTodoBadge(count) {
  const badge = $('todoBadge');
  badge.textContent = count;
  badge.classList.toggle('hidden', !count);
}

async function loadTodos(status = state.todoStatus) {
  try {
    const query = status === 'all' ? '' : `?status=${encodeURIComponent(status)}`;
    const [items, openItems] = await Promise.all([
      api(`/api/todos${query}`),
      api('/api/todos?status=open'),
    ]);
    state.todos = items;
    state.todoStatus = status;
    renderTodos(items, openItems.length);
    updateTodoBadge(openItems.length);
    $('todoFilters').querySelectorAll('.chip').forEach((chip) => {
      chip.classList.toggle('active', chip.dataset.status === status);
    });
  } catch (error) {
    $('todoList').innerHTML = `<div class="empty-result">${escapeHtml(error.message)}</div>`;
  }
}

function renderTodos(items, openCount) {
  $('todoSummary').textContent = `${openCount} 项待办 · 当前显示 ${items.length} 项`;
  const list = $('todoList');
  list.innerHTML = items.map((item) => {
    const priorityLabel = {high: '高', medium: '中', low: '低'}[item.priority] || item.priority;
    const done = item.status === 'done';
    return `
      <article class="todo-item ${done ? 'done' : ''}">
        <input type="checkbox" data-id="${escapeHtml(item.id)}" ${done ? 'checked' : ''} aria-label="切换完成状态">
        <div class="todo-main">
          <div class="todo-title">${escapeHtml(item.title)}</div>
          <div class="meta-line">${escapeHtml(item.owner || '')}${item.due ? ' · ' + escapeHtml(item.due) : ''} · ${escapeHtml(priorityLabel)}优先级</div>
          <div class="todo-source">${escapeHtml(item.conversation_title || '')}</div>
        </div>
      </article>
    `;
  }).join('') || '<div class="empty-result">暂无跟进事项。可以在左侧添加一条。</div>';

  list.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    checkbox.onchange = async () => {
      try {
        await api(`/api/todos/${encodeURIComponent(checkbox.dataset.id)}`, {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({status: checkbox.checked ? 'done' : 'open'}),
        });
        showToast(checkbox.checked ? '已标记完成' : '已恢复待办');
        await loadTodos(state.todoStatus);
      } catch (error) {
        showToast(error.message, true);
      }
    };
  });
}

function bindEvents() {
  $('tabs').addEventListener('click', (event) => {
    const button = event.target.closest('.tab');
    if (!button) return;
    document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab === button));
    document.querySelectorAll('.page').forEach((page) => page.classList.toggle('active', page.id === `page-${button.dataset.tab}`));
    if (button.dataset.tab === 'settings') renderAudit();
    if (button.dataset.tab === 'report') loadMentorReport();
    if (button.dataset.tab === 'todos') loadTodos();
  });
  $('refreshReport').onclick = () => loadMentorReport();
  $('reportConversationSelect').onchange = () => {
    state.reportConversation = $('reportConversationSelect').value;
    loadMentorReport(state.reportConversation);
  };
  $('reportRangeSelect').onchange = () => {
    state.reportRange = $('reportRangeSelect').value;
  };
  $('generateReport').onclick = generateMentorReport;
  $('refreshTodos').onclick = () => loadTodos();
  $('todoFilters').addEventListener('click', (event) => {
    const chip = event.target.closest('.chip');
    if (chip) loadTodos(chip.dataset.status);
  });
  $('todoForm').onsubmit = async (event) => {
    event.preventDefault();
    const title = $('todoTitle').value.trim();
    if (!title) return showToast('请填写跟进事项', true);
    try {
      await api('/api/todos', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          title,
          due: $('todoDue').value.trim(),
          priority: $('todoPriority').value,
          conversationId: state.mentorReport ? state.mentorReport.conversation_id : undefined,
        }),
      });
      $('todoTitle').value = '';
      $('todoDue').value = '';
      showToast('已添加跟进事项');
      await loadTodos('open');
    } catch (error) { showToast(error.message, true); }
  };
  $('refreshState').onclick = () => loadState().then(() => showToast('已刷新')).catch((error) => showToast(error.message, true));
  $('conversationSearch').oninput = renderConversations;
  $('loadMessages').onclick = () => loadMessages();
  $('loadEarlierMessages').onclick = () => loadMessages({append: true});
  $('summarize').onclick = createSummary;
  $('toggleRaw').onclick = () => $('rawPanel').classList.toggle('hidden');
  $('toggleRealNames').onclick = async () => {
    if (!state.showRealNames && state.settings.maskNames) {
      const ok = confirm('显示原名会把真实备注名暴露在当前屏幕上，确认继续吗？');
      if (!ok) return;
    }
    state.showRealNames = !state.showRealNames;
    $('toggleRealNames').textContent = state.showRealNames ? '恢复脱敏' : '显示原名';
    renderMessages();
  };
  $('importChats').onchange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const data = await importFile(file, '/api/import/chats');
      showToast(`聊天导入完成：识别 ${data.stats.records} 条，新增 ${data.stats.inserted} 条，会话 ${data.stats.conversations} 个`);
      await loadState();
    } catch (error) { showToast(error.message, true); } finally { event.target.value = ''; }
  };
  $('watchForm').onsubmit = async (event) => {
    event.preventDefault();
    try {
      await api('/api/watchlist', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({displayName: $('watchName').value, authorId: $('watchId').value}),
      });
      $('watchName').value = '';
      $('watchId').value = '';
      showToast('已添加关注对象');
      await loadState();
    } catch (error) { showToast(error.message, true); }
  };
  $('importMoments').onchange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const data = await importFile(file, '/api/import/moments');
      const authors = (data.stats.authors || [])
        .filter((author, index, list) => list.findIndex((item) => item.id === author.id) === index)
        .map((author) => `${author.name}（${author.id}）`);
      const authorHint = data.stats.watched === 0 && authors.length
        ? `。未匹配关注对象，请添加：${authors.join('、')}`
        : '';
      showToast(`朋友圈导入完成：识别 ${data.stats.records} 条，关注 ${data.stats.watched} 条，新增 ${data.stats.new} 条${authorHint}`, true);
      await loadState();
    } catch (error) { showToast(error.message, true); } finally { event.target.value = ''; }
  };
  $('markMomentsRead').onclick = async () => {
    try {
      await api('/api/moments/mark-read', {method: 'POST'});
      await loadState();
      showToast('已标记为已读');
    } catch (error) { showToast(error.message, true); }
  };
  $('settingsForm').onsubmit = async (event) => {
    event.preventDefault();
    const payload = {
      provider: $('provider').value,
      apiBaseUrl: $('apiBaseUrl').value,
      model: $('model').value,
      requestTimeoutSeconds: Number($('requestTimeoutSeconds').value || 45),
      maxMessagesPerRequest: Number($('maxMessagesPerRequest').value || 500),
      maskNames: $('maskNames').checked,
      fallbackToLocal: $('fallbackToLocal').checked,
    };
    if ($('apiKey').value) payload.apiKey = $('apiKey').value;
    try {
      await api('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      showToast('设置已保存');
      await loadState();
    } catch (error) { showToast(error.message, true); }
  };
}

bindEvents();
loadState()
  .then(() => loadMentorReport())
  .catch((error) => showToast(error.message, true));
