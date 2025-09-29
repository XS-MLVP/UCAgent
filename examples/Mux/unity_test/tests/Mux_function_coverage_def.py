#coding=utf-8

import toffee.funcov as fc


# 创建功能覆盖组
funcov_api = fc.CovGroup("FG-API")
funcov_select = fc.CovGroup("FG-SELECT")
funcov_boundary = fc.CovGroup("FG-BOUNDARY")
funcov_groups = [funcov_api, funcov_select, funcov_boundary]


# 为FG-API组添加检查点
def init_coverage_group_api(g, dut):
    """初始化API功能覆盖组"""
    g.add_watch_point(dut,
        {
            "CK-SEL-00": lambda x: x.sel.value == 0b00 and x.out.value == ((x.in_data.value >> 0) & 1),
            "CK-SEL-01": lambda x: x.sel.value == 0b01 and x.out.value == ((x.in_data.value >> 1) & 1),
            "CK-SEL-10": lambda x: x.sel.value == 0b10 and x.out.value == ((x.in_data.value >> 2) & 1),
            "CK-SEL-11": lambda x: x.sel.value == 0b11 and x.out.value == ((x.in_data.value >> 0) & 1),
        },
        name="FC-SELECT")


# 为FG-SELECT组添加检查点
def init_coverage_group_select(g, dut):
    """初始化选择功能覆盖组"""
    # 基本选择功能
    g.add_watch_point(dut,
        {
            "CK-SEL-00": lambda x: x.sel.value == 0b00 and x.out.value == ((x.in_data.value >> 0) & 1),
            "CK-SEL-01": lambda x: x.sel.value == 0b01 and x.out.value == ((x.in_data.value >> 1) & 1),
            "CK-SEL-10": lambda x: x.sel.value == 0b10 and x.out.value == ((x.in_data.value >> 2) & 1),
            "CK-SEL-11": lambda x: x.sel.value == 0b11 and x.out.value == ((x.in_data.value >> 0) & 1),
        },
        name="FC-BASIC-SELECT")
    
    # 输入通道连通性
    g.add_watch_point(dut,
        {
            "CK-CHANNEL-0": lambda x: x.out.value == ((x.in_data.value >> 0) & 1),
            "CK-CHANNEL-1": lambda x: x.out.value == ((x.in_data.value >> 1) & 1),
            "CK-CHANNEL-2": lambda x: x.out.value == ((x.in_data.value >> 2) & 1),
            "CK-CHANNEL-3": lambda x: x.out.value == ((x.in_data.value >> 3) & 1),
        },
        name="FC-CHANNEL-CONNECT")


# 为FG-BOUNDARY组添加检查点
def init_coverage_group_boundary(g, dut):
    """初始化边界条件覆盖组"""
    # 默认路径处理
    g.add_watch_point(dut,
        {
            "CK-DEFAULT": lambda x: x.sel.value == 0b11 and x.out.value == ((x.in_data.value >> 0) & 1),
        },
        name="FC-DEFAULT-PATH")
    
    # 全1输入测试
    g.add_watch_point(dut,
        {
            "CK-ALL-ONE-SEL-00": lambda x: x.in_data.value == 0b1111 and x.sel.value == 0b00 and x.out.value == 1,
            "CK-ALL-ONE-SEL-01": lambda x: x.in_data.value == 0b1111 and x.sel.value == 0b01 and x.out.value == 1,
            "CK-ALL-ONE-SEL-10": lambda x: x.in_data.value == 0b1111 and x.sel.value == 0b10 and x.out.value == 1,
            "CK-ALL-ONE-SEL-11": lambda x: x.in_data.value == 0b1111 and x.sel.value == 0b11 and x.out.value == 1,
        },
        name="FC-ALL-ONE")
    
    # 全0输入测试
    g.add_watch_point(dut,
        {
            "CK-ALL-ZERO-SEL-00": lambda x: x.in_data.value == 0b0000 and x.sel.value == 0b00 and x.out.value == 0,
            "CK-ALL-ZERO-SEL-01": lambda x: x.in_data.value == 0b0000 and x.sel.value == 0b01 and x.out.value == 0,
            "CK-ALL-ZERO-SEL-10": lambda x: x.in_data.value == 0b0000 and x.sel.value == 0b10 and x.out.value == 0,
            "CK-ALL-ZERO-SEL-11": lambda x: x.in_data.value == 0b0000 and x.sel.value == 0b11 and x.out.value == 0,
        },
        name="FC-ALL-ZERO")


def init_function_coverage(dut):
    """初始化所有功能覆盖组"""
    # 初始化各功能组的检查点
    init_coverage_group_api(funcov_api, dut)
    init_coverage_group_select(funcov_select, dut)
    init_coverage_group_boundary(funcov_boundary, dut)


def get_coverage_groups(dut):
    # 初始化功能覆盖组
    init_function_coverage(dut)
    return funcov_groups
