// Second RTL stub for batch checker tests
module DUT2 (
    input  wire clk,
    input  wire rst,
    input  wire [7:0] data_in,
    output wire [7:0] data_out
);
    assign data_out = data_in;
endmodule
