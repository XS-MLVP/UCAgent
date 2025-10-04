// Generator : SpinalHDL v1.12.3    git head : 591e64062329e5e2e2b81f4d52422948053edb97
// Component : IntegerDivider
// Git hash  : 6221f085c30272192c9d8b62e4b9c69a87587166
// Author    : wangjunyue2001@gmail.com

`timescale 1ns/1ps

module IntegerDivider (
  input  wire          io_valid,
  input  wire          io_flush,
  input  wire          io_signed,
  input  wire          io_useRem,
  input  wire [31:0]   io_dividend,
  input  wire [31:0]   io_divisor,
  output wire          io_ready,
  output wire          io_done,
  output wire [31:0]   io_result,
  input  wire          clk,
  input  wire          reset
);
  localparam fsm_IDLE = 2'd0;
  localparam fsm_BUSY = 2'd1;
  localparam fsm_DONE = 2'd2;

  wire       [35:0]   pre_io_divX;
  wire       [35:0]   pre_io_divD;
  wire                pre_io_negX;
  wire                pre_io_negD;
  wire       [5:0]    pre_io_shiftR;
  wire       [4:0]    pre_io_cycle;
  wire                pre_io_special;
  wire                pre_io_div0;
  wire                pre_io_ALTB;
  wire                pre_io_overflow;
  wire       [35:0]   stage_io_sum;
  wire       [35:0]   stage_io_carry;
  wire       [3:0]    stage_io_qsm;
  wire       [31:0]   post_io_reminder;
  wire       [31:0]   post_io_quotient;
  wire                startDiv;
  wire                fsm_wantExit;
  reg                 fsm_wantStart;
  wire                fsm_wantKill;
  reg        [4:0]    fsm_cnt;
  wire                idle;
  reg        [1:0]    fsm_stateReg;
  reg        [1:0]    fsm_stateNext;
  wire                when_IntegerDivider_l77;
  wire                fsm_onExit_IDLE;
  wire                fsm_onExit_BUSY;
  wire                fsm_onExit_DONE;
  wire                fsm_onEntry_IDLE;
  wire                fsm_onEntry_BUSY;
  wire                fsm_onEntry_DONE;
  `ifndef SYNTHESIS
  reg [31:0] fsm_stateReg_string;
  reg [31:0] fsm_stateNext_string;
  `endif


  PreProcess pre (
    .io_valid    (startDiv          ), //i
    .io_signed   (io_signed         ), //i
    .io_dividend (io_dividend[31:0] ), //i
    .io_divisor  (io_divisor[31:0]  ), //i
    .io_divX     (pre_io_divX[35:0] ), //o
    .io_divD     (pre_io_divD[35:0] ), //o
    .io_negX     (pre_io_negX       ), //o
    .io_negD     (pre_io_negD       ), //o
    .io_shiftR   (pre_io_shiftR[5:0]), //o
    .io_cycle    (pre_io_cycle[4:0] ), //o
    .io_special  (pre_io_special    ), //o
    .io_div0     (pre_io_div0       ), //o
    .io_ALTB     (pre_io_ALTB       ), //o
    .io_overflow (pre_io_overflow   ), //o
    .clk         (clk               ), //i
    .reset       (reset             )  //i
  );
  DivStage stage (
    .io_valid (startDiv            ), //i
    .io_divX  (pre_io_divX[35:0]   ), //i
    .io_divD  (pre_io_divD[35:0]   ), //i
    .io_sum   (stage_io_sum[35:0]  ), //o
    .io_carry (stage_io_carry[35:0]), //o
    .io_qsm   (stage_io_qsm[3:0]   ), //o
    .clk      (clk                 ), //i
    .reset    (reset               )  //i
  );
  PostProcess post (
    .io_valid    (startDiv              ), //i
    .io_dividend (io_dividend[31:0]     ), //i
    .io_divD     (pre_io_divD[35:0]     ), //i
    .io_negX     (pre_io_negX           ), //i
    .io_negD     (pre_io_negD           ), //i
    .io_shiftR   (pre_io_shiftR[5:0]    ), //i
    .io_ALTB     (pre_io_ALTB           ), //i
    .io_div0     (pre_io_div0           ), //i
    .io_overflow (pre_io_overflow       ), //i
    .io_qsm      (stage_io_qsm[3:0]     ), //i
    .io_sum      (stage_io_sum[35:0]    ), //i
    .io_carry    (stage_io_carry[35:0]  ), //i
    .io_reminder (post_io_reminder[31:0]), //o
    .io_quotient (post_io_quotient[31:0]), //o
    .clk         (clk                   ), //i
    .reset       (reset                 )  //i
  );
  `ifndef SYNTHESIS
  always @(*) begin
    case(fsm_stateReg)
      fsm_IDLE : fsm_stateReg_string = "IDLE";
      fsm_BUSY : fsm_stateReg_string = "BUSY";
      fsm_DONE : fsm_stateReg_string = "DONE";
      default : fsm_stateReg_string = "????";
    endcase
  end
  always @(*) begin
    case(fsm_stateNext)
      fsm_IDLE : fsm_stateNext_string = "IDLE";
      fsm_BUSY : fsm_stateNext_string = "BUSY";
      fsm_DONE : fsm_stateNext_string = "DONE";
      default : fsm_stateNext_string = "????";
    endcase
  end
  `endif

  assign fsm_wantExit = 1'b0;
  always @(*) begin
    fsm_wantStart = 1'b0;
    case(fsm_stateReg)
      fsm_BUSY : begin
      end
      fsm_DONE : begin
      end
      default : begin
        fsm_wantStart = 1'b1;
      end
    endcase
  end

  assign fsm_wantKill = 1'b0;
  assign io_done = (fsm_stateReg == fsm_DONE);
  assign io_ready = idle;
  assign startDiv = ((idle && io_valid) && (! io_flush));
  assign io_result = (io_useRem ? post_io_reminder : post_io_quotient);
  always @(*) begin
    fsm_stateNext = fsm_stateReg;
    case(fsm_stateReg)
      fsm_BUSY : begin
        if(io_flush) begin
          fsm_stateNext = fsm_IDLE;
        end else begin
          if(when_IntegerDivider_l77) begin
            fsm_stateNext = fsm_DONE;
          end
        end
      end
      fsm_DONE : begin
        fsm_stateNext = fsm_IDLE;
      end
      default : begin
        if(startDiv) begin
          if(pre_io_special) begin
            fsm_stateNext = fsm_DONE;
          end else begin
            fsm_stateNext = fsm_BUSY;
          end
        end
      end
    endcase
    if(fsm_wantKill) begin
      fsm_stateNext = fsm_IDLE;
    end
  end

  assign when_IntegerDivider_l77 = (fsm_cnt == 5'h0);
  assign fsm_onExit_IDLE = ((fsm_stateNext != fsm_IDLE) && (fsm_stateReg == fsm_IDLE));
  assign fsm_onExit_BUSY = ((fsm_stateNext != fsm_BUSY) && (fsm_stateReg == fsm_BUSY));
  assign fsm_onExit_DONE = ((fsm_stateNext != fsm_DONE) && (fsm_stateReg == fsm_DONE));
  assign fsm_onEntry_IDLE = ((fsm_stateNext == fsm_IDLE) && (fsm_stateReg != fsm_IDLE));
  assign fsm_onEntry_BUSY = ((fsm_stateNext == fsm_BUSY) && (fsm_stateReg != fsm_BUSY));
  assign fsm_onEntry_DONE = ((fsm_stateNext == fsm_DONE) && (fsm_stateReg != fsm_DONE));
  assign idle = (fsm_stateReg == fsm_IDLE);
  always @(posedge clk or posedge reset) begin
    if(reset) begin
      fsm_stateReg <= fsm_IDLE;
    end else begin
      fsm_stateReg <= fsm_stateNext;
    end
  end

  always @(posedge clk) begin
    case(fsm_stateReg)
      fsm_BUSY : begin
        fsm_cnt <= (fsm_cnt - 5'h01);
      end
      fsm_DONE : begin
      end
      default : begin
        if(startDiv) begin
          if(!pre_io_special) begin
            fsm_cnt <= pre_io_cycle;
          end
        end
      end
    endcase
  end


endmodule

module PostProcess (
  input  wire          io_valid,
  input  wire [31:0]   io_dividend,
  input  wire [35:0]   io_divD,
  input  wire          io_negX,
  input  wire          io_negD,
  input  wire [5:0]    io_shiftR,
  input  wire          io_ALTB,
  input  wire          io_div0,
  input  wire          io_overflow,
  input  wire [3:0]    io_qsm,
  input  wire [35:0]   io_sum,
  input  wire [35:0]   io_carry,
  output wire [31:0]   io_reminder,
  output wire [31:0]   io_quotient,
  input  wire          clk,
  input  wire          reset
);

  wire       [31:0]   conv_io_q;
  wire       [31:0]   conv_io_qm;
  wire       [35:0]   _zz_reminder_csaSum;
  wire       [35:0]   _zz_reminder_csaSum_1;
  wire       [3:0]    _zz_reminder_csaSum_2;
  wire       [35:0]   _zz_reminder_fixed;
  wire       [31:0]   _zz_reminder_result;
  wire       [31:0]   _zz_quotient_fixQ;
  wire       [0:0]    _zz_quotient_fixQ_1;
  wire       [35:0]   sumR;
  wire                negR;
  wire       [35:0]   reminder_D;
  wire       [35:0]   reminder_csaSum;
  wire       [35:0]   reminder_fixSign;
  reg        [35:0]   reminder_fixed;
  wire       [35:0]   reminder_shifted;
  wire       [31:0]   reminder_result;
  wire       [31:0]   quotient_pre;
  wire                quotient_negQ;
  wire       [31:0]   quotient_fixQ;
  reg        [31:0]   quotient_result;
  wire       [31:0]   quotient_neg1;

  assign _zz_reminder_csaSum = ((io_negX ? (~ io_sum) : io_sum) + (io_negX ? (~ io_carry) : io_carry));
  assign _zz_reminder_csaSum_2 = (io_negX ? 4'b1111 : 4'b0000);
  assign _zz_reminder_csaSum_1 = {32'd0, _zz_reminder_csaSum_2};
  assign _zz_reminder_fixed = reminder_fixSign;
  assign _zz_reminder_result = reminder_shifted[31 : 0];
  assign _zz_quotient_fixQ_1 = (quotient_negQ ? 1'b1 : 1'b0);
  assign _zz_quotient_fixQ = {31'd0, _zz_quotient_fixQ_1};
  DivConverter conv (
    .io_valid (io_valid        ), //i
    .io_qsm   (io_qsm[3:0]     ), //i
    .io_q     (conv_io_q[31:0] ), //o
    .io_qm    (conv_io_qm[31:0]), //o
    .clk      (clk             ), //i
    .reset    (reset           )  //i
  );
  assign sumR = (io_sum + io_carry);
  assign negR = sumR[35];
  assign reminder_D = ((negR ? io_divD : 36'h0) <<< 2);
  assign reminder_csaSum = (_zz_reminder_csaSum + _zz_reminder_csaSum_1);
  assign reminder_fixSign = (reminder_csaSum + (io_negX ? (~ reminder_D) : reminder_D));
  assign reminder_shifted = ($signed(reminder_fixed) >>> io_shiftR);
  assign reminder_result = _zz_reminder_result;
  assign io_reminder = ((io_div0 || io_ALTB) ? io_dividend : (io_overflow ? 32'h0 : reminder_result));
  assign quotient_pre = (negR ? conv_io_qm : conv_io_q);
  assign quotient_negQ = (io_negX ^ io_negD);
  assign quotient_fixQ = ((quotient_negQ ? (~ quotient_pre) : quotient_pre) + _zz_quotient_fixQ);
  assign quotient_neg1 = {32{1'b1}};
  assign io_quotient = (io_div0 ? quotient_neg1 : (io_overflow ? io_dividend : (io_ALTB ? 32'h0 : quotient_result)));
  always @(posedge clk) begin
    reminder_fixed <= ($signed(_zz_reminder_fixed) >>> 2'b10);
    quotient_result <= quotient_fixQ;
  end


endmodule

module DivStage (
  input  wire          io_valid,
  input  wire [35:0]   io_divX,
  input  wire [35:0]   io_divD,
  output wire [35:0]   io_sum,
  output wire [35:0]   io_carry,
  output wire [3:0]    io_qsm,
  input  wire          clk,
  input  wire          reset
);

  wire       [3:0]    st_io_qsm;
  wire       [6:0]    st_io_p;
  wire       [35:0]   csa_io_cout;
  wire       [35:0]   csa_io_sum;
  wire       [3:0]    qsm;
  reg        [35:0]   pSum;
  reg        [35:0]   pCarry;
  wire       [2:0]    msBitsD;
  wire       [7:0]    msBitsS;
  wire       [7:0]    msBitsC;
  wire                carryIn;
  wire       [35:0]   divD2;
  wire       [35:0]   negD;
  wire       [35:0]   negD2;
  reg        [35:0]   addIn;

  SelectTable st (
    .io_sum   (msBitsS[7:0]  ), //i
    .io_carry (msBitsC[7:0]  ), //i
    .io_divD  (msBitsD[2:0]  ), //i
    .io_qsm   (st_io_qsm[3:0]), //o
    .io_p     (st_io_p[6:0]  )  //o
  );
  CarrySaveAdder csa (
    .io_x    (pSum[35:0]       ), //i
    .io_y    (pCarry[35:0]     ), //i
    .io_z    (addIn[35:0]      ), //i
    .io_cin  (carryIn          ), //i
    .io_cout (csa_io_cout[35:0]), //o
    .io_sum  (csa_io_sum[35:0] )  //o
  );
  assign msBitsD = io_divD[31 : 29];
  assign msBitsS = pSum[35 : 28];
  assign msBitsC = pCarry[35 : 28];
  assign io_sum = pSum;
  assign io_carry = pCarry;
  assign io_qsm = qsm;
  assign qsm = st_io_qsm;
  assign carryIn = (qsm[3] || qsm[2]);
  assign divD2 = (io_divD <<< 1);
  assign negD = (~ io_divD);
  assign negD2 = (~ divD2);
  always @(*) begin
    case(qsm)
      4'b1000 : begin
        addIn = negD2;
      end
      4'b0100 : begin
        addIn = negD;
      end
      4'b0010 : begin
        addIn = io_divD;
      end
      4'b0001 : begin
        addIn = divD2;
      end
      default : begin
        addIn = 36'h0;
      end
    endcase
  end

  always @(posedge clk) begin
    if(io_valid) begin
      pSum <= io_divX;
      pCarry <= 36'h0;
    end else begin
      pSum <= (csa_io_sum <<< 2);
      pCarry <= (csa_io_cout <<< 2);
    end
  end


endmodule

module PreProcess (
  input  wire          io_valid,
  input  wire          io_signed,
  input  wire [31:0]   io_dividend,
  input  wire [31:0]   io_divisor,
  output wire [35:0]   io_divX,
  output wire [35:0]   io_divD,
  output wire          io_negX,
  output wire          io_negD,
  output wire [5:0]    io_shiftR,
  output wire [4:0]    io_cycle,
  output wire          io_special,
  output wire          io_div0,
  output wire          io_ALTB,
  output wire          io_overflow,
  input  wire          clk,
  input  wire          reset
);

  wire       [31:0]   _zz_posA;
  wire       [0:0]    _zz_posA_1;
  wire       [31:0]   _zz_posB;
  wire       [0:0]    _zz_posB_1;
  wire       [5:0]    _zz_resBits;
  wire       [1:0]    _zz_resBits_1;
  wire       [5:0]    _zz_shift;
  wire       [1:0]    _zz_shift_1;
  wire                negA;
  wire                negB;
  wire       [31:0]   posA;
  wire       [31:0]   posB;
  wire       [32:0]   ifX;
  wire       [32:0]   ifD;
  wire       [31:0]   _zz_lzcA;
  wire       [15:0]   _zz_lzcA_1;
  wire       [7:0]    _zz_lzcA_2;
  wire       [3:0]    _zz_lzcA_3;
  wire       [1:0]    _zz_lzcA_4;
  wire       [0:0]    _zz_lzcA_5;
  wire       [0:0]    _zz_lzcA_6;
  wire       [1:0]    _zz_lzcA_7;
  wire       [1:0]    _zz_lzcA_8;
  wire       [0:0]    _zz_lzcA_9;
  wire       [0:0]    _zz_lzcA_10;
  wire       [1:0]    _zz_lzcA_11;
  wire       [2:0]    _zz_lzcA_12;
  wire       [3:0]    _zz_lzcA_13;
  wire       [1:0]    _zz_lzcA_14;
  wire       [0:0]    _zz_lzcA_15;
  wire       [0:0]    _zz_lzcA_16;
  wire       [1:0]    _zz_lzcA_17;
  wire       [1:0]    _zz_lzcA_18;
  wire       [0:0]    _zz_lzcA_19;
  wire       [0:0]    _zz_lzcA_20;
  wire       [1:0]    _zz_lzcA_21;
  wire       [2:0]    _zz_lzcA_22;
  wire       [3:0]    _zz_lzcA_23;
  wire       [7:0]    _zz_lzcA_24;
  wire       [3:0]    _zz_lzcA_25;
  wire       [1:0]    _zz_lzcA_26;
  wire       [0:0]    _zz_lzcA_27;
  wire       [0:0]    _zz_lzcA_28;
  wire       [1:0]    _zz_lzcA_29;
  wire       [1:0]    _zz_lzcA_30;
  wire       [0:0]    _zz_lzcA_31;
  wire       [0:0]    _zz_lzcA_32;
  wire       [1:0]    _zz_lzcA_33;
  wire       [2:0]    _zz_lzcA_34;
  wire       [3:0]    _zz_lzcA_35;
  wire       [1:0]    _zz_lzcA_36;
  wire       [0:0]    _zz_lzcA_37;
  wire       [0:0]    _zz_lzcA_38;
  wire       [1:0]    _zz_lzcA_39;
  wire       [1:0]    _zz_lzcA_40;
  wire       [0:0]    _zz_lzcA_41;
  wire       [0:0]    _zz_lzcA_42;
  wire       [1:0]    _zz_lzcA_43;
  wire       [2:0]    _zz_lzcA_44;
  wire       [3:0]    _zz_lzcA_45;
  wire       [4:0]    _zz_lzcA_46;
  wire       [15:0]   _zz_lzcA_47;
  wire       [7:0]    _zz_lzcA_48;
  wire       [3:0]    _zz_lzcA_49;
  wire       [1:0]    _zz_lzcA_50;
  wire       [0:0]    _zz_lzcA_51;
  wire       [0:0]    _zz_lzcA_52;
  wire       [1:0]    _zz_lzcA_53;
  wire       [1:0]    _zz_lzcA_54;
  wire       [0:0]    _zz_lzcA_55;
  wire       [0:0]    _zz_lzcA_56;
  wire       [1:0]    _zz_lzcA_57;
  wire       [2:0]    _zz_lzcA_58;
  wire       [3:0]    _zz_lzcA_59;
  wire       [1:0]    _zz_lzcA_60;
  wire       [0:0]    _zz_lzcA_61;
  wire       [0:0]    _zz_lzcA_62;
  wire       [1:0]    _zz_lzcA_63;
  wire       [1:0]    _zz_lzcA_64;
  wire       [0:0]    _zz_lzcA_65;
  wire       [0:0]    _zz_lzcA_66;
  wire       [1:0]    _zz_lzcA_67;
  wire       [2:0]    _zz_lzcA_68;
  wire       [3:0]    _zz_lzcA_69;
  wire       [7:0]    _zz_lzcA_70;
  wire       [3:0]    _zz_lzcA_71;
  wire       [1:0]    _zz_lzcA_72;
  wire       [0:0]    _zz_lzcA_73;
  wire       [0:0]    _zz_lzcA_74;
  wire       [1:0]    _zz_lzcA_75;
  wire       [1:0]    _zz_lzcA_76;
  wire       [0:0]    _zz_lzcA_77;
  wire       [0:0]    _zz_lzcA_78;
  wire       [1:0]    _zz_lzcA_79;
  wire       [2:0]    _zz_lzcA_80;
  wire       [3:0]    _zz_lzcA_81;
  wire       [1:0]    _zz_lzcA_82;
  wire       [0:0]    _zz_lzcA_83;
  wire       [0:0]    _zz_lzcA_84;
  wire       [1:0]    _zz_lzcA_85;
  wire       [1:0]    _zz_lzcA_86;
  wire       [0:0]    _zz_lzcA_87;
  wire       [0:0]    _zz_lzcA_88;
  wire       [1:0]    _zz_lzcA_89;
  wire       [2:0]    _zz_lzcA_90;
  wire       [3:0]    _zz_lzcA_91;
  wire       [4:0]    _zz_lzcA_92;
  wire       [5:0]    lzcA;
  wire       [31:0]   _zz_lzcB;
  wire       [15:0]   _zz_lzcB_1;
  wire       [7:0]    _zz_lzcB_2;
  wire       [3:0]    _zz_lzcB_3;
  wire       [1:0]    _zz_lzcB_4;
  wire       [0:0]    _zz_lzcB_5;
  wire       [0:0]    _zz_lzcB_6;
  wire       [1:0]    _zz_lzcB_7;
  wire       [1:0]    _zz_lzcB_8;
  wire       [0:0]    _zz_lzcB_9;
  wire       [0:0]    _zz_lzcB_10;
  wire       [1:0]    _zz_lzcB_11;
  wire       [2:0]    _zz_lzcB_12;
  wire       [3:0]    _zz_lzcB_13;
  wire       [1:0]    _zz_lzcB_14;
  wire       [0:0]    _zz_lzcB_15;
  wire       [0:0]    _zz_lzcB_16;
  wire       [1:0]    _zz_lzcB_17;
  wire       [1:0]    _zz_lzcB_18;
  wire       [0:0]    _zz_lzcB_19;
  wire       [0:0]    _zz_lzcB_20;
  wire       [1:0]    _zz_lzcB_21;
  wire       [2:0]    _zz_lzcB_22;
  wire       [3:0]    _zz_lzcB_23;
  wire       [7:0]    _zz_lzcB_24;
  wire       [3:0]    _zz_lzcB_25;
  wire       [1:0]    _zz_lzcB_26;
  wire       [0:0]    _zz_lzcB_27;
  wire       [0:0]    _zz_lzcB_28;
  wire       [1:0]    _zz_lzcB_29;
  wire       [1:0]    _zz_lzcB_30;
  wire       [0:0]    _zz_lzcB_31;
  wire       [0:0]    _zz_lzcB_32;
  wire       [1:0]    _zz_lzcB_33;
  wire       [2:0]    _zz_lzcB_34;
  wire       [3:0]    _zz_lzcB_35;
  wire       [1:0]    _zz_lzcB_36;
  wire       [0:0]    _zz_lzcB_37;
  wire       [0:0]    _zz_lzcB_38;
  wire       [1:0]    _zz_lzcB_39;
  wire       [1:0]    _zz_lzcB_40;
  wire       [0:0]    _zz_lzcB_41;
  wire       [0:0]    _zz_lzcB_42;
  wire       [1:0]    _zz_lzcB_43;
  wire       [2:0]    _zz_lzcB_44;
  wire       [3:0]    _zz_lzcB_45;
  wire       [4:0]    _zz_lzcB_46;
  wire       [15:0]   _zz_lzcB_47;
  wire       [7:0]    _zz_lzcB_48;
  wire       [3:0]    _zz_lzcB_49;
  wire       [1:0]    _zz_lzcB_50;
  wire       [0:0]    _zz_lzcB_51;
  wire       [0:0]    _zz_lzcB_52;
  wire       [1:0]    _zz_lzcB_53;
  wire       [1:0]    _zz_lzcB_54;
  wire       [0:0]    _zz_lzcB_55;
  wire       [0:0]    _zz_lzcB_56;
  wire       [1:0]    _zz_lzcB_57;
  wire       [2:0]    _zz_lzcB_58;
  wire       [3:0]    _zz_lzcB_59;
  wire       [1:0]    _zz_lzcB_60;
  wire       [0:0]    _zz_lzcB_61;
  wire       [0:0]    _zz_lzcB_62;
  wire       [1:0]    _zz_lzcB_63;
  wire       [1:0]    _zz_lzcB_64;
  wire       [0:0]    _zz_lzcB_65;
  wire       [0:0]    _zz_lzcB_66;
  wire       [1:0]    _zz_lzcB_67;
  wire       [2:0]    _zz_lzcB_68;
  wire       [3:0]    _zz_lzcB_69;
  wire       [7:0]    _zz_lzcB_70;
  wire       [3:0]    _zz_lzcB_71;
  wire       [1:0]    _zz_lzcB_72;
  wire       [0:0]    _zz_lzcB_73;
  wire       [0:0]    _zz_lzcB_74;
  wire       [1:0]    _zz_lzcB_75;
  wire       [1:0]    _zz_lzcB_76;
  wire       [0:0]    _zz_lzcB_77;
  wire       [0:0]    _zz_lzcB_78;
  wire       [1:0]    _zz_lzcB_79;
  wire       [2:0]    _zz_lzcB_80;
  wire       [3:0]    _zz_lzcB_81;
  wire       [1:0]    _zz_lzcB_82;
  wire       [0:0]    _zz_lzcB_83;
  wire       [0:0]    _zz_lzcB_84;
  wire       [1:0]    _zz_lzcB_85;
  wire       [1:0]    _zz_lzcB_86;
  wire       [0:0]    _zz_lzcB_87;
  wire       [0:0]    _zz_lzcB_88;
  wire       [1:0]    _zz_lzcB_89;
  wire       [2:0]    _zz_lzcB_90;
  wire       [3:0]    _zz_lzcB_91;
  wire       [4:0]    _zz_lzcB_92;
  wire       [5:0]    lzcB;
  wire       [4:0]    lzcX;
  wire       [4:0]    lzcD;
  wire       [32:0]   normX;
  wire       [32:0]   normD;
  reg        [32:0]   divD;
  wire       [4:0]    zeroDiff;
  wire                ALTB;
  wire       [5:0]    resBits;
  wire       [4:0]    cycle;
  reg                 ALTB_regNext;
  wire       [35:0]   divX;
  wire       [0:0]    rightShiftX;
  wire       [35:0]   divXShifted;
  wire       [5:0]    shift;
  reg        [5:0]    shiftR;
  wire                div0;
  wire                minX;
  wire                overflow;

  assign _zz_posA_1 = (negA ? 1'b1 : 1'b0);
  assign _zz_posA = {31'd0, _zz_posA_1};
  assign _zz_posB_1 = (negB ? 1'b1 : 1'b0);
  assign _zz_posB = {31'd0, _zz_posB_1};
  assign _zz_resBits_1 = {1'b0,1'b1};
  assign _zz_resBits = {4'd0, _zz_resBits_1};
  assign _zz_shift_1 = {1'b0,1'b1};
  assign _zz_shift = {4'd0, _zz_shift_1};
  assign negA = (io_signed && io_dividend[31]);
  assign negB = (io_signed && io_divisor[31]);
  assign posA = ((negA ? (~ io_dividend) : io_dividend) + _zz_posA);
  assign posB = ((negB ? (~ io_divisor) : io_divisor) + _zz_posB);
  assign ifX = {posA,1'b0};
  assign ifD = {posB,1'b0};
  assign _zz_lzcA = posA;
  assign _zz_lzcA_1 = _zz_lzcA[31 : 16];
  assign _zz_lzcA_2 = _zz_lzcA_1[15 : 8];
  assign _zz_lzcA_3 = _zz_lzcA_2[7 : 4];
  assign _zz_lzcA_4 = _zz_lzcA_3[3 : 2];
  assign _zz_lzcA_5 = (~ _zz_lzcA_4[1 : 1]);
  assign _zz_lzcA_6 = (~ _zz_lzcA_4[0 : 0]);
  assign _zz_lzcA_7 = {(_zz_lzcA_5[0] && _zz_lzcA_6[0]),((! _zz_lzcA_5[0]) ? 1'b0 : (! _zz_lzcA_6[0]))};
  assign _zz_lzcA_8 = _zz_lzcA_3[1 : 0];
  assign _zz_lzcA_9 = (~ _zz_lzcA_8[1 : 1]);
  assign _zz_lzcA_10 = (~ _zz_lzcA_8[0 : 0]);
  assign _zz_lzcA_11 = {(_zz_lzcA_9[0] && _zz_lzcA_10[0]),((! _zz_lzcA_9[0]) ? 1'b0 : (! _zz_lzcA_10[0]))};
  assign _zz_lzcA_12 = {(_zz_lzcA_7[1] && _zz_lzcA_11[1]),((! _zz_lzcA_7[1]) ? {1'b0,_zz_lzcA_7[0 : 0]} : {(! _zz_lzcA_11[1]),_zz_lzcA_11[0 : 0]})};
  assign _zz_lzcA_13 = _zz_lzcA_2[3 : 0];
  assign _zz_lzcA_14 = _zz_lzcA_13[3 : 2];
  assign _zz_lzcA_15 = (~ _zz_lzcA_14[1 : 1]);
  assign _zz_lzcA_16 = (~ _zz_lzcA_14[0 : 0]);
  assign _zz_lzcA_17 = {(_zz_lzcA_15[0] && _zz_lzcA_16[0]),((! _zz_lzcA_15[0]) ? 1'b0 : (! _zz_lzcA_16[0]))};
  assign _zz_lzcA_18 = _zz_lzcA_13[1 : 0];
  assign _zz_lzcA_19 = (~ _zz_lzcA_18[1 : 1]);
  assign _zz_lzcA_20 = (~ _zz_lzcA_18[0 : 0]);
  assign _zz_lzcA_21 = {(_zz_lzcA_19[0] && _zz_lzcA_20[0]),((! _zz_lzcA_19[0]) ? 1'b0 : (! _zz_lzcA_20[0]))};
  assign _zz_lzcA_22 = {(_zz_lzcA_17[1] && _zz_lzcA_21[1]),((! _zz_lzcA_17[1]) ? {1'b0,_zz_lzcA_17[0 : 0]} : {(! _zz_lzcA_21[1]),_zz_lzcA_21[0 : 0]})};
  assign _zz_lzcA_23 = {(_zz_lzcA_12[2] && _zz_lzcA_22[2]),((! _zz_lzcA_12[2]) ? {1'b0,_zz_lzcA_12[1 : 0]} : {(! _zz_lzcA_22[2]),_zz_lzcA_22[1 : 0]})};
  assign _zz_lzcA_24 = _zz_lzcA_1[7 : 0];
  assign _zz_lzcA_25 = _zz_lzcA_24[7 : 4];
  assign _zz_lzcA_26 = _zz_lzcA_25[3 : 2];
  assign _zz_lzcA_27 = (~ _zz_lzcA_26[1 : 1]);
  assign _zz_lzcA_28 = (~ _zz_lzcA_26[0 : 0]);
  assign _zz_lzcA_29 = {(_zz_lzcA_27[0] && _zz_lzcA_28[0]),((! _zz_lzcA_27[0]) ? 1'b0 : (! _zz_lzcA_28[0]))};
  assign _zz_lzcA_30 = _zz_lzcA_25[1 : 0];
  assign _zz_lzcA_31 = (~ _zz_lzcA_30[1 : 1]);
  assign _zz_lzcA_32 = (~ _zz_lzcA_30[0 : 0]);
  assign _zz_lzcA_33 = {(_zz_lzcA_31[0] && _zz_lzcA_32[0]),((! _zz_lzcA_31[0]) ? 1'b0 : (! _zz_lzcA_32[0]))};
  assign _zz_lzcA_34 = {(_zz_lzcA_29[1] && _zz_lzcA_33[1]),((! _zz_lzcA_29[1]) ? {1'b0,_zz_lzcA_29[0 : 0]} : {(! _zz_lzcA_33[1]),_zz_lzcA_33[0 : 0]})};
  assign _zz_lzcA_35 = _zz_lzcA_24[3 : 0];
  assign _zz_lzcA_36 = _zz_lzcA_35[3 : 2];
  assign _zz_lzcA_37 = (~ _zz_lzcA_36[1 : 1]);
  assign _zz_lzcA_38 = (~ _zz_lzcA_36[0 : 0]);
  assign _zz_lzcA_39 = {(_zz_lzcA_37[0] && _zz_lzcA_38[0]),((! _zz_lzcA_37[0]) ? 1'b0 : (! _zz_lzcA_38[0]))};
  assign _zz_lzcA_40 = _zz_lzcA_35[1 : 0];
  assign _zz_lzcA_41 = (~ _zz_lzcA_40[1 : 1]);
  assign _zz_lzcA_42 = (~ _zz_lzcA_40[0 : 0]);
  assign _zz_lzcA_43 = {(_zz_lzcA_41[0] && _zz_lzcA_42[0]),((! _zz_lzcA_41[0]) ? 1'b0 : (! _zz_lzcA_42[0]))};
  assign _zz_lzcA_44 = {(_zz_lzcA_39[1] && _zz_lzcA_43[1]),((! _zz_lzcA_39[1]) ? {1'b0,_zz_lzcA_39[0 : 0]} : {(! _zz_lzcA_43[1]),_zz_lzcA_43[0 : 0]})};
  assign _zz_lzcA_45 = {(_zz_lzcA_34[2] && _zz_lzcA_44[2]),((! _zz_lzcA_34[2]) ? {1'b0,_zz_lzcA_34[1 : 0]} : {(! _zz_lzcA_44[2]),_zz_lzcA_44[1 : 0]})};
  assign _zz_lzcA_46 = {(_zz_lzcA_23[3] && _zz_lzcA_45[3]),((! _zz_lzcA_23[3]) ? {1'b0,_zz_lzcA_23[2 : 0]} : {(! _zz_lzcA_45[3]),_zz_lzcA_45[2 : 0]})};
  assign _zz_lzcA_47 = _zz_lzcA[15 : 0];
  assign _zz_lzcA_48 = _zz_lzcA_47[15 : 8];
  assign _zz_lzcA_49 = _zz_lzcA_48[7 : 4];
  assign _zz_lzcA_50 = _zz_lzcA_49[3 : 2];
  assign _zz_lzcA_51 = (~ _zz_lzcA_50[1 : 1]);
  assign _zz_lzcA_52 = (~ _zz_lzcA_50[0 : 0]);
  assign _zz_lzcA_53 = {(_zz_lzcA_51[0] && _zz_lzcA_52[0]),((! _zz_lzcA_51[0]) ? 1'b0 : (! _zz_lzcA_52[0]))};
  assign _zz_lzcA_54 = _zz_lzcA_49[1 : 0];
  assign _zz_lzcA_55 = (~ _zz_lzcA_54[1 : 1]);
  assign _zz_lzcA_56 = (~ _zz_lzcA_54[0 : 0]);
  assign _zz_lzcA_57 = {(_zz_lzcA_55[0] && _zz_lzcA_56[0]),((! _zz_lzcA_55[0]) ? 1'b0 : (! _zz_lzcA_56[0]))};
  assign _zz_lzcA_58 = {(_zz_lzcA_53[1] && _zz_lzcA_57[1]),((! _zz_lzcA_53[1]) ? {1'b0,_zz_lzcA_53[0 : 0]} : {(! _zz_lzcA_57[1]),_zz_lzcA_57[0 : 0]})};
  assign _zz_lzcA_59 = _zz_lzcA_48[3 : 0];
  assign _zz_lzcA_60 = _zz_lzcA_59[3 : 2];
  assign _zz_lzcA_61 = (~ _zz_lzcA_60[1 : 1]);
  assign _zz_lzcA_62 = (~ _zz_lzcA_60[0 : 0]);
  assign _zz_lzcA_63 = {(_zz_lzcA_61[0] && _zz_lzcA_62[0]),((! _zz_lzcA_61[0]) ? 1'b0 : (! _zz_lzcA_62[0]))};
  assign _zz_lzcA_64 = _zz_lzcA_59[1 : 0];
  assign _zz_lzcA_65 = (~ _zz_lzcA_64[1 : 1]);
  assign _zz_lzcA_66 = (~ _zz_lzcA_64[0 : 0]);
  assign _zz_lzcA_67 = {(_zz_lzcA_65[0] && _zz_lzcA_66[0]),((! _zz_lzcA_65[0]) ? 1'b0 : (! _zz_lzcA_66[0]))};
  assign _zz_lzcA_68 = {(_zz_lzcA_63[1] && _zz_lzcA_67[1]),((! _zz_lzcA_63[1]) ? {1'b0,_zz_lzcA_63[0 : 0]} : {(! _zz_lzcA_67[1]),_zz_lzcA_67[0 : 0]})};
  assign _zz_lzcA_69 = {(_zz_lzcA_58[2] && _zz_lzcA_68[2]),((! _zz_lzcA_58[2]) ? {1'b0,_zz_lzcA_58[1 : 0]} : {(! _zz_lzcA_68[2]),_zz_lzcA_68[1 : 0]})};
  assign _zz_lzcA_70 = _zz_lzcA_47[7 : 0];
  assign _zz_lzcA_71 = _zz_lzcA_70[7 : 4];
  assign _zz_lzcA_72 = _zz_lzcA_71[3 : 2];
  assign _zz_lzcA_73 = (~ _zz_lzcA_72[1 : 1]);
  assign _zz_lzcA_74 = (~ _zz_lzcA_72[0 : 0]);
  assign _zz_lzcA_75 = {(_zz_lzcA_73[0] && _zz_lzcA_74[0]),((! _zz_lzcA_73[0]) ? 1'b0 : (! _zz_lzcA_74[0]))};
  assign _zz_lzcA_76 = _zz_lzcA_71[1 : 0];
  assign _zz_lzcA_77 = (~ _zz_lzcA_76[1 : 1]);
  assign _zz_lzcA_78 = (~ _zz_lzcA_76[0 : 0]);
  assign _zz_lzcA_79 = {(_zz_lzcA_77[0] && _zz_lzcA_78[0]),((! _zz_lzcA_77[0]) ? 1'b0 : (! _zz_lzcA_78[0]))};
  assign _zz_lzcA_80 = {(_zz_lzcA_75[1] && _zz_lzcA_79[1]),((! _zz_lzcA_75[1]) ? {1'b0,_zz_lzcA_75[0 : 0]} : {(! _zz_lzcA_79[1]),_zz_lzcA_79[0 : 0]})};
  assign _zz_lzcA_81 = _zz_lzcA_70[3 : 0];
  assign _zz_lzcA_82 = _zz_lzcA_81[3 : 2];
  assign _zz_lzcA_83 = (~ _zz_lzcA_82[1 : 1]);
  assign _zz_lzcA_84 = (~ _zz_lzcA_82[0 : 0]);
  assign _zz_lzcA_85 = {(_zz_lzcA_83[0] && _zz_lzcA_84[0]),((! _zz_lzcA_83[0]) ? 1'b0 : (! _zz_lzcA_84[0]))};
  assign _zz_lzcA_86 = _zz_lzcA_81[1 : 0];
  assign _zz_lzcA_87 = (~ _zz_lzcA_86[1 : 1]);
  assign _zz_lzcA_88 = (~ _zz_lzcA_86[0 : 0]);
  assign _zz_lzcA_89 = {(_zz_lzcA_87[0] && _zz_lzcA_88[0]),((! _zz_lzcA_87[0]) ? 1'b0 : (! _zz_lzcA_88[0]))};
  assign _zz_lzcA_90 = {(_zz_lzcA_85[1] && _zz_lzcA_89[1]),((! _zz_lzcA_85[1]) ? {1'b0,_zz_lzcA_85[0 : 0]} : {(! _zz_lzcA_89[1]),_zz_lzcA_89[0 : 0]})};
  assign _zz_lzcA_91 = {(_zz_lzcA_80[2] && _zz_lzcA_90[2]),((! _zz_lzcA_80[2]) ? {1'b0,_zz_lzcA_80[1 : 0]} : {(! _zz_lzcA_90[2]),_zz_lzcA_90[1 : 0]})};
  assign _zz_lzcA_92 = {(_zz_lzcA_69[3] && _zz_lzcA_91[3]),((! _zz_lzcA_69[3]) ? {1'b0,_zz_lzcA_69[2 : 0]} : {(! _zz_lzcA_91[3]),_zz_lzcA_91[2 : 0]})};
  assign lzcA = {(_zz_lzcA_46[4] && _zz_lzcA_92[4]),((! _zz_lzcA_46[4]) ? {1'b0,_zz_lzcA_46[3 : 0]} : {(! _zz_lzcA_92[4]),_zz_lzcA_92[3 : 0]})};
  assign _zz_lzcB = posB;
  assign _zz_lzcB_1 = _zz_lzcB[31 : 16];
  assign _zz_lzcB_2 = _zz_lzcB_1[15 : 8];
  assign _zz_lzcB_3 = _zz_lzcB_2[7 : 4];
  assign _zz_lzcB_4 = _zz_lzcB_3[3 : 2];
  assign _zz_lzcB_5 = (~ _zz_lzcB_4[1 : 1]);
  assign _zz_lzcB_6 = (~ _zz_lzcB_4[0 : 0]);
  assign _zz_lzcB_7 = {(_zz_lzcB_5[0] && _zz_lzcB_6[0]),((! _zz_lzcB_5[0]) ? 1'b0 : (! _zz_lzcB_6[0]))};
  assign _zz_lzcB_8 = _zz_lzcB_3[1 : 0];
  assign _zz_lzcB_9 = (~ _zz_lzcB_8[1 : 1]);
  assign _zz_lzcB_10 = (~ _zz_lzcB_8[0 : 0]);
  assign _zz_lzcB_11 = {(_zz_lzcB_9[0] && _zz_lzcB_10[0]),((! _zz_lzcB_9[0]) ? 1'b0 : (! _zz_lzcB_10[0]))};
  assign _zz_lzcB_12 = {(_zz_lzcB_7[1] && _zz_lzcB_11[1]),((! _zz_lzcB_7[1]) ? {1'b0,_zz_lzcB_7[0 : 0]} : {(! _zz_lzcB_11[1]),_zz_lzcB_11[0 : 0]})};
  assign _zz_lzcB_13 = _zz_lzcB_2[3 : 0];
  assign _zz_lzcB_14 = _zz_lzcB_13[3 : 2];
  assign _zz_lzcB_15 = (~ _zz_lzcB_14[1 : 1]);
  assign _zz_lzcB_16 = (~ _zz_lzcB_14[0 : 0]);
  assign _zz_lzcB_17 = {(_zz_lzcB_15[0] && _zz_lzcB_16[0]),((! _zz_lzcB_15[0]) ? 1'b0 : (! _zz_lzcB_16[0]))};
  assign _zz_lzcB_18 = _zz_lzcB_13[1 : 0];
  assign _zz_lzcB_19 = (~ _zz_lzcB_18[1 : 1]);
  assign _zz_lzcB_20 = (~ _zz_lzcB_18[0 : 0]);
  assign _zz_lzcB_21 = {(_zz_lzcB_19[0] && _zz_lzcB_20[0]),((! _zz_lzcB_19[0]) ? 1'b0 : (! _zz_lzcB_20[0]))};
  assign _zz_lzcB_22 = {(_zz_lzcB_17[1] && _zz_lzcB_21[1]),((! _zz_lzcB_17[1]) ? {1'b0,_zz_lzcB_17[0 : 0]} : {(! _zz_lzcB_21[1]),_zz_lzcB_21[0 : 0]})};
  assign _zz_lzcB_23 = {(_zz_lzcB_12[2] && _zz_lzcB_22[2]),((! _zz_lzcB_12[2]) ? {1'b0,_zz_lzcB_12[1 : 0]} : {(! _zz_lzcB_22[2]),_zz_lzcB_22[1 : 0]})};
  assign _zz_lzcB_24 = _zz_lzcB_1[7 : 0];
  assign _zz_lzcB_25 = _zz_lzcB_24[7 : 4];
  assign _zz_lzcB_26 = _zz_lzcB_25[3 : 2];
  assign _zz_lzcB_27 = (~ _zz_lzcB_26[1 : 1]);
  assign _zz_lzcB_28 = (~ _zz_lzcB_26[0 : 0]);
  assign _zz_lzcB_29 = {(_zz_lzcB_27[0] && _zz_lzcB_28[0]),((! _zz_lzcB_27[0]) ? 1'b0 : (! _zz_lzcB_28[0]))};
  assign _zz_lzcB_30 = _zz_lzcB_25[1 : 0];
  assign _zz_lzcB_31 = (~ _zz_lzcB_30[1 : 1]);
  assign _zz_lzcB_32 = (~ _zz_lzcB_30[0 : 0]);
  assign _zz_lzcB_33 = {(_zz_lzcB_31[0] && _zz_lzcB_32[0]),((! _zz_lzcB_31[0]) ? 1'b0 : (! _zz_lzcB_32[0]))};
  assign _zz_lzcB_34 = {(_zz_lzcB_29[1] && _zz_lzcB_33[1]),((! _zz_lzcB_29[1]) ? {1'b0,_zz_lzcB_29[0 : 0]} : {(! _zz_lzcB_33[1]),_zz_lzcB_33[0 : 0]})};
  assign _zz_lzcB_35 = _zz_lzcB_24[3 : 0];
  assign _zz_lzcB_36 = _zz_lzcB_35[3 : 2];
  assign _zz_lzcB_37 = (~ _zz_lzcB_36[1 : 1]);
  assign _zz_lzcB_38 = (~ _zz_lzcB_36[0 : 0]);
  assign _zz_lzcB_39 = {(_zz_lzcB_37[0] && _zz_lzcB_38[0]),((! _zz_lzcB_37[0]) ? 1'b0 : (! _zz_lzcB_38[0]))};
  assign _zz_lzcB_40 = _zz_lzcB_35[1 : 0];
  assign _zz_lzcB_41 = (~ _zz_lzcB_40[1 : 1]);
  assign _zz_lzcB_42 = (~ _zz_lzcB_40[0 : 0]);
  assign _zz_lzcB_43 = {(_zz_lzcB_41[0] && _zz_lzcB_42[0]),((! _zz_lzcB_41[0]) ? 1'b0 : (! _zz_lzcB_42[0]))};
  assign _zz_lzcB_44 = {(_zz_lzcB_39[1] && _zz_lzcB_43[1]),((! _zz_lzcB_39[1]) ? {1'b0,_zz_lzcB_39[0 : 0]} : {(! _zz_lzcB_43[1]),_zz_lzcB_43[0 : 0]})};
  assign _zz_lzcB_45 = {(_zz_lzcB_34[2] && _zz_lzcB_44[2]),((! _zz_lzcB_34[2]) ? {1'b0,_zz_lzcB_34[1 : 0]} : {(! _zz_lzcB_44[2]),_zz_lzcB_44[1 : 0]})};
  assign _zz_lzcB_46 = {(_zz_lzcB_23[3] && _zz_lzcB_45[3]),((! _zz_lzcB_23[3]) ? {1'b0,_zz_lzcB_23[2 : 0]} : {(! _zz_lzcB_45[3]),_zz_lzcB_45[2 : 0]})};
  assign _zz_lzcB_47 = _zz_lzcB[15 : 0];
  assign _zz_lzcB_48 = _zz_lzcB_47[15 : 8];
  assign _zz_lzcB_49 = _zz_lzcB_48[7 : 4];
  assign _zz_lzcB_50 = _zz_lzcB_49[3 : 2];
  assign _zz_lzcB_51 = (~ _zz_lzcB_50[1 : 1]);
  assign _zz_lzcB_52 = (~ _zz_lzcB_50[0 : 0]);
  assign _zz_lzcB_53 = {(_zz_lzcB_51[0] && _zz_lzcB_52[0]),((! _zz_lzcB_51[0]) ? 1'b0 : (! _zz_lzcB_52[0]))};
  assign _zz_lzcB_54 = _zz_lzcB_49[1 : 0];
  assign _zz_lzcB_55 = (~ _zz_lzcB_54[1 : 1]);
  assign _zz_lzcB_56 = (~ _zz_lzcB_54[0 : 0]);
  assign _zz_lzcB_57 = {(_zz_lzcB_55[0] && _zz_lzcB_56[0]),((! _zz_lzcB_55[0]) ? 1'b0 : (! _zz_lzcB_56[0]))};
  assign _zz_lzcB_58 = {(_zz_lzcB_53[1] && _zz_lzcB_57[1]),((! _zz_lzcB_53[1]) ? {1'b0,_zz_lzcB_53[0 : 0]} : {(! _zz_lzcB_57[1]),_zz_lzcB_57[0 : 0]})};
  assign _zz_lzcB_59 = _zz_lzcB_48[3 : 0];
  assign _zz_lzcB_60 = _zz_lzcB_59[3 : 2];
  assign _zz_lzcB_61 = (~ _zz_lzcB_60[1 : 1]);
  assign _zz_lzcB_62 = (~ _zz_lzcB_60[0 : 0]);
  assign _zz_lzcB_63 = {(_zz_lzcB_61[0] && _zz_lzcB_62[0]),((! _zz_lzcB_61[0]) ? 1'b0 : (! _zz_lzcB_62[0]))};
  assign _zz_lzcB_64 = _zz_lzcB_59[1 : 0];
  assign _zz_lzcB_65 = (~ _zz_lzcB_64[1 : 1]);
  assign _zz_lzcB_66 = (~ _zz_lzcB_64[0 : 0]);
  assign _zz_lzcB_67 = {(_zz_lzcB_65[0] && _zz_lzcB_66[0]),((! _zz_lzcB_65[0]) ? 1'b0 : (! _zz_lzcB_66[0]))};
  assign _zz_lzcB_68 = {(_zz_lzcB_63[1] && _zz_lzcB_67[1]),((! _zz_lzcB_63[1]) ? {1'b0,_zz_lzcB_63[0 : 0]} : {(! _zz_lzcB_67[1]),_zz_lzcB_67[0 : 0]})};
  assign _zz_lzcB_69 = {(_zz_lzcB_58[2] && _zz_lzcB_68[2]),((! _zz_lzcB_58[2]) ? {1'b0,_zz_lzcB_58[1 : 0]} : {(! _zz_lzcB_68[2]),_zz_lzcB_68[1 : 0]})};
  assign _zz_lzcB_70 = _zz_lzcB_47[7 : 0];
  assign _zz_lzcB_71 = _zz_lzcB_70[7 : 4];
  assign _zz_lzcB_72 = _zz_lzcB_71[3 : 2];
  assign _zz_lzcB_73 = (~ _zz_lzcB_72[1 : 1]);
  assign _zz_lzcB_74 = (~ _zz_lzcB_72[0 : 0]);
  assign _zz_lzcB_75 = {(_zz_lzcB_73[0] && _zz_lzcB_74[0]),((! _zz_lzcB_73[0]) ? 1'b0 : (! _zz_lzcB_74[0]))};
  assign _zz_lzcB_76 = _zz_lzcB_71[1 : 0];
  assign _zz_lzcB_77 = (~ _zz_lzcB_76[1 : 1]);
  assign _zz_lzcB_78 = (~ _zz_lzcB_76[0 : 0]);
  assign _zz_lzcB_79 = {(_zz_lzcB_77[0] && _zz_lzcB_78[0]),((! _zz_lzcB_77[0]) ? 1'b0 : (! _zz_lzcB_78[0]))};
  assign _zz_lzcB_80 = {(_zz_lzcB_75[1] && _zz_lzcB_79[1]),((! _zz_lzcB_75[1]) ? {1'b0,_zz_lzcB_75[0 : 0]} : {(! _zz_lzcB_79[1]),_zz_lzcB_79[0 : 0]})};
  assign _zz_lzcB_81 = _zz_lzcB_70[3 : 0];
  assign _zz_lzcB_82 = _zz_lzcB_81[3 : 2];
  assign _zz_lzcB_83 = (~ _zz_lzcB_82[1 : 1]);
  assign _zz_lzcB_84 = (~ _zz_lzcB_82[0 : 0]);
  assign _zz_lzcB_85 = {(_zz_lzcB_83[0] && _zz_lzcB_84[0]),((! _zz_lzcB_83[0]) ? 1'b0 : (! _zz_lzcB_84[0]))};
  assign _zz_lzcB_86 = _zz_lzcB_81[1 : 0];
  assign _zz_lzcB_87 = (~ _zz_lzcB_86[1 : 1]);
  assign _zz_lzcB_88 = (~ _zz_lzcB_86[0 : 0]);
  assign _zz_lzcB_89 = {(_zz_lzcB_87[0] && _zz_lzcB_88[0]),((! _zz_lzcB_87[0]) ? 1'b0 : (! _zz_lzcB_88[0]))};
  assign _zz_lzcB_90 = {(_zz_lzcB_85[1] && _zz_lzcB_89[1]),((! _zz_lzcB_85[1]) ? {1'b0,_zz_lzcB_85[0 : 0]} : {(! _zz_lzcB_89[1]),_zz_lzcB_89[0 : 0]})};
  assign _zz_lzcB_91 = {(_zz_lzcB_80[2] && _zz_lzcB_90[2]),((! _zz_lzcB_80[2]) ? {1'b0,_zz_lzcB_80[1 : 0]} : {(! _zz_lzcB_90[2]),_zz_lzcB_90[1 : 0]})};
  assign _zz_lzcB_92 = {(_zz_lzcB_69[3] && _zz_lzcB_91[3]),((! _zz_lzcB_69[3]) ? {1'b0,_zz_lzcB_69[2 : 0]} : {(! _zz_lzcB_91[3]),_zz_lzcB_91[2 : 0]})};
  assign lzcB = {(_zz_lzcB_46[4] && _zz_lzcB_92[4]),((! _zz_lzcB_46[4]) ? {1'b0,_zz_lzcB_46[3 : 0]} : {(! _zz_lzcB_92[4]),_zz_lzcB_92[3 : 0]})};
  assign lzcX = lzcA[4 : 0];
  assign lzcD = lzcB[4 : 0];
  assign normX = (ifX <<< lzcX);
  assign normD = (ifD <<< lzcD);
  assign io_divD = {3'd0, divD};
  assign io_negD = negB;
  assign zeroDiff = (lzcD - lzcX);
  assign ALTB = (lzcD < lzcX);
  assign resBits = (_zz_resBits + {1'b0,(ALTB ? 5'h0 : zeroDiff)});
  assign cycle = (resBits[5 : 1] + 5'h01);
  assign io_cycle = cycle;
  assign io_ALTB = ALTB_regNext;
  assign divX = {3'b000,normX};
  assign rightShiftX = (! resBits[0]);
  assign divXShifted = (divX >>> rightShiftX);
  assign io_divX = divXShifted;
  assign io_negX = negA;
  assign shift = ({1'b0,lzcD} + _zz_shift);
  assign io_shiftR = shiftR;
  assign div0 = (! (|io_divisor));
  assign io_div0 = div0;
  assign minX = (io_dividend[31] && (! (|io_dividend[30 : 0])));
  assign overflow = ((io_signed && minX) && (&io_divisor));
  assign io_overflow = overflow;
  assign io_special = ((ALTB || div0) || overflow);
  always @(posedge clk) begin
    if(io_valid) begin
      divD <= normD;
    end
    ALTB_regNext <= ALTB;
    if(io_valid) begin
      shiftR <= shift;
    end
  end


endmodule

module DivConverter (
  input  wire          io_valid,
  input  wire [3:0]    io_qsm,
  output wire [31:0]   io_q,
  output wire [31:0]   io_qm,
  input  wire          clk,
  input  wire          reset
);

  wire                s;
  wire                m1;
  wire                m0;
  wire       [1:0]    a;
  wire       [1:0]    b;
  wire                shiftA;
  wire                shiftB;
  wire                loadA;
  wire                loadB;
  reg        [31:0]   A_1;
  reg        [31:0]   B_1;
  wire       [29:0]   lowA;
  wire       [29:0]   lowB;
  wire       [31:0]   fullA;
  wire       [31:0]   fullB;
  wire       [31:0]   nextA;
  wire       [31:0]   nextB;

  assign s = (io_qsm[1] || io_qsm[0]);
  assign m1 = (io_qsm[3] || io_qsm[0]);
  assign m0 = (io_qsm[2] || io_qsm[1]);
  assign a = {(s || m1),m0};
  assign b = {((! m1) && ((! m0) || s)),(! m0)};
  assign shiftA = (! s);
  assign shiftB = (s || ((! m0) && (! m1)));
  assign loadA = (! shiftA);
  assign loadB = (! shiftB);
  assign lowA = A_1[29 : 0];
  assign lowB = B_1[29 : 0];
  assign fullA = {(loadA ? lowB : lowA),a};
  assign fullB = {(loadB ? lowA : lowB),b};
  assign nextA = fullA[31 : 0];
  assign nextB = fullB[31 : 0];
  assign io_q = A_1;
  assign io_qm = B_1;
  always @(posedge clk) begin
    if(io_valid) begin
      A_1 <= 32'h0;
      B_1 <= 32'h0;
    end else begin
      A_1 <= nextA;
      B_1 <= nextB;
    end
  end


endmodule

module CarrySaveAdder (
  input  wire [35:0]   io_x,
  input  wire [35:0]   io_y,
  input  wire [35:0]   io_z,
  input  wire          io_cin,
  output wire [35:0]   io_cout,
  output wire [35:0]   io_sum
);

  wire       [34:0]   low_x;
  wire       [34:0]   low_y;
  wire       [34:0]   low_z;

  assign low_x = io_x[34 : 0];
  assign low_y = io_y[34 : 0];
  assign low_z = io_z[34 : 0];
  assign io_sum = ((io_x ^ io_y) ^ io_z);
  assign io_cout = {((low_x & (low_y | low_z)) | (low_y & low_z)),io_cin};

endmodule

module SelectTable (
  input  wire [7:0]    io_sum,
  input  wire [7:0]    io_carry,
  input  wire [2:0]    io_divD,
  output reg  [3:0]    io_qsm,
  output wire [6:0]    io_p
);

  wire       [7:0]    sum;
  wire       [6:0]    p;
  reg        [7:0]    m_0;
  reg        [7:0]    m_1;
  reg        [7:0]    m_2;
  reg        [7:0]    m_3;
  wire                mask_0;
  wire                mask_1;
  wire                mask_2;
  wire                mask_3;

  assign sum = (io_sum + io_carry);
  assign p = sum[7 : 1];
  assign io_p = p;
  always @(*) begin
    m_0[0] = ($signed(7'h73) <= $signed(p));
    m_0[1] = ($signed(7'h72) <= $signed(p));
    m_0[2] = ($signed(7'h70) <= $signed(p));
    m_0[3] = ($signed(7'h6f) <= $signed(p));
    m_0[4] = ($signed(7'h6e) <= $signed(p));
    m_0[5] = ($signed(7'h6c) <= $signed(p));
    m_0[6] = ($signed(7'h6a) <= $signed(p));
    m_0[7] = ($signed(7'h69) <= $signed(p));
  end

  always @(*) begin
    m_1[0] = ($signed(7'h7c) <= $signed(p));
    m_1[1] = ($signed(7'h7c) <= $signed(p));
    m_1[2] = ($signed(7'h7a) <= $signed(p));
    m_1[3] = ($signed(7'h7a) <= $signed(p));
    m_1[4] = ($signed(7'h7a) <= $signed(p));
    m_1[5] = ($signed(7'h7a) <= $signed(p));
    m_1[6] = ($signed(7'h78) <= $signed(p));
    m_1[7] = ($signed(7'h78) <= $signed(p));
  end

  always @(*) begin
    m_2[0] = ($signed(7'h04) <= $signed(p));
    m_2[1] = ($signed(7'h04) <= $signed(p));
    m_2[2] = ($signed(7'h06) <= $signed(p));
    m_2[3] = ($signed(7'h06) <= $signed(p));
    m_2[4] = ($signed(7'h06) <= $signed(p));
    m_2[5] = ($signed(7'h06) <= $signed(p));
    m_2[6] = ($signed(7'h08) <= $signed(p));
    m_2[7] = ($signed(7'h08) <= $signed(p));
  end

  always @(*) begin
    m_3[0] = ($signed(7'h0c) <= $signed(p));
    m_3[1] = ($signed(7'h0e) <= $signed(p));
    m_3[2] = ($signed(7'h10) <= $signed(p));
    m_3[3] = ($signed(7'h11) <= $signed(p));
    m_3[4] = ($signed(7'h12) <= $signed(p));
    m_3[5] = ($signed(7'h14) <= $signed(p));
    m_3[6] = ($signed(7'h16) <= $signed(p));
    m_3[7] = ($signed(7'h17) <= $signed(p));
  end

  assign mask_0 = m_0[io_divD];
  assign mask_1 = m_1[io_divD];
  assign mask_2 = m_2[io_divD];
  assign mask_3 = m_3[io_divD];
  always @(*) begin
    if(mask_3) begin
      io_qsm = 4'b1000;
    end else begin
      if(mask_2) begin
        io_qsm = 4'b0100;
      end else begin
        if(mask_1) begin
          io_qsm = 4'b0000;
        end else begin
          if(mask_0) begin
            io_qsm = 4'b0010;
          end else begin
            io_qsm = 4'b0001;
          end
        end
      end
    end
  end


endmodule
