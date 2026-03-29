(function () {
  const appPath = (path) => (typeof window.__appPath === "function" ? window.__appPath(path) : path);
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function nl2br(value) {
    return escapeHtml(value).replace(/\n/g, "<br>");
  }

  function renderAssistantMessage(msg, layout, labels, animateLatest) {
    const analysis = msg && msg.analysis ? String(msg.analysis) : "";
    const refined = msg && msg.refined_idea ? String(msg.refined_idea) : "";
    const questions = Array.isArray(msg && msg.questions) ? msg.questions : [];
    if (layout === "detail") {
      return `
        <article class="chat-bubble chat-assistant${animateLatest ? " is-pending" : ""}">
          <div class="chat-role">Claw / Copilot</div>
          <div ${animateLatest ? 'data-live-analysis="1"' : ""}>${animateLatest ? "" : nl2br(analysis)}</div>
          ${questions.length ? `<div class="soft-text" style="margin-top: 12px; font-weight: 700;">${escapeHtml(labels.nextAnswers)}</div><ul style="margin-top: 8px;" ${animateLatest ? 'data-live-questions="1"' : ""}>${animateLatest ? "" : questions.map((q) => `<li>${escapeHtml(q)}</li>`).join("")}</ul>` : `<div ${animateLatest ? 'data-live-questions="1"' : ""}></div>`}
          ${refined ? `<div class="soft-block" style="margin-top: 14px;" ${animateLatest ? 'data-live-refined="1"' : ""}>${animateLatest ? "" : nl2br(refined)}</div>` : `<div ${animateLatest ? 'data-live-refined="1"' : ""}></div>`}
        </article>
      `;
    }
    return `
      <div class="chat-row assistant${animateLatest ? " is-pending" : ""}">
        <div class="avatar-circle">WC</div>
        <div class="assistant-panel">
          <div class="assistant-section">
            <div class="assistant-title">${escapeHtml(labels.analysisTitle)}</div>
            <div class="assistant-text" ${animateLatest ? 'data-live-analysis="1"' : ""}>${animateLatest ? "" : nl2br(analysis)}</div>
          </div>
          <div class="assistant-section split-line">
            <div class="assistant-title">${escapeHtml(labels.nextQuestions)}</div>
            <ol class="question-list" ${animateLatest ? 'data-live-questions="1"' : ""}>${animateLatest ? "" : questions.map((q) => `<li>${escapeHtml(q)}</li>`).join("")}</ol>
          </div>
          <div class="assistant-section split-line">
            <div class="assistant-title">${escapeHtml(labels.currentBrief)}</div>
            <div class="assistant-text" ${animateLatest ? 'data-live-refined="1"' : ""}>${animateLatest ? "" : nl2br(refined)}</div>
          </div>
        </div>
      </div>
    `;
  }

  function renderUserMessage(msg, layout, labels) {
    const content = nl2br(msg && msg.content ? msg.content : "");
    if (layout === "detail") {
      return `<article class="chat-bubble chat-user"><div class="chat-role">${escapeHtml(labels.you)}</div><div>${content}</div></article>`;
    }
    return `<div class="chat-row user"><div class="user-bubble">${content}</div><div class="user-tag">${escapeHtml(labels.you)}</div></div>`;
  }

  function renderMessages(feed, messages, layout, labels, animateLatest) {
    if (!feed) return;
    if (!Array.isArray(messages) || !messages.length) {
      feed.innerHTML = layout === "detail"
        ? `<div class="soft-block">${escapeHtml(labels.noConversation)}</div>`
        : `<div class="chat-row assistant"><div class="avatar-circle">WC</div><div class="assistant-panel"><div class="assistant-section"><div class="assistant-title">${escapeHtml(labels.emptyTitle)}</div><div class="assistant-text">${escapeHtml(labels.emptyBody)}</div></div></div></div>`;
      return;
    }
    const latestAssistantIndex = animateLatest
      ? [...messages].map((item, index) => ({ item, index })).filter((item) => item.item.role === "assistant").map((item) => item.index).pop()
      : -1;
    feed.innerHTML = messages.map((msg, index) => {
      if (msg.role === "assistant") {
        return renderAssistantMessage(msg, layout, labels, animateLatest && index === latestAssistantIndex);
      }
      return renderUserMessage(msg, layout, labels);
    }).join("");
  }

  function animateAssistant(feed, latestTurn) {
    if (!feed || !latestTurn) return;
    const analysisEl = feed.querySelector('[data-live-analysis="1"]');
    const questionsEl = feed.querySelector('[data-live-questions="1"]');
    const refinedEl = feed.querySelector('[data-live-refined="1"]');
    const analysis = String(latestTurn.analysis || "");
    let index = 0;
    function tick() {
      if (!analysisEl) return;
      analysisEl.innerHTML = nl2br(analysis.slice(0, index));
      if (index < analysis.length) {
        index += Math.max(1, Math.ceil(analysis.length / 120));
        window.setTimeout(tick, 18);
        return;
      }
      if (questionsEl && Array.isArray(latestTurn.questions)) {
        if (questionsEl.tagName === "OL" || questionsEl.tagName === "UL") {
          questionsEl.innerHTML = latestTurn.questions.map((q) => `<li>${escapeHtml(q)}</li>`).join("");
        }
      }
      if (refinedEl) {
        refinedEl.innerHTML = nl2br(String(latestTurn.refined_idea || ""));
      }
      const pending = feed.querySelector('.is-pending');
      if (pending) pending.classList.remove('is-pending');
    }
    tick();
  }

  function appendPending(feed, layout, labels) {
    if (!feed) return;
    const pendingHtml = layout === "detail"
      ? `<article class="chat-bubble chat-assistant is-pending" data-pending-row="1"><div class="chat-role">Claw / Copilot</div><div class="typing-dots">${escapeHtml(labels.thinking)}</div></article>`
      : `<div class="chat-row assistant is-pending" data-pending-row="1"><div class="avatar-circle">WC</div><div class="assistant-panel"><div class="assistant-section"><div class="assistant-title">${escapeHtml(labels.analysisTitle)}</div><div class="assistant-text typing-dots">${escapeHtml(labels.thinking)}</div></div></div></div>`;
    feed.insertAdjacentHTML("beforeend", pendingHtml);
  }

  function updateSummary(root, payload) {
    root.querySelectorAll('[data-refined-idea]').forEach((el) => {
      el.textContent = payload.refined_idea || "";
    });
    root.querySelectorAll('[data-round-count]').forEach((el) => {
      el.textContent = String(payload.round_count || 0);
    });
    root.querySelectorAll('[data-ready-hint]').forEach((el) => {
      el.textContent = payload.latest_turn && payload.latest_turn.ready_hint ? payload.latest_turn.ready_hint : "";
    });
  }

  function init(root) {
    if (!root) return;
    if (root.dataset.liveInitialized === 'true') return;
    const form = root.querySelector('[data-idea-reply-form]');
    const feed = root.querySelector('[data-idea-feed]');
    if (!form || !feed) return;
    root.dataset.liveInitialized = 'true';
    const layout = root.dataset.layout || "dashboard";
    const sessionId = root.dataset.sessionId || "";
    const labels = {
      you: root.dataset.labelYou || "You",
      thinking: root.dataset.labelThinking || "Thinking",
      analysisTitle: root.dataset.labelAnalysisTitle || "NovelClaw analysis",
      nextQuestions: root.dataset.labelNextQuestions || "Next questions",
      currentBrief: root.dataset.labelCurrentBrief || "Current writing brief",
      nextAnswers: root.dataset.labelNextAnswers || "Suggested next answers:",
      readiness: root.dataset.labelReadiness || "Readiness",
      noConversation: root.dataset.labelNoConversation || "No conversation yet.",
      emptyTitle: root.dataset.labelEmptyTitle || "Welcome",
      emptyBody: root.dataset.labelEmptyBody || "Start a session.",
      continuing: root.dataset.labelContinuing || "NovelClaw is continuing...",
      runStarted: root.dataset.labelRunStarted || "NovelClaw started the run. Refreshing the workspace...",
    };
    const textarea = form.querySelector('textarea[name="reply"]');
    const submitBtn = form.querySelector('button[type="submit"]');
    let polling = null;
    let pollErrorCount = 0;
    let recoveryRedirect = false;
    let pollTicks = 0;
    const MIN_PENDING_MS = 900;
    const POST_SUCCESS_STATUS_MS = 1400;

    function scrollFeedToBottom() {
      if (!feed) return;
      feed.scrollTop = feed.scrollHeight;
    }

    function latestVisibleMessageIsUser() {
      const last = feed ? feed.lastElementChild : null;
      if (!last || !last.classList) return false;
      return last.classList.contains('user') || last.classList.contains('chat-user');
    }

    function ensurePendingVisual() {
      if (!feed || feed.querySelector('[data-pending-row="1"]')) return;
      appendPending(feed, layout, labels);
      scrollFeedToBottom();
    }

    function normalizeError(value, fallback) {
      if (!value) return fallback || "Request failed";
      if (typeof value === "string") return value;
      if (value instanceof Error) return value.message || fallback || "Request failed";
      if (Array.isArray(value)) return value.map((item) => normalizeError(item, "")).filter(Boolean).join(" | " );
      if (typeof value === "object") {
        if (typeof value.error === "string") return value.error;
        if (typeof value.message === "string") return value.message;
        if (typeof value.detail === "string") return value.detail;
        if (Array.isArray(value.detail)) return normalizeError(value.detail, fallback);
        if (Array.isArray(value.loc)) {
          const prefix = value.loc.join(".");
          return value.msg ? `${prefix}: ${value.msg}` : prefix;
        }
        if (typeof value.msg === "string") return value.msg;
      }
      return fallback || String(value);
    }

    function ensureStatusNode() {
      let node = root.querySelector('[data-idea-status]');
      if (!node) {
        node = document.createElement('div');
        node.setAttribute('data-idea-status', '1');
        node.className = 'console-alert';
        node.hidden = true;
        form.insertAdjacentElement('beforebegin', node);
      }
      return node;
    }

    function setStatus(kind, message) {
      const node = ensureStatusNode();
      const text = normalizeError(message, '');
      if (!text) {
        node.hidden = true;
        node.textContent = '';
        node.className = 'console-alert';
        return;
      }
      node.hidden = false;
      node.className = `console-alert ${kind === 'error' ? 'error' : 'ok'}`;
      node.textContent = text;
    }

    function sleep(ms) {
      return new Promise((resolve) => window.setTimeout(resolve, ms));
    }

    async function readPayload(response) {
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        return response.json();
      }
      const raw = await response.text();
      return { ok: response.ok, error: raw || response.statusText || 'Request failed' };
    }

    function setBusy(isBusy) {
      if (textarea) textarea.disabled = isBusy;
      if (submitBtn) submitBtn.disabled = isBusy;
    }

    function forceRefreshToSession() {
      if (recoveryRedirect || !sessionId) return;
      recoveryRedirect = true;
      window.setTimeout(function () {
        window.location.href = appPath(`/console/chat?session_id=${encodeURIComponent(sessionId)}`);
      }, 350);
    }

    function refreshWorkspaceWhenRunStarts(payload) {
      if (!payload || payload.status === 'active' || !payload.final_job_id || !sessionId) {
        return false;
      }
      setStatus('ok', labels.runStarted);
      window.setTimeout(function () {
        window.location.href = appPath(`/console/chat?session_id=${encodeURIComponent(sessionId)}`);
      }, 500);
      return true;
    }

    async function fetchState(animateLatest) {
      const baseUrl = appPath(`/api/idea-copilot/${sessionId}/state`);
      const sep = baseUrl.includes('?') ? '&' : '?';
      const response = await fetch(`${baseUrl}${sep}_=${Date.now()}`, {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      });
      const payload = await readPayload(response);
      if (!response.ok || !payload.ok) {
        throw new Error(normalizeError(payload, 'Failed to load state'));
      }
      if (!payload.reply_pending && payload.reply_error) {
        throw new Error(normalizeError(payload.reply_error, 'Reply failed'));
      }
      updateSummary(root, payload);
      if (!payload.reply_pending) {
        if (refreshWorkspaceWhenRunStarts(payload)) {
          return payload;
        }
        renderMessages(feed, payload.messages, layout, labels, !!animateLatest);
        scrollFeedToBottom();
        if (animateLatest && payload.latest_turn && payload.latest_turn.role === 'assistant') {
          animateAssistant(feed, payload.latest_turn);
        }
      }
      return payload;
    }

    function startPolling(options) {
      const forceUntilAssistant = !!(options && options.forceUntilAssistant);
      if (polling) window.clearInterval(polling);
      pollTicks = 0;
      polling = window.setInterval(async function () {
        try {
          pollTicks += 1;
          const payload = await fetchState(false);
          pollErrorCount = 0;
          if (!payload.reply_pending) {
            const messages = Array.isArray(payload.messages) ? payload.messages : [];
            const latestRole = messages.length ? String(messages[messages.length - 1].role || '') : '';
            const waitForAssistant = forceUntilAssistant && !payload.final_job_id && latestRole === 'user';
            if (waitForAssistant) {
              const syncingText = pollTicks >= 20
                ? `${labels.continuing} ${document.documentElement.lang.toLowerCase().startsWith('zh') ? '鍥炲宸茬敓鎴愶紝姝ｅ湪鍚屾鍒板綋鍓嶅伐浣滃彴鈥? : 'The reply is still syncing into this workspace...'}`
                : labels.continuing;
              setStatus('ok', syncingText);
              ensurePendingVisual();
              return;
            }
            window.clearInterval(polling);
            polling = null;
            renderMessages(feed, payload.messages, layout, labels, true);
            scrollFeedToBottom();
            if (payload.latest_turn && payload.latest_turn.role === 'assistant') {
              animateAssistant(feed, payload.latest_turn);
            }
            setStatus('ok', '');
            setBusy(false);
            if (refreshWorkspaceWhenRunStarts(payload)) {
              return;
            }
          }
        } catch (error) {
          pollErrorCount += 1;
          if (pollErrorCount <= 8) {
            setStatus('ok', `${labels.continuing} ${document.documentElement.lang.toLowerCase().startsWith('zh') ? '姝ｅ湪閲嶈繛瀹炴椂鐘舵€佲€? : 'Reconnecting live state...'}`);
            return;
          }
          if (pollErrorCount <= 16) {
            setStatus('ok', document.documentElement.lang.toLowerCase().startsWith('zh') ? '鐘舵€佸悓姝ュ紓甯革紝姝ｅ湪寮哄埗鍒锋柊褰撳墠宸ヤ綔鍙扳€? : 'State sync is unstable. Refreshing the workspace...');
            forceRefreshToSession();
            return;
          }
          window.clearInterval(polling);
          polling = null;
          setStatus('error', error);
          setBusy(false);
        }
      }, 900);
    }

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const reply = textarea ? String(textarea.value || '').trim() : '';
      if (!reply) {
        setStatus('error', 'Reply cannot be empty');
        return;
      }
      const payload = new FormData(form);
      setStatus('ok', '');
      setBusy(true);
      const submitStartedAt = Date.now();
      feed.querySelector('[data-pending-row="1"]')?.remove();
      feed.insertAdjacentHTML('beforeend', renderUserMessage({ role: 'user', content: reply }, layout, labels));
      if (feed.lastElementChild) feed.lastElementChild.setAttribute('data-optimistic-user', '1');
      appendPending(feed, layout, labels);
      setStatus('ok', labels.continuing);
      scrollFeedToBottom();
      if (textarea) textarea.value = '';
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: payload,
          headers: {
            'X-Requested-With': 'fetch',
            Accept: 'application/json',
          },
        });
        const data = await readPayload(response);
        if (!response.ok || !data.ok) {
          throw new Error(normalizeError(data, 'Submit failed'));
        }
        updateSummary(root, data);
        if (data.reply_pending) {
          setStatus('ok', labels.continuing);
          ensurePendingVisual();
          startPolling({ forceUntilAssistant: true, maxTicks: 30 });
        } else {
          const elapsed = Date.now() - submitStartedAt;
          const remainingPending = Math.max(0, MIN_PENDING_MS - elapsed);
          if (remainingPending > 0) {
            await sleep(remainingPending);
          }
          if (refreshWorkspaceWhenRunStarts(data)) {
            return;
          }
          renderMessages(feed, data.messages, layout, labels, true);
          scrollFeedToBottom();
          animateAssistant(feed, data.latest_turn);
          setStatus('ok', labels.continuing);
          window.setTimeout(function () {
            setStatus('ok', '');
          }, POST_SUCCESS_STATUS_MS);
          setBusy(false);
        }
      } catch (error) {
        feed.querySelector('[data-pending-row="1"]')?.remove();
        feed.querySelector('[data-optimistic-user="1"]')?.remove();
        setStatus('error', error);
        setBusy(false);
      }
    });

    if (root.dataset.replyPending === 'true') {
      setBusy(true);
      setStatus('ok', labels.continuing);
      ensurePendingVisual();
      startPolling({ forceUntilAssistant: true, maxTicks: 30 });
    } else if (latestVisibleMessageIsUser()) {
      setStatus('ok', labels.continuing);
      ensurePendingVisual();
      startPolling({ forceUntilAssistant: true, maxTicks: 30 });
    }

    // Auto-resize textarea
    if (textarea) {
      textarea.addEventListener('input', function () {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 260) + 'px';
      });
    }

    // Ctrl+Enter / Cmd+Enter to submit
    if (textarea) {
      textarea.addEventListener('keydown', function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
          event.preventDefault();
          form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }
      });
    }
  }

  window.initIdeaCopilotLive = init;

  function autoInit() {
    document.querySelectorAll('[data-idea-copilot-root]').forEach(init);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoInit, { once: true });
  } else {
    autoInit();
  }
})();

