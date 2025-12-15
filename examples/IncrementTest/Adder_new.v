
// A verilog 64-bit full adder with carry in and carry out

module Adder #(
    parameter WIDTH = 64
) (
    input [WIDTH-1:0] a,
    input [WIDTH-1:0] b,
    input cin,
    input signed_mode,
    output [WIDTH-1:0] sum,
    output cout
);

wire signed_mode_eff = (signed_mode === 1'b1);

wire [WIDTH:0] unsigned_result = {1'b0, a} + {1'b0, b} + {{WIDTH{1'b0}}, cin};
wire signed [WIDTH:0] signed_result =
    $signed({a[WIDTH-1], a}) + $signed({b[WIDTH-1], b}) + $signed({{WIDTH{1'b0}}, cin});

wire [WIDTH:0] result = signed_mode_eff ? $unsigned(signed_result) : unsigned_result;
assign {cout, sum} = result;

endmodule
