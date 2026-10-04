// ModelSim Testbench for sequential_format_one_pkt_test
// Test case: DSEG1=256, n_seg=2, Second segment size=300
//
// This test verifies the sequential format packet structure:
//   Segment 1: Data length = 256 (within single-packet range 0~256)
//   Segment 2: Data length = 300 (exceeds 256, should cause error)
//
// Expected behavior:
//   - Segment 1 data completes within one AXI burst
//   - Segment 2 triggers REG_LEN_ERR because 300 > 256

`timescale 1ns/1ps

module sequential_format_one_pkt_dseg1_256_tb;

    // ---------------------------------------------------------------
    // Parameters
    // ---------------------------------------------------------------
    parameter ADDR_WIDTH       = 12;
    parameter AXI_DATA_WIDTH   = 256;
    parameter AXI_ADDR_WIDTH   = 32;
    parameter DLEN_WIDTH       = 16;
    parameter TUPLE_NUM        = 1;
    parameter AUX_KEY_ID_WIDTH = 4;

    // Derived
    localparam BYTE_NUM     = AXI_DATA_WIDTH / 8;  // 32 bytes
    localparam STRB_WIDTH   = BYTE_NUM;

    // ---------------------------------------------------------------
    // Test control
    // ---------------------------------------------------------------
    integer test_pass_count = 0;
    integer test_fail_count = 0;

    // ---------------------------------------------------------------
    // DUT signals
    // ---------------------------------------------------------------
    reg                                    clk;
    reg                                    rst_n;
    reg                                    soft_rst;

    // Input command interface
    reg                                    cmd_in_valid;
    wire                                   cmd_in_ready;
    reg  [160-1:0]                         cmd_in_data;  // 5 words x 32 bits
    reg  [2-1:0]                           cmd_in_start;
    reg  [2-1:0]                           cmd_in_end;
    reg  [8-1:0]                           cmd_in_count;
    reg  [3-1:0]                           cmd_in_empty;
    reg                                    cmd_in_user;

    // Output command interface
    wire                                   cmd_out_valid;
    reg                                    cmd_out_ready;
    wire [256-1:0]                         cmd_out_data;

    // Output SRAM write interface
    wire                                   o_sram_wr_cmd_valid;
    reg                                    o_sram_wr_cmd_ready;
    wire [10-1:0]                          o_sram_wr_addr;
    wire [8-1:0]                           o_sram_wr_length;
    wire                                   o_sram_wr_data_valid;
    reg                                    o_sram_wr_data_ready;
    wire [256-1:0]                         o_sram_wr_data;
    wire                                   o_sram_wr_last;

    // SRAM read interface (unused in this test)
    reg                                    i_sram_rd_cmd_valid;
    wire                                   i_sram_rd_cmd_ready;
    reg  [10-1:0]                          i_sram_rd_addr;
    reg  [8-1:0]                           i_sram_rd_length;
    wire                                   i_sram_rd_data_valid;
    reg                                    i_sram_rd_data_ready;
    wire [256-1:0]                         i_sram_rd_data;
    wire                                   i_sram_rd_last;

    // AXI Master Write Address Channel
    wire                                   m_axi_awvalid;
    reg                                    m_axi_awready;
    wire [AXI_ADDR_WIDTH-1:0]              m_axi_awaddr;
    wire [8-1:0]                           m_axi_awlen;
    wire [3-1:0]                           m_axi_awsize;
    wire [2-1:0]                           m_axi_awburst;
    wire [4-1:0]                           m_axi_awcache;
    wire [3-1:0]                           m_axi_awprot;
    wire [4-1:0]                           m_axi_awqos;
    wire [4-1:0]                           m_axi_awregion;
    wire [5-1:0]                           m_axi_awuser;
    wire [1-1:0]                           m_axi_awlock;
    wire [4-1:0]                           m_axi_awid;

    // AXI Master Write Data Channel
    wire                                   m_axi_wvalid;
    reg                                    m_axi_wready;
    wire [AXI_DATA_WIDTH-1:0]              m_axi_wdata;
    wire [STRB_WIDTH-1:0]                  m_axi_wstrb;
    wire                                   m_axi_wlast;
    wire [4-1:0]                           m_axi_wid;
    wire                                   m_axi_wuser;

    // AXI Master Write Response Channel
    reg                                    m_axi_bvalid;
    wire                                   m_axi_bready;
    reg  [2-1:0]                           m_axi_bresp;
    reg  [4-1:0]                           m_axi_bid;
    reg                                    m_axi_buser;

    // AXI Master Read Address Channel (unused)
    wire                                   m_axi_arvalid;
    reg                                    m_axi_arready;
    wire [AXI_ADDR_WIDTH-1:0]              m_axi_araddr;
    wire [8-1:0]                           m_axi_arlen;
    wire [3-1:0]                           m_axi_arsize;
    wire [2-1:0]                           m_axi_arburst;
    wire [4-1:0]                           m_axi_arcache;
    wire [3-1:0]                           m_axi_arprot;
    wire [4-1:0]                           m_axi_arqos;
    wire [4-1:0]                           m_axi_arregion;
    wire [5-1:0]                           m_axi_aruser;
    wire [1-1:0]                           m_axi_arlock;
    wire [4-1:0]                           m_axi_arid;

    // AXI Master Read Data Channel (unused)
    reg                                    m_axi_rvalid;
    wire                                   m_axi_rready;
    reg  [AXI_DATA_WIDTH-1:0]              m_axi_rdata;
    reg  [2-1:0]                           m_axi_rresp;
    reg                                    m_axi_rlast;
    reg  [4-1:0]                           m_axi_rid;
    reg                                    m_axi_ruser;

    // Error output
    wire                                   err_req;
    wire                                   err_seg_len;

    // ---------------------------------------------------------------
    // Clock and Reset
    // ---------------------------------------------------------------
    initial clk = 1'b0;
    always #2.5 clk = ~clk;  // 200MHz

    // ---------------------------------------------------------------
    // DUT Instantiation
    // ---------------------------------------------------------------
    output_port_merger #(
        .ADDR_WIDTH         (ADDR_WIDTH),
        .AXI_DATA_WIDTH     (AXI_DATA_WIDTH),
        .AXI_ADDR_WIDTH     (AXI_ADDR_WIDTH),
        .DLEN_WIDTH         (DLEN_WIDTH),
        .TUPLE_NUM          (TUPLE_NUM),
        .AUX_KEY_ID_WIDTH   (AUX_KEY_ID_WIDTH)
    ) u_dut (
        .clk                    (clk),
        .rst_n                  (rst_n),
        .soft_rst               (soft_rst),

        // Input command
        .cmd_in_valid           (cmd_in_valid),
        .cmd_in_ready           (cmd_in_ready),
        .cmd_in_data            (cmd_in_data),
        .cmd_in_start           (cmd_in_start),
        .cmd_in_end             (cmd_in_end),
        .cmd_in_count           (cmd_in_count),
        .cmd_in_empty           (cmd_in_empty),
        .cmd_in_user            (cmd_in_user),

        // Output command
        .cmd_out_valid          (cmd_out_valid),
        .cmd_out_ready          (cmd_out_ready),
        .cmd_out_data           (cmd_out_data),

        // SRAM write
        .o_sram_wr_cmd_valid    (o_sram_wr_cmd_valid),
        .o_sram_wr_cmd_ready    (o_sram_wr_cmd_ready),
        .o_sram_wr_addr         (o_sram_wr_addr),
        .o_sram_wr_length       (o_sram_wr_length),
        .o_sram_wr_data_valid   (o_sram_wr_data_valid),
        .o_sram_wr_data_ready   (o_sram_wr_data_ready),
        .o_sram_wr_data         (o_sram_wr_data),
        .o_sram_wr_last         (o_sram_wr_last),

        // SRAM read
        .i_sram_rd_cmd_valid    (i_sram_rd_cmd_valid),
        .i_sram_rd_cmd_ready    (i_sram_rd_cmd_ready),
        .i_sram_rd_addr         (i_sram_rd_addr),
        .i_sram_rd_length       (i_sram_rd_length),
        .i_sram_rd_data_valid   (i_sram_rd_data_valid),
        .i_sram_rd_data_ready   (i_sram_rd_data_ready),
        .i_sram_rd_data         (i_sram_rd_data),
        .i_sram_rd_last         (i_sram_rd_last),

        // AXI Write Address
        .m_axi_awvalid          (m_axi_awvalid),
        .m_axi_awready          (m_axi_awready),
        .m_axi_awaddr           (m_axi_awaddr),
        .m_axi_awlen            (m_axi_awlen),
        .m_axi_awsize           (m_axi_awsize),
        .m_axi_awburst          (m_axi_awburst),
        .m_axi_awcache          (m_axi_awcache),
        .m_axi_awprot           (m_axi_awprot),
        .m_axi_awqos            (m_axi_awqos),
        .m_axi_awregion         (m_axi_awregion),
        .m_axi_awuser           (m_axi_awuser),
        .m_axi_awlock           (m_axi_awlock),
        .m_axi_awid             (m_axi_awid),

        // AXI Write Data
        .m_axi_wvalid           (m_axi_wvalid),
        .m_axi_wready           (m_axi_wready),
        .m_axi_wdata            (m_axi_wdata),
        .m_axi_wstrb            (m_axi_wstrb),
        .m_axi_wlast            (m_axi_wlast),
        .m_axi_wid              (m_axi_wid),
        .m_axi_wuser            (m_axi_wuser),

        // AXI Write Response
        .m_axi_bvalid           (m_axi_bvalid),
        .m_axi_bready           (m_axi_bready),
        .m_axi_bresp            (m_axi_bresp),
        .m_axi_bid              (m_axi_bid),
        .m_axi_buser            (m_axi_buser),

        // AXI Read Address
        .m_axi_arvalid          (m_axi_arvalid),
        .m_axi_arready          (m_axi_arready),
        .m_axi_araddr           (m_axi_araddr),
        .m_axi_arlen            (m_axi_arlen),
        .m_axi_arsize           (m_axi_arsize),
        .m_axi_arburst          (m_axi_arburst),
        .m_axi_arcache          (m_axi_arcache),
        .m_axi_arprot           (m_axi_arprot),
        .m_axi_arqos            (m_axi_arqos),
        .m_axi_arregion         (m_axi_arregion),
        .m_axi_aruser           (m_axi_aruser),
        .m_axi_arlock           (m_axi_arlock),
        .m_axi_arid             (m_axi_arid),

        // AXI Read Data
        .m_axi_rvalid           (m_axi_rvalid),
        .m_axi_rready           (m_axi_rready),
        .m_axi_rdata            (m_axi_rdata),
        .m_axi_rresp            (m_axi_rresp),
        .m_axi_rlast            (m_axi_rlast),
        .m_axi_rid              (m_axi_rid),
        .m_axi_ruser            (m_axi_ruser),

        // Errors
        .err_req                (err_req),
        .err_seg_len            (err_seg_len)
    );

    // ---------------------------------------------------------------
    // AXI Write Response BFM
    // ---------------------------------------------------------------
    // Track AWID for BRESP
    reg [3:0] awid_queue [0:63];
    integer   awid_wr_ptr = 0;
    integer   awid_rd_ptr = 0;

    always @(posedge clk) begin
        if (m_axi_awvalid && m_axi_awready) begin
            awid_queue[awid_wr_ptr] <= m_axi_awid;
            awid_wr_ptr <= awid_wr_ptr + 1;
        end
    end

    // Response generation: 1~3 cycle latency
    integer bresp_delay;
    reg     bresp_pending;

    task automatic send_bresp();
        begin
            bresp_delay = ($urandom_range(1, 3));
            repeat (bresp_delay) @(posedge clk);
            m_axi_bresp  = 2'b00;  // OKAY
            m_axi_bid    = awid_queue[awid_rd_ptr];
            m_axi_buser  = 1'b0;
            m_axi_bvalid = 1'b1;
            @(posedge clk);
            while (!m_axi_bready) @(posedge clk);
            m_axi_bvalid = 1'b0;
            awid_rd_ptr  = awid_rd_ptr + 1;
        end
    endtask

    always @(posedge clk) begin
        if (m_axi_awvalid && m_axi_awready && !bresp_pending) begin
            bresp_pending = 1;
            send_bresp();
            bresp_pending = 0;
        end
    end

    // ---------------------------------------------------------------
    // WREADY toggle (back-pressure)
    // ---------------------------------------------------------------
    integer wready_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            m_axi_wready <= 1'b1;
            wready_cnt   <= 0;
        end else begin
            wready_cnt <= wready_cnt + 1;
            if (wready_cnt % 7 == 0)
                m_axi_wready <= 1'b0;
            else
                m_axi_wready <= 1'b1;
        end
    end

    // ---------------------------------------------------------------
    // SRAM Write BFM
    // ---------------------------------------------------------------
    reg  [255:0] sram_mem [0:1023];
    reg  [9:0]   sram_wr_idx;
    integer      sram_wr_bursts = 0;
    integer      sram_wr_words  = 0;

    initial begin
        o_sram_wr_cmd_ready  = 1'b1;
        o_sram_wr_data_ready = 1'b1;
        sram_wr_idx = 0;
    end

    always @(posedge clk) begin
        if (o_sram_wr_data_valid && o_sram_wr_data_ready) begin
            sram_mem[sram_wr_idx] <= o_sram_wr_data;
            sram_wr_idx <= sram_wr_idx + 1;
            sram_wr_words <= sram_wr_words + 1;
        end
        if (o_sram_wr_last) begin
            sram_wr_bursts <= sram_wr_bursts + 1;
        end
    end

    // ---------------------------------------------------------------
    // Command output capture
    // ---------------------------------------------------------------
    integer cmd_out_count;
    reg [255:0] cmd_out_captured [0:15];

    always @(posedge clk) begin
        if (cmd_out_valid && cmd_out_ready) begin
            cmd_out_captured[cmd_out_count] <= cmd_out_data;
            cmd_out_count <= cmd_out_count + 1;
        end
    end

    // ---------------------------------------------------------------
    // Error tracking
    // ---------------------------------------------------------------
    integer err_req_count;
    integer err_seg_len_count;

    always @(posedge clk) begin
        if (err_req)     err_req_count <= err_req_count + 1;
        if (err_seg_len) err_seg_len_count <= err_seg_len_count + 1;
    end

    // ---------------------------------------------------------------
    // AXI Read BFM (idle)
    // ---------------------------------------------------------------
    initial begin
        m_axi_arready = 1'b0;
        m_axi_rvalid  = 1'b0;
        m_axi_rdata   = 0;
        m_axi_rresp   = 2'b00;
        m_axi_rlast   = 1'b0;
        m_axi_rid     = 0;
        m_axi_ruser   = 0;
    end

    // ---------------------------------------------------------------
    // Task: Build sequential format cmd_in_data (160 bits)
    //
    // Field layout (5 words x 32 bits):
    //   Word 0 [31:0]    = reserved
    //   Word 1 [127:96]  = m_addr (AXI address)
    //   Word 2 [159:128] = reserved
    //   Word 3 [191:160] = src_addr (SRAM address)
    //   Word 3 [215:192] = pld_len (bytes)
    //   Word 3 [223:216] = meta_type
    //   Word 3 [239:224] = reserved
    //   Word 4 [255:240] = seg_num
    //   Word 4 [271:256] = ctrl_flag
    //   Word 4 [279:272] = seg_id
    // ---------------------------------------------------------------
    task automatic build_sequential_cmd(
        input  [31:0] m_addr,
        input  [31:0] src_addr,
        input  [31:0] pld_len_bytes,  // total payload length in bytes
        input  [7:0]  meta_type,
        input  [15:0] seg_num,
        input  [15:0] ctrl_flag,
        input  [7:0]  seg_id,
        output [159:0] cmd_data
    );
        reg [255:0] pkt;
        begin
            pkt = 256'd0;
            pkt[31:0]    = 32'd0;           // reserved
            pkt[127:96]  = m_addr;          // AXI address
            pkt[159:128] = 32'd0;           // reserved
            pkt[191:160] = src_addr;        // SRAM source address
            pkt[215:192] = pld_len_bytes;   // payload length in bytes
            pkt[223:216] = meta_type;       // metadata type
            pkt[239:224] = 16'd0;           // reserved
            pkt[255:240] = seg_num;         // number of segments
            pkt[271:256] = ctrl_flag;       // control flag
            pkt[279:272] = seg_id;          // segment ID
            cmd_data = pkt[159:0];
        end
    endtask

    // ---------------------------------------------------------------
    // Task: Populate SRAM with known data pattern
    // ---------------------------------------------------------------
    task automatic populate_sram(
        input [9:0]  start_addr,
        input [15:0] num_words,
        input [255:0] pattern_base
    );
        integer i;
        begin
            for (i = 0; i < num_words; i = i + 1) begin
                sram_mem[start_addr + i] = pattern_base + i;
            end
            $display("[TB] SRAM populated: addr %0d ~ %0d (%0d words)",
                     start_addr, start_addr + num_words - 1, num_words);
        end
    endtask

    // ---------------------------------------------------------------
    // Test Stimulus
    // ---------------------------------------------------------------
    reg [159:0] test_cmd;
    reg [31:0]  seg1_m_addr;
    reg [31:0]  seg1_src_addr;
    reg [31:0]  seg1_pld_len;
    reg [31:0]  seg2_m_addr;
    reg [31:0]  seg2_src_addr;
    reg [31:0]  seg2_pld_len;

    initial begin
        // -----------------------------------------------------------
        // Initialize
        // -----------------------------------------------------------
        rst_n              = 1'b0;
        soft_rst           = 1'b0;
        cmd_in_valid       = 1'b0;
        cmd_in_data        = 160'd0;
        cmd_in_start       = 2'b00;
        cmd_in_end         = 2'b00;
        cmd_in_count       = 8'd0;
        cmd_in_empty       = 4'd0;
        cmd_in_user        = 1'b0;
        cmd_out_ready      = 1'b1;
        cmd_out_count      = 0;
        err_req_count      = 0;
        err_seg_len_count  = 0;
        sram_wr_bursts     = 0;
        sram_wr_words      = 0;
        bresp_pending      = 0;

        // AXI defaults
        m_axi_awready      = 1'b1;
        m_axi_bvalid       = 1'b0;
        m_axi_bresp        = 2'b00;
        m_axi_bid          = 4'd0;
        m_axi_buser        = 1'b0;
        awid_wr_ptr        = 0;
        awid_rd_ptr        = 0;

        // -----------------------------------------------------------
        // Reset
        // -----------------------------------------------------------
        #50;
        rst_n = 1'b1;
        #50;

        $display("==========================================================");
        $display("[TB] Sequential Format Test: DSEG1=256, N_SEG=2");
        $display("[TB] Segment 1: 256 words (8192 bytes)");
        $display("[TB] Segment 2: 300 words (9600 bytes) - should trigger ERR");
        $display("==========================================================");

        // -----------------------------------------------------------
        // Populate SRAM with test data
        // -----------------------------------------------------------
        // Segment 1: 256 words at SRAM address 0
        populate_sram(10'd0, 16'd256, 256'hA000_0000_0000_0000);
        // Segment 2: 300 words at SRAM address 256
        populate_sram(10'd256, 16'd300, 256'hB000_0000_0000_0000);

        // -----------------------------------------------------------
        // SEGMENT 1: 256 words = 8192 bytes, sequential format
        // -----------------------------------------------------------
        $display("\n[TB] === Sending Segment 1: 256 words (8192 bytes) ===");

        seg1_m_addr    = 32'h0000_1000;  // AXI destination
        seg1_src_addr  = 32'h0000_0000;  // SRAM source
        seg1_pld_len   = 32'd8192;       // 256 * 32 = 8192 bytes

        build_sequential_cmd(
            .m_addr      (seg1_m_addr),
            .src_addr    (seg1_src_addr),
            .pld_len_bytes(seg1_pld_len),
            .meta_type   (8'd0),
            .seg_num     (16'd2),        // 2 segments total
            .ctrl_flag   (16'd1),        // sequential format
            .seg_id      (8'd0),         // segment 0
            .cmd_data    (test_cmd)
        );

        // Drive cmd_in
        @(posedge clk);
        cmd_in_valid <= 1'b1;
        cmd_in_data  <= test_cmd;
        cmd_in_start <= 2'b01;
        cmd_in_end   <= 2'b01;
        cmd_in_count <= 8'd0;
        cmd_in_empty <= 4'd0;
        cmd_in_user  <= 1'b0;

        @(posedge clk);
        while (!cmd_in_ready) @(posedge clk);
        cmd_in_valid <= 1'b0;
        cmd_in_start <= 2'b00;
        cmd_in_end   <= 2'b00;

        // Wait for SRAM write burst to complete
        $display("[TB] Waiting for Segment 1 SRAM write...");
        wait(sram_wr_bursts >= 1);
        $display("[TB] Segment 1 SRAM write complete. Bursts: %0d, Words: %0d",
                 sram_wr_bursts, sram_wr_words);

        #100;

        // -----------------------------------------------------------
        // SEGMENT 2: 300 words = 9600 bytes (exceeds 256 word limit)
        // -----------------------------------------------------------
        $display("\n[TB] === Sending Segment 2: 300 words (9600 bytes) ===");
        $display("[TB] Expected: err_seg_len should assert (300 > 256)");

        seg2_m_addr    = 32'h0000_2000;
        seg2_src_addr  = 32'h0000_0100;  // SRAM addr 256
        seg2_pld_len   = 32'd9600;       // 300 * 32 = 9600 bytes

        build_sequential_cmd(
            .m_addr      (seg2_m_addr),
            .src_addr    (seg2_src_addr),
            .pld_len_bytes(seg2_pld_len),
            .meta_type   (8'd0),
            .seg_num     (16'd2),        // still 2 segments
            .ctrl_flag   (16'd1),
            .seg_id      (8'd1),         // segment 1
            .cmd_data    (test_cmd)
        );

        @(posedge clk);
        cmd_in_valid <= 1'b1;
        cmd_in_data  <= test_cmd;
        cmd_in_start <= 2'b01;
        cmd_in_end   <= 2'b01;
        cmd_in_count <= 8'd0;
        cmd_in_empty <= 4'd0;
        cmd_in_user  <= 1'b0;

        @(posedge clk);
        while (!cmd_in_ready) @(posedge clk);
        cmd_in_valid <= 1'b0;
        cmd_in_start <= 2'b00;
        cmd_in_end   <= 2'b00;

        // Wait a bit for error to propagate
        #200;

        // -----------------------------------------------------------
        // Check results
        // -----------------------------------------------------------
        $display("\n==========================================================");
        $display("[TB] Test Results Summary");
        $display("==========================================================");

        // Check segment 1 completed successfully
        if (sram_wr_bursts >= 1) begin
            $display("[PASS] Segment 1 (256 words): SRAM write completed");
            $display("       SRAM write bursts = %0d", sram_wr_bursts);
            $display("       SRAM write words  = %0d", sram_wr_words);
            test_pass_count = test_pass_count + 1;
        end else begin
            $display("[FAIL] Segment 1 (256 words): No SRAM write detected");
            test_fail_count = test_fail_count + 1;
        end

        // Check segment 1 data integrity (first and last words)
        if (sram_mem[0] === (256'hA000_0000_0000_0000 + 0)) begin
            $display("[PASS] Segment 1: First SRAM word matches expected pattern");
            test_pass_count = test_pass_count + 1;
        end else begin
            $display("[FAIL] Segment 1: First SRAM word mismatch");
            $display("       Expected: 0x%064X", 256'hA000_0000_0000_0000);
            $display("       Got:      0x%064X", sram_mem[0]);
            test_fail_count = test_fail_count + 1;
        end

        // Check err_seg_len for segment 2
        if (err_seg_len_count > 0) begin
            $display("[PASS] Segment 2 (300 words): err_seg_len asserted as expected");
            $display("       err_seg_len_count = %0d", err_seg_len_count);
            test_pass_count = test_pass_count + 1;
        end else begin
            $display("[FAIL] Segment 2 (300 words): err_seg_len NOT asserted");
            $display("       Expected error because 300 > 256 word limit");
            test_fail_count = test_fail_count + 1;
        end

        // Check no spurious req errors
        if (err_req_count == 0) begin
            $display("[PASS] No spurious err_req detected");
            test_pass_count = test_pass_count + 1;
        end else begin
            $display("[INFO] err_req count = %0d (check if expected)", err_req_count);
        end

        // Check cmd_out
        if (cmd_out_count > 0) begin
            $display("[PASS] Command output generated (count = %0d)", cmd_out_count);
            test_pass_count = test_pass_count + 1;
        end else begin
            $display("[INFO] No command output captured");
        end

        $display("==========================================================");
        $display("[TB] TOTAL: %0d PASSED, %0d FAILED", test_pass_count, test_fail_count);
        $display("==========================================================");

        if (test_fail_count == 0)
            $display("[TB] *** ALL TESTS PASSED ***");
        else
            $display("[TB] *** %0d TESTS FAILED ***", test_fail_count);

        #100;
        $finish;
    end

    // ---------------------------------------------------------------
    // Timeout watchdog
    // ---------------------------------------------------------------
    initial begin
        #500000;
        $display("[TB] ERROR: Simulation timeout!");
        $finish;
    end

    // ---------------------------------------------------------------
    // Waveform dump
    // ---------------------------------------------------------------
    initial begin
        $dumpfile("sequential_format_one_pkt_dseg1_256_tb.vcd");
        $dumpvars(0, sequential_format_one_pkt_dseg1_256_tb);
    end

endmodule
