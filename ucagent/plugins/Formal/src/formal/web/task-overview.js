/** Render the Formal task overview from the live or saved workspace records. */

/** Format wall-clock duration without wrapping long runs at 24 hours. */
function duration(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  return [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60]
    .map(value => String(value).padStart(2, '0')).join(':');
}

/** Translate only states reported by the mission or runtime. */
function statusLabel(mission, runtime, archived) {
  if (mission.all_completed || runtime?.task_outcome === 'completed') return ['已完成', 'done'];
  if (archived) return ['归档任务', ''];
  if (runtime === null) return ['连接中断', 'failed'];
  if (runtime?.instance === 'failed' || runtime?.execution === 'failed') return ['执行失败', 'failed'];
  if (runtime?.instance === 'closed') return ['已结束', ''];
  if (mission.is_waiting_for_review || runtime?.execution === 'waiting_human') return ['待人工 Check', 'waiting'];
  const initial = runtime?.operations?.findLast(operation => operation.command === 'initial_commands');
  if (['queued', 'running'].includes(initial?.state)) return ['初始化工作区', ''];
  if (initial?.state === 'failed') return ['初始化失败', 'failed'];
  const labels = {running: ['运行中', 'running'], pausing: ['正在暂停', 'waiting'],
    paused: ['已暂停', 'waiting'], idle: ['等待运行', '']};
  return labels[runtime?.execution] ?? ['正在连接任务', ''];
}

/** Mount the overview and keep links stable as polling refreshes the clocks. */
export function mountTaskOverview(node, {openWorkflow, openReview, openActivity, openFile}) {
  const field = name => node.querySelector('[data-' + name + ']');
  const progress = field('task-progress');
  const review = field('stage-review');
  const activityList = field('task-activity');
  const artifactList = field('task-artifacts');
  const stagePanel = node.querySelector('.fc-task-stage');
  const stageTitle = node.querySelector('#fc-current-stage');
  const title = node.querySelector('#fc-task-title');
  const timeFormat = new Intl.DateTimeFormat(undefined, {hour: '2-digit', minute: '2-digit', second: '2-digit'});
  progress.addEventListener('click', openWorkflow);
  review.addEventListener('click', openReview);

  /** Create a row whose source can be inspected in the existing pane. */
  function addLink(list, label, action, epoch) {
    const row = document.createElement('div');
    const link = document.createElement('button');
    link.type = 'button';
    link.textContent = label;
    link.addEventListener('click', action);
    if (Number.isFinite(epoch)) {
      const time = document.createElement('time');
      const date = new Date(epoch * 1000);
      time.textContent = timeFormat.format(date);
      time.dateTime = date.toISOString();
      row.append(time);
    }
    row.append(link);
    list.append(row);
  }

  /** Render the current task, its active stage and the links available in this workspace. */
  function update({mission, runtime, view, archived, summary, stage, stageName, objective, activity}) {
    const now = Date.now() / 1000;
    const task = mission.task ?? {};
    const backendLabels = {claude: 'Claude Code', codex: 'Codex', opencode: 'OpenCode', blank: '未启用'};
    const status = field('task-status');
    const [label, tone] = statusLabel(mission, runtime, archived);
    if (status.textContent !== label) status.textContent = label;
    status.dataset.tone = tone;
    title.textContent = mission.mission_name || '形式化验证任务';
    progress.hidden = !summary.total;
    progress.textContent = '已完成 ' + summary.completed + ' / ' + summary.total
      + ' 个阶段' + (summary.skipped ? ' · 已跳过 ' + summary.skipped : '');
    const end = task.finished_at ?? (archived ? null : now);
    field('task-module').textContent = task.module || view?.dut || '—';
    field('task-backend').textContent = (Object.hasOwn(backendLabels, task.agent_backend)
      ? backendLabels[task.agent_backend] : task.agent_backend) || '—';
    field('task-solver').textContent = view?.solver || '—';
    field('task-elapsed').textContent = Number.isFinite(task.started_at) && Number.isFinite(end)
      ? duration(end - task.started_at) : '—';

    const recent = activity.filter(event => !stage?.started_at || event.time >= stage.started_at).slice(0, 3);
    stagePanel.hidden = !stage;
    if (stage) {
      field('stage-number').textContent = '当前阶段 · ' + (mission.stages.indexOf(stage) + 1);
      stageTitle.textContent = stageName;
      field('stage-elapsed').textContent = stage.time_cost ? '阶段用时 ' + stage.time_cost : '';
      field('stage-last-activity').textContent = recent.length
        ? '距最近活动 ' + duration(now - recent[0].time) : '';
      const goal = field('stage-objective');
      if (goal.dataset.objective !== objective) {
        goal.dataset.objective = objective;
        goal.replaceChildren(...objective.split(/(`[^`]+`)/).map(part => {
          if (!part.startsWith('`') || !part.endsWith('`') || part.length < 3) return part;
          const code = document.createElement('code');
          code.textContent = part.slice(1, -1);
          return code;
        }));
      }
      review.hidden = !mission.is_waiting_for_review;
    }

    const activityKey = JSON.stringify([archived, recent.map(event => [event.generation, event.id])]);
    if (activityList.dataset.key !== activityKey) {
      activityList.dataset.key = activityKey;
      activityList.replaceChildren();
      for (const event of recent) addLink(activityList, event.label, () => openActivity(event), event.time);
      if (!recent.length) activityList.textContent = archived ? '此工作区没有保存活动记录。' : '暂无工具活动。';
    }

    const files = (view?.reports ?? [])
      .filter(file => !file.template_only && (file.path !== view.run?.report || view.freshness !== 'historical'))
      .sort((a, b) => (b.modified_at ?? 0) - (a.modified_at ?? 0)).slice(0, 3);
    const artifactKey = JSON.stringify(files);
    if (artifactList.dataset.key !== artifactKey) {
      artifactList.dataset.key = artifactKey;
      artifactList.replaceChildren();
      for (const file of files) addLink(artifactList, file.name, () => openFile(file.path), file.modified_at);
      if (!files.length) artifactList.textContent = '暂无可预览产物。';
    }
  }

  return {update, focus: () => title.focus({preventScroll: true})};
}
