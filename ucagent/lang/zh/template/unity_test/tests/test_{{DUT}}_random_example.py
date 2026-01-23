#coding=utf-8

from {{DUT}}_api import * # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误
import ucagent

# 根据需要定义随机测试函数
#def test_random_add_normal(env):
#    env.dut.fc_cover["FG-A"].mark_function("FC-ADD", test_add_normal, ["CK-NORM1", "CK-NORM2"])  # 通过属性fc_cover获取覆盖分组，然后标记该函数覆盖了哪个功能和哪些检测点
#    env.dut.fc_cover["FG-B"].mark_function("FC-SUB", test_add_normal, ["CK-NORM3"])  # 如果该用例和多个功能点相关，则需要多次调用 mark_function 分别进行功能点-检查点标记
#    import random
#    for c in range(ucagent.repeat_count()):
#        a = random.randint(0, 100)
#        b = random.randint(0, 100)
#        out, _ = api_alu_operation(env, 0, a, b)
#        assert out == 3, f"ALU add fail: {a} + {b} expect out==3, but find: {out}"

# 其他随机测试用例