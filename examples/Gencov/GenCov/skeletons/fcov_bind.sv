//=========================================================
//File name    : {DUT}_fcov_bind.sv
//Discribution : {DUT} functional coverage bind file (golden template)
//=========================================================
`ifndef {DUT}_FCOV_BIND__SV
`define {DUT}_FCOV_BIND__SV

`include "{DUT}_fcov.sv"

// Bind coverage to DUT
// TODO: fill parameter overrides and signal mapping
// Guidance (DCache-style):
// - Bind to the DUT top module name {DUT}.
// - Map IO first, then internal signals (if needed).
// - Internal signals should be hierarchical paths inside DUT.
// - Keep naming consistent with {DUT}_fcov ports.
bind {DUT} {DUT}_fcov u_{DUT}_fcov (
    .clock(clock),
    .reset(reset)
    // TODO: add port connections
    // Example:
    // .io_req_valid(io_req_valid),
    // .io_req_ready(io_req_ready),
    // .s1_fire(u_stage.s1_fire)
);

`endif
