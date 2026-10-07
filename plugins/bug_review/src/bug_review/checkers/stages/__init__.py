"""Stage-local Bug Review checks executed in workflow order."""

from . import full_replay, case_triage, dut_evidence, report_reconcile, root_correlation, publish

CHECKS = (full_replay.check, case_triage.check, dut_evidence.check,
          report_reconcile.check, root_correlation.check, publish.check)
