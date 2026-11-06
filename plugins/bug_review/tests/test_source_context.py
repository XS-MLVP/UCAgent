"""Check bounded static source navigation without executing test modules."""

import pytest
from bug_review.core.records import Case
from bug_review.tools import ReviewContext
from conftest import NODE


def replace_source(layout, text):
    """Customize only this synthetic archived fixture before testing read-only navigation."""
    source = layout.inputs / "tests/test_demo.py"
    source.parent.chmod(0o755)
    source.chmod(0o644)
    source.write_text(text)
    return source


@pytest.mark.parametrize("import_line, call_name", [("from helpers import drive as send", "send"), ("from helpers import *", "drive")])
def test_original_function_and_helpers_are_cited_without_imports(linked, import_line, call_name):
    """Find local helpers and explicit local imported aliases using AST only."""
    source = replace_source(linked, f'{import_line}\nraise RuntimeError("must not execute")\n\ndef prepare():\n    return {call_name}()\n\ndef test_bad():\n    assert prepare()\n')
    (source.parent / 'helpers.py').write_text('raise RuntimeError("do not import")\n\ndef drive():\n    return 0\n')
    result = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(case_id=NODE)
    assert result['success']
    context = result['source_context']
    assert 'assert prepare()' in context['test_excerpts'][0]['text']
    assert context['helper_refs'] == [{'name': 'prepare', 'ref': 'inputs/tests/test_demo.py:4-5'},
                                      {'name': call_name, 'ref': 'inputs/tests/helpers.py:3-4'}]
    assert not context['diagnostics']
    assert not linked.case(NODE).executions


def test_class_async_and_parameter_identity(linked):
    """Disambiguate qualified methods and preserve parameter IDs containing separators."""
    path = replace_source(linked, 'class Other:\n    def test_bad(self):\n        assert False\n\nclass Selected:\n    def helper(self):\n        return 1\n    async def test_bad(self):\n        assert self.helper() == 1\n')
    node = 'tests/test_demo.py::Selected::test_bad[value::part]'
    review = linked.review(); review.cases[node] = Case(case_id=node, case_key='C0002', waveform_test_case_name=node); linked.save(review)
    result = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(case_id=node)
    context = result['source_context']
    assert 'async def' in context['test_excerpts'][0]['text']
    assert 'assert False' not in context['test_excerpts'][0]['text']
    assert context['helper_refs'] == [{'name': 'helper', 'ref': 'inputs/tests/test_demo.py:6-7'}]


def test_large_function_is_bounded_and_explicitly_partial(linked):
    """Long functions expose both boundaries without flooding model context."""
    source = replace_source(linked, 'def test_bad():\n' + '    value = 0\n' * 100 + '    assert value == 0\n')
    context = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(case_id=NODE)['source_context']
    assert context['test_truncated']
    assert len(context['test_excerpts']) == 2
    assert sum(len(e['text'].splitlines()) for e in context['test_excerpts']) == 60
    assert 'assert value == 0' in context['test_excerpts'][-1]['text']


def test_bad_python_and_missing_definition_provide_navigation_diagnostics(linked):
    """A source lookup failure must leave actual Case and execution records readable."""
    source = linked.inputs / 'tests/test_demo.py'
    for text in ['def broken(:\n', 'def another_test():\n    pass\n', '']:
        replace_source(linked, text)
        result = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(case_id=NODE)
        assert result['success']
        assert result['case_id'] == NODE
        assert result['source_context']['diagnostics']
        assert result['source_context']['test_excerpts'] == []


def test_local_import_symlink_cannot_expose_external_source(linked, tmp_path):
    """Resolving helper candidates must honor the same workspace boundary as citations."""
    source = replace_source(linked, 'from helpers import drive\n\ndef test_bad():\n    assert drive()\n')
    private = tmp_path.parent / (tmp_path.name + '-outside.py'); private.write_text('PRIVATE_EXTERNAL_SOURCE\n')
    (source.parent / 'helpers.py').symlink_to(private)
    result = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(case_id=NODE)
    assert result['source_context']['diagnostics']
    assert not result['source_context']['helper_refs']
    assert 'PRIVATE_EXTERNAL_SOURCE' not in str(result)


def test_relative_helper_import_is_static_local_navigation(linked):
    """Resolve a relative helper within the archived package without importing it."""
    source = replace_source(linked, 'from .helpers import drive\n\ndef test_bad():\n    assert drive()\n')
    (source.parent / 'helpers.py').write_text('def drive():\n    return 0\n')
    result = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(case_id=NODE)
    assert result['source_context']['helper_refs'] == [{'name': 'drive', 'ref': 'inputs/tests/helpers.py:1-2'}]


def test_parameter_decorator_is_in_original_excerpt(linked):
    """Keep parameter definitions visible instead of stripping the decorator source."""
    replace_source(linked, 'import pytest\n\n@pytest.mark.parametrize("value", [1, 2])\ndef test_bad(value):\n    assert value == 0\n')
    result = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(case_id=NODE)
    assert '@pytest.mark.parametrize' in result['source_context']['test_excerpts'][0]['text']


def test_single_long_source_line_has_a_character_budget(linked):
    """Physical-line bounds must also bound unusually long generated expressions."""
    replace_source(linked, 'def test_bad():\n    value = "' + 'x' * 20000 + '"\n    assert value\n')
    context = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(case_id=NODE)['source_context']
    assert context['test_truncated']
    assert context['test_excerpts'][0]['truncated']
    assert len(context['test_excerpts'][0]['text']) == 6000


def test_queue_returns_validated_group_without_writing(linked):
    """Derive navigation from the actual content gate instead of a category marker."""
    from bug_review.tools import ReviewWorkQueue
    before = (linked.out / 'review.json').read_bytes()
    tool = ReviewWorkQueue(workspace=str(linked.workspace), output_dir='results')
    result = tool._run(stage='targeted_review')
    assert result['success'] is False
    assert result['error_code'] == 'REVIEW_INCOMPLETE'
    assert result['case_progress'] == {'total': 1, 'ready': 0, 'pending': 1}
    assert result['next_group']['cases'][0]['case_id'] == NODE
    assert 'source_context' not in result['next_group']['cases'][0]
    assert (linked.out / 'review.json').read_bytes() == before
    case = linked.case(NODE); case.analysis.category = 'test'; linked.save_case(case)
    assert tool._run(stage='targeted_review')['case_progress']['ready'] == 0


def test_queue_ready_cases_and_unlinked_group(analyzed):
    """Ready Cases stay complete while the next unreviewed indexed Case is projected."""
    from bug_review.tools import ReviewWorkQueue
    tool = ReviewWorkQueue(workspace=str(analyzed.workspace), output_dir='results')
    result = tool._run(stage='targeted_review')
    assert result['success']
    assert result['case_progress'] == {'total': 1, 'ready': 1, 'pending': 0}
    assert result['next_group'] is None
    review = analyzed.review(); review.options.full_regression_enabled = True
    node = 'tests/test_demo.py::test_unrelated'
    review.cases[node] = Case(case_id=node, case_key='C0002', waveform_test_case_name=node)
    analyzed.save(review)
    result = tool._run(stage='targeted_review')
    assert result['success'] is False
    assert result['case_progress'] == {'total': 2, 'ready': 1, 'pending': 1}
    assert result['next_group']['cases'][0]['case_id'] == node
