# -*- coding: utf-8 -*-
"""
MiniWorkflow 自定义检查器

这个模块包含了计算器文档生成器工作流所需的自定义检查器。
"""

import os
import re
from ucagent.checkers.base import Checker


class WordCountChecker(Checker):
    """
    文档字数检查器

    功能：检查文档的字数是否在指定范围内
    用途：确保文档内容充实，不会太短或太长
    """

    def __init__(
        self, file_path: str, word_min: int = 0, word_max: int = 10000, **kwargs
    ):
        """
        初始化检查器

        参数:
            file_path: 要检查的文件路径
            word_min: 最小字数要求
            word_max: 最大字数限制
            **kwargs: 其他参数（包含 need_human_check 等）
        """
        # 保存参数
        self.file_path = file_path
        self.word_min = word_min
        self.word_max = word_max

        # 设置是否需要人工检查（从 kwargs 中获取）
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        执行检查逻辑

        参数:
            timeout: 超时时间（秒），0 表示不限制
            **kwargs: 其他参数

        返回:
            (is_pass, result):
                - is_pass (bool): True 表示检查通过，False 表示失败
                - result (dict|str): 检查结果详情
        """
        # 处理文件路径
        # 如果有workspace属性，使用get_path；否则直接使用相对/绝对路径
        if hasattr(self, "workspace") and self.workspace:
            abs_path = self.get_path(self.file_path)
        else:
            # 独立使用时，直接处理路径
            abs_path = (
                os.path.abspath(self.file_path)
                if not os.path.isabs(self.file_path)
                else self.file_path
            )

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            return False, {
                "error": f"文件不存在：{self.file_path}",
                "suggestion": "请确认文件已生成，检查文件路径是否正确",
            }

        try:
            # 读取文件内容
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 统计字数（中文字符 + 英文单词）
            chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", content))
            english_words = len(re.findall(r"\b[a-zA-Z]+\b", content))
            total_words = chinese_chars + english_words

            # 检查字数是否在范围内
            if total_words < self.word_min:
                return False, {
                    "error": "文档字数不足",
                    "current_words": total_words,
                    "required_min": self.word_min,
                    "required_max": self.word_max,
                    "shortage": self.word_min - total_words,
                    "suggestion": f"当前 {total_words} 字，至少需要 {self.word_min} 字，还差 {self.word_min - total_words} 字",
                }

            if total_words > self.word_max:
                return False, {
                    "error": "文档字数超出限制",
                    "current_words": total_words,
                    "required_min": self.word_min,
                    "required_max": self.word_max,
                    "excess": total_words - self.word_max,
                    "suggestion": f"当前 {total_words} 字，最多 {self.word_max} 字，超出 {total_words - self.word_max} 字",
                }

            # 检查通过
            return True, {
                "message": "字数检查通过",
                "current_words": total_words,
                "required_range": f"{self.word_min}-{self.word_max}",
                "file_path": self.file_path,
            }

        except Exception as e:
            # 捕获异常，返回错误信息
            return False, {"error": f"检查失败：{str(e)}", "file_path": self.file_path}


class RequiredSectionsChecker(Checker):
    """
    必需章节检查器

    功能：检查文档是否包含所有必需的章节
    用途：确保文档结构完整，符合模板要求
    """

    def __init__(self, file_path: str, required_sections: list, **kwargs):
        """
        初始化检查器

        参数:
            file_path: 要检查的文件路径
            required_sections: 必需章节列表（二级标题文本）
            **kwargs: 其他参数，如 workspace
        """
        # 调用父类初始化
        super().__init__()

        # 设置 workspace（如果传入）
        if "workspace" in kwargs:
            self.workspace = kwargs["workspace"]

        # 保存参数
        self.file_path = file_path
        self.required_sections = required_sections

        # 设置是否需要人工检查
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        执行检查逻辑

        参数:
            timeout: 超时时间（秒）
            **kwargs: 其他参数

        返回:
            (is_pass, result): 检查结果
        """
        # 处理文件路径
        # 如果有workspace属性，使用get_path；否则直接使用相对/绝对路径
        if hasattr(self, "workspace") and self.workspace:
            abs_path = self.get_path(self.file_path)
        else:
            # 独立使用时，直接处理路径
            abs_path = (
                os.path.abspath(self.file_path)
                if not os.path.isabs(self.file_path)
                else self.file_path
            )

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            return False, {
                "error": f"文件不存在：{self.file_path}",
                "suggestion": "请确认文件已生成",
            }

        try:
            # 读取文件内容
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 提取所有二级标题（## 开头的行）
            # 正则表达式：^##\s+(.+)$
            found_sections = []
            for match in re.finditer(r"^##\s+(.+)$", content, re.MULTILINE):
                section_title = match.group(1).strip()
                found_sections.append(section_title)

            # 检查每个必需章节是否存在
            missing_sections = []
            for required in self.required_sections:
                # 检查是否有匹配的章节（允许部分匹配）
                found = False
                for found_section in found_sections:
                    if required in found_section or found_section in required:
                        found = True
                        break

                if not found:
                    missing_sections.append(required)

            # 如果有缺失的章节
            if missing_sections:
                return False, {
                    "error": "文档缺少必需章节",
                    "missing_sections": missing_sections,
                    "required_sections": self.required_sections,
                    "found_sections": found_sections,
                    "suggestion": f"请添加以下章节：{', '.join(missing_sections)}",
                }

            # 检查通过
            return True, {
                "message": "章节检查通过",
                "required_sections": self.required_sections,
                "found_sections": found_sections,
                "file_path": self.file_path,
            }

        except Exception as e:
            # 捕获异常
            return False, {"error": f"检查失败：{str(e)}", "file_path": self.file_path}


# 导出检查器类
__all__ = ["WordCountChecker", "RequiredSectionsChecker"]
