const state = {
  data: null,
  report: "all",
  decisionFilter: "all",
  severities: new Set(["critical", "high", "medium", "low", "info", "user"]),
  search: "",
  selectedId: null,
  selectedIds: new Set(),
  designSnapshot: null,
  designFileCache: {},
  designFingerprints: null,
  designChanges: {},
  designDeleted: [],
  expandedWorkflowDirs: new Set(),
  mode: "review",
  planningView: "file:wfgen/requirements_manifest.yaml",
  planningRequest: 0,
  planningSearch: "",
  planningPresentation: "parsed",
  designDrafts: {},
  designValidationErrors: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function iconRefresh() {
  if (window.lucide) window.lucide.createIcons();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) throw new Error(payload.error || "请求失败");
  return payload.result;
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast visible${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.className = "toast", 3000);
}

function decisionLabel(decision) {
  return {approved: "已批准", rejected: "已拒绝", deferred: "已暂缓"}[decision] || decision;
}

function defaultDecisionReason(item, decision) {
  const subject = item.component ? `组件“${item.component}”` : `问题“${item.title}”`;
  const report = reportLabel(item.source_report);
  if (decision === "rejected") {
    return `已审阅${subject}的描述与证据，当前不接受该评估建议。现有证据不足以证明问题会造成所述影响，或该行为属于预期设计；本决定仅拒绝当前结论，后续如补充可复现证据，应重新提交评估。`;
  }
  if (decision === "deferred") {
    return `已审阅${subject}的描述与证据，暂缓作出最终处理决定。需要补充需求依据、影响范围或复现结果后再次评审；在重新批准前，不应由增量工作流自动实施相关修改。`;
  }
  return `已审阅${subject}的描述、影响与证据，同意按报告中的修复建议处理。修改范围应限制在该问题涉及的内容，完成后必须重新运行${report}评估，确认问题已解决且没有引入新的回归。`;
}

function reportLabel(report) {
  return {tools: "工具", checkers: "Checker", flow: "流程", env: "环境", run: "运行", user: "用户", repairs: "版本", incremental: "增量"}[report] || report;
}

function entryKindLabel(kind) {
  return {issue: "问题说明", suggestion: "改进建议", context: "补充信息"}[kind] || "用户条目";
}

function integrityLabel(status) {
  return {verified: "哈希匹配", drifted: "内容漂移", missing: "目标缺失", superseded: "已被替代"}[status] || status;
}

function historyStatusLabel(status) {
  return {
    available: "可恢复",
    deleted: "已删除",
    missing: "备份缺失",
    corrupt: "备份损坏",
    none: "没有旧版本",
  }[status] || status;
}

function repairItems() {
  if (!state.data) return [];
  const severity = {missing: "critical", drifted: "critical", superseded: "medium", verified: "low"};
  return state.data.repairs.map(item => ({
    ...item,
    review_id: item.repair_id,
    source_kind: "repair",
    source_report: "repairs",
    severity: severity[item.integrity] || "medium",
    title: item.target,
    description: item.rationale,
    decision: null,
  }));
}

function matchesDecisionFilter(item) {
  if (item.source_kind === "repair") return true;
  const decision = item.decision?.decision;
  if (state.decisionFilter === "all") return true;
  if (state.decisionFilter === "unapproved") return !decision;
  if (state.decisionFilter === "decided") return Boolean(decision);
  return decision === state.decisionFilter;
}

function filteredItems() {
  if (!state.data) return [];
  const query = state.search.trim().toLowerCase();
  const source = state.report === "repairs" ? repairItems() : state.data.items;
  return source
    .filter(item => state.report === "all" || item.source_report === state.report)
    .filter(item => state.severities.has(item.severity))
    .filter(matchesDecisionFilter)
    .filter(item => !query || [
      item.review_id, item.title, item.description, item.source_report, item.component,
      item.target, item.entry_id, item.sha256
    ].join(" ").toLowerCase().includes(query))
    .sort((a, b) => {
      if (state.report === "repairs") {
        return String(b.applied_at || "").localeCompare(String(a.applied_at || ""));
      }
      const rank = {critical: 0, high: 1, medium: 2, low: 3, info: 4, user: 5};
      return (rank[a.severity] ?? 5) - (rank[b.severity] ?? 5) || a.title.localeCompare(b.title);
    });
}

function renderSummary() {
  const totals = state.data.summary.totals || {};
  const reportStates = state.data.reports.map(r => r.latest?.status || "not_run");
  const failed = reportStates.filter(x => x === "failed").length;
  const passed = reportStates.filter(x => x === "passed").length;
  const repairs = repairItems();
  const abnormalRepairs = repairs.filter(x => ["missing", "drifted"].includes(x.integrity)).length;
  const availableHistory = repairs.filter(x => x.backup_status === "available").length;
  $("#summaryStrip").innerHTML = `
    <div class="summary-stat"><span>开放问题</span><strong>${state.data.items.length}</strong></div>
    <div class="summary-stat"><span>Critical / High</span><strong>${state.data.items.filter(x => ["critical","high"].includes(x.severity)).length}</strong></div>
    <div class="summary-stat"><span>部署版本</span><strong>${repairs.length}</strong></div>
    <div class="summary-stat"><span>可恢复版本</span><strong>${availableHistory}</strong></div>
    <div class="summary-stat"><span>部署异常</span><strong>${abnormalRepairs}</strong></div>
    <div class="summary-stat"><span>报告通过 / 失败</span><strong>${passed} / ${failed}</strong></div>
    <div class="summary-stat status"><span>汇总状态</span><strong>${totals.failed ? "需要处理" : "无高危阻塞"}</strong></div>`;
  $("#generatedAt").textContent = state.data.summary.generated_at
    ? `汇总时间 ${new Date(state.data.summary.generated_at).toLocaleString()}`
    : "尚未生成汇总";
  $("#reportStatus").innerHTML = [...state.data.reports, state.data.incremental].map(report => {
    const status = report.latest?.status || "not_run";
    const labels = {
      passed: "通过",
      passed_with_findings: "有发现",
      failed: "失败",
      blocked: "阻塞",
      skipped: "跳过",
      running: "运行中",
      no_change: "无修改",
      partial: "未完成",
      not_run: "未运行",
    };
    return `<div class="report-state">
      <strong>${escapeHtml(reportLabel(report.report_type))}</strong>
      <span title="${escapeHtml(report.latest_run_id || "无运行记录")}">
        <i class="state-dot ${escapeHtml(status)}"></i>${escapeHtml(labels[status] || status)}
      </span>
    </div>`;
  }).join("");
}

function renderCounts() {
  const items = state.data.items;
  const counts = {all: items.length, tools: 0, checkers: 0, flow: 0, env: 0, run: 0, user: 0, repairs: state.data.repairs.length};
  items.forEach(item => counts[item.source_report] = (counts[item.source_report] || 0) + 1);
  Object.entries(counts).forEach(([key, count]) => {
    const node = $(`#count${key[0].toUpperCase()}${key.slice(1)}`);
    if (node) node.textContent = count;
  });
}

function renderList() {
  const items = filteredItems();
  const list = $("#issueList");
  const versionMode = state.report === "repairs";
  $("#viewTitle").textContent = state.report === "repairs"
    ? "增量版本管理"
    : state.report === "all" ? "全部开放问题" : `${reportLabel(state.report)}问题`;
  $("#viewSubtitle").textContent = state.report === "repairs"
    ? `${items.length} 个文件版本，可检查完整性、管理旧版本或清理列表记录`
    : `${items.length} 项，按严重程度排序`;
  $("#decisionFilter").value = state.decisionFilter;
  $("#decisionFilter").closest("label").hidden = versionMode;
  $("#batchToolbar").hidden = false;
  if (!items.length) {
    list.innerHTML = `<div class="empty-state"><i data-lucide="circle-check-big"></i><h3>当前筛选无结果</h3><p>调整报告、严重程度或搜索条件。</p></div>`;
    renderDetail(null);
    renderBatchToolbar();
    iconRefresh();
    return;
  }
  list.innerHTML = items.map(item => `
    <div class="issue-row ${item.review_id === state.selectedId ? "selected" : ""}" data-id="${escapeHtml(item.review_id)}" role="listitem">
      <label class="row-select" title="选择此项">
        <input type="checkbox" data-select-id="${escapeHtml(item.review_id)}" ${state.selectedIds.has(item.review_id) ? "checked" : ""}>
      </label>
      <button class="issue-content" data-open-id="${escapeHtml(item.review_id)}">
        <span class="severity-bar ${escapeHtml(item.severity)}"></span>
        <span>
          <span class="issue-meta">
            ${item.source_kind === "repair"
              ? `${escapeHtml(integrityLabel(item.integrity))} · ${escapeHtml(item.run_id)} · ${escapeHtml(item.batch_id || "未分批")} · ${escapeHtml(item.attempt_id || item.entry_id)}`
              : `${escapeHtml(item.severity)} · ${escapeHtml(item.source_report === "user" ? entryKindLabel(item.entry_kind) : reportLabel(item.source_report))}`}
            ${item.source_kind !== "repair" && item.decision ? `<span class="decision-chip">${escapeHtml(decisionLabel(item.decision.decision))}</span>` : ""}
          </span>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.description)}</p>
        </span>
      </button>
    </div>`).join("");
  $$("[data-open-id]").forEach(node => node.addEventListener("click", () => {
    state.selectedId = node.dataset.openId;
    renderList();
  }));
  $$("[data-select-id]").forEach(node => node.addEventListener("change", () => {
    node.checked ? state.selectedIds.add(node.dataset.selectId) : state.selectedIds.delete(node.dataset.selectId);
    renderBatchToolbar();
  }));
  const selected = items.find(item => item.review_id === state.selectedId);
  renderDetail(selected || null);
  renderBatchToolbar();
}

function renderBatchToolbar() {
  const versionMode = state.report === "repairs";
  $("#batchToolbar").hidden = false;
  $("#bulkDecisionButton").hidden = versionMode;
  $("#bulkDeleteLabel").textContent = versionMode ? "批量删除版本记录" : "批量删除";
  const visibleIds = filteredItems().map(item => item.review_id);
  const selectedVisible = visibleIds.filter(id => state.selectedIds.has(id)).length;
  $("#selectedCount").textContent = `已选择 ${state.selectedIds.size} 项`;
  $("#selectVisible").checked = visibleIds.length > 0 && selectedVisible === visibleIds.length;
  $("#selectVisible").indeterminate = selectedVisible > 0 && selectedVisible < visibleIds.length;
  $("#clearSelectionButton").disabled = state.selectedIds.size === 0;
  $("#bulkDecisionButton").disabled = state.selectedIds.size === 0;
  $("#bulkDeleteButton").disabled = state.selectedIds.size === 0;
}

function evidenceHtml(evidence) {
  if (typeof evidence === "string") {
    return `<div class="evidence-item"><p>${escapeHtml(evidence)}</p></div>`;
  }
  const locator = [evidence.path, evidence.location, evidence.command].filter(Boolean).join(" · ");
  return `<div class="evidence-item">
    <code>${escapeHtml(evidence.kind || "evidence")}${locator ? ` · ${escapeHtml(locator)}` : ""}</code>
    <p>${escapeHtml(evidence.observation || evidence.detail || JSON.stringify(evidence))}</p>
  </div>`;
}

function detailFact(label, value) {
  if (value === undefined || value === null || value === "" ||
      (Array.isArray(value) && value.length === 0)) return "";
  const display = Array.isArray(value) ? value.join("\n") :
    typeof value === "object" ? JSON.stringify(value, null, 2) : value;
  return `<div class="detail-fact"><span>${escapeHtml(label)}</span><p>${escapeHtml(display)}</p></div>`;
}

function renderDetail(item) {
  const panel = $("#detailPanel");
  if (!item) {
    panel.innerHTML = `<div class="empty-state"><i data-lucide="mouse-pointer-2"></i><h3>选择一个条目</h3><p>查看问题证据或已部署修复的验收状态。</p></div>`;
    iconRefresh();
    return;
  }
  if (item.source_kind === "repair") {
    renderRepairDetail(item, panel);
    return;
  }
  const evidence = item.evidence || [];
  const decision = item.decision;
  panel.innerHTML = `
    <div class="detail-heading">
      <span class="badge ${escapeHtml(item.severity)}">${escapeHtml(item.severity)}</span>
      <h2>${escapeHtml(item.title)}</h2>
      <p>${escapeHtml(item.review_id)} · run ${escapeHtml(item.source_run_id || "user")}</p>
    </div>
    <section class="detail-section"><h3>问题描述</h3><p>${escapeHtml(item.description)}</p></section>
    ${item.source_kind === "finding" ? `<section class="detail-section">
      <h3>判断依据</h3>
      <div class="detail-facts">
        ${detailFact("组件", item.component)}
        ${detailFact("置信度", item.confidence)}
        ${detailFact("严重程度理由", item.severity_reason)}
        ${detailFact("需求引用", item.requirement_refs)}
        ${detailFact("预期行为", item.expected)}
        ${detailFact("实际行为", item.actual)}
        ${detailFact("影响", item.impact)}
        ${detailFact("建议修复", item.recommendation)}
        ${detailFact("复现方法", item.repro)}
      </div>
    </section>` : `<section class="detail-section">
      <h3>建议信息</h3>
      <div class="detail-facts">
        ${detailFact("优先级", item.priority)}
        ${detailFact("条目类型", entryKindLabel(item.entry_kind))}
        ${detailFact("创建时间", item.created_at)}
      </div>
    </section>`}
    <section class="detail-section">
      <h3>证据（${evidence.length}）</h3>
      <div class="evidence-list">${evidence.length ? evidence.map(evidenceHtml).join("") : "<p>用户建议无需评估证据。</p>"}</div>
    </section>
    ${decision ? `<section class="detail-section"><h3>当前决定</h3><p>${escapeHtml(decisionLabel(decision.decision))}：${escapeHtml(decision.reason || "")}\n${escapeHtml(decision.decided_at || "")}</p></section>` : ""}
    <div class="detail-actions">
      <button class="primary-button" id="openDecisionButton"><i data-lucide="stamp"></i>${decision ? "更新决定" : "审批"}</button>
      <button class="danger-button" id="deleteReviewItemButton"><i data-lucide="trash-2"></i>删除条目</button>
    </div>`;
  $("#openDecisionButton").addEventListener("click", () => openDecision(item));
  $("#deleteReviewItemButton").addEventListener("click", () => deleteReviewItems([item.review_id]));
  iconRefresh();
}

function renderRepairDetail(item, panel) {
  const checks = state.data.incremental.latest?.checks || [];
  panel.innerHTML = `
    <div class="detail-heading">
      <span class="badge ${escapeHtml(item.severity)}">${escapeHtml(integrityLabel(item.integrity))}</span>
      <h2>${escapeHtml(item.target)}</h2>
      <p>${escapeHtml(item.entry_id)} · ${escapeHtml(item.applied_at || "时间未知")}</p>
    </div>
    <section class="detail-section"><h3>修复内容</h3><p>${escapeHtml(item.rationale || "未提供修复说明")}</p></section>
    <section class="detail-section">
      <h3>部署证据</h3>
      <div class="detail-facts">
        ${detailFact("候选文件", item.source)}
        ${detailFact("正式文件", `${item.workflow_root}/${item.target}`)}
        ${detailFact("记录 SHA256", item.sha256)}
        ${detailFact("当前 SHA256", item.actual_sha256 || "目标不存在")}
        ${detailFact("批准来源", item.approval_ids)}
        ${detailFact("增量运行", item.run_id)}
        ${detailFact("修复批次", item.batch_id)}
        ${detailFact("尝试版本", item.attempt_id)}
        ${detailFact("部署状态", integrityLabel(item.integrity))}
        ${detailFact("记录类型", item.operation === "restore" ? "用户恢复" : "增量部署")}
        ${detailFact("替代版本", item.supersedes)}
        ${detailFact("旧版本状态", historyStatusLabel(item.backup_status))}
        ${detailFact("旧版本路径", item.backup?.path)}
        ${detailFact("旧版本 SHA256", item.backup?.sha256)}
        ${detailFact("旧版本创建时间", item.backup?.created_at)}
        ${detailFact("旧版本删除记录", item.backup?.deleted_at
          ? `${item.backup.deleted_at}\n${item.backup.delete_reason || ""}` : "")}
      </div>
    </section>
    <section class="detail-section">
      <h3>最新增量检查（${checks.length}）</h3>
      <div class="check-list">${checks.length ? checks.map(check => `
        <div class="check-row">
          <i class="state-dot ${escapeHtml(check.status)}"></i>
          <strong>${escapeHtml(check.id)}</strong>
          <span>${escapeHtml(check.summary || check.status)}</span>
        </div>`).join("") : "<p>尚无完整增量检查报告。</p>"}
      </div>
    </section>
    ${item.legacy_review || item.legacy_stale_review ? `<section class="detail-section"><h3>旧版验收元数据</h3><p>该记录保留旧系统的验收信息，仅供审计，不影响后继版本部署。</p></section>` : ""}
    <div class="detail-actions">
      ${item.backup_status === "available" ? `
        <button class="secondary-button" id="restoreHistoryButton"><i data-lucide="history"></i>恢复旧版本</button>
        <button class="danger-button" id="deleteHistoryButton"><i data-lucide="trash-2"></i>删除旧版本</button>
      ` : ""}
      <button class="danger-button" id="deleteRepairRecordButton"><i data-lucide="list-x"></i>删除版本记录</button>
    </div>`;
  $("#restoreHistoryButton")?.addEventListener("click", () => openHistoryAction(item, "restore"));
  $("#deleteHistoryButton")?.addEventListener("click", () => openHistoryAction(item, "delete"));
  $("#deleteRepairRecordButton").addEventListener("click", () => deleteRepairItems([item.repair_id]));
  iconRefresh();
}

function syncLocation() {
  const url = new URL(window.location.href);
  url.searchParams.set("tab", state.mode === "planning" ? "design" : "review");
  if (state.mode === "planning") {
    url.searchParams.delete("view");
    url.searchParams.set("design", state.planningView);
    state.planningPresentation === "source"
      ? url.searchParams.set("format", "source")
      : url.searchParams.delete("format");
  } else {
    url.searchParams.delete("design");
    url.searchParams.delete("format");
    state.report === "all" ? url.searchParams.delete("view") : url.searchParams.set("view", state.report);
  }
  window.history.replaceState({}, "", url);
}

function setSystemMode(mode, sync = true) {
  state.mode = mode;
  $("#reviewSystem").hidden = mode !== "review";
  $("#planningSystem").hidden = mode !== "planning";
  $("#refreshButton").hidden = mode !== "review";
  $("#newSuggestionButton").hidden = mode !== "review";
  $$("[data-system-mode]").forEach(node => {
    const active = node.dataset.systemMode === mode;
    node.classList.toggle("active", active);
    node.setAttribute("aria-selected", String(active));
    node.tabIndex = active ? 0 : -1;
  });
  if (sync) syncLocation();
  iconRefresh();
}

function designPathFromView(view) {
  const prefix = "file:";
  return String(view || "").startsWith(prefix) ? String(view).slice(prefix.length) : "";
}

function snapshotFingerprints(snapshot) {
  const values = {};
  (snapshot?.monitored_files || []).forEach(item => { values[item.path] = item.fingerprint; });
  (snapshot?.workflow_tree?.nodes || []).forEach(item => { values[item.path] = item.fingerprint; });
  return values;
}

async function loadDesignSnapshot(compare = false) {
  const previous = state.designFingerprints;
  const snapshot = await api("/api/design");
  const current = snapshotFingerprints(snapshot);
  state.designChanges = {};
  state.designDeleted = [];
  if (compare && previous) {
    Object.entries(current).forEach(([path, fingerprint]) => {
      if (!(path in previous)) state.designChanges[path] = "added";
      else if (previous[path] !== fingerprint) state.designChanges[path] = "modified";
    });
    state.designDeleted = Object.keys(previous).filter(path => !(path in current));
  }
  state.designSnapshot = snapshot;
  state.designFingerprints = current;
  if (!state.expandedWorkflowDirs.size) {
    (snapshot.workflow_tree?.nodes || [])
      .filter(node => node.kind === "directory" && node.depth === 0 && !node.runtime)
      .forEach(node => state.expandedWorkflowDirs.add(node.relative));
  }
}

function changeBadgeHtml(path) {
  const value = state.designChanges[path];
  if (!value) return "";
  const label = {added: "新增", modified: "修改"}[value] || value;
  return `<em class="change-badge ${escapeHtml(value)}">${escapeHtml(label)}</em>`;
}

function monitoredFileButton(item) {
  const active = state.planningView === `file:${item.path}`;
  const icon = item.format === "md" ? "file-text" : item.format === "json" ? "braces" : "file-cog";
  return `<button class="planning-artifact ${active ? "active" : ""} ${item.exists ? "" : "missing"}" data-design-path="${escapeHtml(item.path)}" ${item.exists ? "" : "disabled"}>
    <i data-lucide="${icon}"></i><span>${escapeHtml(item.path.split("/").pop())}</span>${changeBadgeHtml(item.path)}<small>${item.exists ? escapeHtml(item.format.toUpperCase()) : "缺失"}</small>
  </button>`;
}

function workflowTreeHtml(nodes) {
  const query = state.planningSearch.trim().toLowerCase();
  const byParent = new Map();
  const keep = new Set();
  const byRelative = new Map(nodes.map(node => [node.relative, node]));
  nodes.forEach(node => {
    if (!query || node.relative.toLowerCase().includes(query)) {
      keep.add(node.relative);
      let parent = node.parent;
      while (parent) {
        keep.add(parent);
        parent = byRelative.get(parent)?.parent || "";
      }
    }
    if (!byParent.has(node.parent)) byParent.set(node.parent, []);
    byParent.get(node.parent).push(node);
  });
  const branch = parent => (byParent.get(parent) || []).filter(node => !query || keep.has(node.relative)).map(node => {
    const directory = node.kind === "directory";
    const expanded = directory && (state.expandedWorkflowDirs.has(node.relative) || Boolean(query));
    const active = state.planningView === `file:${node.path}`;
    const icon = node.kind === "symlink" ? "link" : directory ? (expanded ? "folder-open" : "folder") : "file";
    return `<div class="tree-node ${node.runtime ? "runtime" : ""}" style="--tree-depth:${node.depth}">
      <button class="tree-row ${active ? "active" : ""}" data-${directory ? "tree-dir" : node.kind === "file" ? "design-path" : "tree-link"}="${escapeHtml(directory ? node.relative : node.path)}">
        <i data-lucide="${icon}"></i><span>${escapeHtml(node.name)}</span>${changeBadgeHtml(node.path)}
      </button>${expanded ? branch(node.relative) : ""}
    </div>`;
  }).join("");
  return branch("");
}

function expandSelectedWorkflowPath(path) {
  if (!path.startsWith("workflow/")) return;
  let parent = path.slice("workflow/".length).split("/").slice(0, -1);
  while (parent.length) {
    state.expandedWorkflowDirs.add(parent.join("/"));
    parent = parent.slice(0, -1);
  }
}

function renderPlanningNavigation() {
  const files = state.designSnapshot?.monitored_files || [];
  const query = state.planningSearch.trim().toLowerCase();
  const visible = files.filter(item => !query || item.path.toLowerCase().includes(query));
  $("#planningFileNav").innerHTML = visible.filter(item => item.group === "planning").map(monitoredFileButton).join("") || `<p class="planning-empty-nav">没有匹配文件。</p>`;
  $("#incrementalFileNav").innerHTML = visible.filter(item => item.group === "incremental").map(monitoredFileButton).join("") || `<p class="planning-empty-nav">没有匹配文件。</p>`;
  const tree = state.designSnapshot?.workflow_tree;
  const deleted = state.designDeleted.length ? `<div class="deleted-files"><strong>本次删除 ${state.designDeleted.length}</strong>${state.designDeleted.slice(0, 8).map(path => `<span>${escapeHtml(path)}</span>`).join("")}</div>` : "";
  $("#workflowTreeNav").innerHTML = `${tree?.truncated ? `<p class="tree-warning">目录节点超过 ${tree.limit}，结果已截断。</p>` : ""}${deleted}${tree?.exists ? workflowTreeHtml(tree.nodes || []) : `<p class="planning-empty-nav">workflow/ 尚不存在。</p>`}`;
  $$('[data-design-path]').forEach(node => node.addEventListener("click", () => {
    state.planningView = `file:${node.dataset.designPath}`;
    state.planningPresentation = "parsed";
    syncLocation();
    renderPlanningNavigation();
    renderPlanningView();
  }));
  $$('[data-tree-dir]').forEach(node => node.addEventListener("click", () => {
    const path = node.dataset.treeDir;
    state.expandedWorkflowDirs.has(path) ? state.expandedWorkflowDirs.delete(path) : state.expandedWorkflowDirs.add(path);
    renderPlanningNavigation();
  }));
  iconRefresh();
}

function displayTimestamp(value) {
  if (!value) return "修改时间未知";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? "修改时间未知" : timestamp.toLocaleString();
}

function artifactToolbarHtml(artifact) {
  const parsedLabel = artifact.format === "md" ? "阅读视图" : "结构化视图";
  const toggle = artifact.specialized_view && !artifact.parse_error ? `<div class="artifact-view-toggle">
      <button class="${state.planningPresentation === "parsed" ? "active" : ""}" data-planning-presentation="parsed">${parsedLabel}</button>
      <button class="${state.planningPresentation === "source" ? "active" : ""}" data-planning-presentation="source">原始文件</button>
    </div>` : `<span class="raw-view-label">全文模式</span>`;
  const editable = [
    "wfgen/input_example_manifest.yaml", "wfgen/workflow_build.yaml",
    "wfgen/requirements_manifest.yaml", "wfgen/workflow_implementation_plan.md",
  ].includes(artifact.path);
  const editing = Boolean(state.designDrafts[artifact.path]);
  return `<div class="artifact-toolbar">
    <div><span class="artifact-format">${escapeHtml(artifact.format.toUpperCase())}</span><span>${escapeHtml((artifact.size || 0).toLocaleString())} B</span><span>${escapeHtml(displayTimestamp(artifact.modified_at))}</span></div>
    <div>${toggle}${editable ? `<button class="${editing ? "primary-button" : "secondary-button"} compact-button" data-begin-design-edit="${escapeHtml(artifact.path)}"><i data-lucide="${editing ? "pencil-line" : "square-pen"}"></i>${editing ? "正在编辑" : "结构化编辑"}</button>` : ""}</div>
  </div>`;
}

function bindArtifactPresentation() {
  $$('[data-planning-presentation]').forEach(node => node.addEventListener("click", () => {
    state.planningPresentation = node.dataset.planningPresentation;
    syncLocation();
    renderPlanningView();
  }));
  $$('[data-begin-design-edit]').forEach(node => node.addEventListener("click", () => beginDesignEdit(node.dataset.beginDesignEdit)));
}

async function getDesignFile(path) {
  if (!state.designFileCache[path]) {
    state.designFileCache[path] = await api(`/api/design-files/${encodeURIComponent(path)}`);
  }
  return state.designFileCache[path];
}

function normalizedEditPath(path) {
  return String(path || "").split(".").map(part => /^\d+$/.test(part) ? "*" : part).join(".");
}

function schemaPathValue(values, path) {
  if (!values) return undefined;
  return values[path] ?? values[normalizedEditPath(path)];
}

function designPathParts(path) {
  return String(path || "").split(".").filter(Boolean);
}

function designValueAt(root, path) {
  return designPathParts(path).reduce((value, key) => value?.[key], root);
}

function setDesignValue(root, path, value) {
  const parts = designPathParts(path);
  const key = parts.pop();
  const parent = parts.reduce((item, part) => item[part], root);
  parent[key] = value;
}

function designReadOnly(schema, path) {
  const normalized = normalizedEditPath(path);
  return (schema.read_only || []).some(pattern => normalized === pattern || normalized.startsWith(`${pattern}.`));
}

function designListTemplate(schema, path, value) {
  const configured = schemaPathValue(schema.list_templates, path);
  if (configured !== undefined) return JSON.parse(JSON.stringify(configured));
  const key = designPathParts(path).at(-1);
  if (["reference_files", "output_files"].includes(key)) return "";
  if (key === "checker") return {name: "", args: {}};
  if (key === "fixtures") return {path: "", content: ""};
  if (key === "tests") return {name: "", args: {}, expected_pass: true};
  if (value.length) return typeof value[0] === "object" ? JSON.parse(JSON.stringify(value[0])) : "";
  return "";
}

function designObjectTemplate(path) {
  const normalized = normalizedEditPath(path);
  if (normalized === "section_coverage") return [];
  if (normalized === "runtime_contract.modes") {
    return {config: "config.yaml", make_target: "run", description: ""};
  }
  return "";
}

function fixedDesignItem(schema, path, value) {
  const values = schema.fixed_items?.[path];
  if (!values) return false;
  const identity = typeof value === "string" ? value : value?.path || value?.name;
  return values.includes(identity);
}

function designScalarEditor(value, path, schema, readOnly) {
  const label = designPathParts(path).at(-1) || "value";
  if (readOnly) {
    const display = typeof value === "string" && value.length > 500 ? `${value.slice(0, 500)}\n…（只读内容已折叠）` : String(value ?? "");
    return `<div class="design-readonly"><span>${escapeHtml(label)}</span><pre>${escapeHtml(display)}</pre></div>`;
  }
  if (typeof value === "boolean") {
    return `<label class="design-toggle"><input type="checkbox" data-design-field="${escapeHtml(path)}" data-value-type="boolean" ${value ? "checked" : ""}><span>${escapeHtml(label)}</span></label>`;
  }
  const options = schemaPathValue(schema.enums, path);
  if (options) {
    return `<label class="design-field"><span>${escapeHtml(label)}</span><select data-design-field="${escapeHtml(path)}" data-value-type="string">${options.map(option => `<option value="${escapeHtml(option)}" ${option === value ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select></label>`;
  }
  const stringValue = value ?? "";
  const multiline = typeof stringValue === "string" && (stringValue.length > 80 || stringValue.includes("\n"));
  return `<label class="design-field"><span>${escapeHtml(label)}</span>${multiline
    ? `<textarea rows="${Math.min(10, Math.max(3, String(stringValue).split("\n").length + 1))}" data-design-field="${escapeHtml(path)}" data-value-type="string">${escapeHtml(stringValue)}</textarea>`
    : `<input data-design-field="${escapeHtml(path)}" data-value-type="${typeof value === "number" ? "number" : "string"}" value="${escapeHtml(stringValue)}">`}
    ${typeof stringValue === "string" ? `<small>${stringValue.length} 字符</small>` : ""}</label>`;
}

function designEditorHtml(value, path, schema, depth = 0) {
  const readOnly = designReadOnly(schema, path);
  if (value === null || typeof value !== "object") return designScalarEditor(value, path, schema, readOnly);
  const label = designPathParts(path).at(-1) || "结构化内容";
  if (Array.isArray(value)) {
    return `<section class="design-edit-group design-array depth-${Math.min(depth, 3)}"><header><div><strong>${escapeHtml(label)}</strong><small>${value.length} 项</small></div>${readOnly ? "" : `<button class="icon-button" data-design-add="${escapeHtml(path)}" title="新增条目"><i data-lucide="plus"></i></button>`}</header><div class="design-array-items">${value.map((item, index) => {
      const itemPath = path ? `${path}.${index}` : String(index);
      const fixed = fixedDesignItem(schema, path, item);
      return `<article class="design-array-item"><div class="design-item-actions"><span>#${index + 1}${fixed ? " · 固定" : ""}</span>${readOnly || fixed ? "" : `<button data-design-move="up" data-design-array="${escapeHtml(path)}" data-design-index="${index}" title="上移"><i data-lucide="arrow-up"></i></button><button data-design-move="down" data-design-array="${escapeHtml(path)}" data-design-index="${index}" title="下移"><i data-lucide="arrow-down"></i></button><button data-design-remove="${escapeHtml(path)}" data-design-index="${index}" title="删除"><i data-lucide="trash-2"></i></button>`}</div>${designEditorHtml(item, itemPath, schema, depth + 1)}</article>`;
    }).join("") || `<p class="design-empty">当前列表为空。</p>`}</div></section>`;
  }
  const entries = Object.entries(value);
  const closed = (schema.closed_objects || []).includes(normalizedEditPath(path));
  return `<section class="design-edit-group design-object depth-${Math.min(depth, 3)}"><header><div><strong>${escapeHtml(label)}</strong><small>${entries.length} 个字段</small></div>${readOnly || closed ? "" : `<button class="icon-button" data-design-add-key="${escapeHtml(path)}" title="新增字段"><i data-lucide="list-plus"></i></button>`}</header><div class="design-object-fields">${entries.map(([key, item]) => {
    const childPath = path ? `${path}.${key}` : key;
    return `<div class="design-object-field">${designEditorHtml(item, childPath, schema, depth + 1)}${readOnly || closed || designReadOnly(schema, childPath) || ["stage_index", "stage_name"].includes(key) ? "" : `<button class="design-key-delete" data-design-delete-key="${escapeHtml(path)}" data-design-key="${escapeHtml(key)}" title="删除字段"><i data-lucide="x"></i></button>`}</div>`;
  }).join("")}</div></section>`;
}

function currentDesignDraft() {
  return state.designDrafts[designPathFromView(state.planningView)];
}

function designValidationHtml(path, edit) {
  const errors = state.designValidationErrors.filter(item => item.path === path);
  const planText = edit.schema.kind === "implementation_plan"
    ? Object.entries(edit.draft.sections || {}).map(([heading, value]) => `### ${heading}\n${value}`).join("\n") : "";
  const effective = planText.replace(/[\s`*#\-_:：/<>|()[\]{}]+/g, "").length;
  const metric = edit.schema.kind === "implementation_plan"
    ? `<div class="design-metric ${effective < edit.schema.minimum_effective_prose ? "invalid" : "valid"}"><strong>${effective}</strong><span>有效正文字符 / 最少 ${edit.schema.minimum_effective_prose}</span></div>` : "";
  const errorHtml = errors.length ? `<div class="design-validation-errors"><strong>草稿尚未通过校验</strong>${errors.map(item => `<p>${escapeHtml(item.message)}</p>`).join("")}</div>` : "";
  let values = edit.derived || {};
  if (edit.schema.kind === "input_example") values = {
    target_dir: "input/example",
    copy_mode: edit.draft.source_dir === edit.originalSourceDir ? edit.derived.copy_mode : "保存时按目录存在性计算",
    required_input_count: edit.draft.required_input?.length || 0,
    resource_count: edit.draft.resource_paths?.length || 0,
  };
  if (edit.schema.kind === "requirements") values = Object.fromEntries(
    Object.entries(edit.derived.minimum_counts || {}).map(([key]) => [key, edit.draft[`required_${key}`]?.length ?? edit.derived.minimum_counts[key]])
  );
  if (edit.schema.kind === "workflow_build") values = {
    stage_count: edit.draft.workflow_spec?.stages?.length || 0,
    checker_count: edit.draft.workflow_spec?.checkers?.length || 0,
    public_file_count: edit.draft.files?.public?.length || 0,
  };
  const derived = edit.schema.kind !== "implementation_plan"
    ? `<div class="design-derived">${Object.entries(values).map(([key, value]) => `<div><span>${escapeHtml(key)}</span><strong>${escapeHtml(typeof value === "object" ? JSON.stringify(value) : value)}</strong></div>`).join("")}</div>` : "";
  return metric + derived + errorHtml;
}

function updateDesignDraftToolbar() {
  const count = Object.keys(state.designDrafts).length;
  const blocked = ["running", "invalid"].includes(state.designSnapshot?.ucagent?.state);
  $("#designDraftCount").hidden = !count;
  $("#designDraftCount").textContent = `${count} 个草稿`;
  for (const id of ["cancelDesignEditsButton", "validateDesignEditsButton", "saveDesignEditsButton"]) {
    $(id.startsWith("#") ? id : `#${id}`).hidden = !count;
  }
  $("#saveDesignEditsButton").disabled = blocked;
  $("#saveDesignEditsButton").title = blocked ? "UCAgent 正在运行，停止并刷新后才能保存" : "保存全部草稿";
}

function bindDesignEditor() {
  $$('[data-design-field]').forEach(node => node.addEventListener("input", () => {
    const draft = currentDesignDraft();
    let value = node.type === "checkbox" ? node.checked : node.value;
    if (node.dataset.valueType === "number") value = Number(value);
    setDesignValue(draft.draft, node.dataset.designField, value);
    draft.dirty = true;
    state.designValidationErrors = [];
    if (node.tagName === "TEXTAREA") node.parentElement.querySelector("small").textContent = `${String(value).length} 字符`;
  }));
  $$('[data-design-add]').forEach(node => node.addEventListener("click", () => {
    const draft = currentDesignDraft();
    const list = designValueAt(draft.draft, node.dataset.designAdd);
    list.push(designListTemplate(draft.schema, node.dataset.designAdd, list));
    draft.dirty = true;
    state.designValidationErrors = [];
    renderPlanningView();
  }));
  $$('[data-design-remove]').forEach(node => node.addEventListener("click", () => {
    const draft = currentDesignDraft();
    designValueAt(draft.draft, node.dataset.designRemove).splice(Number(node.dataset.designIndex), 1);
    draft.dirty = true;
    state.designValidationErrors = [];
    renderPlanningView();
  }));
  $$('[data-design-move]').forEach(node => node.addEventListener("click", () => {
    const draft = currentDesignDraft();
    const list = designValueAt(draft.draft, node.dataset.designArray);
    const from = Number(node.dataset.designIndex);
    const to = node.dataset.designMove === "up" ? from - 1 : from + 1;
    if (to < 0 || to >= list.length) return;
    [list[from], list[to]] = [list[to], list[from]];
    draft.dirty = true;
    state.designValidationErrors = [];
    renderPlanningView();
  }));
  $$('[data-design-add-key]').forEach(node => node.addEventListener("click", () => {
    const key = prompt("输入新字段名称");
    if (!key?.trim()) return;
    const draft = currentDesignDraft();
    const object = designValueAt(draft.draft, node.dataset.designAddKey);
    if (Object.prototype.hasOwnProperty.call(object, key.trim())) return toast("字段已存在", true);
    object[key.trim()] = designObjectTemplate(node.dataset.designAddKey);
    draft.dirty = true;
    state.designValidationErrors = [];
    renderPlanningView();
  }));
  $$('[data-design-delete-key]').forEach(node => node.addEventListener("click", () => {
    const draft = currentDesignDraft();
    delete designValueAt(draft.draft, node.dataset.designDeleteKey)[node.dataset.designKey];
    draft.dirty = true;
    state.designValidationErrors = [];
    renderPlanningView();
  }));
}

async function beginDesignEdit(path) {
  try {
    if (!state.designDrafts[path]) {
      state.designDrafts[path] = await api(`/api/design-edit/${encodeURIComponent(path)}`);
      state.designDrafts[path].originalSourceDir = state.designDrafts[path].draft.source_dir;
    }
    state.planningPresentation = "parsed";
    updateDesignDraftToolbar();
    renderPlanningView();
  } catch (error) {
    toast(error.message, true);
  }
}

function designEditsPayload() {
  return Object.values(state.designDrafts).map(item => ({
    path: item.path, fingerprint: item.fingerprint, draft: item.draft,
  }));
}

async function validateDesignDrafts(showSuccess = true) {
  const result = await api("/api/design-edit/validate", {
    method: "POST", body: JSON.stringify({edits: designEditsPayload()}),
  });
  state.designValidationErrors = result.errors || [];
  if (!result.valid) {
    renderPlanningView();
    toast(`草稿存在 ${result.errors.length} 项错误：${result.errors[0].message}`, true);
    return false;
  }
  if (showSuccess) toast("全部草稿已通过结构、覆盖和 Checker 契约校验");
  return true;
}

async function saveDesignDrafts() {
  try {
    if (!await validateDesignDrafts(false)) return;
    const result = await api("/api/design-edit/save", {
      method: "POST", body: JSON.stringify({edits: designEditsPayload()}),
    });
    state.designDrafts = {};
    state.designValidationErrors = [];
    state.designFileCache = {};
    await loadDesignSnapshot(false);
    updateDesignDraftToolbar();
    renderPlanningNavigation();
    renderUcagentProgress();
    renderPlanningView();
    toast(`已保存 ${result.saved.length} 份规划文件`);
  } catch (error) {
    toast(error.message, true);
  }
}

function cancelDesignDrafts() {
  if (!confirm("放弃全部尚未保存的结构化修改？")) return;
  state.designDrafts = {};
  state.designValidationErrors = [];
  updateDesignDraftToolbar();
  renderPlanningView();
}

function scalarHtml(value) {
  if (value === null) return `<span class="structure-null">null</span>`;
  if (typeof value === "boolean") return `<span class="structure-bool">${value}</span>`;
  if (typeof value === "number") return `<span class="structure-number">${value}</span>`;
  return `<span class="structure-string">${escapeHtml(String(value))}</span>`;
}

function structuredValueHtml(value, depth = 0) {
  if (value === null || typeof value !== "object") return scalarHtml(value);
  if (Array.isArray(value)) {
    if (!value.length) return `<span class="structure-empty">空列表</span>`;
    if (value.every(item => item === null || typeof item !== "object")) {
      return `<div class="structure-tags">${value.map(item => `<span>${scalarHtml(item)}</span>`).join("")}</div>`;
    }
    return `<div class="structure-list">${value.map((item, index) => `
      <section class="structure-item"><header><span>#${index + 1}</span></header>${structuredValueHtml(item, depth + 1)}</section>`).join("")}</div>`;
  }
  const entries = Object.entries(value);
  if (!entries.length) return `<span class="structure-empty">空对象</span>`;
  return `<div class="structure-object depth-${Math.min(depth, 3)}">${entries.map(([key, item]) => `
    <section class="structure-field"><header>${escapeHtml(key)}</header><div>${structuredValueHtml(item, depth + 1)}</div></section>`).join("")}</div>`;
}

function markdownHtml(markdown) {
  const lines = String(markdown || "").split("\n");
  const output = [];
  let code = false;
  let list = "";
  const closeList = () => { if (list) { output.push(`</${list}>`); list = ""; } };
  const inline = text => escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  for (const line of lines) {
    if (line.startsWith("```")) {
      closeList();
      output.push(code ? "</code></pre>" : "<pre><code>");
      code = !code;
      continue;
    }
    if (code) { output.push(`${escapeHtml(line)}\n`); continue; }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const bullet = line.match(/^\s*[-*+]\s+(.+)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length + 1;
      output.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (bullet) {
      if (list && list !== "ul") closeList();
      if (!list) { output.push("<ul>"); list = "ul"; }
      output.push(`<li>${inline(bullet[1])}</li>`);
    } else if (numbered) {
      if (list && list !== "ol") closeList();
      if (!list) { output.push("<ol>"); list = "ol"; }
      output.push(`<li>${inline(numbered[1])}</li>`);
    } else if (!line.trim()) {
      closeList();
    } else {
      closeList();
      output.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  if (code) output.push("</code></pre>");
  return output.join("") || `<p>文件为空。</p>`;
}

function structureIssuesHtml(artifact) {
  const issues = artifact.structure_issues || [];
  if (!artifact.specialized_view) return "";
  if (!issues.length) return `<div class="contract-banner valid"><i data-lucide="circle-check"></i><div><strong>固定结构完整</strong><span>这是阅读器的轻量结构提示，正式结论仍以工作流 Checker 为准。</span></div></div>`;
  return `<div class="contract-banner warning"><i data-lucide="triangle-alert"></i><div><strong>发现 ${issues.length} 项结构提示</strong><span>以下提示不等同于正式 Checker 结果。</span><ul>${issues.map(issue => `<li><code>${escapeHtml(issue.path)}</code> ${escapeHtml(issue.message)}</li>`).join("")}</ul></div></div>`;
}

function itemTitle(item) {
  if (typeof item === "string") return item;
  return item?.name || item?.path || item?.id || "未命名条目";
}

function componentCollectionHtml(title, items) {
  const values = Array.isArray(items) ? items : [];
  return `<section class="planning-panel component-collection"><h3>${escapeHtml(title)} <span>${values.length}</span></h3><div class="component-grid">${values.map(item => `
    <article><strong>${escapeHtml(itemTitle(item))}</strong>${typeof item === "object" ? `<dl>${Object.entries(item).filter(([key]) => !["name", "path", "id"].includes(key)).map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : value)}</dd>`).join("")}</dl>` : ""}</article>`).join("") || "<p>无条目</p>"}</div></section>`;
}

function requirementsManifestViewHtml(artifact) {
  const view = artifact.view_model || {};
  const counts = view.counts || {};
  const cards = Object.entries(counts).map(([key, count]) => `<div class="plan-metric"><span>${escapeHtml(key.replace("required_", ""))}</span><strong>${count}</strong></div>`).join("");
  const coverage = (view.coverage || []).map(item => `<div class="coverage-row"><strong>${escapeHtml(item.section)}</strong><div class="structure-tags">${(item.targets || []).map(target => `<span>${escapeHtml(target)}</span>`).join("")}</div></div>`).join("");
  const components = view.components || {};
  const stages = components.required_stages || [];
  return `${structureIssuesHtml(artifact)}<div class="plan-overview-grid">${cards}</div>
    <section class="planning-panel manifest-source"><span>需求来源</span><strong>${escapeHtml(view.source_requirement || "未声明")}</strong></section>
    <section class="planning-panel"><h3>需求章节覆盖</h3>${coverage || "<p>没有章节覆盖记录。</p>"}</section>
    <section class="planning-panel"><h3>阶段与配置归属</h3><div class="data-table"><div class="data-row heading"><span>阶段</span><span>显示名称</span><span>配置</span></div>${stages.map(stage => `<div class="data-row"><code>${escapeHtml(stage.name || "")}</code><span>${escapeHtml(stage.label || "")}</span><code>${escapeHtml(stage.config || "")}</code></div>`).join("")}</div></section>
    ${componentCollectionHtml("业务工具", components.required_tools)}
    ${componentCollectionHtml("Checker", components.required_checkers)}
    ${componentCollectionHtml("GuideDoc", components.required_guidedocs)}
    ${componentCollectionHtml("用户文档", components.required_user_docs)}
    <section class="planning-panel split-contract"><div><h3>运行时契约</h3>${structuredValueHtml(view.runtime_contract || {})}</div><div><h3>里程碑</h3>${structuredValueHtml(view.milestones || {})}<h3>最低交付数量</h3>${structuredValueHtml(view.minimum_counts || {})}</div></section>
    <section class="planning-panel"><h3>依赖与 Make 目标</h3>${structuredValueHtml({python: view.python_dependencies || [], system: view.system_dependencies || [], make_targets: view.make_targets || []})}</section>`;
}

function workflowBuildViewHtml(artifact) {
  const view = artifact.view_model || {};
  const workflow = view.workflow || {};
  const runtime = view.runtime_contract || {};
  const fileGroups = view.files || {};
  const stages = view.stages || [];
  const checkers = view.checkers || [];
  const fileSection = group => (fileGroups[group] || []).map(item => `<div class="file-contract-row"><code>${escapeHtml(item.path || "")}</code><span>${escapeHtml(item.template || "")}</span></div>`).join("") || "<p>无文件</p>";
  return `${structureIssuesHtml(artifact)}${view.reference_template ? `<div class="reference-banner"><i data-lucide="book-copy"></i>这是结构参考模板，不是当前业务的真实构建配置。</div>` : ""}
    <div class="build-identity"><div><span>工作流</span><h3>${escapeHtml(workflow.name || "未命名")}</h3><p>${escapeHtml(workflow.description || "")}</p></div><dl><dt>版本</dt><dd>${escapeHtml(workflow.version || "")}</dd><dt>交付根目录</dt><dd>${escapeHtml(view.root?.path || "")}</dd><dt>覆盖</dt><dd>${escapeHtml(String(view.root?.overwrite ?? ""))}</dd></dl></div>
    <section class="planning-panel"><h3>运行时输入与模式</h3><div class="runtime-summary"><div>${structuredValueHtml({target_variable: runtime.target_variable, input_root: runtime.input_root, output_root: runtime.output_root, example_target: runtime.example_target, required_input: runtime.required_input || []})}</div><div>${structuredValueHtml(view.modes || {})}</div></div></section>
    <section class="planning-panel"><h3>交付文件</h3><div class="two-columns"><div><h4>公开文件</h4>${fileSection("public")}</div><div><h4>内部文件</h4>${fileSection("internal")}</div></div></section>
    <section class="planning-panel"><h3>Make 目标</h3><div class="structure-tags">${(view.make_targets || []).map(target => `<span>${escapeHtml(target)}</span>`).join("")}</div></section>
    <section class="planning-panel"><h3>阶段流程</h3><div class="stage-flow">${stages.map((stage, index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><div><h4>${escapeHtml(stage.name || "")}</h4><p>${escapeHtml(stage.description || "")}</p><dl><dt>引用</dt><dd>${escapeHtml((stage.reference_files || []).join("\n"))}</dd><dt>输出</dt><dd>${escapeHtml((stage.output_files || []).join("\n"))}</dd><dt>Checker</dt><dd>${escapeHtml((stage.checker || []).map(binding => binding.name || "").join(", "))}</dd></dl></div></article>`).join("")}</div></section>
    <section class="planning-panel"><h3>Checker 中心定义</h3><div class="checker-contracts">${checkers.map(checker => `<details><summary><strong>${escapeHtml(checker.name)}</strong><span>${escapeHtml(checker.entry?.class_name || "")}</span><small>${checker.fixtures.length} fixtures · ${checker.tests.length} tests</small></summary><p>${escapeHtml(checker.description)}</p><dl><dt>实现</dt><dd>${escapeHtml(`${checker.entry?.file || ""} :: ${checker.entry?.method || ""}`)}</dd></dl><pre><code>${escapeHtml(checker.source || "")}</code></pre></details>`).join("")}</div></section>
    <section class="planning-panel"><h3>验收契约</h3>${structuredValueHtml(view.acceptance || {})}</section>`;
}

function inputExampleViewHtml(artifact) {
  const view = artifact.view_model || {};
  return `${structureIssuesHtml(artifact)}<div class="copy-flow"><div><span>来源</span><strong>${escapeHtml(view.source_dir || "-")}</strong></div><i data-lucide="arrow-right"></i><div><span>${escapeHtml(view.copy_mode || "未声明")}</span><strong>复制规则</strong></div><i data-lucide="arrow-right"></i><div><span>目标</span><strong>${escapeHtml(view.target_dir || "-")}</strong></div></div>
    ${componentCollectionHtml("必需示例输入", view.required_input)}${componentCollectionHtml("资源路径映射", view.resource_paths)}`;
}

function smokeSelectionViewHtml(artifact) {
  const view = artifact.view_model || {};
  return `${structureIssuesHtml(artifact)}<div class="smoke-tool-card"><span>代表性业务工具</span><h2>${escapeHtml(view.name || "未选择")}</h2><dl><dt>Tool Spec</dt><dd><code>${escapeHtml(view.spec_path || "")}</code></dd></dl></div>${componentCollectionHtml("验证 Fixture", view.fixture_paths)}`;
}

function mcpBaselineViewHtml(artifact) {
  const view = artifact.view_model || {};
  const tools = view.tools || [];
  const calls = view.mcp_result?.calls || [];
  const callByName = Object.fromEntries(calls.map(call => [call.name, call]));
  return `${structureIssuesHtml(artifact)}<div class="evidence-header ${escapeHtml(view.status || "unknown")}"><div><span>${escapeHtml(view.stage || "MCP 基线")}</span><h2>${escapeHtml(view.status || "unknown")}</h2></div><dl><dt>生成时间</dt><dd>${escapeHtml(view.generated_at || "")}</dd><dt>结果日志</dt><dd>${escapeHtml(view.mcp_result?.result_log || view.result_log || "")}</dd></dl></div>
    <section class="planning-panel"><h3>工具调用矩阵</h3><div class="data-table"><div class="data-row heading"><span>工具</span><span>Direct</span><span>MCP</span></div>${tools.map(tool => `<div class="data-row"><strong>${escapeHtml(tool.name || "")}</strong><span class="status-text ${escapeHtml(tool.direct_result?.status || "unknown")}">${escapeHtml(tool.direct_result?.status || "unknown")}</span><span class="status-text ${escapeHtml(callByName[tool.name]?.status || "missing")}">${escapeHtml(callByName[tool.name]?.status || "missing")}</span></div>`).join("")}</div></section>
    <section class="planning-panel split-contract"><div><h3>服务生命周期</h3>${structuredValueHtml(view.service_lifecycle || {})}</div><div><h3>测试后静态检查</h3>${structuredValueHtml(view.post_mcp_static_check || {})}</div></section>
    <section class="planning-panel"><h3>失败摘要</h3>${(view.failure_summary || []).length ? structuredValueHtml(view.failure_summary) : `<div class="no-failures"><i data-lucide="circle-check"></i><span>没有失败记录${view.summary_note ? `<small>${escapeHtml(view.summary_note)}</small>` : ""}</span></div>`}</section>`;
}

function guidedocSchemaViewHtml(artifact) {
  const view = artifact.view_model || {};
  return `${structureIssuesHtml(artifact)}<div class="guide-schema-header"><div><span>${escapeHtml(view.document_type || "")}</span><h2>${escapeHtml(view.title || "")}</h2></div><dl><dt>输出</dt><dd>${escapeHtml(view.output || "")}</dd><dt>操作契约</dt><dd>${escapeHtml(String(view.operation_contract ?? ""))}</dd></dl></div><div class="guide-section-flow">${(view.sections || []).map((section, index) => `<article><span>${index + 1}</span><div><small>${escapeHtml(section.id || "")}</small><h3>${escapeHtml(section.heading || "")}</h3><p>${escapeHtml(section.content || "")}</p></div></article>`).join("")}</div>`;
}

function implementationPlanViewHtml(artifact) {
  const view = artifact.view_model || {};
  const sections = view.sections || [];
  const records = view.records || [];
  return `${structureIssuesHtml(artifact)}<div class="plan-stat-strip">${Object.entries(view.stats || {}).map(([key, value]) => `<div><span>${escapeHtml(key)}</span><strong>${value}</strong></div>`).join("")}</div><div class="plan-reader-body">${sections.map((section, index) => `<section id="plan-section-${index}" class="plan-prose-section"><h2>${escapeHtml(section.heading)}</h2>${markdownHtml(section.content)}${(section.children || []).map(child => `<div class="plan-component"><h3>${escapeHtml(child.heading)}</h3>${markdownHtml(child.content)}</div>`).join("")}</section>`).join("")}<section id="plan-timeline" class="plan-prose-section"><h2>阶段追加记录</h2><div class="living-plan-timeline">${records.map(record => `<article><div class="timeline-index">${String(record.index).padStart(2, "0")}</div><div><h3>${escapeHtml(record.name)}</h3><p class="digest">前序 SHA256：${escapeHtml(record.digest)}</p><p>${record.prose_length} 个有效字符</p>${record.sections.map(section => `<details><summary>${escapeHtml(section.heading)}</summary>${markdownHtml(section.content)}</details>`).join("")}</div></article>`).join("") || "<p>尚无追加记录。</p>"}</div></section></div>`;
}

function appliedChangesViewHtml(artifact) {
  const view = artifact.view_model || {};
  const entries = [...(view.entries || [])].reverse();
  return `${structureIssuesHtml(artifact)}<div class="plan-overview-grid">
    <div class="plan-metric"><span>Revision</span><strong>${escapeHtml(view.revision ?? "-")}</strong></div>
    <div class="plan-metric"><span>部署批次</span><strong>${view.entry_count || 0}</strong></div>
    <div class="plan-metric"><span>文件变更</span><strong>${view.change_count || 0}</strong></div>
  </div><section class="planning-panel deployment-reader"><h3>部署记录</h3>${entries.map(entry => `<details>
    <summary><span class="status-text ${escapeHtml(entry.status || "unknown")}">${escapeHtml(entry.status || "unknown")}</span><strong>${escapeHtml(entry.id || "未命名部署")}</strong><small>${escapeHtml(entry.applied_at || "")}</small></summary>
    <div class="deployment-meta">${structuredValueHtml({run_id: entry.run_id, batch_id: entry.batch_id, attempt_id: entry.attempt_id, operation: entry.operation, workflow_root: entry.workflow_root, approval_ids: entry.approval_ids, approval_provenance: entry.approval_provenance})}</div>
    <div class="deployment-files">${(entry.changes || []).map(change => `<article><header><code>${escapeHtml(change.target || "")}</code><span>${escapeHtml(String(change.sha256 || "").slice(0, 12))}</span></header><p>${escapeHtml(change.rationale || "")}</p>${structuredValueHtml({source: change.source, approval_ids: change.approval_ids, backup: change.backup || {}, supersedes: change.supersedes || {}})}</article>`).join("")}</div>
  </details>`).join("") || "<p>尚无部署记录。</p>"}</section>`;
}

function incrementalReportViewHtml(artifact) {
  const view = artifact.view_model || {};
  const latest = view.latest;
  if (!latest) return `${structureIssuesHtml(artifact)}<div class="planning-empty compact"><i data-lucide="clipboard-x"></i><h3>尚无增量运行</h3><p>该文件已经初始化，但 runs 列表为空。</p></div>`;
  const checks = latest.checks || [];
  const findings = latest.findings || [];
  return `${structureIssuesHtml(artifact)}<div class="evidence-header ${escapeHtml(latest.status || "unknown")}"><div><span>最新增量运行</span><h2>${escapeHtml(latest.run_id || "未知运行")}</h2><p>${escapeHtml(latest.summary?.verdict || latest.status || "")}</p></div><dl><dt>状态</dt><dd>${escapeHtml(latest.status || "")}</dd><dt>开始</dt><dd>${escapeHtml(latest.started_at || "")}</dd><dt>结束</dt><dd>${escapeHtml(latest.finished_at || "")}</dd></dl></div>
    <div class="plan-overview-grid"><div class="plan-metric"><span>Revision</span><strong>${escapeHtml(view.revision ?? "-")}</strong></div><div class="plan-metric"><span>运行数</span><strong>${view.run_count || 0}</strong></div><div class="plan-metric"><span>检查项</span><strong>${checks.length}</strong></div><div class="plan-metric"><span>发现项</span><strong>${findings.length}</strong></div></div>
    <section class="planning-panel"><h3>运行摘要与指标</h3>${structuredValueHtml({target: latest.target || {}, summary: latest.summary || {}, metrics: latest.metrics || {}})}</section>
    <section class="planning-panel"><h3>检查结果</h3><div class="incremental-checks">${checks.map(check => `<article class="${escapeHtml(check.status || "unknown")}"><header><i class="state-dot ${escapeHtml(check.status || "unknown")}"></i><strong>${escapeHtml(check.id || "")}</strong><span>${escapeHtml(check.status || "")}</span></header><p>${escapeHtml(check.summary || "")}</p><details><summary>查看证据</summary>${structuredValueHtml(check.evidence || [])}</details></article>`).join("") || "<p>无检查记录。</p>"}</div></section>
    <section class="planning-panel"><h3>发现项</h3>${findings.length ? `<div class="incremental-findings">${findings.map(finding => `<article><header><strong>${escapeHtml(finding.title || finding.id || "未命名发现")}</strong><span class="status-text ${escapeHtml(finding.severity || "unknown")}">${escapeHtml(finding.severity || "")}</span></header><p>${escapeHtml(finding.description || "")}</p>${structuredValueHtml({component: finding.component, expected: finding.expected, actual: finding.actual, remediation: finding.remediation})}</article>`).join("")}</div>` : `<div class="no-failures"><i data-lucide="circle-check"></i><span>没有发现项</span></div>`}</section>
    <section class="planning-panel"><h3>历史运行</h3><div class="run-history">${(view.runs || []).map(run => `<details><summary><strong>${escapeHtml(run.run_id || "")}</strong><span class="status-text ${escapeHtml(run.status || "unknown")}">${escapeHtml(run.status || "")}</span><small>${escapeHtml(run.finished_at || run.started_at || "")}</small></summary>${structuredValueHtml({summary: run.summary || {}, metrics: run.metrics || {}, findings: run.findings || []})}</details>`).join("")}</div></section>`;
}

function sourcePreviewHtml(artifact) {
  if (!artifact.previewable) return `<div class="binary-preview"><i data-lucide="file-warning"></i><h3>不能预览该文件</h3><p>${escapeHtml(artifact.reason || "仅提供文件元数据")}</p><dl><dt>大小</dt><dd>${escapeHtml((artifact.size || 0).toLocaleString())} B</dd><dt>修改时间</dt><dd>${escapeHtml(displayTimestamp(artifact.modified_at))}</dd></dl></div>`;
  return `<pre class="source-reader">${String(artifact.content || "").split("\n").map((line, index) => `<span data-line="${index + 1}">${escapeHtml(line)}</span>`).join("\n")}</pre>`;
}

function specializedArtifactHtml(artifact) {
  const renderers = {
    requirements_manifest: requirementsManifestViewHtml,
    workflow_build: workflowBuildViewHtml,
    workflow_build_schema: workflowBuildViewHtml,
    input_example_manifest: inputExampleViewHtml,
    smoke_tool_selection: smokeSelectionViewHtml,
    mcp_baseline_evidence: mcpBaselineViewHtml,
    guidedoc_spec_schema: guidedocSchemaViewHtml,
    workflow_implementation_plan: implementationPlanViewHtml,
    applied_changes: appliedChangesViewHtml,
    incremental_report: incrementalReportViewHtml,
  };
  return renderers[artifact.artifact_kind]?.(artifact) || sourcePreviewHtml(artifact);
}

function bindSpecializedInteractions() {
  $$('[data-plan-anchor]').forEach(node => node.addEventListener("click", () => {
    document.getElementById(node.dataset.planAnchor)?.scrollIntoView({behavior: "smooth", block: "start"});
  }));
}

function renderDocumentOutline() {
  const scroller = $("#planningReaderScroll");
  const outline = $("#documentOutlineBar");
  if (!scroller || !outline) return;
  const headings = [...scroller.querySelectorAll(".planning-panel > h3, .plan-prose-section > h2, .build-identity h3, .guide-schema-header h2, .evidence-header h2")];
  const unique = [];
  headings.forEach((heading, index) => {
    const label = heading.textContent.trim();
    if (!label || unique.some(item => item.label === label)) return;
    heading.id ||= `design-section-${index}`;
    unique.push({id: heading.id, label});
  });
  outline.hidden = !unique.length;
  outline.innerHTML = unique.map(item => `<button data-outline-target="${escapeHtml(item.id)}">${escapeHtml(item.label)}</button>`).join("");
  $$('[data-outline-target]').forEach(node => node.addEventListener("click", () => {
    const heading = document.getElementById(node.dataset.outlineTarget);
    if (!heading) return;
    const top = heading.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop - 14;
    scroller.scrollTo({top, behavior: "smooth"});
  }));
  let scheduled = false;
  const updateActive = () => {
    scheduled = false;
    const scrollerTop = scroller.getBoundingClientRect().top + 24;
    let active = unique[0]?.id;
    unique.forEach(item => {
      const heading = document.getElementById(item.id);
      if (heading && heading.getBoundingClientRect().top <= scrollerTop) active = item.id;
    });
    $$('[data-outline-target]').forEach(node => node.classList.toggle("active", node.dataset.outlineTarget === active));
  };
  scroller.addEventListener("scroll", () => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(updateActive);
    }
  });
  updateActive();
}

function durationLabel(seconds) {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.max(0, Math.floor(Number(seconds)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

function renderUcagentProgress() {
  const progress = state.designSnapshot?.ucagent || {state: "not_started"};
  const labels = {not_started: "尚未启动", running: "运行记录中", completed: "全部完成", exited: "异常退出", invalid: "状态损坏"};
  const percent = progress.total_stages ? Math.round((progress.completed_stages || 0) / progress.total_stages * 100) : 0;
  if (progress.state === "not_started") {
    $("#ucagentProgress").innerHTML = `<div class="progress-empty"><i data-lucide="circle-dashed"></i><h3>UCAgent 尚未启动</h3><p>未找到根目录 <code>.ucagent/ucagent_info.json</code>。</p></div>`;
    iconRefresh();
    return;
  }
  if (progress.state === "invalid") {
    $("#ucagentProgress").innerHTML = `<div class="progress-empty error"><i data-lucide="file-warning"></i><h3>进度状态无法读取</h3><p>${escapeHtml(progress.error || "状态文件格式错误")}</p><small>${escapeHtml(displayTimestamp(progress.modified_at))}</small></div>`;
    iconRefresh();
    return;
  }
  $("#ucagentProgress").innerHTML = `<div class="progress-heading"><span>根 UCAgent</span><strong class="progress-state ${escapeHtml(progress.state)}">${escapeHtml(labels[progress.state] || progress.state)}</strong></div>
    <section class="progress-card"><div class="progress-numbers"><strong>${progress.completed_stages || 0}</strong><span>/ ${progress.total_stages || 0} 阶段</span></div><div class="progress-track"><span style="width:${percent}%"></span></div><small>${percent}% · ${escapeHtml(durationLabel(progress.elapsed_seconds))}</small></section>
    <section class="progress-card current-stage"><span>当前记录</span><h3>${escapeHtml(progress.stage_title || (progress.all_completed ? "工作流已完成" : `Stage ${progress.stage_index ?? "-"}`))}</h3><dl><dt>阶段索引</dt><dd>${escapeHtml(progress.stage_index ?? "-")}</dd><dt>本阶段失败</dt><dd class="${progress.stage_fail_count ? "danger-text" : ""}">${escapeHtml(progress.stage_fail_count || 0)}</dd><dt>累计失败</dt><dd class="${progress.failure_count_total ? "danger-text" : ""}">${escapeHtml(progress.failure_count_total || 0)}</dd><dt>Checker</dt><dd>${progress.stage_check_pass ? "通过" : progress.stage_completed ? "未通过" : "等待"}</dd></dl></section>
    ${progress.checkers?.length ? `<section class="progress-card"><span>Checker 最近结果</span><div class="checker-mini-list">${progress.checkers.map(checker => `<div><strong>${escapeHtml(checker.name)}</strong><small><b>${checker.passed || 0} PASS</b>${checker.failed ? `<em>${checker.failed} FAIL</em>` : ""}</small></div>`).join("")}</div></section>` : ""}
    ${progress.journal ? `<section class="progress-card"><span>阶段 Journal</span><p>${escapeHtml(progress.journal)}</p></section>` : ""}
    <section class="progress-card"><span>最近阶段</span><div class="recent-stage-list">${(progress.recent_stages || []).map(stage => `<div><i class="state-dot ${stage.completed ? stage.check_pass ? "passed" : "failed" : "not_run"}"></i><span>${escapeHtml(stage.title || `Stage ${stage.index}`)}</span><small>${escapeHtml(durationLabel(stage.time_cost))}</small></div>`).join("")}</div></section>
    <footer class="progress-updated">状态文件更新于<br>${escapeHtml(displayTimestamp(progress.modified_at))}</footer>`;
  iconRefresh();
}

async function renderPlanningView() {
  const target = $("#planningContent");
  const request = ++state.planningRequest;
  const path = designPathFromView(state.planningView);
  if (!path) {
    target.innerHTML = `<div class="planning-empty"><i data-lucide="mouse-pointer-2"></i><h3>选择监控内容</h3><p>从左侧选择构建文件、增量记录或 workflow 文本文件。</p></div>`;
    iconRefresh();
    return;
  }
  target.innerHTML = `<div class="planning-loading">正在解析 ${escapeHtml(path)}...</div>`;
  try {
    const artifact = await getDesignFile(path);
    if (request !== state.planningRequest) return;
    const edit = state.designDrafts[path];
    const source = state.planningPresentation === "source" || artifact.artifact_kind === "workflow_source" || !artifact.specialized_view || Boolean(artifact.parse_error);
    const content = edit && state.planningPresentation !== "source"
      ? `<div class="design-editor"><div class="design-editor-notice"><i data-lucide="pencil-line"></i><div><strong>结构化草稿</strong><p>修改仅保存在当前浏览器内。完成后使用页面顶部的“保存修改”统一写入。</p></div></div>${designValidationHtml(path, edit)}${designEditorHtml(edit.draft, "", edit.schema)}</div>`
      : source
      ? sourcePreviewHtml(artifact)
      : specializedArtifactHtml(artifact);
    const description = edit && state.planningPresentation !== "source"
      ? "受控字段编辑模式；原始文件和系统字段保持只读"
      : artifact.parse_error
      ? `格式解析失败，已回退到完整原文：${artifact.parse_error}`
      : artifact.artifact_kind === "workflow_source"
        ? "workflow/ 文件只读预览"
      : source ? "原始文件视图" : "依据母工作流固定契约生成的专用阅读视图";
    target.innerHTML = `<div class="planning-reader"><header class="planning-reader-header"><div class="planning-title"><span class="eyebrow">${escapeHtml(artifact.path)}</span><h2>${escapeHtml(path)}</h2><p>${escapeHtml(description)}</p></div>${artifactToolbarHtml(artifact)}<nav class="document-outline-bar" id="documentOutlineBar" aria-label="当前文档章节" hidden></nav></header><div class="planning-reader-scroll" id="planningReaderScroll">${content}</div></div>`;
    bindArtifactPresentation();
    if (edit && state.planningPresentation !== "source") bindDesignEditor();
    else bindSpecializedInteractions();
    renderDocumentOutline();
  } catch (error) {
    if (request !== state.planningRequest) return;
    target.innerHTML = `<div class="planning-empty"><h3>无法解析文件</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
  iconRefresh();
}

async function openPlanningSystem(view = "file:wfgen/requirements_manifest.yaml", sync = true) {
  setSystemMode("planning", false);
  state.planningView = view;
  try {
    if (!state.designSnapshot) await loadDesignSnapshot(false);
    const requestedPath = designPathFromView(state.planningView);
    const known = new Set([
      ...(state.designSnapshot.monitored_files || []).filter(item => item.exists).map(item => item.path),
      ...(state.designSnapshot.workflow_tree?.nodes || []).filter(item => item.kind === "file").map(item => item.path),
    ]);
    if (!known.has(requestedPath)) {
      const first = (state.designSnapshot.monitored_files || []).find(item => item.exists);
      state.planningView = first ? `file:${first.path}` : "";
      state.planningPresentation = "parsed";
      if (requestedPath) toast("请求的监控文件不存在，已打开首个可用文件", true);
    }
    expandSelectedWorkflowPath(designPathFromView(state.planningView));
    if (sync) syncLocation();
    renderPlanningNavigation();
    renderUcagentProgress();
    renderPlanningView();
  } catch (error) {
    $("#planningContent").innerHTML = `<div class="planning-empty"><h3>无法读取规划产物</h3><p>${escapeHtml(error.message)}</p></div>`;
    $("#ucagentProgress").innerHTML = `<div class="progress-empty error"><h3>设计监控不可用</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function openHistoryAction(item, action) {
  const restore = action === "restore";
  $("#historyRepairId").value = item.repair_id;
  $("#historyAction").value = action;
  $("#historyTitle").textContent = restore ? "恢复历史版本" : "删除历史版本";
  $("#historySubmitLabel").textContent = restore ? "确认恢复" : "确认删除";
  $("#saveHistoryButton").classList.toggle("danger-button", !restore);
  $("#saveHistoryButton").classList.toggle("primary-button", restore);
  $("#historyDescription").textContent = restore
    ? `将 ${item.backup.path} 恢复到 ${item.workflow_root}/${item.target}。恢复前会自动保存当前正式文件，并新增一条可审计部署记录。`
    : `永久删除 ${item.backup.path}。部署哈希、删除时间和理由仍会保留，但删除后不能再使用这个版本恢复。`;
  $("#historyReason").value = restore
    ? `当前修复不符合预期，恢复部署 ${item.entry_id} 之前保存的文件版本，并保留现有版本以便再次回退。`
    : `该历史版本已确认不再需要，为释放工作区临时存储而删除，保留审计元数据。`;
  $("#historyError").textContent = "";
  $("#historyDialog").showModal();
  iconRefresh();
}

async function saveHistoryAction(event) {
  event.preventDefault();
  const action = $("#historyAction").value;
  const reason = $("#historyReason").value.trim();
  if (!reason) {
    $("#historyError").textContent = "必须填写操作理由。";
    return;
  }
  try {
    await api(`/api/repairs/history/${action}`, {
      method: "POST",
      body: JSON.stringify({id: $("#historyRepairId").value, reason}),
    });
    $("#historyDialog").close();
    state.selectedId = null;
    toast(action === "restore" ? "历史版本已恢复，原正式文件已另行备份" : "历史版本已删除并保留审计记录");
    await loadState(false);
  } catch (error) {
    $("#historyError").textContent = error.message;
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[char]);
}

function openDecision(item) {
  $("#decisionItemId").value = item.review_id;
  $("#decisionTitle").textContent = item.title;
  $("#decisionError").textContent = "";
  const value = item.decision?.decision || "approved";
  $(`#decisionForm input[value="${value}"]`).checked = true;
  const reason = $("#decisionReason");
  reason.value = item.decision?.reason || defaultDecisionReason(item, value);
  reason.dataset.generated = item.decision?.reason ? "false" : "true";
  $("#decisionDialog").showModal();
  iconRefresh();
}

async function saveDecision(event) {
  event.preventDefault();
  const decision = $("#decisionForm input[name=decision]:checked")?.value;
  const reason = $("#decisionReason").value.trim();
  if (!decision || !reason) {
    $("#decisionError").textContent = "请选择决定并填写理由。";
    return;
  }
  try {
    await api("/api/decisions", {
      method: "POST",
      body: JSON.stringify({id: $("#decisionItemId").value, decision, reason}),
    });
    $("#decisionDialog").close();
    toast("决定已记录并写入审计历史");
    await loadState(false);
  } catch (error) {
    $("#decisionError").textContent = error.message;
  }
}

async function saveSuggestion(event) {
  event.preventDefault();
  const title = $("#suggestionTitle").value.trim();
  const description = $("#suggestionDescription").value.trim();
  if (!title || !description) {
    $("#suggestionError").textContent = "标题和建议内容不能为空。";
    return;
  }
  try {
    await api("/api/suggestions", {
      method: "POST",
      body: JSON.stringify({
        title,
        description,
        priority: $("#suggestionPriority").value,
        entry_kind: $("#suggestionKind").value,
      }),
    });
    $("#suggestionDialog").close();
    $("#suggestionForm").reset();
    toast("用户条目已添加");
    await loadState(false);
  } catch (error) {
    $("#suggestionError").textContent = error.message;
  }
}

function bulkDecisionReason(decision, count) {
  if (decision === "rejected") {
    return `已批量审阅所选 ${count} 项的描述与证据，当前不接受这些评估结论或用户条目。现有证据不足以支持所述影响，后续如补充可复现依据，应重新提交评审。`;
  }
  if (decision === "deferred") {
    return `已批量审阅所选 ${count} 项，暂缓作出最终处理决定。需要先补充需求依据、影响范围或复现结果；在重新批准前，增量工作流不得实施相关修改。`;
  }
  return `已批量审阅所选 ${count} 项的描述、影响与证据，同意按各项修复建议或用户要求处理。修改必须分别受对应批准项约束，完成后应重新运行受影响的评估确认结果。`;
}

function openBulkDecision() {
  const count = state.selectedIds.size;
  if (!count) return;
  $("#bulkDecisionTitle").textContent = `审批所选 ${count} 项`;
  const decision = $("#bulkDecisionForm input[name=bulkDecision]:checked")?.value || "approved";
  $("#bulkDecisionReason").value = bulkDecisionReason(decision, count);
  $("#bulkDecisionReason").dataset.generated = "true";
  $("#bulkDecisionError").textContent = "";
  $("#bulkDecisionDialog").showModal();
  iconRefresh();
}

async function saveBulkDecision(event) {
  event.preventDefault();
  const decision = $("#bulkDecisionForm input[name=bulkDecision]:checked")?.value;
  const reason = $("#bulkDecisionReason").value.trim();
  if (!decision || !reason || !state.selectedIds.size) {
    $("#bulkDecisionError").textContent = "请选择项目、决定并填写理由。";
    return;
  }
  try {
    await api("/api/decisions/bulk", {
      method: "POST",
      body: JSON.stringify({ids: [...state.selectedIds], decision, reason}),
    });
    $("#bulkDecisionDialog").close();
    const count = state.selectedIds.size;
    state.selectedIds.clear();
    toast(`已记录 ${count} 项批量决定`);
    await loadState(false);
  } catch (error) {
    $("#bulkDecisionError").textContent = error.message;
  }
}

async function withdraw(item) {
  if (!confirm(`确认撤回用户条目“${item.title}”？`)) return;
  try {
    await api(`/api/suggestions/${encodeURIComponent(item.source_id)}/withdraw`, {
      method: "POST", body: "{}",
    });
    state.selectedId = null;
    toast("用户条目已撤回");
    await loadState(false);
  } catch (error) {
    toast(error.message, true);
  }
}

async function deleteReviewItems(ids) {
  const repairs = repairItems();
  if (ids.some(id => repairs.some(item => item.review_id === id))) {
    await deleteRepairItems(ids);
    return;
  }
  const message = `确认物理删除 ${ids.length} 个评估或用户条目？对应的关联审批也会删除，此操作不能撤销。`;
  if (!confirm(message)) return;
  try {
    const result = await api("/api/review-items/delete", {
      method: "POST",
      body: JSON.stringify({ids}),
    });
    state.selectedId = null;
    ids.forEach(id => state.selectedIds.delete(id));
    toast(`已删除 ${result.deleted.length} 个条目，清理 ${result.approvals_deleted} 条关联审批`);
    await loadState(false);
  } catch (error) {
    toast(error.message, true);
  }
}

async function deleteRepairItems(ids) {
  const reason = ids.length === 1
    ? "用户从版本管理界面删除该部署版本记录，以清理控制台列表。"
    : `用户批量删除 ${ids.length} 条部署版本记录，以清理控制台列表。`;
  if (!confirm(
    `确认从版本管理界面删除 ${ids.length} 条记录？\n\n` +
    "当前 workflow 正式文件不会改变，可恢复的旧版本文件也会保留；底层审计信息仍可追溯。"
  )) return;
  try {
    const result = await api("/api/repairs/delete", {
      method: "POST",
      body: JSON.stringify({ids, reason}),
    });
    state.selectedId = null;
    ids.forEach(id => state.selectedIds.delete(id));
    toast(`已从版本管理列表删除 ${result.deleted.length} 条记录`);
    await loadState(false);
  } catch (error) {
    toast(error.message, true);
  }
}

function deleteSelectedReviewItems() {
  if (state.selectedIds.size) deleteReviewItems([...state.selectedIds]);
}

async function loadState(showToast = true) {
  $("#refreshButton").disabled = true;
  try {
    state.data = await api("/api/state");
    const currentIds = new Set([...state.data.items, ...repairItems()].map(item => item.review_id));
    state.selectedIds = new Set([...state.selectedIds].filter(id => currentIds.has(id)));
    renderSummary();
    renderCounts();
    renderList();
    if (showToast) toast("报告已刷新");
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("#refreshButton").disabled = false;
    iconRefresh();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const parameters = new URLSearchParams(window.location.search);
  const requestedView = parameters.get("view");
  const requestedTab = parameters.get("tab");
  const requestedDesign = parameters.get("design");
  if (["all", "tools", "checkers", "flow", "env", "run", "user", "repairs"].includes(requestedView)) {
    state.report = requestedView;
    $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.report === requestedView));
  }
  if (requestedTab === "design") {
    if (requestedDesign?.startsWith("file:")) state.planningView = requestedDesign;
    else if (requestedDesign?.startsWith("artifact:")) state.planningView = `file:wfgen/${requestedDesign.slice("artifact:".length)}`;
    else if (requestedDesign === "incremental") state.planningView = "file:eval/incremental_report.json";
    else state.planningView = "file:wfgen/requirements_manifest.yaml";
    state.planningPresentation = parameters.get("format") === "source" ? "source" : "parsed";
  }
  $$(".nav-item").forEach(node => node.addEventListener("click", () => {
    $$(".nav-item").forEach(item => item.classList.remove("active"));
    node.classList.add("active");
    state.report = node.dataset.report;
    state.selectedId = null;
    state.selectedIds.clear();
    syncLocation();
    renderList();
  }));
  $$(".severity-filter input").forEach(node => node.addEventListener("change", () => {
    node.checked ? state.severities.add(node.value) : state.severities.delete(node.value);
    renderList();
  }));
  $("#decisionFilter").addEventListener("change", event => {
    state.decisionFilter = event.target.value;
    state.selectedId = null;
    state.selectedIds.clear();
    renderList();
  });
  $("#searchInput").addEventListener("input", event => {
    state.search = event.target.value;
    renderList();
  });
  $("#refreshButton").addEventListener("click", () => loadState());
  $("#selectVisible").addEventListener("change", event => {
    filteredItems().forEach(item => {
      event.target.checked ? state.selectedIds.add(item.review_id) : state.selectedIds.delete(item.review_id);
    });
    renderList();
  });
  $("#clearSelectionButton").addEventListener("click", () => {
    state.selectedIds.clear();
    renderList();
  });
  $("#bulkDecisionButton").addEventListener("click", openBulkDecision);
  $("#bulkDeleteButton").addEventListener("click", deleteSelectedReviewItems);
  $("#reviewTab").addEventListener("click", () => setSystemMode("review"));
  $("#designTab").addEventListener("click", () => openPlanningSystem(state.planningView));
  $("#refreshPlanningButton").addEventListener("click", async () => {
    state.designFileCache = {};
    $("#refreshPlanningButton").disabled = true;
    try {
      await loadDesignSnapshot(true);
      const path = designPathFromView(state.planningView);
      const available = new Set([
        ...(state.designSnapshot.monitored_files || []).filter(item => item.exists).map(item => item.path),
        ...(state.designSnapshot.workflow_tree?.nodes || []).filter(item => item.kind === "file").map(item => item.path),
      ]);
      if (path && !available.has(path)) {
        const first = (state.designSnapshot.monitored_files || []).find(item => item.exists);
        state.planningView = first ? `file:${first.path}` : "";
        state.planningPresentation = "parsed";
      }
      syncLocation();
      renderPlanningNavigation();
      renderUcagentProgress();
      renderPlanningView();
      const changeCount = Object.keys(state.designChanges).length + state.designDeleted.length;
      toast(changeCount ? `设计监控已刷新，发现 ${changeCount} 项变化` : "设计监控已刷新，没有文件变化");
    } catch (error) {
      toast(error.message, true);
    } finally {
      $("#refreshPlanningButton").disabled = false;
    }
  });
  $("#planningSearchInput").addEventListener("input", event => {
    state.planningSearch = event.target.value;
    renderPlanningNavigation();
  });
  $("#cancelDesignEditsButton").addEventListener("click", cancelDesignDrafts);
  $("#validateDesignEditsButton").addEventListener("click", async () => {
    try { await validateDesignDrafts(true); } catch (error) { toast(error.message, true); }
  });
  $("#saveDesignEditsButton").addEventListener("click", saveDesignDrafts);
  $("#newSuggestionButton").addEventListener("click", () => {
    $("#suggestionError").textContent = "";
    $("#suggestionDialog").showModal();
    iconRefresh();
  });
  $("#saveDecisionButton").addEventListener("click", saveDecision);
  $("#saveBulkDecisionButton").addEventListener("click", saveBulkDecision);
  $("#saveSuggestionButton").addEventListener("click", saveSuggestion);
  $("#saveHistoryButton").addEventListener("click", saveHistoryAction);
  $("#decisionReason").addEventListener("input", event => {
    event.target.dataset.generated = "false";
  });
  $$("#decisionForm input[name=decision]").forEach(node => node.addEventListener("change", () => {
    const reason = $("#decisionReason");
    if (reason.dataset.generated !== "true") return;
    const item = state.data?.items.find(entry => entry.review_id === $("#decisionItemId").value);
    if (item) reason.value = defaultDecisionReason(item, node.value);
  }));
  $("#bulkDecisionReason").addEventListener("input", event => {
    event.target.dataset.generated = "false";
  });
  $$("#bulkDecisionForm input[name=bulkDecision]").forEach(node => node.addEventListener("change", () => {
    const reason = $("#bulkDecisionReason");
    if (reason.dataset.generated === "true") {
      reason.value = bulkDecisionReason(node.value, state.selectedIds.size);
    }
  }));
  loadState(false).then(() => {
    updateDesignDraftToolbar();
    if (requestedTab === "design") {
      openPlanningSystem(state.planningView, false);
    } else {
      setSystemMode("review", false);
    }
  });
  iconRefresh();
});
