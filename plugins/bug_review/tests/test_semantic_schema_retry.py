"""Regression tests for semantic review schema validation."""
import copy
import pytest

from bug_review.benchmark_workflow.pipeline import InvalidSemanticSchemaError, _is_retryable_semantic_error
from bug_review.benchmark_workflow.semantic_task_store import _valid_cached_row, SemanticTaskStore
from bug_review.benchmark_workflow.task_manifest import stable_hash


def test_is_retryable_semantic_error():
    err = InvalidSemanticSchemaError("test schema failure")
    assert _is_retryable_semantic_error(err) is True
    # 普通 ValueError 不应被误判为可重试
    assert _is_retryable_semantic_error(ValueError("normal value error")) is False


def test_valid_cached_row_with_schema_fallback():
    snapshot = {"left": {"candidate_id": "c1"}, "right": {"candidate_id": "c2"}, "score": 1}
    input_hash = stable_hash(snapshot)
    prompt_hash = stable_hash(["prompt"])

    task_input = {
        "left_candidate_id": "c1",
        "right_candidate_id": "c2",
        "input_snapshot_hash": input_hash,
        "prompt_hash": prompt_hash,
    }

    base_judgement = {
        "relation": "insufficient evidence",
        "property_match_status": "unknown",
        "trigger_match_status": "unknown",
        "expected_observed_match_status": "unknown",
        "rtl_cause_match_status": "unknown",
        "input_snapshot_hash": input_hash,
        "prompt_hash": prompt_hash,
    }

    # 1. 正常的 schema_valid = True
    valid_row = {
        "left_candidate_id": "c1",
        "right_candidate_id": "c2",
        "judgement": {**base_judgement, "schema_valid": True},
    }
    assert _valid_cached_row(valid_row, task_input) is True

    # 2. 未经降级的 schema_valid = False -> 必须拒绝
    invalid_row = {
        "left_candidate_id": "c1",
        "right_candidate_id": "c2",
        "judgement": {**base_judgement, "schema_valid": False},
    }
    assert _valid_cached_row(invalid_row, task_input) is False

    # 3. 经重试3次后降级的 schema_valid = False 且 relation == 'insufficient evidence' -> 允许通过
    downgraded_row = {
        "left_candidate_id": "c1",
        "right_candidate_id": "c2",
        "judgement": {
            **base_judgement,
            "schema_valid": False,
            "schema_fallback_downgraded": True,
            "schema_fallback_warning": "failed 3 times",
        },
    }
    assert _valid_cached_row(downgraded_row, task_input) is True

    # 4. 试图伪造 schema_fallback_downgraded 但 relation 不是 insufficient evidence -> 必须拒绝
    bogus_row = {
        "left_candidate_id": "c1",
        "right_candidate_id": "c2",
        "judgement": {
            **base_judgement,
            "relation": "same bug",
            "schema_valid": False,
            "schema_fallback_downgraded": True,
        },
    }
    assert _valid_cached_row(bogus_row, task_input) is False


def test_semantic_task_store_save_success_with_fallback(tmp_path):
    store = SemanticTaskStore(tmp_path)
    left = {"candidate_id": "cand_a", "dut": "dut_x"}
    right = {"candidate_id": "cand_b", "dut": "dut_x"}
    runtime_config = {"provider": "mock", "model": "m"}

    task_input = store.prepare(left, right, 1, runtime_config)

    # 模拟重试 3 次后的降级结果
    downgraded_row = {
        "left_candidate_id": task_input["left_candidate_id"],
        "right_candidate_id": task_input["right_candidate_id"],
        "left_model": "m1",
        "right_model": "m2",
        "dut": "dut_x",
        "score": 1,
        "judgement": {
            "relation": "insufficient evidence",
            "property_match_status": "unknown",
            "trigger_match_status": "unknown",
            "expected_observed_match_status": "unknown",
            "rtl_cause_match_status": "unknown",
            "schema_valid": False,
            "schema_fallback_downgraded": True,
            "schema_fallback_warning": "failed 3 times",
            "input_snapshot_hash": task_input["input_snapshot_hash"],
            "prompt_hash": task_input["prompt_hash"],
        },
    }

    # 保存降级结果，不应抛出异常
    store.save_success(task_input, downgraded_row)

    # 加载已保存的结果，验证能够顺利加载
    loaded = store.load_success(task_input)
    assert loaded is not None
    assert loaded["semantic_judgement"]["judgement"]["schema_fallback_downgraded"] is True


def test_execute_llm_request_streaming_success():
    from bug_review.benchmark_workflow.semantic_judge import _execute_llm_request

    class FakeDelta:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, delta):
            self.delta = delta

    class FakeChunk:
        def __init__(self, content):
            self.choices = [FakeChoice(FakeDelta(content))]

    class FakeCompletions:
        def create(self, **kwargs):
            if kwargs.get("stream"):
                return [FakeChunk('{"relation": '), FakeChunk('"same bug"}')]
            raise RuntimeError("stream=False should not be called if stream=True succeeds")

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    res = _execute_llm_request(
        FakeClient(),
        model="fake-model",
        messages=[{"role": "user", "content": "hi"}],
        request_timeout=30.0,
    )
    assert res == '{"relation": "same bug"}'


def test_execute_llm_request_streaming_fallback_to_non_streaming():
    from bug_review.benchmark_workflow.semantic_judge import _execute_llm_request

    class FakeMessage:
        content = '{"relation": "different bugs"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            if kwargs.get("stream"):
                raise ValueError("stream mode not supported by upstream")
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    res = _execute_llm_request(
        FakeClient(),
        model="fake-model",
        messages=[{"role": "user", "content": "hi"}],
        request_timeout=30.0,
    )
    assert res == '{"relation": "different bugs"}'
