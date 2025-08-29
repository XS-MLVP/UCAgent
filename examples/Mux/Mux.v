
module Mux (
    input [3:0] in_data, // 4 个输入信号
    input [1:0] sel,     // 2 位选择信号
    output reg out       // 输出信号
);
    always @(*) begin
        case (sel)
            2'b00: out = in_data[0];
            2'b01: out = in_data[1];
            2'b10: out = in_data[2];
            default: out = in_data[0];
        endcase
    end
endmodule
