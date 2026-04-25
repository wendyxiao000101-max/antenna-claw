"""Topology self-check and non-interactive auto-revision workflow.

The interactive "ask user to confirm each fix" loop was removed so this
workflow can run headless as part of an OpenClaw-driven pipeline.
The caller decides whether to enable it; when enabled, LEAM will attempt
up to ``max_rounds`` LLM-driven fixes and report the outcome via the
existing topology report printer.
"""

from ..models import DesignSession
from ..postprocess import build_fix_prompt
from ..services import ValidationService


class TopologyRevisionWorkflow:
    def __init__(self, validation_service: ValidationService):
        self.validation_service = validation_service

    def run(
        self,
        session: DesignSession,
        regenerate_model_and_boolean,
        max_rounds: int = 3,
    ) -> None:
        print("\n[拓扑自检] 正在分析几何结构…")
        for round_num in range(1, max_rounds + 1):
            issues = self.validation_service.run_topology(session)
            self.validation_service.print_topology_report(issues)
            errors = [i for i in issues if i.severity == "error"]
            warnings = [i for i in issues if i.severity == "warning"]

            if not errors and not warnings:
                print("[拓扑自检] 所有关键检查已通过，模型拓扑结构正确。")
                return

            print(
                f"发现 {len(errors)} 个错误 / {len(warnings)} 个警告。"
                f"（第 {round_num}/{max_rounds} 轮，自动修复）"
            )

            fix_context = build_fix_prompt(issues, user_instructions="")
            session.description = session.description + "\n\n" + fix_context
            print(f"\n[修复 {round_num}] 重新生成 model.bas + boolean_ops.bas …")
            regenerate_model_and_boolean(session)
            print(f"[修复 {round_num}] 重新生成完成，重新执行拓扑检查…\n")

        issues = self.validation_service.run_topology(session)
        self.validation_service.print_topology_report(issues)
        remaining = sum(1 for i in issues if i.severity in ("error", "warning"))
        if remaining:
            print(
                f"已达到最大修复轮数（{max_rounds}），仍有 {remaining} 个问题未解决。\n"
                "请在 OpenClaw 侧决定是否根据报告进一步修改生成的 .bas 文件。"
            )
        else:
            print("[拓扑自检] 所有关键检查已通过。")
