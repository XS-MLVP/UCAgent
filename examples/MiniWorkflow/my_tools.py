# -*- coding: utf-8 -*-
"""
MiniWorkflow 自定义工具

这个模块包含了计算器文档生成器工作流所需的自定义工具。
"""

import os
import re
from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool


class CountWordsArgs(BaseModel):
    """CountWords 工具的参数定义"""

    file_path: str = Field(description="要统计字数的文件路径")


class CountWords(UCTool):
    """
    统计文档字数工具

    功能：统计指定 Markdown 文件的字数和段落数
    用途：用于验证文档内容是否充实，满足字数要求
    """

    name: str = "CountWords"
    description: str = "统计指定 Markdown 文件的字数和段落数，返回统计信息"
    args_schema: type[BaseModel] = CountWordsArgs

    def _run(self, file_path: str, run_manager=None) -> str:
        """
        执行字数统计

        参数:
            file_path: 文件路径（支持相对路径和变量）
            run_manager: 运行管理器（可选）

        返回:
            统计结果字符串，包含字数和段落数
        """
        # 限制文件路径为工作空间内的相对路径，防止路径穿越和任意文件读取
        allowed_root = os.path.realpath(os.getcwd())

        # 禁止使用绝对路径
        if os.path.isabs(file_path):
            return (
                f"错误：不支持绝对路径 - {file_path}\n"
                f"提示：请使用相对于当前工作目录的相对路径"
            )

        # 简单阻止路径穿越：禁止包含 '..' 路径段
        if ".." in file_path.split(os.path.sep):
            return (
                f"错误：文件路径包含非法的 '..' 段 - {file_path}\n"
                f"提示：请不要访问工作目录之外的文件"
            )

        # 尝试多个可能的路径来找到文件（均需在 allowed_root 下）
        current_dir = os.getcwd()
        possible_paths = [
            file_path,  # 当前目录
            os.path.join(current_dir, file_path),  # 相对于当前工作目录
            os.path.join(current_dir, "output", file_path),  # 相对于 output 子目录
        ]

        abs_path = None
        for path in possible_paths:
            if not os.path.exists(path):
                continue
            candidate = os.path.realpath(path)
            # 确保文件位于允许的根目录内
            if candidate == allowed_root or candidate.startswith(
                allowed_root + os.path.sep
            ):
                abs_path = candidate
                break

        # 检查文件是否存在且位于允许的目录下
        if not abs_path or not os.path.exists(abs_path):
            return (
                f"错误：文件不存在或不在允许的目录内 - {file_path}\n"
                f"提示：请确保文件位于当前工作目录或其子目录（例如 output）下，并使用相对路径"
            )

        try:
            # 读取文件内容
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 统计中文字符数（不包括标点符号和空格）
            chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", content))

            # 统计英文单词数
            english_words = len(re.findall(r"\b[a-zA-Z]+\b", content))

            # 总字数 = 中文字符数 + 英文单词数
            total_words = chinese_chars + english_words

            # 统计段落数（非空行数）
            paragraphs = len([line for line in content.split("\n") if line.strip()])

            # 统计章节数（# 开头的行）
            sections = len(re.findall(r"^#+\s+.+$", content, re.MULTILINE))

            # 返回统计结果
            result = f"""字数统计结果：
- 总字数: {total_words} 字
- 中文字符: {chinese_chars} 字
- 英文单词: {english_words} 词
- 段落数: {paragraphs} 段
- 章节数: {sections} 章节
- 文件路径: {file_path}"""

            return result

        except Exception as e:
            return f"错误：统计字数失败 - {str(e)}"


class ExtractSectionsArgs(BaseModel):
    """ExtractSections 工具的参数定义"""

    file_path: str = Field(description="要提取章节的 Markdown 文件路径")


class ExtractSections(UCTool):
    """
    提取文档章节结构工具

    功能：提取 Markdown 文件中的所有章节标题及其层级
    用途：用于检查文档结构是否完整，是否包含必需章节
    """

    name: str = "ExtractSections"
    description: str = "提取 Markdown 文件中的所有章节标题，返回章节列表和层级结构"
    args_schema: type[BaseModel] = ExtractSectionsArgs

    def _run(self, file_path: str, run_manager=None) -> str:
        """
        执行章节提取

        参数:
            file_path: 文件路径（支持相对路径和变量）
            run_manager: 运行管理器（可选）

        返回:
            章节列表字符串，按层级组织
        """
        # 尝试多个可能的路径来找到文件
        if os.path.isabs(file_path):
            # 如果是绝对路径，直接使用
            abs_path = file_path
        else:
            # 尝试相对路径的多个可能位置
            current_dir = os.getcwd()
            possible_paths = [
                file_path,  # 当前目录
                os.path.join(current_dir, file_path),  # 相对于当前工作目录
                os.path.join(current_dir, "output", file_path),  # 相对于 output 子目录
            ]

            abs_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    abs_path = os.path.abspath(path)
                    break

        # 检查文件是否存在
        if not abs_path or not os.path.exists(abs_path):
            return f"错误：文件不存在 - {file_path}\n提示：请尝试使用绝对路径，或确保文件在当前工作目录下"

        try:
            # 读取文件内容
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 提取所有章节标题（# 开头的行）
            # 使用正则表达式匹配：^(#+)\s+(.+)$
            # 分组1：井号数量（表示层级）
            # 分组2：标题文本
            sections = []
            for match in re.finditer(r"^(#+)\s+(.+)$", content, re.MULTILINE):
                level = len(match.group(1))  # 井号数量 = 层级
                title = match.group(2).strip()  # 标题文本
                sections.append((level, title))

            # 如果没有找到章节
            if not sections:
                return "未找到任何章节标题（以 # 开头的行）"

            # 格式化输出章节列表
            result_lines = [f"文档章节结构（共 {len(sections)} 个章节）：\n"]

            for level, title in sections:
                # 使用缩进表示层级
                indent = "  " * (level - 1)
                result_lines.append(f"{indent}{'#' * level} {title}")

            # 统计各层级章节数量
            level_counts = {}
            for level, _ in sections:
                level_counts[level] = level_counts.get(level, 0) + 1

            result_lines.append("\n章节层级统计：")
            for level in sorted(level_counts.keys()):
                result_lines.append(f"  - {level}级标题: {level_counts[level]} 个")

            return "\n".join(result_lines)

        except Exception as e:
            return f"错误：提取章节失败 - {str(e)}"


# 导出工具类
__all__ = ["CountWords", "ExtractSections"]
