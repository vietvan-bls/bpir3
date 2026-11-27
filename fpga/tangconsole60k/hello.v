// Tang Console 60K (GW5AT-60): 8 LED chạy đuổi + UART 115200 in "Hello" mỗi lần LED đổi trạng thái.
// Nút KEY (AA13) giữ → nháy nhanh gấp 4. Nút RESET (AB13) → đếm lại từ 0.
// Nhận ký tự từ UART → gửi trả (echo) ngay.
module top (
    input  wire clk,       // 50 MHz (V22)
    input  wire key_i,     // nút, kéo lên, nhấn = 0
    input  wire rst_i,
    input  wire RXD,
    output wire TXD,
    output reg  [7:0] led = 8'b1  // 8 LED chạy đuổi, dịch mỗi 0.5 s
);
    localparam CLK = 50_000_000, BAUD = 115200, DIV = CLK / BAUD;

    // ---- nháy LED ----
    reg [24:0] cnt = 0;
    reg [15:0] blinks = 0;
    wire [24:0] period = key_i ? CLK / 2 - 1 : CLK / 8 - 1;
    reg tick = 0;
    always @(posedge clk) begin
        tick <= 0;
        if (!rst_i) begin cnt <= 0; blinks <= 0; end
        else if (cnt >= period) begin
            cnt <= 0; led <= {led[6:0], led[7]}; blinks <= blinks + 1; tick <= 1;
        end else cnt <= cnt + 1;
    end

    // ---- UART RX ----
    reg [1:0] rxs = 2'b11;
    always @(posedge clk) rxs <= {rxs[0], RXD};
    reg [15:0] rcnt = 0; reg [3:0] rbit = 0; reg [7:0] rsh = 0; reg rbusy = 0;
    reg [7:0] rdata = 0; reg rvalid = 0;
    always @(posedge clk) begin
        rvalid <= 0;
        if (!rbusy) begin
            if (!rxs[1]) begin rbusy <= 1; rcnt <= DIV / 2; rbit <= 0; end
        end else if (rcnt != 0) rcnt <= rcnt - 1;
        else begin
            rcnt <= DIV - 1;
            if (rbit == 0) begin if (rxs[1]) rbusy <= 0; end       // start bit giả
            else if (rbit <= 8) rsh <= {rxs[1], rsh[7:1]};
            else begin rbusy <= 0; rdata <= rsh; rvalid <= rxs[1]; end
            rbit <= rbit + 1;
        end
    end

    // ---- UART TX ----
    reg [9:0] tsh = 10'h3ff; reg [3:0] tleft = 0; reg [15:0] tcnt = 0;
    assign TXD = tsh[0];
    wire tready = tleft == 0;
    reg [7:0] tbyte; reg tgo;
    always @(posedge clk) begin
        if (tgo && tready) begin tsh <= {1'b1, tbyte, 1'b0}; tleft <= 10; tcnt <= DIV - 1; end
        else if (!tready) begin
            if (tcnt != 0) tcnt <= tcnt - 1;
            else begin tcnt <= DIV - 1; tsh <= {1'b1, tsh[9:1]}; tleft <= tleft - 1; end
        end
    end

    // ---- câu chào: "Hello Tang Console #xxxx\r\n" (xxxx = số lần nháy, hex) ----
    localparam MSG = "Hello Tang Console #";
    localparam MLEN = 20;
    reg [4:0] idx = 0; reg sending = 0; reg [15:0] snap = 0;
    reg pend_echo = 0; reg [7:0] echo = 0;
    function [7:0] hex(input [3:0] v); hex = v < 10 ? "0" + v : "A" + v - 10; endfunction
    always @(posedge clk) begin
        tgo <= 0;
        if (rvalid) begin pend_echo <= 1; echo <= rdata; end
        if (tick && !sending) begin sending <= 1; idx <= 0; snap <= blinks; end
        if (tready && !tgo) begin
            if (sending) begin
                tgo <= 1;
                if (idx < MLEN) tbyte <= MSG[8*(MLEN-1-idx) +: 8];
                else case (idx - MLEN)
                    0: tbyte <= hex(snap[15:12]);
                    1: tbyte <= hex(snap[11:8]);
                    2: tbyte <= hex(snap[7:4]);
                    3: tbyte <= hex(snap[3:0]);
                    4: tbyte <= 8'h0d;
                    default: tbyte <= 8'h0a;
                endcase
                if (idx == MLEN + 5) sending <= 0;
                idx <= idx + 1;
            end else if (pend_echo) begin tgo <= 1; tbyte <= echo; pend_echo <= 0; end
        end
    end
endmodule
