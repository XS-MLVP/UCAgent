# Makefile for MiniWorkflow Example

# 检测 ucagent 命令
UCAGENT_PY := $(wildcard ../../ucagent.py)

ifdef UCAGENT_PY
CMD ?= python3 ../../ucagent.py
else
CMD ?= ucagent
endif

# 默认项目名称
PROJECT ?= Calculator

.PHONY: help clean init run test

help:
	@echo "MiniWorkflow - 计算器文档生成器"
	@echo ""
	@echo "可用命令:"
	@echo "  make clean       - 清理输出目录"
	@echo "  make init        - 初始化输出目录"
	@echo "  make run         - 运行文档生成工作流"
	@echo "  make test        - 测试工具和检查器"
	@echo ""
	@echo "示例:"
	@echo "  make run         - 为 Calculator 项目生成文档"

clean:
	@echo "清理输出目录..."
	@rm -rf output/
	@echo "清理完成"

init:
	@echo "初始化输出目录..."
	@mkdir -p output
	@echo "初始化完成"

run: clean init
	@echo "启动 UCAgent 工作流..."
	@echo "项目: $(PROJECT)"
	@echo ""
	@cp -r $(PROJECT) output/
	$(CMD) ./output/ $(PROJECT) \
		--mcp-server-no-file-tools \
		--config ./mini.yaml \
		--guid-doc-path ./Guide_Doc/ \
		-s -hm --tui --no-embed-tools

test:
	@echo "测试自定义工具..."
	@python3 -c "from my_tools import CountWords, ExtractSections; print('工具导入成功')"
	@echo "测试自定义检查器..."
	@python3 -c "from my_checkers import WordCountChecker, RequiredSectionsChecker; print('检查器导入成功')"
	@echo "所有测试通过!"
