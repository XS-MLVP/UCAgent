module gnt2bin
#( parameter 
   NUM_PORTS = 6,
   SEL_WIDTH = ((NUM_PORTS > 1) ? $clog2(NUM_PORTS) : 1))
 (
    input clk,
    input rst,
    input [NUM_PORTS-1 : 0] in,
    output [SEL_WIDTH-1 : 0] out
 );
        reg     set;
        reg [SEL_WIDTH-1 : 0] ff1;
        integer i;

        always @(*)
        begin
            set = 1'b0;
            ff1 = 'b0;
            for (i = 0; i < NUM_PORTS; i = i + 1) begin
                if (in[i] & ~set) begin
                    set = 1'b1;
                    ff1 = i[0 +: SEL_WIDTH];
                end
            end
        end

        reg [SEL_WIDTH-1 : 0] ff1_d; 
        assign out = ff1_d;
        
        always @(posedge clk)
        if(rst)
            ff1_d <= 0;
        else 
            ff1_d <= ff1;

endmodule
