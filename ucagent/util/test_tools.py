#coding=utf-8

import os
from ucagent.util.log import warning


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
    class FakeEnv:
        def __init__(self, dut):
            self.dut = dut
    return FakeEnv(dut)


def is_imp_test_template():
    n = os.environ.get("UC_IS_IMP_TEMPLATE", "false").strip()
    return n.lower() in ["1", "true"]
