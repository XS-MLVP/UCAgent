"""Select one {{DUT}} backend while preserving a single UT suite."""

from pathlib import Path

import pytest
from design_with_ppa import (
    get_performance_waveform_path,
    managed_test_implementation,
    normalize_line_coverage_source_paths,
    register_managed_test_options,
)
from toffee_test.reporter import (
    get_file_in_tmp_dir,
    set_func_coverage,
    set_line_coverage,
)

from {{DUT}}_adapter import create_adapter
from {{DUT}}_function_coverage_def import get_coverage_groups


def pytest_configure(config):
    """Register workflow-owned markers without changing the pytest root directory."""

    config.addinivalue_line(
        "markers",
        "performance: deterministic simulation performance case that emits PPA evidence",
    )


def pytest_addoption(parser):
    """Register the workflow-owned backend selector."""

    register_managed_test_options(parser)


@pytest.fixture
def env(request):
    """Create, instrument, reset, and release one backend-neutral environment."""

    backend = managed_test_implementation(request.config)
    adapter = create_adapter(backend)
    # Coverage predicates consume the normalized environment, never the
    # backend-specific DUT object.  This keeps reference and RTL timing
    # differences inside the adapter.
    groups = get_coverage_groups(adapter)
    adapter.bind_coverage(groups)
    coverage_path = None
    if backend == "rtl":
        data_dir = Path(__file__).resolve().parent / "data"
        coverage_path = get_file_in_tmp_dir(
            request,
            str(data_dir),
            f"{request.node.name}.dat",
            new_path=True,
        )
        if request.node.get_closest_marker("performance") is not None:
            waveform_path = get_performance_waveform_path(request, extension="vcd")
        else:
            waveform_path = get_file_in_tmp_dir(
                request,
                str(data_dir),
                f"{request.node.name}.vcd",
                new_path=True,
            )
        # Both artifact paths must be bound before reset or the first Step.
        adapter.configure_test_artifacts(coverage_path, waveform_path)
    adapter.reset()
    yield adapter
    try:
        # Performance tests flush immediately before writing their sidecar.
        # Ordinary functional tests let Finish close the native trace; an
        # unconditional extra flush can crash some native RTL runtimes.
        if request.node.get_closest_marker("performance") is not None:
            adapter.flush_waveform()
        set_func_coverage(request, groups)
    finally:
        # Finish writes the native coverage file.  Register it with Toffee only
        # after the backend has closed the file, matching ToffeeRequest.finish.
        adapter.finish()
        if coverage_path is not None:
            # The native runtime records the ephemeral staging directory of the
            # managed build; point those entries at the installed sources so the
            # report renderer can open every recorded file.
            normalize_line_coverage_source_paths(coverage_path)
            set_line_coverage(
                request,
                coverage_path,
                ignore=str(Path(__file__).resolve().parent / "{{DUT}}.ignore"),
            )
