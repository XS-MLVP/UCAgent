#coding=utf-8

import os
from ucagent.util.log import warning
import inspect
import ast
from collections import OrderedDict
import json


def ucagent_lib_path():
    """return ucagent lib path"""
    return os.path.abspath(__file__).split(os.sep + "ucagent" + os.sep)[0]


def repeat_count():
    """test repeat count"""
    default_v = 3
    n = os.environ.get("UC_TEST_RCOUNT", f"{default_v}").strip()
    try:
        return int(n)
    except Exception as e:
        warning(f"convert os.env['UC_TEST_RCOUNT']({n}) to Int value fail: {e}, use default 3")
        return default_v

def get_fake_dut():
    """Create a fake DUT instance with no functionality"""
    class FakeDUT:
        def InitClock(self, name: str):
            pass
        def Step(self, i:int = 1):
            pass
        def StepRis(self, callback, args=(), kwargs={}):
            pass
        def StepFal(self, callback, args=(), kwargs={}):
            pass
        def ResumeWaveformDump(self):
            pass
        def PauseWaveformDump(self):
            pass
        def WaveformPaused(self) -> int:
            pass
        def GetXPort(self):
            pass
        def GetXClock(self):
            pass
        def SetWaveform(self, filename: str):
            pass
        def GetWaveFormat(self) -> str:
            pass
        def FlushWaveform(self):
            pass
        def SetCoverage(self, filename: str):
            pass
        def GetCovMetrics(self) -> int:
            pass
        def CheckPoint(self, name: str) -> int:
            pass
        def Restore(self, name: str) -> int:
            pass
        def GetInternalSignal(self, name: str, index=-1, is_array=False, use_vpi=False):
            pass
        def GetInternalSignalList(self, prefix="", deep=99, use_vpi=False):
            pass
        def VPIInternalSignalList(self, prefix="", deep=99):
            pass
        def Finish(self):
            pass
        def RefreshComb(self):
            pass
    return FakeDUT()


def get_fake_env(dut):
    """Create a fake Env instance with no functionality"""
    class FakeEnv:
        def __init__(self, dut):
            self.dut = dut
    return FakeEnv(dut)


def is_imp_test_template():
    """Check if is implementation test template"""
    n = os.environ.get("UC_IS_IMP_TEMPLATE", "false").strip()
    return n.lower() in ["1", "true"]


def get_xpin_info(cls):
    """Get pins from DUT class"""
    tree = ast.parse(inspect.getsource(cls))
    xpin_info = OrderedDict()
    # Find __init__ method
    init_node = next((node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == '__init__'), None)
    if not init_node:
        return xpin_info
    for stmt in init_node.body:
        # Check for assignment: self.attr = ...
        if not isinstance(stmt, ast.Assign):
            continue
        for target in stmt.targets:
            if not (isinstance(target, ast.Attribute) and
                    isinstance(target.value, ast.Name) and
                    target.value.id == 'self'):
                continue
            # Check structure: xsp.XPin(xsp.XData(WIDTH, ...), ...)
            try:
                call = stmt.value
                if not (isinstance(call, ast.Call) and call.func.attr == 'XPin'):
                    continue
                xdata_arg = call.args[0]
                if not (isinstance(xdata_arg, ast.Call) and xdata_arg.func.attr == 'XData'):
                    continue
                width_node = xdata_arg.args[0]
                # Support both Python 3.8+ (Constant) and older (Num)
                width = getattr(width_node, 'value', getattr(width_node, 'n', None))
                if width is not None:
                    xpin_info[target.attr] = width
            except AttributeError:
                continue
    return xpin_info


def get_mock_dut_from(cls):
    """Create a mock DUT instance with no arguments"""
    xpin_info = get_xpin_info(cls)
    cls_Xdata = cls.__init__.__globals__['xsp'].XData
    cls_XPin = cls.__init__.__globals__['xsp'].XPin
    cls_XClock = cls.__init__.__globals__['xsp'].XClock
    cls_XPort = cls.__init__.__globals__['xsp'].XPort
    get_test_step = cls.__init__.__globals__['xsp'].TEST_get_u64_step_func
    def initialize_mock_dut(self):
        self.xclock = cls_XClock(get_test_step(), 0)
        self.xport  = cls_XPort()
        self.xclock.Add(self.xport)
        self.event = self.xclock.getEvent()
        self._pins = {}
        for pin_name, width in xpin_info.items():
            value = cls_XPin(cls_Xdata(width, cls_Xdata.InOut), self.event)
            setattr(self, pin_name, value)
            self.xport.Add(pin_name, value.xdata)
            self._pins[pin_name] = value
        self._is_initialized = True
    class MockDUT(object):
        def __init__(self):
            super().__init__()
            initialize_mock_dut(self)
        def InitClock(self, name: str):
            self.xclock.Add(self.xport[name])
        def Step(self, i:int = 1):
            self.xclock.Step(i)
        def StepRis(self, callback, args=(), kwargs={}):
            self.xclock.StepRis(callback, args, kwargs)
        def StepFal(self, callback, args=(), kwargs={}):
            self.xclock.StepFal(callback, args, kwargs)
        def __str__(self):
            ret = OrderedDict()
            for pin_name, pin in self._pins.items():
                ret[f"{pin_name}[{pin.xdata.W()}]"] = pin.xdata.value
            return json.dumps(ret, indent=4)
        def __setattr__(self, name, value):
            if not hasattr(self, "_is_initialized") or not self._is_initialized:
                return super().__setattr__(name, value)
            orin_attr = self.__dict__.get(name, None)
            if isinstance(orin_attr, cls_XPin):
                assert False, "Directly setting XPin is not allowed. Set its value attribute instead. eg: dut.a.value = 1"
            if isinstance(orin_attr, (cls_XClock, cls_XPort)):
                assert False, "Directly setting XClock or XPort is not allowed."
            assert name in self.__dict__, f"Attribute {name} not found in MockDUT."
            return super().__setattr__(name, value)
    return MockDUT()
