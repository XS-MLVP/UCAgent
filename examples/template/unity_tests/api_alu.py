#coding=utf-8


from fake_alu import ALU


def create_dut():
    """
    Create a new instance of the ALU (Arithmetic Logic Unit) for testing.
    
    Returns:
        ALU: An instance of the ALU class.
    """
    return ALU()


def api_alu_operation(dut, op, a, b, c=0):
    """
    Perform operations on the ALU.

    Args:
        dut (ALU): The ALU instance.
        op (int): Operation code (0 for addition, 1 for subtraction, etc.).
        a (int): First operand.
        b (int): Second operand.
        c (int): Carry-in value (0 or 1). Defaults to 0.

    Returns:
        tuple: Result of the addition and carry out flag.
    """
    dut.a.value = a
    dut.b.value = b
    dut.cin.value = c
    dut.op.value = op
    dut.Step(1)  # Simulate a clock step
    return dut.out.value, dut.cout.value
