from Mux_api import *  # 导入DUT相关的API函数, 必须用 import *， 而不是 import env，不然会出现 dut 没定义错误


def test_sel_11_should_select_in_data_3(env):
    """测试sel=11时应该选择in_data[3]作为输出"""
    # 标记功能覆盖点
    env.dut.fc_cover["FG-SELECT"].mark_function("FC-BASIC-SELECT", test_sel_11_should_select_in_data_3, ["CK-SEL-11"])
    
    # 根据常规4选1多路选择器的设计，sel=11应该选择in_data[3]
    # 但当前MUX设计选择了in_data[0]，这确实是一个设计缺陷
    
    # 设置in_data[3]=1, 其他位为0，sel=11
    output = api_Mux_select(env, 0b1000, 0b11)  # in_data[3] = 1, sel = 11
    # 按照常规设计，输出应该是1 (选择in_data[3])
    # 但按照当前设计，输出是0 (选择了in_data[0])
    # 这个测试应该失败，以暴露设计缺陷
    assert output == 1, f"按照常规4选1多路选择器设计，sel=11时应选择in_data[3]，期望输出1，实际输出{output}"
    
    # 再测试一个用例：in_data[3]=0, in_data[0]=1, sel=11
    output = api_Mux_select(env, 0b0001, 0b11)  # in_data[0] = 1, sel = 11
    assert output == 0, f"按照常规4选1多路选择器设计，sel=11时应选择in_data[3]=0，期望输出0，实际输出{output}"