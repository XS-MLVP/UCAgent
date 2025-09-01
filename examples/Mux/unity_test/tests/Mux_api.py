
import os
from Mux import DUTMux

def create_dut():
    """
    创建并初始化Mux DUT实例。

    本函数负责实例化Mux的DUT（Design Under Test），并根据需要进行基本配置，
    例如开启波形追踪。

    Returns:
        DUTMux: 配置完成的Mux DUT实例。
    """
    # 实例化DUT
    dut = DUTMux()

    # 根据需要开启波形（VCD）记录
    # 通过环境变量控制是否生成波形文件，方便调试
    if os.getenv("ENABLE_WAVEFORM", "0") == "1":
        # 定义波形文件的输出路径
        waveform_path = "unity_test/waveforms/Mux_waveform.vcd"
        # 确保波形文件所在目录存在
        os.makedirs(os.path.dirname(waveform_path), exist_ok=True)
        # 设置波形文件
        dut.SetWaveform(waveform_path)
        dut.OpenWaveform()

    return dut

import pytest
from toffee_test.reporter import set_func_coverage
from unity_test.tests.Mux_function_coverage_def import get_coverage_groups

@pytest.fixture()
def dut(request):
    """
    Pytest fixture for Mux DUT.

    - 创建DUT实例
    - 设置功能覆盖率
    - 管理DUT生命周期

    Args:
        request: Pytest request object.

    Yields:
        DUTMux: The Mux DUT instance.
    """
    dut = create_dut()

    # Get functional coverage groups
    func_coverage_group = get_coverage_groups(dut)

    # Set coverage sample callback
    if func_coverage_group:
        dut.StepRis(lambda _: [g.sample() for g in func_coverage_group])

    # Bind coverage groups to DUT instance
    setattr(dut, "fc_cover", {g.name: g for g in func_coverage_group})

    yield dut

    # Teardown
    if func_coverage_group:
        set_func_coverage(request, func_coverage_group)
        for g in func_coverage_group:
            g.clear()
    dut.Finish()

def api_Mux_select(dut, sel_value, in_data_value):
    """
    通用Mux选择API

    Args:
        dut: DUT实例
    in_data_value (int): 4个输入信号的值, e.g. 0b1110

    Returns:
        int: Mux的输出值
    """
    dut.sel.value = sel_value
    dut.sel.value = sel_value
    dut.in_data.value = in_data_value
    dut.Step(1)
    return dut.out.value
