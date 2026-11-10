/** Structured stage presentation shared by the Agent and Master dashboards. */
(function (root) {
  'use strict';

  /** Escape all stage metadata before inserting it into either dashboard. */
  function escape(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
  }

  /** Render explicit stage state without inferring completion from its index. */
  function renderStage(stage, currentIndex) {
    const current = typeof stage.is_current === 'boolean'
      ? stage.is_current : Number.isInteger(stage.index) && stage.index === currentIndex;
    const state = stage.is_skipped ? 'skipped' : current ? 'current'
      : stage.is_completed ? 'completed' : 'pending';
    const label = {skipped: 'Skipped', current: 'Current', completed: 'Completed',
      pending: stage.reached ? 'Incomplete' : 'Pending'}[state];
    const index = Number.isInteger(stage.index) ? stage.index : '?';
    const metadata = [];
    if (stage.fail_count !== undefined) metadata.push(`${stage.fail_count} fails`);
    if (stage.time_cost) metadata.push(stage.time_cost);
    const skills = Array.isArray(stage.skill_list) ? stage.skill_list : Object.keys(stage.skill_list || {});
    if (skills.length) metadata.push(`Skills: ${skills.join(', ')}`);
    const flags = [stage.needs_human_check && 'HM', stage.need_fail_llm_suggestion && 'LF',
      stage.need_pass_llm_suggestion && 'LP'].filter(Boolean);
    return `<span class="uc-stage uc-stage-${state}">${index} ${escape(stage.title)} `
      + `<span class="uc-stage-status">[${label}]</span>`
      + (metadata.length ? ` (${escape(metadata.join(', '))})` : '')
      + (flags.length ? ` <span class="uc-stage-flags">[${flags.join(' ')}]</span>` : '') + '</span>';
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
    // A skipped stage is resolved, but must never be counted as validated completion.
    const skipped = stages.filter(stage => stage.is_skipped).length;
    const completed = stages.filter(stage => stage.is_completed && !stage.is_skipped).length;
    return {total, completed, skipped, percent: Math.floor((completed + skipped) / total * 100),
      label: `${completed}/${total} completed${skipped ? ` · ${skipped} skipped` : ''}`};
  }

  root.UCAgentStageView = {renderStage, progress};
})(globalThis);
