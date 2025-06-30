module DualPort (
    input clk,
    input rst,

    // Interface 0
    input in0_valid,
    output in0_ready,
    input [7:0] in0_data,
    input [1:0] in0_cmd,
    output out0_valid,
    input out0_ready,
    output [7:0] out0_data,
    output [1:0] out0_cmd,

    // Interface 1
    input in1_valid,
    output in1_ready,
    input [7:0] in1_data,
    input [1:0] in1_cmd,
    output out1_valid,
    input out1_ready,
    output [7:0] out1_data,
    output [1:0] out1_cmd
);
    // Command definitions
    localparam CMD_PUSH = 2'b00;
    localparam CMD_POP = 2'b01;
    localparam CMD_PUSH_OKAY = 2'b10;
    localparam CMD_POP_OKAY = 2'b11;

    // Stack memory and pointer
    reg [7:0] stack_mem[0:255];
    reg [7:0] sp;
    reg busy;

    reg [7:0] out0_data_reg, out1_data_reg;
    reg [1:0] out0_cmd_reg, out1_cmd_reg;
    reg out0_valid_reg, out1_valid_reg;

    assign out0_data = out0_data_reg;
    assign out0_cmd = out0_cmd_reg;
    assign out0_valid = out0_valid_reg;
    assign out1_data = out1_data_reg;
    assign out1_cmd = out1_cmd_reg;
    assign out1_valid = out1_valid_reg;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            sp <= 0;
            busy <= 0;
        end else begin
            // Interface 0 Request Handling
            if (!busy && in0_valid && in0_ready) begin
                case (in0_cmd)
                    CMD_PUSH: begin
                        busy <= 1;
                        sp <= sp + 1;
                        out0_valid_reg <= 1;
                        stack_mem[sp] <= in0_data;
                        out0_cmd_reg <= CMD_PUSH_OKAY;
                    end
                    CMD_POP: begin
                        busy <= 1;
                        sp <= sp - 1;
                        out0_valid_reg <= 1;
                        out0_data_reg <= stack_mem[sp - 1];
                        out0_cmd_reg <= CMD_POP_OKAY;
                    end
                    default: begin
                        out0_valid_reg <= 0;
                    end
                endcase
            end

            // Interface 1 Request Handling
            if (!busy && in1_valid && in1_ready) begin
                case (in1_cmd)
                    CMD_PUSH: begin
                        busy <= 1;
                        sp <= sp + 1;
                        out1_valid_reg <= 1;
                        stack_mem[sp] <= in1_data;
                        out1_cmd_reg <= CMD_PUSH_OKAY;
                    end
                    CMD_POP: begin
                        busy <= 1;
                        sp <= sp - 1;
                        out1_valid_reg <= 1;
                        out1_data_reg <= stack_mem[sp - 1];
                        out1_cmd_reg <= CMD_POP_OKAY;
                    end
                    default: begin
                        out1_valid_reg <= 0;
                    end
                endcase
            end

            // Interface 0 Response Handling
            if (busy && out0_ready) begin
                out0_valid_reg <= 0;
                busy <= 0;
            end

            // Interface 1 Response Handling
            if (busy && out1_ready) begin
                out1_valid_reg <= 0;
                busy <= 0;
            end
        end
    end

    assign in0_ready = (in0_cmd == CMD_PUSH && sp < 255|| in0_cmd == CMD_POP && sp > 0) && !busy;
    assign in1_ready = (in1_cmd == CMD_PUSH && sp < 255|| in1_cmd == CMD_POP && sp > 0) && !busy && !(in0_ready && in0_valid);

endmodule
