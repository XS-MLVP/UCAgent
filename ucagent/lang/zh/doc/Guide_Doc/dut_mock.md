# DUT Mock 组件指南

本文档给出在验证环境中设计与实现 Mock 组件的规范与实例，配合 `dut_fixture.md` 一起使用。

目标：
- 为 DUT 的上下游依赖（存储器、总线、外设、参考模型等）提供可控、可观测、可复现的替代实现
- 便于在 env fixture 中通过 `dut.StepRis(...)` 统一驱动 Mock，简化测试编写

## 何时需要 Mock

- DUT 依赖外部模块（如存储器、总线/通道、外设、协议端点）而无法在测试中直接提供真实实现
- 需要可控的时序、延迟、吞吐、背压、错误注入等行为
- 需要参考模型（Golden Model）用于结果比对


## 设计原则

1) 可配置：
- 通过构造参数或属性设置延迟、带宽、FIFO 深度、随机抖动、错误注入概率等

2) 明确接口：
- 对外暴露清晰的方法：如 `read(addr)`, `write(addr, data)`, `push(...)`, `pop(...)`，或协议事务接口

1) 时序统一：
- 将所有周期行为集中在 `on_clock_edge(cycles, ...)` 中，由 `dut.StepRis(...)` 驱动
- 组合电路场景仍使用 `dut.Step(1)` 触发 StepRis，以保持统一

1) 资源管理：
- 提供 `reset()`/`clear()` 用于状态清空，必要时提供 `close()` 或在 env 清理阶段移除回调

1) 可观测性：
- 提供统计计数器、最近 N 次事务的日志、调试开关；遇到协议违规能输出提示

1) 可复现性：
- 涉及随机行为时接受 `seed`，并保证同一 seed 下行为可复现


## 生命周期与对接点（env 内集成）

典型流程：
1. 在 env 的 `__init__` 中实例化 Mock，并绑定 DUT 引脚
2. 在 `__init__` 里通过 `dut.StepRis(self.mock.on_clock_edge)` 注册 Mock 的时钟回调
3. 需要时在 env 暴露一些便捷方法，转调到 Mock（如 `mem_read`, `mem_write`）

注意：默认 `StepRis` 回调按注册顺序执行。一般先注册覆盖率采样，再注册 Mock 驱动，最后注册监控/日志回调，便于保证正确的执行顺序。


## 最小可用 Mock 模板

```python
class MockTemplate:
	"""最小可用 Mock 模板

	Args:
		latency: 周期延迟，控制请求到响应的最小周期
		enable_log: 是否打印关键日志
	"""

	def __init__(self, latency=0, enable_log=False):
		self.latency = latency
		self.enable_log = enable_log
		self._cycles = 0
		self._pending = []  # [(ready_cycle, payload), ...]
		self.stats = {
			'req': 0,
			'rsp': 0,
		}

	def bind(self, dut_or_bundle):
		"""绑定 DUT 或 Bundle，对接信号/接口。"""
		self.io = dut_or_bundle

	def reset(self):
		"""清空内部状态。"""
		self._cycles = 0
		self._pending.clear()
		for k in self.stats:
			self.stats[k] = 0

	def request(self, payload):
		"""上层或 env 主动投递一个请求。"""
		self.stats['req'] += 1
		self._pending.append((self._cycles + self.latency, payload))

	def on_clock_edge(self, cycles):
		"""时钟上升沿回调，由 dut.StepRis 驱动。"""
		self._cycles = cycles
		# 到期事务产生响应/驱动信号
		ready = [p for p in self._pending if p[0] <= cycles]
		if ready:
			for _, payload in ready:
				self._do_response(payload)
				self.stats['rsp'] += 1
			# 移除已完成事务
			self._pending = [p for p in self._pending if p[0] > cycles]

	def _do_response(self, payload):
		"""将响应写回到绑定的接口（示例）。"""
		if self.enable_log:
			print(f"[MockTemplate] cycles={self._cycles}, payload={payload}")
		# 示例：如果 io 有 'valid'/'data' 信号可驱动
		if hasattr(self.io, 'valid'):
			self.io.valid.value = 1
		if hasattr(self.io, 'data'):
			self.io.data.value = payload
```


## 示例一：AXI4-Lite 内存模型 Mock（简化）

该示例展示如何用 Bundle 封装 DUT 端口，并实现带可配置延迟的读写存储。

```python
from toffee import Bundle, Signals


class AXI4LiteBundle(Bundle):
	# 极简化信号：valid/ready/data 仅作示范，真实 AXI4-Lite 请按协议完整定义
	aw_valid, aw_ready, aw_addr = Signals(3)
	w_valid, w_ready, w_data = Signals(3)
	b_valid, b_ready, b_resp = Signals(3)
	ar_valid, ar_ready, ar_addr = Signals(3)
	r_valid, r_ready, r_data, r_resp = Signals(4)


class MockAXI4LiteMemory:
	"""简化的 AXI4-Lite 内存模型

	Args:
		read_latency: 读响应延迟（周期）
		write_latency: 写响应延迟（周期）
		size: 内存大小（字）
		init_value: 默认初始化值
	"""

	def __init__(self, read_latency=1, write_latency=0, size=1024, init_value=0):
		self.read_latency = read_latency
		self.write_latency = write_latency
		self.mem = [init_value] * size
		self._cycles = 0
		self._pending_w = []  # (ready_cycle, addr, data)
		self._pending_r = []  # (ready_cycle, addr)
		self.stats = {'read': 0, 'write': 0}

	def bind(self, dut):
		# 通过前缀绑定：例如 DUT 端口以 io_axi_ 开头
		self.axi = AXI4LiteBundle.from_prefix('io_axi_')
		self.axi.bind(dut)

	def reset(self):
		self._cycles = 0
		self._pending_w.clear()
		self._pending_r.clear()
		self.stats = {'read': 0, 'write': 0}

	def on_clock_edge(self, cycles):
		self._cycles = cycles

		# 写地址/数据握手（极简示范）
		if self.axi.aw_valid.value and self.axi.w_valid.value:
			addr = self.axi.aw_addr.value
			data = self.axi.w_data.value
			self._pending_w.append((cycles + self.write_latency, addr, data))
			self.stats['write'] += 1
			# 简化 ready 逻辑
			self.axi.aw_ready.value = 1
			self.axi.w_ready.value = 1

		# 处理到期写响应
		due_w = [x for x in self._pending_w if x[0] <= cycles]
		if due_w:
			for _, addr, data in due_w:
				if 0 <= addr < len(self.mem):
					self.mem[addr] = data
			# 返回写响应
			self.axi.b_valid.value = 1
			self.axi.b_resp.value = 0  # OKAY
			self._pending_w = [x for x in self._pending_w if x[0] > cycles]

		# 读地址握手
		if self.axi.ar_valid.value:
			addr = self.axi.ar_addr.value
			self._pending_r.append((cycles + self.read_latency, addr))
			self.stats['read'] += 1
			self.axi.ar_ready.value = 1

		# 处理到期读响应
		due_r = [x for x in self._pending_r if x[0] <= cycles]
		if due_r:
			for _, addr in due_r:
				data = self.mem[addr] if 0 <= addr < len(self.mem) else 0
				self.axi.r_valid.value = 1
				self.axi.r_data.value = data
				self.axi.r_resp.value = 0  # OKAY
			self._pending_r = [x for x in self._pending_r if x[0] > cycles]
```

在 env 中集成：

```python
class DUTEnv:
	def __init__(self, dut):
		self.dut = dut
		self.mem = MockAXI4LiteMemory(read_latency=2, write_latency=1)
		self.mem.bind(dut)
		self.mem.reset()
		self.dut.StepRis(self.mem.on_clock_edge)

	def Step(self, c=1):
		return self.dut.Step(c)
```


## 示例二：参考模型 Mock（功能比对）

用于对 DUT 输出进行黄金参考比对。适合组合/时序运算模块，如 ALU、编码器等。

```python
class MockAdderGolden:
	"""加法器参考模型，基于 DUT 当前输入给出期望输出，用于对比。"""

	def __init__(self, bundle):
		self.io = bundle  # 已与 DUT 绑定的 Bundle
		self.errors = 0

	def reset(self):
		self.errors = 0

	def on_clock_edge(self, cycles):
		a = getattr(self.io, 'a').value if hasattr(self.io, 'a') else None
		b = getattr(self.io, 'b').value if hasattr(self.io, 'b') else None
		sum_sig = getattr(self.io, 'sum') if hasattr(self.io, 'sum') else None
		if a is not None and b is not None and sum_sig is not None:
			expect = (a + b) & ((1 << sum_sig.width) - 1) if hasattr(sum_sig, 'width') else a + b
			got = sum_sig.value
			if got is not None and expect != got:
				self.errors += 1
				print(f"[MockAdderGolden][C{cycles}] expect={expect}, got={got}")
```

集成方式：将 DUT 端口封装到 Bundle，绑定后注册 `StepRis(self.golden.on_clock_edge)`；测试里可断言 `golden.errors == 0`，或将错误累计交由覆盖/报告模块处理。


## 高级话题

- 多 Mock 协同：为不同接口分别注册回调，或在一个回调中按优先级调度，避免竞态
- 参数化：可配合 pytest parametrize，生成不同延迟/带宽的环境变体（如 `env_slow`, `env_fast`）
- 随机性与可复现：统一通过 `seed` 控制随机模块，必要时将 `seed` 写入报告
- 日志与性能：长仿真中谨慎打印；提供 `enable_log`/`log_interval` 控制


## 常见问题排查

1) 回调不生效：
- 是否调用了 `dut.StepRis(mock.on_clock_edge)`？是否实际推进了 `dut.Step(...)`？
- 组合电路仅 `RefreshComb` 不会触发 StepRis，必须 `Step(1)`

1) 死锁/事务不前进：
- 检查 valid/ready 或 req/resp 的握手机制是否对齐；确认回调里是否正确更新握手信号

1) 随机导致不可复现：
- 保证所有随机路径受相同 `seed` 控制；在日志中记录 `seed`


## 开发检查清单（Checklist）

- [ ] Mock 类名以 `Mock` 开头，并位于 `{OUT}/tests/{DUT}_api.py`
- [ ] 在 env 中实例化并通过 `dut.StepRis(...)` 注册回调
- [ ] 需要提供bind方法与 DUT 的引脚(直接引脚或者对应的Bundle封装)进行连接，支持 `reset()/clear()`
- [ ] 需要有函数：`on_clock_edge(self, cycles)`
- [ ] 提供必要的配置参数（延迟、深度、背压等）与统计信息
- [ ] 关键方法和类提供中文注释，便于协作与审阅
- [ ] 通过一个最小单元测试/示例验证 Mock 行为正确


参考文档：
- `Guide_Doc/dut_fixture.md`
