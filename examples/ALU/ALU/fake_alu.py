#coding=utf-8


class XData:
    def __init__(self, width, v=0):
        self.width = width  # 数据宽度
        self.value = v

class DUTALU:
    def __init__(self):
        self.a    = XData(64, 0)
        self.b    = XData(64, 0)
        self.cin  = XData(1,  0)
        self.op   = XData(4,  0)
        self.out  = XData(64, 0)
        self.cout = XData(1,  0)
        self._cb_list = []

    def __operate(self, a: int, b: int, cin: int, op: int):
        # 保证输入为64位无符号数
        mask = (1 << 64) - 1
        a = a & mask
        b = b & mask
        cin = cin & 0x1
        out = 0
        cout = 0
        if op == 1:  # 减法
            result = a - b - cin
            out = result & mask
            cout = 1 if (a < b + cin) else 0  # 借位
        elif op == 2:  # 乘法
            result = a * b
            out = result & mask
            cout = 1 if (result >> 64) != 0 else 0  # 高64位非零为溢出
        elif op == 3:  # 按位与
            out = a & b
            cout = 0
        elif op == 4:  # 按位或
            out = a | b
            cout = 0
        elif op == 5:  # 按位异或
            out = a ^ b
            cout = 0
        elif op == 6:  # 按位非
            out = (~a) & mask
            cout = 0
        elif op == 7:  # 左移
            shift = b & 0x3F  # 只取低6位
            # Bug 2: 故意写错左移实现，比如用右移代替
            out = (a >> shift) & mask  # 故意写错， 正确为：out = (a << shift) & mask
            cout = 0
        elif op == 8:  # 右移
            shift = b & 0x3F
            out = (a >> shift) & mask
            cout = 0
        else:
            out = 0
            cout = 0
        self.out.value = out
        self.cout.value = cout

    def Step(self, cycles: int):
        self.__operate(self.a.value, self.b.value, self.cin.value, self.op.value)
        for cb in self._cb_list:
            cb(self)

    def InitClock(self, clck):
        pass

    def StepRis(self, func):
        self._cb_list.append(func)

    def Finish(self):
        self._cb_list.clear()