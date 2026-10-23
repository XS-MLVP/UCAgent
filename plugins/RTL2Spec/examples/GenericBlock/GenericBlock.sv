/* Configurable register with synchronous reset and an enable input. */
module GenericBlock #(
    parameter int WIDTH = 8
) (
    input logic clock,
    input logic reset,
    input logic enable,
    input logic [WIDTH-1:0] data_in,
    output logic [WIDTH-1:0] data_out
);
    always_ff @(posedge clock) begin
        if (reset)
            data_out <= '0;
        else if (enable)
            data_out <= data_in;
    end
endmodule
