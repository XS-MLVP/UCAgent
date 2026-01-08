//----------------------------------------------------------------------
//   Copyright 2011-2012 Mentor Graphics Corporation
//   All Rights Reserved Worldwide
//
//   Licensed under the Apache License, Version 2.0 (the
//   "License"); you may not use this file except in
//   compliance with the License.  You may obtain a copy of
//   the License at
//
//       http://www.apache.org/licenses/LICENSE-2.0
//
//   Unless required by applicable law or agreed to in
//   writing, software distributed under the License is
//   distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
//   CONDITIONS OF ANY KIND, either express or implied.  See
//   the License for the specific language governing
//   permissions and limitations under the License.
//----------------------------------------------------------------------

//
// UART Register file - Main functionality of UART
//
module uart_register_file (input PCLK,
                           input PRESETn,
                           input PSEL,
                           input PWRITE,
                           input PENABLE,
                           input[4:0] PADDR,
                           input [31:0] PWDATA,
                           output logic[31:0] PRDATA,
                           output logic PREADY,
                           output logic PSLVERR,
                           output logic[7:0] LCR,
                           // Transmitter related signals
                           output logic tx_fifo_we,
                           output logic tx_enable,
                           input[4:0] tx_fifo_count,
                           input tx_fifo_empty,
                           input tx_fifo_full,
                           input tx_busy,
                           // Receiver related signals
                           input [10:0] rx_data_out,
                           input rx_idle,
                           input rx_overrun,
                           input parity_error,
                           input framing_error,
                           input break_error,
                           input[4:0] rx_fifo_count,
                           input rx_fifo_empty,
                           input rx_fifo_full,
                           input push_rx_fifo,
                           output logic rx_enable,
                           output logic rx_fifo_re,
                           // Modem interface related signals
                           output logic loopback,
                           input ctsn,
                           input dsrn,
                           input dcdn,
                           input rin,
                           output logic rtsn,
                           output logic dtrn,
                           output logic out1n,
                           output logic out2n,
                           output logic irq,
                           output logic baud_o
                          );

// Include defines for addresses and offsets
`define DR 5'h0
`define IER 5'h1
`define IIR 5'h2
`define FCR 5'h2
`define LCR 5'h3
`define MCR 5'h4
`define LSR 5'h5
`define MSR 5'h6
`define DIV1 5'h7
`define DIV2 5'h8

// APB interface FSM states
typedef enum {IDLE, SETUP, ACCESS} APB_STATE;


// Interconnect:
//
wire [2:0] tx_state;

wire [3:0] rx_state;

logic we;
logic re;

// RX FIFO over its threshold:
logic rx_fifo_over_threshold;

// UART Registers:
logic[3:0] IER;
logic[3:0] IIR;
logic[7:0] FCR;
logic[4:0] MCR;
logic[7:0] MSR;
logic[3:0] LSR;
logic[15:0] DIVISOR;


// Baudrate counter
logic[15:0] dlc;
logic enable;
logic start_dlc;

// RX & TX enables
logic rx_enabled;
logic tx_enabled;

logic rx_overrun_int;
logic reset_overrun;

logic tx_int;
logic rx_int;
logic rx_parity_int;
logic rx_framing_int;
logic rx_break_int;
logic cts_0;
logic cts_1;
logic cts_int;
logic dcd_0;
logic dcd_1;
logic dcd_int;
logic dsr_0;
logic dsr_1;
logic dsr_int;
logic ri_0;
logic ri_1;
logic ri_int;

logic ms_int;
logic nDCD_1;
logic nCTS_1;
logic nDSR_1;
logic nRI_1;

logic ls_int;


logic fifo_error;

logic last_tx_fifo_empty;

// APB Bus interface FSM:
APB_STATE fsm_state;

always @(posedge PCLK)
  begin
    if (PRESETn == 0)
      begin
        we <= 0;
        re <= 0;
        PREADY <= 0;
        fsm_state <= IDLE;
      end
    else
      case (fsm_state)
        IDLE: begin
                we <= 0;
                re <= 0;
                PREADY <= 0;
                if (PSEL)
                  fsm_state <= SETUP;
              end
        SETUP: begin
                 re <= 0;
                 if (PSEL && PENABLE)
                   begin
                     fsm_state <= ACCESS;
                     if (PWRITE)
                       we <= 1;
                   end
                 else
                   fsm_state <= IDLE;
               end
        ACCESS: begin
                  PREADY <= 1;
                  we <= 0;
                  if(PWRITE == 0)
                    re <= 1;
                  fsm_state <= IDLE;
                end
        default: fsm_state <= IDLE;
      endcase
  end

// One clock pulse per enable
assign baud_o = ~PCLK && enable;

// Interrupt line
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      irq <= 0;
    end
    else if((re == 1) && (PADDR == `IIR)) begin
      irq <= 0;
    end
    else begin
      irq <= (IER[0] & rx_int) | (IER[1] & tx_int) | (IER[2] & ls_int) | (IER[3] & ms_int);
    end
  end

// Loopback:
assign loopback = MCR[4];

// The register implementations:

// TX Data register strobe
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      tx_fifo_we <= 0;
    end
    else begin
      if((we == 1) && (PADDR == `DR)) begin
        tx_fifo_we <= 1;
      end
      else begin
        tx_fifo_we <= 0;
      end
    end
  end

// DIVISOR - baud rate divider
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      DIVISOR <= 0;
      start_dlc <= 0;
    end
    else begin
      if(we == 1) begin
        case(PADDR)
          `DIV1: begin
                   DIVISOR[7:0] <= PWDATA[7:0];
                   start_dlc <= 1;
                 end
          `DIV2: begin
                   DIVISOR[15:8] <= PWDATA[7:0];
                 end
        endcase
      end
      else begin
        start_dlc <= 0;
      end
    end
  end

// LCR - Line control register
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      LCR <= 0;
    end
    else begin
      if((we == 1) && (PADDR == `LCR)) begin
        LCR <= PWDATA[7:0];
      end
    end
  end

// MCR - Control register
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      MCR <= 0;
    end
    else begin
      if((we == 1) && (PADDR == `MCR)) begin
        MCR <= PWDATA[4:0];
      end
    end
  end

assign out1n = MCR[2];
assign out2n = MCR[3];
assign dtrn = ~MCR[0];
assign rtsn = ~MCR[1];

// FCR - FIFO Control Register:
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      FCR <= 8'hc0;
    end
    else begin
      if((we == 1) && (PADDR == `FCR)) begin
        FCR <= PWDATA[7:0];
      end
    end
  end

// IER - Interrupt Masks:
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      IER <= 0;
    end
    else begin
      if((we == 1) && (PADDR == `IER)) begin
        IER <= PWDATA[3:0];
      end
    end
  end

//
// Read back path:
//
always_comb begin
    PSLVERR = 0;
    case(PADDR)
      `DR: PRDATA = {24'h0, rx_data_out[7:0]};
      `IER: PRDATA = {28'h0, IER};
      `IIR: PRDATA = {28'hc, IIR};
      `LCR: PRDATA = {24'h0, LCR};
      `MCR: PRDATA = {28'h0, MCR};
      `LSR: PRDATA = {24'h0, fifo_error, (tx_fifo_empty & ~tx_busy), tx_fifo_empty, LSR, ~rx_fifo_empty};
      `MSR: PRDATA = {24'h0, MSR};
      `DIV1: PRDATA = {24'h0, DIVISOR[7:0]};
      `DIV2: PRDATA = {24'h0, DIVISOR[15:8]};
      default: begin
                 PRDATA = 32'h0;
                 PSLVERR = 1;
               end
    endcase
end

// Read pulse to pop the Rx Data FIFO
always @(posedge PCLK)
begin
  if (PRESETn == 0)
    rx_fifo_re <= 0;
  else
  if (rx_fifo_re) // restore the signal to 0 after one clock cycle
    rx_fifo_re <= 0;
  else
  if ((re) && (PADDR == `DR))
    rx_fifo_re <= 1; // advance read pointer
end

//
// LSR RX error bits
//
always @(posedge PCLK)
begin
  if(PRESETn == 0) begin
    ls_int <= 0;
    LSR <= 0;
  end
  else begin
    if((PADDR == `LSR) && (re == 1)) begin
      LSR <= 0;
      ls_int <= 0;
    end
    else if(rx_fifo_re == 1) begin
      LSR <= {rx_data_out[10], rx_data_out[8], rx_data_out[9], rx_overrun};
      ls_int <= |{rx_data_out[10:8], rx_fifo_over_threshold};
    end
    else begin
      ls_int <= |LSR;
    end
  end
end




// Interrupt Identification register
always @(posedge PCLK)
begin
  if(PRESETn == 0) begin
    IIR <= 4'h1;
  end
  else begin
    if((ls_int == 1) && (IER[2] == 1)) begin
      IIR <= 4'h6;
    end
    else if((rx_int == 1) && (IER[0] == 1)) begin
      IIR <= 4'h4;
    end
    else if((tx_int == 1) && (IER[1] == 1)) begin
      IIR <= 4'h2;
    end
    else if((ms_int == 1) && (IER[3] == 1)) begin
      IIR <= 4'h0;
    end
    else begin
      IIR <= 4'h1;
    end
  end
end

//
// Baud rate generator:
//
// Frequency divider
always @(posedge PCLK)
begin
  if (PRESETn == 0)
    dlc <= 0;
  else
    if (start_dlc | ~ (|dlc))
        dlc <= DIVISOR - 1;               // preset counter
    else
      dlc <= dlc - 1;              // decrement counter
end

// Enable signal generation logic
always @(posedge PCLK)
begin
  if (PRESETn == 0)
    enable <= 1'b0;
  else
    if (|DIVISOR & ~(|dlc))     // dl>0 & dlc==0
      enable <= 1'b1;
    else
      enable <= 1'b0;
end

assign tx_enable = enable;

assign rx_enable = enable;


//
// Interrupts
//
// TX Interrupt - Triggered when TX FIFO contents below threshold
//                Cleared by a write to the interrupt clear bit
//
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      tx_int <= 0;
      last_tx_fifo_empty <= 0;
    end
    else begin
      last_tx_fifo_empty <= tx_fifo_empty;
      if((re == 1) && (PADDR == `IIR) && (PRDATA[3:0] == 4'h2)) begin
        tx_int <= 0;
      end
      else begin
        tx_int <= (tx_fifo_empty & ~last_tx_fifo_empty) | tx_int;
      end
    end
  end

//
// RX Interrupt - Triggered when RX FIFO contents above threshold
//                Cleared by a write to the interrupt clear bit
//
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      rx_int <= 0;
    end
    else begin
      rx_int <= rx_fifo_over_threshold;
    end
  end

// RX FIFO over its threshold
always_comb
  case(FCR[7:6])
    2'h0: rx_fifo_over_threshold = (rx_fifo_count >= 1);
    2'h1: rx_fifo_over_threshold = (rx_fifo_count >= 4);
    2'h2: rx_fifo_over_threshold = (rx_fifo_count >= 8);
    2'h3: rx_fifo_over_threshold = (rx_fifo_count >= 14);
    default: rx_fifo_over_threshold = 0;
  endcase

//
// Modem Status register and interrupt:
//
always @(posedge PCLK)
  begin
    if(PRESETn == 0) begin
      ms_int <= 0;
      nCTS_1 <= 0;
      nDSR_1 <= 0;
      nRI_1 <= 0;
      nDCD_1 <= 0;
      MSR[7:0] <= 0;
    end
    else begin
      if((re == 1) && (PADDR == `MSR)) begin
        ms_int <= 0;
        MSR[3:0] <= 0;
      end
      else begin
        ms_int <= ms_int | ((nCTS_1 ^ ctsn) | (nDSR_1 ^ dsrn) | (nDCD_1 ^ dcdn) | (~rin & nRI_1));
        MSR[0] <= (nCTS_1 ^ ctsn) | MSR[0];
        MSR[1] <= (nDSR_1 ^ dsrn) | MSR[1];
        MSR[2] <= (~rin & nRI_1) | MSR[2];
        MSR[3] <= (nDCD_1 ^ dcdn) | MSR[3];
        nCTS_1 <= ctsn;
        nDSR_1 <= dsrn;
        nRI_1 <= rin;
        nDCD_1 <= dcdn;
        MSR[4] <= loopback ? MCR[1]: ~ctsn;
        MSR[5] <= loopback ? MCR[0] : ~dsrn;
        MSR[6] <= loopback ? MCR[2] : ~rin;
        MSR[7] <= loopback ? MCR[3] : ~dcdn;
      end
    end
  end

endmodule: uart_register_file
