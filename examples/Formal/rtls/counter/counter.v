//-----------------------------------------------------------
`define COUNT_MAX 3'd5
`define INITIAL_VALUE 3'd0
module counter(in,clk,rst_n,c_out,coi_test);
   
   input in,clk,rst_n;
   output reg[2:0] c_out;
   output 	   coi_test;   
   always@(posedge clk or negedge rst_n)
     if(!rst_n)
       c_out<=`INITIAL_VALUE;
     else if(c_out==`COUNT_MAX)
       c_out<=3'd0;
     else
       c_out<=c_out+3'd1; //the rtl bug
   

   reg 		   coi_test;   
   always@(posedge clk or negedge rst_n)
     if(!rst_n)
       coi_test<=1'd0;
     else
       coi_test<=in;
   
   
endmodule // top

/*-----------------------------------------------------------
 >>Q1:design info?
   1.this is a 1-step counter with reset state 
     and max value limit;
 
 >>Q2:how to use the abv(assertion-based verification) methodology to verify?  
   1.assertion: using the sva to descript the 
     function property of design
   2.methodology: static verification "formal"
 
 >>Q3:how to convert design spec to verification goal completely??
   1.the reset state of counter should be `INITIAL_VALUE;
   2.the counter increase step is 1;
   3.the couter value should <= `COUNT_MAX
   4.ensure each value between `INITIAL_VALUE and `COUNT_MAX should be covered;

  >>Q4:how to convert the verification goal to sva;
   1.understanding the basic blcock grammar,meaning and usage
   2.according to the verification goal to translate one by one
 
-----------------------------------------------------------*/
