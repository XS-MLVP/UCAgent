`default_nettype none

// Module: ex_saturating_add8
// Purpose: Reusable unsigned 8-bit saturating adder for simple datapaths.
// Interface: The carry output reports an arithmetic overflow before saturation.
module ex_saturating_add8 (
    input  wire [7:0] a_i,
    input  wire [7:0] b_i,
    output wire [7:0] sum_o,
    output wire       carry_o
);
    wire [8:0] full_sum;

    assign full_sum = {1'b0, a_i} + {1'b0, b_i};
    assign carry_o = full_sum[8];
    assign sum_o = carry_o ? 8'hff : full_sum[7:0];
endmodule

// Module: ex_xor_reduce8
// Purpose: Reusable bitwise XOR and parity helper for the example datapath.
module ex_xor_reduce8 (
    input  wire [7:0] data_i,
    output wire [7:0] xor_o,
    output wire       parity_o
);
    assign xor_o = data_i;
    assign parity_o = ^data_i;
endmodule

`default_nettype wire
