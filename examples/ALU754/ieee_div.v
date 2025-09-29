`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 12.02.2025 01:28:31
// Design Name: 
// Module Name: ieee_div
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


module ieee_div #(parameter N = 32, M = 23,P = N-M-1)(
  input[N-1:0] A,
  input[N-1:0] B,
  
  output reg [N-1:0] OUT, 
  output reg OverFlow,
  output reg UnderFlow
  );
  
  wire[M:0] C1;
 
  reg[P+1:0] temp_exp;
  reg[P+1:0] bias = 127;
  
  reg[P+1:0] temp_Shift;
    
    Fixed_Point_Divider D1({1'b1,A[M-1:0]},{1'b1,B[M-1:0]},C1);
    
    always@(*) begin
    
        OUT[N-1] = A[N-1]^B[N-1];//sign
        
        //exponent
        temp_Shift = -( {9'b0,(~C1[M])} + B[N-2:M] + bias +2 );
        
        temp_exp = A[N-2:M] + temp_Shift;
        
        if (temp_exp[P+1] == 0 && temp_exp[P] == 1)
          begin
             OverFlow = 1;
             UnderFlow =0;
             OUT[N-2:0] = 31'b1111111111111111111111111111111;
          end
        else if (temp_exp[P+1] == 1)
          begin
             OverFlow = 0;
             UnderFlow = 1;
             OUT[N-2:0] = 0;
          end
        else
             OverFlow = 0;
             UnderFlow = 0;
             OUT[N-2:M]= temp_exp;
             if (C1[M] == 0)
                 OUT[M-1:0] = {C1[M-2:0],1'b0};
             else
                 OUT[M-1:0] = C1[M-1:0];   
    end   
endmodule


module Fixed_Point_Divider #(parameter M = 23)(
    input [M:0] A,
    input [M:0] B,
    output reg [M:0] Q_out
);
    reg [M+1:0] temp_A;
    reg [M:0] Q = 0;
    reg [M+2:0] diff;
    integer i;

    always @(*) begin
        temp_A = {1'b0, A};
        if (B == A) begin
            Q = {1'b1, {23{1'b0}}};
        end else begin
            for (i = 24; i >= 1; i = i - 1) begin
                diff = temp_A - {1'b0, B};
                if (diff[M+1] == 1) begin
                    Q[i-1] = 0;
                end else begin
                    Q[i-1] = 1;
                    temp_A = diff;
                end
                temp_A = temp_A << 1;
            end
            Q_out = Q;
        end
    end

endmodule