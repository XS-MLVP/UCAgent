// Checker for traffic
module traffic_checker (
  input clk,
  input rst_n,
  input car_present,
  input [4:0] long_timer_value,
  input [4:0] short_timer_value,
  input [1:0] farm_light,
  input [1:0] hwy_light,
  input [1:0] timer_state,
  input [4:0] timer_cnt,
  input farm_start,
  input hwy_start,
  input enable_f,
  input enable_h,
  input start_t,
  input sh_t,
  input lo_t
);

  // Parameters for states
  localparam GREEN  = 2'd0;
  localparam YELLOW = 2'd1;
  localparam RED    = 2'd2;

  // ---------------------------------------------------------------------------
  // 1. FG-API: Assumptions & Protocol Constraints
  // ---------------------------------------------------------------------------

  // <CK_API_RST_SYNC> (Style: Assume)
  property CK_API_RST_SYNC;
    @(posedge clk) $rose(rst_n) |-> $past(!rst_n);
  endproperty
  M_CK_API_RST_SYNC: assume property (CK_API_RST_SYNC);

  // <CK_API_TIMER_THRESHOLD> (Style: Assume)
  property CK_API_TIMER_THRESHOLD;
    @(posedge clk) short_timer_value < long_timer_value;
  endproperty
  M_CK_API_TIMER_THRESHOLD: assume property (CK_API_TIMER_THRESHOLD);

  // <CK_API_TIMER_MIN> (Style: Assume)
  property CK_API_TIMER_MIN;
    @(posedge clk) short_timer_value > 0 && long_timer_value > 0;
  endproperty
  M_CK_API_TIMER_MIN: assume property (CK_API_TIMER_MIN);

  // <CK_API_INPUT_KNOWN> (Style: Assume)
  property CK_API_INPUT_KNOWN;
    @(posedge clk) !$isunknown({car_present, long_timer_value, short_timer_value});
  endproperty
  M_CK_API_INPUT_KNOWN: assume property (CK_API_INPUT_KNOWN);

  // ---------------------------------------------------------------------------
  // 2. FG-SAFETY: Mutual Exclusion and Illegal States
  // ---------------------------------------------------------------------------

  // <CK_SAFE_MUTEX> (Style: Comb)
  property CK_SAFE_MUTEX;
    (farm_light != RED) |-> (hwy_light == RED);
  endproperty
  A_CK_SAFE_MUTEX: assert property (CK_SAFE_MUTEX);

  // <CK_SAFE_NOT_BOTH_GREEN> (Style: Comb)
  property CK_SAFE_NOT_BOTH_GREEN;
    !(farm_light == GREEN && hwy_light == GREEN);
  endproperty
  A_CK_SAFE_NOT_BOTH_GREEN: assert property (CK_SAFE_NOT_BOTH_GREEN);

  // <CK_SAFE_NOT_BOTH_YELLOW> (Style: Comb)
  property CK_SAFE_NOT_BOTH_YELLOW;
    !(farm_light == YELLOW && hwy_light == YELLOW);
  endproperty
  A_CK_SAFE_NOT_BOTH_YELLOW: assert property (CK_SAFE_NOT_BOTH_YELLOW);

  // <CK_SAFE_FARM_VAL> (Style: Comb)
  property CK_SAFE_FARM_VAL;
    farm_light <= RED;
  endproperty
  A_CK_SAFE_FARM_VAL: assert property (CK_SAFE_FARM_VAL);

  // <CK_SAFE_HWY_VAL> (Style: Comb)
  property CK_SAFE_HWY_VAL;
    hwy_light <= RED;
  endproperty
  A_CK_SAFE_HWY_VAL: assert property (CK_SAFE_HWY_VAL);

  // ---------------------------------------------------------------------------
  // 3. FG-CONTROL: State Machines, Pointers, and Flags
  // ---------------------------------------------------------------------------

  // <CK_RESET_FARM_RED> (Style: Seq)
  property CK_RESET_FARM_RED;
    @(posedge clk) !rst_n |=> farm_light == RED;
  endproperty
  A_CK_RESET_FARM_RED: assert property (CK_RESET_FARM_RED);

  // <CK_RESET_HWY_GREEN> (Style: Seq)
  property CK_RESET_HWY_GREEN;
    @(posedge clk) !rst_n |=> hwy_light == GREEN;
  endproperty
  A_CK_RESET_HWY_GREEN: assert property (CK_RESET_HWY_GREEN);

  // <CK_FARM_G_TO_Y> (Style: Seq)
  property CK_FARM_G_TO_Y;
    @(posedge clk) disable iff (!rst_n)
    (farm_light == GREEN && (car_present == 1'b0 || lo_t)) |=> farm_light == YELLOW;
  endproperty
  A_CK_FARM_G_TO_Y: assert property (CK_FARM_G_TO_Y);

  // <CK_FARM_Y_TO_R> (Style: Seq)
  property CK_FARM_Y_TO_R;
    @(posedge clk) disable iff (!rst_n)
    (farm_light == YELLOW && sh_t) |=> farm_light == RED;
  endproperty
  A_CK_FARM_Y_TO_R: assert property (CK_FARM_Y_TO_R);

  // <CK_FARM_R_TO_G> (Style: Seq)
  property CK_FARM_R_TO_G;
    @(posedge clk) disable iff (!rst_n)
    (farm_light == RED && enable_f) |=> farm_light == GREEN;
  endproperty
  A_CK_FARM_R_TO_G: assert property (CK_FARM_R_TO_G);

  // <CK_FARM_STABLE> (Style: Seq)
  property CK_FARM_STABLE;
    @(posedge clk) disable iff (!rst_n)
    (farm_light == GREEN && car_present == 1'b1 && !lo_t) ||
    (farm_light == YELLOW && !sh_t) ||
    (farm_light == RED && !enable_f) |=> $stable(farm_light);
  endproperty
  A_CK_FARM_STABLE: assert property (CK_FARM_STABLE);

  // <CK_HWY_G_TO_Y> (Style: Seq)
  property CK_HWY_G_TO_Y;
    @(posedge clk) disable iff (!rst_n)
    (hwy_light == GREEN && (car_present == 1'b1 && lo_t)) |=> hwy_light == YELLOW;
  endproperty
  A_CK_HWY_G_TO_Y: assert property (CK_HWY_G_TO_Y);

  // <CK_HWY_Y_TO_R> (Style: Seq)
  property CK_HWY_Y_TO_R;
    @(posedge clk) disable iff (!rst_n)
    (hwy_light == YELLOW && sh_t) |=> hwy_light == RED;
  endproperty
  A_CK_HWY_Y_TO_R: assert property (CK_HWY_Y_TO_R);

  // <CK_HWY_R_TO_G> (Style: Seq)
  property CK_HWY_R_TO_G;
    @(posedge clk) disable iff (!rst_n)
    (hwy_light == RED && enable_h) |=> hwy_light == GREEN;
  endproperty
  A_CK_HWY_R_TO_G: assert property (CK_HWY_R_TO_G);

  // <CK_HWY_STABLE> (Style: Seq)
  property CK_HWY_STABLE;
    @(posedge clk) disable iff (!rst_n)
    (hwy_light == GREEN && (!car_present || !lo_t)) ||
    (hwy_light == YELLOW && !sh_t) ||
    (hwy_light == RED && !enable_h) |=> $stable(hwy_light);
  endproperty
  A_CK_HWY_STABLE: assert property (CK_HWY_STABLE);

  // <CK_TIMER_RESET> (Style: Seq)
  property CK_TIMER_RESET;
    @(posedge clk) (!rst_n || start_t) |=> timer_cnt == 0;
  endproperty
  A_CK_TIMER_RESET: assert property (CK_TIMER_RESET);

  // <CK_TIMER_INC> (Style: Seq)
  property CK_TIMER_INC;
    @(posedge clk) disable iff (!rst_n || start_t)
    (timer_state != 2'd2) |=> timer_cnt == $past(timer_cnt) + 1'b1;
  endproperty
  A_CK_TIMER_INC: assert property (CK_TIMER_INC);

  // <CK_TIMER_SHORT_VALID> (Style: Comb)
  property CK_TIMER_SHORT_VALID;
    (timer_state == 2'd1 || timer_state == 2'd2) |-> sh_t;
  endproperty
  A_CK_TIMER_SHORT_VALID: assert property (CK_TIMER_SHORT_VALID);

  // <CK_TIMER_LONG_VALID> (Style: Comb)
  property CK_TIMER_LONG_VALID;
    (timer_state == 2'd2) |-> lo_t;
  endproperty
  A_CK_TIMER_LONG_VALID: assert property (CK_TIMER_LONG_VALID);

  // ---------------------------------------------------------------------------
  // 4. FG-PROGRESS: Liveness & No-Starvation
  // ---------------------------------------------------------------------------

  // <CK_LIVE_FARM_GREEN> (Style: Seq)
  property CK_LIVE_FARM_GREEN;
    @(posedge clk) disable iff (!rst_n)
    (car_present == 1'b1) |-> s_eventually (farm_light == GREEN);
  endproperty
  A_CK_LIVE_FARM_GREEN: assert property (CK_LIVE_FARM_GREEN);

  // <CK_LIVE_HWY_GREEN> (Style: Seq)
  property CK_LIVE_HWY_GREEN;
    @(posedge clk) disable iff (!rst_n)
    (car_present == 1'b0) |-> s_eventually (hwy_light == GREEN);
  endproperty
  A_CK_LIVE_HWY_GREEN: assert property (CK_LIVE_HWY_GREEN);

  // ---------------------------------------------------------------------------
  // 5. FG-COVERAGE: Reachability Covers
  // ---------------------------------------------------------------------------

  // <CK_COVER_FARM_G> (Style: Cover)
  property CK_COVER_FARM_G;
    @(posedge clk) disable iff (!rst_n)
    farm_light == GREEN;
  endproperty
  C_CK_COVER_FARM_G: cover property (CK_COVER_FARM_G);

  // <CK_COVER_FARM_Y> (Style: Cover)
  property CK_COVER_FARM_Y;
    @(posedge clk) disable iff (!rst_n)
    farm_light == YELLOW;
  endproperty
  C_CK_COVER_FARM_Y: cover property (CK_COVER_FARM_Y);

  // <CK_COVER_HWY_Y> (Style: Cover)
  property CK_COVER_HWY_Y;
    @(posedge clk) disable iff (!rst_n)
    hwy_light == YELLOW;
  endproperty
  C_CK_COVER_HWY_Y: cover property (CK_COVER_HWY_Y);

  // <CK_COVER_HWY_R> (Style: Cover)
  property CK_COVER_HWY_R;
    @(posedge clk) disable iff (!rst_n)
    hwy_light == RED;
  endproperty
  C_CK_COVER_HWY_R: cover property (CK_COVER_HWY_R);

endmodule
