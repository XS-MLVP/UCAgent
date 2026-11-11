/** Structured stage presentation shared by the Agent and Master dashboards. */
(function (root) {
  'use strict';

  /** Escape all stage metadata before inserting it into either dashboard. */
  function escape(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
  }

  /** Use the live flag when available, or the saved mission cursor. */
  function isCurrent(stage, currentIndex) {
    return typeof stage.is_current === 'boolean'
      ? stage.is_current : Number.isInteger(stage.index) && stage.index === currentIndex;
  }

  /** A skip counts as processed when the execution cursor has passed the stage. */
  function skipProcessed(stage, currentIndex, allCompleted) {
    return stage.is_skipped && (allCompleted || stage.is_completed || stage.index < currentIndex);
  }

  /** Split the section and display name, including titles in saved workspace records. */
  function stageTitle(stage) {
    const title = String(stage.title || '');
    const numberedTitle = /^(\d+(?:\.\d+)*)-([A-Za-z0-9_]+)-([\s\S]+)$/.exec(title);
    const section = stage.section_index || numberedTitle?.[1] || String(stage.index ?? '');
    const identity = [stage.section_index, stage.stage_name].filter(Boolean).join('-');
    const description = identity && title.startsWith(identity + '-')
      ? title.slice(identity.length + 1) : numberedTitle?.[3] || title;
    const batch = /\[(\d+)\/(\d+)(?:\|[^\]]*)?\]\s*$/.exec(description);
    const label = description.replace(/\s*\[(?:\d+|-)(?:\/(?:\d+|-))?(?:\|[^\]]*)?\]\s*$/, '').trim() || description;
    return {section, label, batch: batch && Number(batch[2]) > 0 ? batch : null};
  }

  /** Describe stage state consistently in the workflow and the stage dialog. */
  function stageStatus(stage, currentIndex, allCompleted, waitingForReview) {
    const current = isCurrent(stage, currentIndex);
    const state = stage.is_skipped ? 'skipped' : current ? 'current'
      : stage.is_completed ? 'completed' : 'pending';
    const label = {skipped: skipProcessed(stage, currentIndex, allCompleted) ? 'Skipped' : 'Scheduled to skip',
      current: waitingForReview ? 'Awaiting review' : 'Current', completed: 'Completed',
      pending: stage.reached ? 'Incomplete' : 'Pending'}[state];
    const marker = {skipped: '–', current: waitingForReview ? '!' : '▸', completed: '✓', pending: '○'}[state];
    return {current, state, label, marker};
  }

  /** Render compact stage metadata with the full title available on hover and focus. */
  function renderStage(stage, currentIndex, allCompleted, waitingForReview) {
    const {current, state, label, marker} = stageStatus(stage, currentIndex, allCompleted, waitingForReview);
    const {section, label: name, batch} = stageTitle(stage);
    const skills = Array.isArray(stage.skill_list) ? stage.skill_list : Object.keys(stage.skill_list || {});
    const flags = [stage.needs_human_check && 'HM', stage.need_fail_llm_suggestion && 'LF',
      stage.need_pass_llm_suggestion && 'LP'].filter(Boolean);
    const failureLabel = stage.fail_count > 0 ? `${stage.fail_count} failed checks` : '';
    const metadata = [stage.title, label, failureLabel, stage.time_cost,
      skills.length && `Skills: ${skills.join(', ')}`, flags.join(' ')].filter(Boolean).join(' · ');
    const batchLabel = current && batch
      ? `${batch[1]}/${batch[2]} · ${Math.floor(Math.min(1, Number(batch[1]) / Number(batch[2])) * 100)}%`
      : '';
    return `<span class="uc-stage uc-stage-${state}" title="${escape(metadata)}">`
      + `<span class="uc-stage-marker" role="img" aria-label="${label}">${marker}</span>`
      + `<span class="uc-stage-number">${escape(section)}</span>`
      + `<span class="uc-stage-name">${escape(name)}</span>`
      + (batchLabel ? `<span class="uc-stage-batch">${batchLabel}</span>` : '')
      + (failureLabel ? `<span class="uc-stage-fails" aria-label="${failureLabel}">!${Number(stage.fail_count)}</span>` : '')
      + (flags.length ? `<span class="uc-stage-flags">${flags.join(' ')}</span>` : '')
      + (stage.time_cost ? `<span class="uc-stage-time">${escape(stage.time_cost)}</span>` : '') + '</span>';
  }

  /** Count completed stages and skips that have actually been processed. */
  function summarize(stages, currentIndex, allCompleted) {
    const total = stages.length;
    let completed = 0;
    let skipped = 0;
    stages.forEach((stage, index) => {
      if (stage.is_skipped) {
        if (skipProcessed({...stage, index: stage.index ?? index}, currentIndex, allCompleted)) skipped++;
      } else if (stage.is_completed) completed++;
    });
    return {total, completed, skipped, percent: total ? Math.floor((completed + skipped) / total * 100) : null,
      label: `${completed}/${total} completed${skipped ? ` · ${skipped} skipped` : ''}`};
  }

  /** Use workflow labels when provided, and group other workflows by adjacent sections. */
  function groupStages(stages) {
    const groups = [];
    let lastSection;
    let sectionCount = 0;
    for (const stage of stages) {
      const section = stageTitle(stage).section.split('.')[0];
      const group = groups[groups.length - 1];
      const name = stage.display_group || '';
      const startsSection = section !== lastSection;
      if (!group || name !== group.name || (!name && startsSection && sectionCount >= 5)) {
        groups.push({key: stage.index, name, first: section, last: section, stages: []});
        sectionCount = 0;
      }
      const currentGroup = groups[groups.length - 1];
      currentGroup.last = section;
      currentGroup.stages.push(stage);
      if (startsSection) sectionCount++;
      lastSection = section;
    }
    return groups;
  }

  /** Render one disclosure in execution order, with a resolved-stage count. */
  function renderGroup(group, currentIndex, allCompleted, open, rows) {
    const {completed, skipped, total} = summarize(group.stages, currentIndex, allCompleted);
    const name = group.name || (group.first === group.last ? `Stage ${group.first}` : `Stages ${group.first}–${group.last}`);
    return `<details class="uc-stage-group" data-stage-group="${escape(group.key)}"${open ? ' open' : ''}>`
      + `<summary title="${escape(name)}"><span class="uc-stage-group-name">${escape(name)}</span>`
      + `<span class="uc-stage-group-count" title="${completed} completed · ${skipped} skipped">${completed + skipped}/${total}</span></summary>`
      + `<div class="uc-stage-group-items">${rows}</div></details>`;
  }

  /** Count completion and skip flags; legacy snapshots without flags remain unknown. */
  function progress(agent) {
    const rows = agent.task_list?.task_list?.stage_list;
    const stages = Array.isArray(rows) ? rows : [];
    const total = stages.length || Math.max(0, Number(agent.total_stage_count) || 0);
    const known = stages.length > 0 && stages.every(stage =>
      typeof stage.is_completed === 'boolean' || stage.is_skipped === true);
    if (!known) {
      return {total, percent: total && agent.is_mission_complete ? 100 : null,
        label: !total ? '—' : agent.is_mission_complete ? 'Complete (stage counts unavailable)' : 'Completion unavailable'};
    }
    return summarize(stages, agent.current_stage_index, agent.is_mission_complete);
  }

  root.UCAgentStageView = {escape, isCurrent, stageTitle, stageStatus, renderStage, groupStages, renderGroup, summarize, progress};
})(globalThis);
