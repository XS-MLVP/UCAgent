`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 11.02.2025 20:51:19
// Design Name: 
// Module Name: ieee_comp
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////

module ieee_comp #(
    parameter WIDTH = 32,
    parameter EXP_WIDTH = 8,
    parameter MANT_WIDTH = 23
) (
    input [WIDTH-1:0] a,  // IEEE 754 floating-point number A
    input [WIDTH-1:0] b,  // IEEE 754 floating-point number B
    output reg gt,        // A > B
    output reg lt,        // A < B
    output reg eq         // A == B
);

    // Extract sign, exponent, and mantissa for A
    wire sign_a = a[WIDTH-1];
    wire [EXP_WIDTH-1:0] exp_a = a[WIDTH-2:MANT_WIDTH];
    wire [MANT_WIDTH-1:0] mant_a = a[MANT_WIDTH-1:0];
    // Extract sign, exponent, and mantissa for B
    wire sign_b = b[WIDTH-1];
    wire [EXP_WIDTH-1:0] exp_b = b[WIDTH-2:MANT_WIDTH];
    wire [MANT_WIDTH-1:0] mant_b = b[MANT_WIDTH-1:0];
    // Convert to unsigned representation for Magnitude comparison (excluding sign bit)
    wire [WIDTH-2:0] unsigned_a = {exp_a, mant_a};
    wire [WIDTH-2:0] unsigned_b = {exp_b, mant_b};
    // Calculate the difference between unsigned_a and unsigned_b
    wire [WIDTH-1:0] diff = {1'b0, unsigned_a} - {1'b0, unsigned_b};

    // Define constants based on parameters
    localparam MAX_EXP = {EXP_WIDTH{1'b1}};
    localparam ZERO_MANT = {MANT_WIDTH{1'b0}};
    always @(*) begin
        // Default outputs
        gt = 0;
        lt = 0;
        eq = 0;
        // Handle special cases (NaN, Inf, zero)
        if ((exp_a == MAX_EXP && mant_a != ZERO_MANT) || (exp_b == MAX_EXP && mant_b != ZERO_MANT)) begin
            // At least one operand is NaN: outputs remain 0
        end 
        else if (exp_a == MAX_EXP && exp_b == MAX_EXP) begin
            // Both are Inf: compare signs
            if (sign_a == sign_b) eq = 1;
            else if (sign_a) lt = 1;
            else gt = 1;
        end 
        else if (exp_a == MAX_EXP) begin
            // A is Inf: check sign
            gt = !sign_a;
            lt = sign_a;
        end 
        else if (exp_b == MAX_EXP) begin
            // B is Inf: check sign
            gt = sign_b;
            lt = !sign_b;
        end 
        else if ((exp_a == 0 && mant_a == ZERO_MANT) && (exp_b == 0 && mant_b == ZERO_MANT)) begin
            // Both are zero
            eq = 1;
        end 
        else if (sign_a != sign_b) begin
            // Opposite signs: positive is larger
            lt = sign_a;
            gt = !sign_a;
        end 
        else begin
            // Same sign: compare magnitudes using diff
            if (diff == 0) begin
                eq = 1;
            end else begin
                // Determine magnitude order based on diff sign bit
                if (diff[WIDTH-1]) begin // unsigned_a < unsigned_b
                    if (sign_a) gt = 1; // Both negative: a is larger
                    else        lt = 1; // Both positive: a is smaller
                end 
                else begin       // unsigned_a > unsigned_b
                    if (sign_a) lt = 1; // Both negative: a is smaller
                    else        gt = 1; // Both positive: a is larger
                end
            end
        end
    end
endmodule
