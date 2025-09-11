#coding=utf-8

class DutPins:
    """DutPins provides dynamic access to DUT pins based on a provided mapping."""
    def __init__(self, pin_maps):
        self.pins = pin_maps
    def __getattribute__(self, name):
        if name == "pins":
            return super().__getattribute__(name)
        if name in self.pins:
            return self.pins[name]
        return super().__getattribute__(name)


class SinglePort:
    """SinglePort manages a single port of the DUT, handling push and pop operations."""
    def __init__(self, dut, prefix):
        self.dut = dut
        self.port = DutPins({
            "in_valid":  getattr(dut, f"in{prefix}_valid"),
            "in_ready":  getattr(dut, f"in{prefix}_ready"),
            "in_data":   getattr(dut, f"in{prefix}_data"),
            "in_cmd":    getattr(dut, f"in{prefix}_cmd"),
            "out_valid": getattr(dut, f"out{prefix}_valid"),
            "out_ready": getattr(dut, f"out{prefix}_ready"),
            "out_data":  getattr(dut, f"out{prefix}_data"),
            "out_cmd":   getattr(dut, f"out{prefix}_cmd"),
        })
        self.ret_pop_list = []
        self.push_list = []
        self.cmd = None
        self.prefix = prefix
        self.state = 0 #  0: idle, 1: send cmd, 2: wait rsp

    def reset(self):
        self.ret_pop_list = []
        self.push_list = []
        self.cmd = None
        self.state = 0

    def is_busy(self):
        return self.state != 0

    def _push(self, value):
        if value is None:
            return False
        self.port.in_valid.value = 1
        self.port.in_cmd.value = 0
        self.port.in_data.value = value

    def _pop(self):
        self.port.in_valid.value = 1
        self.port.in_cmd.value = 1
        self.port.in_data.value = 0

    def data_handler(self, c):
        # state machine for push/pop
        if self.state == 1:
            if self.port.in_ready.value == 1:
                self.port.in_valid.value = 0
                self.port.out_ready.value = 1
                self.state = 2
                if self.port.in_cmd.value == 0:
                    # push command sent
                    pass
        elif self.state == 2:
            if self.port.out_valid.value == 1:
                self.port.out_ready.value = 0
                self.state = 0
                if self.port.out_cmd.value == 3:
                    self.ret_pop_list.append(self.port.out_data.value)
        if self.state == 0:
            if self.cmd is None and len(self.push_list) > 0:
                self.cmd = self.push_list.pop(0)
            if self.cmd is not None:
                if self.cmd == "POP":
                    self._pop()
                else:
                    self._push(self.cmd)
                self.state = 1
                self.cmd = None

    def is_idle(self):
        return self.cmd is None and len(self.push_list) == 0 and not self.is_busy()

    def stat(self):
        return f"Port {self.prefix}: push_list={self.push_list}, ret_pop_list={self.ret_pop_list}, state={self.state}, cmd={self.cmd}"


class DualPortEnv:
    """DualPortEnv manages two SinglePort instances, providing a higher-level interface for testing."""
    def __init__(self, dut):
        self.dut = dut
        self.port0 = SinglePort(dut, "0")
        self.port1 = SinglePort(dut, "1")

    def push_pop_list(self, data_list0, data_list1, max_cycles=100, ex_cycles=10):
        """Push and pop data between two ports.

        Args:
            data_list0 (_type_): data list for port 0, can contain integers (for push), None or "POP" strings.
            data_list1 (_type_): data list for port 1, can contain integers (for push), None or "POP" strings.
            max_cycles (int, optional): maximum number of cycles to run. Defaults to 100.
            ex_cycles (int, optional): number of extra cycles to run after processing. Defaults to 10.

        Returns:
            pop_list0, pop_list1: lists of popped data from port 0 and port 1 respectively.
        """
        self.reset()
        self.port0.push_list = data_list0
        self.port1.push_list = data_list1
        self.dut.xclock.ClearRisCallBacks()
        self.dut.StepRis(self.port0.data_handler)
        self.dut.StepRis(self.port1.data_handler)
        count = 0
        while (not self.port0.is_idle() or not self.port1.is_idle()) and count < max_cycles:
            self.dut.Step(1)
            count += 1
        if  (not self.port0.is_idle() or not self.port1.is_idle()) > 0:
            print("Warning: max_cycles reached, some data may not be processed.")
            print(self.port0.stat())
            print(self.port1.stat())
        if ex_cycles > 0:
            self.dut.Step(ex_cycles)
        self.dut.xclock.ClearRisCallBacks()
        return self.port0.ret_pop_list, self.port1.ret_pop_list

    def reset(self):
        self.dut.rst.value = 1
        self.dut.Step(1)
        self.dut.rst.value = 0
        self.dut.Step(1)
        self.port0.reset()
        self.port1.reset()
