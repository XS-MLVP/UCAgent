---
name: formal-quick-run
description: 快速试跑当前UCAgent代码的Adder或其他原始DUT Formal任务，或将已退出任务以原身份重新上线；自动选端口，直接返回动态页面链接，不做完整审计。
---

# Formal 快速试跑与重新上线

这是给开发／编码助手使用的启动Skill，不是验证任务内部的阶段Skill。适用于“快速看看当前优化效果”“启动Adder／biu”“把离线任务重新上线”。使用本Skill时直接运行一次脚本，启动成功就返回页面链接，不展开长审计或重复浏览器验收。

## 一条命令启动

从本文件目录定位 `scripts/quick_run.py`，使用已能运行UCAgent的Python解释器。脚本会使用同一个解释器启动Agent；不安装依赖、不自动切分支、不拉代码。用户明确要求同步时才先同步一次，工作区有改动则保留。

```bash
python3 <本Skill目录>/scripts/quick_run.py start
```

默认原始输入为当前checkout的 `examples/Adder`，后台运行Formal工作流、Claude Code后端，使用随机空闲端口，返回 `url`、`workspace`、`log` 和 `agent_id`。仅创建独立目录并复制RTL、头文件、README、filelist和存储器数据，不复制旧生成结果。

连接已有Master、让远端浏览器可打开：

```bash
python3 <本Skill目录>/scripts/quick_run.py start --master 127.0.0.1:8911 --public-host 172.38.8.191
```

使用其他DUT，例如原始BIU输入目录：

```bash
python3 <本Skill目录>/scripts/quick_run.py start --source /path/to/e203_biu --master 127.0.0.1:8911 --public-host 172.38.8.191
```

没有Master时直接给任务页面，不为了看页面另起Master。Master地址只复用用户已经提供或本次已确认运行的服务；不可假定示例端口在每台机器都有效。需要自定义时可加 `--config /path/to/config.yaml`、`--backend claude`、`--checkout /path/to/UCAgent`。默认配置关闭追踪、Embedding和额外阶段建议，seed为11020。`glm-5.3-flash`之类网关模型名的Claude Code提示若任务正常调用工具，不当作启动失败，不去改模型配置。

## 一条命令重新上线

```bash
python3 <本Skill目录>/scripts/quick_run.py online --workspace /path/to/existing/task
```

由本脚本启动的任务会自动恢复保存的端口、Master、配置和Agent ID。若服务仍在运行，返回原链接，不重复启动。

恢复以前手工启动的离线任务时，补上原身份与端口：

```bash
python3 <本Skill目录>/scripts/quick_run.py online --workspace /path/to/existing/task --master 127.0.0.1:8911 --agent-id original-agent-id --port 8913 --public-host 172.38.8.191
```

`online`复用原工作区的DUT、OUT和配置，保留结果；**不传 `--loop`、`--exit-on-completion`、`--force-stage-index`、`--no-history`**，因此只恢复服务和Master连接，不重新证明、不启动模型循环。配置不能读取时只要求补原 `--config`，不发明新的验证参数。不停止或覆盖已占用端口的其他进程。

## 最少操作原则

- 不必逐项询问输入、配置、端口；交给脚本校验。输入必须是原始DUT目录，含 `README.md` 和RTL；只复制支持的源文件，不改原输入。
- 脚本最多等待15秒页面就绪，返回 `online` 或 `starting`。`starting`时给链接与日志路径即可，不在同一轮反复轮询。`error`时看该次日志处理具体错误，不重复启动相同任务。
- 只保留一个小的 `.formal-quick-run.json`（工作区、PID、端口、配置与身份）和进程日志，用于以后重新上线；不生成输入哈希审计、调用统计、长报告或跑全套测试。
- 脚本是明确启动后台服务的操作，返回后服务继续运行。记录返回的工作区和PID；不要用 `timeout` 包住正常运行的Agent，也不要为了退出当前对话杀任务。
- `--dry-run`只准备独立输入并打印命令，不启动、不消耗模型。验证Skill脚本时优先用它；没有用户要求不要额外启动第二个真实模型任务。
- 页面可打开不等于验证完成，`Exit`不等于设计全部通过。普通试跑启动后先返回链接，用户另问结果时再检查阶段／证明。

## 最终回复示例

```text
已启动，使用当前分支代码和干净的Adder输入。
任务页：http://<host>:<port>/agent/<id>/cmd/
```

重新上线则说明“原链接已恢复，只恢复服务，没有重跑验证”。不重复输出长命令和检查步骤。
