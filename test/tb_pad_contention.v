/*
 * tb_pad_contention - bidirectional uio pad model for the configuration hand-off.
 *
 * test/tb.v wires uio_in and uio_out as separate nets, so the cocotb suite can
 * only observe the output-enable timing: it can prove the chip does not drive
 * uio at the wrong moment, but it cannot model what happens on the pads when
 * the host and the chip drive at the same time.
 *
 * This testbench closes that gap. The host driver and the chip's uio_oe/uio_out
 * driver share one net, exactly as on a board, so a hand-off error shows up as
 * a contended (x) pad and a corrupted configuration word. It is a standalone
 * instrument and is deliberately NOT part of the cocotb build (test/Makefile
 * lists tb.v explicitly); see test/README.md for how to run it.
 *
 * History: this testbench found the F1 defect recorded in
 * docs/post-silicon-readiness-audit.md, where uio_oe was asserted from boot[1]
 * one clock before the configuration-commit edge.
 *
 * Expected result: no host/chip overlap during the three-edge configuration
 * window, the committed word equal to the word the host drove, and uio_oe high
 * once the chip has taken over the bus.
 *
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none `timescale 1ns / 1ps

module tb_pad_contention ();

  /* 100 ns period, the submitted 10 MHz operating point. */
  localparam real HALF = 50.0;

  reg clk = 0;
  reg rst_n = 0;
  reg ena = 1;
  reg [7:0] ui_in = 0;

  /* Host side: the controller's push-pull drivers, with an explicit enable.
     seg=(1,2,3,0) pat=1(worst) can_sel=2 win_sel=0 force_can=0 force_err=0. */
  localparam [15:0] CFG = 16'h09E7;
  reg [7:0] host_drv = 0;
  reg       host_oe = 1;

  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;
  wire [7:0] uio_in;
  wire [7:0] uio_pad;

  assign uio_pad = host_oe ? host_drv : 8'bz;
  assign uio_pad = uio_oe  ? uio_out  : 8'bz;
  assign uio_in  = uio_pad;

  tt_um_echoworld424_tpv dut (
      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (ena),
      .clk    (clk),
      .rst_n  (rst_n)
  );

  integer violations = 0;
  integer k;

  task tick;
    begin
      clk = 1; #(HALF);
      clk = 0; #(HALF);
    end
  endtask

  initial begin
    clk = 0;
    rst_n = 0;
    ui_in = CFG[7:0];
    host_drv = CFG[15:8];
    host_oe = 1;
    #7;

    /* Reset is asserted with the config word already driven. */
    for (k = 0; k < 4; k = k + 1) tick;

    /* Release reset during the clock LOW phase. */
    rst_n = 1;
    #2;

    /* Host contract: hold the configuration word through three rising edges.
       The configuration commits at the third; the chip must not drive before
       or on that edge. */
    for (k = 1; k <= 3; k = k + 1) begin
      clk = 1; #(HALF);
      if (host_oe && (uio_oe !== 8'h00)) begin
        $display("FAIL: host/chip contention at rising edge %0d (uio_oe=%b, pad=%b)",
                 k, uio_oe, uio_pad);
        violations = violations + 1;
      end
      clk = 0; #(HALF);
    end

    /* Host releases within the following clock period; the chip takes over. */
    host_oe = 0;
    ui_in = 8'h00;      /* ui[7] = FREEZE must be low while running */
    for (k = 0; k < 4; k = k + 1) tick;

    if (uio_oe !== 8'hFF) begin
      $display("FAIL: chip does not own uio after the hand-off (uio_oe=%b)", uio_oe);
      violations = violations + 1;
    end

    if (dut.cfg !== CFG) begin
      $display("FAIL: committed cfg = 0x%04h, host drove 0x%04h", dut.cfg, CFG);
      violations = violations + 1;
    end

    if (violations == 0) begin
      $display("PASS: cfg = 0x%04h committed with no host/chip pad contention", dut.cfg);
      $finish;
    end else begin
      $display("FAIL: %0d violation(s)", violations);
      $fatal(1);
    end
  end

endmodule
