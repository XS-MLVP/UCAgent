"""Declare the independent UT workflow and resolve its document input mode."""

from pathlib import Path

from ucagent.core.plugins import Plugin, PluginWorkflow

from . import __version__
from .adoption import ToffeeUTAdoptionChecker, stage_catalog, validate_task_selection
from .checkers import ToffeeUTBatchChecker, ToffeeUTChecker
from .handoff import ToffeeUTHandoff
from .paths import local_path
from .project import inspect_inputs
from .tools import RunToffee, create_tools


def prepare_workflow(cfg, context):
    """Resolve input routing before stage construction without writing any project files."""
    mode = cfg.get_value("runtime_options.ut_document_mode", "auto")
    documents = cfg.get_value("runtime_options.ut_documents", None)
    rtl_dirs = cfg.get_value("runtime_options.ut_rtl_dirs", None)
    for key, value in (("ut_documents", documents), ("ut_rtl_dirs", rtl_dirs)):
        if value is not None and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            raise ValueError(f"runtime_options.{key} must be null or a list of workspace-relative paths")
    for key, default in (("ut_workers", 1), ("ut_timeout", 1200)):
        value = cfg.get_value(f"runtime_options.{key}", default)
        if type(value) is not int or value < 1:
            raise ValueError(f"runtime_options.{key} must be a positive integer")
        if key == "ut_timeout" and value > 3600:
            raise ValueError("runtime_options.ut_timeout must not exceed 3600 seconds")
    optional = {}
    for key in ("ut_reference_model", "ut_mock_components", "ut_line_coverage",
                "ut_human_env_spec_review", "ut_human_env_review"):
        value = cfg.get_value(f"runtime_options.{key}", key == "ut_line_coverage")
        if type(value) is not bool:
            raise ValueError(f"runtime_options.{key} must be true or false")
        optional[key] = value
    native = cfg.get_value("runtime_options.ut_dut_package", None)
    if native is not None and not isinstance(native, str):
        raise ValueError("runtime_options.ut_dut_package must be null or a relative path")
    task = cfg.get_value("runtime_options.ut_task", "")
    selected = validate_task_selection(task, cfg.get_value("runtime_options.ut_task_stages", None),
                                       stage_catalog([stage.as_dict() for stage in cfg.stage]))
    inventory = inspect_inputs(context["WORKSPACE"], context["DUT"], context["OUT"], documents, rtl_dirs, mode)
    cfg.un_freeze()
    cfg.set_value("runtime_options.ut_document_mode", inventory["document_mode"])
    cfg.set_value("runtime_options.ut_documents", list(inventory["documents"]))
    optional_stages = {
        "reference_model_implementation": "ut_reference_model",
        "reference_model_fixture_imp": "ut_reference_model",
        "line_coverage_analysis_and_improvement": "ut_line_coverage",
        "mock_design_and_implementation": "ut_mock_components",
        "mock_fixture_implementation": "ut_mock_components",
        "mock_functional_test": "ut_mock_components",
        "test_mock_components_in_batch": "ut_mock_components",
        "human_check_env_specification": "ut_human_env_spec_review",
        "human_check_env_implementation": "ut_human_env_review",
    }
    def configure_optional_stages(stages):
        """Set only explicitly optional original stages without changing their order."""
        for stage in stages:
            if stage.name in optional_stages:
                stage.skip = not optional[optional_stages[stage.name]]
            if stage.has_attr("stage"):
                configure_optional_stages(stage.stage)
    configure_optional_stages(cfg.stage)
    if not inventory["documents"]:
        specification = next(stage for stage in cfg.stage if stage.name == "functional_specification_analysis")
        mapping = next(stage for stage in specification.stage if stage.name == "functional_line_mapping_gap_analysis")
        # Keep the stage visible but never claim to have mapped non-existent input lines.
        mapping.skip = True
        specification.checker[0].args.phase = "checkpoints"
    if selected is not None:
        unavailable = set()

        def find_unavailable(stages, parent_skipped=False):
            """Respect optional configuration rather than enabling hidden dependencies."""
            for stage in stages:
                skipped = parent_skipped or stage.get_value("skip", False) or stage.get_value("ignore", False)
                if skipped:
                    unavailable.add(stage.name)
                find_unavailable(stage.get_value("stage", []), skipped)

        find_unavailable(cfg.stage)
        disabled = sorted(set(selected) & unavailable)
        if disabled:
            raise ValueError(f"Selected task stages are disabled or inapplicable: {disabled}; confirm their configuration first")

        def scope_stages(stages, include_children=False):
            """Select any requested node; keep unselected ancestors as containers only."""
            active = False
            for stage in stages:
                include = include_children or stage.name in selected
                children = scope_stages(stage.get_value("stage", []), include)
                enabled = stage.name not in unavailable and (include or children)
                if enabled and not include:
                    # A selected child does not authorize its parent's aggregate
                    # acceptance work or unrelated siblings.
                    stage.checker, stage.output_files, stage.reference_files, stage.skill_list = [], [], [], []
                    stage.task = ["Execute only the explicitly selected child stages; this container does not authorize aggregate acceptance or unrelated work."]
                stage.skip = not enabled
                active = active or enabled
            return active

        scope_stages(cfg.stage)
    # Both document modes traverse the full verification lifecycle. Inferred
    # behavior stays unconfirmed; neither path silently skips a review stage.
    if Path(context["OUT"]).as_posix() == "." and cfg.get_value("write_dirs") == ["."]:
        cfg.set_value("write_dirs", ["testbenches", "tools", "docs", "dut", "results", "__init__.py",
                                     "conftest.py", "pytest.ini", "README.md", "workspace.json", "requirements.txt"])
    cfg.freeze()
    return {"TB": inventory["testbench"], "DOCUMENT_MODE": inventory["document_mode"],
            "UT_TASK": task or "Complete the configured verification workflow",
            "UT_TASK_SCOPE": "full configured scope" if selected is None else ", ".join(selected),
            "DESIGN_SPEC": (Path(context["OUT"]) / inventory["design_spec"]).as_posix(),
            "VERIFICATION_SPEC": (Path(context["OUT"]) / inventory["verification_spec"]).as_posix()}


def prepare_adoption(cfg, context):
    """Prepare a read-only project handoff without scaffolding or changing verification inputs."""
    root = local_path(context["WORKSPACE"], context["OUT"], allow_root=True)
    if not root.is_dir():
        raise ValueError("Task adoption needs an existing project; select its path with --output")
    catalog = stage_catalog()
    task = cfg.get_value("runtime_options.ut_task", "")
    validate_task_selection(task, cfg.get_value("runtime_options.ut_task_stages", None), catalog)
    report = local_path(context["WORKSPACE"],
                        (Path(context["OUT"]) / f"docs/reviews/{context['DUT']}-adoption.md").as_posix())
    return {"UT_TASK": task or "Clarify the current user request; do not assume full-DUT acceptance",
            "ADOPTION_REPORT": report.relative_to(Path(context["WORKSPACE"]).resolve()).as_posix(),
            "UT_STAGE_CATALOG": "\n".join(f"{name}: {row['description']}" for name, row in catalog.items())}


def get_plugin():
    """Expose tools, method resources and phase checkers without importing UnitTest."""
    root = Path(__file__).resolve().parent
    return Plugin(
        name="toffee-ut", version=__version__, root=root,
        requires_ucagent=">=26.9.2.dev14",
        python_requirements=("uc-toffee", "wavekit", "PyYAML>=6,<7", "Jinja2>=3.1.6,<4"),
        description="Toffee 2 UT projects with document-aware preparation and deterministic automation",
        tool_factories=(create_tools,), manager_tools=(RunToffee,),
        runtime_hooks=(ToffeeUTHandoff,),
        checkers=(ToffeeUTChecker, ToffeeUTBatchChecker, ToffeeUTAdoptionChecker),
        workflows=(PluginWorkflow(
            name="ut", config_file=root / "workflows/ut.yaml",
            guide_doc_paths=(root / "Guide_Doc",), skill_paths=(root / "skills",),
            template_context_factory=prepare_workflow,
        ), PluginWorkflow(
            name="adopt", config_file=root / "workflows/adopt.yaml",
            guide_doc_paths=(root / "Guide_Doc",), skill_paths=(root / "skills",),
            template_context_factory=prepare_adoption,
        )),
    )
