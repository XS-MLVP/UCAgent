"""Deterministic simulation-time performance tests for {{DUT}}."""

import pytest

from design_with_ppa import write_performance_result


@pytest.mark.performance
def test_{{DUT}}_performance_latency(env, request):
    """Measure one Spec latency metric with deterministic stimulus."""

    # The fixture binds env.waveform_path before reset and the first Step.
    # Compute and assert the metric in both backends. Only the RTL branch
    # flushes the real waveform and writes its sidecar.
    if env.backend == "rtl":
        env.flush_waveform()
        assert env.waveform_path is not None
        write_performance_result(request, {}, env.waveform_path, {})
    assert False, "Not implemented"


@pytest.mark.performance
def test_{{DUT}}_performance_throughput(env, request):
    """Measure one sustained Spec throughput metric with a fixed window."""

    if env.backend == "rtl":
        env.flush_waveform()
        assert env.waveform_path is not None
        write_performance_result(request, {}, env.waveform_path, {})
    assert False, "Not implemented"
