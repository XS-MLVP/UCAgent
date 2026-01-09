//=========================================================
//File name    : {DUT}_fcov.sv
//Discribution : {DUT} functional coverage (golden template)
//=========================================================
`ifndef {DUT}_FCOV__SV
`define {DUT}_FCOV__SV

module {DUT}_fcov #(
    // TODO: add parameters if needed
) (
    input  logic clock,
    input  logic reset
    // TODO: add DUT signals (IO + internal mirrors)
);

    // --------------------------------------------------------------------
    // Guidance (DCache-style):
    // - Prefer explicit covergroup per feature/interface.
    // - Gate sampling with iff(valid && ready) or stage fire.
    // - Use bins all_value[] or explicit ranges for address fields.
    // - Use cross for valid/ready or key attribute combinations.
    // - Keep HVP feature tags as line comments above coverpoints (e.g. CK-XXX).
    // --------------------------------------------------------------------

    // Example covergroup skeleton
    covergroup cg_basic @(posedge clock iff (reset == 0));
        // TODO: add coverpoints/cross and HVP feature tags
        // // CK-NORMAL-FETCH
        // cp_valid_ready: cross io_req_valid, io_req_ready;
        //
        // // CK-ADDR-SET
        // cp_addr_set: coverpoint io_req_addr[SET_W+5:6]
        //     iff (io_req_valid && io_req_ready) {
        //   bins all_value[] = {[0:255]};
        // }
        //
        // // CK-CMD-TYPE
        // cp_cmd: coverpoint io_req_cmd
        //     iff (io_req_valid && io_req_ready) {
        //   bins all_value[] = {0, 1, 2};
        // }
        //
        // // CK-CMD-X-READY
        // cp_cmd_x_ready: cross io_req_cmd, io_req_ready;
    endgroup

    cg_basic cg_basic_inst = new();

endmodule : {DUT}_fcov

`endif
