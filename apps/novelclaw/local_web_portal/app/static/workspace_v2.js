(function () {
  const appPath = (path) => (typeof window.__appPath === "function" ? window.__appPath(path) : path);
  const root = document.querySelector("[data-workspace-root]");
  const boot = document.getElementById("workspace-bootstrap");
  if (!root || !boot) return;
  let payload = {};
  try { payload = JSON.parse(boot.textContent || "{}"); } catch (_) { return; }
  const ui = payload.ui || {};
  const data = payload.data || {};
  const txt = (k, d) => String(ui[k] || d || "");
  const isZh = String(document.documentElement.lang || "").toLowerCase().startsWith("zh");
  const l = (zh, en) => (isZh ? zh : en);
  const esc = (v) => String(v || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const preview = (v, n) => {
    const s = String(v || "").replace(/\s+/g, " ").trim();
    return !s ? "" : (s.length <= n ? s : `${s.slice(0, Math.max(0, n - 3))}...`);
  };
  const line1 = (v) => String(v || "").split(/\r?\n/).map((x) => x.trim()).find(Boolean) || "";
  const pagesOf = (v) => {
    const s = String(v || "").trim();
    if (!s) return [""];
    const parts = s.split(/\n{2,}/).map((x) => x.trim()).filter(Boolean);
    if (!parts.length) return [s];
    const out = []; let buf = []; let len = 0;
    parts.forEach((p) => {
      if (buf.length && (len + p.length > 2100 || buf.length >= 6)) { out.push(buf.join("\n\n")); buf = [p]; len = p.length; }
      else { buf.push(p); len += p.length; }
    });
    if (buf.length) out.push(buf.join("\n\n"));
    return out;
  };

  const refs = {
    modeBtns: [...document.querySelectorAll("[data-workspace-mode-btn]")],
    modePanels: [...document.querySelectorAll("[data-workspace-panel]")],
    navLinks: [...document.querySelectorAll("[data-workspace-nav]")],
    rail: document.getElementById("chapter-rail"),
    railTitle: document.getElementById("chapter-rail-title"),
    railCount: document.getElementById("chapter-rail-count"),
    reader: document.getElementById("manuscript-reader-shell"),
    planning: document.getElementById("manuscript-planning-shell"),
    empty: document.getElementById("manuscript-empty"),
    indicator: document.getElementById("manuscript-reader-indicator"),
    chapterKicker: document.getElementById("manuscript-chapter-kicker"),
    pageKicker: document.getElementById("manuscript-page-kicker"),
    title: document.getElementById("manuscript-title"),
    body: document.getElementById("manuscript-page-body"),
    meta: document.getElementById("manuscript-footer-meta"),
    download: document.getElementById("manuscript-download-link"),
    words: document.getElementById("manuscript-word-count"),
    sideText: document.getElementById("manuscript-side-snippet"),
    sidePages: document.getElementById("manuscript-side-pages"),
    prevCh: document.getElementById("prev-chapter-btn"),
    nextCh: document.getElementById("next-chapter-btn"),
    prevPg: document.getElementById("prev-page-btn"),
    nextPg: document.getElementById("next-page-btn"),
    planKick: document.getElementById("planning-kicker"),
    planPage: document.getElementById("planning-page-kicker"),
    planSource: document.getElementById("planning-source-chip"),
    planTitle: document.getElementById("planning-title"),
    planBody: document.getElementById("planning-body"),
    briefList: document.getElementById("manuscript-brief-list"),
    outlineList: document.getElementById("manuscript-outline-list"),
    beatList: document.getElementById("manuscript-beat-list"),
    briefCount: document.getElementById("manuscript-brief-count"),
    outlineCount: document.getElementById("manuscript-outline-count"),
    beatCount: document.getElementById("manuscript-beat-count"),
    planningEmpty: document.getElementById("manuscript-planning-empty"),
    draftForm: document.getElementById("manuscript-draft-form"),
    draftContent: document.getElementById("manuscript-draft-content"),
    draftSave: document.getElementById("manuscript-draft-save"),
    outlineForm: document.getElementById("manuscript-outline-form"),
    outlineTitleInput: document.getElementById("manuscript-outline-title"),
    outlineContent: document.getElementById("manuscript-outline-content"),
    outlineSave: document.getElementById("manuscript-outline-save"),
    briefForm: document.getElementById("manuscript-brief-form"),
    briefIdInput: document.getElementById("manuscript-brief-id"),
    briefTopicInput: document.getElementById("manuscript-brief-topic"),
    briefContentInput: document.getElementById("manuscript-brief-content"),
    briefSave: document.getElementById("manuscript-brief-save"),
    manuscriptStatus: document.getElementById("manuscript-editor-status"),
    groupList: document.getElementById("memory-group-list"),
    zoneName: document.getElementById("memory-active-zone-name"),
    zoneDesc: document.getElementById("memory-active-zone-desc"),
    zoneCount: document.getElementById("memory-active-zone-count"),
    activeBankName: document.getElementById("memory-active-bank-name"),
    activeBankDesc: document.getElementById("memory-active-bank-desc"),
    activeBankCount: document.getElementById("memory-active-bank-count"),
    structureLayer: document.getElementById("memory-structure-layer"),
    latestTopic: document.getElementById("memory-latest-topic"),
    addBankNote: document.getElementById("memory-add-bank-note"),
    bankTitle: document.getElementById("memory-bank-group-title"),
    bankDesc: document.getElementById("memory-bank-group-desc"),
    bankGrid: document.getElementById("memory-bank-grid"),
    taxonomyTitle: document.getElementById("memory-taxonomy-title"),
    taxonomyDesc: document.getElementById("memory-taxonomy-desc"),
    taxonomyBankCount: document.getElementById("memory-taxonomy-bank-count"),
    detailList: document.getElementById("memory-bank-detail-list"),
    editTitle: document.getElementById("memory-editor-title"),
    editDesc: document.getElementById("memory-editor-desc"),
    editCount: document.getElementById("memory-editor-count"),
    entryList: document.getElementById("memory-entry-list"),
    addForm: document.getElementById("memory-add-form"),
    addTopic: document.getElementById("memory-add-topic"),
    addContent: document.getElementById("memory-add-content"),
    editForm: document.getElementById("memory-edit-form"),
    editId: document.getElementById("memory-edit-id"),
    editTopic: document.getElementById("memory-edit-topic"),
    editContent: document.getElementById("memory-edit-content"),
    status: document.getElementById("memory-editor-status"),
    refresh: document.getElementById("memory-refresh-btn"),
  };

  const runId = String(data.run_id || root.dataset.runId || "");
  const downloadJobId = Number(data.download_job_id || 0);
  const tactical = data.tactical_banks || {};
  const bankEntries = (name) => Array.isArray(tactical[name]) ? tactical[name] : [];
  const chapterEntries = (name, ch) => bankEntries(name).filter((x) => Number(x.chapter || x.metadata?.chapter || 0) === Number(ch || 0));
  const chapters = (Array.isArray(data.chapters) ? data.chapters : []).map((x) => {
    const c = String(x.content || "").trim();
    return { chapter: Number(x.chapter || 0), iteration: Number(x.iteration || 0), filename: String(x.filename || ""), content: c, title: line1(c) || x.filename || `${txt("chapterLabel", "Chapter")} ${x.chapter || "?"}`, preview: preview(c, 140), pages: pagesOf(c), length: c.length };
  });
  const outlines = Array.isArray(data.outlines) ? data.outlines : [];
  const globalOutlines = outlines.filter((x) => !x.chapter || x.kind === "global_outline");
  const outlineMap = new Map(outlines.filter((x) => x.chapter).map((x) => [Number(x.chapter), x]));
  const draftMap = new Map(chapters.map((x) => [x.chapter, x]));
  const nums = new Set();
  chapters.forEach((x) => nums.add(x.chapter));
  outlines.forEach((x) => { if (x.chapter) nums.add(Number(x.chapter)); });
  bankEntries("chapter_briefs").forEach((x) => { const ch = Number(x.chapter || x.metadata?.chapter || 0); if (ch > 0) nums.add(ch); });
  const rail = [...nums].filter((x) => x > 0).sort((a, b) => a - b).map((chapter) => {
    const draft = draftMap.get(chapter) || null;
    const outline = outlineMap.get(chapter) || null;
    const briefs = chapterEntries("chapter_briefs", chapter);
    const scenes = chapterEntries("scene_cards", chapter);
    return { chapter, draft, outline, briefs, scenes, title: (draft && draft.title) || (outline && outline.title) || preview(line1((briefs[0] || {}).content || ""), 52) || `${txt("chapterLabel", "Chapter")} ${chapter}` };
  });

  let groups = Array.isArray(data.memory_groups) ? data.memory_groups.slice() : [];
  const _defaultZoneSlug = root.dataset.defaultZone || "";
  const _defaultZoneIdx = _defaultZoneSlug && groups.length ? Math.max(0, groups.findIndex((g) => g.slug === _defaultZoneSlug)) : 0;
  const s = { rail: Math.max(0, rail.reduce((a, x, i) => x.draft ? i : a, 0)), page: 0, planKey: "", group: _defaultZoneIdx, bank: "", entry: "" };
  const kindCls = (k) => ({ chapter_brief: "mkind-chapter", scene_card: "mkind-scene", entity_state: "mkind-entity", relationship_state: "mkind-relation", world_state: "mkind-world", continuity_fact: "mkind-fact", revision_note: "mkind-revision", working_memory: "mkind-work", between_chapter_note: "mkind-note", manual: "mkind-manual", manual_workspace: "mkind-manual" }[String(k || "")] || "mkind-default");
  const structureLabel = (slug) => ({
    premise: txt("structurePremise", "Premise Layer"),
    author_brief: txt("structureAuthorBrief", "Author Brief Layer"),
    chapter_planning: txt("structureChapterPlanning", "Chapter Planning Layer"),
    revision_loop: txt("structureRevisionLoop", "Revision Loop Layer"),
    canon_state: txt("structureCanonState", "Canon Layer"),
    runtime: txt("structureRuntime", "Runtime Layer"),
  }[String(slug || "")] || txt("futureExpansion", "Ready for future bank expansion"));
  const normalizeMode = (m) => String(m || "").toLowerCase() === "memory" ? "memory" : "manuscript";
  const panelModes = refs.modePanels.map((p) => p.dataset.workspacePanel || "").filter(Boolean);
  const defaultMode = normalizeMode(root.dataset.workspaceDefaultMode || panelModes[0] || "manuscript");
  const modeFromHash = () => {
    const hashMode = String(window.location.hash || "").replace(/^#/, "");
    return hashMode ? normalizeMode(hashMode) : defaultMode;
  };

  const setMode = (m, options = {}) => {
    let mode = normalizeMode(m);
    if (panelModes.length && !panelModes.includes(mode)) {
      mode = panelModes[0];
    }
    refs.modeBtns.forEach((b) => b.classList.toggle("is-active", b.dataset.workspaceModeBtn === mode));
    refs.modePanels.forEach((p) => p.classList.toggle("is-active", p.dataset.workspacePanel === mode));
    refs.navLinks.forEach((link) => link.classList.toggle("is-active", link.dataset.workspaceNav === mode));
    root.dataset.workspaceMode = mode;
    if (!options.fromHash) {
      const nextHash = `#${mode}`;
      if (window.location.hash !== nextHash) history.replaceState(null, "", `${window.location.pathname}${window.location.search}${nextHash}`);
    }
  };
  const cur = () => rail.length ? rail[Math.max(0, Math.min(s.rail, rail.length - 1))] : null;
  const setStatus = (msg, err) => {
    if (!refs.status) return;
    refs.status.textContent = msg || "";
    refs.status.classList.toggle("is-error", !!err);
    refs.status.classList.toggle("is-ok", !!msg && !err);
  };
  const setManuscriptStatus = (msg, err) => {
    if (!refs.manuscriptStatus) return;
    refs.manuscriptStatus.textContent = msg || "";
    refs.manuscriptStatus.classList.toggle("is-error", !!err);
    refs.manuscriptStatus.classList.toggle("is-ok", !!msg && !err);
  };
  const planKeyOf = (kind, id, fallback) => `${String(kind || "item")}::${String(id || fallback || "")}`;
  const buildPlanningCards = () => {
    const r = cur();
    const briefCards = [];
    const outlineCards = [];
    const beatCards = [];

    bankEntries("story_premise").slice(0, 1).forEach((x, i) => {
      briefCards.push({
        key: planKeyOf("premise", x.id, `${x.timestamp || ""}-${i}`),
        kind: "premise",
        tone: "warm",
        title: l("故事前提", "Premise"),
        meta: x.timestamp || "",
        previewText: preview(x.content, 260),
        content: String(x.content || "").trim(),
        sourceLabel: l("故事前提", "Premise"),
        editable: false,
      });
    });
    bankEntries("task_briefs").slice(0, 2).forEach((x, i) => {
      briefCards.push({
        key: planKeyOf("task_brief", x.id, `${x.timestamp || ""}-${i}`),
        kind: "task_brief",
        tone: "warm",
        title: l("任务简报", "Task Brief"),
        meta: x.timestamp || "",
        previewText: preview(x.content, 220),
        content: String(x.content || "").trim(),
        sourceLabel: l("任务简报", "Task brief"),
        editable: false,
      });
    });
    bankEntries("style_guide").slice(0, 1).forEach((x, i) => {
      briefCards.push({
        key: planKeyOf("style_guide", x.id, `${x.timestamp || ""}-${i}`),
        kind: "style_guide",
        tone: "warm",
        title: l("风格指南", "Style Guide"),
        meta: x.timestamp || "",
        previewText: preview(x.content, 200),
        content: String(x.content || "").trim(),
        sourceLabel: l("风格指南", "Style guide"),
        editable: false,
      });
    });
    if (r && Array.isArray(r.briefs)) {
      r.briefs.forEach((x, i) => {
        briefCards.push({
          key: planKeyOf("brief", x.id, `${r.chapter || 0}-${i}`),
          kind: "brief",
          tone: "warm",
          title: x.topic || `${txt("chapterBrief", "Chapter Brief")} ${r.chapter || ""}`,
          meta: x.timestamp || `${txt("chapterLabel", "Chapter")} ${r.chapter || ""}`,
          previewText: preview(x.content, 250),
          content: String(x.content || "").trim(),
          sourceLabel: txt("chapterBrief", "Chapter Brief"),
          editable: true,
          chapter: Number(r.chapter || 0),
          asset: x,
        });
      });
    }

    globalOutlines.slice(0, 2).forEach((x, i) => {
      outlineCards.push({
        key: planKeyOf("outline", x.id, `global-${i}`),
        kind: "outline",
        tone: "paper",
        title: x.title || txt("globalOutline", "Global Outline"),
        meta: x.timestamp || "",
        previewText: preview(x.content, 280),
        content: String(x.content || "").trim(),
        sourceLabel: txt("globalOutline", "Global Outline"),
        editable: true,
        chapter: 0,
        asset: x,
      });
    });
    outlines.filter((x) => x.chapter).slice(0, 8).forEach((x, i) => {
      outlineCards.push({
        key: planKeyOf("outline", x.id, `${x.chapter || 0}-${i}`),
        kind: "outline",
        tone: "paper",
        title: x.title || `${txt("chapterOutline", "Chapter Outline")} ${x.chapter || ""}`,
        meta: x.chapter ? `${txt("chapterLabel", "Chapter")} ${x.chapter}` : (x.timestamp || ""),
        previewText: preview(x.content, 220),
        content: String(x.content || "").trim(),
        sourceLabel: txt("chapterOutline", "Chapter Outline"),
        editable: true,
        chapter: Number(x.chapter || 0),
        asset: x,
      });
    });

    if (r) {
      r.scenes.slice(0, 4).forEach((x, i) => {
        beatCards.push({
          key: planKeyOf("scene", x.id, `${r.chapter || 0}-${i}-${x.timestamp || ""}`),
          kind: "scene",
          tone: "cool",
          title: x.topic || `${txt("sceneCard", "Scene Card")} ${i + 1}`,
          meta: x.timestamp || `${txt("chapterLabel", "Chapter")} ${r.chapter || ""}`,
          previewText: preview(x.content, 220),
          content: String(x.content || "").trim(),
          sourceLabel: txt("sceneCard", "Scene Card"),
          editable: false,
          chapter: Number(r.chapter || 0),
          asset: x,
        });
      });
    }
    (Array.isArray(data.plot_points) ? data.plot_points : []).slice(0, 4).forEach((x, i) => {
      beatCards.push({
        key: planKeyOf("plot_point", x.id, `${x.timestamp || ""}-${i}`),
        kind: "plot_point",
        tone: "cool",
        title: x.position || l("情节点", "Plot Beat"),
        meta: x.timestamp || "",
        previewText: preview(x.content, 180),
        content: String(x.content || "").trim(),
        sourceLabel: l("情节点", "Plot beat"),
        editable: false,
        asset: x,
      });
    });

    return {
      briefCards,
      outlineCards,
      beatCards,
      all: [...briefCards, ...outlineCards, ...beatCards],
    };
  };
  const currentPlanningSelection = () => {
    if (!s.planKey) return null;
    return buildPlanningCards().all.find((item) => item.key === s.planKey) || null;
  };
  const currentOutlineAsset = () => {
    const selected = currentPlanningSelection();
    if (selected && selected.kind === "outline" && selected.asset) return selected.asset;
    const r = cur();
    if (r && r.outline) return r.outline;
    return globalOutlines[0] || null;
  };
  const currentBriefAsset = () => {
    const selected = currentPlanningSelection();
    if (selected && selected.kind === "brief" && selected.asset) return selected.asset;
    const r = cur();
    return r && Array.isArray(r.briefs) && r.briefs.length ? r.briefs[0] : null;
  };

  function renderCards() {
    const packs = buildPlanningCards();
    const renderPlanningCards = (items) => items.map((item) => {
      const active = item.key === s.planKey ? " is-active" : "";
      const editableBadge = item.editable ? `<span class="manuscript-intel-card-chip">${esc(l("可编辑", "Editable"))}</span>` : "";
      return `<button type="button" class="manuscript-intel-card ${esc(item.tone || "paper")}${active}" data-plan-key="${esc(item.key)}"><div class="manuscript-intel-card-head"><span>${esc(item.title || "")}</span>${editableBadge}</div><div class="manuscript-intel-card-meta">${esc(item.meta || item.sourceLabel || "")}</div><div class="manuscript-intel-card-body">${esc(item.previewText || "")}</div><div class="manuscript-intel-card-foot">${esc(item.editable ? l("点击查看并编辑", "Click to inspect and edit") : l("点击查看", "Click to inspect"))}</div></button>`;
    }).join("");
    if (refs.briefList) refs.briefList.innerHTML = renderPlanningCards(packs.briefCards);
    if (refs.briefCount) refs.briefCount.textContent = String(packs.briefCards.length);
    if (refs.outlineList) refs.outlineList.innerHTML = renderPlanningCards(packs.outlineCards);
    if (refs.outlineCount) refs.outlineCount.textContent = String(packs.outlineCards.length);
    if (refs.beatList) refs.beatList.innerHTML = renderPlanningCards(packs.beatCards);
    if (refs.beatCount) refs.beatCount.textContent = String(packs.beatCards.length);
    const allPlanningEmpty = !packs.briefCards.length && !packs.outlineCards.length && !packs.beatCards.length;
    if (refs.planningEmpty) refs.planningEmpty.hidden = !allPlanningEmpty;
  }

  function renderRail() {
    if (!refs.rail) return;
    if (refs.railCount) refs.railCount.textContent = String(rail.length);
    if (!rail.length) { refs.rail.innerHTML = `<div class="empty-note">${esc(txt("noChapters", "No chapter or planning content yet."))}</div>`; return; }
    const maxLen = Math.max(...rail.map((x) => (x.draft ? x.draft.length : 1)), 1);
    refs.rail.innerHTML = rail.map((x, i) => {
      const active = i === s.rail ? " is-active" : "";
      const drafted = !!x.draft;
      const status = drafted ? txt("draftReady", "Draft Ready") : txt("planningOnly", "Planning Only");
      const bar = drafted ? Math.round((x.draft.length / maxLen) * 100) : 18;
      const meta = drafted ? `${txt("iterationLabel", "Iteration")} ${x.draft.iteration} · ${x.draft.pages.length} ${txt("pageLabel", "Page")}` : `${txt("chapterOutline", "Chapter Outline")} / ${txt("sceneCard", "Scene Card")}`;
      const pv = drafted ? x.draft.preview : preview((x.outline || {}).content || (x.briefs[0] || {}).content || (x.scenes[0] || {}).content || "", 120);
      return `<button type="button" class="chapter-rail-item${active}" data-rail="${i}"><div class="chapter-rail-row-head"><span class="chapter-rail-kicker">${esc(`${txt("chapterLabel", "Chapter")} ${x.chapter}`)}</span><span class="chapter-rail-status ${drafted ? "is-drafted" : "is-planned"}">${esc(status)}</span></div><strong>${esc(x.title)}</strong><span class="chapter-rail-meta">${esc(meta)}</span><span class="chapter-rail-preview">${esc(pv)}</span><div class="chapter-rail-bar"><div class="chapter-rail-bar-fill" style="width:${bar}%"></div></div></button>`;
    }).join("");
  }

  function renderManuscriptEmptyState() {
    if (!refs.empty) return;
    const sid = new URLSearchParams(window.location.search).get('session_id');
    const sfx = sid ? `?session_id=${encodeURIComponent(sid)}` : '';
    const path = window.location.pathname;
    const isOutline = path.includes('/manuscript/outline');
    const isPlanning = path.includes('/manuscript/planning');
    const outlineUrl = appPath(`/console/manuscript/outline${sfx}`);
    const planningUrl = appPath(`/console/manuscript/planning${sfx}`);
    let hint = '';
    if (isOutline) {
      hint = `<a href="${planningUrl}" class="ws-empty-nav-link">${esc(txt("chapterBrief", "Chapter brief"))} <span>04 →</span></a>`;
    } else if (isPlanning) {
      hint = `<a href="${outlineUrl}" class="ws-empty-nav-link">${esc(txt("chapterOutline", "Chapter outline"))} <span>03 →</span></a>`;
    } else {
      hint = `<a href="${outlineUrl}" class="ws-empty-nav-link">${esc(txt("chapterOutline", "Chapter outline"))} <span>03 →</span></a><a href="${planningUrl}" class="ws-empty-nav-link">${esc(txt("chapterBrief", "Chapter brief"))} <span>04 →</span></a>`;
    }
    refs.empty.innerHTML = `<div class="ws-empty-compact"><p class="ws-empty-compact-note">${esc(txt("planningSummary", "No draft yet. Showing planning materials."))}</p><div class="ws-empty-compact-nav">${hint}</div></div>`;
  }

  function renderManuscript() {
    renderRail(); renderCards();
    const r = cur();
    const selectedPlan = currentPlanningSelection();
    if (!r) {
      renderManuscriptEmptyState();
      if (refs.empty) refs.empty.classList.remove("hidden");
      if (refs.reader) refs.reader.classList.add("hidden");
      if (refs.planning) refs.planning.classList.add("hidden");
      return;
    }
    if (refs.empty) {
      refs.empty.classList.add("hidden");
      refs.empty.innerHTML = "";
    }
    if (refs.prevCh) refs.prevCh.disabled = s.rail <= 0;
    if (refs.nextCh) refs.nextCh.disabled = s.rail >= rail.length - 1;
    if (refs.indicator) refs.indicator.textContent = `${txt("chapterLabel", "Chapter")} ${r.chapter} / ${rail.length}`;
    if (r.draft && !selectedPlan) {
      const ch = r.draft; s.page = Math.max(0, Math.min(s.page, ch.pages.length - 1));
      const page = ch.pages[s.page] || "";
      if (refs.planning) refs.planning.classList.add("hidden");
      if (refs.reader) refs.reader.classList.remove("hidden");
      if (refs.chapterKicker) refs.chapterKicker.textContent = `${txt("chapterLabel", "Chapter")} ${r.chapter}`;
      if (refs.pageKicker) refs.pageKicker.textContent = `${txt("pageLabel", "Page")} ${s.page + 1} / ${ch.pages.length}`;
      if (refs.title) refs.title.textContent = r.title;
      if (refs.body) refs.body.textContent = page || txt("emptySnippet", "No visible text on this page.");
      if (refs.meta) refs.meta.textContent = `${ch.filename} · ${txt("iterationLabel", "Iteration")} ${ch.iteration} · ${txt("charsLabel", "Chars")} ${ch.length}`;
      if (refs.words) refs.words.textContent = `${page.length} ${txt("charsLabel", "Chars")}`;
      if (refs.download) refs.download.href = downloadJobId && r.chapter ? appPath(`/jobs/${downloadJobId}/download/chapter/${r.chapter}`) : "#";
      if (refs.sideText) refs.sideText.textContent = preview(page || ch.content, 260) || txt("emptySnippet", "No visible text on this page.");
      if (refs.sidePages) refs.sidePages.textContent = `${txt("pageLabel", "Page")} ${ch.pages.length}`;
      if (refs.prevPg) refs.prevPg.disabled = s.page <= 0;
      if (refs.nextPg) refs.nextPg.disabled = s.page >= ch.pages.length - 1;
    } else {
      const plan = selectedPlan
        ? String(selectedPlan.content || selectedPlan.previewText || "").trim()
        : [r.outline ? `# ${r.outline.title || txt("chapterOutline", "Chapter Outline")}\n${r.outline.content}` : "", ...r.briefs.slice(0, 2).map((x) => `# ${txt("chapterBrief", "Chapter Brief")}\n${x.content}`), ...r.scenes.slice(0, 4).map((x, i) => `# ${txt("sceneCard", "Scene Card")} ${i + 1}\n${x.content}`), !r.outline && !r.briefs.length && globalOutlines.length ? `# ${txt("globalOutline", "Global Outline")}\n${globalOutlines[0].content || ""}` : ""].filter(Boolean).join("\n\n").trim();
      if (refs.reader) refs.reader.classList.add("hidden");
      if (refs.planning) refs.planning.classList.remove("hidden");
      if (refs.planKick) refs.planKick.textContent = selectedPlan ? (selectedPlan.sourceLabel || txt("planningOnly", "Planning Only")) : (r.outline ? txt("chapterOutline", "Chapter Outline") : txt("planningOnly", "Planning Only"));
      if (refs.planPage) refs.planPage.textContent = selectedPlan ? (selectedPlan.meta || txt("planningOnly", "Planning Only")) : txt("planningOnly", "Planning Only");
      if (refs.planSource) refs.planSource.textContent = selectedPlan ? (selectedPlan.editable ? l("可编辑", "Editable") : l("查看", "Inspect")) : (r.outline ? txt("chapterOutline", "Chapter Outline") : txt("chapterBrief", "Chapter Brief"));
      if (refs.planTitle) refs.planTitle.textContent = selectedPlan ? (selectedPlan.title || r.title) : r.title;
      if (refs.planBody) refs.planBody.textContent = plan || txt("planningSummary", "No draft yet. Showing the current chapter planning packet.");
      if (refs.sideText) refs.sideText.textContent = preview(plan, 260) || txt("planningSummary", "No draft yet. Showing the current chapter planning packet.");
      if (refs.sidePages) refs.sidePages.textContent = txt("planningOnly", "Planning Only");
      if (refs.prevPg) refs.prevPg.disabled = true;
      if (refs.nextPg) refs.nextPg.disabled = true;
    }
    renderManuscriptEditors();
  }

  function renderManuscriptEditors() {
    const r = cur();
    const draft = r && r.draft ? r.draft : null;
    const outline = currentOutlineAsset();
    const brief = currentBriefAsset();

    if (refs.draftContent) refs.draftContent.value = draft ? (draft.content || "") : "";
    if (refs.draftContent) refs.draftContent.disabled = !draft;
    if (refs.draftSave) refs.draftSave.disabled = !draft || !runId;
    if (refs.draftContent && !draft) refs.draftContent.placeholder = txt("draftEditorEmpty", "There is no chapter draft to edit yet.");

    if (refs.outlineTitleInput) refs.outlineTitleInput.value = outline ? (outline.title || "") : "";
    if (refs.outlineContent) refs.outlineContent.value = outline ? (outline.content || "") : "";
    if (refs.outlineTitleInput) refs.outlineTitleInput.disabled = !outline;
    if (refs.outlineContent) refs.outlineContent.disabled = !outline;
    if (refs.outlineSave) refs.outlineSave.disabled = !outline || !runId || !outline.id;
    if (refs.outlineContent && !outline) refs.outlineContent.placeholder = txt("outlineEditorEmpty", "There is no editable outline yet.");

    if (refs.briefIdInput) refs.briefIdInput.value = brief ? (brief.id || "") : "";
    if (refs.briefTopicInput) refs.briefTopicInput.value = brief ? (brief.topic || "") : "";
    if (refs.briefContentInput) refs.briefContentInput.value = brief ? (brief.content || "") : "";
    if (refs.briefTopicInput) refs.briefTopicInput.disabled = !brief;
    if (refs.briefContentInput) refs.briefContentInput.disabled = !brief;
    if (refs.briefSave) refs.briefSave.disabled = !brief || !runId;
    if (refs.briefContentInput && !brief) refs.briefContentInput.placeholder = txt("briefEditorEmpty", "There is no editable chapter brief yet.");
  }

  const curGroup = () => groups.length ? groups[Math.max(0, Math.min(s.group, groups.length - 1))] : null;
  const curBank = () => {
    const g = curGroup(); if (!g || !Array.isArray(g.banks) || !g.banks.length) return null;
    let b = g.banks.find((x) => x.slug === s.bank); if (!b) { b = g.banks[0]; s.bank = b.slug; } return b;
  };
  const curEntry = () => {
    const b = curBank(); if (!b || !Array.isArray(b.entries) || !b.entries.length) return null;
    let e = b.entries.find((x) => x.id === s.entry); if (!e) { e = b.entries[0]; s.entry = e.id; } return e;
    };

  function renderMemory() {
    if (refs.groupList) refs.groupList.innerHTML = !groups.length ? `<div class="empty-note">${esc(txt("noEntries", "This bank has no entries yet."))}</div>` : groups.map((g, i) => {
      const color = ["#6f4ef6", "#1570ef", "#0f9f7b", "#db7c1f", "#d14343", "#7c3aed"][i % 6];
      return `<button type="button" class="memory-group-card${i === s.group ? " is-active" : ""}" data-group="${i}"><div class="memory-group-card-inner"><div class="memory-group-dot" style="background:${color}"></div><div class="memory-group-copy"><span class="memory-group-kicker">${esc(g.name || "")}</span><strong>${esc(g.description || "")}</strong><div class="memory-group-meta"><span class="memory-group-count-pill" style="background:${color}18;color:${color};">${esc(String(g.count || 0))}</span><span>${esc(txt("memoryEntries", "entries"))}</span></div></div></div></button>`;
    }).join("");
    const g = curGroup(); const b = curBank(); const e = curEntry();
    const bankName = b ? (b.name || txt("untitledBank", "Untitled Bank")) : txt("waitingSelection", "Waiting for selection");
    const bankDesc = b ? (b.description || "") : txt("noBankSelected", "After you pick a bank, this shows its purpose and latest write.");
    const latest = b ? (b.latest_topic || b.latest_preview || "") : "";
    if (refs.zoneName) refs.zoneName.textContent = g ? (g.name || "") : txt("zoneEmpty", "No zones available yet.");
    if (refs.zoneDesc) refs.zoneDesc.textContent = g ? (g.description || "") : "";
    if (refs.zoneCount) refs.zoneCount.textContent = String((g && Array.isArray(g.banks) ? g.banks.length : 0));
    if (refs.activeBankName) refs.activeBankName.textContent = bankName;
    if (refs.activeBankDesc) refs.activeBankDesc.textContent = bankDesc;
    if (refs.activeBankCount) refs.activeBankCount.textContent = String((b && b.count) || 0);
    if (refs.structureLayer) refs.structureLayer.textContent = g ? structureLabel(g.slug) : txt("futureExpansion", "Ready for future bank expansion");
    if (refs.latestTopic) {
      refs.latestTopic.innerHTML = b
        ? `<span class="mem-zone-latest-label">${esc(txt("latestWrite", "Latest write"))}</span><span class="mem-zone-latest-text">${esc(preview(latest, 180) || txt("noRecentWrite", "No recent write yet."))}</span>`
        : `<span class="mem-zone-latest-label">${esc(txt("activeBank", "Active bank"))}</span><span class="mem-zone-latest-text">${esc(txt("noBankSelected", "Pick a bank to view details."))}</span>`;
    }
    if (refs.addBankNote) refs.addBankNote.textContent = b ? `${txt("writingIntoBank", "Writing into:")} ${bankName}` : txt("noBankSelected", "Pick a bank to view details.");
    if (refs.bankTitle) refs.bankTitle.textContent = g ? (g.name || "") : "";
    if (refs.bankDesc) refs.bankDesc.textContent = g ? (g.description || "") : "";
    if (refs.bankGrid) refs.bankGrid.innerHTML = !g || !Array.isArray(g.banks) || !g.banks.length
      ? `<div class="empty-note">${esc(txt("taxonomyEmpty", "There is no bank breakdown in this zone yet."))}</div>`
      : (g.banks || []).map((x) => `<button type="button" class="memory-bank-card${x.slug === s.bank ? " is-active" : ""}" data-bank="${esc(x.slug)}"><div class="memory-bank-card-head"><strong>${esc(x.name || txt("untitledBank", "Untitled Bank"))}</strong><span class="mini-badge">${esc(String(x.count || 0))}</span></div><div class="memory-bank-card-desc">${esc(x.description || "")}</div><div class="memory-bank-card-preview">${esc(x.latest_preview || x.latest_topic || "")}</div></button>`).join("");
    if (refs.taxonomyTitle) refs.taxonomyTitle.textContent = g ? (g.name || "") : txt("waitingZoneSelection", "Waiting for zone selection");
    if (refs.taxonomyDesc) refs.taxonomyDesc.textContent = g ? (g.description || "") : txt("taxonomyEmpty", "There is no bank breakdown in this zone yet.");
    if (refs.taxonomyBankCount) refs.taxonomyBankCount.textContent = String((g && Array.isArray(g.banks) ? g.banks.length : 0));
    if (refs.detailList) refs.detailList.innerHTML = !g || !Array.isArray(g.banks) || !g.banks.length
      ? `<div class="empty-note">${esc(txt("taxonomyEmpty", "There is no bank breakdown in this zone yet."))}</div>`
      : g.banks.map((x) => {
        const active = x.slug === s.bank ? " is-active" : "";
        const latest = x.latest_topic || x.latest_preview || x.description || "-";
        return `<button type="button" class="memory-bank-detail-card${active}" data-bank="${esc(x.slug)}"><div class="memory-bank-detail-head"><strong>${esc(x.name || txt("untitledBank", "Untitled Bank"))}</strong><span class="mini-badge">${esc(String(x.count || 0))}</span></div><div class="memory-bank-detail-body">${esc(x.description || "")}</div><div class="memory-bank-detail-meta"><span>${esc(structureLabel(g.slug))}</span><span>${esc(txt("latestWrite", "Latest write"))}: ${esc(preview(latest, 84) || "-")}</span></div></button>`;
      }).join("");
    if (refs.editTitle) refs.editTitle.textContent = b ? (b.name || txt("untitledBank", "Untitled Bank")) : "";
    if (refs.editDesc) refs.editDesc.textContent = b ? (b.description || "") : "";
    if (refs.editCount) refs.editCount.textContent = String((b && b.count) || 0);
    if (refs.entryList) refs.entryList.innerHTML = !b || !Array.isArray(b.entries) || !b.entries.length
      ? `<div class="mem-zone-empty-state"><div class="mem-zone-empty-kicker">${esc(bankName)}</div><strong>${esc(txt("emptyBankTitle", "This bank has no entries yet."))}</strong><p>${esc(txt("emptyBankHint", "Add a short note, status update, or fact on the right to start building this bank."))}</p></div>`
      : b.entries.map((x) => `<button type="button" class="memory-entry-card${x.id === s.entry ? " is-active" : ""}" data-entry="${esc(x.id)}"><div class="memory-entry-card-head"><strong>${esc(x.topic || txt("topicPlaceholder", "Entry topic"))}</strong><span class="row-meta">${esc(x.timestamp || "")}</span></div><div class="memory-entry-card-preview">${esc(preview(x.content || "", 150))}</div><div class="memory-entry-card-meta">${x.chapter !== null && x.chapter !== undefined ? `<span class="memory-entry-chip">${esc(`Ch ${x.chapter}`)}</span>` : ""}${x.kind ? `<span class="memory-kind-badge ${kindCls(x.kind)}">${esc(x.kind)}</span>` : ""}${x.source ? `<span class="memory-entry-chip">${esc(x.source)}</span>` : ""}</div></button>`).join("");
    if (refs.editId) refs.editId.value = e ? (e.id || "") : "";
    if (refs.editTopic) refs.editTopic.value = e ? (e.topic || "") : "";
    if (refs.editContent) refs.editContent.value = e ? (e.content || "") : "";
  }

  async function refreshGroups() {
    if (!runId) return;
    try { const r = await fetch(appPath(`/api/runs/${runId}/memory-banks`), { cache: "no-store" }); if (!r.ok) throw new Error(); const j = await r.json(); groups = Array.isArray(j.groups) ? j.groups : []; renderMemory(); setStatus(txt("refreshed", "Memory refreshed."), false); } catch (_) { setStatus(txt("refreshFailed", "Refresh failed. Try again shortly."), true); }
  }
  async function addEntry() {
    const b = curBank(); const content = String(refs.addContent ? refs.addContent.value : "").trim(); const topic = String(refs.addTopic ? refs.addTopic.value : "").trim();
    if (!runId || !b || !content) { setStatus(txt("addFailed", "Enter content before saving."), true); return; }
    setStatus(txt("saving", "Saving..."), false);
    try { const r = await fetch(appPath(`/api/runs/${runId}/memory-banks/${b.slug}/entries`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topic, content, source: "manual_workspace" }) }); if (!r.ok) throw new Error(); const j = await r.json(); groups = Array.isArray(j.groups) ? j.groups : groups; s.bank = b.slug; s.entry = j.entry && j.entry.id ? j.entry.id : ""; if (refs.addContent) refs.addContent.value = ""; renderMemory(); setStatus(txt("saved", "Saved."), false); } catch (_) { setStatus(txt("saveFailed", "Save failed. Try again shortly."), true); }
  }
  async function saveEntry() {
    const b = curBank(); const id = String(refs.editId ? refs.editId.value : "").trim(); const topic = String(refs.editTopic ? refs.editTopic.value : "").trim(); const content = String(refs.editContent ? refs.editContent.value : "").trim();
    if (!runId || !b || !id) { setStatus(txt("selectEntry", "Pick a recent entry first, then save edits."), true); return; }
    if (!content) { setStatus(txt("addFailed", "Enter content before saving."), true); return; }
    setStatus(txt("saving", "Saving..."), false);
    try { const r = await fetch(appPath(`/api/runs/${runId}/memory-banks/${b.slug}/entries/${id}`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topic, content, source: "manual_workspace" }) }); if (!r.ok) throw new Error(); const j = await r.json(); groups = Array.isArray(j.groups) ? j.groups : groups; s.bank = b.slug; s.entry = j.entry && j.entry.id ? j.entry.id : id; renderMemory(); setStatus(txt("saved", "Saved."), false); } catch (_) { setStatus(txt("saveFailed", "Save failed. Try again shortly."), true); }
  }

  let draftSaving = false;
  async function saveDraft() {
    if (draftSaving) return;
    const r = cur();
    const draft = r && r.draft ? r.draft : null;
    const content = String(refs.draftContent ? refs.draftContent.value : "");
    if (!runId || !draft || !content.trim()) { setManuscriptStatus(txt("draftEditorEmpty", "There is no chapter draft to edit yet."), true); return; }
    setManuscriptStatus(txt("saving", "Saving..."), false);
    draftSaving = true;
    try {
      const resp = await fetch(appPath(`/api/runs/${runId}/chapters/${draft.chapter}/content`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, base_content: draft.content }),
      });
      const j = await resp.json();
      if (!resp.ok) throw new Error(j.detail || txt("saveFailed", "Save failed. Try again shortly."));
      const updated = j.chapter || {};
      draft.content = String(updated.content || "").trim();
      draft.title = String(updated.title || line1(draft.content) || draft.filename || draft.title || "");
      draft.preview = preview(draft.content, 140);
      draft.pages = pagesOf(draft.content);
      draft.length = draft.content.length;
      if (cur()?.draft === draft && refs.draftContent?.value === content) renderManuscript();
      setManuscriptStatus(txt("draftSaved", "Chapter draft saved."), false);
    } catch (error) {
      setManuscriptStatus(error.message || txt("saveFailed", "Save failed. Try again shortly."), true);
    } finally { draftSaving = false; }
  }

  async function saveOutline() {
    const outline = currentOutlineAsset();
    const title = String(refs.outlineTitleInput ? refs.outlineTitleInput.value : "").trim();
    const content = String(refs.outlineContent ? refs.outlineContent.value : "");
    if (!runId || !outline || !outline.id || !content.trim()) { setManuscriptStatus(txt("outlineEditorEmpty", "There is no editable outline yet."), true); return; }
    setManuscriptStatus(txt("saving", "Saving..."), false);
    try {
      const resp = await fetch(appPath(`/api/runs/${runId}/outlines/${outline.id}`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, content }),
      });
      if (!resp.ok) throw new Error();
      const j = await resp.json();
      const updated = j.outline || {};
      outline.title = String(updated.title || title || outline.title || "");
      outline.content = String(updated.content || "").trim();
      outline.timestamp = String(updated.timestamp || outline.timestamp || "");
      renderManuscript();
      setManuscriptStatus(txt("outlineSaved", "Outline saved."), false);
    } catch (_) {
      setManuscriptStatus(txt("saveFailed", "Save failed. Try again shortly."), true);
    }
  }

  async function saveBrief() {
    const brief = currentBriefAsset();
    const topic = String(refs.briefTopicInput ? refs.briefTopicInput.value : "").trim();
    const content = String(refs.briefContentInput ? refs.briefContentInput.value : "");
    if (!runId || !brief || !brief.id || !content.trim()) { setManuscriptStatus(txt("briefEditorEmpty", "There is no editable chapter brief yet."), true); return; }
    setManuscriptStatus(txt("saving", "Saving..."), false);
    try {
      const resp = await fetch(appPath(`/api/runs/${runId}/memory-banks/chapter_briefs/entries/${brief.id}`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, content, source: "manual_workspace" }),
      });
      if (!resp.ok) throw new Error();
      const j = await resp.json();
      const entry = j.entry || {};
      brief.topic = String(entry.topic || topic || "");
      brief.content = String(entry.content || "").trim();
      brief.timestamp = String(entry.timestamp || brief.timestamp || "");
      groups = Array.isArray(j.groups) ? j.groups : groups;
      renderManuscript();
      renderMemory();
      setManuscriptStatus(txt("briefSaved", "Chapter brief saved."), false);
    } catch (_) {
      setManuscriptStatus(txt("saveFailed", "Save failed. Try again shortly."), true);
    }
  }

  refs.modeBtns.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.workspaceModeBtn || "manuscript")));
  window.addEventListener("hashchange", () => setMode(modeFromHash(), { fromHash: true }));
  if (refs.rail) refs.rail.addEventListener("click", (e) => { const t = e.target.closest("[data-rail]"); if (!t) return; s.rail = Number(t.dataset.rail || 0); s.page = 0; s.planKey = ""; renderManuscript(); });
  if (refs.prevCh) refs.prevCh.addEventListener("click", () => { s.rail -= 1; s.page = 0; s.planKey = ""; renderManuscript(); });
  if (refs.nextCh) refs.nextCh.addEventListener("click", () => { s.rail += 1; s.page = 0; s.planKey = ""; renderManuscript(); });
  if (refs.prevPg) refs.prevPg.addEventListener("click", () => { s.page -= 1; renderManuscript(); });
  if (refs.nextPg) refs.nextPg.addEventListener("click", () => { s.page += 1; renderManuscript(); });
  document.addEventListener("keydown", (e) => {
    if (!document.querySelector('[data-workspace-panel="manuscript"].is-active')) return;
    if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
    const r = cur(); if (!r) return;
    if (e.key === "ArrowLeft") { if (r.draft && s.page > 0) s.page -= 1; else { s.rail = Math.max(0, s.rail - 1); s.page = 0; s.planKey = ""; } renderManuscript(); }
    if (e.key === "ArrowRight") { if (r.draft && s.page < r.draft.pages.length - 1) s.page += 1; else { s.rail = Math.min(rail.length - 1, s.rail + 1); s.page = 0; s.planKey = ""; } renderManuscript(); }
  });
  if (refs.groupList) refs.groupList.addEventListener("click", (e) => { const t = e.target.closest("[data-group]"); if (!t) return; s.group = Number(t.dataset.group || 0); s.bank = ""; s.entry = ""; renderMemory(); });
  if (refs.bankGrid) refs.bankGrid.addEventListener("click", (e) => { const t = e.target.closest("[data-bank]"); if (!t) return; s.bank = t.dataset.bank || ""; s.entry = ""; renderMemory(); });
  if (refs.detailList) refs.detailList.addEventListener("click", (e) => { const t = e.target.closest("[data-bank]"); if (!t) return; s.bank = t.dataset.bank || ""; s.entry = ""; renderMemory(); });
  if (refs.entryList) refs.entryList.addEventListener("click", (e) => { const t = e.target.closest("[data-entry]"); if (!t) return; s.entry = t.dataset.entry || ""; renderMemory(); });
  if (refs.addForm) refs.addForm.addEventListener("submit", (e) => { e.preventDefault(); addEntry(); });
  if (refs.editForm) refs.editForm.addEventListener("submit", (e) => { e.preventDefault(); saveEntry(); });
  if (refs.draftForm) refs.draftForm.addEventListener("submit", (e) => { e.preventDefault(); saveDraft(); });
  if (refs.outlineForm) refs.outlineForm.addEventListener("submit", (e) => { e.preventDefault(); saveOutline(); });
  if (refs.briefForm) refs.briefForm.addEventListener("submit", (e) => { e.preventDefault(); saveBrief(); });
  if (refs.refresh) refs.refresh.addEventListener("click", refreshGroups);
  const onPlanCardClick = (e) => {
    const t = e.target.closest("[data-plan-key]");
    if (!t) return;
    const nextKey = String(t.dataset.planKey || "");
    s.planKey = s.planKey === nextKey ? "" : nextKey;
    renderManuscript();
  };
  if (refs.briefList) refs.briefList.addEventListener("click", onPlanCardClick);
  if (refs.outlineList) refs.outlineList.addEventListener("click", onPlanCardClick);
  if (refs.beatList) refs.beatList.addEventListener("click", onPlanCardClick);

  setMode(modeFromHash(), { fromHash: true });
  renderManuscript();
  renderMemory();
})();
