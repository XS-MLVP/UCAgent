"""DesignWithPPA public package with dependency-isolated lazy exports."""

from importlib import import_module
from typing import Any


_EXPORT_GROUPS = {
    "performance": (
        "get_performance_waveform_path",
        "measure_cycle_latency",
        "measure_latency",
        "measure_throughput",
        "write_performance_result",
    ),
    "ppa": (
        "AnalyzePPA",
        "AnalyzePPAArgs",
        "compare_ppa_reports",
    ),
    "consistency": (
        "RunDesignConsistency",
        "RunDesignConsistencyArgs",
    ),
    "python_dut": (
        "PinSpec",
        "PythonDUTError",
        "ReferenceDUT",
        "ReferencePin",
        "ReferenceXPort",
        "create_dut",
        "managed_test_implementation",
        "prepare_native_artifact_path",
        "register_managed_test_options",
    ),
    "rtl": (
        "CHISEL_MILL_VERSION",
        "CHISEL_SCALA_VERSION",
        "CHISEL_VERSION",
        "ChiselLanguageBackend",
        "PreparedRTL",
        "RTLPreparationRequest",
        "RTLSourceTemplate",
        "RTLSourceValidation",
        "RTLLanguageBackend",
        "RTLLanguageError",
        "ResolvedRTLConfig",
        "available_rtl_languages",
        "build_rtl_template_context",
        "discover_rtl_libraries",
        "register_rtl_language",
        "resolve_rtl_config",
        "unregister_rtl_language",
    ),
}
_EXPORTS = {
    name: module_name
    for module_name, names in _EXPORT_GROUPS.items()
    for name in names
}

__all__ = sorted(_EXPORTS)
__version__ = "0.4.7"


def __getattr__(name: str) -> Any:
    """Load the implementation module only when its public symbol is requested."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy public exports to introspection tools."""

    return sorted(set(globals()) | set(__all__))
