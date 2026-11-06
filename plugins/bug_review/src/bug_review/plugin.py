"""Register claim-focused review and synchronize the optional native stage switch."""

from pathlib import Path
from ucagent.plugins import Plugin, PluginWorkflow
from . import __version__
from .core.layout import resolved_options
from .checkers.analysis import BugReviewStageChecker
from .tools import (PrepareReviewInputs, SubmitReviewClaims, CollectReviewCases, CaptureReplayReport,
                    UpdateCaseAnalysis, SubmitReviewDecisions, ReviewContext, ReviewWorkQueue,
                    ReviewRefCheck, RenderBugReviewReport, ApplyReceiptToCase, ApplyWaveformEvent,
                    SetWaveformReviewNote, ReviewSignalCatalog)


def configure_workflow(cfg, context):
    """Derive the native skip flag and available tools from resolved runtime booleans."""
    options = resolved_options(cfg)
    cfg.un_freeze()
    for stage in cfg.stage:
        if stage.name == 'waveform_review':
            stage.set_value('skip', not options.waveform_enabled)
    ignored = list(cfg.get_value('tools.ignore_tools', []))
    if not options.waveform_enabled:
        ignored = list(dict.fromkeys([*ignored, 'WaveInfo', 'WaveInfoReceipts']))
    cfg.set_value('tools.ignore_tools', ignored)
    cfg.freeze()
    return {}


def create_tools(context):
    """Expose direct record tools and omit waveform tools when disabled."""
    options = resolved_options(context.cfg)
    shared = dict(workspace=str(context.workspace), output_dir=context.output_dir,
                  module=context.cfg.__dict__.get('_temp_cfg', {}).get('DUT', context.workspace.name), options=options)
    classes = [PrepareReviewInputs, SubmitReviewClaims, CollectReviewCases, CaptureReplayReport,
               UpdateCaseAnalysis, SubmitReviewDecisions, ReviewContext, ReviewWorkQueue,
               ReviewRefCheck, RenderBugReviewReport]
    if options.waveform_enabled:
        classes.extend([ApplyReceiptToCase, ApplyWaveformEvent, SetWaveformReviewNote, ReviewSignalCatalog])
    return [tool(**shared) for tool in classes]


def get_plugin():
    """Declare five required stages and one optional waveform stage."""
    root = Path(__file__).parent
    return Plugin(name='bug_review', version=__version__,
        description='Review original Bug claims with targeted tests and optional waveforms', root=root,
        requires_ucagent='>=26.9.2.dev6', tool_factories=(create_tools,), checkers=(BugReviewStageChecker,),
        workflows=(PluginWorkflow(name='analysis', config_file=root / 'workflows/analysis.yaml',
            guide_doc_paths=(root / 'Guide_Doc/analysis.md', root / 'Guide_Doc/bug_review_writing.md'),
            skill_paths=(root / 'skills',), template_context_factory=configure_workflow),))
