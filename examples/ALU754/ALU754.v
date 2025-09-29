`timescale 1ns / 1ps

module ALU754(
    input [31:0] a,
    input [31:0] b,
    input [2:0] op,
    output reg [31:0] result,
    output reg overflow,
    output reg underflow,
    output reg gt,
    output reg lt,
    output reg eq
);

    // Operation codes
    localparam ADD = 3'b000;
    localparam MUL = 3'b001;
    localparam DIV = 3'b010;
    localparam CMP = 3'b011;

    // Wires for intermediate results
    wire [31:0] add_result, mul_result, div_result;
    wire add_overflow, add_underflow;
    wire mul_overflow, mul_underflow;
    wire div_overflow, div_underflow;
    wire cmp_gt, cmp_lt, cmp_eq;

    // Instantiate the addition module
    ieee_add add_inst (
        .a(a),
        .b(b),
        .s(add_result),
        .overflow(add_overflow),
        .underflow(add_underflow)
    );

    // Instantiate the multiplication module
    ieee_mul mul_inst (
        .a(a),
        .b(b),
        .s(mul_result),
        .OVERFLOW(mul_overflow),
        .UNDERFLOW(mul_underflow)
    );

    // Instantiate the division module
    ieee_div div_inst (
        .A(a),
        .B(b),
        .OUT(div_result),
        .OverFlow(div_overflow),
        .UnderFlow(div_underflow)
    );

    // Instantiate the comparison module
    ieee_comp comp_inst (
        .a(a),
        .b(b),
        .gt(cmp_gt),
        .lt(cmp_lt),
        .eq(cmp_eq)
    );

    // ALU operation selection
    always @(*) begin
        case(op)
            ADD: begin
                result = add_result;
                overflow = add_overflow;
                underflow = add_underflow;
                gt = 1'b0;
                lt = 1'b0;
                eq = 1'b0;
            end
            MUL: begin
                result = mul_result;
                overflow = mul_overflow;
                underflow = mul_underflow;
                gt = 1'b0;
                lt = 1'b0;
                eq = 1'b0;
            end
            DIV: begin
                result = div_result;
                overflow = div_overflow;
                underflow = div_underflow;
                gt = 1'b0;
                lt = 1'b0;
                eq = 1'b0;
            end
            CMP: begin
                result = 32'b0; // No result for comparison
                overflow = 1'b0;
                underflow = 1'b0;
                gt = cmp_gt;
                lt = cmp_lt;
                eq = cmp_eq;
            end
            default: begin
                result = 32'b0;
                overflow = 1'b0;
                underflow = 1'b0;
                gt = 1'b0;
                lt = 1'b0;
                eq = 1'b0;
            end
        endcase
    end

endmodule
