//----------------------------------------------------------------------
//   Copyright 2011 Mentor Graphics Corporation
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
// This is a 16 deep 8 bit wide FIFO
// that keeps track of its size
//
module uart_tx_fifo(
  input clk,
  input rstn,
  input push,
  input pop,
  input [7:0] data_in,
  output logic fifo_empty,
  output logic fifo_full,
  output logic[4:0] count,
  output logic[7:0] data_out);

logic[3:0] ip_count;
logic[3:0] op_count;
typedef logic[7:0] fifo_t;

fifo_t data_fifo[15:0];

always @(posedge clk)
  begin
    if(rstn == 0) begin
      count <= 0;
      ip_count <= 0;
      op_count <= 0;
    end
    else begin
      case({push, pop})
        2'b01: begin
                 if(count > 0) begin
                   op_count <= op_count + 1;
                   count <= count - 1;
                 end
               end
        2'b10: begin
                 if(count <= 5'hf) begin
                   ip_count <= ip_count + 1;
                   data_fifo[ip_count] <= data_in;
                   count <= count + 1;
                 end
               end
        2'b11: begin
                 op_count <= op_count + 1;
                 ip_count <= ip_count + 1;
                 data_fifo[ip_count] <= data_in;
               end
      endcase
    end
  end

always_comb
  data_out = data_fifo[op_count];

always_comb
  fifo_empty = ~(|count);

always_comb
  fifo_full = (count == 5'b10000);

property fifo_full_prop;
  @(posedge clk)
  fifo_full |-> (count == 5'b10000);
endproperty: fifo_full_prop

property fifo_empty_prop;
  @(posedge clk)
  fifo_empty |-> (count == 0);
endproperty: fifo_empty_prop

property fifo_niether;
  @(posedge clk)
  (!fifo_full && !fifo_empty) |-> ((count > 0) && (count < 5'b10000));
endproperty: fifo_niether

TX_FIFO_FULL_CHK: assert property(fifo_full_prop);
TX_FIFO_EMPTY_CHK: assert property(fifo_empty_prop);
TX_FIFO_OK_CHK: assert property(fifo_niether);



endmodule: uart_tx_fifo
