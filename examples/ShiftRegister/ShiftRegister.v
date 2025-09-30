module ShiftRegister (
    input clk,
    input areset,  // 异步高电平复位到0
    input load,    // 同步加载
    input ena,     // 右移使能
    input [3:0] data,
    output reg [3:0] q
);
    
    always @(posedge clk or posedge areset) begin
        if (areset) begin
            // 异步复位，寄存器清零
            q <= 4'b0;
        end
        else begin
            if (load) begin
                // 同步加载，优先级最高
                q <= data;
            end
            else if (ena) begin
                // 右移操作：q[3]变为0，其他位右移
                q <= {1'b0, q[3:1]};
            end
            // 如果load和ena都为0，保持q不变
        end
    end

endmodule