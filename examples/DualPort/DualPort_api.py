#coding=utf-8


class DutPins:
    def __init__(self, pin_maps):
        self.pins = pin_maps
    def __getattribute__(self, name):
        if name in self.pins:
            return self.pins[name]
        return super().__getattribute__(name)


def api_DualPort_reset(dut):
    """Reset the DUT by setting rst to 1 for one cycle, then set it back to 0."""
    dut.rst.value = 1
    dut.Step(1)
    dut.rst.value = 0
    dut.Step(1)
    return True


def api_DualPort_push_and_pop(dut, data_for_port_0: list, data_for_port_1: list, ex_cycles=10):
    """Push and pop data on two ports of the DUT.
    Each cycle, push/pop data from data_for_port_0 and data_for_port_1,
    If the data is None, skip that cycle.
    If the data is a number, perform a push operation.
    If the data is a string "POP", perform a pop operation.
    The popped values are collected in ret_pop_list_0 and ret_pop_list_1.
    If the DUT is not ready for push/pop operations, the operation is delayed to the next cycle.
    Example:
        api_DualPort_push_and_pop(dut,
            [1, 2, 3],
            [1, None, "POP"]
            )
        returns:
            ret_pop_list_0: []
            ret_pop_list_1: [3]
    Args:
        dut: The DualPort instance.
        data_for_port_0: List of data to push/pop for port 0.
        data_for_port_1: List of data to push/pop for port 1.
        ex_cycles: Extra cycles to wait after all data has been processed.
    Returns:
        ret_pop_list_0: List of popped values from port 0.
        ret_pop_list_1: List of popped values from port 1.
    """
    port0 = DutPins({
        "in_valid": dut.in0_valid, "in_ready": dut.in0_ready,   "in_data": dut.in0_data,
        "in_cmd": dut.in0_cmd,     "out_valid": dut.out0_valid, "out_ready": dut.out0_ready,
        "out_data": dut.out0_data, "out_cmd": dut.out0_cmd,
    })
    port1 = DutPins({
        "in_valid": dut.in1_valid, "in_ready": dut.in1_ready,   "in_data": dut.in1_data,
        "in_cmd": dut.in1_cmd,     "out_valid": dut.out1_valid, "out_ready": dut.out1_ready,
        "out_data": dut.out1_data, "out_cmd": dut.out1_cmd,
    })
    ret_pop_list_0 = []
    ret_pop_list_1 = []
    def push(port, data):
        if data is None:
            return True
        if port.in_ready.value == 1:
            port.in_valid.value = 1
            port.in_cmd.value = 0
            port.in_data.value = data
            return True
        return False
    def pop(port, ret_list):
        if port.out_valid.value == 1:
            ret_list.append(port.out_data.value)
            return True
        return False
    def push_pop_task(data_list, port, ret_list):
        port.in_valid.value = 0
        port.out_ready.value = 0
        if len(data_list) == 0:
            return
        data = data_list[0]
        if data != "POP":
            if push(port, data):
                data_list.pop(0)
        else:
            port.out_ready.value = 1
            if pop(port, ret_list):
                data_list.pop(0)
    dut.xclock.ClearRisCallBacks()
    dut.StepRis(lambda c: push_pop_task(data_for_port_0, port0, ret_pop_list_0))
    dut.StepRis(lambda c: push_pop_task(data_for_port_1, port1, ret_pop_list_1))
    while len(data_for_port_1) > 0 or len(data_for_port_0) > 0:
        dut.Step(1)
    if ex_cycles > 0:
        dut.Step(ex_cycles)
    dut.xclock.ClearRisCallBacks()
    return ret_pop_list_0, ret_pop_list_1
