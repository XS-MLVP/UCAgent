`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 05.02.2025 10:45:16
// Design Name: 
// Module Name: ieee_add
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



module ieee_add (a, b, s, overflow, underflow);
    input [31:0] a, b;
    output reg [31:0] s;
    output reg overflow, underflow;
    reg signed [8:0] exp;
    reg [23:0] mantisa_a, mantisa_b;
    reg [24:0] mantisa_out;
    reg [22:0] mantisa_last;

    always @ (*)
    begin
        if (a[30:23] >= b[30:23])
        begin
            mantisa_b = {1'b1, b[22:0]} >> (a[30:23] - b[30:23]);
            mantisa_a = {1'b1, a[22:0]};
            exp = a[30:23];
        end
        else
        begin
            mantisa_a = {1'b1, a[22:0]} >> (b[30:23] - a[30:23]);
            mantisa_b = {1'b1, b[22:0]};
            exp = b[30:23];
        end

        if (a[31] ^ b[31])
        begin
            if (mantisa_a >= mantisa_b)
            begin
                mantisa_out = mantisa_a - mantisa_b;
                s[31] = a[31];
            end
            else
            begin
                mantisa_out = mantisa_b - mantisa_a;
                s[31] = b[31];
            end
        end
        else
        begin
            mantisa_out = mantisa_a + mantisa_b;
            s[31] = a[31];
        end

        if (mantisa_out[24] == 1)
        begin
            mantisa_last = mantisa_out[23:1];
            exp = exp + 1'b1;
        end
        else if (mantisa_out[23] == 1)
        begin
            mantisa_last = mantisa_out[22:0];
        end
        else if (mantisa_out[22] == 1)
        begin
            mantisa_last = {mantisa_out[21:0], 1'b0};
            exp = exp - 1;
        end
        else if (mantisa_out[21] == 1)
        begin
            mantisa_last = {mantisa_out[20:0], 2'b00};
            exp = exp - 2;
        end
        else if (mantisa_out[20] == 1)
        begin
            mantisa_last = {mantisa_out[19:0], 3'b000};
            exp = exp - 3;
        end
        else if (mantisa_out[19] == 1)
        begin
            mantisa_last = {mantisa_out[18:0], 4'b0000};
            exp = exp - 4;
        end
        else if (mantisa_out[18] == 1)
        begin
            mantisa_last = {mantisa_out[17:0], 5'b00000};
            exp = exp - 5;
        end
        else if (mantisa_out[17] == 1)
        begin
            mantisa_last = {mantisa_out[16:0], 6'b000000};
            exp = exp - 6;
        end
        else if (mantisa_out[16] == 1)
        begin
            mantisa_last = {mantisa_out[15:0], 7'b0000000};
            exp = exp - 7;
        end
        else if (mantisa_out[15] == 1)
        begin
            mantisa_last = {mantisa_out[14:0], 8'b00000000};
            exp = exp - 8;
        end
        else if (mantisa_out[14] == 1)
        begin
            mantisa_last = {mantisa_out[13:0], 9'b000000000};
            exp = exp - 9;
        end
        else if (mantisa_out[13] == 1)
        begin
            mantisa_last = {mantisa_out[12:0], 10'b0000000000};
            exp = exp - 10;
        end
        else if (mantisa_out[12] == 1)
        begin
            mantisa_last = {mantisa_out[11:0], 11'b00000000000};
            exp = exp - 11;
        end
        else if (mantisa_out[11] == 1)
        begin
            mantisa_last = {mantisa_out[10:0], 12'b000000000000};
            exp = exp - 12;
        end
        else if (mantisa_out[10] == 1)
        begin
            mantisa_last = {mantisa_out[9:0], 13'b0000000000000};
            exp = exp - 13;
        end
        else if (mantisa_out[9] == 1)
        begin
            mantisa_last = {mantisa_out[8:0], 14'b00000000000000};
            exp = exp - 14;
        end
        else if (mantisa_out[8] == 1)
        begin
            mantisa_last = {mantisa_out[7:0], 15'b000000000000000};
            exp = exp - 15;
        end
        else if (mantisa_out[7] == 1)
        begin
            mantisa_last = {mantisa_out[6:0], 16'b0000000000000000};
            exp = exp - 16;
        end
        else if (mantisa_out[6] == 1)
        begin
            mantisa_last = {mantisa_out[5:0], 17'b00000000000000000};
            exp = exp - 17;
        end
        else if (mantisa_out[5] == 1)
        begin
            mantisa_last = {mantisa_out[4:0], 18'b000000000000000000};
            exp = exp - 18;
        end
        else
        begin
            mantisa_last = 0;
            exp = 0;
            s[31] = 0;
        end

        if (exp > 254)
        begin
            overflow = 1;
            underflow = 0;
            s[30:0] = {8'hFF, mantisa_last};
        end
        else if (exp < 0)
        begin
            overflow = 0;
            underflow = 1;
            s[30:0] = {8'b00000000, mantisa_last};
        end
        else
        begin
            overflow = 0;
            underflow = 0;
            s[30:0] = {exp[7:0], mantisa_last};
        end
    end
endmodule


