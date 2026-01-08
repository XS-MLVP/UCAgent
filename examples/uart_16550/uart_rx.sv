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
// UART receive engine
//
module uart_rx(
  input PCLK,
  input PRESETn,
  input RXD,
  input pop_rx_fifo,
  input enable,
  input[7:0] LCR,
  output logic rx_idle,
  output[10:0] rx_fifo_out,
  output[4:0] rx_fifo_count,
  output logic push_rx_fifo,
  output rx_fifo_empty,
  output rx_fifo_full,
  output logic rx_overrun,
  output logic parity_error,
  output logic framing_error,
  output logic break_error);

typedef enum {IDLE, START, BIT0, BIT1, BIT2, BIT3, BIT4,
              BIT5, BIT6, BIT7, PARITY, STOP1, STOP2} rx_fsm_t;

rx_fsm_t rx_state;
logic[3:0] bit_counter;
logic[10:0] rx_buffer;

logic[2:0] filter;
logic filtered_rxd;

// RX_FIFO
uart_rx_fifo  rx_fifo(
                      .clk(PCLK),
                      .rstn(PRESETn),
                      .push(push_rx_fifo),
                      .pop(pop_rx_fifo),
                      .data_in(rx_buffer),
                      .fifo_empty(rx_fifo_empty),
                      .fifo_full(rx_fifo_full),
                      .count(rx_fifo_count),
                      .data_out(rx_fifo_out));

// Majority logic filter and sync stage:
always @(posedge PCLK) begin
  if(PRESETn == 0) begin
    filter <= 3'b111;
  end
  else begin
    filter[0] <= RXD;
    filter[2:1] <= filter[1:0];
  end
end

always_comb
  case(filter)
    3'b000: filtered_rxd = 0;
    3'b001: filtered_rxd = 0;
    3'b010: filtered_rxd = 0;
    3'b011: filtered_rxd = 1;
    3'b100: filtered_rxd = 0;
    3'b101: filtered_rxd = 1;
    3'b110: filtered_rxd = 1;
    3'b111: filtered_rxd = 1;
    default: filtered_rxd = 1;
  endcase

// RX FSM:
always @(posedge PCLK) begin
  if(PRESETn == 0) begin
    rx_state <= IDLE;
    bit_counter <= 0;
    push_rx_fifo <= 0;
    rx_buffer <= 0;
    rx_overrun <= 0;
    parity_error <= 0;
    framing_error <= 0;
    break_error <= 0;
    rx_idle <= 1;
  end
  else begin
    case(rx_state)
      IDLE: begin
              push_rx_fifo <= 0;
              rx_buffer <= 0;
              bit_counter <= 0;
              if(filtered_rxd == 0) begin
                rx_state <= START;
                rx_idle <= 0;
              end
              else begin
                rx_idle <= 1;
              end
            end
      START: begin
               if(enable == 1) begin
                 if((bit_counter == 4'h6) && (filtered_rxd == 0)) begin
                   rx_state <= BIT0;
                   bit_counter <= 0;
                 end
                 else begin
                   if(filtered_rxd == 1) begin
                     rx_state <= IDLE;
                   end
                   else begin
                     bit_counter <= bit_counter + 1;
                   end
                 end
               end
             end
      BIT0: begin
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 rx_state <= BIT1;
                 rx_buffer[0] <= filtered_rxd;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT1: begin
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 rx_buffer[1] <= filtered_rxd;
                 rx_state <= BIT2;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT2: begin
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 rx_state <= BIT3;
                 rx_buffer[2] <= filtered_rxd;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT3: begin
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 rx_buffer[3] <= filtered_rxd;
                 rx_state <= BIT4;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT4: begin
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 rx_buffer[4] <= filtered_rxd;
                 if(LCR[1:0] != 0) begin

                   rx_state <= BIT5;
                 end
                 else begin
                   if(LCR[3] == 1) begin
                     rx_state <= PARITY;
                   end
                   else begin
                     rx_state <= STOP1;
                   end
                 end
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT5: begin
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 rx_buffer[5] <= filtered_rxd;
                 if(LCR[1:0] > 2'b01) begin
                   rx_state <= BIT6;
                   rx_buffer[5] <= filtered_rxd;
                 end
                 else begin
                   if(LCR[3] == 1) begin
                     rx_state <= PARITY;
                   end
                   else begin
                     rx_state <= STOP1;
                   end
                 end
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT6: begin
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 rx_buffer[6] <= filtered_rxd;
                 if(LCR[1:0] == 2'b11) begin
                   rx_state <= BIT7;
                 end
                 else begin
                   if(LCR[3] == 1) begin
                     rx_state <= PARITY;
                   end
                   else begin
                     rx_state <= STOP1;
                   end
                 end
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT7: begin
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 rx_buffer[7] <= filtered_rxd;
                 if(LCR[3] == 1) begin
                   rx_state <= PARITY;
                 end
                 else begin
                   rx_state <= STOP1;
                 end
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      PARITY: begin
                if((enable == 1) && (bit_counter == 4'hf)) begin
                  rx_state <= STOP1;
                  case(LCR[5:3])
                    3'b001: rx_buffer[9] <= ~(filtered_rxd == ~(^rx_buffer));
                    3'b011: rx_buffer[9] <= ~(filtered_rxd == (^rx_buffer));
                    3'b101: rx_buffer[9] <= ~filtered_rxd; // Stick 1
                    3'b111: rx_buffer[9] <= filtered_rxd; // Stick 0
                    default: rx_buffer[9] <= 0;
                  endcase
                end
                if(enable == 1) begin
                  bit_counter <= bit_counter + 1;
                end
              end
       STOP1: begin
                parity_error <= rx_buffer[9];
                if((enable == 1) && (bit_counter == 4'hf)) begin
                  rx_state <= STOP2;
                  rx_buffer[8] <= ~filtered_rxd;
                  rx_buffer[10] <= ~(|{filtered_rxd, rx_buffer}); // Break error
                end
                if(enable == 1) begin
                  bit_counter <= bit_counter + 1;
                end
              end
       STOP2: begin
                framing_error <= rx_buffer[8];
                break_error <= rx_buffer[10];
                push_rx_fifo <= 1;
                rx_state <= IDLE;
                if(rx_fifo_count == 4'hf) begin
                  rx_overrun <= 1;
                end
                else begin
                  rx_overrun <= 0;
                end
              end
       default: rx_state <= IDLE;
     endcase
   end
end

property rx_parity;
  @(posedge PCLK)
  $rose(rx_state == STOP1) |=> parity_error == rx_buffer[9];
endproperty: rx_parity

RX_PE_CHK: assert property(rx_parity);

property rx_framing;
  @(posedge PCLK)
  $rose((rx_state == STOP1) && (enable == 1) && (bit_counter == 4'hf)) |=>
    rx_buffer[8] == ~filtered_rxd;
endproperty: rx_framing

RX_FE_CHK: assert property(rx_framing);

property rx_break;
  @(posedge PCLK)
  $rose((rx_state == STOP2) && ~(|{filtered_rxd, rx_buffer})) |=> break_error;
endproperty: rx_break

RX_BE_CHK: assert property(rx_break);

property rx_overrun_prop;
  @(posedge PCLK)
  $rose((rx_state == STOP2) && (rx_fifo_count == 4'hf)) |=> (rx_overrun == 1);
endproperty: rx_overrun_prop

RX_OE_CHK: assert property(rx_overrun_prop);

endmodule: uart_rx
