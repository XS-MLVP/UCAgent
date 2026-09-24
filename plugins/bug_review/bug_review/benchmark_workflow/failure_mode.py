"""Rule-based failure mode classification for benchmark records.

The classifier intentionally stays conservative and deterministic.  It uses
record text, candidate ids, signals, and replay/test metadata to separate
symptom bugs before RTL-root clustering.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List


_HANDSHAKE_PATTERNS = (
    "handshake", "握手", "ready/valid", "valid/ready", "ready 未拉高", "valid 未拉高",
    "握手失败", "握手超时", "握手卡死", "无法握手", "ready signals", "valid signals"
)
_BACKPRESSURE_PATTERNS = (
    "backpressure", "背压", "反压", "stall", "流水线阻塞", "阻塞", "流控"
)
_ORDERING_CONCURRENCY_PATTERNS = (
    "ordering", "concurrency", "乱序", "保序", "顺序错误", "并发", "双 sta", "发射顺序",
    "死锁", "deadlock", "竞争", "race", "hazard", "冲突", "反序"
)
_ROUTING_SELECTION_PATTERNS = (
    "routing", "selection", "路由", "选路", "选择错误", "多路选择", "arbiter", "仲裁",
    "bypass", "旁路", "mux", "分发", "dispatch", "分支选择"
)
_PROTOCOL_PATTERNS = (
    "protocol", "协议", "违背", "违规", "tilelink", "axi", "chi", "dtlb", "pmp",
    "非法访问", "权限异常", "越界", "opcode", "非法指令", "illegal", "violation", "映射错误", "权限检查"
)
_DONE_TIMEOUT_PATTERNS = (
    "timeout",
    "timed out",
    "never asserts",
    "never asserted",
    "never assert",
    "does not assert",
    "not assert",
    "no done",
    "done not",
    "done never",
    "等待 done 超时",
    "超时",
    "无法完成",
    "不拉高",
    "没有拉高",
    "卡死",
)
_OUTPUT_MISMATCH_AFTER_DONE_PATTERNS = (
    "done=1", "after done", "done 有效", "完成信号后", "写回错误", "writeback", "写回阶段", "返回值错误"
)
_OUTPUT_MISMATCH_PATTERNS = (
    "mismatch",
    "differs",
    "incorrect",
    "wrong",
    "not match",
    "偏离",
    "不一致",
    "错误",
    "不匹配",
)
_RESET_PATTERNS = ("reset", "rst", "复位", "初始状态", "复位后", "残留", "未清除", "stale", "未复位", "泄漏")
_LOAD_BUSY_PATTERNS = ("load while busy", "busy load", "busy", "override", "背靠背", "运行中再次", "忙")
_XZ_PATTERNS = ("unknown", "high impedance", "x/z", " x ", " z ", "高阻", "未知", "不定态")



def _has_failed_dut_oracle(record: Dict[str, object]) -> bool:
    """Return whether persisted test evidence proves a functional mismatch.

    Root clustering runs before replay, so replay absence cannot distinguish a
    coverage observation from an already-failing DUT oracle.  Prefer the
    saved pytest/toffee outcome and assertion evidence when it is available.
    """
    evidence_sets = (record.get("oracle_evidence", []), record.get("tests", []))
    for evidence in evidence_sets:
        if not isinstance(evidence, list):
            continue
        for test in evidence:
            if not isinstance(test, dict):
                continue
            if str(test.get("outcome") or "").lower() not in {"failed", "error"}:
                continue
            if (
                test.get("exception_message")
                or test.get("assertion_preview")
                or test.get("assertions")
            ):
                return True
    return False


def _has_explicit_value_mismatch(record: Dict[str, object]) -> bool:
    expected = record.get("expected")
    observed = record.get("observed")
    if expected not in (None, "") and observed not in (None, ""):
        if str(expected).strip() != str(observed).strip():
            return True
    for result in record.get("replay_results", []) or []:
        if not isinstance(result, dict):
            continue
        expected = result.get("expected")
        observed = result.get("observed")
        if expected not in (None, "") and observed not in (None, ""):
            if str(expected).strip() != str(observed).strip():
                return True
    return False


def _text_parts(record: Dict[str, object]) -> List[str]:
    parts: List[str] = []
    for key in (
        "property_text",
        "root_cause",
        "trigger",
        "observed",
        "expected",
        "failure_mode",
        "validation_summary",
        "coverage_evidence_summary",
    ):
        value = record.get(key)
        if value not in (None, ""):
            parts.append(str(value))
    for key in ("candidate_ids", "signals", "signal_names", "observations", "tests"):
        value = record.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item not in (None, ""))
    for result in record.get("replay_results", []) or []:
        if not isinstance(result, dict):
            continue
        for key in ("status", "failure_mode", "message", "stdout", "stderr", "observed", "expected"):
            value = result.get(key)
            if value not in (None, ""):
                parts.append(str(value))
    return parts


def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def _record_text(record: Dict[str, object]) -> str:
    return "\n".join(_text_parts(record))


def infer_primary_signal(record: Dict[str, object], failure_mode: str | None = None) -> str:
    """Infer the signal that best represents the observed failure."""
    signals = [str(item).lower() for item in record.get("signals", []) or []]
    text = _record_text(record).lower()
    mode = failure_mode or classify_failure_mode(record)

    if mode in {"done_timeout", "done_never_asserts"}:
        return "done"
    if mode == "reset_state_mismatch":
        if "text_out" in signals or "text_out" in text:
            return "text_out"
        return "rst"
    if mode == "load_while_busy":
        return "ld" if "ld" in signals or " ld" in text else "busy"
    if "text_out" in signals or "text_out" in text:
        return "text_out"
    if "done" in signals or "done" in text:
        return "done"
    if "rst" in signals or "reset" in text:
        return "rst"
    return signals[0] if signals else "unknown"


def classify_failure_mode(record: Dict[str, object]) -> str:
    """Classify a benchmark record into a stable failure-mode family."""
    text = _record_text(record)
    lowered = text.lower()
    signals = {str(item).lower() for item in record.get("signals", []) or []}
    replay_statuses = {
        str(item.get("status")).lower()
        for item in record.get("replay_results", []) or []
        if isinstance(item, dict) and item.get("status")
    }
    validation_summary = str(record.get("validation_summary") or "")
    coverage_summary = str(record.get("coverage_evidence_summary") or "none")

    has_done = "done" in signals or "done" in lowered
    has_timeout = _contains_any(text, _DONE_TIMEOUT_PATTERNS)
    reset_context = " ".join(
        str(record.get(key) or "")
        for key in ("property_text", "observed", "root_cause", "validation_summary")
    )

    # 1. X/Z 传播
    if _contains_any(text, _XZ_PATTERNS):
        return "x_z_propagation"

    # 2. 复位状态不匹配 / 状态残留
    if _contains_any(reset_context, _RESET_PATTERNS):
        if not has_timeout and ("assert" in lowered or _contains_any(text, _OUTPUT_MISMATCH_PATTERNS) or "残留" in reset_context or "泄漏" in reset_context):
            return "reset_state_mismatch"

    # 3. 排序 / 并发 / 死锁错误
    if _contains_any(text, _ORDERING_CONCURRENCY_PATTERNS):
        return "ordering_or_concurrency_failure"

    # 4. 握手失败
    if _contains_any(text, _HANDSHAKE_PATTERNS):
        return "handshake_failure"

    # 5. 背压失败
    if _contains_any(text, _BACKPRESSURE_PATTERNS):
        return "backpressure_failure"

    # 6. 协议违规 / 权限异常映射
    if _contains_any(text, _PROTOCOL_PATTERNS):
        return "protocol_violation"

    # 7. 路由 / 选路 / 仲裁 / 旁路错误
    if _contains_any(text, _ROUTING_SELECTION_PATTERNS):
        return "routing_or_selection_failure"

    # 8. 完成信号异常
    if has_done and has_timeout:
        return "done_timeout"
    if re.search(r"\bdone\b.*\b(never|not|no|assert)", lowered):
        return "done_never_asserts"
    if has_timeout and ("done" in lowered or "commit" in lowered or "finish" in lowered):
        return "done_completion_failure"

    # 9. 忙状态加载
    if _contains_any(text, _LOAD_BUSY_PATTERNS) and ("ld" in signals or "load" in lowered or "busy" in lowered):
        if not has_timeout:
            return "load_while_busy"

    # 10. 完成信号后输出不匹配 / 写回错误
    if _contains_any(text, _OUTPUT_MISMATCH_PATTERNS) and _contains_any(text, _OUTPUT_MISMATCH_AFTER_DONE_PATTERNS):
        return "output_mismatch_after_done"

    # 11. 功能输出不匹配（兜底）
    if _has_failed_dut_oracle(record) or _has_explicit_value_mismatch(record) or _contains_any(text, _OUTPUT_MISMATCH_PATTERNS):
        return "output_mismatch"

    if (
        replay_statuses.isdisjoint({"reproduced", "not_reproduced"})
        and coverage_summary != "none"
        and validation_summary
    ):
        return "coverage_only"
    return "undetermined"



def failure_mode_family(failure_mode: str) -> str:
    """Return the root-cause clustering family for a detailed failure mode."""
    if failure_mode in {"done_timeout", "done_never_asserts"}:
        return "done_completion_failure"
    return failure_mode or "undetermined"
