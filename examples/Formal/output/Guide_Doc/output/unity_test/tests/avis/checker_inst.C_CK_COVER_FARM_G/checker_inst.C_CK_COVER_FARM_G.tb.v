module traffic_wrapper_tb();

// inputs to DUT
reg clk;
reg rst_n;
reg car_present;
reg [4:0] long_timer_value;
reg [4:0] short_timer_value;
wire [1:0] farm_light;
wire [1:0] hwy_light;

// DUT instance
traffic_wrapper traffic_wrapper (
      clk
    , rst_n
    , car_present
    , long_timer_value
    , short_timer_value
    , farm_light
    , hwy_light
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
    traffic_wrapper.dut.hwy_control.hwy_light <= 2'b00;
    car_present <= 1'b0;
    traffic_wrapper.dut.timer.state <= 2'b00;
    traffic_wrapper.dut.farm_control.farm_light <= 2'b10;
    rst_n <= 1'b1;
    traffic_wrapper.dut.timer.timer <= 5'b00000;
    long_timer_value <= 5'b10000;
    short_timer_value <= 5'b01110;
end

// test vectors
initial begin
    #5;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    long_timer_value <= 5'b11110;
    short_timer_value <= 5'b00001;
    #4;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    long_timer_value <= 5'b00010;
    #4;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    car_present <= 1'b1;
    #4;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    car_present <= 1'b0;
    #4;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    #4;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    long_timer_value <= 5'b01010;
    #4;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    long_timer_value <= 5'b01000;
    #4;
    clk <= 1'b0;
    #5;
    clk <= 1'b1;
    #1;
    short_timer_value <= 5'b00011;
    #4;
    clk <= 1'b0;
$finish;
end

endmodule
