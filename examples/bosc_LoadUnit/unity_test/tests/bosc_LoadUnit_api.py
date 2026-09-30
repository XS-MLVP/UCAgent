#coding=utf-8

import json
import os
from typing import Any, Dict

import pytest
import ucagent
from bosc_LoadUnit_function_coverage_def import get_coverage_groups
from toffee import Bundle
from toffee_test.reporter import get_file_in_tmp_dir, set_func_coverage, set_line_coverage
from toffee_test.reporter import set_title_info, set_user_info

# import your dut module here
import bosc_LoadUnit as _bosc_LoadUnit_module
from bosc_LoadUnit import DUTbosc_LoadUnit  # Replace with the actual DUT class import


def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def _signal_tree_path():
    generated_path = os.path.join(os.path.dirname(os.path.abspath(_bosc_LoadUnit_module.__file__)), "signals.json")
    if os.path.exists(generated_path):
        return generated_path
    return os.path.abspath(current_path_file("../../bosc_LoadUnit/signals.json"))


def _is_pin_desc(node):
    return isinstance(node, dict) and "Pin" in node


def _bundle_class_name(path_items):
    tokens = []
    for item in path_items:
        cleaned = "".join(char if char.isalnum() else "_" for char in item)
        for token in cleaned.strip("_").split("_"):
            if not token:
                continue
            if token[0].isdigit():
                token = f"n{token}"
            tokens.append(token[0].upper() + token[1:])
    return "".join(tokens) + "Bundle"


def _build_bundle_class(path_items, tree_node):
    attrs = {"signals": []}
    for key, value in tree_node.items():
        if key == "_":
            continue
        if _is_pin_desc(value):
            attrs["signals"].append(key)
            continue
        child_cls = _build_bundle_class(path_items + (key,), value)
        attrs[key] = child_cls.from_prefix(f"{key}_")
    return type(_bundle_class_name(path_items), (Bundle,), attrs)


with open(_signal_tree_path(), "r", encoding="utf-8") as signal_tree_file:
    _LOADUNIT_SIGNAL_TREE = json.load(signal_tree_file)

LoadUnitSystemBundle = _build_bundle_class(
    ("loadunit", "system"),
    {
        "clock": _LOADUNIT_SIGNAL_TREE["clock"],
        "reset": _LOADUNIT_SIGNAL_TREE["reset"],
    },
)
LoadUnitIoBundle = _build_bundle_class(("loadunit", "io"), _LOADUNIT_SIGNAL_TREE["io"])


def get_coverage_data_path(request, new_path:bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    # 获取测试用例名称，为每个测试用例创建对应的代码行覆盖率文件
    tc_name = request.node.name if request is not None else "bosc_LoadUnit"
    return get_file_in_tmp_dir(request, current_path_file("data/"), f"{tc_name}.dat",  new_path=new_path)


def get_waveform_path(request, new_path:bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    # 获取测试用例名称，为每个测试用例创建对应的波形
    tc_name = request.node.name if request is not None else "bosc_LoadUnit"
    return get_file_in_tmp_dir(request, current_path_file("data/"), f"{tc_name}.fst",  new_path=new_path)


def create_dut(request):
    """
    Create a new instance of the bosc_LoadUnit for testing.
    
    Returns:
        dut_instance: An instance of the bosc_LoadUnit class.
    """
    # 如果是正在生成测试模板，返回fake DUT用于提速（模板中不会真运行DUT）
    if ucagent.is_imp_test_template():
        return ucagent.get_fake_dut(DUTbosc_LoadUnit)

    # Replace with the actual instantiation and initialization of your DUT
    dut = DUTbosc_LoadUnit()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(get_coverage_data_path(request, new_path=True))

    # 设置波形生成文件
    dut.SetWaveform(get_waveform_path(request, new_path=True))

    # LoadUnit 是时序电路，创建后立即绑定主时钟
    dut.InitClock("clock")

    return dut


@pytest.fixture(scope="function") # 用scope="function"确保每个测试用例都创建了一个全新的DUT
def dut(request):
    dut = create_dut(request)                         # 创建DUT
    func_coverage_group = get_coverage_groups(dut)
    # 时钟已在 create_dut 中完成绑定，这里只负责覆盖率采样与生命周期管理

    # 上升沿采样，StepRis也适用于组合电路用dut.Step推进时采样.
    # 必须要有g.sample()采样覆盖组, 如何不在StepRis/StepFal中采样，则需要在test function中手动调用，否则无法统计覆盖率导致失败
    dut.StepRis(lambda _: [g.sample()
                           for g in
                           func_coverage_group])

    # 以属性名称fc_cover保存覆盖组到DUT
    setattr(dut, "fc_cover",
            {g.name:g for g in func_coverage_group})

    # 返回DUT实例
    yield dut

    # 测试后处理
    # 需要在测试结束的时候，通过set_func_coverage把覆盖组传递给toffee_test*
    set_func_coverage(request, func_coverage_group)

    # 设置需要收集的代码行覆盖率文件(获取已有路径new_path=False) 向toffee_test传代码行递覆盖率数据
    # 代码行覆盖率 ignore 文件的固定路径为当前文件所在目录下的：bosc_LoadUnit.ignore，请不要改变
    set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("bosc_LoadUnit.ignore"))

    # 设置用户信息到报告
    set_user_info("UCAgent-26.4.18.dev65+g53aeab81c", "unitychip@bosc.ac.cn")
    set_title_info("bosc_LoadUnit Test Report")

    for g in func_coverage_group:                        # 采样覆盖组
        g.clear()                                        # 清空统计
    dut.Finish()                                         # 清理DUT，每个DUT class 都有 Finish 方法

@pytest.fixture(scope="function") # 用scope="function"确保每个测试用例都创建了一个全新的 Mock DUT
def mock_dut():
    return ucagent.get_mock_dut_from(DUTbosc_LoadUnit)

# 定义bosc_LoadUnitEnv类，封装DUT的引脚和常用操作
class bosc_LoadUnitEnv:
    """封装 LoadUnit 的系统引脚和完整 io 端口树。"""

    def __init__(self, dut):
        self.dut = dut
        # clock/reset 没有共同前缀，使用 from_dict 显式绑定。
        self.system = LoadUnitSystemBundle.from_dict({
            "clock": "clock",
            "reset": "reset",
        })
        self.system.bind(dut)

        # 其余端口严格按 signals.json 的层次生成 Bundle，并通过 io_ 前缀绑定。
        self.io = LoadUnitIoBundle.from_prefix("io_")
        self.io.bind(dut)

        # 常用事务接口别名，后续 env API 和 mock 组件直接复用这些分组。
        self.reset_pin = self.system.reset
        self.redirect = self.io.redirect
        self.csr_ctrl = self.io.csrCtrl
        self.scalar_req = self.io.ldin
        self.scalar_resp = self.io.ldout
        self.vector_req = self.io.vecldin
        self.vector_resp = self.io.vecldout
        self.replay = self.io.replay
        self.fast_rep = self.io.fast_rep
        self.lsq = self.io.lsq
        self.misalign = self.io.misalign
        self.tlb = self.io.tlb
        self.dcache = self.io.dcache
        self.prefetch = self.io.prefetch
        self.wakeup = self.io.wakeup
        self.feedback_slow = self.io.feedback_slow
        self.rollback = self.io.rollback
        self.forward_mshr = self.io.forward_mshr
        self.sbuffer = self.io.sbuffer
        self.ubuffer = self.io.ubuffer
        self.from_csr_trigger = self.io.fromCsrTrigger
        self.stld_nuke_query = self.io.stld_nuke_query
        self.tl_d_channel = self.io.tl_d_channel
        self.pmp = self.io.pmp
        self.ld_cancel_ld1 = getattr(dut, "io_ldCancel_ld1Cancel", None)
        self.ld_cancel_ld2 = getattr(dut, "io_ldCancel_ld2Cancel", None)
        self.misalign_allow_spec = getattr(dut, "io_misalign_allow_spec", None)

        self.set_default_inputs()

    # 根据需要添加清空Env注册的回调函数
    # def clear_cbs(self):
    #     self.dut.xclock.RemoveStepRisCbByDesc(self.handle_axi_transactions.__name__)
    #     ...

    def clear_inputs(self):
        # 只清零输入引脚；clock 由 InitClock 负责推进，不在 env 中直接驱动。
        self.io.set_all(0)
        self.reset_pin.value = 0
        if self.misalign_allow_spec is not None:
            self.misalign_allow_spec.value = 0
        return self

    def set_default_inputs(self):
        # 为常见下游消费接口提供安全的默认 ready，避免基础场景被背压卡死。
        self.clear_inputs()
        self.scalar_resp.ready.value = 1
        self.lsq.ldld_nuke_query.req.ready.value = 1
        self.lsq.stld_nuke_query.req.ready.value = 1
        self.misalign.enq_req.ready.value = 1
        self.dcache.req.ready.value = 1
        return self

    def reset(self, cycles:int = 2):
        self.set_default_inputs()
        self.reset_pin.value = 1
        self.dut.Step(cycles)
        self.reset_pin.value = 0
        self.dut.Step(1)
        return self

    def Finish(self):
        return self.dut.Finish()

    # 直接导出DUT的通用操作Step
    def Step(self, i:int = 1):
        return self.dut.Step(i)


# 定义env fixture, 请取消下面的注释，并根据需要修改名称
@pytest.fixture(scope="function") # 用scope="function"确保每个测试用例都创建了一个全新的Env
def env(dut):
    # 一般情况下为每个test都创建全新的 env 不需要 yield
    return bosc_LoadUnitEnv(dut)


def _set_flag_value(flag_value_bundle, value: int, flag: int = 1):
    flag_value_bundle.flag.value = int(flag)
    flag_value_bundle.value.value = int(value)


def _fill_scalar_load_request(
    env,
    src0: int,
    fu_op_type: int,
    rob_idx: int,
    lq_idx: int,
    sq_idx: int,
    pc: int,
    store_set_hit: int = 0,
):
    env.scalar_req.bits.src["0"].value = int(src0)
    env.scalar_req.bits.uop.pc.value = int(pc)
    env.scalar_req.bits.uop.fuOpType.value = int(fu_op_type)
    env.scalar_req.bits.uop.fuType.value = 0
    env.scalar_req.bits.uop.rfWen.value = 1
    env.scalar_req.bits.uop.fpWen.value = 0
    env.scalar_req.bits.uop.imm.value = 0
    env.scalar_req.bits.uop.pdest.value = 1
    env.scalar_req.bits.uop.ftqOffset.value = 0
    env.scalar_req.bits.uop.ssid.value = 0
    env.scalar_req.bits.uop.storeSetHit.value = int(store_set_hit)
    env.scalar_req.bits.uop.loadWaitBit.value = 0
    env.scalar_req.bits.uop.loadWaitStrict.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.valid.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.isRVC.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.brType.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.isCall.value = 0
    env.scalar_req.bits.uop.preDecodeInfo.isRet.value = 0
    _set_flag_value(env.scalar_req.bits.uop.robIdx, rob_idx)
    _set_flag_value(env.scalar_req.bits.uop.lqIdx, lq_idx)
    _set_flag_value(env.scalar_req.bits.uop.sqIdx, sq_idx)
    _set_flag_value(env.scalar_req.bits.uop.ftqPtr, 0, flag=0)
    _set_flag_value(env.scalar_req.bits.uop.waitForRobIdx, 0, flag=0)


def _fill_vector_load_request(
    env,
    vaddr: int,
    mask: int,
    reg_offset: int,
    elem_idx: int,
    elem_idx_inside_vd: int,
    aligned_type: int,
    vec_active: int,
    rob_idx: int,
    lq_idx: int,
    pc: int,
):
    env.vector_req.bits.vaddr.value = int(vaddr)
    env.vector_req.bits.basevaddr.value = int(vaddr & ((1 << 50) - 1))
    env.vector_req.bits.mask.value = int(mask)
    env.vector_req.bits.reg_offset.value = int(reg_offset)
    env.vector_req.bits.elemIdx.value = int(elem_idx)
    env.vector_req.bits.elemIdxInsideVd.value = int(elem_idx_inside_vd)
    env.vector_req.bits.alignedType.value = int(aligned_type)
    env.vector_req.bits.vecActive.value = int(vec_active)
    env.vector_req.bits.mBIndex.value = 0
    env.vector_req.bits.uop.pc.value = int(pc)
    env.vector_req.bits.uop.instr.value = 0
    env.vector_req.bits.uop.foldpc.value = 0
    env.vector_req.bits.uop.fuType.value = 0
    env.vector_req.bits.uop.fuOpType.value = 0
    env.vector_req.bits.uop.rfWen.value = 0
    env.vector_req.bits.uop.fpWen.value = 0
    env.vector_req.bits.uop.vecWen.value = 1
    env.vector_req.bits.uop.v0Wen.value = 0
    env.vector_req.bits.uop.vlWen.value = 0
    env.vector_req.bits.uop.hasException.value = 0
    env.vector_req.bits.uop.isFetchMalAddr.value = 0
    env.vector_req.bits.uop.waitForward.value = 0
    env.vector_req.bits.uop.blockBackward.value = 0
    env.vector_req.bits.uop.preDecodeInfo.valid.value = 0
    env.vector_req.bits.uop.preDecodeInfo.isRVC.value = 0
    env.vector_req.bits.uop.preDecodeInfo.brType.value = 0
    env.vector_req.bits.uop.preDecodeInfo.isCall.value = 0
    env.vector_req.bits.uop.preDecodeInfo.isRet.value = 0
    _set_flag_value(env.vector_req.bits.uop.robIdx, rob_idx)
    _set_flag_value(env.vector_req.bits.uop.lqIdx, lq_idx)
    _set_flag_value(env.vector_req.bits.uop.ftqPtr, 0, flag=0)
    _set_flag_value(env.vector_req.bits.uop.sqIdx, 0, flag=0)
    _set_flag_value(env.vector_req.bits.uop.waitForRobIdx, 0, flag=0)


def _fill_misalign_blocker_request(env, src_addr: int, rob_idx: int = 2, lq_idx: int = 2):
    env.misalign.ldin.bits.fullva.value = int(src_addr)
    env.misalign.ldin.bits.vaddr.value = int(src_addr)
    env.misalign.ldin.bits.mask.value = 0xF
    env.misalign.ldin.bits.is128bit.value = 0
    env.misalign.ldin.bits.isFinalSplit.value = 0
    env.misalign.ldin.bits.isvec.value = 0
    env.misalign.ldin.bits.memBackTypeMM.value = 0
    env.misalign.ldin.bits.misalignNeedWakeUp.value = 0
    env.misalign.ldin.bits.mmio.value = 0
    env.misalign.ldin.bits.mshrid.value = 0
    env.misalign.ldin.bits.nc.value = 0
    env.misalign.ldin.bits.schedIndex.value = 0
    env.misalign.ldin.bits.vecActive.value = 0
    env.misalign.ldin.bits.uop.pc.value = int(src_addr)
    env.misalign.ldin.bits.uop.fuOpType.value = 0
    env.misalign.ldin.bits.uop.rfWen.value = 1
    env.misalign.ldin.bits.uop.fpWen.value = 0
    _set_flag_value(env.misalign.ldin.bits.uop.robIdx, rob_idx)
    _set_flag_value(env.misalign.ldin.bits.uop.lqIdx, lq_idx)
    _set_flag_value(env.misalign.ldin.bits.uop.sqIdx, 0)
    _set_flag_value(env.misalign.ldin.bits.uop.ftqPtr, 0, flag=0)
    _set_flag_value(env.misalign.ldin.bits.uop.waitForRobIdx, 0, flag=0)


def _fill_uncache_mmio_request(env, rob_idx: int, lq_idx: int, sq_idx: int, pc: int, pdest: int = 1):
    env.lsq.uncache.bits.uop.pc.value = int(pc)
    env.lsq.uncache.bits.uop.fuOpType.value = 0
    env.lsq.uncache.bits.uop.fuType.value = 0
    env.lsq.uncache.bits.uop.rfWen.value = 1
    env.lsq.uncache.bits.uop.fpWen.value = 0
    env.lsq.uncache.bits.uop.imm.value = 0
    env.lsq.uncache.bits.uop.pdest.value = int(pdest)
    env.lsq.uncache.bits.uop.ftqOffset.value = 0
    env.lsq.uncache.bits.uop.ssid.value = 0
    env.lsq.uncache.bits.uop.storeSetHit.value = 0
    env.lsq.uncache.bits.uop.loadWaitBit.value = 0
    env.lsq.uncache.bits.uop.loadWaitStrict.value = 0
    env.lsq.uncache.bits.uop.preDecodeInfo.valid.value = 0
    env.lsq.uncache.bits.uop.preDecodeInfo.isRVC.value = 0
    env.lsq.uncache.bits.uop.preDecodeInfo.brType.value = 0
    env.lsq.uncache.bits.uop.preDecodeInfo.isCall.value = 0
    env.lsq.uncache.bits.uop.preDecodeInfo.isRet.value = 0
    _set_flag_value(env.lsq.uncache.bits.uop.robIdx, rob_idx)
    _set_flag_value(env.lsq.uncache.bits.uop.lqIdx, lq_idx)
    _set_flag_value(env.lsq.uncache.bits.uop.sqIdx, sq_idx)
    _set_flag_value(env.lsq.uncache.bits.uop.ftqPtr, 0, flag=0)
    _set_flag_value(env.lsq.uncache.bits.uop.waitForRobIdx, 0, flag=0)


def _fill_nc_load_request(
    env,
    vaddr: int,
    paddr: int,
    data: int,
    fu_op_type: int,
    rob_idx: int,
    lq_idx: int,
    sq_idx: int,
    pc: int,
    pdest: int = 1,
    store_set_hit: int = 0,
    is128bit: bool = False,
    vec_active: int = 1,
):
    env.lsq.nc_ldin.bits.vaddr.value = int(vaddr)
    env.lsq.nc_ldin.bits.paddr.value = int(paddr)
    env.lsq.nc_ldin.bits.data.value = int(data)
    env.lsq.nc_ldin.bits.is128bit.value = int(bool(is128bit))
    env.lsq.nc_ldin.bits.isvec.value = 0
    env.lsq.nc_ldin.bits.vecActive.value = int(vec_active)
    env.lsq.nc_ldin.bits.schedIndex.value = 0
    env.lsq.nc_ldin.bits.uop.pc.value = int(pc)
    env.lsq.nc_ldin.bits.uop.fuOpType.value = int(fu_op_type)
    env.lsq.nc_ldin.bits.uop.fuType.value = 0
    env.lsq.nc_ldin.bits.uop.rfWen.value = 1
    env.lsq.nc_ldin.bits.uop.fpWen.value = 0
    env.lsq.nc_ldin.bits.uop.imm.value = 0
    env.lsq.nc_ldin.bits.uop.pdest.value = int(pdest)
    env.lsq.nc_ldin.bits.uop.ftqOffset.value = 0
    env.lsq.nc_ldin.bits.uop.ssid.value = 0
    env.lsq.nc_ldin.bits.uop.storeSetHit.value = int(store_set_hit)
    env.lsq.nc_ldin.bits.uop.loadWaitBit.value = 0
    env.lsq.nc_ldin.bits.uop.loadWaitStrict.value = 0
    env.lsq.nc_ldin.bits.uop.preDecodeInfo.valid.value = 0
    env.lsq.nc_ldin.bits.uop.preDecodeInfo.isRVC.value = 0
    env.lsq.nc_ldin.bits.uop.preDecodeInfo.brType.value = 0
    env.lsq.nc_ldin.bits.uop.preDecodeInfo.isCall.value = 0
    env.lsq.nc_ldin.bits.uop.preDecodeInfo.isRet.value = 0
    _set_flag_value(env.lsq.nc_ldin.bits.uop.robIdx, rob_idx)
    _set_flag_value(env.lsq.nc_ldin.bits.uop.lqIdx, lq_idx)
    _set_flag_value(env.lsq.nc_ldin.bits.uop.sqIdx, sq_idx)
    _set_flag_value(env.lsq.nc_ldin.bits.uop.ftqPtr, 0, flag=0)
    _set_flag_value(env.lsq.nc_ldin.bits.uop.waitForRobIdx, 0, flag=0)


def _clear_memory_response_inputs(env):
    env.tlb.resp.valid.value = 0
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = 0
    if hasattr(env.tlb.resp.bits.paddr, "1"):
        getattr(env.tlb.resp.bits.paddr, "1").value = 0
    env.tlb.resp.bits.excp["0"].pf_ld.value = 0
    env.tlb.resp.bits.excp["0"].gpf_ld.value = 0
    env.tlb.resp.bits.excp["0"].af_ld.value = 0
    env.tlb.resp.bits.excp["0"].isHyper.value = 0
    env.tlb.resp.bits.excp["0"].vaNeedExt.value = 0
    env.pmp.ld.value = 0
    env.pmp.st.value = 0
    env.pmp.mmio.value = 0
    env.dcache.resp_bits.miss.value = 0
    env.dcache.resp_bits.data.value = 0
    env.dcache.resp_bits.handled.value = 0
    env.dcache.resp_bits.meta_prefetch.value = 0
    env.dcache.resp_bits.mshr_id.value = 0
    env.dcache.resp_bits.tl_error_delayed_tl.denied.value = 0
    env.dcache.resp_bits.tl_error_delayed_tl.corrupt.value = 0
    env.dcache.s2.bank_conflict.value = 0
    env.dcache.s2.mq_nack.value = 0
    env.lsq.forward.addrInvalid.value = 0
    env.lsq.forward.dataInvalid.value = 0
    env.lsq.forward.matchInvalid.value = 0
    env.lsq.forward.addrInvalidSqIdx.flag.value = 0
    env.lsq.forward.addrInvalidSqIdx.value.value = 0
    env.lsq.forward.dataInvalidSqIdx.flag.value = 0
    env.lsq.forward.dataInvalidSqIdx.value.value = 0
    env.sbuffer.matchInvalid.value = 0
    env.ubuffer.matchInvalid.value = 0
    for idx in range(16):
        getattr(env.lsq.forward.forwardData, str(idx)).value = 0
        getattr(env.lsq.forward.forwardMask, str(idx)).value = 0
        getattr(env.sbuffer.forwardData, str(idx)).value = 0
        getattr(env.sbuffer.forwardMask, str(idx)).value = 0
        getattr(env.ubuffer.forwardData, str(idx)).value = 0
        getattr(env.ubuffer.forwardMask, str(idx)).value = 0


def _drive_forward_group(group, data: int, mask: int):
    for idx in range(16):
        getattr(group.forwardData, str(idx)).value = (int(data) >> (idx * 8)) & 0xFF
        getattr(group.forwardMask, str(idx)).value = (int(mask) >> idx) & 0x1


def _capture_loadunit_outputs(env) -> Dict[str, Any]:
    return {
        "scalar_writeback": env.scalar_resp.bits.as_dict() if env.scalar_resp.valid.value else None,
        "vector_writeback": env.vector_resp.bits.as_dict() if env.vector_resp.valid.value else None,
        "wakeup": env.wakeup.bits.as_dict() if env.wakeup.valid.value else None,
        "feedback_slow": env.feedback_slow.bits.as_dict() if env.feedback_slow.valid.value else None,
        "rollback": env.rollback.bits.as_dict() if env.rollback.valid.value else None,
        "ld_cancel_ld1": 1 if env.ld_cancel_ld1 is not None and int(env.ld_cancel_ld1.value) else None,
        "ld_cancel_ld2": 1 if env.ld_cancel_ld2 is not None and int(env.ld_cancel_ld2.value) else None,
        "misalign_ldout": env.misalign.ldout.bits.as_dict() if env.misalign.ldout.valid.value else None,
        "misalign_enq": env.misalign.enq_req.bits.as_dict() if env.misalign.enq_req.valid.value else None,
        "ifetch_prefetch_vaddr": env.io.ifetchPrefetch.bits_vaddr.value if env.io.ifetchPrefetch.valid.value else None,
    }


def api_bosc_LoadUnit_reset(env, reset_cycles: int = 2, max_cycles: int = 8) -> Dict[str, int]:
    """执行 LoadUnit 的标准复位序列并推进时钟。

    该 API 封装了 `bosc_LoadUnitEnv.reset()`，用于统一执行基础复位与时钟推进。
    复位前会恢复 env 的默认输入基线，复位释放后再额外推进 1 拍，便于后续请求直接发射。

    Args:
        env: bosc_LoadUnit 的 env fixture，必须是已完成初始化的 `bosc_LoadUnitEnv`。
        reset_cycles (int): `reset` 拉高维持的时钟周期数，必须为正整数。
        max_cycles (int): API 允许消耗的最大周期预算，必须不小于 `reset_cycles + 1`。

    Returns:
        Dict[str, int]: 复位执行摘要，包含 `reset_cycles` 与 `consumed_cycles`。

    Raises:
        ValueError: 当 `reset_cycles` 非正数或 `max_cycles` 过小时抛出。

    Example:
        >>> api_bosc_LoadUnit_reset(env, reset_cycles=2, max_cycles=8)

    Note:
        - API 底层通过 `env.reset()` 和 `Step()` 驱动时序电路。
        - 该 API 不尝试检查 DUT 功能正确性，只负责提供稳定的初始状态。
    """
    if reset_cycles <= 0:
        raise ValueError(f"reset_cycles 必须大于 0，当前值为 {reset_cycles}")
    if max_cycles < reset_cycles + 1:
        raise ValueError(
            f"max_cycles 必须不小于 reset_cycles + 1，当前值为 {max_cycles}"
        )

    env.reset(reset_cycles)
    return {
        "reset_cycles": int(reset_cycles),
        "consumed_cycles": int(reset_cycles + 1),
    }


def api_bosc_LoadUnit_send_scalar_load(
    env,
    src0: int,
    fu_op_type: int = 0,
    rob_idx: int = 1,
    lq_idx: int = 1,
    sq_idx: int = 0,
    pc: int = 0x1000,
    store_set_hit: int = 0,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """通过 `io_ldin` 发送一个标准标量 load 请求。

    该 API 负责统一填充标量请求的基础 uop 元数据，并在 ready/valid 握手完成前保持
    `io_ldin_valid` 和关键载荷稳定。适合后续测试直接调用，而不必逐字段手写接口驱动。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        src0 (int): 作为 load 地址基值使用的源操作数，写入 `io_ldin_bits_src_0`。
        fu_op_type (int): Load 操作类型编码，写入 `io_ldin_bits_uop_fuOpType`。
        rob_idx (int): ROB 索引值，写入 `uop.robIdx`。
        lq_idx (int): LoadQueue 索引值，写入 `uop.lqIdx`。
        sq_idx (int): StoreQueue 索引值，写入 `uop.sqIdx`。
        pc (int): 该请求的程序计数器字段。
        store_set_hit (int): `uop.storeSetHit` 输入，用于驱动依赖 store set 的前递/违例场景。
        max_cycles (int): 最多等待多少拍完成握手。

    Returns:
        Dict[str, Any]: 发送结果摘要，包含是否握手成功、等待周期和最终请求镜像。

    Raises:
        TimeoutError: 当在 `max_cycles` 周期内始终未等到 `io_ldin_ready` 时抛出。

    Example:
        >>> api_bosc_LoadUnit_send_scalar_load(env, src0=0x1000, fu_op_type=0)

    Note:
        - 握手判断依据是“本拍 ready 为 1 且本拍 valid 保持有效，然后推进 1 拍”。
        - 该 API 只负责请求发射，不保证后续一定写回，需要配合响应注入或输出采集 API 使用。
    """
    if max_cycles <= 0:
        raise ValueError(f"max_cycles 必须大于 0，当前值为 {max_cycles}")
    if min(src0, fu_op_type, rob_idx, lq_idx, sq_idx, pc, store_set_hit) < 0:
        raise ValueError("标量 load 请求参数不允许为负数")

    env.set_default_inputs()
    _fill_scalar_load_request(
        env,
        src0,
        fu_op_type,
        rob_idx,
        lq_idx,
        sq_idx,
        pc,
        store_set_hit=store_set_hit,
    )
    env.scalar_req.valid.value = 1

    for waited_cycles in range(max_cycles):
        ready_now = int(env.scalar_req.ready.value)
        env.Step(1)
        if ready_now:
            env.scalar_req.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited_cycles,
                "request": env.scalar_req.bits.as_dict(),
            }

    env.scalar_req.valid.value = 0
    raise TimeoutError("标量 load 请求在 max_cycles 内未完成 ready/valid 握手")


def api_bosc_LoadUnit_send_misalign_buffer_load(
    env,
    vaddr: int,
    mask: int = 0x0F,
    rob_idx: int = 1,
    lq_idx: int = 1,
    sq_idx: int = 0,
    pc: int = 0x1000,
    fu_op_type: int = 0,
    is_final_split: bool = False,
    misalign_need_wakeup: bool = False,
    is128bit: bool = False,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """通过 `io_misalign_ldin` 发送一条来自 MisalignBuffer 的重发请求。

    该 API 用于驱动非对齐 load 的第二次/第三次/第四次上流水路径。它会封装
    `io_misalign_ldin` 的关键字段填写方式，并在 ready/valid 握手完成前保持请求稳定，
    便于 testcase 针对 first split / final split / needWakeUp 分支做定向验证。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        vaddr (int): MisalignBuffer 重发请求的虚拟地址，同时写入 `vaddr/fullva`。
        mask (int): 本次对齐子请求的字节 mask。
        rob_idx (int): ROB 索引值。
        lq_idx (int): LoadQueue 索引值。
        sq_idx (int): StoreQueue 索引值。
        pc (int): 程序计数器字段。
        fu_op_type (int): Misalign 子请求的 load 操作类型编码。
        is_final_split (bool): 是否为最终拆分子请求。
        misalign_need_wakeup (bool): 是否走 `misalignNeedWakeUp` 直接唤醒分支。
        is128bit (bool): 是否按 128bit 子请求属性发射。
        max_cycles (int): 最大握手等待周期数。

    Returns:
        Dict[str, Any]: 发送结果摘要，包含握手状态、等待周期和请求镜像。

    Raises:
        TimeoutError: 当在 `max_cycles` 周期内未等到 `io_misalign_ldin_ready` 时抛出。
        ValueError: 当参数非法时抛出。
    """
    if max_cycles <= 0:
        raise ValueError(f"max_cycles 必须大于 0，当前值为 {max_cycles}")
    if min(vaddr, mask, rob_idx, lq_idx, sq_idx, pc, fu_op_type) < 0:
        raise ValueError("misalign buffer load 请求参数不允许为负数")

    env.set_default_inputs()
    _fill_misalign_blocker_request(env, vaddr, rob_idx=rob_idx, lq_idx=lq_idx)
    env.misalign.ldin.bits.mask.value = int(mask)
    env.misalign.ldin.bits.is128bit.value = int(bool(is128bit))
    env.misalign.ldin.bits.isFinalSplit.value = int(bool(is_final_split))
    env.misalign.ldin.bits.misalignNeedWakeUp.value = int(bool(misalign_need_wakeup))
    env.misalign.ldin.bits.uop.pc.value = int(pc)
    env.misalign.ldin.bits.uop.fuOpType.value = int(fu_op_type)
    _set_flag_value(env.misalign.ldin.bits.uop.sqIdx, sq_idx)
    env.misalign.ldin.valid.value = 1

    for waited_cycles in range(max_cycles):
        ready_now = int(env.misalign.ldin.ready.value)
        env.Step(1)
        if ready_now:
            env.misalign.ldin.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited_cycles,
                "request": env.misalign.ldin.bits.as_dict(),
            }

    env.misalign.ldin.valid.value = 0
    raise TimeoutError("misalign buffer load 请求在 max_cycles 内未完成 ready/valid 握手")


def api_bosc_LoadUnit_hold_scalar_load_under_backpressure(
    env,
    src0: int,
    fu_op_type: int = 0,
    rob_idx: int = 1,
    lq_idx: int = 1,
    sq_idx: int = 0,
    pc: int = 0x1000,
    hold_cycles: int = 3,
    max_cycles: int = 8,
) -> Dict[str, Any]:
    """制造标量 load 输入背压并保持请求载荷稳定。

    该 API 用高优先级 `misalign.ldin` 请求占用 stage 0，使普通 `io_ldin` 请求在
    `valid=1, ready=0` 状态下停留多个周期，用于验证接口封装不会在背压期间修改或丢失请求载荷。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        src0 (int): 标量 load 的源地址字段。
        fu_op_type (int): 标量 load 的操作类型编码。
        rob_idx (int): 标量请求 ROB 索引。
        lq_idx (int): 标量请求 LoadQueue 索引。
        sq_idx (int): 标量请求 StoreQueue 索引。
        pc (int): 标量请求 PC 字段。
        hold_cycles (int): 希望保持背压的周期数，至少为 2。
        max_cycles (int): API 的最大周期预算，必须不小于 `hold_cycles`。

    Returns:
        Dict[str, Any]: 背压保持结果，包含 ready 历史、保持前后的请求镜像和稳定性判断。

    Raises:
        ValueError: 当周期参数非法或请求字段为负数时抛出。

    Example:
        >>> api_bosc_LoadUnit_hold_scalar_load_under_backpressure(env, src0=0x1000)

    Note:
        - API 结束时会清除 `io_ldin_valid` 与 `misalign.ldin.valid`，并恢复默认输入基线。
        - 该 API 只用于验证 API 层背压保持行为，不表示 misalign 功能路径本身已被完整验证。
    """
    if hold_cycles < 2:
        raise ValueError(f"hold_cycles 必须大于等于 2，当前值为 {hold_cycles}")
    if max_cycles < hold_cycles:
        raise ValueError(f"max_cycles 必须不小于 hold_cycles，当前值为 {max_cycles}")
    if min(src0, fu_op_type, rob_idx, lq_idx, sq_idx, pc) < 0:
        raise ValueError("标量 load 背压请求参数不允许为负数")

    env.set_default_inputs()
    _fill_scalar_load_request(env, src0, fu_op_type, rob_idx, lq_idx, sq_idx, pc)
    _fill_misalign_blocker_request(env, src0 + 0x40)
    env.scalar_req.valid.value = 1
    env.misalign.ldin.valid.value = 1

    before = env.scalar_req.bits.as_dict()
    ready_history = []
    for _ in range(hold_cycles):
        env.Step(1)
        ready_history.append(int(env.scalar_req.ready.value))
    after = env.scalar_req.bits.as_dict()

    env.scalar_req.valid.value = 0
    env.misalign.ldin.valid.value = 0
    env.set_default_inputs()

    return {
        "held": any(ready == 0 for ready in ready_history),
        "stable": before == after,
        "ready_history": ready_history,
        "before": before,
        "after": after,
    }


def api_bosc_LoadUnit_send_vector_load(
    env,
    vaddr: int,
    mask: int = 0x1,
    reg_offset: int = 0,
    elem_idx: int = 0,
    elem_idx_inside_vd: int = 0,
    aligned_type: int = 0,
    vec_active: int = 1,
    rob_idx: int = 1,
    lq_idx: int = 1,
    pc: int = 0x1000,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """通过 `io_vecldin` 发送一个标准向量 load 请求。

    该 API 统一封装向量地址、mask、元素索引和关键 uop 字段的填写方式，并在
    `io_vecldin_ready` 拉高前持续保持请求稳定，便于构造向量路径的接口级测试。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        vaddr (int): 向量 load 请求的虚拟地址。
        mask (int): 16bit lane mask。
        reg_offset (int): 向量寄存器偏移。
        elem_idx (int): 元素索引。
        elem_idx_inside_vd (int): 元素在目标寄存器中的索引。
        aligned_type (int): 对齐类型编码。
        vec_active (int): 是否激活向量路径，通常为 1。
        rob_idx (int): ROB 索引值。
        lq_idx (int): LoadQueue 索引值。
        pc (int): 程序计数器字段。
        max_cycles (int): 最大握手等待周期数。

    Returns:
        Dict[str, Any]: 发送结果摘要，包含握手状态、等待周期和请求镜像。

    Raises:
        TimeoutError: 当在 `max_cycles` 周期内未等到 `io_vecldin_ready` 时抛出。

    Example:
        >>> api_bosc_LoadUnit_send_vector_load(env, vaddr=0x2000, mask=0x3)

    Note:
        - API 仅负责向量请求的发射，不自动注入 TLB/DCache 等后续响应。
        - 若需要测试字段填充，可直接检查返回字典中的 `request` 内容。
    """
    if max_cycles <= 0:
        raise ValueError(f"max_cycles 必须大于 0，当前值为 {max_cycles}")
    if min(vaddr, mask, reg_offset, elem_idx, elem_idx_inside_vd, aligned_type, vec_active, rob_idx, lq_idx, pc) < 0:
        raise ValueError("向量 load 请求参数不允许为负数")

    env.set_default_inputs()
    _fill_vector_load_request(
        env,
        vaddr,
        mask,
        reg_offset,
        elem_idx,
        elem_idx_inside_vd,
        aligned_type,
        vec_active,
        rob_idx,
        lq_idx,
        pc,
    )
    env.vector_req.valid.value = 1

    for waited_cycles in range(max_cycles):
        ready_now = int(env.vector_req.ready.value)
        env.Step(1)
        if ready_now:
            env.vector_req.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited_cycles,
                "request": env.vector_req.bits.as_dict(),
            }

    env.vector_req.valid.value = 0
    raise TimeoutError("向量 load 请求在 max_cycles 内未完成 ready/valid 握手")


def api_bosc_LoadUnit_send_mmio_load(
    env,
    rob_idx: int = 1,
    lq_idx: int = 1,
    sq_idx: int = 0,
    pc: int = 0x1000,
    pdest: int = 1,
    pmp_mmio_hint: bool = False,
    debug_vaddr: int | None = None,
    debug_paddr: int = 0,
    debug_is_mmio: bool | None = None,
    raw_data: int | None = None,
    raw_addr_offset: int = 0,
    raw_fu_op_type: int = 3,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """通过 `io_lsq_uncache` 发送一条 MMIO/uncache load 请求。

    该 API 用于驱动 LoadUnit 的 MMIO 第二次上流水路径。请求会经由 `io_lsq_uncache`
    进入 stage 0，因此可以观测到规格要求的“早唤醒”行为。`pmp_mmio_hint` 仅用于
    在黑盒测试中同步拉高 `io_pmp_mmio`，便于覆盖模型和测试断言区分普通 wakeup 与
    MMIO wakeup；该提示位本身并不参与 uncache 请求握手。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        rob_idx (int): MMIO 请求的 ROB 索引。
        lq_idx (int): MMIO 请求的 LoadQueue 索引。
        sq_idx (int): MMIO 请求的 StoreQueue 索引。
        pc (int): 请求 PC 字段。
        pdest (int): 目的寄存器索引。
        pmp_mmio_hint (bool): 是否在发射窗口内同步拉高 `io_pmp_mmio`。
        debug_vaddr (int | None): 可选的 MMIO debug 虚拟地址；缺省时沿用 `pc`。
        debug_paddr (int): 可选的 MMIO debug 物理地址。
        debug_is_mmio (bool | None): 可选的 MMIO debug 标志；缺省时跟随 `pmp_mmio_hint`。
        raw_data (int | None): 可选的 `io_lsq_ld_raw_data_lqData` 注入值。
        raw_addr_offset (int): `raw_data` 的地址偏移字段。
        raw_fu_op_type (int): `raw_data.uop.fuOpType`，默认按 64bit load 设置。
        max_cycles (int): 最多等待多少拍完成握手。

    Returns:
        Dict[str, Any]: 发送结果摘要，包含握手状态、等待周期和请求镜像。

    Raises:
        TimeoutError: 当在 `max_cycles` 周期内始终未等到 `io_lsq_uncache_ready` 时抛出。
        ValueError: 当参数非法时抛出。
    """
    if max_cycles <= 0:
        raise ValueError(f"max_cycles 必须大于 0，当前值为 {max_cycles}")
    if min(rob_idx, lq_idx, sq_idx, pc, pdest, debug_paddr, raw_addr_offset, raw_fu_op_type) < 0:
        raise ValueError("MMIO load 请求参数不允许为负数")
    if debug_vaddr is not None and debug_vaddr < 0:
        raise ValueError("MMIO load 请求的 debug_vaddr 不允许为负数")
    if raw_data is not None and raw_data < 0:
        raise ValueError("MMIO load 请求的 raw_data 不允许为负数")

    env.set_default_inputs()
    _fill_uncache_mmio_request(env, rob_idx, lq_idx, sq_idx, pc, pdest=pdest)
    env.pmp.mmio.value = int(bool(pmp_mmio_hint))
    env.lsq.uncache.bits.debug.vaddr.value = int(pc if debug_vaddr is None else debug_vaddr)
    env.lsq.uncache.bits.debug.paddr.value = int(debug_paddr)
    env.lsq.uncache.bits.debug.isMMIO.value = int(bool(pmp_mmio_hint) if debug_is_mmio is None else bool(debug_is_mmio))
    if raw_data is not None:
        env.lsq.ld_raw_data.addrOffset.value = int(raw_addr_offset)
        env.lsq.ld_raw_data.lqData.value = int(raw_data)
        env.lsq.ld_raw_data.uop.fuOpType.value = int(raw_fu_op_type)
        env.lsq.ld_raw_data.uop.fpWen.value = 0
    env.lsq.uncache.valid.value = 1

    for waited_cycles in range(max_cycles):
        ready_now = int(env.lsq.uncache.ready.value)
        env.Step(1)
        if ready_now:
            env.lsq.uncache.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited_cycles,
                "request": env.lsq.uncache.bits.as_dict(),
            }

    env.lsq.uncache.valid.value = 0
    raise TimeoutError("MMIO load 请求在 max_cycles 内未完成 ready/valid 握手")


def api_bosc_LoadUnit_send_nc_load(
    env,
    vaddr: int,
    paddr: int,
    data: int,
    fu_op_type: int = 3,
    rob_idx: int = 1,
    lq_idx: int = 1,
    sq_idx: int = 0,
    pc: int = 0x1000,
    pdest: int = 1,
    store_set_hit: int = 0,
    is128bit: bool = False,
    vec_active: int = 1,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """通过 `io_lsq_nc_ldin` 发送一条 non-cacheable load 请求。

    该 API 用于驱动 LoadUnit 的 NC 第二次上流水路径。请求会直接携带物理地址和可选
    的前递数据，因此适合验证 bypass-TLB、RAR/RAW 压力以及 NC 最终写回等场景。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        vaddr (int): NC 请求的虚拟地址，用于地址对齐/调试路径。
        paddr (int): NC 请求的物理地址。
        data (int): NC 路径可直接使用的前递/回填数据。
        fu_op_type (int): load 操作类型编码，默认使用 64bit load。
        rob_idx (int): ROB 索引值。
        lq_idx (int): LoadQueue 索引值。
        sq_idx (int): StoreQueue 索引值。
        pc (int): 请求 PC 字段。
        pdest (int): 目的寄存器索引。
        store_set_hit (int): `uop.storeSetHit` 输入，用于驱动前递歧义场景。
        is128bit (bool): 是否按 128bit NC 请求发送。
        vec_active (int): `vecActive` 字段，标量场景通常保持为 1。
        max_cycles (int): 最多等待多少拍完成握手。

    Returns:
        Dict[str, Any]: 发送结果摘要，包含握手状态、等待周期和请求镜像。

    Raises:
        TimeoutError: 当在 `max_cycles` 周期内始终未等到 `io_lsq_nc_ldin_ready` 时抛出。
        ValueError: 当参数非法时抛出。
    """
    if max_cycles <= 0:
        raise ValueError(f"max_cycles 必须大于 0，当前值为 {max_cycles}")
    if min(vaddr, paddr, data, fu_op_type, rob_idx, lq_idx, sq_idx, pc, pdest, store_set_hit, vec_active) < 0:
        raise ValueError("NC load 请求参数不允许为负数")

    env.set_default_inputs()
    _fill_nc_load_request(
        env,
        vaddr=vaddr,
        paddr=paddr,
        data=data,
        fu_op_type=fu_op_type,
        rob_idx=rob_idx,
        lq_idx=lq_idx,
        sq_idx=sq_idx,
        pc=pc,
        pdest=pdest,
        store_set_hit=store_set_hit,
        is128bit=is128bit,
        vec_active=vec_active,
    )
    env.lsq.nc_ldin.valid.value = 1

    for waited_cycles in range(max_cycles):
        ready_now = int(env.lsq.nc_ldin.ready.value)
        env.Step(1)
        if ready_now:
            env.lsq.nc_ldin.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited_cycles,
                "request": env.lsq.nc_ldin.bits.as_dict(),
            }

    env.lsq.nc_ldin.valid.value = 0
    raise TimeoutError("NC load 请求在 max_cycles 内未完成 ready/valid 握手")


def api_bosc_LoadUnit_send_nc_load_with_scalar_contender(
    env,
    nc_vaddr: int,
    nc_paddr: int,
    nc_data: int,
    scalar_src0: int,
    nc_fu_op_type: int = 3,
    scalar_fu_op_type: int = 3,
    nc_rob_idx: int = 1,
    nc_lq_idx: int = 1,
    nc_sq_idx: int = 0,
    scalar_rob_idx: int = 2,
    scalar_lq_idx: int = 2,
    scalar_sq_idx: int = 0,
    pc: int = 0x1000,
    max_cycles: int = 8,
) -> Dict[str, Any]:
    """同拍发射一条 NC 请求和一条标量请求，验证 NC 对低优先级请求的仲裁行为。

    该 API 用于构造 stage 0 同拍竞争场景：`io_lsq_nc_ldin` 与 `io_ldin` 同时有效，
    期望 NC 请求优先被选择，而标量请求保持等待或延后处理。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        nc_vaddr: NC 请求虚拟地址。
        nc_paddr: NC 请求物理地址。
        nc_data: NC 请求携带的数据。
        scalar_src0: 标量 load 的地址源操作数。
        nc_fu_op_type: NC 请求 load 类型编码。
        scalar_fu_op_type: 标量 load 类型编码。
        nc_rob_idx: NC 请求 ROB 索引。
        nc_lq_idx: NC 请求 LQ 索引。
        nc_sq_idx: NC 请求 SQ 索引。
        scalar_rob_idx: 标量请求 ROB 索引。
        scalar_lq_idx: 标量请求 LQ 索引。
        scalar_sq_idx: 标量请求 SQ 索引。
        pc: 两条请求共用的 PC 基值。
        max_cycles: 最大等待周期数。

    Returns:
        Dict[str, Any]: 包含 NC/标量两条请求的 ready 历史与是否被接受。

    Raises:
        ValueError: 当参数非法时抛出。
        TimeoutError: 当在 `max_cycles` 内未观察到 NC 请求被接受时抛出。
    """
    if max_cycles <= 0:
        raise ValueError(f"max_cycles 必须大于 0，当前值为 {max_cycles}")
    if min(
        nc_vaddr,
        nc_paddr,
        nc_data,
        scalar_src0,
        nc_fu_op_type,
        scalar_fu_op_type,
        nc_rob_idx,
        nc_lq_idx,
        nc_sq_idx,
        scalar_rob_idx,
        scalar_lq_idx,
        scalar_sq_idx,
        pc,
    ) < 0:
        raise ValueError("NC/scalar 竞争请求参数不允许为负数")

    env.set_default_inputs()
    _fill_nc_load_request(
        env,
        vaddr=nc_vaddr,
        paddr=nc_paddr,
        data=nc_data,
        fu_op_type=nc_fu_op_type,
        rob_idx=nc_rob_idx,
        lq_idx=nc_lq_idx,
        sq_idx=nc_sq_idx,
        pc=pc,
        pdest=1,
        store_set_hit=1,
        is128bit=False,
        vec_active=1,
    )
    _fill_scalar_load_request(
        env,
        src0=scalar_src0,
        fu_op_type=scalar_fu_op_type,
        rob_idx=scalar_rob_idx,
        lq_idx=scalar_lq_idx,
        sq_idx=scalar_sq_idx,
        pc=pc + 4,
    )
    env.lsq.nc_ldin.valid.value = 1
    env.scalar_req.valid.value = 1

    nc_ready_history = []
    scalar_ready_history = []
    for waited_cycles in range(max_cycles):
        nc_ready_now = int(env.lsq.nc_ldin.ready.value)
        scalar_ready_now = int(env.scalar_req.ready.value)
        nc_ready_history.append(nc_ready_now)
        scalar_ready_history.append(scalar_ready_now)
        env.Step(1)
        if nc_ready_now:
            env.lsq.nc_ldin.valid.value = 0
            env.scalar_req.valid.value = 0
            return {
                "nc_accepted": True,
                "scalar_accepted_same_cycle": bool(scalar_ready_now),
                "wait_cycles": waited_cycles,
                "nc_ready_history": nc_ready_history,
                "scalar_ready_history": scalar_ready_history,
            }

    env.lsq.nc_ldin.valid.value = 0
    env.scalar_req.valid.value = 0
    raise TimeoutError("NC/scalar 竞争场景在 max_cycles 内未观察到 NC 请求被接受")


def api_bosc_LoadUnit_inject_memory_resp(
    env,
    tlb_valid: bool = False,
    tlb_paddr: int = 0,
    tlb_miss: bool = False,
    tlb_pf_ld: bool = False,
    tlb_gpf_ld: bool = False,
    tlb_af_ld: bool = False,
    pmp_ld: bool = False,
    pmp_st: bool = False,
    pmp_mmio: bool = False,
    dcache_data: int = 0,
    dcache_miss: bool = False,
    dcache_bank_conflict: bool = False,
    dcache_mq_nack: bool = False,
    dcache_denied: bool = False,
    dcache_corrupt: bool = False,
    forward_source: str = "",
    forward_data: int = 0,
    forward_mask: int = 0xFFFF,
    forward_data_invalid: bool = False,
    forward_addr_invalid: bool = False,
    forward_match_invalid: bool = False,
    forward_data_invalid_sq_idx: int | None = None,
    forward_addr_invalid_sq_idx: int | None = None,
    sbuffer_match_invalid: bool = False,
    ubuffer_match_invalid: bool = False,
    hold_cycles: int = 1,
    max_cycles: int = 1,
) -> Dict[str, Any]:
    """向 TLB/PMP/DCache/前递网络注入一拍标准响应。

    该 API 将外部存储系统相关输入统一收口，适合在请求已经发射后，用一拍方式向 DUT
    注入“正常命中 / miss / bank conflict / mq nack / store-to-load forward”等基础场景。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        tlb_valid (bool): 是否拉高 `io_tlb_resp_valid`。
        tlb_paddr (int): 注入到 TLB 响应中的物理地址低位值。
        tlb_miss (bool): 是否将 TLB 响应标记为 miss。
        tlb_pf_ld (bool): 是否注入 TLB load page fault。
        tlb_gpf_ld (bool): 是否注入 TLB load guest page fault。
        tlb_af_ld (bool): 是否注入 TLB load access fault。
        pmp_ld (bool): 是否注入 PMP load fault。
        pmp_st (bool): 是否注入 PMP store fault。
        pmp_mmio (bool): 是否注入 PMP mmio 属性。
        dcache_data (int): 注入到 DCache 响应中的 64bit/128bit 数据低位值。
        dcache_miss (bool): 是否注入 dcache miss。
        dcache_bank_conflict (bool): 是否注入 bank conflict。
        dcache_mq_nack (bool): 是否注入 mq nack。
        dcache_denied (bool): 是否注入 TileLink denied 错误。
        dcache_corrupt (bool): 是否注入 TileLink corrupt 错误。
        forward_source (str): 前递来源，可选 `\"\"`/`\"lsq\"`/`\"sbuffer\"`/`\"ubuffer\"`。
        forward_data (int): 前递数据，按 16 个 byte lane 写入。
        forward_mask (int): 前递 mask，最低 16bit 有效。
        forward_data_invalid (bool): 是否注入 LSQ forward 数据未 ready。
        forward_addr_invalid (bool): 是否注入 LSQ forward 地址不匹配。
        forward_match_invalid (bool): 是否注入 LSQ forward VP match 失败。
        forward_data_invalid_sq_idx (int | None): 当 `dataInvalid` 生效时，可选地携带对应的 SQ 索引。
        forward_addr_invalid_sq_idx (int | None): 当 `addrInvalid` 生效时，可选地携带对应的 SQ 索引。
        sbuffer_match_invalid (bool): 是否注入 SBuffer VP match 失败。
        ubuffer_match_invalid (bool): 是否注入 UBuffer VP match 失败。
        hold_cycles (int): 响应保持拍数。对 PMP fault 与 TL error 这类跨级传播场景，通常需要保持多拍。
        max_cycles (int): 本 API 最多推进的周期数，必须不小于 `hold_cycles`。

    Returns:
        Dict[str, Any]: 注入摘要，包含关键输入的镜像配置。

    Raises:
        ValueError: 当 `forward_source` 非法、`hold_cycles < 1` 或 `max_cycles < hold_cycles` 时抛出。

    Example:
        >>> api_bosc_LoadUnit_inject_memory_resp(env, tlb_valid=True, tlb_paddr=0x8000)

    Note:
        - 该 API 会在推进 `hold_cycles` 拍后清除瞬时响应输入，避免对后续场景产生粘连影响。
        - TLB 页异常通常 1 拍即可；PMP fault 与 DCache TL error 建议保持 3 拍以覆盖 stage 2/3 传播窗口。
    """
    if hold_cycles < 1:
        raise ValueError(f"hold_cycles 必须大于等于 1，当前值为 {hold_cycles}")
    if max_cycles < hold_cycles:
        raise ValueError(
            f"max_cycles 必须不小于 hold_cycles，当前值为 {max_cycles}"
        )
    if forward_source not in ("", "lsq", "sbuffer", "ubuffer"):
        raise ValueError(f"非法的 forward_source: {forward_source}")

    _clear_memory_response_inputs(env)

    env.tlb.resp.valid.value = int(tlb_valid)
    env.tlb.resp.bits.miss.value = int(tlb_miss)
    getattr(env.tlb.resp.bits.paddr, "0").value = int(tlb_paddr)
    if hasattr(env.tlb.resp.bits.paddr, "1"):
        getattr(env.tlb.resp.bits.paddr, "1").value = 0
    env.tlb.resp.bits.excp["0"].pf_ld.value = int(tlb_pf_ld)
    env.tlb.resp.bits.excp["0"].gpf_ld.value = int(tlb_gpf_ld)
    env.tlb.resp.bits.excp["0"].af_ld.value = int(tlb_af_ld)
    env.pmp.ld.value = int(pmp_ld)
    env.pmp.st.value = int(pmp_st)
    env.pmp.mmio.value = int(pmp_mmio)

    env.dcache.resp_bits.data.value = int(dcache_data)
    env.dcache.resp_bits.miss.value = int(dcache_miss)
    env.dcache.resp_bits.handled.value = 1 if not dcache_miss else 0
    env.dcache.resp_bits.tl_error_delayed_tl.denied.value = int(dcache_denied)
    env.dcache.resp_bits.tl_error_delayed_tl.corrupt.value = int(dcache_corrupt)
    env.dcache.s2.bank_conflict.value = int(dcache_bank_conflict)
    env.dcache.s2.mq_nack.value = int(dcache_mq_nack)
    env.lsq.forward.dataInvalid.value = int(forward_data_invalid)
    env.lsq.forward.addrInvalid.value = int(forward_addr_invalid)
    env.lsq.forward.matchInvalid.value = int(forward_match_invalid)
    if forward_data_invalid_sq_idx is not None:
        env.lsq.forward.dataInvalidSqIdx.flag.value = 1
        env.lsq.forward.dataInvalidSqIdx.value.value = int(forward_data_invalid_sq_idx)
    if forward_addr_invalid_sq_idx is not None:
        env.lsq.forward.addrInvalidSqIdx.flag.value = 1
        env.lsq.forward.addrInvalidSqIdx.value.value = int(forward_addr_invalid_sq_idx)
    env.sbuffer.matchInvalid.value = int(sbuffer_match_invalid)
    env.ubuffer.matchInvalid.value = int(ubuffer_match_invalid)

    if forward_source == "lsq":
        env.lsq.forward.matchInvalid.value = 0
        _drive_forward_group(env.lsq.forward, forward_data, forward_mask)
    elif forward_source == "sbuffer":
        env.sbuffer.matchInvalid.value = 0
        _drive_forward_group(env.sbuffer, forward_data, forward_mask)
    elif forward_source == "ubuffer":
        env.ubuffer.matchInvalid.value = 0
        _drive_forward_group(env.ubuffer, forward_data, forward_mask)

    env.Step(hold_cycles)
    _clear_memory_response_inputs(env)

    return {
        "tlb_valid": int(tlb_valid),
        "tlb_paddr": int(tlb_paddr),
        "tlb_miss": int(tlb_miss),
        "tlb_pf_ld": int(tlb_pf_ld),
        "tlb_gpf_ld": int(tlb_gpf_ld),
        "tlb_af_ld": int(tlb_af_ld),
        "pmp_ld": int(pmp_ld),
        "pmp_st": int(pmp_st),
        "pmp_mmio": int(pmp_mmio),
        "dcache_data": int(dcache_data),
        "dcache_miss": int(dcache_miss),
        "dcache_bank_conflict": int(dcache_bank_conflict),
        "dcache_mq_nack": int(dcache_mq_nack),
        "dcache_denied": int(dcache_denied),
        "dcache_corrupt": int(dcache_corrupt),
        "forward_source": forward_source,
        "forward_data": int(forward_data),
        "forward_mask": int(forward_mask),
        "forward_data_invalid": int(forward_data_invalid),
        "forward_addr_invalid": int(forward_addr_invalid),
        "forward_match_invalid": int(forward_match_invalid),
        "forward_data_invalid_sq_idx": forward_data_invalid_sq_idx,
        "forward_addr_invalid_sq_idx": forward_addr_invalid_sq_idx,
        "sbuffer_match_invalid": int(sbuffer_match_invalid),
        "ubuffer_match_invalid": int(ubuffer_match_invalid),
        "hold_cycles": int(hold_cycles),
    }


def api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles: int = 20) -> Dict[str, Any]:
    """等待并采集 LoadUnit 的写回与控制输出。

    该 API 统一观测 `ldout`、`vecldout`、`wakeup`、`feedback_slow`、`rollback`、
    `misalign_ldout` 等对外可见结果，避免测试用例逐个接口重复轮询。

    Args:
        env: bosc_LoadUnit 的 env fixture。
        max_cycles (int): 最多等待多少拍出现任一有效输出。

    Returns:
        Dict[str, Any]: 采集结果字典。若某类输出在采集窗口内未有效，则对应值为 `None`。

    Raises:
        TimeoutError: 当在 `max_cycles` 周期内始终没有任何可采集输出时抛出。

    Example:
        >>> result = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=10)
        >>> print(result[\"scalar_writeback\"])

    Note:
        - 该 API 只负责统一观测，不会主动驱动任何输入。
        - 返回值中的子项直接来源于对应 Bundle 的 `as_dict()` 结果，适合后续断言或日志记录。
    """
    if max_cycles < 0:
        raise ValueError(f"max_cycles 不允许为负数，当前值为 {max_cycles}")

    for waited_cycles in range(max_cycles + 1):
        snapshot = _capture_loadunit_outputs(env)
        if any(value is not None for value in snapshot.values()):
            snapshot["wait_cycles"] = waited_cycles
            return snapshot
        if waited_cycles != max_cycles:
            env.Step(1)

    raise TimeoutError("在 max_cycles 周期内未观测到任何写回或控制输出")


# 定义其他Env
# @pytest.fixture(scope="function") # 用scope="function"确保每个测试用例都创建了一个全新的Env
# def env1(dut):
#     return MyEnv1(dut)
#
#
# 根据DUT的功能需要，定义API函数， API函数需要通用且稳定，不是越多越好
# def api_bosc_LoadUnit_{operation_name}(env, ...):
#    """
#    api description and parameters
#    ...
#    """
#    env.some_input.value = value
#    env.Step()
#    return env.some_output.value
#    # Replace with the actual API function for your DUT
#    ...


# 本文件为模板，请根据需要修改，删除不需要的代码和注释

"""Current API delta reserved for LoadUnit coverage-specific helpers."""

from typing import Any, Dict

def _configure_memory_triggers(env, triggers, debug_mode: int, can_raise_breakpoint: int) -> list[Dict[str, int]]:
    configured = []
    trigger_by_index = {int(trigger["index"]): trigger for trigger in triggers}
    env.from_csr_trigger.debugMode.value = int(debug_mode)
    env.from_csr_trigger.triggerCanRaiseBpExp.value = int(can_raise_breakpoint)

    for index in range(4):
        trigger = trigger_by_index.get(index, {})
        enabled = int(trigger.get("enabled", 0))
        entry = env.from_csr_trigger.tdataVec[str(index)]
        env.from_csr_trigger.tEnableVec[str(index)].value = enabled
        entry.matchType.value = int(trigger.get("match_type", 0))
        entry.select.value = int(trigger.get("select", 0))
        entry.timing.value = int(trigger.get("timing", 0))
        entry.action.value = int(trigger.get("action", 0))
        entry.chain.value = int(trigger.get("chain", 0))
        entry.load.value = int(trigger.get("load", enabled))
        entry.tdata2.value = int(trigger.get("tdata2", 0))
        configured.append({
            "index": index,
            "enabled": enabled,
            "match_type": int(trigger.get("match_type", 0)),
            "select": int(trigger.get("select", 0)),
            "timing": int(trigger.get("timing", 0)),
            "action": int(trigger.get("action", 0)),
            "chain": int(trigger.get("chain", 0)),
            "load": int(trigger.get("load", enabled)),
            "tdata2": int(trigger.get("tdata2", 0)),
        })
    return configured

def api_bosc_LoadUnit_send_triggered_vector_load(
    env,
    vaddr: int,
    mask: int,
    triggers,
    aligned_type: int = 4,
    debug_mode: int = 0,
    can_raise_breakpoint: int = 1,
    rob_idx: int = 20,
    lq_idx: int = 20,
    clear_cycles: int = 1,
    observe_cycles: int = 4,
    complete_response: bool = False,
    response_data: int = 0x0123456789ABCDEF,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Configure memory triggers and issue one vector request without clearing them.

    Args:
        env: bosc_LoadUnit environment fixture.
        vaddr: Vector request virtual address.
        mask: Active vector byte mask.
        triggers: Trigger dictionaries containing index, enable, match, action, chain, and address fields.
        aligned_type: Alignment encoding; bit 2 selects the 128-bit unit-stride trigger path.
        debug_mode: Global debug-mode gate from CSR trigger state.
        can_raise_breakpoint: Permission for action-zero breakpoint triggers.
        rob_idx: Request ROB index.
        lq_idx: Request load-queue index.
        clear_cycles: Cycles to sample the cleared trigger configuration before applying new values.
        observe_cycles: Cycles allowed for trigger metadata to propagate after acceptance.
        complete_response: Inject a normal TLB/DCache response so vector writeback is observable.
        response_data: DCache data used when complete_response is enabled.
        max_cycles: Maximum cycles to wait for the vector ready/valid handshake.

    Returns:
        Dict[str, Any]: Handshake result, request/configuration mirrors, and observable vector trigger state.
    """
    if max_cycles <= 0 or min(clear_cycles, observe_cycles, response_data) < 0:
        raise ValueError("cycle limits must be non-negative and max_cycles must be positive")
    if not 0 <= mask <= 0xFFFF:
        raise ValueError("mask must fit in 16 bits")

    env.set_default_inputs()
    env.Step(clear_cycles)
    _fill_vector_load_request(
        env,
        vaddr=vaddr,
        mask=mask,
        reg_offset=aligned_type & 0xF,
        elem_idx=mask.bit_length() - 1 if mask else 0,
        elem_idx_inside_vd=(mask.bit_length() - 1 if mask else 0),
        aligned_type=aligned_type,
        vec_active=1,
        rob_idx=rob_idx,
        lq_idx=lq_idx,
        pc=vaddr + 0x1000,
    )
    configured = _configure_memory_triggers(env, triggers, debug_mode, can_raise_breakpoint)
    env.vector_req.valid.value = 1

    for waited_cycles in range(max_cycles):
        ready_now = int(env.vector_req.ready.value)
        env.Step(1)
        if ready_now:
            request = env.vector_req.bits.as_dict()
            env.vector_req.valid.value = 0
            memory_response = None
            if complete_response:
                memory_response = api_bosc_LoadUnit_inject_memory_resp(
                    env,
                    tlb_valid=True,
                    tlb_paddr=vaddr,
                    dcache_data=response_data,
                    hold_cycles=2,
                    max_cycles=2,
                )
            response_history = []
            for cycle in range(observe_cycles + 1):
                response_history.append({
                    "cycle": cycle,
                    "valid": int(env.vector_resp.valid.value),
                    "payload": env.vector_resp.bits.as_dict() if env.vector_resp.valid.value else None,
                })
                if cycle < observe_cycles:
                    env.Step(1)
            return {
                "accepted": True,
                "wait_cycles": waited_cycles,
                "request": request,
                "trigger_config": configured,
                "vector_response_valid": int(env.vector_resp.valid.value),
                "vector_trigger_mask": int(env.vector_resp.bits.vecTriggerMask.value),
                "response_history": response_history,
                "memory_response": memory_response,
            }

    env.vector_req.valid.value = 0
    raise TimeoutError("triggered vector request did not complete ready/valid handshake")

def _issue_trigger_sequence_request(env, port, request_snapshot, max_cycles: int, label: str) -> Dict[str, Any]:
    port.valid.value = 1
    for waited_cycles in range(max_cycles):
        ready_now = int(port.ready.value)
        env.Step(1)
        if ready_now:
            port.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited_cycles,
                "request": request_snapshot(),
                "tlb_req_valid": int(env.tlb.req.valid.value),
                "dcache_req_valid": int(env.dcache.req.valid.value),
            }
    port.valid.value = 0
    raise TimeoutError(f"{label} request did not complete ready/valid handshake")

def api_bosc_LoadUnit_run_trigger_request_class_sequence(
    env,
    scalar_high_addr: int,
    vector_low_addr: int,
    prefetch_addr: int,
    scalar_low_addr: int,
    triggers,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Issue scalar, unit-stride vector, prefetch, and scalar requests under one trigger configuration.

    Args:
        env: bosc_LoadUnit environment fixture.
        scalar_high_addr: First scalar address, chosen to establish high address bits.
        vector_low_addr: Unit-stride vector address used for scalar-to-vector mode transition.
        prefetch_addr: Physical prefetch address used to exercise trigger isolation.
        scalar_low_addr: Final scalar address used to leave prefetch mode.
        triggers: Trigger dictionaries kept active across all four requests.
        max_cycles: Maximum wait for each ready/valid request and prefetch availability.

    Returns:
        Dict[str, Any]: Ordered request results and observable TLB/DCache routing samples.
    """
    if max_cycles <= 0 or min(scalar_high_addr, vector_low_addr, prefetch_addr, scalar_low_addr) < 0:
        raise ValueError("addresses must be non-negative and max_cycles must be positive")

    env.set_default_inputs()
    env.Step(1)
    configured = _configure_memory_triggers(env, triggers, debug_mode=0, can_raise_breakpoint=1)

    _fill_scalar_load_request(env, scalar_high_addr, 3, 220, 92, 0, scalar_high_addr + 4)
    scalar_high = _issue_trigger_sequence_request(
        env, env.scalar_req, env.scalar_req.bits.as_dict, max_cycles, "initial scalar"
    )
    env.Step(1)

    _fill_vector_load_request(
        env,
        vaddr=vector_low_addr,
        mask=0x8001,
        reg_offset=4,
        elem_idx=15,
        elem_idx_inside_vd=15,
        aligned_type=4,
        vec_active=1,
        rob_idx=221,
        lq_idx=93,
        pc=vector_low_addr + 4,
    )
    vector = _issue_trigger_sequence_request(
        env, env.vector_req, env.vector_req.bits.as_dict, max_cycles, "unit-stride vector"
    )
    env.Step(1)

    waited_for_prefetch = 0
    while not int(env.io.canAcceptHighConfPrefetch.value):
        if waited_for_prefetch >= max_cycles:
            raise TimeoutError("prefetch input did not become available")
        env.Step(1)
        waited_for_prefetch += 1
    env.prefetch.req.bits.paddr.value = int(prefetch_addr)
    env.prefetch.req.bits.confidence.value = 3
    env.prefetch.req.bits.is_store.value = 0
    env.prefetch.req.bits.pf_source_value.value = 5
    env.prefetch.req.valid.value = 1
    env.Step(1)
    prefetch = {
        "accepted": True,
        "wait_cycles": waited_for_prefetch,
        "paddr": int(prefetch_addr),
        "tlb_req_valid": int(env.tlb.req.valid.value),
        "dcache_req_valid": int(env.dcache.req.valid.value),
    }
    env.prefetch.req.valid.value = 0
    env.Step(1)

    _fill_scalar_load_request(env, scalar_low_addr, 3, 222, 94, 0, scalar_low_addr + 4)
    scalar_low = _issue_trigger_sequence_request(
        env, env.scalar_req, env.scalar_req.bits.as_dict, max_cycles, "recovery scalar"
    )

    return {
        "mode_order": ["scalar", "vector-unit-stride", "prefetch", "scalar"],
        "trigger_config": configured,
        "scalar_high": scalar_high,
        "vector": vector,
        "prefetch": prefetch,
        "scalar_low": scalar_low,
    }

def api_bosc_LoadUnit_send_triggered_scalar_load(
    env,
    vaddr: int,
    triggers,
    debug_mode: int = 0,
    can_raise_breakpoint: int = 1,
    rob_idx: int = 1,
    lq_idx: int = 1,
    observe_cycles: int = 12,
    response_data: int = 0xFEDCBA9876543210,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Complete a scalar load under an explicit memory-trigger configuration.

    Args:
        env: bosc_LoadUnit environment fixture.
        vaddr: Scalar request address used by the trigger comparator.
        triggers: Trigger dictionaries containing comparator, chain, action, and payload fields.
        debug_mode: Global trigger debug-mode suppression gate.
        can_raise_breakpoint: Permission for action-zero breakpoint triggers.
        rob_idx: Request ROB index.
        lq_idx: Request load-queue index.
        observe_cycles: Cycles allowed for the matching scalar writeback to appear.
        response_data: DCache data returned for the completed scalar load.
        max_cycles: Maximum cycles to wait for the scalar ready/valid handshake.

    Returns:
        Dict[str, Any]: Request/configuration mirrors and scalar writebacks sampled by request address.
    """
    if max_cycles <= 0 or observe_cycles < 0 or min(vaddr, rob_idx, lq_idx, response_data) < 0:
        raise ValueError("addresses, indices, and cycle limits must be non-negative")

    env.set_default_inputs()
    env.Step(1)
    _fill_scalar_load_request(env, vaddr, 3, rob_idx, lq_idx, 0, vaddr + 4)
    configured = _configure_memory_triggers(env, triggers, debug_mode, can_raise_breakpoint)
    issue = _issue_trigger_sequence_request(
        env, env.scalar_req, env.scalar_req.bits.as_dict, max_cycles, "triggered scalar"
    )
    memory_response = api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=vaddr,
        dcache_data=response_data,
        hold_cycles=2,
        max_cycles=2,
    )
    response_history = []
    for cycle in range(observe_cycles + 1):
        payload = env.scalar_resp.bits.as_dict() if env.scalar_resp.valid.value else None
        response_history.append({"cycle": cycle, "payload": payload})
        if cycle < observe_cycles:
            env.Step(1)

    return {
        "accepted": issue["accepted"],
        "wait_cycles": issue["wait_cycles"],
        "request": issue["request"],
        "trigger_config": configured,
        "memory_response": memory_response,
        "response_history": response_history,
    }

"""Stage C API delta for LoadUnit arbitration and split-response coverage."""

from typing import Any, Dict

def _configure_prefetch_request(env, paddr: int, confidence: int, source: int) -> None:
    env.prefetch.req.bits.paddr.value = int(paddr)
    env.prefetch.req.bits.alias.value = (int(paddr) >> 12) & 0x3
    env.prefetch.req.bits.confidence.value = int(bool(confidence))
    env.prefetch.req.bits.is_store.value = 0
    env.prefetch.req.bits.pf_source_value.value = int(source) & 0x7

def _configure_stage0_competitor(env, competitor: str, identity: int):
    if competitor == "scalar":
        _fill_scalar_load_request(
            env,
            src0=0x1000 + identity * 0x40,
            fu_op_type=3,
            rob_idx=identity,
            lq_idx=identity & 0x7F,
            sq_idx=identity & 0x3F,
            pc=0x8000 + identity * 4,
        )
        return env.scalar_req
    if competitor == "vector":
        _fill_vector_load_request(
            env,
            vaddr=0x2000 + identity * 0x40,
            mask=0xA55A,
            reg_offset=identity & 0x1F,
            elem_idx=identity & 0xF,
            elem_idx_inside_vd=(identity + 3) & 0xF,
            aligned_type=4,
            vec_active=1,
            rob_idx=identity,
            lq_idx=identity & 0x7F,
            pc=0x9000 + identity * 4,
        )
        return env.vector_req
    raise ValueError(f"unsupported stage0 competitor: {competitor}")

def _set_stage0_uop_metadata(uop, pattern: int, identity: int) -> Dict[str, int]:
    values = {
        "crossPageIPFFix": pattern & 1,
        "ftqPtr_flag": (pattern >> 1) & 1,
        "ftqPtr_value": (pattern >> 2) & 0x3F,
        "ftqOffset": (pattern >> 8) & 0xF,
        "instr": pattern & 0xFFFFFFFF,
        "foldpc": (pattern >> 4) & 0x3FF,
        "ldest": (pattern >> 6) & 0x3F,
        "selImm": (pattern >> 12) & 0xF,
        "fuType": pattern & ((1 << 35) - 1),
        "fuOpType": 3,
        "robIdx": identity,
        "lqIdx": identity & 0x7F,
    }
    extended_fields = {
        "pred_taken": (pattern >> 3) & 1,
        "satpFlushFirstFetchFault": (pattern >> 5) & 1,
        "vecWen": (pattern >> 7) & 1,
        "v0Wen": (pattern >> 9) & 1,
        "vlWen": (pattern >> 11) & 1,
        "isXSTrap": (pattern >> 13) & 1,
        "waitForward": (pattern >> 15) & 1,
        "blockBackward": (pattern >> 17) & 1,
        "canRobCompress": (pattern >> 19) & 1,
        "numLsElem": (pattern >> 21) & 0x1F,
        "fpu_typeTagOut": (pattern >> 2) & 0x3,
        "fpu_wflags": (pattern >> 6) & 1,
        "fpu_typ": (pattern >> 10) & 0x3,
        "fpu_fmt": (pattern >> 14) & 0x3,
        "fpu_rm": (pattern >> 18) & 0x7,
    }
    values.update(extended_fields)
    for name in ("crossPageIPFFix", "ftqOffset", "instr", "foldpc", "ldest", "selImm"):
        if hasattr(uop, name):
            getattr(uop, name).value = values[name]
    for name, value in extended_fields.items():
        if hasattr(uop, name):
            getattr(uop, name).value = value
    uop.fuType.value = values["fuType"]
    uop.fuOpType.value = values["fuOpType"]
    uop.rfWen.value = 1
    uop.fpWen.value = 0
    uop.pdest.value = (identity & 0x1F) + 1
    _set_flag_value(uop.robIdx, values["robIdx"])
    _set_flag_value(uop.lqIdx, values["lqIdx"])
    _set_flag_value(uop.sqIdx, identity & 0x3F)
    if hasattr(uop, "ftqPtr"):
        _set_flag_value(uop.ftqPtr, values["ftqPtr_value"], flag=values["ftqPtr_flag"])
    if hasattr(uop, "srcType"):
        for index in range(5):
            getattr(uop.srcType, str(index)).value = (pattern >> (index * 4)) & 0xF
            values[f"srcType_{index}"] = (pattern >> (index * 4)) & 0xF
    return values

def _configure_arbitration_source(
    env,
    source: str,
    identity: int,
    pattern: int,
) -> Dict[str, Any]:
    vaddr = 0xD0000 + identity * 0x20 + (pattern & 0xF)
    paddr = 0xE0000 + identity * 0x20 + (pattern & 0xF)
    if source in ("high-prefetch", "low-prefetch"):
        confidence = int(source == "high-prefetch")
        _configure_prefetch_request(env, paddr, confidence, source=identity & 0x7)
        return {
            "source": source,
            "identity": identity,
            "pattern": pattern,
            "port": env.prefetch.req,
            "expected": {
                "paddr": paddr,
                "dcache_vaddr": paddr & 0x3FFF,
            },
        }

    if source == "misalign-wakeup":
        _fill_misalign_blocker_request(
            env, vaddr, rob_idx=identity, lq_idx=identity & 0x7F
        )
        env.misalign.ldin.bits.misalignNeedWakeUp.value = 1
        port = env.misalign.ldin
    elif source in ("mshr-replay", "replay"):
        port = env.replay
        port.bits.vaddr.value = vaddr
        port.bits.mask.value = 0xFFFF
        port.bits.isvec.value = 0
        port.bits.is128bit.value = 1
        port.bits.vecActive.value = 1
        port.bits.forward_tlDchannel.value = int(source == "mshr-replay")
        port.bits.mshrid.value = identity & 0xF
    elif source == "fast-replay":
        port = getattr(env.fast_rep, "in")
        port.bits.vaddr.value = vaddr
        port.bits.paddr.value = paddr
        port.bits.data.value = (pattern << 64) | (~pattern & ((1 << 64) - 1))
        port.bits.mask.value = 0xFFFF
        port.bits.is128bit.value = 1
        port.bits.isvec.value = 0
        port.bits.vecActive.value = 1
        port.bits.isLoadReplay.value = 1
        port.bits.isFrmMisAlignBuf.value = 0
        port.bits.lateKill.value = 0
        port.bits.rep_info_mshr_id.value = identity & 0xF
    elif source == "vector":
        _fill_vector_load_request(
            env,
            vaddr=vaddr,
            mask=0xA55A,
            reg_offset=identity & 0xF,
            elem_idx=identity & 0xF,
            elem_idx_inside_vd=(identity + 3) & 0xF,
            aligned_type=4,
            vec_active=1,
            rob_idx=identity,
            lq_idx=identity & 0x7F,
            pc=vaddr + 4,
        )
        port = env.vector_req
    elif source == "scalar":
        _fill_scalar_load_request(
            env, vaddr, 3, identity, identity & 0x7F, identity & 0x3F, vaddr + 4
        )
        port = env.scalar_req
    elif source == "uncache":
        _fill_uncache_mmio_request(
            env, identity, identity & 0x7F, identity & 0x3F, vaddr + 4,
            pdest=(identity & 0x1F) + 1,
        )
        port = env.lsq.uncache
    elif source == "nc":
        _fill_nc_load_request(
            env, vaddr, paddr, pattern & ((1 << 128) - 1), 3,
            identity, identity & 0x7F, identity & 0x3F, vaddr + 4,
            pdest=(identity & 0x1F) + 1, is128bit=True,
        )
        port = env.lsq.nc_ldin
    else:
        raise ValueError(f"unsupported arbitration source: {source}")

    expected = _set_stage0_uop_metadata(port.bits.uop, pattern, identity)
    expected["vaddr"] = vaddr & ((1 << 50) - 1)
    return {
        "source": source,
        "identity": identity,
        "pattern": pattern,
        "port": port,
        "expected": expected,
    }

def _arbitration_source_ready(env, configured: Dict[str, Any]) -> int:
    source = configured["source"]
    if source == "high-prefetch":
        return int(env.io.canAcceptHighConfPrefetch.value)
    if source == "low-prefetch":
        return int(env.io.canAcceptLowConfPrefetch.value)
    if source == "fast-replay":
        # fast_rep.in is a valid-only pulse interface; ownership is observed at wakeup.
        return 1
    return int(configured["port"].ready.value)

def _observe_arbitration_accept(env, configured: Dict[str, Any]) -> Dict[str, Any]:
    source = configured["source"]
    observation = {
        "source": source,
        "identity": configured["identity"],
        "expected": configured["expected"],
        "wakeup": None,
        "dcache": None,
    }
    if int(env.dcache.req.valid.value):
        observation["dcache"] = env.dcache.req.bits.as_dict()
    if source not in ("high-prefetch", "low-prefetch") and int(env.wakeup.valid.value):
        observation["wakeup"] = env.wakeup.bits.as_dict()
    return observation

def _arbitration_observation_matches(
    observation: Dict[str, Any],
    configured: Dict[str, Any],
) -> bool:
    source = configured["source"]
    if source in ("high-prefetch", "low-prefetch"):
        dcache = observation["dcache"]
        if dcache is None:
            return False
        observed_addr = dcache.get("vaddr", dcache.get("vaddr_dup"))
        return (
            observed_addr is not None
            and int(observed_addr) == configured["expected"]["dcache_vaddr"]
        )
    if source == "vector":
        dcache = observation["dcache"]
        return (
            dcache is not None
            and int(dcache["lqIdx"]["value"]) == (configured["identity"] & 0x7F)
            and int(dcache["vaddr_dup"]) == configured["expected"]["vaddr"]
        )
    wakeup = observation["wakeup"]
    return (
        wakeup is not None
        and int(wakeup["robIdx"]["value"]) == configured["identity"]
        and int(wakeup["lqIdx"]["value"]) == (configured["identity"] & 0x7F)
    )

def api_bosc_LoadUnit_observe_adjacent_source_priority(
    env,
    higher_source: str,
    lower_source: str,
    higher_identity: int,
    lower_identity: int,
    higher_pattern: int,
    lower_pattern: int,
    max_cycles: int = 16,
) -> Dict[str, Any]:
    """Observe two concurrent stage-0 sources accepting in priority order.

    Args:
        env: LoadUnit environment fixture.
        higher_source: Source expected to own the first arbitration cycle.
        lower_source: Source expected to remain pending during that cycle.
        higher_identity: ROB/LQ or prefetch identity for the higher source.
        lower_identity: ROB/LQ or prefetch identity for the lower source.
        higher_pattern: Metadata pattern driven on the higher source.
        lower_pattern: Complementary metadata pattern driven on the lower source.
        max_cycles: Maximum cycles allowed for both sources to be accepted.

    Returns:
        Initial readiness, stable blocked payload, and ordered accept observations.
    """
    if max_cycles < 4:
        raise ValueError("max_cycles must be at least four")
    if higher_source == lower_source:
        raise ValueError("arbitration sources must be distinct")

    env.set_default_inputs()
    higher = _configure_arbitration_source(
        env, higher_source, higher_identity, higher_pattern
    )
    lower = _configure_arbitration_source(
        env, lower_source, lower_identity, lower_pattern
    )
    higher["port"].valid.value = 1
    lower["port"].valid.value = 1

    lower_before = lower["port"].bits.as_dict()
    initial_higher_ready = _arbitration_source_ready(env, higher)
    initial_lower_ready = _arbitration_source_ready(env, lower)
    first = None
    second = None
    blocked_lower_ready = None
    lower_blocked_snapshot = None
    ready_history = []

    for cycle in range(max_cycles):
        higher_ready = _arbitration_source_ready(env, higher)
        lower_ready = _arbitration_source_ready(env, lower)
        ready_history.append({
            "cycle": cycle,
            "higher_ready": higher_ready,
            "lower_ready": lower_ready,
        })
        env.Step(1)

        if first is None and higher_ready:
            blocked_lower_ready = _arbitration_source_ready(env, lower)
            lower_blocked_snapshot = lower["port"].bits.as_dict()
            first = _observe_arbitration_accept(env, higher)
            higher["port"].valid.value = 0
            continue
        if first is not None and lower_ready:
            lower["port"].valid.value = 0
            candidate = _observe_arbitration_accept(env, lower)
            for _ in range(4):
                if _arbitration_observation_matches(candidate, lower):
                    second = candidate
                    break
                env.Step(1)
                candidate = _observe_arbitration_accept(env, lower)
            break

    higher["port"].valid.value = 0
    lower["port"].valid.value = 0
    if first is None:
        raise TimeoutError(f"higher-priority source {higher_source} was not accepted")
    if second is None:
        raise TimeoutError(f"lower-priority source {lower_source} was not released")

    return {
        "higher_source": higher_source,
        "lower_source": lower_source,
        "initial_higher_ready": initial_higher_ready,
        "initial_lower_ready": initial_lower_ready,
        "blocked_lower_ready": blocked_lower_ready,
        "blocked_payload_stable": lower_before == lower_blocked_snapshot,
        "ready_history": ready_history,
        "first": first,
        "second": second,
    }

def api_bosc_LoadUnit_observe_stage0_source_metadata(
    env,
    source: str,
    identity: int,
    pattern: int,
    max_cycles: int = 4,
) -> Dict[str, Any]:
    """Observe metadata selected from one stage-0 request source.

    Args:
        env: LoadUnit environment fixture.
        source: One of misalign-wakeup, mshr-replay, fast-replay, replay,
            scalar, uncache, or nc.
        identity: ROB/LQ transaction identity unique to the selected source.
        pattern: Coherent pattern applied to all metadata fields exposed by the source.
        max_cycles: Maximum cycles reserved for observing source acceptance.

    Returns:
        Input metadata, selected wakeup payload, readiness, and downstream identities.
    """
    allowed = {
        "misalign-wakeup", "mshr-replay", "fast-replay", "replay",
        "scalar", "uncache", "nc",
    }
    if source not in allowed:
        raise ValueError(f"unsupported stage-0 source: {source}")
    if max_cycles < 1:
        raise ValueError("max_cycles must be positive")

    env.set_default_inputs()
    vaddr = 0xB0000 + identity * 0x20 + (pattern & 0xF)
    paddr = 0xC0000 + identity * 0x20 + (pattern & 0xF)
    port = None
    if source == "misalign-wakeup":
        _fill_misalign_blocker_request(env, vaddr, rob_idx=identity, lq_idx=identity & 0x7F)
        env.misalign.ldin.bits.misalignNeedWakeUp.value = 1
        port = env.misalign.ldin
    elif source in ("mshr-replay", "replay"):
        port = env.replay
        port.bits.vaddr.value = vaddr
        port.bits.mask.value = 0xFFFF
        port.bits.isvec.value = 0
        port.bits.is128bit.value = 1
        port.bits.vecActive.value = 1
        port.bits.forward_tlDchannel.value = int(source == "mshr-replay")
        port.bits.mshrid.value = identity & 0xF
    elif source == "fast-replay":
        port = getattr(env.fast_rep, "in")
        port.bits.vaddr.value = vaddr
        port.bits.paddr.value = paddr
        port.bits.data.value = (pattern << 64) | (~pattern & ((1 << 64) - 1))
        port.bits.mask.value = 0xFFFF
        port.bits.is128bit.value = 1
        port.bits.isvec.value = 0
        port.bits.vecActive.value = 1
        port.bits.isLoadReplay.value = 1
        port.bits.isFrmMisAlignBuf.value = 0
        port.bits.lateKill.value = 0
        port.bits.rep_info_mshr_id.value = identity & 0xF
    elif source == "scalar":
        _fill_scalar_load_request(
            env, vaddr, 3, identity, identity & 0x7F, identity & 0x3F, vaddr + 4
        )
        port = env.scalar_req
    elif source == "uncache":
        _fill_uncache_mmio_request(
            env, identity, identity & 0x7F, identity & 0x3F, vaddr + 4,
            pdest=(identity & 0x1F) + 1,
        )
        port = env.lsq.uncache
    else:
        _fill_nc_load_request(
            env, vaddr, paddr, pattern & ((1 << 128) - 1), 3,
            identity, identity & 0x7F, identity & 0x3F, vaddr + 4,
            pdest=(identity & 0x1F) + 1, is128bit=True,
        )
        port = env.lsq.nc_ldin

    expected = _set_stage0_uop_metadata(port.bits.uop, pattern, identity)
    port.valid.value = 1
    ready_history = []
    wakeup_valid = 0
    wakeup = None
    dcache_identity = None
    tlb_identity = None
    for _ in range(max_cycles):
        ready_history.append(int(port.ready.value) if hasattr(port, "ready") else 1)
        env.Step(1)
        if int(env.wakeup.valid.value):
            wakeup_valid = 1
            wakeup = env.wakeup.bits.as_dict()
            if int(env.dcache.req.valid.value):
                dcache_identity = env.dcache.req.bits.as_dict()
            if int(env.tlb.req.valid.value):
                tlb_identity = env.tlb.req.bits.as_dict()
            break
    port.valid.value = 0
    return {
        "source": source,
        "identity": identity,
        "expected": expected,
        "ready": int(bool(wakeup_valid)),
        "ready_history": ready_history,
        "wakeup_valid": wakeup_valid,
        "wakeup": wakeup,
        "dcache": dcache_identity,
        "tlb": tlb_identity,
    }

def api_bosc_LoadUnit_observe_prefetch_priority(
    env,
    confidence: int,
    competitor: str,
    paddr: int,
    identity: int = 40,
    is_store: bool = False,
    max_cycles: int = 12,
) -> Dict[str, Any]:
    """Observe prefetch arbitration and delayed competitor ownership.

    Args:
        env: LoadUnit environment fixture.
        confidence: Zero selects low-confidence; nonzero selects high-confidence.
        competitor: Either ``scalar`` or ``vector``.
        paddr: Prefetch physical address identity.
        identity: ROB/LQ identity used by the competing request.
        is_store: Whether the prefetch targets the store path.
        max_cycles: Maximum cycles allowed for both requests to be accepted.

    Returns:
        Arbitration history, stable competitor payload snapshots, and accept counts.
    """
    if max_cycles < 2:
        raise ValueError("max_cycles must be at least two")

    env.set_default_inputs()
    competitor_port = _configure_stage0_competitor(env, competitor, identity)
    _configure_prefetch_request(env, paddr, confidence, source=5)
    env.prefetch.req.bits.is_store.value = int(bool(is_store))
    competitor_port.valid.value = 1
    env.prefetch.req.valid.value = 1

    before = competitor_port.bits.as_dict()
    history = []
    prefetch_accepts = 0
    competitor_accepts = 0

    for cycle in range(max_cycles):
        env.Step(1)
        high_accept = int(env.io.canAcceptHighConfPrefetch.value)
        low_accept = int(env.io.canAcceptLowConfPrefetch.value)
        selected_accept = high_accept if confidence else low_accept
        competitor_ready = int(competitor_port.ready.value)
        history.append({
            "cycle": cycle,
            "high_accept": high_accept,
            "low_accept": low_accept,
            "competitor_ready": competitor_ready,
            "dcache_valid": int(env.dcache.req.valid.value),
        })

        prefetch_fire = bool(env.prefetch.req.valid.value) and bool(selected_accept)
        competitor_fire = bool(competitor_port.valid.value) and bool(competitor_ready)
        if prefetch_fire:
            prefetch_accepts += 1
            env.prefetch.req.valid.value = 0
        if competitor_fire:
            competitor_accepts += 1
            competitor_port.valid.value = 0
        if prefetch_accepts == 1 and competitor_accepts == 1:
            break

    after = competitor_port.bits.as_dict()
    env.prefetch.req.valid.value = 0
    competitor_port.valid.value = 0

    return {
        "confidence": int(bool(confidence)),
        "is_store": int(bool(is_store)),
        "competitor": competitor,
        "paddr": int(paddr),
        "history": history,
        "prefetch_accepts": prefetch_accepts,
        "competitor_accepts": competitor_accepts,
        "payload_stable": before == after,
        "before": before,
        "after": after,
    }

def api_bosc_LoadUnit_observe_ifetch_prefetch(
    env,
    vaddr: int,
    identity: int,
    max_cycles: int = 10,
) -> Dict[str, Any]:
    """Issue a scalar instruction-prefetch operation and observe its isolated output.

    Args:
        env: LoadUnit environment fixture.
        vaddr: 50-bit virtual address expected on the ifetch-prefetch output.
        identity: ROB/LQ identity used to detect any spurious scalar completion.
        max_cycles: Maximum request and registered-output observation window.

    Returns:
        Handshake status, exact ifetch address, and isolation observations.
    """
    if max_cycles < 4:
        raise ValueError("max_cycles must be at least four")
    env.set_default_inputs()
    address = int(vaddr) & ((1 << 50) - 1)
    _fill_scalar_load_request(
        env,
        src0=address,
        fu_op_type=8,
        rob_idx=identity,
        lq_idx=identity & 0x7F,
        sq_idx=identity & 0x3F,
        pc=address,
    )
    env.scalar_req.valid.value = 1

    accepted = False
    ifetch_vaddr = None
    dcache_seen = False
    wakeup_seen = False
    owner_writeback_seen = False
    for _ in range(max_cycles):
        ready_now = int(env.scalar_req.ready.value)
        env.Step(1)
        if ready_now and not accepted:
            accepted = True
            env.scalar_req.valid.value = 0
        if int(env.io.ifetchPrefetch.valid.value):
            ifetch_vaddr = int(env.io.ifetchPrefetch.bits_vaddr.value)
        dcache_seen |= bool(env.dcache.req.valid.value)
        wakeup_seen |= bool(env.wakeup.valid.value)
        if int(env.scalar_resp.valid.value):
            writeback = env.scalar_resp.bits.as_dict()
            owner_writeback_seen |= (
                int(writeback["uop"]["robIdx"]["value"]) == identity
                and int(writeback["uop"]["lqIdx"]["value"]) == (identity & 0x7F)
            )
        if accepted and ifetch_vaddr is not None:
            break

    env.scalar_req.valid.value = 0
    return {
        "accepted": accepted,
        "expected_vaddr": address,
        "ifetch_vaddr": ifetch_vaddr,
        "dcache_seen": dcache_seen,
        "wakeup_seen": wakeup_seen,
        "owner_writeback_seen": owner_writeback_seen,
    }

def api_bosc_LoadUnit_hold_load_then_resume(
    env,
    request_kind: str,
    identity: int,
    stall_cycles: int = 3,
    max_cycles: int = 12,
) -> Dict[str, Any]:
    """Hold a scalar or vector request behind misalign traffic, then release it.

    Args:
        env: LoadUnit environment fixture.
        request_kind: Either ``scalar`` or ``vector``.
        identity: Transaction identity used in address and ROB/LQ fields.
        stall_cycles: Number of cycles the higher-priority source remains valid.
        max_cycles: Maximum total wait after releasing the blocker.

    Returns:
        Ready history, payload stability, and exactly-once release information.
    """
    if stall_cycles < 1 or max_cycles <= stall_cycles:
        raise ValueError("max_cycles must exceed a positive stall_cycles value")

    env.set_default_inputs()
    request_port = _configure_stage0_competitor(env, request_kind, identity)
    _fill_misalign_blocker_request(env, 0x3003 + identity * 0x20, rob_idx=identity + 1, lq_idx=identity + 1)
    request_port.valid.value = 1
    env.misalign.ldin.valid.value = 1

    before = request_port.bits.as_dict()
    ready_history = []
    for _ in range(stall_cycles):
        env.Step(1)
        ready_history.append(int(request_port.ready.value))

    held_snapshot = request_port.bits.as_dict()
    env.misalign.ldin.valid.value = 0
    release_wait = None
    accept_count = 0
    for waited in range(max_cycles - stall_cycles):
        ready_now = int(request_port.ready.value)
        ready_history.append(ready_now)
        env.Step(1)
        if ready_now:
            accept_count += 1
            release_wait = waited
            request_port.valid.value = 0
            break

    after = request_port.bits.as_dict()
    request_port.valid.value = 0
    env.misalign.ldin.valid.value = 0
    return {
        "request_kind": request_kind,
        "identity": identity,
        "ready_history": ready_history,
        "stalled": all(value == 0 for value in ready_history[:stall_cycles]),
        "payload_stable_while_stalled": before == held_snapshot,
        "payload_stable_through_accept": before == after,
        "release_wait": release_wait,
        "accept_count": accept_count,
        "request": after,
    }

def api_bosc_LoadUnit_run_misalign_second_split_response(
    env,
    outcome: str,
    identity: int,
    is128bit: bool = False,
    max_cycles: int = 16,
) -> Dict[str, Any]:
    """Drive a final misalign split and observe its externally visible response.

    Args:
        env: LoadUnit environment fixture.
        outcome: One of ``hit``, ``miss``, ``bank-conflict``, ``mq-nack``, or
            ``forward-invalid``.
        identity: ROB/LQ/SQ identity for the split transaction.
        is128bit: Whether the split carries the 128-bit attribute.
        max_cycles: Maximum observation window after request acceptance.

    Returns:
        Request identity, injected response class, and cycle-by-cycle outputs.
    """
    allowed = {"hit", "miss", "bank-conflict", "mq-nack", "forward-invalid"}
    if outcome not in allowed:
        raise ValueError(f"unsupported misalign outcome: {outcome}")
    if max_cycles < 6:
        raise ValueError("max_cycles must be at least six")

    request = api_bosc_LoadUnit_send_misalign_buffer_load(
        env,
        vaddr=0x4000 + identity * 0x20,
        mask=0xFF00 if is128bit else 0x00F0,
        rob_idx=identity,
        lq_idx=identity & 0x7F,
        sq_idx=identity & 0x3F,
        pc=0xA000 + identity * 4,
        fu_op_type=3,
        is_final_split=True,
        misalign_need_wakeup=outcome != "hit",
        is128bit=is128bit,
        max_cycles=max_cycles,
    )

    _clear_memory_response_inputs(env)
    env.tlb.resp.valid.value = 1
    getattr(env.tlb.resp.bits.paddr, "0").value = 0x8000 + identity * 0x20
    env.dcache.resp_bits.data.value = (0x1122334455667788 << 64) | 0x99AABBCCDDEEFF00
    env.dcache.resp_bits.handled.value = int(outcome == "hit")
    env.dcache.resp_bits.miss.value = int(outcome == "miss")
    env.dcache.s2.bank_conflict.value = int(outcome == "bank-conflict")
    env.dcache.s2.mq_nack.value = int(outcome == "mq-nack")
    env.lsq.forward.dataInvalid.value = int(outcome == "forward-invalid")
    if outcome == "forward-invalid":
        env.lsq.forward.dataInvalidSqIdx.flag.value = 1
        env.lsq.forward.dataInvalidSqIdx.value.value = identity & 0x3F

    observations = []
    for cycle in range(max_cycles):
        snapshot = _capture_loadunit_outputs(env)
        if any(value is not None for value in snapshot.values()):
            observations.append({"cycle": cycle, "outputs": snapshot})
        env.Step(1)
        if cycle == 3:
            _clear_memory_response_inputs(env)

    _clear_memory_response_inputs(env)
    return {
        "outcome": outcome,
        "identity": identity,
        "request": request,
        "observations": observations,
    }

def api_bosc_LoadUnit_observe_scalar_replay_cause(
    env,
    cause: str,
    identity: int,
    max_cycles: int = 12,
) -> Dict[str, Any]:
    """Drive one scalar replay cause and observe its LSQ replay identity.

    Args:
        env: LoadUnit environment fixture.
        cause: One of ``address-ambiguous``, ``tlb-miss``, ``forward-invalid``,
            ``dcache-miss``, ``mq-nack``, ``bank-conflict``,
            ``ldld-backpressure``, ``stld-backpressure``, or
            ``misalign-buffer-full``.
        identity: ROB/LQ identity carried by the replaying transaction.
        max_cycles: Maximum observation window for the replay update.

    Returns:
        Accepted request, expected one-hot cause bit, and observed LSQ updates.
    """
    cause_bits = {
        "address-ambiguous": 0,
        "tlb-miss": 1,
        "forward-invalid": 2,
        "dcache-miss": 4,
        "mq-nack": 3,
        "bank-conflict": 6,
        "ldld-backpressure": 7,
        "stld-backpressure": 8,
        "misalign-buffer-full": 10,
    }
    if cause not in cause_bits:
        raise ValueError(f"unsupported scalar replay cause: {cause}")
    if max_cycles < 5:
        raise ValueError("max_cycles must be at least five")

    env.set_default_inputs()
    vaddr = 0xD8000 + identity * 0x40
    if cause == "misalign-buffer-full":
        vaddr |= 0xF
    paddr = 0xE8000 + identity * 0x40
    if cause == "address-ambiguous":
        _fill_scalar_load_request(
            env,
            src0=vaddr,
            fu_op_type=3,
            rob_idx=identity,
            lq_idx=identity & 0x7F,
            sq_idx=identity & 0x3F,
            pc=vaddr + 4,
            store_set_hit=1,
        )
        env.lsq.forward.addrInvalid.value = 1
        env.scalar_req.valid.value = 1
        issue = None
        for waited in range(max_cycles):
            ready_now = int(env.scalar_req.ready.value)
            env.Step(1)
            if ready_now:
                env.scalar_req.valid.value = 0
                issue = {
                    "accepted": True,
                    "wait_cycles": waited,
                    "request": env.scalar_req.bits.as_dict(),
                }
                break
        if issue is None:
            env.scalar_req.valid.value = 0
            raise TimeoutError("address-ambiguous scalar request was not accepted")
    else:
        issue = api_bosc_LoadUnit_send_scalar_load(
            env,
            src0=vaddr,
            fu_op_type=3,
            rob_idx=identity,
            lq_idx=identity & 0x7F,
            sq_idx=identity & 0x3F,
            pc=vaddr + 4,
            max_cycles=max_cycles,
        )

    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = int(cause == "tlb-miss")
    getattr(env.tlb.resp.bits.paddr, "0").value = paddr
    env.dcache.resp_bits.handled.value = int(cause not in {
        "tlb-miss", "dcache-miss", "mq-nack", "bank-conflict"
    })
    env.dcache.resp_bits.miss.value = int(cause == "dcache-miss")
    env.dcache.s2.mq_nack.value = int(cause == "mq-nack")
    env.dcache.s2.bank_conflict.value = int(cause == "bank-conflict")
    env.lsq.forward.addrInvalid.value = int(cause == "address-ambiguous")
    env.lsq.forward.dataInvalid.value = int(cause == "forward-invalid")
    env.lsq.forward.dataInvalidSqIdx.flag.value = int(cause == "forward-invalid")
    env.lsq.forward.dataInvalidSqIdx.value.value = identity & 0x3F
    env.lsq.ldld_nuke_query.req.ready.value = int(cause != "ldld-backpressure")
    env.lsq.stld_nuke_query.req.ready.value = int(cause != "stld-backpressure")
    if cause == "misalign-buffer-full":
        env.csr_ctrl.hd_misalign_ld_enable.value = 1
        if env.misalign_allow_spec is not None:
            env.misalign_allow_spec.value = 1
        env.misalign.enq_req.ready.value = 0

    observations = []
    for cycle in range(max_cycles):
        if int(env.lsq.ldin.valid.value):
            observations.append({
                "cycle": cycle,
                "rob_idx": int(env.lsq.ldin.bits.uop.robIdx.value.value),
                "lq_idx": int(env.lsq.ldin.bits.uop.lqIdx.value.value),
                "cause_bits": tuple(
                    int(getattr(env.dut, f"io_lsq_ldin_bits_rep_info_cause_{index}").value)
                    for index in range(11)
                ),
            })
        env.Step(1)
        if cycle == 3:
            _clear_memory_response_inputs(env)
            env.lsq.ldld_nuke_query.req.ready.value = 1
            env.lsq.stld_nuke_query.req.ready.value = 1

    _clear_memory_response_inputs(env)
    env.lsq.ldld_nuke_query.req.ready.value = 1
    env.lsq.stld_nuke_query.req.ready.value = 1
    env.misalign.enq_req.ready.value = 1
    return {
        "cause": cause,
        "expected_cause_bit": cause_bits[cause],
        "identity": identity,
        "issue": issue,
        "observations": observations,
    }

def api_bosc_LoadUnit_wait_for_scalar_owner(
    env,
    rob_idx: int,
    lq_idx: int,
    max_cycles: int = 16,
) -> Dict[str, Any]:
    """Wait for the scalar writeback owned by a specific ROB/LQ transaction.

    Args:
        env: LoadUnit environment fixture.
        rob_idx: Expected ROB index value.
        lq_idx: Expected LoadQueue index value.
        max_cycles: Maximum cycles to observe before timing out.

    Returns:
        Matching scalar writeback and the number of cycles waited.
    """
    if max_cycles < 0:
        raise ValueError("max_cycles must be nonnegative")
    for waited in range(max_cycles + 1):
        if int(env.scalar_resp.valid.value):
            writeback = env.scalar_resp.bits.as_dict()
            if (
                int(writeback["uop"]["robIdx"]["value"]) == int(rob_idx)
                and int(writeback["uop"]["lqIdx"]["value"]) == int(lq_idx)
            ):
                return {"writeback": writeback, "wait_cycles": waited}
        if waited != max_cycles:
            env.Step(1)
    raise TimeoutError(
        f"no scalar writeback for ROB {rob_idx} and LQ {lq_idx} within {max_cycles} cycles"
    )

def api_bosc_LoadUnit_send_typed_scalar_load(
    env,
    src0: int,
    fu_op_type: int,
    fp_wen: bool,
    rob_idx: int,
    lq_idx: int,
    sq_idx: int,
    pc: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Send a scalar load with an explicit integer or FP writeback mode.

    Args:
        env: LoadUnit environment fixture.
        src0: Virtual address used by the load.
        fu_op_type: Load width and extension encoding.
        fp_wen: Whether half/word data must be NaN-boxed for FP writeback.
        rob_idx: Reorder-buffer transaction identity.
        lq_idx: LoadQueue transaction identity.
        sq_idx: StoreQueue dependency identity.
        pc: Program counter carried by the micro-op.
        max_cycles: Maximum cycles to wait for ready/valid acceptance.

    Returns:
        Acceptance status, wait count, and the accepted request payload.
    """
    if max_cycles <= 0:
        raise ValueError("max_cycles must be positive")
    env.set_default_inputs()
    _fill_scalar_load_request(
        env,
        src0=src0,
        fu_op_type=fu_op_type,
        rob_idx=rob_idx,
        lq_idx=lq_idx,
        sq_idx=sq_idx,
        pc=pc,
    )
    env.scalar_req.bits.uop.fpWen.value = int(bool(fp_wen))
    env.scalar_req.valid.value = 1
    for waited in range(max_cycles):
        ready_now = int(env.scalar_req.ready.value)
        env.Step(1)
        if ready_now:
            request = env.scalar_req.bits.as_dict()
            env.scalar_req.valid.value = 0
            return {"accepted": True, "wait_cycles": waited, "request": request}
    env.scalar_req.valid.value = 0
    raise TimeoutError("typed scalar load was not accepted within max_cycles")

def api_bosc_LoadUnit_complete_scalar_metadata_pattern(
    env,
    identity: int,
    metadata_pattern: int,
    data_pattern: int,
    max_cycles: int = 16,
) -> Dict[str, Any]:
    """Complete a scalar load carrying a coherent multi-field metadata pattern.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ transaction identity.
        metadata_pattern: Pattern used for instruction, folded PC, destination and FTQ fields.
        data_pattern: 128-bit DCache response payload.
        max_cycles: Maximum completion observation window.

    Returns:
        Accepted request and its matching scalar writeback.
    """
    env.set_default_inputs()
    vaddr = 0x50000 + ((identity & 0xFF) << 5) + (metadata_pattern & 0xF)
    paddr = 0x60000 + ((identity & 0xFF) << 5) + (metadata_pattern & 0xF)
    _fill_scalar_load_request(
        env, vaddr, metadata_pattern & 0x1FF, identity, identity & 0x7F,
        identity & 0x3F, vaddr + 4
    )
    uop = env.scalar_req.bits.uop
    uop.fuType.value = metadata_pattern & 0x1F
    uop.pdest.value = (metadata_pattern & 0xFF) or 1
    uop.ftqPtr.flag.value = 1
    uop.ftqPtr.value.value = metadata_pattern & 0x3F
    uop.ftqOffset.value = metadata_pattern & 0xF
    uop.debug_seqNum.seqNum.value = metadata_pattern & ((1 << 56) - 1)
    uop.debug_seqNum.uopIdx.value = (metadata_pattern >> 8) & 0xFF
    uop.debugInfo.dispatchTime.value = metadata_pattern & ((1 << 64) - 1)
    uop.debugInfo.issueTime.value = (~metadata_pattern) & ((1 << 64) - 1)
    uop.preDecodeInfo.valid.value = metadata_pattern & 1
    uop.preDecodeInfo.isRVC.value = (metadata_pattern >> 1) & 1
    uop.preDecodeInfo.brType.value = (metadata_pattern >> 2) & 0xF
    uop.preDecodeInfo.isCall.value = (metadata_pattern >> 6) & 1
    uop.preDecodeInfo.isRet.value = (metadata_pattern >> 7) & 1
    env.scalar_req.valid.value = 1
    accepted = False
    for waited in range(max_cycles):
        env.Step(1)
        if int(env.scalar_req.ready.value):
            accepted = True
            env.scalar_req.valid.value = 0
            break
    if not accepted:
        env.scalar_req.valid.value = 0
        raise TimeoutError("metadata scalar request was not accepted")

    api_bosc_LoadUnit_inject_memory_resp(
        env, tlb_valid=True, tlb_paddr=paddr, dcache_data=data_pattern,
        hold_cycles=2, max_cycles=2
    )
    completion = api_bosc_LoadUnit_wait_for_scalar_owner(
        env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=max_cycles
    )
    return {
        "vaddr": vaddr,
        "paddr": paddr,
        "metadata_pattern": metadata_pattern,
        "writeback": completion["writeback"],
    }

def api_bosc_LoadUnit_complete_tl_d_replay(
    env,
    identity: int,
    paddr: int,
    mshr_id: int,
    data_256: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Complete a replay request from a matching TL-D refill beat.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ transaction identity.
        paddr: Physical address selecting one of four TL-D beats.
        mshr_id: MSHR identity required by the refill match guard.
        data_256: Four-beat TL-D payload.
        max_cycles: Maximum request and completion window.

    Returns:
        MSHR query identity, selected 128-bit refill window, and scalar writeback.
    """
    if max_cycles < 6:
        raise ValueError("max_cycles must be at least six")
    env.set_default_inputs()
    replay = env.replay
    replay.bits.uop.pc.value = 0x70000 + identity * 4
    replay.bits.uop.fuOpType.value = 3
    replay.bits.uop.fuType.value = 0
    replay.bits.uop.rfWen.value = 1
    replay.bits.uop.fpWen.value = 0
    replay.bits.uop.pdest.value = (identity & 0x1F) + 1
    _set_flag_value(replay.bits.uop.robIdx, identity)
    _set_flag_value(replay.bits.uop.lqIdx, identity & 0x7F)
    _set_flag_value(replay.bits.uop.sqIdx, identity & 0x3F)
    replay.bits.vaddr.value = paddr
    replay.bits.mask.value = 0xFFFF
    replay.bits.isvec.value = 0
    replay.bits.is128bit.value = 1
    replay.bits.forward_tlDchannel.value = 1
    replay.bits.mshrid.value = mshr_id & 0xF

    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = paddr
    env.tl_d_channel.data.value = data_256
    env.tl_d_channel.last.value = (paddr >> 5) & 1
    env.tl_d_channel.denied.value = 0
    env.tl_d_channel.corrupt.value = 0
    env.tl_d_channel.mshrid.value = mshr_id & 0xF
    env.tl_d_channel.valid.value = 1
    env.forward_mshr.forward.result_valid.value = 1
    env.forward_mshr.forward.mshr.value = 0
    env.forward_mshr.denied.value = 0
    env.forward_mshr.corrupt.value = 0

    replay.valid.value = 1
    query = None
    for waited in range(max_cycles):
        env.Step(1)
        if int(env.forward_mshr.valid.value):
            query = {
                "wait_cycles": waited,
                "mshr_id": int(env.forward_mshr.mshrid.value),
                "paddr": int(env.forward_mshr.paddr.value),
            }
            replay.valid.value = 0
            break
    if query is None:
        replay.valid.value = 0
        env.tl_d_channel.valid.value = 0
        env.tlb.resp.valid.value = 0
        env.forward_mshr.forward.result_valid.value = 0
        raise TimeoutError("TL-D replay did not reach the MSHR forward query")

    env.Step(2)
    env.tl_d_channel.valid.value = 0
    env.tlb.resp.valid.value = 0
    env.forward_mshr.forward.result_valid.value = 0
    completion = api_bosc_LoadUnit_wait_for_scalar_owner(
        env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=max_cycles
    )
    beat_index = (paddr >> 3) & 0x3
    next_index = beat_index if (paddr & 0x8) else ((beat_index + 1) & 0x3)
    selected_beat = (data_256 >> (64 * beat_index)) & ((1 << 64) - 1)
    adjacent_beat = (data_256 >> (64 * next_index)) & ((1 << 64) - 1)
    selected_128 = selected_beat | (adjacent_beat << 64)
    expected_data = (selected_128 >> (8 * (paddr & 0xF))) & ((1 << 64) - 1)
    return {
        "query": query,
        "selected_beat": selected_beat,
        "adjacent_beat": adjacent_beat,
        "selected_128": selected_128,
        "expected_data": expected_data,
        "writeback": completion["writeback"],
        "mshr_id": mshr_id & 0xF,
        "paddr": paddr,
    }

def api_bosc_LoadUnit_complete_direct_mshr_forward(
    env,
    identity: int,
    paddr: int,
    mshr_id: int,
    data_128: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Complete a replay using the direct MSHR forward-result interface.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ transaction identity.
        paddr: Physical address used for the MSHR query and byte selection.
        mshr_id: MSHR identity carried by the replay request.
        data_128: Direct MSHR forward payload, split into sixteen byte lanes.
        max_cycles: Maximum query and completion observation window.

    Returns:
        Observed MSHR query identity and the matching scalar writeback.
    """
    if max_cycles < 4:
        raise ValueError("max_cycles must be at least four")
    env.set_default_inputs()
    replay = env.replay
    replay.bits.uop.pc.value = 0x90000 + identity * 4
    replay.bits.uop.fuOpType.value = 3
    replay.bits.uop.fuType.value = 0
    replay.bits.uop.rfWen.value = 1
    replay.bits.uop.fpWen.value = 0
    replay.bits.uop.pdest.value = (identity & 0x1F) + 1
    _set_flag_value(replay.bits.uop.robIdx, identity)
    _set_flag_value(replay.bits.uop.lqIdx, identity & 0x7F)
    _set_flag_value(replay.bits.uop.sqIdx, identity & 0x3F)
    replay.bits.vaddr.value = paddr
    replay.bits.mask.value = 0xFFFF
    replay.bits.isvec.value = 0
    replay.bits.is128bit.value = 1
    replay.bits.forward_tlDchannel.value = 1
    replay.bits.mshrid.value = mshr_id & 0xF

    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = paddr
    env.forward_mshr.forward.result_valid.value = 1
    env.forward_mshr.forward.mshr.value = 1
    env.forward_mshr.denied.value = 0
    env.forward_mshr.corrupt.value = 0
    for lane in range(16):
        getattr(env.forward_mshr.forwardData, str(lane)).value = (
            int(data_128) >> (8 * lane)
        ) & 0xFF

    replay.valid.value = 1
    query = None
    for waited in range(max_cycles):
        env.Step(1)
        if int(env.forward_mshr.valid.value):
            query = {
                "wait_cycles": waited,
                "mshr_id": int(env.forward_mshr.mshrid.value),
                "paddr": int(env.forward_mshr.paddr.value),
            }
            replay.valid.value = 0
            break
    if query is None:
        replay.valid.value = 0
        env.tlb.resp.valid.value = 0
        env.forward_mshr.forward.result_valid.value = 0
        env.forward_mshr.forward.mshr.value = 0
        raise TimeoutError("replay did not issue a direct MSHR query")

    env.Step(2)
    env.tlb.resp.valid.value = 0
    env.forward_mshr.forward.result_valid.value = 0
    env.forward_mshr.forward.mshr.value = 0
    completion = api_bosc_LoadUnit_wait_for_scalar_owner(
        env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=max_cycles
    )
    return {
        "query": query,
        "writeback": completion["writeback"],
        "mshr_id": mshr_id & 0xF,
        "paddr": paddr,
    }

def _api_bosc_LoadUnit_drive_debug_metadata(uop, pattern: int) -> None:
    debug_info = uop.debugInfo
    mask64 = (1 << 64) - 1
    fields = (
        "renameTime", "dispatchTime", "enqRsTime", "selectTime", "issueTime",
        "writebackTime", "runahead_checkpoint_id", "tlbFirstReqTime", "tlbRespTime",
    )
    for field in fields:
        getattr(debug_info, field).value = int(pattern) & mask64
    uop.debug_seqNum.seqNum.value = int(pattern) & ((1 << 56) - 1)
    uop.debug_seqNum.uopIdx.value = (int(pattern) >> 56) & 0xFF
    uop.debug_fuType.value = int(pattern) & ((1 << 35) - 1)

def api_bosc_LoadUnit_complete_scalar_debug_metadata(
    env, identity: int, metadata_pattern: int, data_pattern: int, max_cycles: int = 20
) -> dict:
    """Complete one scalar load carrying all wide debug metadata fields.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        metadata_pattern: Full-width pattern applied to debug metadata.
        data_pattern: 128-bit DCache response data.
        max_cycles: Maximum acceptance and completion observation window.

    Returns:
        Accepted request and the matching owner-bound scalar writeback.
    """
    env.set_default_inputs()
    vaddr = 0x120000 + (identity << 5) + (metadata_pattern & 0xF)
    paddr = 0x220000 + (identity << 5) + (metadata_pattern & 0xF)
    _fill_scalar_load_request(
        env, vaddr, 3, identity, identity & 0x7F, identity & 0x3F, vaddr + 4
    )
    _api_bosc_LoadUnit_drive_debug_metadata(env.scalar_req.bits.uop, metadata_pattern)
    env.scalar_req.valid.value = 1
    accepted_request = None
    for _ in range(max_cycles):
        ready_now = int(env.scalar_req.ready.value)
        env.Step(1)
        if ready_now:
            accepted_request = env.scalar_req.bits.as_dict()
            env.scalar_req.valid.value = 0
            break
    if accepted_request is None:
        env.scalar_req.valid.value = 0
        raise TimeoutError("scalar debug-metadata request was not accepted")
    api_bosc_LoadUnit_inject_memory_resp(
        env, tlb_valid=True, tlb_paddr=paddr, dcache_data=data_pattern,
        hold_cycles=2, max_cycles=2,
    )
    completion = api_bosc_LoadUnit_wait_for_scalar_owner(
        env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=max_cycles
    )
    return {"request": accepted_request, "writeback": completion["writeback"],
            "vaddr": vaddr, "paddr": paddr}

def api_bosc_LoadUnit_complete_uncache_debug_metadata(
    env, identity: int, metadata_pattern: int, raw_data: int,
    address_offset: int, max_cycles: int = 20
) -> dict:
    """Complete one uncache load carrying all wide debug metadata fields.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        metadata_pattern: Full-width pattern applied to debug metadata.
        raw_data: MMIO raw response payload.
        address_offset: Byte offset used by the raw-data selector.
        max_cycles: Maximum acceptance and completion observation window.

    Returns:
        Accepted uncache request and its matching scalar writeback.
    """
    env.set_default_inputs()
    vaddr = (metadata_pattern & ((1 << 50) - 1)) ^ (identity << 8)
    paddr = ((~metadata_pattern) & ((1 << 48) - 1)) ^ (identity << 7)
    _fill_uncache_mmio_request(
        env, identity, identity & 0x7F, identity & 0x3F, vaddr,
        pdest=(identity & 0x1F) + 1,
    )
    _api_bosc_LoadUnit_drive_debug_metadata(env.lsq.uncache.bits.uop, metadata_pattern)
    env.lsq.uncache.bits.debug.vaddr.value = vaddr
    env.lsq.uncache.bits.debug.paddr.value = paddr
    env.lsq.uncache.bits.debug.isMMIO.value = 1
    env.pmp.mmio.value = 1
    env.lsq.ld_raw_data.addrOffset.value = int(address_offset) & 0x7
    env.lsq.ld_raw_data.lqData.value = int(raw_data)
    env.lsq.ld_raw_data.uop.fuOpType.value = 3
    env.lsq.ld_raw_data.uop.fpWen.value = 0
    env.lsq.uncache.valid.value = 1
    accepted_request = None
    for _ in range(max_cycles):
        ready_now = int(env.lsq.uncache.ready.value)
        env.Step(1)
        if ready_now:
            accepted_request = env.lsq.uncache.bits.as_dict()
            env.lsq.uncache.valid.value = 0
            break
    if accepted_request is None:
        env.lsq.uncache.valid.value = 0
        raise TimeoutError("uncache debug-metadata request was not accepted")
    completion = api_bosc_LoadUnit_wait_for_scalar_owner(
        env, rob_idx=identity, lq_idx=identity & 0x7F, max_cycles=max_cycles
    )
    return {"request": accepted_request, "writeback": completion["writeback"],
            "vaddr": vaddr, "paddr": paddr}

def api_bosc_LoadUnit_observe_stld_query_match(
    env, identity: int, query_index: int, query_rob_idx: int,
    load_paddr: int, query_paddr: int, load_mask: int, query_mask: int,
    max_cycles: int = 12
) -> dict:
    """Drive one ST-LD nuke query against an owner-tagged scalar load.

    Args:
        env: LoadUnit environment fixture.
        identity: Scalar ROB/LQ/SQ transaction identity.
        query_index: ST-LD query lane, zero or one.
        query_rob_idx: ROB value carried by the store query.
        load_paddr: Translated physical address of the scalar load.
        query_paddr: Physical address carried by the store query.
        load_mask: Byte mask implied by the scalar address/type scenario.
        query_mask: Byte mask carried by the store query.
        max_cycles: Maximum observation window.

    Returns:
        Request acceptance plus observed rollback and LSQ owner activity.
    """
    if query_index not in (0, 1):
        raise ValueError("query_index must be zero or one")
    env.set_default_inputs()
    vaddr = 0x180000 + (identity << 6) + (load_paddr & 0x3F)
    _fill_scalar_load_request(
        env, vaddr, 3, identity, identity & 0x7F, identity & 0x3F, vaddr + 4
    )
    query = getattr(env.stld_nuke_query, str(query_index))
    query.valid.value = 1
    query.bits.robIdx.flag.value = (query_rob_idx >> 8) & 1
    query.bits.robIdx.value.value = query_rob_idx & 0xFF
    query.bits.paddr.value = int(query_paddr)
    query.bits.mask.value = int(query_mask) & 0xFFFF
    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = int(load_paddr)
    env.dcache.resp_bits.handled.value = 1
    env.dcache.resp_bits.miss.value = 0
    env.dcache.resp_bits.data.value = (int(load_mask) << 64) | int(load_paddr)
    env.scalar_req.valid.value = 1
    accepted = False
    rollback_seen = False
    owner_lsq_seen = False
    for _ in range(max_cycles):
        ready_now = int(env.scalar_req.ready.value)
        env.Step(1)
        if ready_now and not accepted:
            accepted = True
            env.scalar_req.valid.value = 0
        rollback_seen |= bool(env.rollback.valid.value)
        if int(env.lsq.ldin.valid.value):
            owner_lsq_seen |= (
                int(env.lsq.ldin.bits.uop.robIdx.value.value) == identity
                and int(env.lsq.ldin.bits.uop.lqIdx.value.value) == (identity & 0x7F)
            )
    env.scalar_req.valid.value = 0
    query.valid.value = 0
    env.tlb.resp.valid.value = 0
    return {"accepted": accepted, "rollback_seen": rollback_seen,
            "owner_lsq_seen": owner_lsq_seen, "query_index": query_index,
            "query_rob_idx": query_rob_idx}

def api_bosc_LoadUnit_send_misalign_wakeup_addresses(
    env, identity: int, vaddr: int, paddr: int, gpaddr: int, mask: int,
    split_phase: int, max_cycles: int = 20
) -> dict:
    """Send a MisalignBuffer wakeup carrying all three address domains.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        vaddr: Virtual/full virtual address.
        paddr: Physical address carried by the split.
        gpaddr: Guest physical address carried by the split.
        mask: Active split byte mask.
        split_phase: Selects final-split and 128-bit attributes.
        max_cycles: Maximum ready/valid acceptance window.

    Returns:
        Stable accepted request snapshot and wait count.
    """
    env.set_default_inputs()
    _fill_misalign_blocker_request(
        env, vaddr, rob_idx=identity, lq_idx=identity & 0x7F
    )
    bits = env.misalign.ldin.bits
    bits.paddr.value = int(paddr) & ((1 << 48) - 1)
    bits.gpaddr.value = int(gpaddr) & ((1 << 50) - 1)
    bits.mask.value = int(mask) & 0xFFFF
    bits.isFinalSplit.value = int(bool(split_phase & 1))
    bits.is128bit.value = int(bool(split_phase & 2))
    bits.misalignNeedWakeUp.value = 1
    _set_flag_value(bits.uop.sqIdx, identity & 0x3F)
    env.misalign.ldin.valid.value = 1
    before = bits.as_dict()
    for waited in range(max_cycles):
        ready_now = int(env.misalign.ldin.ready.value)
        env.Step(1)
        if ready_now:
            after = bits.as_dict()
            env.misalign.ldin.valid.value = 0
            return {"accepted": True, "wait_cycles": waited,
                    "payload_stable": before == after, "request": after}
    env.misalign.ldin.valid.value = 0
    raise TimeoutError("misalign wakeup address request was not accepted")

"""Current API delta for owner-bound misalign and fault response coverage."""

from typing import Any, Dict

def api_bosc_LoadUnit_send_misalign_debug_metadata(
    env,
    identity: int,
    metadata_pattern: int,
    address_pattern: int,
    mask: int,
    split_phase: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Send a misalign request carrying coherent wide metadata and addresses.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        metadata_pattern: Pattern applied to debug timestamps, sequence and fuType.
        address_pattern: Pattern folded into virtual, physical and guest addresses.
        mask: Sixteen-bit split byte mask.
        split_phase: Bit zero selects final split; bit one selects 128-bit mode.
        max_cycles: Maximum ready/valid acceptance window.

    Returns:
        Accepted request snapshot, derived addresses, and payload stability.
    """
    if max_cycles <= 0:
        raise ValueError("max_cycles must be positive")
    env.set_default_inputs()
    vaddr = int(address_pattern) & ((1 << 50) - 1)
    paddr = ((int(address_pattern) >> 1) ^ int(metadata_pattern)) & ((1 << 48) - 1)
    gpaddr = ((int(address_pattern) << 1) ^ int(metadata_pattern)) & ((1 << 50) - 1)
    _fill_misalign_blocker_request(
        env, vaddr, rob_idx=int(identity), lq_idx=int(identity) & 0x7F
    )
    bits = env.misalign.ldin.bits
    _api_bosc_LoadUnit_drive_debug_metadata(bits.uop, int(metadata_pattern))
    _set_flag_value(bits.uop.sqIdx, int(identity) & 0x3F)
    bits.uop.pc.value = (vaddr + 4) & ((1 << 50) - 1)
    bits.uop.fuOpType.value = int(metadata_pattern) & 0x1FF
    bits.paddr.value = paddr
    bits.gpaddr.value = gpaddr
    bits.mask.value = int(mask) & 0xFFFF
    bits.isFinalSplit.value = int(bool(int(split_phase) & 1))
    bits.is128bit.value = int(bool(int(split_phase) & 2))
    bits.misalignNeedWakeUp.value = int(bool(int(split_phase) & 4))
    env.misalign.ldin.valid.value = 1
    before = bits.as_dict()
    for waited in range(max_cycles):
        ready_now = int(env.misalign.ldin.ready.value)
        env.Step(1)
        if ready_now:
            after = bits.as_dict()
            env.misalign.ldin.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited,
                "payload_stable": before == after,
                "request": after,
                "vaddr": vaddr,
                "paddr": paddr,
                "gpaddr": gpaddr,
            }
    env.misalign.ldin.valid.value = 0
    raise TimeoutError("misalign metadata request was not accepted")

def api_bosc_LoadUnit_run_scalar_fault_response(
    env,
    identity: int,
    fault_kind: str,
    response_delay: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Issue a scalar owner and inject one translation, protection, or TL error.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        fault_kind: clean, tlb-pf, tlb-gpf, tlb-af, pmp-ld, pmp-mmio,
            dcache-denied, dcache-corrupt, or denied-corrupt.
        response_delay: Idle cycles between request acceptance and response injection.
        max_cycles: Maximum observation window after injection.

    Returns:
        Issue, injected response summary, and the first observable output snapshot.
    """
    allowed = {
        "clean", "tlb-pf", "tlb-gpf", "tlb-af", "pmp-ld", "pmp-mmio",
        "dcache-denied", "dcache-corrupt", "denied-corrupt",
    }
    if fault_kind not in allowed:
        raise ValueError(f"unsupported fault kind: {fault_kind}")
    if response_delay < 0:
        raise ValueError("response_delay must be nonnegative")
    vaddr = 0x120000 + int(identity) * 0x40
    paddr = 0x220000 + int(identity) * 0x40
    issue = api_bosc_LoadUnit_send_scalar_load(
        env,
        src0=vaddr,
        fu_op_type=3,
        rob_idx=int(identity),
        lq_idx=int(identity) & 0x7F,
        sq_idx=int(identity) & 0x3F,
        pc=vaddr + 4,
        max_cycles=max_cycles,
    )
    if response_delay:
        env.Step(int(response_delay))
    injection = api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=paddr,
        tlb_pf_ld=fault_kind == "tlb-pf",
        tlb_gpf_ld=fault_kind == "tlb-gpf",
        tlb_af_ld=fault_kind == "tlb-af",
        pmp_ld=fault_kind == "pmp-ld",
        pmp_mmio=fault_kind == "pmp-mmio",
        dcache_data=0x807F00FF55AA33CC,
        dcache_denied=fault_kind in {"dcache-denied", "denied-corrupt"},
        dcache_corrupt=fault_kind in {"dcache-corrupt", "denied-corrupt"},
        hold_cycles=3,
        max_cycles=3,
    )
    try:
        outputs = api_bosc_LoadUnit_collect_writeback_feedback(env, max_cycles=max_cycles)
    except TimeoutError:
        outputs = None
    return {
        "fault_kind": fault_kind,
        "identity": int(identity),
        "vaddr": vaddr,
        "paddr": paddr,
        "issue": issue,
        "injection": injection,
        "outputs": outputs,
    }

def api_bosc_LoadUnit_observe_lsq_replay_metadata(
    env,
    identity: int,
    metadata_pattern: int,
    vector_pattern: int,
    max_cycles: int = 16,
) -> Dict[str, Any]:
    """Drive a metadata-rich scalar miss and observe its LSQ replay update.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        metadata_pattern: Pattern for scalar uop and debug fields.
        vector_pattern: Pattern for vector metadata carried by the scalar uop bundle.
        max_cycles: Maximum acceptance and replay observation window.

    Returns:
        Accepted request and all owner-matched LSQ replay update snapshots.
    """
    env.set_default_inputs()
    vaddr = 0x520000 + (int(identity) << 6) + (int(metadata_pattern) & 0xF)
    paddr = 0x620000 + (int(identity) << 6) + (int(metadata_pattern) & 0xF)
    _fill_scalar_load_request(
        env, vaddr, 3, int(identity), int(identity) & 0x7F,
        int(identity) & 0x3F, vaddr + 4
    )
    bits = env.scalar_req.bits
    uop = bits.uop
    _api_bosc_LoadUnit_drive_debug_metadata(uop, int(metadata_pattern))
    uop.imm.value = int(metadata_pattern) & ((1 << 64) - 1)
    uop.fpu_rm.value = int(metadata_pattern) & 0x7
    uop.vpu.vmask.value = int(vector_pattern) & ((1 << 256) - 1)
    uop.vpu.vl.value = int(vector_pattern) & 0xFFFF
    uop.vpu.vuopIdx.value = (int(vector_pattern) >> 16) & 0xFF
    uop.vpu.vlmul.value = (int(vector_pattern) >> 24) & 0x7
    uop.vpu.specVlmul.value = (int(vector_pattern) >> 27) & 0x7
    uop.vpu.frm.value = (int(vector_pattern) >> 30) & 0x7
    if hasattr(bits, "gpaddr"):
        bits.gpaddr.value = (int(metadata_pattern) ^ int(vector_pattern)) & ((1 << 50) - 1)
    env.scalar_req.valid.value = 1
    accepted_request = None
    for waited in range(max_cycles):
        ready_now = int(env.scalar_req.ready.value)
        env.Step(1)
        if ready_now:
            accepted_request = bits.as_dict()
            env.scalar_req.valid.value = 0
            break
    if accepted_request is None:
        env.scalar_req.valid.value = 0
        raise TimeoutError("metadata replay request was not accepted")

    env.tlb.resp.valid.value = 1
    env.tlb.resp.bits.miss.value = 0
    getattr(env.tlb.resp.bits.paddr, "0").value = paddr
    env.dcache.resp_bits.handled.value = 0
    env.dcache.resp_bits.miss.value = 1
    observations = []
    for cycle in range(max_cycles):
        if int(env.lsq.ldin.valid.value):
            observations.append(env.lsq.ldin.bits.as_dict())
        env.Step(1)
        if cycle == 3:
            _clear_memory_response_inputs(env)
    _clear_memory_response_inputs(env)
    return {
        "identity": int(identity),
        "vaddr": vaddr,
        "paddr": paddr,
        "request": accepted_request,
        "observations": observations,
    }

def api_bosc_LoadUnit_complete_uncache_uop_metadata(
    env,
    identity: int,
    metadata_pattern: int,
    vector_pattern: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Complete an uncache load carrying wide scalar and vector uop metadata.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        metadata_pattern: Pattern for immediate, operation and debug fields.
        vector_pattern: Pattern for vector metadata fields.
        max_cycles: Maximum request and completion observation window.

    Returns:
        Accepted uncache request and matching scalar writeback.
    """
    env.set_default_inputs()
    vaddr = (int(metadata_pattern) ^ (int(identity) << 8)) & ((1 << 50) - 1)
    paddr = ((~int(metadata_pattern)) ^ (int(identity) << 7)) & ((1 << 48) - 1)
    _fill_uncache_mmio_request(
        env, int(identity), int(identity) & 0x7F, int(identity) & 0x3F,
        vaddr, pdest=(int(identity) & 0x1F) + 1
    )
    bits = env.lsq.uncache.bits
    uop = bits.uop
    _api_bosc_LoadUnit_drive_debug_metadata(uop, int(metadata_pattern))
    uop.pc.value = (vaddr + 4) & ((1 << 50) - 1)
    uop.imm.value = int(metadata_pattern) & ((1 << 64) - 1)
    uop.fuOpType.value = int(metadata_pattern) & 0x1FF
    uop.trigger.value = int(metadata_pattern) & 0xF
    uop.fpu_rm.value = int(metadata_pattern) & 0x7
    uop.vpu.vmask.value = int(vector_pattern) & ((1 << 256) - 1)
    uop.vpu.vlmul.value = (int(vector_pattern) >> 24) & 0x7
    bits.debug.vaddr.value = vaddr
    bits.debug.paddr.value = paddr
    bits.debug.isMMIO.value = 1
    env.pmp.mmio.value = 1
    env.lsq.ld_raw_data.addrOffset.value = int(identity) & 0x7
    env.lsq.ld_raw_data.lqData.value = int(metadata_pattern) & ((1 << 64) - 1)
    env.lsq.ld_raw_data.uop.fuOpType.value = 3
    env.lsq.uncache.valid.value = 1
    accepted_request = None
    for waited in range(max_cycles):
        ready_now = int(env.lsq.uncache.ready.value)
        env.Step(1)
        if ready_now:
            accepted_request = bits.as_dict()
            env.lsq.uncache.valid.value = 0
            break
    if accepted_request is None:
        env.lsq.uncache.valid.value = 0
        raise TimeoutError("wide uncache metadata request was not accepted")
    completion = api_bosc_LoadUnit_wait_for_scalar_owner(
        env, int(identity), int(identity) & 0x7F, max_cycles=max_cycles
    )
    return {
        "request": accepted_request,
        "writeback": completion["writeback"],
        "vaddr": vaddr,
        "paddr": paddr,
    }

def api_bosc_LoadUnit_drive_source_paddr_transitions(
    env,
    patterns: list[int],
    max_cycles: int = 64,
) -> list[Dict[str, int]]:
    """Drive DCache, LSU, SBuffer and UBuffer physical-address inputs.

    Args:
        env: LoadUnit environment fixture.
        patterns: Address patterns applied consecutively without reset.
        max_cycles: Maximum number of patterns accepted by this helper.

    Returns:
        Sampled masked values for each source-address input and pattern.
    """
    if not patterns or len(patterns) > max_cycles:
        raise ValueError("patterns must be nonempty and fit max_cycles")
    env.set_default_inputs()
    names = (
        "io_dcache_s1_paddr_dup_lsu",
        "io_dcache_s1_paddr_dup_dcache",
        "io_sbuffer_paddr",
        "io_ubuffer_paddr",
    )
    samples = []
    for index, pattern in enumerate(patterns):
        values = {
            names[0]: int(pattern) & ((1 << 48) - 1),
            names[1]: (~int(pattern)) & ((1 << 48) - 1),
            names[2]: (int(pattern) ^ 0xAAAAAAAAAAAA) & ((1 << 48) - 1),
            names[3]: (int(pattern) ^ 0x555555555555) & ((1 << 48) - 1),
        }
        for name, value in values.items():
            getattr(env.dut, name).value = value
        env.Step(1)
        samples.append({"index": index, **values})
    env.set_default_inputs()
    return samples

"""Current API delta for coarse input, arbitration, and completion matrices."""

from typing import Any, Dict

def _api_bosc_LoadUnit_drive_available_wide_metadata(uop, pattern: int) -> None:
    """Drive the wide metadata fields implemented by a particular input bundle."""
    mask64 = (1 << 64) - 1
    if hasattr(uop, "debugInfo"):
        for field in (
            "renameTime", "dispatchTime", "enqRsTime", "selectTime", "issueTime",
            "writebackTime", "runahead_checkpoint_id", "tlbFirstReqTime", "tlbRespTime",
        ):
            if hasattr(uop.debugInfo, field):
                getattr(uop.debugInfo, field).value = int(pattern) & mask64
    if hasattr(uop, "debug_seqNum"):
        if hasattr(uop.debug_seqNum, "seqNum"):
            uop.debug_seqNum.seqNum.value = int(pattern) & ((1 << 56) - 1)
        if hasattr(uop.debug_seqNum, "uopIdx"):
            uop.debug_seqNum.uopIdx.value = (int(pattern) >> 56) & 0xFF
    if hasattr(uop, "debug_fuType"):
        uop.debug_fuType.value = int(pattern) & ((1 << 35) - 1)
    if hasattr(uop, "debug"):
        if hasattr(uop.debug, "seqNum"):
            uop.debug.seqNum.seqNum.value = int(pattern) & ((1 << 56) - 1)
            uop.debug.seqNum.uopIdx.value = (int(pattern) >> 56) & 0xFF
        if hasattr(uop.debug, "fuType"):
            uop.debug.fuType.value = int(pattern) & ((1 << 35) - 1)

def _api_bosc_LoadUnit_set_unsigned_wide(pin, value: int, width: int) -> None:
    """Write an unsigned wide value through XData's signed byte conversion."""
    actual_width = int(pin.W())
    masked = int(value) & ((1 << actual_width) - 1)
    pin.value = (
        masked - (1 << actual_width)
        if actual_width > 64 and masked & (1 << (actual_width - 1))
        else masked
    )

def _api_bosc_LoadUnit_drive_small_uop_fields(uop, pattern: int) -> None:
    """Drive scalar, FPU, and VPU control fields shared by rich uop bundles."""
    for name in (
        "uopIdx", "numUops", "numWB", "ssid", "numLsElem", "pdest",
        "commitType", "instrSize", "selImm", "ldest",
    ):
        if hasattr(uop, name):
            pin = getattr(uop, name)
            pin.value = int(pattern) & ((1 << int(pin.W())) - 1)
    if hasattr(uop, "waitForRobIdx"):
        uop.waitForRobIdx.flag.value = int(pattern) & 1
        uop.waitForRobIdx.value.value = int(pattern) & 0xFF
    if hasattr(uop, "traceBlockInPipe"):
        for name in ("itype", "iretire", "ilastsize"):
            if hasattr(uop.traceBlockInPipe, name):
                pin = getattr(uop.traceBlockInPipe, name)
                pin.value = int(pattern) & ((1 << int(pin.W())) - 1)
    if hasattr(uop, "preDecodeInfo"):
        for name in ("valid", "isRVC", "brType", "isCall", "isRet"):
            if hasattr(uop.preDecodeInfo, name):
                pin = getattr(uop.preDecodeInfo, name)
                pin.value = int(pattern) & ((1 << int(pin.W())) - 1)
    if hasattr(uop, "srcLoadDependency"):
        for outer_index in range(5):
            if not hasattr(uop.srcLoadDependency, str(outer_index)):
                continue
            outer = getattr(uop.srcLoadDependency, str(outer_index))
            for inner_index in range(3):
                if hasattr(outer, str(inner_index)):
                    pin = getattr(outer, str(inner_index))
                    pin.value = (
                        int(pattern) >> (outer_index + inner_index)
                    ) & ((1 << int(pin.W())) - 1)
    if hasattr(uop, "exceptionVec"):
        for index in range(24):
            if hasattr(uop.exceptionVec, str(index)):
                getattr(uop.exceptionVec, str(index)).value = (
                    int(pattern) >> (index & 7)
                ) & 1
    for bundle_name in ("psrc", "regCacheIdx", "srcState"):
        if not hasattr(uop, bundle_name):
            continue
        bundle = getattr(uop, bundle_name)
        for index in range(5):
            if hasattr(bundle, str(index)):
                pin = getattr(bundle, str(index))
                pin.value = (int(pattern) >> (index * 5)) & ((1 << int(pin.W())) - 1)
    if hasattr(uop, "fpu"):
        for name in ("typeTagOut", "typ", "fmt", "rm", "wflags"):
            if hasattr(uop.fpu, name):
                pin = getattr(uop.fpu, name)
                pin.value = int(pattern) & ((1 << int(pin.W())) - 1)
    if hasattr(uop, "vpu"):
        for name in (
            "vill", "vma", "vta", "vsew", "vlmul", "specVill", "specVma",
            "specVta", "specVsew", "specVlmul", "vm", "vstart", "frm", "vxrm",
            "vuopIdx", "lastUop", "vl", "nf", "veew", "isReverse", "isExt",
            "isNarrow", "isDstMask", "isOpMask", "isMove", "isDependOldVd",
            "isWritePartVd", "isVleff",
        ):
            if hasattr(uop.vpu, name):
                pin = getattr(uop.vpu, name)
                pin.value = int(pattern) & ((1 << int(pin.W())) - 1)

def api_bosc_LoadUnit_hold_scalar_wide_metadata_under_contention(
    env,
    identity: int,
    metadata_pattern: int,
    vector_pattern: int,
    hold_cycles: int = 2,
    max_cycles: int = 16,
) -> Dict[str, Any]:
    """Hold a metadata-rich scalar request behind a misalign request, then accept it.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ identity carried by the scalar request.
        metadata_pattern: Pattern applied to scalar debug and immediate fields.
        vector_pattern: Pattern applied to the scalar uop vector metadata fields.
        hold_cycles: Cycles for which the higher-priority misalign source contends.
        max_cycles: Maximum cycles allowed for contention and scalar acceptance.

    Returns:
        Stable request snapshots, readiness history, and accepted owner metadata.
    """
    if hold_cycles < 1 or max_cycles <= hold_cycles:
        raise ValueError("max_cycles must exceed a positive hold_cycles value")
    env.set_default_inputs()
    vaddr = (0x180000 + (int(identity) << 6) + (int(metadata_pattern) & 0x3F)) & ((1 << 50) - 1)
    _fill_scalar_load_request(
        env, vaddr, int(metadata_pattern) & 0x1FF, int(identity),
        int(identity) & 0x7F, int(identity) & 0x3F, (vaddr + 4) & ((1 << 50) - 1),
    )
    uop = env.scalar_req.bits.uop
    _api_bosc_LoadUnit_set_unsigned_wide(
        getattr(env.scalar_req.bits.src, "0"), metadata_pattern, 0
    )
    _api_bosc_LoadUnit_drive_available_wide_metadata(uop, int(metadata_pattern))
    _api_bosc_LoadUnit_drive_small_uop_fields(uop, int(metadata_pattern))
    uop.imm.value = int(metadata_pattern) & ((1 << 64) - 1)
    if hasattr(uop, "fpu_rm"):
        uop.fpu_rm.value = int(metadata_pattern) & 0x7
    if hasattr(uop, "trigger"):
        uop.trigger.value = int(metadata_pattern) & 0xF
    if hasattr(uop, "vpu"):
        _api_bosc_LoadUnit_set_unsigned_wide(uop.vpu.vmask, vector_pattern, 256)
        uop.vpu.vl.value = int(vector_pattern) & 0xFFFF
        uop.vpu.vuopIdx.value = (int(vector_pattern) >> 16) & 0xFF
        uop.vpu.vlmul.value = (int(vector_pattern) >> 24) & 0x7
        uop.vpu.specVlmul.value = (int(vector_pattern) >> 27) & 0x7
        uop.vpu.frm.value = (int(vector_pattern) >> 30) & 0x7

    _fill_misalign_blocker_request(
        env, (vaddr + 0x100) & ((1 << 50) - 1),
        rob_idx=(int(identity) + 1) & 0xFF,
        lq_idx=(int(identity) + 1) & 0x7F,
    )
    env.scalar_req.valid.value = 1
    env.misalign.ldin.valid.value = 1
    before = env.scalar_req.bits.as_dict()
    ready_history = []
    for _ in range(hold_cycles):
        ready_history.append(int(env.scalar_req.ready.value))
        env.Step(1)
    held = env.scalar_req.bits.as_dict()
    env.misalign.ldin.valid.value = 0

    accepted = None
    for waited in range(max_cycles - hold_cycles):
        ready_now = int(env.scalar_req.ready.value)
        ready_history.append(ready_now)
        env.Step(1)
        if ready_now:
            accepted = env.scalar_req.bits.as_dict()
            env.scalar_req.valid.value = 0
            break
    env.scalar_req.valid.value = 0
    if accepted is None:
        raise TimeoutError("contended scalar metadata request was not accepted")
    return {
        "identity": int(identity),
        "vaddr": vaddr,
        "ready_history": ready_history,
        "blocked": any(value == 0 for value in ready_history[:hold_cycles]),
        "payload_stable": before == held == accepted,
        "debug_width": int(uop.debugInfo.selectTime.W()),
        "request": accepted,
    }

def api_bosc_LoadUnit_send_misalign_wide_uop_pattern(
    env,
    identity: int,
    metadata_pattern: int,
    vector_pattern: int,
    address_pattern: int,
    mask: int,
    split_flags: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Send one misalign request carrying full-width debug and vector metadata.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        metadata_pattern: Pattern applied to debug, immediate, and operation fields.
        vector_pattern: Pattern applied to the 256-bit vmask and vector controls.
        address_pattern: Pattern folded independently into vaddr, paddr, and gpaddr.
        mask: Sixteen-bit byte mask.
        split_flags: Final-split, 128-bit, and wakeup flags in bits zero through two.
        max_cycles: Maximum ready/valid acceptance window.

    Returns:
        Accepted request snapshot, derived addresses, and payload stability.
    """
    if max_cycles <= 0:
        raise ValueError("max_cycles must be positive")
    env.set_default_inputs()
    vaddr = int(address_pattern) & ((1 << int(env.misalign.ldin.bits.vaddr.W())) - 1)
    paddr = ((int(address_pattern) >> 2) ^ int(metadata_pattern)) & ((1 << 48) - 1)
    gpaddr = (
        (int(address_pattern) << 1) ^ int(metadata_pattern)
    ) & ((1 << int(env.misalign.ldin.bits.gpaddr.W())) - 1)
    _fill_misalign_blocker_request(
        env, vaddr, rob_idx=int(identity), lq_idx=int(identity) & 0x7F
    )
    bits = env.misalign.ldin.bits
    uop = bits.uop
    _api_bosc_LoadUnit_drive_available_wide_metadata(uop, int(metadata_pattern))
    _api_bosc_LoadUnit_drive_small_uop_fields(uop, int(metadata_pattern))
    _set_flag_value(uop.sqIdx, int(identity) & 0x3F)
    uop.pc.value = (vaddr + 4) & ((1 << 50) - 1)
    uop.imm.value = int(metadata_pattern) & ((1 << 64) - 1)
    uop.fuOpType.value = int(metadata_pattern) & 0x1FF
    uop.trigger.value = int(metadata_pattern) & 0xF
    _api_bosc_LoadUnit_set_unsigned_wide(uop.vpu.vmask, vector_pattern, 256)
    uop.vpu.vl.value = int(vector_pattern) & 0xFFFF
    uop.vpu.vuopIdx.value = (int(vector_pattern) >> 16) & 0xFF
    uop.vpu.vlmul.value = (int(vector_pattern) >> 24) & 0x7
    uop.vpu.specVlmul.value = (int(vector_pattern) >> 27) & 0x7
    uop.vpu.frm.value = (int(vector_pattern) >> 30) & 0x7
    if hasattr(bits, "mBIndex"):
        bits.mBIndex.value = int(metadata_pattern) & 0xF
    bits.paddr.value = paddr
    if hasattr(bits, "fullva"):
        _api_bosc_LoadUnit_set_unsigned_wide(bits.fullva, address_pattern, 0)
    bits.gpaddr.value = gpaddr
    bits.mask.value = int(mask) & 0xFFFF
    bits.isFinalSplit.value = int(bool(int(split_flags) & 1))
    bits.is128bit.value = int(bool(int(split_flags) & 2))
    bits.misalignNeedWakeUp.value = int(bool(int(split_flags) & 4))
    if hasattr(bits, "schedIndex"):
        bits.schedIndex.value = int(metadata_pattern) & 0x7F
    if hasattr(bits, "mshrid"):
        bits.mshrid.value = int(metadata_pattern) & 0xF
    env.misalign.ldin.valid.value = 1
    before = bits.as_dict()
    for waited in range(max_cycles):
        ready_now = int(env.misalign.ldin.ready.value)
        env.Step(1)
        if ready_now:
            accepted = bits.as_dict()
            env.misalign.ldin.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited,
                "payload_stable": before == accepted,
                "vmask_width": int(uop.vpu.vmask.W()),
                "request": accepted,
                "vaddr": vaddr,
                "paddr": paddr,
                "gpaddr": gpaddr,
            }
    env.misalign.ldin.valid.value = 0
    raise TimeoutError("wide misalign uop request was not accepted")

def api_bosc_LoadUnit_send_vector_wide_uop_pattern(
    env,
    identity: int,
    metadata_pattern: int,
    vector_pattern: int,
    address_pattern: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Send a vector request with full-width uop metadata and observe its issue owner.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ identity carried by the vector request.
        metadata_pattern: Pattern applied to debug, immediate, and operation fields.
        vector_pattern: Pattern applied to vector mask and vector controls.
        address_pattern: Virtual address pattern used by the request.
        max_cycles: Maximum request and downstream observation window.

    Returns:
        Accepted input snapshot and matching DCache/TLB issue observations.
    """
    if max_cycles <= 0:
        raise ValueError("max_cycles must be positive")
    env.set_default_inputs()
    vaddr = int(address_pattern) & ((1 << int(env.vector_req.bits.vaddr.W())) - 1)
    _fill_vector_load_request(
        env, vaddr, int(vector_pattern) & 0xFFFF,
        (int(vector_pattern) >> 16) & 0xFF,
        (int(vector_pattern) >> 24) & 0xFF,
        (int(vector_pattern) >> 32) & 0xFF,
        int(metadata_pattern) & 0x7, 1,
        int(identity), int(identity) & 0x7F,
        (vaddr + 4) & ((1 << 50) - 1),
    )
    bits = env.vector_req.bits
    uop = bits.uop
    if hasattr(bits, "mBIndex"):
        bits.mBIndex.value = int(metadata_pattern) & 0xF
    _api_bosc_LoadUnit_drive_available_wide_metadata(uop, int(metadata_pattern))
    _api_bosc_LoadUnit_drive_small_uop_fields(uop, int(metadata_pattern))
    if hasattr(uop, "imm"):
        uop.imm.value = int(metadata_pattern) & ((1 << 64) - 1)
    uop.fuOpType.value = int(metadata_pattern) & 0x1FF
    if hasattr(uop, "trigger"):
        uop.trigger.value = int(metadata_pattern) & 0xF
    _api_bosc_LoadUnit_set_unsigned_wide(uop.vpu.vmask, vector_pattern, 256)
    uop.vpu.vl.value = int(vector_pattern) & 0xFFFF
    uop.vpu.vuopIdx.value = (int(vector_pattern) >> 16) & 0xFF
    uop.vpu.vstart.value = (int(vector_pattern) >> 40) & 0xFF
    uop.vpu.nf.value = (int(vector_pattern) >> 48) & 0x7
    uop.vpu.vlmul.value = (int(vector_pattern) >> 24) & 0x7
    uop.vpu.specVlmul.value = (int(vector_pattern) >> 27) & 0x7
    uop.vpu.frm.value = (int(vector_pattern) >> 30) & 0x7
    if hasattr(uop, "psrc"):
        for source_index in range(5):
            getattr(uop.psrc, str(source_index)).value = (
                int(metadata_pattern) >> (source_index * 8)
            ) & 0xFF
    env.vector_req.valid.value = 1
    before = bits.as_dict()
    dcache = None
    tlb = None
    for waited in range(max_cycles):
        ready_now = int(env.vector_req.ready.value)
        env.Step(1)
        if int(env.dcache.req.valid.value):
            dcache = env.dcache.req.bits.as_dict()
        if int(env.tlb.req.valid.value):
            tlb = env.tlb.req.bits.as_dict()
        if ready_now:
            accepted = bits.as_dict()
            env.vector_req.valid.value = 0
            for _ in range(3):
                if dcache is not None and tlb is not None:
                    break
                env.Step(1)
                if int(env.dcache.req.valid.value):
                    dcache = env.dcache.req.bits.as_dict()
                if int(env.tlb.req.valid.value):
                    tlb = env.tlb.req.bits.as_dict()
            return {
                "accepted": True,
                "wait_cycles": waited,
                "payload_stable": before == accepted,
                "vmask_width": int(uop.vpu.vmask.W()),
                "request": accepted,
                "dcache": dcache,
                "tlb": tlb,
                "vaddr": vaddr,
            }
    env.vector_req.valid.value = 0
    raise TimeoutError("wide vector metadata request was not accepted")

def api_bosc_LoadUnit_drive_memory_control_transition_matrix(
    env,
    patterns: list[int],
    max_cycles: int = 32,
) -> list[Dict[str, int]]:
    """Drive coherent control and memory-response input transitions.

    Args:
        env: LoadUnit environment fixture.
        patterns: Consecutive patterns for redirect, CSR, TLB, cache, and forward inputs.
        max_cycles: Maximum number of matrix rows accepted by this helper.

    Returns:
        Per-cycle input samples masked to the implemented interface widths.
    """
    if not patterns or len(patterns) > max_cycles:
        raise ValueError("patterns must be nonempty and fit max_cycles")
    env.set_default_inputs()
    samples = []
    for index, raw_pattern in enumerate(patterns):
        pattern = int(raw_pattern)
        bit = pattern & 1
        env.redirect.valid.value = bit
        env.redirect.bits.robIdx.flag.value = bit
        env.redirect.bits.robIdx.value.value = pattern & 0xFF
        env.redirect.bits.level.value = bit
        env.csr_ctrl.ldld_vio_check_enable.value = bit
        env.csr_ctrl.hd_misalign_ld_enable.value = bit

        scalar_uop = env.scalar_req.bits.uop
        scalar_uop.debugInfo.eliminatedMove.value = bit
        scalar_uop.waitForRobIdx.flag.value = bit
        scalar_uop.waitForRobIdx.value.value = pattern & 0xFF

        env.tlb.resp.valid.value = 1
        _api_bosc_LoadUnit_set_unsigned_wide(
            getattr(env.tlb.resp.bits.gpaddr, "0"), pattern, 0
        )
        _api_bosc_LoadUnit_set_unsigned_wide(env.tlb.resp.bits.fullva, pattern, 0)
        _api_bosc_LoadUnit_set_unsigned_wide(
            getattr(env.tlb.resp.bits.paddr, "0"), pattern, 0
        )
        if hasattr(env.tlb.resp.bits.paddr, "1"):
            _api_bosc_LoadUnit_set_unsigned_wide(
                getattr(env.tlb.resp.bits.paddr, "1"), ~pattern, 0
            )

        direct_values = {
            "io_dcache_s1_paddr_dup_lsu": pattern & ((1 << 48) - 1),
            "io_dcache_s1_paddr_dup_dcache": (~pattern) & ((1 << 48) - 1),
            "io_sbuffer_paddr": (pattern ^ 0xAAAAAAAAAAAA) & ((1 << 48) - 1),
            "io_ubuffer_paddr": (pattern ^ 0x555555555555) & ((1 << 48) - 1),
            "io_dcache_resp_bits_mshr_id": pattern & 0xF,
            "io_dcache_resp_bits_meta_prefetch": pattern & 0x7,
            "io_pmp_st": bit,
            "io_pmp_instr": bit,
            "io_dcache_req_ready": bit,
            "io_sbuffer_matchInvalid": bit,
            "io_ubuffer_matchInvalid": bit,
        }
        for lane in range(16):
            direct_values[f"io_ubuffer_forwardData_{lane}"] = (
                pattern >> ((lane & 7) * 8)
            ) & 0xFF
        for name, value in direct_values.items():
            getattr(env.dut, name).value = value
        env.Step(1)
        samples.append({
            "index": index,
            "redirect_valid": bit,
            "redirect_rob_value": pattern & 0xFF,
            "tlb_fullva": pattern & ((1 << int(env.tlb.resp.bits.fullva.W())) - 1),
            **direct_values,
        })
    env.redirect.valid.value = 0
    env.tlb.resp.valid.value = 0
    env.set_default_inputs()
    return samples

def api_bosc_LoadUnit_observe_misalign_terminal_outcome(
    env,
    identity: int,
    metadata_pattern: int,
    vector_pattern: int,
    address_pattern: int,
    data_pattern: int,
    outcome: str,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Run a rich misalign owner to a hit response or LSQ replay update.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ identity carried end to end.
        metadata_pattern: Pattern applied to debug and operation metadata.
        vector_pattern: Pattern applied to vector metadata.
        address_pattern: Pattern applied to virtual, physical, guest, and full addresses.
        data_pattern: 128-bit DCache response payload.
        outcome: Either hit or miss.
        max_cycles: Maximum response and output observation window.

    Returns:
        Accepted request plus owner-matched misalign and LSQ output snapshots.
    """
    if outcome not in {"hit", "miss"}:
        raise ValueError("outcome must be hit or miss")
    request = api_bosc_LoadUnit_send_misalign_wide_uop_pattern(
        env,
        identity=int(identity),
        metadata_pattern=int(metadata_pattern),
        vector_pattern=int(vector_pattern),
        address_pattern=int(address_pattern),
        mask=0xFFFF,
        split_flags=3,
        max_cycles=max_cycles,
    )
    _clear_memory_response_inputs(env)
    env.tlb.resp.valid.value = 1
    _api_bosc_LoadUnit_set_unsigned_wide(
        getattr(env.tlb.resp.bits.paddr, "0"), address_pattern, 0
    )
    _api_bosc_LoadUnit_set_unsigned_wide(
        getattr(env.tlb.resp.bits.gpaddr, "0"), ~int(address_pattern), 0
    )
    _api_bosc_LoadUnit_set_unsigned_wide(env.tlb.resp.bits.fullva, address_pattern, 0)
    _api_bosc_LoadUnit_set_unsigned_wide(env.dcache.resp_bits.data, data_pattern, 0)
    env.dcache.resp_bits.handled.value = int(outcome == "hit")
    env.dcache.resp_bits.miss.value = int(outcome == "miss")

    misalign_outputs = []
    lsq_outputs = []
    for cycle in range(max_cycles):
        if int(env.misalign.ldout.valid.value):
            misalign_outputs.append(env.misalign.ldout.bits.as_dict())
        if int(env.lsq.ldin.valid.value):
            lsq_outputs.append(env.lsq.ldin.bits.as_dict())
        env.Step(1)
        if cycle == 4:
            _clear_memory_response_inputs(env)
    _clear_memory_response_inputs(env)
    return {
        "identity": int(identity),
        "outcome": outcome,
        "request": request,
        "misalign_outputs": misalign_outputs,
        "lsq_outputs": lsq_outputs,
    }

def api_bosc_LoadUnit_send_uncache_transition_pattern(
    env,
    identity: int,
    metadata_pattern: int,
    vector_pattern: int,
    max_cycles: int = 20,
) -> Dict[str, Any]:
    """Accept an uncache request carrying complementary scalar/vector metadata.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ/SQ transaction identity.
        metadata_pattern: Immediate, operation, trigger, and debug metadata pattern.
        vector_pattern: Vector metadata pattern, masked to implemented widths.
        max_cycles: Maximum ready/valid acceptance window.

    Returns:
        Accepted request snapshot and implemented vector-mask width.
    """
    env.set_default_inputs()
    vaddr = int(metadata_pattern) & ((1 << 50) - 1)
    _fill_uncache_mmio_request(
        env, int(identity), int(identity) & 0x7F, int(identity) & 0x3F,
        vaddr, pdest=(int(identity) & 0x1F) + 1,
    )
    uop = env.lsq.uncache.bits.uop
    _api_bosc_LoadUnit_drive_available_wide_metadata(uop, metadata_pattern)
    _api_bosc_LoadUnit_drive_small_uop_fields(uop, metadata_pattern)
    uop.imm.value = int(metadata_pattern) & ((1 << int(uop.imm.W())) - 1)
    uop.fuOpType.value = int(metadata_pattern) & ((1 << int(uop.fuOpType.W())) - 1)
    if hasattr(uop, "trigger"):
        uop.trigger.value = int(metadata_pattern) & ((1 << int(uop.trigger.W())) - 1)
    if hasattr(uop, "vpu"):
        _api_bosc_LoadUnit_set_unsigned_wide(uop.vpu.vmask, vector_pattern, 0)
        uop.vpu.nf.value = (int(vector_pattern) >> 48) & 0x7
        uop.vpu.vstart.value = (int(vector_pattern) >> 40) & 0xFF
    env.lsq.uncache.valid.value = 1
    before = env.lsq.uncache.bits.as_dict()
    for waited in range(max_cycles):
        ready_now = int(env.lsq.uncache.ready.value)
        env.Step(1)
        if ready_now:
            accepted = env.lsq.uncache.bits.as_dict()
            env.lsq.uncache.valid.value = 0
            return {
                "accepted": True,
                "wait_cycles": waited,
                "payload_stable": before == accepted,
                "request": accepted,
            }
    env.lsq.uncache.valid.value = 0
    raise TimeoutError("uncache transition request was not accepted")

def api_bosc_LoadUnit_complete_vector_transition_pattern(
    env,
    identity: int,
    metadata_pattern: int,
    vector_pattern: int,
    address_pattern: int,
    data_pattern: int,
    max_cycles: int = 24,
) -> Dict[str, Any]:
    """Complete a rich vector owner through TLB and DCache to vector writeback.

    Args:
        env: LoadUnit environment fixture.
        identity: ROB/LQ identity carried by the vector request.
        metadata_pattern: Pattern applied to vector uop control fields.
        vector_pattern: Pattern applied to vector mask and lane controls.
        address_pattern: Virtual and translated address pattern.
        data_pattern: 128-bit DCache response payload.
        max_cycles: Maximum request and completion observation window.

    Returns:
        Accepted request plus all observed vector writeback snapshots.
    """
    request = api_bosc_LoadUnit_send_vector_wide_uop_pattern(
        env, identity, metadata_pattern, vector_pattern, address_pattern,
        max_cycles=max_cycles,
    )
    api_bosc_LoadUnit_inject_memory_resp(
        env,
        tlb_valid=True,
        tlb_paddr=int(address_pattern) & ((1 << 48) - 1),
        dcache_data=int(data_pattern) & ((1 << 128) - 1),
        hold_cycles=3,
        max_cycles=3,
    )
    outputs = []
    for _ in range(max_cycles):
        if int(env.vector_resp.valid.value):
            outputs.append(env.vector_resp.bits.as_dict())
        env.Step(1)
    return {"request": request, "outputs": outputs, "identity": int(identity)}

"""Current API delta for interface-wide payload and control transitions."""

from typing import Dict

def _api_bosc_LoadUnit_input_pin_records(node, prefix=()):
    records = []
    for name, value in node.items():
        if name == "_":
            continue
        if isinstance(value, dict) and "Pin" in value:
            if value["Pin"] == "input":
                records.append((prefix + (name,), value))
            continue
        if isinstance(value, dict):
            records.extend(_api_bosc_LoadUnit_input_pin_records(value, prefix + (name,)))
    return records

def api_bosc_LoadUnit_drive_interface_transition_matrix(
    env,
    patterns: list[int],
    dwell_cycles: int = 1,
    max_cycles: int = 16,
) -> list[Dict[str, int]]:
    """Drive every implemented IO input through coherent bit-pattern transitions.

    Args:
        env: LoadUnit environment fixture.
        patterns: Consecutive zero, ones, checkerboard, or walking-bit patterns.
        dwell_cycles: Number of cycles each applied pattern remains resident.
        max_cycles: Maximum number of transition rows.

    Returns:
        Per-row counts and representative values read back from driven input pins.
    """
    if not patterns or len(patterns) > max_cycles or dwell_cycles < 1:
        raise ValueError("patterns must be nonempty and fit max_cycles")
    records = _api_bosc_LoadUnit_input_pin_records(_LOADUNIT_SIGNAL_TREE["io"])
    if not records:
        raise RuntimeError("signals.json contains no implemented IO inputs")
    env.set_default_inputs()
    samples = []
    for row_index, raw_pattern in enumerate(patterns):
        driven = 0
        representative = {}
        for path, descriptor in records:
            flat_name = "io_" + "_".join(path)
            if not hasattr(env.dut, flat_name):
                continue
            pin = getattr(env.dut, flat_name)
            high = int(descriptor.get("High", -1))
            low = int(descriptor.get("Low", 0))
            width = 1 if high < low else high - low + 1
            mask = (1 << width) - 1
            mixed = int(raw_pattern) ^ (row_index * 0x9E3779B97F4A7C15)
            value = mixed & mask
            pin.value = value - (1 << width) if width > 64 and value & (1 << (width - 1)) else value
            driven += 1
            if len(representative) < 8:
                representative[flat_name] = value
        env.Step(dwell_cycles)
        samples.append({"row": row_index, "driven": driven, **representative})
    env.set_default_inputs()
    env.Step(2)
    return samples
