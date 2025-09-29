`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 05.02.2025 10:43:21
// Design Name: 
// Module Name: ieee_mul
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


module ieee_mul(a, b, s, OVERFLOW, UNDERFLOW);
  input [31:0] a, b;
  output reg [31:0] s;
  output reg OVERFLOW, UNDERFLOW;
  reg sign;
  reg [8:0] exp;
  reg [47:0] mantisa;  // Full precision multiplication result
  reg [22:0] mantisa2; // Extracted 23-bit mantissa

  always @(*) begin
    // Compute sign bit
    sign = a[31] ^ b[31];
    // Compute exponent
    exp = a[30:23] + b[30:23] - 127;
    // Compute mantissa multiplication with implicit leading 1s
    mantisa = {1'b1, a[22:0]} * {1'b1, b[22:0]};
    // Normalize the mantissa
    if (mantisa[47] == 1) begin
      mantisa2 = mantisa[46:24]; // Take the top 23 bits
      exp = exp + 1; // Adjust exponent
    end else begin
      mantisa2 = mantisa[45:23];
    end
    // Handle overflow and underflow
    if (exp > 255) begin
      OVERFLOW = 1;
      UNDERFLOW = 0;
      s = {sign, 8'b11111111, mantisa2}; // Set exponent to max (Inf)
    end else if (exp < 0) begin
      OVERFLOW = 0;
      UNDERFLOW = 1;
      s = {sign, 8'b00000000, mantisa2}; // Set exponent to min (Zero)
    end else begin
      OVERFLOW = 0;
      UNDERFLOW = 0;
      s = {sign, exp[7:0], mantisa2}; // Normal case
    end
  end
endmodule



