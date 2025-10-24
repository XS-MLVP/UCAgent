module uart_tx(
  input PCLK,
  input PRESETn,
  input[7:0] PWDATA,
  input tx_fifo_push,
  input[7:0] LCR,
  input enable,
  output tx_fifo_empty,
  output tx_fifo_full,
  output[4:0] tx_fifo_count,
  output logic busy,
  output logic TXD);

typedef enum {IDLE, START, BIT0, BIT1, BIT2, BIT3, BIT4,
              BIT5, BIT6, BIT7, PARITY, STOP1, STOP2} tx_fsm_t;

tx_fsm_t tx_state;
logic[3:0] bit_counter;
logic[7:0] tx_buffer;
wire[7:0] tx_fifo_out;
logic pop_tx_fifo;

// TX FIFO:
uart_tx_fifo  tx_fifo(
                      .clk(PCLK),
                      .rstn(PRESETn),
                      .push(tx_fifo_push),
                      .pop(pop_tx_fifo),
                      .data_in(PWDATA),
                      .fifo_empty(tx_fifo_empty),
                      .fifo_full(tx_fifo_full),
                      .count(tx_fifo_count),
                      .data_out(tx_fifo_out));

// TX FSM:
always @(posedge PCLK) begin
  if(PRESETn == 0) begin
    tx_state <= IDLE;
    bit_counter <= 0;
    tx_buffer <= 0;
    TXD <= 1;
    pop_tx_fifo <= 0;
    busy <= 0;
  end
  else begin
    case(tx_state)
      IDLE: begin
              if((tx_fifo_empty == 0) && (enable == 1)) begin
                tx_state <= START;
                pop_tx_fifo <= 1;
                tx_buffer <= tx_fifo_out;
                busy <= 1;
                bit_counter <= 0;
              end
              else begin
                busy <= 0;
              end
            end
      START: begin
               pop_tx_fifo <= 0;
               TXD <= 0;
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 tx_state <= BIT0;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT0: begin
              TXD <= tx_buffer[0];
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 tx_state <= BIT1;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT1: begin
              TXD <= tx_buffer[1];
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 tx_state <= BIT2;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT2: begin
              TXD <= tx_buffer[2];
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 tx_state <= BIT3;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT3: begin
              TXD <= tx_buffer[3];
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 tx_state <= BIT4;
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT4: begin
              TXD <= tx_buffer[4];
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 if(LCR[1:0] != 0) begin
                   tx_state <= BIT5;
                 end
                 else begin
                   if(LCR[3] == 1) begin
                     tx_buffer[7:5] <= 0;
                     tx_state <= PARITY;
                   end
                   else begin
                     tx_state <= STOP1;
                   end
                 end
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT5: begin
              TXD <= tx_buffer[5];
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 if(LCR[1:0] > 2'b01) begin
                   tx_state <= BIT6;
                 end
                 else begin
                   if(LCR[3] == 1) begin
                     tx_buffer[7:6] <= 0;
                     tx_state <= PARITY;
                   end
                   else begin
                     tx_state <= STOP1;
                   end
                 end
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT6: begin
              TXD <= tx_buffer[6];
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 if(LCR[1:0] == 2'b11) begin
                   tx_state <= BIT7;
                 end
                 else begin
                   if(LCR[3] == 1) begin
                     tx_buffer[7] <= 0;
                     tx_state <= PARITY;
                   end
                   else begin
                     tx_state <= STOP1;
                   end
                 end
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      BIT7: begin
              TXD <= tx_buffer[7];
               if((enable == 1) && (bit_counter == 4'hf)) begin
                 if(LCR[3] == 1) begin
                   tx_state <= PARITY;
                 end
                 else begin
                   tx_state <= STOP1;
                 end
               end
               if(enable == 1) begin
                 bit_counter <= bit_counter + 1;
               end
             end
      PARITY: begin
                case(LCR[5:3])
                  3'b001: TXD <= ~(^tx_buffer);
                  3'b011: TXD <= ^tx_buffer;
                  3'b101: TXD <= 1;
                  3'b111: TXD <= 0;
                  default: TXD <= 0;
                endcase
                if((enable == 1) && (bit_counter == 4'hf)) begin
                  tx_state <= STOP1;
                end
                if(enable == 1) begin
                  bit_counter <= bit_counter + 1;
                end
              end
       STOP1: begin
                TXD <=1;
                if((enable == 1) && (bit_counter == 4'hf)) begin
                  if(LCR[2] == 1) begin
                    tx_state <= STOP2;
                  end
                  else begin
                      tx_state <= IDLE;
                  end
                end
                if(enable == 1) begin
                  bit_counter <= bit_counter + 1;
                end
              end
       STOP2: begin
                TXD <= 1;
                if((enable == 1) && (bit_counter == 4'hf)) begin
                    tx_state <= IDLE;
                end
                if(enable == 1) begin
                  bit_counter <= bit_counter + 1;
                end
              end
       default: tx_state <= IDLE;
     endcase
   end
end



endmodule: uart_tx