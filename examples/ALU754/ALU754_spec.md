## Module Name
ALU (Arithmetic Logic Unit)

## Module Overview
The ALU module is a 32-bit floating-point arithmetic and logic unit designed to perform a variety of operations based on the IEEE-754 standard for floating-point arithmetic. It supports addition, subtraction, multiplication, division, logical operations (AND, OR, XOR), bitwise shifts, complement, and conversion of floating-point numbers to integers. The module is designed for FPGA implementation and handles exceptions, overflow, and underflow conditions.

## Input Ports
- **a_operand**: 32 bits, input, IEEE-754 floating-point representation. Represents the first operand for the ALU operations.
- **b_operand**: 32 bits, input, IEEE-754 floating-point representation. Represents the second operand for the ALU operations.
- **Operation**: 4 bits, input, determines the operation to be performed by the ALU. Encodes the operation type (e.g., addition, subtraction, multiplication, etc.).

## Output Ports
- **ALU_Output**: 32 bits, output, IEEE-754 floating-point representation. Represents the result of the selected ALU operation.
- **Exception**: 1 bit, output, indicates if an exception occurred (e.g., invalid input or overflow in intermediate calculations).
- **Overflow**: 1 bit, output, indicates if the result of the operation exceeds the maximum representable value.
- **Underflow**: 1 bit, output, indicates if the result of the operation is below the minimum representable value.

## Parameters
No configurable parameters are explicitly defined in the module. The design is fixed for 32-bit IEEE-754 floating-point operations.

## Implementation Details
### Core Logic
- The ALU supports multiple operations, including:
  - Addition and subtraction using the `Addition_Subtraction` submodule.
  - Multiplication using the `Multiplication` submodule.
  - Division using the `Division` submodule.
  - Logical operations (AND, OR, XOR) and bitwise shifts (left and right).
  - Complement operation for bitwise negation.
  - Conversion of floating-point numbers to integers using the `Floating_Point_to_Integer` submodule.
- Each operation is selected based on the 4-bit `Operation` input, with specific encoding for each operation.

### Control Logic
- The `Operation` input determines which operation is performed. For each operation, specific input signals are routed to the corresponding submodule or logic block.
- The outputs of the submodules are multiplexed based on the `Operation` input to generate the final `ALU_Output`, `Exception`, `Overflow`, and `Underflow` signals.

### Data Flow
- The operands (`a_operand` and `b_operand`) are routed to the appropriate submodules based on the operation type.
- Intermediate results from submodules are combined and routed to the output ports.
- Logical and bitwise operations are performed directly within the ALU module using combinational logic.

### Submodules
1. **Addition_Subtraction**: Handles addition and subtraction of two 32-bit floating-point numbers. Includes logic for aligning exponents, handling significands, and managing exceptions.
2. **Multiplication**: Performs multiplication of two 32-bit floating-point numbers. Includes normalization, rounding, and exception handling.
3. **Division**: Implements division using an iterative approach. Includes normalization and exception handling.
4. **Floating_Point_to_Integer**: Converts a 32-bit floating-point number to an integer representation.
5. **Priority Encoder**: Used in the `Addition_Subtraction` submodule to normalize results during subtraction.

### Encoding Schemes
- The `Operation` input uses a 4-bit encoding to select the desired operation:
  - `4'd1`: Multiplication
  - `4'd2`: Division
  - `4'd3`: Subtraction
  - `4'd4`: OR
  - `4'd5`: AND
  - `4'd6`: XOR
  - `4'd7`: Left Shift
  - `4'd8`: Right Shift
  - `4'd9`: Floating-point to Integer Conversion
  - `4'd10`: Addition
  - `4'd11`: Complement

### Pointer Management
Not applicable in this design.

### Condition Checks
- Exception conditions are checked for invalid inputs (e.g., exponent values of 255 in IEEE-754 representation).
- Overflow and underflow conditions are checked based on the calculated exponent values.

### Reset and Clocking
- The design does not explicitly include clock or reset signals. It operates as a purely combinational logic block.

## Output Behavior
- **ALU_Output**: Generated based on the selected operation. For arithmetic operations, the result is in IEEE-754 format. For logical operations, the result is in standard 32-bit binary format.
- **Exception**: Set to 1 if an invalid operation or input is detected (e.g., exponent values of 255).
- **Overflow**: Set to 1 if the result exceeds the maximum representable value in IEEE-754 format.
- **Underflow**: Set to 1 if the result is below the minimum representable value in IEEE-754 format.

### Specific Conditions
- For addition and subtraction, the `Addition_Subtraction` submodule handles alignment of operands, calculation, and normalization.
- For multiplication, the `Multiplication` submodule handles normalization and rounding of the product.
- For division, the `Division` submodule uses an iterative approach to calculate the result.
- Logical operations (AND, OR, XOR) and bitwise shifts are performed directly using combinational logic.
- The complement operation negates all bits of the input operand.