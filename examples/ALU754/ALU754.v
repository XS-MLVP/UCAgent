module ALU754(
	input [31:0] a_operand,
	input [31:0] b_operand,
	input [3:0] Operation,	
	output [31:0] ALU_Output,
	output Exception,Overflow,Underflow
	);


wire [31:0] Add_Sub_A,Add_Sub_B,Mul_A,Mul_B,Div_A,Div_B,OR_Output,AND_Output,XOR_Output,L_S_Output,R_S_Output,Floating_Point;

wire Add_Sub_Exception,Mul_Exception,Mul_Overflow,Mul_Underflow,Div_Exception;

wire [31:0] Add_Sub_Output,Mul_Output,Div_Output,Integer_Value;

wire AddBar_Sub;

wire [31:0] Complement_output;



assign {Add_Sub_A,Add_Sub_B,AddBar_Sub} = (Operation == 4'd10) ? {a_operand,b_operand,1'b0} : 
                                       (Operation == 4'd3) ? {a_operand,b_operand,1'b1} : 65'dz;

assign {Mul_A,Mul_B} = (Operation == 4'd1) ? {a_operand,b_operand} : 64'dz;

assign {Div_A,Div_B} = (Operation == 4'd2) ? {a_operand,b_operand}	: 64'dz;

// assign {Add_Sub_A,Add_Sub_B,AddBar_Sub} = (Operation == 4'd3) ? {a_operand,b_operand,1'b1} : 64'dz; // Combined with line above

assign OR_Output = (Operation == 4'd4) ? a_operand | b_operand	: 32'dz;

assign AND_Output = (Operation == 4'd5) ? a_operand & b_operand	: 32'dz;

assign XOR_Output = (Operation == 4'd6) ? a_operand ^ b_operand: 32'dz;

assign L_S_Output = (Operation == 4'd7) ? a_operand << 1'b1 : 32'dz;

assign R_S_Output = (Operation == 4'd8) ? a_operand >> 1'b1	: 32'dz;

assign Floating_Point = (Operation == 4'd9) ? a_operand	: 32'dz;

assign Complement_output = (Operation == 4'd11) ? !a_operand : 32'dz;

/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

Addition_Subtraction AuI(Add_Sub_A,Add_Sub_B,AddBar_Sub,Add_Sub_Exception,Add_Sub_Output);

Multiplication MuI(Mul_A,Mul_B,Mul_Exception,Mul_Overflow,Mul_Underflow,Mul_Output);

Division DuI(Div_A,Div_B,Div_Exception,Div_Output);

Floating_Point_to_Integer FuI(Floating_Point,Integer_Value);

/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd10) ? {Add_Sub_Exception,1'b0,1'b0,Add_Sub_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd1) ? {Mul_Exception,Mul_Overflow,Mul_Underflow,Mul_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd2) ? {Div_Exception,1'b0,1'b0,Div_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd3) ? {Add_Sub_Exception,1'b0,1'b0,Add_Sub_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd4) ? {1'b0,1'b0,1'b0,OR_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd5) ? {1'b0,1'b0,1'b0,AND_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd6) ? {1'b0,1'b0,1'b0,XOR_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd7) ? {1'b0,1'b0,1'b0,L_S_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd8) ? {1'b0,1'b0,1'b0,R_S_Output}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd9) ? {1'b0,1'b0,1'b0,Integer_Value}	: 35'dz;

assign {Exception,Overflow,Underflow,ALU_Output} = (Operation == 4'd11) ? {1'b0,1'b0,1'b0,Complement_output} : 35'dz;

endmodule



module Addition_Subtraction(
input [31:0] a_operand,b_operand, //Inputs in the format of IEEE-754 Representation.
input AddBar_Sub,				  //If Add_Sub is low then Addition else Subtraction.
output Exception,
output [31:0] result              //Outputs in the format of IEEE-754 Representation.
);

wire operation_sub_addBar;
wire Comp_enable;
wire output_sign;

wire [31:0] operand_a,operand_b;
wire [23:0] significand_a,significand_b;
wire [7:0] exponent_diff;


wire [23:0] significand_b_add_sub;
wire [7:0] exponent_b_add_sub;

wire [24:0] significand_add;
wire [30:0] add_sum;

wire [23:0] significand_sub_complement;
wire [24:0] significand_sub;
wire [30:0] sub_diff;
wire [24:0] subtraction_diff; 
wire [7:0] exponent_sub;

//for operations always operand_a must not be less than b_operand
assign {Comp_enable,operand_a,operand_b} = (a_operand[30:0] < b_operand[30:0]) ? {1'b1,b_operand,a_operand} : {1'b0,a_operand,b_operand};

assign exp_a = operand_a[30:23];
assign exp_b = operand_b[30:23];

//Exception flag sets 1 if either one of the exponent is 255.
assign Exception = (&operand_a[30:23]) | (&operand_b[30:23]);

assign output_sign = AddBar_Sub ? Comp_enable ? !operand_a[31] : operand_a[31] : operand_a[31] ;

assign operation_sub_addBar = AddBar_Sub ? operand_a[31] ^ operand_b[31] : ~(operand_a[31] ^ operand_b[31]);

//Assigining significand values according to Hidden Bit.
//If exponent is equal to zero then hidden bit will be 0 for that respective significand else it will be 1
assign significand_a = (|operand_a[30:23]) ? {1'b1,operand_a[22:0]} : {1'b0,operand_a[22:0]};
assign significand_b = (|operand_b[30:23]) ? {1'b1,operand_b[22:0]} : {1'b0,operand_b[22:0]};

//Evaluating Exponent Difference
assign exponent_diff = operand_a[30:23] - operand_b[30:23];

//Shifting significand_b according to exponent_diff
assign significand_b_add_sub = significand_b >> exponent_diff;

assign exponent_b_add_sub = operand_b[30:23] + exponent_diff; 

//Checking exponents are same or not
assign perform = (operand_a[30:23] == exponent_b_add_sub);

///////////////////////////////////////////////////////////////////////////////////////////////////////
//------------------------------------------------ADD BLOCK------------------------------------------//

assign significand_add = (perform & operation_sub_addBar) ? (significand_a + significand_b_add_sub) : 25'd0; 

//Result will be equal to Most 23 bits if carry generates else it will be Least 22 bits.
assign add_sum[22:0] = significand_add[24] ? significand_add[23:1] : significand_add[22:0];

//If carry generates in sum value then exponent must be added with 1 else feed as it is.
assign add_sum[30:23] = significand_add[24] ? (1'b1 + operand_a[30:23]) : operand_a[30:23];

///////////////////////////////////////////////////////////////////////////////////////////////////////
//------------------------------------------------SUB BLOCK------------------------------------------//

assign significand_sub_complement = (perform & !operation_sub_addBar) ? ~(significand_b_add_sub) + 24'd1 : 24'd0 ; 

assign significand_sub = perform ? (significand_a + significand_sub_complement) : 25'd0;

priority_encoder pe(significand_sub,operand_a[30:23],subtraction_diff,exponent_sub);

assign sub_diff[30:23] = exponent_sub;

assign sub_diff[22:0] = subtraction_diff[22:0];

///////////////////////////////////////////////////////////////////////////////////////////////////////
//-------------------------------------------------OUTPUT--------------------------------------------//

//If there is no exception and operation will evaluate


assign result = Exception ? 32'b0 : ((!operation_sub_addBar) ? {output_sign,sub_diff} : {output_sign,add_sum});
endmodule



module priority_encoder(
			input [24:0] significand,
			input [7:0] Exponent_a,
			output reg [24:0] Significand,
			output [7:0] Exponent_sub
			);

reg [4:0] shift;

always @(significand)
begin
	casex (significand)
		25'b1_1xxx_xxxx_xxxx_xxxx_xxxx_xxxx :	begin
													Significand = significand;
									 				shift = 5'd0;
								 			  	end
		25'b1_01xx_xxxx_xxxx_xxxx_xxxx_xxxx : 	begin						
										 			Significand = significand << 1;
									 				shift = 5'd1;
								 			  	end

		25'b1_001x_xxxx_xxxx_xxxx_xxxx_xxxx : 	begin						
										 			Significand = significand << 2;
									 				shift = 5'd2;
								 				end

		25'b1_0001_xxxx_xxxx_xxxx_xxxx_xxxx : 	begin 							
													Significand = significand << 3;
								 	 				shift = 5'd3;
								 				end

		25'b1_0000_1xxx_xxxx_xxxx_xxxx_xxxx : 	begin						
									 				Significand = significand << 4;
								 	 				shift = 5'd4;
								 				end

		25'b1_0000_01xx_xxxx_xxxx_xxxx_xxxx : 	begin						
									 				Significand = significand << 5;
								 	 				shift = 5'd5;
								 				end

		25'b1_0000_001x_xxxx_xxxx_xxxx_xxxx : 	begin						// 24'h020000
									 				Significand = significand << 6;
								 	 				shift = 5'd6;
								 				end

		25'b1_0000_0001_xxxx_xxxx_xxxx_xxxx : 	begin						// 24'h010000
									 				Significand = significand << 7;
								 	 				shift = 5'd7;
								 				end

		25'b1_0000_0000_1xxx_xxxx_xxxx_xxxx : 	begin						// 24'h008000
									 				Significand = significand << 8;
								 	 				shift = 5'd8;
								 				end

		25'b1_0000_0000_01xx_xxxx_xxxx_xxxx : 	begin						// 24'h004000
									 				Significand = significand << 9;
								 	 				shift = 5'd9;
								 				end

		25'b1_0000_0000_001x_xxxx_xxxx_xxxx : 	begin						// 24'h002000
									 				Significand = significand << 10;
								 	 				shift = 5'd10;
								 				end

		25'b1_0000_0000_0001_xxxx_xxxx_xxxx : 	begin						// 24'h001000
									 				Significand = significand << 11;
								 	 				shift = 5'd11;
								 				end

		25'b1_0000_0000_0000_1xxx_xxxx_xxxx : 	begin						// 24'h000800
									 				Significand = significand << 12;
								 	 				shift = 5'd12;
								 				end

		25'b1_0000_0000_0000_01xx_xxxx_xxxx : 	begin						// 24'h000400
									 				Significand = significand << 13;
								 	 				shift = 5'd13;
								 				end

		25'b1_0000_0000_0000_001x_xxxx_xxxx : 	begin						// 24'h000200
									 				Significand = significand << 14;
								 	 				shift = 5'd14;
								 				end

		25'b1_0000_0000_0000_0001_xxxx_xxxx  : 	begin						// 24'h000100
									 				Significand = significand << 15;
								 	 				shift = 5'd15;
								 				end

		25'b1_0000_0000_0000_0000_1xxx_xxxx : 	begin						// 24'h000080
									 				Significand = significand << 16;
								 	 				shift = 5'd16;
								 				end

		25'b1_0000_0000_0000_0000_01xx_xxxx : 	begin						// 24'h000040
											 		Significand = significand << 17;
										 	 		shift = 5'd17;
												end

		25'b1_0000_0000_0000_0000_001x_xxxx : 	begin						// 24'h000020
									 				Significand = significand << 18;
								 	 				shift = 5'd18;
								 				end

		25'b1_0000_0000_0000_0000_0001_xxxx : 	begin						// 24'h000010
									 				Significand = significand << 19;
								 	 				shift = 5'd19;
												end

		25'b1_0000_0000_0000_0000_0000_1xxx :	begin						// 24'h000008
									 				Significand = significand << 20;
								 					shift = 5'd20;
								 				end

		25'b1_0000_0000_0000_0000_0000_01xx : 	begin						// 24'h000004
									 				Significand = significand << 21;
								 	 				shift = 5'd21;
								 				end

		25'b1_0000_0000_0000_0000_0000_001x : 	begin						// 24'h000002
									 				Significand = significand << 22;
								 	 				shift = 5'd22;
								 				end

		25'b1_0000_0000_0000_0000_0000_0001 : 	begin						// 24'h000001
									 				Significand = significand << 23;
								 	 				shift = 5'd23;
								 				end

		25'b1_0000_0000_0000_0000_0000_0000 : 	begin						// 24'h000000
								 					Significand = significand << 24;
							 	 					shift = 5'd24;
								 				end
		default : 	begin
						Significand = (~significand) + 1'b1;
						shift = 8'd0;
					end

	endcase
end
assign Exponent_sub = Exponent_a - shift;

endmodule


module Multiplication(
		input [31:0] a_operand,
		input [31:0] b_operand,
		output Exception,Overflow,Underflow,
		output [31:0] result
		);

wire sign,product_round,normalised,zero;
wire [8:0] exponent,sum_exponent;
wire [22:0] product_mantissa;
wire [23:0] operand_a,operand_b;
wire [47:0] product,product_normalised; //48 Bits


assign sign = a_operand[31] ^ b_operand[31];

//Exception flag sets 1 if either one of the exponent is 255.
assign Exception = (&a_operand[30:23]) | (&b_operand[30:23]);

//Assigining significand values according to Hidden Bit.
//If exponent is equal to zero then hidden bit will be 0 for that respective significand else it will be 1

assign operand_a = (|a_operand[30:23]) ? {1'b1,a_operand[22:0]} : {1'b0,a_operand[22:0]};

assign operand_b = (|b_operand[30:23]) ? {1'b1,b_operand[22:0]} : {1'b0,b_operand[22:0]};

assign product = operand_a * operand_b;			//Calculating Product

assign product_round = |product_normalised[22:0];  //Ending 22 bits are OR'ed for rounding operation.

assign normalised = product[47] ? 1'b1 : 1'b0;	

assign product_normalised = normalised ? product : product << 1;	//Assigning Normalised value based on 48th bit

//Final Manitssa.
assign product_mantissa = product_normalised[46:24] + {21'b0,(product_normalised[23] & product_round)};

assign zero = Exception ? 1'b0 : (product_mantissa == 23'd0) ? 1'b1 : 1'b0;

assign sum_exponent = a_operand[30:23] + b_operand[30:23];

assign exponent = sum_exponent - 8'd127 + normalised;

assign Overflow = ((exponent[8] & !exponent[7]) & !zero) ; //If overall exponent is greater than 255 then Overflow condition.
//Exception Case when exponent reaches its maximu value that is 384.

//If sum of both exponents is less than 127 then Underflow condition.
assign Underflow = ((exponent[8] & exponent[7]) & !zero) ? 1'b1 : 1'b0; 

assign result = Exception ? 32'd0 : zero ? {sign,31'd0} : Overflow ? {sign,8'hFF,23'd0} : Underflow ? {sign,31'd0} : {sign,exponent[7:0],product_mantissa};


endmodule



module Iteration(
	input [31:0] operand_1,
	input [31:0] operand_2,
	output [31:0] solution
	);

wire [31:0] Intermediate_Value1,Intermediate_Value2;

Multiplication M1(operand_1,operand_2,,,,Intermediate_Value1);

//32'h4000_0000 -> 2.
Addition_Subtraction A1(32'h4000_0000,{1'b1,Intermediate_Value1[30:0]},1'b0,,Intermediate_Value2);

Multiplication M2(operand_1,Intermediate_Value2,,,,solution);

endmodule



module Division(
	input [31:0] a_operand,
	input [31:0] b_operand,
	output Exception,
	output [31:0] result
);

wire sign;
wire [7:0] shift;
wire [7:0] exponent_a;
wire [31:0] divisor;
wire [31:0] operand_a;
wire [31:0] Intermediate_X0;
wire [31:0] Iteration_X0;
wire [31:0] Iteration_X1;
wire [31:0] Iteration_X2;
wire [31:0] Iteration_X3;
wire [31:0] solution;

wire [31:0] denominator;
wire [31:0] operand_a_change;

assign Exception = (&a_operand[30:23]) | (&b_operand[30:23]);

assign sign = a_operand[31] ^ b_operand[31];

assign shift = 8'd126 - b_operand[30:23];

assign divisor = {1'b0,8'd126,b_operand[22:0]};

assign denominator = divisor;

assign exponent_a = a_operand[30:23] + shift;

assign operand_a = {a_operand[31],exponent_a,a_operand[22:0]};

assign operand_a_change = operand_a;

//32'hC00B_4B4B = (-37)/17
Multiplication x0(32'hC00B_4B4B,divisor,,,,Intermediate_X0);

//32'h4034_B4B5 = 48/17
Addition_Subtraction X0(Intermediate_X0,32'h4034_B4B5,1'b0,,Iteration_X0);

Iteration X1(Iteration_X0,divisor,Iteration_X1);

Iteration X2(Iteration_X1,divisor,Iteration_X2);

Iteration X3(Iteration_X2,divisor,Iteration_X3);

Multiplication END(Iteration_X3,operand_a,,,,solution);

assign result = {sign,solution[30:0]};
endmodule


module Floating_Point_to_Integer(
		input [31:0] a_operand,
		output [31:0] Integer
		);

reg [23:0] Integer_Value;

always @(*)
begin
	if (a_operand[30:23] == 8'd127)
			begin
				Integer_Value = 23'd0;
			end

	else if (a_operand[30:23] == 8'd128)
			begin
				Integer_Value = {a_operand[22],22'd0};
				 
			end

	else if (a_operand[30:23] == 8'd129)
			begin
				Integer_Value = {a_operand[22:21],21'd0};
				 
			end

	else if (a_operand[30:23] == 8'd130)
			begin
				Integer_Value = {a_operand[22:20],20'd0};
				 
			end

	else if (a_operand[30:23] == 8'd131)
			begin
				Integer_Value = {a_operand[22:19],19'd0};
				 
			end

	else if (a_operand[30:23] == 8'd132)
			begin
				Integer_Value = {a_operand[22:18],18'd0};
				 
			end

	else if (a_operand[30:23] == 8'd133)
			begin
				Integer_Value = {a_operand[22:17],17'd0};
				 
			end

	else if (a_operand[30:23] == 8'd134)
			begin
				Integer_Value = {a_operand[22:16],16'd0};
				 
			end

	else if (a_operand[30:23] == 8'd135)
			begin
				Integer_Value = {a_operand[22:15],15'd0};
				 
			end

	else if (a_operand[30:23] == 8'd136)
			begin
				Integer_Value = {a_operand[22:14],14'd0};
				 
			end

	else if (a_operand[30:23] == 8'd137)
			begin
				Integer_Value = {a_operand[22:13],13'd0};
				 
			end

	else if (a_operand[30:23] == 8'd138)
			begin
				Integer_Value = {a_operand[22:12],12'd0};
				 
			end

	else if (a_operand[30:23] == 8'd139)
			begin
				Integer_Value = {a_operand[22:11],11'd0};
				 
			end

	else if (a_operand[30:23] == 8'd140)
			begin
				Integer_Value = {a_operand[22:10],10'd0};
				 
			end

	else if (a_operand[30:23] == 8'd141)
			begin
				Integer_Value = {a_operand[22:9],9'd0};
				 
			end

	else if (a_operand[30:23] == 8'd142)
			begin
				Integer_Value = {a_operand[22:8],8'd0};
				 
			end

	else if (a_operand[30:23] == 8'd143)
			begin
				Integer_Value = {a_operand[22:7],7'd0};
				 
			end

	else if (a_operand[30:23] == 8'd144)
			begin
				Integer_Value = {a_operand[22:6],6'd0};
				 
			end

	else if (a_operand[30:23] == 8'd145)
			begin
				Integer_Value = {a_operand[22:5],5'd0};
				 
			end

	else if (a_operand[30:23] == 8'd146)
			begin
				Integer_Value = {a_operand[22:4],4'd0};
				 
			end

	else if (a_operand[30:23] == 8'd147)
			begin
				Integer_Value = {a_operand[22:3],3'd0};
				 
			end

	else if (a_operand[30:23] == 8'd148)
			begin
				Integer_Value = {a_operand[22:2],2'd0};
				 
			end

	else if (a_operand[30:23] == 8'd149)
			begin
				Integer_Value = {a_operand[22:1],1'd0};
				 
			end

	else if (a_operand[30:23] >= 8'd150)
			begin
				Integer_Value = a_operand[22:0];
				 
			end

	else if (a_operand[30:23] <= 8'd126)
			begin
				Integer_Value = 24'd0;
				 
			end
end

assign Integer = {a_operand[31:23],Integer_Value[23:1]};

endmodule
