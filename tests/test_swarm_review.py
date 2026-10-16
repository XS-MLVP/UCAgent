"""Regression tests for queue-time stage review guards without model dependencies."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('swarm_review', Path(__file__).parents[1] / 'ucagent/swarm_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class ReviewTests(unittest.TestCase):
    """Use only the public stage behavior needed by the review protocol."""
    def setUp(self):
        """Build a stage whose checker passed and is awaiting human review."""
        self.stage = SimpleNamespace(check_pass=True, check_info=[{'passed': True}], human=None, needed=True)
        self.stage.is_completed = lambda: False
        self.stage.is_wait_human_check = lambda: self.stage.needed and self.stage.human is not True
        self.stage.get_hmcheck_state = lambda: (self.stage.human, '')
        self.stage.do_hmcheck_pass = lambda text: setattr(self.stage, 'human', True)
        self.stage.do_hmcheck_fail = lambda text: setattr(self.stage, 'human', False)
        self.manager = SimpleNamespace(stage_index=2, get_current_stage=lambda: self.stage)
        self.loops = []
        self.pdb = SimpleNamespace(agent=SimpleNamespace(stage_manager=self.manager), do_loop=self.loops.append)
        self.pdb.api_mission_info = lambda return_dict: {'current_index': self.manager.stage_index, 'stages': []}
        self.pdb.api_update_stage_flags = lambda indices, hmcheck_needed: setattr(self.stage, 'needed', hmcheck_needed)

    def command(self, action='continue', feedback=''):
        """Capture a decision against the currently visible stage epoch."""
        return {'operation_id': 'op', 'stage_index': 2, 'action': action, 'feedback': feedback,
                'review_token': review.snapshot(self.pdb)['review_token']}

    def test_duplicate_approval_is_applied_once(self):
        """Retrying the same operation cannot advance a second stage."""
        command = self.command()
        self.assertEqual(review.apply(self.pdb, command)['status'], 'applied')
        self.manager.stage_index = 3
        review.apply(self.pdb, command)
        self.assertEqual(len(self.loops), 1)

    def test_delayed_approval_and_changed_evidence_are_rejected(self):
        """Revalidate stage and check evidence at actual command execution."""
        command = self.command()
        self.manager.stage_index = 3
        with self.assertRaises(ValueError): review.apply(self.pdb, command)
        self.manager.stage_index = 2
        self.stage.check_info.append({'new': 'check'})
        with self.assertRaises(ValueError): review.apply(self.pdb, command)
        self.assertFalse(self.loops)

    def test_feedback_rechecks_and_does_not_pass_human_review(self):
        """Feedback stays in this stage and requires a fresh successful check."""
        review.apply(self.pdb, self.command('feedback', 'Correct the assertion'))
        self.assertFalse(self.stage.human)
        self.assertFalse(self.stage.check_pass)
        self.assertIn('Correct the assertion', self.loops[0])
        self.assertFalse(review.snapshot(self.pdb)['waiting_for_review'])

    def test_unchecked_stage_and_empty_feedback_are_rejected(self):
        """HM requirement alone is not evidence that the stage is ready."""
        with self.assertRaises(ValueError): review.apply(self.pdb, self.command('feedback'))
        self.stage.check_pass = False
        with self.assertRaises(ValueError): review.apply(self.pdb, self.command())
        self.assertFalse(self.loops)

    def test_restart_epoch_and_operation_conflict(self):
        """Restarted runtimes and changed operation payloads invalidate approvals."""
        command = self.command()
        del self.pdb._swarm_review
        with self.assertRaises(ValueError): review.apply(self.pdb, command)
        command = self.command('enable_hm')
        review.apply(self.pdb, command)
        command['feedback'] = 'changed'
        with self.assertRaises(ValueError): review.apply(self.pdb, command)


if __name__ == '__main__':
    unittest.main()
