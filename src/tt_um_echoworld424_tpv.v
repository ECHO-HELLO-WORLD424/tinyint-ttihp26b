/*
 * tt_um_echoworld424_tpv - Timing-Prediction Test Vehicle (IHP SG13G2, 1x1 tile)
 *
 * A self-checking arithmetic timing-failure experiment:
 *  - DUT: 16-bit ripple-carry adder with programmable carry delay banks.
 *  - Oracle: bit-serial reference adder (very short path), self-checking.
 *  - Canaries: generic and structure-matched ring oscillators with edge
 *    counters over a configurable window (delay telemetry).
 *  - Measurement: 19-cycle frames (FRAME_LAST=18, 0..18), error/op counters,
 *    first-error capture, serial byte readout with auto-incrementing pointer,
 *    freeze input.
 *
 * Pin protocol:
 *  - Reset/config phase (rst_n low): {uio_in, ui_in} = 16-bit config word,
 *    sampled into the config register at reset release. uio is an input.
 *  - Run phase: uio switches to output (status bus), uo shows the readout
 *    pointer and live flags. ui_in[7] = freeze (hold counters/read out).
 *
 * Config word (LSB = ui_in[0]):
 *  [1:0] seg0, [3:2] seg1, [5:4] seg2, [7:6] seg3 : DUT delay bank taps
 *  [9:8]  pattern (0=PRBS 1=WORST 2=ALT 3=HOLD)
 *  [11:10] canary sel (both RO canaries)
 *  [13:12] window sel (2^8/2^10/2^12/2^14 clk cycles)
 *  [14]  force canary count mask, [15] force DUT error (DFT)
 *
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 1ns / 1ps

module tt_um_echoworld424_tpv (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);
  localparam [4:0] FRAME_LAST = 5'd18;  /* frames are 19 cycles */

  /* ------------------------------------------------------------------ */
  /* Configuration (sampled while in reset, committed at reset release)  */
  /* ------------------------------------------------------------------ */
  reg  [15:0] cfg;
  reg  [15:0] cfg_sh;
  wire [15:0] cfg_word = {uio_in, ui_in};

  /* Boot counter: cfg commits once, at the boot==2 clock edge (race-free
     even when release coincides with a clock edge), then freezes. */
  reg  [1:0]  boot;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)                boot <= 2'd0;
    else if (boot != 2'd3)     boot <= boot + 2'd1;
  end

  /* Shadow samples the pins while boot < 3 (reset plus two cycles), so the
     host must hold the config word until three cycles after reset release.
     Gating with the boot register (not rst_n directly) avoids an
     enable-from-reset-signals structure that synthesis would mis-map. */
  always @(posedge clk) begin
    if (boot != 2'd3) cfg_sh <= cfg_word;
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)              cfg <= 16'h0000;
    else if (boot == 2'd2)   cfg <= cfg_sh;
  end

  wire [1:0] seg0 = cfg[1:0];
  wire [1:0] seg1 = cfg[3:2];
  wire [1:0] seg2 = cfg[5:4];
  wire [1:0] seg3 = cfg[7:6];
  wire [1:0] pat_sel   = cfg[9:8];
  wire [1:0] can_sel   = cfg[11:10];
  wire [1:0] win_sel   = cfg[13:12];
  wire       force_can = cfg[14];
  wire       force_err = cfg[15];

  /* Freeze input (run phase only; host holds ui_in[7] low while running). */
  wire freeze    = ui_in[7];
  wire update_en = ~freeze;   /* clock-enable for all measurement state */

  /* uio switches from config input to status output after reset release. */
  reg [1:0] oe_cnt;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)            oe_cnt <= 2'd0;
    else if (!oe_cnt[1])   oe_cnt <= oe_cnt + 2'd1;
  end
  assign uio_oe = {8{oe_cnt[1]}};

  /* ------------------------------------------------------------------ */
  /* Frame timing: one timed operation per 18 cycles                     */
  /* ------------------------------------------------------------------ */
  reg [4:0] frame_cnt;
  wire frame_boundary = (frame_cnt == FRAME_LAST);
  wire load           = frame_boundary & update_en;
  /* Hold the checker until the first real operand pair is loaded, so the
     reset-operand state is never measured and P(0) is the first checked op. */
  reg       started;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)   started <= 1'b0;
    else if (load) started <= 1'b1;
  end
  wire chk_start    = (frame_cnt == 5'd0) & update_en & started;
  wire frame_strobe = (frame_cnt == 5'd0);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)         frame_cnt <= 5'd0;
    else if (update_en) frame_cnt <= frame_boundary ? 5'd0 : frame_cnt + 5'd1;
  end

  /* ------------------------------------------------------------------ */
  /* DUT: pattern -> ripple-carry adder -> result register               */
  /* ------------------------------------------------------------------ */
  wire [15:0] pat_a;
  wire [15:0] pat_b;
  wire        pat_cin;

  tpv_pattern_gen u_pat (
    .clk (clk),
    .rst_n(rst_n),
    .load(load),
    .sel (pat_sel),
    .a   (pat_a),
    .b   (pat_b),
    .cin (pat_cin)
  );

  wire [15:0] rca_sum;
  wire        rca_cout;

  tpv_rca16 u_dut (
    .a      (pat_a),
    .b      (pat_b),
    .cin    (pat_cin),
    .seg_sel({seg3, seg2, seg1, seg0}),
    .sum    (rca_sum),
    .cout   (rca_cout)
  );

  /* One-shot DUT timing capture: result_reg samples the DUT exactly once per
     operation, on the chk_start edge (frame_cnt == 0, one cycle after the
     operand load, the first edge where the combinational result is sampled).
     It then holds that first sample until the checker comparison at the next
     frame boundary, so a timing-failed capture can never be overwritten by a
     later settled value. chk_start is gated by `started`, so the reset-operand
     state is never captured, and by update_en, so freeze holds the capture. */
  reg [16:0] result_reg;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)         result_reg <= 17'd0;
    else if (chk_start) result_reg <= {rca_cout, rca_sum} ^ {17{force_err}};
  end

  /* ------------------------------------------------------------------ */
  /* Oracle: bit-serial reference adder                                  */
  /* ------------------------------------------------------------------ */
  wire [16:0] chk_acc;
  wire        chk_done;

  tpv_checker u_chk (
    .clk  (clk),
    .rst_n(rst_n),
    .en   (update_en & started),  /* no free-running on reset operands */
    .start(chk_start),
    .a    (pat_a),
    .b    (pat_b),
    .cin  (pat_cin),
    .acc  (chk_acc),
    .done (chk_done)
  );

  /* The checker started on op k commits one cycle before the next boundary,
     so during the boundary cycle both chk_acc (correct sum of op k) and
     result_reg (captured DUT result of op k) are live and aligned: compare
     directly, with no hold pipelines. */
  wire dut_err = frame_boundary & chk_done & update_en & (chk_acc != result_reg);

  reg [15:0] err_cnt;
  reg        err_seen;
  reg [7:0]  err_dut_b;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      err_cnt   <= 16'd0;
      err_seen  <= 1'b0;
      err_dut_b <= 8'd0;
    end else if (dut_err) begin
      if (!err_seen) begin
        err_seen  <= 1'b1;
        err_dut_b <= result_reg[7:0];
      end
      if (!(&err_cnt)) err_cnt <= err_cnt + 16'd1;
    end
  end

  reg [15:0] ops_cnt;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) ops_cnt <= 16'd0;
    else if (frame_boundary && update_en && !(&ops_cnt)) ops_cnt <= ops_cnt + 16'd1;
  end

  /* ------------------------------------------------------------------ */
  /* Measurement window for the RO canaries                              */
  /* ------------------------------------------------------------------ */
  reg [15:0] win_cnt;
  reg        win_done;
  wire [15:0] win_thresh = (win_sel == 2'd0) ? 16'h00FF :
                           (win_sel == 2'd1) ? 16'h03FF :
                           (win_sel == 2'd2) ? 16'h0FFF :
                                               16'h3FFF;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      win_cnt  <= 16'd0;
      win_done <= 1'b0;
    end else if (update_en && !win_done) begin
      win_cnt <= win_cnt + 16'd1;
      if (win_cnt == win_thresh) win_done <= 1'b1;
    end
  end

  /* RO enable: gated until the boot completes (config committed, three
     cycles after reset release) so the async edge counters never tick with
     a stale mask, and frozen once the window completes. */
  wire ro_en = update_en & ~win_done & (boot == 2'd3);

  /* The RO loop nodes are intentionally circular (ring oscillators). */
  /* verilator lint_off UNOPTFLAT */
  wire        gen_node;
  wire        mat_node;
  /* verilator lint_on UNOPTFLAT */
  reg [9:0] gen_cnt;
  reg [9:0] mat_cnt;

  tpv_ro_gen u_ro_gen (
    .rst_n  (rst_n),
    .en     (ro_en),
    .sel    (can_sel),
    .mask   (force_can),
    .ro_node(gen_node),
    .cnt    (gen_cnt)
  );

  tpv_ro_match u_ro_mat (
    .rst_n  (rst_n),
    .en     (ro_en),
    .sel    (can_sel),
    .mask   (force_can),
    .ro_node(mat_node),
    .cnt    (mat_cnt)
  );

  wire gen_dead = win_done & (gen_cnt == 10'd0);
  wire mat_dead = win_done & (mat_cnt == 10'd0);

  /* ------------------------------------------------------------------ */
  /* Serial status readout (uio = data byte, uo[3:0] = pointer)          */
  /* ------------------------------------------------------------------ */
  reg [3:0] ro_ptr;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) ro_ptr <= 4'd0;
    else        ro_ptr <= ro_ptr + 4'd1;
  end

  reg [7:0] ro_byte;
  always @* begin
    case (ro_ptr)
      4'd0:    ro_byte = err_cnt[7:0];
      4'd1:    ro_byte = err_cnt[15:8];
    4'd2:    ro_byte = gen_cnt[7:0];
    4'd3:    ro_byte = {6'b0, gen_cnt[9:8]};
    4'd4:    ro_byte = mat_cnt[7:0];
    4'd5:    ro_byte = {6'b0, mat_cnt[9:8]};
      4'd6:    ro_byte = ops_cnt[7:0];
      4'd7:    ro_byte = ops_cnt[15:8];
      4'd8:    ro_byte = {seg3, seg2, seg1, seg0};
      4'd9:    ro_byte = {1'b1, mat_dead, gen_dead, err_seen, can_sel, win_sel};
      4'd10:   ro_byte = err_dut_b;
      4'd11:   ro_byte = 8'h00;
      default: ro_byte = 8'h00;
    endcase
  end

  assign uio_out = ro_byte;
  assign uo_out  = {frame_strobe, mat_dead, gen_dead, dut_err, ro_ptr};

  /* List all unused inputs to prevent warnings */
  wire _unused = &{ena, gen_node, mat_node, 1'b0};

endmodule
