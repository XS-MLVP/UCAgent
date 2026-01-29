//=========================================================
//File name    : {DUT}_io_modport.sv
//Discribution : {DUT} IO interface + modport (golden template)
//=========================================================
`ifndef {DUT}_IO_MODPORT__SV
`define {DUT}_IO_MODPORT__SV

interface {DUT}_io_if (input bit clock, input bit reset);
    // TODO: declare top IO signals (group by interface)
    // Example:
    // logic io_req_valid;
    // logic io_req_ready;
    // logic [ADDR_W-1:0] io_req_addr;

    // Coverage sampling modport (use input direction)
    modport fcov_mp (
        input clock,
        input reset
        // TODO: add IO signals for sampling
        // input io_req_valid,
        // input io_req_ready,
        // input [ADDR_W-1:0] io_req_addr
    );
endinterface : {DUT}_io_if

`endif
