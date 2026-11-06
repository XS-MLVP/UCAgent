"""Stage-bound review commands for authenticated Swarm integrations."""

import hashlib
import json
import threading
import uuid
from collections import OrderedDict

_INIT_LOCK = threading.Lock()


def _state(pdb):
    """Create one process-local epoch; restarts invalidate old approvals."""
    with _INIT_LOCK:
        if not hasattr(pdb, '_swarm_review'):
            pdb._swarm_review = {'epoch': uuid.uuid4().hex, 'revision': 0,
                                 'receipts': OrderedDict(), 'lock': threading.RLock()}
        return pdb._swarm_review


def snapshot(pdb):
    """Return actual stage evidence and an opaque approval precondition."""
    state = _state(pdb)
    with state['lock']:
        mission = pdb.api_mission_info(return_dict=True)
        stage = pdb.agent.stage_manager.get_current_stage()
        waiting = bool(stage and not stage.is_completed() and stage.is_wait_human_check()
                       and stage.check_pass and getattr(pdb.agent, '_need_human', False))
        evidence = json.dumps({'index': mission['current_index'],
                               'checks': stage.check_info if stage else None,
                               'human': stage.get_hmcheck_state() if stage else None},
                              sort_keys=True, default=str)
        # Outcomes change during execution, so a decision cannot approve unseen work.
        token = hashlib.sha256(f"{state['epoch']}:{state['revision']}:{waiting}:{evidence}".encode()).hexdigest()
        return {'mission': mission, 'waiting_for_review': waiting,
                'review_token': token, 'receipts': list(state['receipts'].values())}


def apply(pdb, request):
    """Validate again on the PDB queue, then apply at most once per epoch."""
    if not isinstance(request, dict):
        raise ValueError('review request must be an object')
    state = _state(pdb)
    with state['lock']:
        operation = request.get('operation_id', '')
        if not isinstance(operation, str) or not operation or len(operation) > 128:
            raise ValueError('invalid operation_id')
        digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        prior = state['receipts'].get(operation)
        if prior:
            if prior['request_sha256'] != digest:
                raise ValueError('operation_id conflict')
            return prior
        current = snapshot(pdb)
        index = request.get('stage_index')
        if (type(index) is not int or index != current['mission']['current_index']
                or request.get('review_token') != current['review_token']):
            raise ValueError('stale review; refresh the current stage')
        action = request.get('action')
        feedback = request.get('feedback', '')
        if not isinstance(feedback, str) or len(feedback) > 16000:
            raise ValueError('invalid feedback')
        if action not in ('enable_hm', 'continue', 'feedback'):
            raise ValueError('invalid review action')
        if action != 'enable_hm' and not current['waiting_for_review']:
            raise ValueError('stage is not ready for human review')
        if action == 'feedback' and not feedback.strip():
            raise ValueError('feedback is required')
        receipt = {'operation_id': operation, 'request_sha256': digest,
                   'stage_index': index, 'action': action, 'status': 'accepted'}
        state['receipts'][operation] = receipt
        state['revision'] += 1
        # Eviction also changes the epoch: an evicted command cannot be replayed.
        if len(state['receipts']) > 100:
            state['receipts'].popitem(last=False)
            state['epoch'] = uuid.uuid4().hex
        stage = pdb.agent.stage_manager.get_current_stage()
        try:
            if action == 'enable_hm':
                pdb.api_update_stage_flags([index], hmcheck_needed=True)
            elif action == 'continue':
                stage.do_hmcheck_pass(feedback)
            else:
                stage.do_hmcheck_fail(feedback)
                stage.check_pass = False
            receipt['status'] = 'applied'
        except Exception:
            receipt['status'] = 'failed'
            raise
    if action != 'enable_hm':
        prompt = ('Human review passed; complete this stage and continue. '
                  if action == 'continue' else 'Address human review feedback in this stage: ')
        pdb.do_loop(prompt + feedback)
    return receipt


def reject(pdb, request, reason):
    """Expose queue-time rejection without changing an existing operation receipt."""
    state = _state(pdb)
    operation = request.get('operation_id') if isinstance(request, dict) else None
    if not isinstance(operation, str) or not operation or len(operation) > 128:
        return
    with state['lock']:
        if operation in state['receipts']:
            return
        state['receipts'][operation] = {'operation_id': operation,
            'request_sha256': hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
            'stage_index': request.get('stage_index'), 'action': request.get('action'),
            'status': 'rejected', 'reason': reason}
        if len(state['receipts']) > 100:
            state['receipts'].popitem(last=False)
            state['epoch'] = uuid.uuid4().hex
