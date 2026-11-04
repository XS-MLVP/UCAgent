// Minimal RTL stub used by static_bug checker tests.
// Lines are numbered so tests can reference specific ranges.
module DUT (
    input  wire clk,
    input  wire rst,
    input  wire start,
    output reg  done
);
    reg [1:0] state;
    always @(posedge clk) begin
        if (rst) state <= 0;
        else case (state)
            0: if (start) state <= 1;  // BUG: missing guard
            1: state <= 2;
            2: state <= 0;
        endcase
    end
    assign done = (state == 2);
endmodule
