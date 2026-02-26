// Wrapper for traffic (main)
module traffic_wrapper (
  input clk,
  input rst_n,
  input car_present,
  input [4:0] long_timer_value,
  input [4:0] short_timer_value,
  output [1:0] farm_light,
  output [1:0] hwy_light
);

  // ---------------------------------------------------------------------------
  // DUT Instantiation
  // ---------------------------------------------------------------------------
  main dut (
    .clk(clk),
    .reset_n(rst_n),
    .car_present(car_present),
    .long_timer_value(long_timer_value),
    .short_timer_value(short_timer_value),
    .farm_light(farm_light),
    .hwy_light(hwy_light)
  );

  // ---------------------------------------------------------------------------
  // White-box Verification: Internal Signals Extraction
  // ---------------------------------------------------------------------------
  wire [1:0] timer_state = dut.timer.state;
  wire [4:0] timer_cnt   = dut.timer.timer;
  wire farm_start        = dut.farm_start_timer;
  wire hwy_start         = dut.hwy_start_timer;
  wire enable_f          = dut.enable_farm;
  wire enable_h          = dut.enable_hwy;
  wire start_t           = dut.start_timer;
  wire sh_t              = dut.short_timer;
  wire lo_t              = dut.long_timer;

  // ---------------------------------------------------------------------------
  // Checker Instantiation
  // ---------------------------------------------------------------------------
  traffic_checker checker_inst (
    .clk(clk),
    .rst_n(rst_n),
    .car_present(car_present),
    .long_timer_value(long_timer_value),
    .short_timer_value(short_timer_value),
    .farm_light(farm_light),
    .hwy_light(hwy_light),
    .timer_state(timer_state),
    .timer_cnt(timer_cnt),
    .farm_start(farm_start),
    .hwy_start(hwy_start),
    .enable_f(enable_f),
    .enable_h(enable_h),
    .start_t(start_t),
    .sh_t(sh_t),
    .lo_t(lo_t)
  );

endmodule