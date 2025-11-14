
// A verilog 64-bit full adder with carry in and carry out

module Adder #(
    parameter WIDTH = 64
) (
    input [WIDTH-1:0] a,
    input [WIDTH-1:0] b,
    input cin,
    output [WIDTH-2:0] sum,
    output cout
);

assign {cout, sum}  = a + b + cin;

endmodule
