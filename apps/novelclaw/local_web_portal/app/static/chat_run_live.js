(function () {
  const appPath = (path) => (typeof window.__appPath === "function" ? window.__appPath(path) : path);
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function parseKv(detail) {
    const data = {};
    const text = String(detail || "");
    const parts = [];
    let chunk = "";
    let depth = 0;
    let quote = "";
    for (let i = 0; i < text.length; i += 1) {
      const ch = text[i];
      if (quote) {
        chunk += ch;
        if (ch === quote && text[i - 1] !== "\\") quote = "";
        continue;
      }
      if (ch === '"' || ch === "'") {
        quote = ch;
        chunk += ch;
        continue;
      }
      if (ch === "{" || ch === "[" || ch === "(") depth += 1;
      if (ch === "}" || ch === "]" || ch === ")") depth = Math.max(0, depth - 1);
      if (ch === "," && depth === 0) {
        if (chunk.trim()) parts.push(chunk.trim());
        chunk = "";
        continue;
      }
      chunk += ch;
    }
    if (chunk.trim()) parts.push(chunk.trim());
    parts.forEach((part) => {
      const idx = part.indexOf("=");
      if (idx > 0) data[part.slice(0, idx).trim()] = part.slice(idx + 1).trim();
    });
    return data;
  }

  function formatBlock(value, emptyText) {
    const raw = String(value || "").trim();
    if (!raw) return emptyText || "";
    if ((raw.startsWith("{") && raw.endsWith("}")) || (raw.startsWith("[") && raw.endsWith("]"))) {
      try { return JSON.stringify(JSON.parse(raw), null, 2); } catch (_) {}
    }
    return raw;
  }

  function parseTraceEntries(progressText) {
    return String(progressText || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && line.startsWith("[event]"))
      .map((line) => {
        const parts = line.split("|").map((part) => part.trim());
        return { stamp: String(parts[0] || "").replace("[event]", "").trim(), eventName: parts[1] || "", detail: parts.slice(2).join(" | ") };
      });
  }

  const isZh = String(document.documentElement.lang || "").toLowerCase().startsWith("zh");
  const l = (zh, en) => (isZh ? zh : en);
  const toolLabel = (slug) => ({
    inspect_workspace: l("检查工作区", "inspect_workspace"),
    plot_strategy: l("规划剧情", "plot_strategy"),
    retrieve_context: l("检索上下文", "retrieve_context"),
    enrich_character: l("补强角色", "enrich_character"),
    enrich_world: l("补强世界观", "enrich_world"),
    draft_chapter: l("起草章节", "draft_chapter"),
    rewrite_chapter: l("重写章节", "rewrite_chapter"),
    sync_storyboard: l("同步故事板", "sync_storyboard"),
    sync_characters: l("同步角色", "sync_characters"),
    sync_world: l("同步世界观", "sync_world"),
    ask_user: l("向你提问", "ask_user"),
    finalize: l("完成定稿", "finalize"),
  }[slug] || slug || l("工具", "tool"));
  const TOOL_META = {
    inspect_workspace: { icon: "WS", label: toolLabel("inspect_workspace") },
    plot_strategy: { icon: "PL", label: toolLabel("plot_strategy") },
    retrieve_context: { icon: "CTX", label: toolLabel("retrieve_context") },
    enrich_character: { icon: "CHR", label: toolLabel("enrich_character") },
    enrich_world: { icon: "WRLD", label: toolLabel("enrich_world") },
    draft_chapter: { icon: "DR", label: toolLabel("draft_chapter") },
    rewrite_chapter: { icon: "RW", label: toolLabel("rewrite_chapter") },
    sync_storyboard: { icon: "SB", label: toolLabel("sync_storyboard") },
    sync_characters: { icon: "CH", label: toolLabel("sync_characters") },
    sync_world: { icon: "WD", label: toolLabel("sync_world") },
    ask_user: { icon: "ASK", label: toolLabel("ask_user") },
    finalize: { icon: "OK", label: toolLabel("finalize") },
  };

  const CHECKPOINT_CHIPS = [
    l("按当前方向继续", "Continue as-is"),
    l("下一章加强张力", "Raise tension next chapter"),
    l("放慢节奏补细节", "Slow down for detail"),
    l("更聚焦角色", "Focus more on character"),
    l("增加世界质感", "Add more world texture"),
  ];
  const CHECKPOINT_MEMORY_BANKS = [
    { slug: "chapter_briefs", label: l("章节简报", "Chapter briefs") },
    { slug: "scene_cards", label: l("场景卡", "Scene cards") },
    { slug: "entity_state", label: l("实体状态", "Entity state") },
    { slug: "relationship_state", label: l("关系状态", "Relationship state") },
    { slug: "world_state", label: l("世界状态", "World state") },
    { slug: "continuity_facts", label: l("连续性事实", "Continuity facts") },
    { slug: "revision_notes", label: l("修订笔记", "Revision notes") },
    { slug: "working_set", label: l("工作记忆", "Working set") },
  ];

  function toolMeta(name) {
    return TOOL_META[name] || { icon: "TL", label: toolLabel(name) };
  }

  function buildDisplayItems(entries) {
    const items = [];
    for (const entry of entries) {
      const kv = parseKv(entry.detail);
      const name = entry.eventName;
      if (name === "claw_loop_start" || name === "claw_native_loop") {
        items.push({ type: "banner", id: `loop-${entry.stamp}`, title: l("Claw 循环已启动", "Claw loop started"), body: `max_steps=${kv.max_steps || "-"}${kv.enabled_actions ? ` | ${l("可用工具", "tools")}=${kv.enabled_actions}` : ""}` });
        continue;
      }
      if (name === "claw_decision" || name === "claw_action_start") {
        items.push({ type: "tool-card", id: `tool-${entry.stamp}-${kv.action || name}`, action: kv.action || name, step: kv.step || "-", status: "running", params: formatBlock(kv.params || kv.reason || kv.channel || "", ""), result: "" });
        continue;
      }
      if (name === "claw_action_result") {
        const action = kv.action || "";
        let card = null;
        for (let i = items.length - 1; i >= 0; i -= 1) {
          if (items[i].type === "tool-card" && items[i].action === action && items[i].status === "running") { card = items[i]; break; }
        }
        if (!card) {
          card = { type: "tool-card", id: `tool-result-${entry.stamp}`, action, step: kv.step || "-", status: "running", params: "", result: "" };
          items.push(card);
        }
        card.status = "complete";
        card.result = formatBlock(kv.excerpt || entry.detail || "", "");
        continue;
      }
      if (name === "claw_write_result" || name === "claw_candidate_update") {
        for (let i = items.length - 1; i >= 0; i -= 1) {
          if (items[i].type === "tool-card" && items[i].status === "running") {
            items[i].status = "complete";
            items[i].result = `${l("长度", "length")}=${kv.length || "-"} ${l("字", "chars")}${kv.issues && kv.issues !== "0" ? ` | ${l("问题", "issues")}=${kv.issues}` : ""}`;
            break;
          }
        }
        continue;
      }
      if (name === "claw_quality_ok") { items.push({ type: "banner", id: `quality-${entry.stamp}`, title: l("质量检查通过", "Quality check passed"), body: `${l("步骤", "step")}=${kv.step || "-"}` }); continue; }
      if (name === "claw_ask_user") { items.push({ type: "tool-card", id: `ask-${entry.stamp}`, action: "ask_user", step: kv.step || "-", status: "ask", params: formatBlock(kv.question || entry.detail || "", ""), result: "" }); continue; }
      if (name === "claw_user_reply") {
        for (let i = items.length - 1; i >= 0; i -= 1) {
          if (items[i].type === "tool-card" && items[i].action === "ask_user") { items[i].status = "complete"; items[i].result = `${l("回复", "reply")}=${kv.answer || entry.detail || ""}`; break; }
        }
        continue;
      }
      if (name === "claw_user_interrupt") { items.push({ type: "interrupt", id: `interrupt-${entry.stamp}`, title: l("你在中途插话", "You (mid-run)"), body: kv.message || entry.detail || "" }); continue; }
      if (name === "claw_chapter_checkpoint") { items.push({ type: "banner", id: `checkpoint-${entry.stamp}`, title: isZh ? `第 ${kv.chapter || "?"} 章已完成` : `Chapter ${kv.chapter || "?"} finished`, body: `${l("计划总章数", "planned_total")}=${kv.planned_total || "-"} | ${l("字数", "chars")}=${kv.chars || "-"}` }); continue; }
      if (name === "claw_user_chapter_instruction") { items.push({ type: "banner", id: `chapter-note-${entry.stamp}`, title: isZh ? `已记录第 ${kv.chapter || "?"} 章要求` : `Instruction recorded for chapter ${kv.chapter || "?"}`, body: kv.instruction || entry.detail || "" }); continue; }
      if (name === "claw_user_memory_update") { items.push({ type: "banner", id: `memory-${entry.stamp}`, title: isZh ? `第 ${kv.chapter || "?"} 章后已更新记忆` : `Memory updated after chapter ${kv.chapter || "?"}`, body: kv.banks || entry.detail || "" }); continue; }
      if (name === "claw_finalize_ready" || name === "claw_loop_complete") { items.push({ type: "banner", id: `complete-${entry.stamp}`, title: l("Claw 循环完成", "Claw loop complete"), body: kv.reason || entry.detail || "" }); continue; }
      if (name === "global_outline" || name === "chapter_outline_ready" || name === "chapter_plan") items.push({ type: "banner", id: `status-${entry.stamp}`, title: name, body: entry.detail || "" });
    }
    return items;
  }

  function renderAssistantRow(title, bodyHtml, bodyClass) {
    return `<div class="chat-row assistant"><div class="avatar-circle">WC</div><div class="assistant-panel"><div class="assistant-section"><div class="assistant-title">${esc(title)}</div><div class="${bodyClass || "assistant-text"}">${bodyHtml}</div></div></div></div>`;
  }

  function renderToolCard(item, isLive) {
    const meta = toolMeta(item.action);
    const toneClass = item.status === "running" ? "tc-running" : item.status === "complete" ? "tc-complete" : "tc-ask";
    const badgeClass = item.status === "running" ? "tc-badge-running" : item.status === "complete" ? "tc-badge-complete" : "tc-badge-ask";
    const badgeLabel = item.status === "running" ? l("执行中", "Running") : item.status === "complete" ? l("完成", "Done") : l("等待中", "Waiting");
    const spinnerHtml = item.status === "running" && isLive ? `<div class="tc-spinner-line"><span class="tc-spinner"></span><span>${l("正在执行", "Executing")} ${esc(meta.label)}</span></div>` : "";
    const bodyHtml = `${item.params ? `<div class="tc-section-label">${l("输入", "Input")}</div><pre class="tc-code-block">${esc(item.params)}</pre>` : ""}${item.result ? `<div class="tc-section-label">${l("结果", "Result")}</div><pre class="tc-code-block tc-code-block-result">${esc(item.result)}</pre>` : ""}`;
    return `<article class="tool-call-card ${toneClass}" data-tc-id="${esc(item.id)}"><button class="tool-call-header" type="button" data-tc-toggle="${esc(item.id)}"><span class="tool-call-icon">${esc(meta.icon)}</span><span class="tool-call-name">${esc(meta.label)}</span><span class="tool-call-meta"><span class="tool-call-step">${l("步骤", "step")} ${esc(String(item.step))}</span><span class="tc-badge ${badgeClass}">${esc(badgeLabel)}</span><span class="tc-chevron">&rsaquo;</span></span></button>${spinnerHtml}<div class="tool-call-body">${bodyHtml || `<div class="tc-empty-note">${esc(l("还没有结构化细节。", "No structured details yet."))}</div>`}</div></article>`;
  }

  function renderProgressFallback(snapshot, status, errorMessage) {
    const data = snapshot || {};
    const normalizedStatus = String(status || "").toLowerCase();
    const stalled = !!data.stalled;
    const phase = String(data.phase_label || data.phase || normalizedStatus || "running");
    const note = String(data.phase_note || "").trim();
    const chapter = Number(data.current_chapter || 0);
    const total = Number(data.planned_total || 0);
    const elapsed = Number(data.elapsed_seconds || 0);
    const idle = Number(data.idle_seconds || -1);
    const words = Number(data.total_words || 0);
    const percent = Number(data.percent || 0);
    const reason = String(data.stall_reason || errorMessage || "").trim();
    return `<div class="claw-progress-fallback${stalled ? " is-stalled" : ""}"><div class="claw-progress-fallback-head"><strong>${esc(stalled ? l("Claw 可能卡住了", "Claw may be stalled") : l("Claw 仍在处理中", "Claw is still working"))}</strong><span class="mini-badge">${esc(phase)}</span></div><div class="claw-progress-fallback-grid"><div class="claw-progress-metric"><span>${l("状态", "Status")}</span><strong>${esc(normalizedStatus || "running")}</strong></div><div class="claw-progress-metric"><span>${l("章节", "Chapter")}</span><strong>${chapter > 0 ? `${chapter}${total > 0 ? ` / ${total}` : ""}` : "-"}</strong></div><div class="claw-progress-metric"><span>${l("耗时", "Elapsed")}</span><strong>${esc(`${elapsed}s`)}</strong></div><div class="claw-progress-metric"><span>${l("字数", "Words")}</span><strong>${esc(words ? String(words) : "-")}</strong></div></div><div class="claw-progress-track"><div class="claw-progress-track-fill" style="width:${Math.max(4, Math.min(100, percent || 4))}%"></div></div><div class="claw-progress-fallback-note">${esc(note || l("工作进程还在更新状态，但暂时还没有结构化轨迹事件。", "The worker is still updating status, but no structured trace items have been emitted yet."))}</div>${idle >= 0 ? `<div class="claw-progress-fallback-meta">${l("距离上次日志空闲", "Last log idle")}: ${esc(String(idle))}s</div>` : ""}${reason ? `<div class="claw-exec-error"><strong>${stalled ? l("需要注意", "Attention needed") : l("运行提示", "Runtime note")}</strong><div class="claw-exec-error-body">${esc(reason)}</div></div>` : ""}</div>`;
  }

  function renderTimeline(items, isLive, status, errorMessage, snapshot) {
    const normalizedStatus = String(status || "").toLowerCase();
    const errorText = String(errorMessage || "").trim();
    if (!items.length && normalizedStatus === "failed") return renderAssistantRow(l("Claw 运行失败", "Claw failed"), `<div class="claw-exec-error"><strong>${esc(l("在结构化事件出现前运行就终止了。", "Run terminated before structured events arrived."))}</strong><div class="claw-exec-error-body">${esc(errorText || l("未知错误", "Unknown error"))}</div></div>`, "claw-timeline-body");
    if (!items.length) return renderAssistantRow(l("Claw 执行中", "Claw execution"), renderProgressFallback(snapshot, status, errorMessage), "claw-timeline-body");

    const hasComplete = items.some((item) => item.type === "banner" && String(item.id || "").startsWith("complete-"));
    const askCard = items.find((item) => item.type === "tool-card" && item.status === "ask");
    const runningCard = items.find((item) => item.type === "tool-card" && item.status === "running");
    let title = l("Claw 执行中", "Claw execution");
    if (normalizedStatus === "failed") title = l("Claw 运行失败", "Claw failed");
    else if (askCard) title = l("Claw 正在等待你的回复", "Claw is waiting for your answer");
    else if (hasComplete) title = l("Claw 已完成", "Claw completed");
    else if (runningCard && isLive) title = isZh ? `Claw 正在执行 ${toolLabel(runningCard.action)}` : `Claw is working on ${runningCard.action}`;

    const failureHtml = normalizedStatus === "failed" ? `<div class="claw-exec-error"><strong>${esc(l("运行异常终止。", "Run terminated unexpectedly."))}</strong><div class="claw-exec-error-body">${esc(errorText || l("未知错误", "Unknown error"))}</div></div>` : "";
    const timelineHtml = items.map((item) => {
      if (item.type === "tool-card") return renderToolCard(item, isLive);
      if (item.type === "interrupt") return `<div class="claw-user-interrupt-row"><div class="claw-user-interrupt-label">${esc(item.title)}</div><div class="claw-user-interrupt-body">${esc(item.body)}</div></div>`;
      if (String(item.id || "").startsWith("loop-")) return `<div class="claw-banner claw-banner-info"><strong>${esc(item.title)}</strong>${item.body ? `<span>${esc(item.body)}</span>` : ""}</div>`;
      if (String(item.id || "").startsWith("complete-")) return `<div class="claw-banner claw-banner-success"><strong>${esc(item.title)}</strong>${item.body ? `<span>${esc(item.body)}</span>` : ""}</div>`;
      return `<div class="claw-status-pill-row"><span class="claw-status-pill-dot"></span><div><strong>${esc(item.title)}</strong>${item.body ? `<span class="claw-status-pill-body">${esc(item.body)}</span>` : ""}</div></div>`;
    }).join("\n");
    return renderAssistantRow(title, `<div class="claw-execution-timeline">${failureHtml}${timelineHtml}</div>`, "claw-timeline-body");
  }

  function renderQuestion(question, sending) {
    return renderAssistantRow(l("Claw 正在提问", "Claw is asking"), `<div class="agent-question-card"><div class="agent-question-text">${esc(question)}</div><div class="agent-question-input-row"><textarea class="agent-question-textarea" rows="3" placeholder="${esc(l("在这里输入你的回复", "Type your answer here"))}"></textarea><button class="agent-question-submit primary-btn" type="button"${sending ? " disabled" : ""}>${esc(l("回复", "Reply"))}</button></div><div class="agent-question-status"${sending ? "" : " hidden"}>${esc(l("正在发送回复...", "Sending reply..."))}</div></div>`);
  }

  function renderCheckpoint(payload, sending, memoryDrafts) {
    const chapterNo = payload.chapter || "?";
    const plannedTotal = payload.planned_total || "?";
    const draftHtml = (memoryDrafts || []).length ? `<div class="chapter-checkpoint-memory-list">${memoryDrafts.map((item, index) => `<div class="checkpoint-memory-pill"><strong>${esc(item.label || item.bank)}</strong><span>${esc(item.content || "")}</span><button type="button" class="checkpoint-memory-remove" data-remove-memory="${index}">x</button></div>`).join("")}</div>` : `<div class="row-meta">${esc(l("还没有待加入的记忆。", "No memory additions queued yet."))}</div>`;
    const subtitle = isZh ? `第 ${String(chapterNo)} / ${String(plannedTotal)} 章。继续前进、补充要求，或先更新记忆。` : `Chapter ${String(chapterNo)} / ${String(plannedTotal)}. Continue, add notes, or update memory before the next chapter.`;
    return renderAssistantRow(isZh ? `第 ${esc(String(chapterNo))} 章完成` : `Chapter ${esc(String(chapterNo))} complete`, `<div class="chapter-checkpoint-card"><div class="chapter-checkpoint-header"><div><div class="chapter-checkpoint-title">${esc(l("章节检查点", "Chapter checkpoint"))}</div><div class="chapter-checkpoint-subtitle">${esc(subtitle)}</div></div></div><div class="chapter-checkpoint-chips">${CHECKPOINT_CHIPS.map((chip) => `<button type="button" class="checkpoint-chip" data-chip="${esc(chip)}">${esc(chip)}</button>`).join("")}</div><div class="chapter-checkpoint-input-row"><textarea class="chapter-checkpoint-textarea" rows="3" placeholder="${esc(l("给下一章补充一个可选指令", "Optional instruction for the next chapter"))}"></textarea><button class="primary-btn chapter-checkpoint-submit" type="button"${sending ? " disabled" : ""}>${esc(l("继续", "Continue"))}</button></div><div class="chapter-checkpoint-memory-box"><div class="row-meta checkpoint-memory-heading">${esc(l("继续前先补一条动态记忆", "Add dynamic memory before continuing"))}</div><div class="chapter-checkpoint-memory-row"><select class="chapter-memory-bank">${CHECKPOINT_MEMORY_BANKS.map((item) => `<option value="${esc(item.slug)}">${esc(item.label)}</option>`).join("")}</select><textarea class="chapter-memory-textarea" rows="2" placeholder="${esc(l("添加一条供后续步骤使用的记忆", "Add a memory note for future steps"))}"></textarea><button class="mini-btn primary chapter-memory-add" type="button"${sending ? " disabled" : ""}>${esc(l("加入记忆", "Add memory"))}</button></div>${draftHtml}</div><div class="chapter-checkpoint-status"${sending ? "" : " hidden"}>${esc(l("正在发送给 Claw...", "Sending to Claw..."))}</div><button type="button" class="chapter-checkpoint-skip" data-skip>${esc(l("不补充，直接继续", "Continue without notes"))}</button></div>`);
  }

  function renderInterruptBar(isVisible, sending, statusText) {
    if (!isVisible) return "";
    return `<div class="claw-interrupt-bar"><div class="claw-interrupt-copy"><strong>${esc(l("运行中插话给 Claw", "Interrupt Claw mid-run"))}</strong><span>${esc(l("你的消息会注入到下一次决策步骤里，不需要离开当前聊天页。", "Your message will be injected into the next decision step without leaving this chat page."))}</span></div><div class="claw-interrupt-input-row"><textarea class="claw-interrupt-textarea" rows="2" placeholder="${esc(l("告诉 Claw 改方向、这章后停下、收紧 brief，或改优先级", "Tell Claw to change direction, stop after this chapter, tighten the brief, or focus on a different priority"))}"></textarea><button class="primary-btn claw-interrupt-submit" type="button"${sending ? " disabled" : ""}>${esc(l("发送", "Send"))}</button></div><div class="claw-interrupt-status"${statusText ? "" : " hidden"}>${esc(statusText || "")}</div></div>`;
  }

  function init(root) {
    if (!root) return;
    const sessionId = String(root.dataset.sessionId || "");
    if (!sessionId) return;

    const workspaceRoot = root.closest("[data-idea-copilot-root]");
    const feed = workspaceRoot ? workspaceRoot.querySelector("[data-run-chat-feed]") : null;
    const chatBoard = workspaceRoot ? workspaceRoot.querySelector("[data-idea-feed]") : null;
    if (!workspaceRoot || !feed || !chatBoard || root.dataset.liveInitialized) return;
    root.dataset.liveInitialized = "true";

    let controlsHost = workspaceRoot.querySelector("[data-chat-runtime-controls]");
    if (!controlsHost) {
      controlsHost = document.createElement("div");
      controlsHost.dataset.chatRuntimeControls = "true";
      chatBoard.insertAdjacentElement("afterend", controlsHost);
    }

    let currentRunId = "";
    let currentProgressLog = "";
    let currentStatus = "idle";
    let currentErrorMessage = "";
    let currentProgressSnapshot = null;
    let currentQuestion = null;
    let currentCheckpoint = null;
    let checkpointMemoryDrafts = [];
    let questionSending = false;
    let checkpointSending = false;
    let interruptSending = false;
    let interruptStatus = "";
    let interruptDraft = "";
    let questionDraft = "";
    let checkpointDraft = "";
    let checkpointMemoryDraftText = "";
    let checkpointMemoryDraftBank = CHECKPOINT_MEMORY_BANKS[0] ? CHECKPOINT_MEMORY_BANKS[0].slug : "";
    let isLive = true;
    let stopped = false;
    let previousSignature = "";
    let previousFeedMarkup = null;
    let previousControlsMarkup = null;
    let checkpointSignature = "";
    let questionPolling = false;
    let checkpointPolling = false;
    let interruptTimer = null;

    function scrollToBottom() {
      chatBoard.scrollTop = chatBoard.scrollHeight;
    }

    function setInterruptStatus(message) {
      interruptStatus = message || "";
      if (interruptTimer) {
        window.clearTimeout(interruptTimer);
        interruptTimer = null;
      }
      if (interruptStatus) {
        interruptTimer = window.setTimeout(() => {
          interruptStatus = "";
          renderAll();
        }, 2400);
      }
    }

    function captureComposerState() {
      const active = document.activeElement;
      const interruptTextarea = controlsHost.querySelector(".claw-interrupt-textarea");
      const questionTextarea = feed.querySelector(".agent-question-textarea");
      const checkpointTextarea = feed.querySelector(".chapter-checkpoint-textarea");
      const checkpointMemoryTextarea = feed.querySelector(".chapter-memory-textarea");
      const checkpointMemorySelect = feed.querySelector(".chapter-memory-bank");

      if (interruptTextarea) interruptDraft = String(interruptTextarea.value || "");
      if (questionTextarea) questionDraft = String(questionTextarea.value || "");
      if (checkpointTextarea) checkpointDraft = String(checkpointTextarea.value || "");
      if (checkpointMemoryTextarea) checkpointMemoryDraftText = String(checkpointMemoryTextarea.value || "");
      if (checkpointMemorySelect) checkpointMemoryDraftBank = String(checkpointMemorySelect.value || checkpointMemoryDraftBank || "");

      const state = { area: "", start: 0, end: 0 };
      if (active && active.classList) {
        if (active.classList.contains("claw-interrupt-textarea")) state.area = "interrupt";
        else if (active.classList.contains("agent-question-textarea")) state.area = "question";
        else if (active.classList.contains("chapter-checkpoint-textarea")) state.area = "checkpoint";
        else if (active.classList.contains("chapter-memory-textarea")) state.area = "checkpoint-memory";
      }
      if (state.area && typeof active.selectionStart === "number") {
        state.start = active.selectionStart;
        state.end = active.selectionEnd;
      }
      return state;
    }

    function restoreComposerState(focusState) {
      const interruptTextarea = controlsHost.querySelector(".claw-interrupt-textarea");
      const questionTextarea = feed.querySelector(".agent-question-textarea");
      const checkpointTextarea = feed.querySelector(".chapter-checkpoint-textarea");
      const checkpointMemoryTextarea = feed.querySelector(".chapter-memory-textarea");
      const checkpointMemorySelect = feed.querySelector(".chapter-memory-bank");

      if (interruptTextarea) interruptTextarea.value = interruptDraft;
      if (questionTextarea) questionTextarea.value = questionDraft;
      if (checkpointTextarea) checkpointTextarea.value = checkpointDraft;
      if (checkpointMemoryTextarea) checkpointMemoryTextarea.value = checkpointMemoryDraftText;
      if (checkpointMemorySelect && checkpointMemoryDraftBank) checkpointMemorySelect.value = checkpointMemoryDraftBank;

      let target = null;
      if (focusState && focusState.area === "interrupt") target = interruptTextarea;
      if (focusState && focusState.area === "question") target = questionTextarea;
      if (focusState && focusState.area === "checkpoint") target = checkpointTextarea;
      if (focusState && focusState.area === "checkpoint-memory") target = checkpointMemoryTextarea;
      if (target) {
        target.focus();
        if (typeof target.setSelectionRange === "function") {
          const start = Math.min(focusState.start || 0, target.value.length);
          const end = Math.min(focusState.end || start, target.value.length);
          target.setSelectionRange(start, end);
        }
      }
    }

    function renderAll() {
      const followOutput = chatBoard.scrollHeight - chatBoard.clientHeight - chatBoard.scrollTop < 80;
      const focusState = captureComposerState();
      const items = buildDisplayItems(parseTraceEntries(currentProgressLog));
      const openIds = new Set();
      feed.querySelectorAll(".tool-call-card.tc-open").forEach((node) => openIds.add(node.dataset.tcId));
      const blocks = [renderTimeline(items, isLive, currentStatus, currentErrorMessage, currentProgressSnapshot)];
      if (currentQuestion) blocks.push(renderQuestion(currentQuestion, questionSending));
      if (currentCheckpoint) blocks.push(renderCheckpoint(currentCheckpoint, checkpointSending, checkpointMemoryDrafts));
      const markup = blocks.join("\n");
      if (markup !== previousFeedMarkup) { feed.innerHTML = markup; previousFeedMarkup = markup; }
      feed.querySelectorAll(".tool-call-card").forEach((node) => {
        if (openIds.has(node.dataset.tcId)) node.classList.add("tc-open");
      });
      const currentCard = feed.querySelector(".tool-call-card.tc-running, .tool-call-card.tc-ask");
      if (currentCard && !currentCard.classList.contains("tc-open")) currentCard.classList.add("tc-open");
      const controlsMarkup = renderInterruptBar(!!currentRunId && isLive && !stopped, interruptSending, interruptStatus);
      if (controlsMarkup !== previousControlsMarkup) { controlsHost.innerHTML = controlsMarkup; previousControlsMarkup = controlsMarkup; }
      controlsHost.hidden = !controlsHost.innerHTML;
      restoreComposerState(focusState);
      const signature = `${currentProgressLog.length}|${currentQuestion || ""}|${currentCheckpoint ? `${currentCheckpoint.chapter || ""}-${currentCheckpoint.ts || ""}` : ""}|${interruptStatus}`;
      if (signature !== previousSignature && followOutput && !(focusState && focusState.area)) {
        previousSignature = signature;
        scrollToBottom();
      } else {
        previousSignature = signature;
      }
    }

    async function refreshStatus(signal) {
      const response = await fetch(appPath(`/api/idea-copilot/${sessionId}/live`), { cache: "no-store", signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Failed to fetch live status");
      currentRunId = data.run_id || currentRunId;
      currentProgressLog = data.progress_log_raw || data.progress_log || "";
      currentStatus = String(data.status || "");
      currentErrorMessage = String(data.error_message || "");
      currentProgressSnapshot = data.progress_snapshot || null;
      isLive = ["queued", "running"].includes(currentStatus);
      renderAll();
    }

    async function pollQuestion(signal) {
      if (!currentRunId || questionPolling || stopped) return;
      questionPolling = true;
      try {
        const response = await fetch(appPath(`/api/runs/${currentRunId}/pending-question`), { cache: "no-store", signal });
        if (!response.ok) throw new Error("Live state unavailable");
        const data = await response.json();
        currentQuestion = data.pending && data.question ? data.question : null;
        if (!currentQuestion) questionSending = false;
        renderAll();
      } finally { questionPolling = false; }
    }

    async function pollCheckpoint(signal) {
      if (!currentRunId || checkpointPolling || stopped) return;
      checkpointPolling = true;
      try {
        const response = await fetch(appPath(`/api/runs/${currentRunId}/chapter-complete`), { cache: "no-store", signal });
        if (!response.ok) throw new Error("Live state unavailable");
        const data = await response.json();
        currentCheckpoint = data.pending ? data : null;
        if (!currentCheckpoint) {
          checkpointSending = false;
          checkpointDraft = "";
          checkpointMemoryDraftText = "";
          checkpointMemoryDrafts = [];
          checkpointSignature = "";
        } else {
          const nextSignature = `${currentCheckpoint.chapter || ""}-${currentCheckpoint.ts || ""}`;
          if (nextSignature !== checkpointSignature) {
            checkpointDraft = "";
            checkpointMemoryDraftText = "";
            checkpointMemoryDraftBank = CHECKPOINT_MEMORY_BANKS[0] ? CHECKPOINT_MEMORY_BANKS[0].slug : checkpointMemoryDraftBank;
            checkpointMemoryDrafts = [];
            checkpointSignature = nextSignature;
          }
        }
        renderAll();
      } finally { checkpointPolling = false; }
    }

    async function sendQuestionReply() {
      const textarea = feed.querySelector(".agent-question-textarea");
      const answer = textarea ? String(textarea.value || "").trim() : "";
      if (!answer || !currentRunId || questionSending) return;
      questionDraft = answer;
      questionSending = true;
      renderAll();
      try {
        const response = await fetch(appPath(`/api/runs/${currentRunId}/answer`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) });
        if (!response.ok) throw new Error("Failed to send reply");
        currentQuestion = null;
        questionDraft = "";
        questionSending = false;
        await refreshStatus();
      } catch (error) {
        questionSending = false;
        renderAll();
        window.console.error(error);
      }
    }

    async function sendCheckpointMessage(message) {
      if (!currentRunId || checkpointSending) return;
      checkpointDraft = String(message || "");
      checkpointSending = true;
      renderAll();
      try {
        const response = await fetch(appPath(`/api/runs/${currentRunId}/chapter-message`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: message || "", memory_updates: checkpointMemoryDrafts.map((item) => ({ bank: item.bank, content: item.content, source: "checkpoint_ui", kind: "between_chapter_note" })) }) });
        if (!response.ok) throw new Error("Failed to send chapter instruction");
        currentCheckpoint = null;
        checkpointDraft = "";
        checkpointMemoryDraftText = "";
        checkpointMemoryDrafts = [];
        checkpointSignature = "";
        checkpointSending = false;
        await refreshStatus();
      } catch (error) {
        checkpointSending = false;
        renderAll();
        window.console.error(error);
      }
    }

    async function sendInterruptMessage() {
      if (!currentRunId || interruptSending) return;
      const textarea = controlsHost.querySelector(".claw-interrupt-textarea");
      const message = textarea ? String(textarea.value || "").trim() : "";
      if (!message) return;
      interruptDraft = message;
      interruptSending = true;
      renderAll();
      try {
        const response = await fetch(appPath(`/api/runs/${currentRunId}/interrupt`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) });
        if (!response.ok) throw new Error("Failed to send interrupt");
        interruptDraft = "";
        interruptSending = false;
        setInterruptStatus("Interrupt sent. Claw will read it on the next decision step.");
        renderAll();
      } catch (error) {
        interruptSending = false;
        setInterruptStatus("Failed to send interrupt.");
        renderAll();
        window.console.error(error);
      }
    }

    feed.addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-tc-toggle]");
      if (toggle) {
        const card = toggle.closest(".tool-call-card");
        if (card) card.classList.toggle("tc-open");
        return;
      }
      if (event.target.closest(".agent-question-submit")) return void sendQuestionReply();
      const chip = event.target.closest("[data-chip]");
      if (chip) {
        const textarea = feed.querySelector(".chapter-checkpoint-textarea");
        if (textarea) {
          textarea.value = chip.dataset.chip || "";
          checkpointDraft = textarea.value;
          textarea.focus();
        }
        return;
      }
      if (event.target.closest(".chapter-memory-add")) {
        const select = feed.querySelector(".chapter-memory-bank");
        const textarea = feed.querySelector(".chapter-memory-textarea");
        const bank = select ? String(select.value || "").trim() : "";
        const content = textarea ? String(textarea.value || "").trim() : "";
        if (bank && content) {
          const option = CHECKPOINT_MEMORY_BANKS.find((item) => item.slug === bank);
          checkpointMemoryDrafts.push({ bank, label: option ? option.label : bank, content });
          checkpointMemoryDraftText = "";
          if (textarea) textarea.value = "";
          renderAll();
        }
        return;
      }
      const removeBtn = event.target.closest("[data-remove-memory]");
      if (removeBtn) {
        const index = Number(removeBtn.dataset.removeMemory || -1);
        if (index >= 0) {
          checkpointMemoryDrafts.splice(index, 1);
          renderAll();
        }
        return;
      }
      if (event.target.closest(".chapter-checkpoint-submit")) {
        const textarea = feed.querySelector(".chapter-checkpoint-textarea");
        return void sendCheckpointMessage(textarea ? String(textarea.value || "").trim() : "");
      }
      if (event.target.closest("[data-skip]")) sendCheckpointMessage("");
    });

    feed.addEventListener("input", (event) => {
      if (event.target.closest(".agent-question-textarea")) questionDraft = String(event.target.value || "");
      if (event.target.closest(".chapter-checkpoint-textarea")) checkpointDraft = String(event.target.value || "");
      if (event.target.closest(".chapter-memory-textarea")) checkpointMemoryDraftText = String(event.target.value || "");
      if (event.target.closest(".chapter-memory-bank")) checkpointMemoryDraftBank = String(event.target.value || checkpointMemoryDraftBank || "");
    });

    controlsHost.addEventListener("click", (event) => {
      if (event.target.closest(".claw-interrupt-submit")) sendInterruptMessage();
    });

    controlsHost.addEventListener("input", (event) => {
      if (event.target.closest(".claw-interrupt-textarea")) interruptDraft = String(event.target.value || "");
    });

    controlsHost.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && event.target.closest(".claw-interrupt-textarea")) {
        event.preventDefault();
        sendInterruptMessage();
      }
    });

    window.NovelClawLive.poll(async (signal) => {
      await refreshStatus(signal);
      if (!isLive) {
        stopped = true;
        currentQuestion = null;
        currentCheckpoint = null;
        renderAll();
        return false;
      }
      await pollQuestion(signal);
      await pollCheckpoint(signal);
      return true;
    }, { interval: 1500 });
  }

  window.initChatRunLive = init;
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-chat-run-root]").forEach(init);
  });
})();
