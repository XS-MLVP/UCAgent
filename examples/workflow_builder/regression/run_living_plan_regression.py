from __future__ import annotations

import tempfile
from pathlib import Path

from examples.workflow_builder.tools.workflow_builder.plan_contract import append_record, validate_records
from examples.workflow_builder.tools.workflow_builder.uc_checkers import WorkflowLivingPlanChecker


def _record(label: str) -> str:
    return f"""### 阶段目标
完成{label}的真实业务目标，明确输入边界、成功条件和不能通过手工修改候选结果绕过的限制。
### 决策与变更
记录本阶段选择的接口、路径、实现方式、兼容约束和相对初始设计发生的全部变化，供后续阶段直接使用。
### 产物与验证证据
列出实际生成文件、结构化报告、Checker 返回、测试命令和退出状态，并说明证据为何足以支持当前结论。
### 问题与处理
保留遇到的失败现象、根因、修改位置和回归结果；没有发现新问题时也要明确写出检查范围和未发现问题。
### 后续约束
写明后续阶段必须读取的产物、不得重新设计的契约、仍需完成的工作以及失败时应返回的正确修改位置。
"""


def _check(workspace: Path, stage: str) -> tuple[bool, object]:
    checker = WorkflowLivingPlanChecker(
        plan_path="wfgen/workflow_implementation_plan.md",
        current_stage=stage,
    )
    checker.workspace = str(workspace)
    return checker.do_check()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="living_plan_regression_") as temp:
        workspace = Path(temp)
        plan_path = workspace / "wfgen/workflow_implementation_plan.md"
        plan_path.parent.mkdir(parents=True)
        baseline = "# 工作流实现计划\n\n这里保存完整架构基线，后续阶段只能追加记录。\n"

        stage0 = append_record(
            baseline,
            "extract_requirements_and_plan",
            _record("需求提取"),
        )
        plan_path.write_text(stage0, encoding="utf-8")
        passed, result = _check(workspace, "extract_requirements_and_plan")
        assert passed, result

        try:
            append_record(
                stage0,
                "extract_requirements_and_plan",
                _record("重复需求提取"),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate stage record must be rejected")

        stage1 = append_record(
            stage0,
            "design_workflow_build_config",
            _record("构建配置设计"),
        )
        assert not validate_records(stage1, "design_workflow_build_config")
        plan_path.write_text(stage1, encoding="utf-8")
        passed, result = _check(workspace, "design_workflow_build_config")
        assert passed, result

        rewritten = stage1.replace("完整架构基线", "被覆盖的架构基线", 1)
        plan_path.write_text(rewritten, encoding="utf-8")
        passed, result = _check(workspace, "design_workflow_build_config")
        assert not passed and result["record_errors"], result

        try:
            append_record(
                stage1,
                "build_initial_template",
                "### 阶段目标\n过短",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("short stage record must be rejected")

    print("[PASS] living workflow implementation plan contract")


if __name__ == "__main__":
    main()
