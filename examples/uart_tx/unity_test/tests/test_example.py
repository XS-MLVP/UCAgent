#coding=utf-8

from Uart_tx_api import * # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误


# 根据需要定义测试函数
#def test_add_normal(env):
#    out, _ = api_alu_operation(env, 0, 1, 2)
#    env.dut.fc_cover["FG-A"].mark_function("FC-ADD", test_add_normal, ["CK-NORM1", "CK-NORM2"])  # 通过属性fc_cover获取覆盖分组，然后标记该函数覆盖了哪个功能和哪些检测点
#    env.dut.fc_cover["FG-B"].mark_function("FC-SUB", test_add_normal, ["CK-NORM3"])  # 如果该用例和多个功能点相关，则需要多次调用 mark_function 分别进行功能点-检查点标记
#    assert out == 3


# 请根据任务需要，完成所有test的编写，每个test函数都需要用mark_function进行检测点标记

# Your test functions here:
# ...

# 如果测试用例很多，你需要编写多个 test_*.py 文件
# 例如 test_add.py, test_sub.py 等等
# ...
