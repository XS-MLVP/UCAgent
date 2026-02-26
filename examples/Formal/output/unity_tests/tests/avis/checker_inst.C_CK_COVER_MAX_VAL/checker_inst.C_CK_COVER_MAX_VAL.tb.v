module Adder_wrapper_tb();

// inputs to DUT
reg clk;
reg rst_n;
reg [63:0] a;
reg [63:0] b;
reg cin;
wire [62:0] sum;
wire cout;

// DUT instance
Adder_wrapper Adder_wrapper (
      clk
    , rst_n
    , a
    , b
    , cin
    , sum
    , cout
    );

// VCD dump
initial begin
    $dumpfile("tb.vcd");
    $dumpvars;
    $dumpon;
end

// initialization
initial begin
    clk <= 1'b1;
    rst_n <= 1'b1;
    a <= 64'b1111111111111111111111111111111111111111111111111111111111111111;
    b <= 64'b1111111111111111111111111111111111111111111111111111111111111111;
    cin <= 1'b1;
end

// test vectors
initial begin
    #5;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    #4;
    clk <= 1'b0;
$finish;
end

endmodule
