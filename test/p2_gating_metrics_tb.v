/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Gating-activity metrics testbench for the ICG clock-gating proposal.
// Drives the 8192-MAC mixed stream through the variant core once per mode
// (conventional / dynamic-8 / dynamic-12 / dynamic-16) and reports, per run:
//   * total window cycles and cycles each bank ICG GATE is high,
//   * GCLK rising edges per gated clock (bank ICGs and cold-stage ICGs),
//   * stage-2/3/4 write events,
//   * per-nibble state toggles,
//   * clock-edge reduction per FF group versus the always-clocked baseline
//     (baseline clock pin = 2 toggle edges per MAC; the reduction ratio is
//     identical on posedge-only counts).
// A 20-bit golden accumulator (modulo add + sticky overflow) checks the
// core's accumulator_value/accumulator_overflow outputs every window cycle,
// so the metrics run is self-checking.
module p2_gating_metrics_tb;

  localparam [2:0] COMMAND_FINISH   = 3'b000;
  localparam [2:0] COMMAND_CLEAR    = 3'b001;
  localparam [2:0] COMMAND_MAC      = 3'b010;
  localparam [2:0] COMMAND_MAC_LAST = 3'b011;
  localparam [2:0] COMMAND_READ     = 3'b100;

  reg clk = 1'b0;
  reg rst_n = 1'b1;

  reg        request_valid = 1'b0;
  reg [2:0]  request_command = 3'b000;
  reg [7:0]  request_data = 8'h00;
  reg        request_signed_mode = 1'b0;
  reg        request_from_bist = 1'b0;

  wire        request_ready;
  wire [7:0]  multiplier_product;
  wire [19:0] extended_product;
  wire [19:0] accumulator_value;
  wire        latched_signed_mode;
  wire [7:0]  response_data;
  wire        response_valid;
  wire [7:0]  pair_count;
  wire        done;
  wire [7:0]  last_product;
  wire        accumulator_overflow;
  wire        count_overflow;
  wire        protocol_error;

  tiny_int_core dut (
      .clk                 (clk),
      .rst_n               (rst_n),
      .request_valid       (request_valid),
      .request_ready       (request_ready),
      .request_command     (request_command),
      .request_data        (request_data),
      .request_signed_mode (request_signed_mode),
      .request_from_bist   (request_from_bist),
      .multiplier_product  (multiplier_product),
      .extended_product    (extended_product),
      .accumulator_value   (accumulator_value),
      .latched_signed_mode (latched_signed_mode),
      .response_data       (response_data),
      .response_valid      (response_valid),
      .pair_count          (pair_count),
      .done                (done),
      .last_product        (last_product),
      .accumulator_overflow(accumulator_overflow),
      .count_overflow      (count_overflow),
      .protocol_error      (protocol_error)
  );

  always #10 clk = ~clk;

  // Hierarchical probes into the gated banks.
  wire conv_gate = dut.conventional_bank_gclk_en;
  wire dyn_gate  = dut.dynamic_bank_gclk_en;
  wire [4:2] dyn_stage_gate = dut.dynamic_stage_gclk_en;
  wire conv_bank_gclk = dut.conventional_accumulator.bank_gclk;
  wire dyn_bank_gclk  = dut.dynamic_accumulator.bank_gclk;
  wire stage_2_gclk   = dut.dynamic_accumulator.stage_2_gclk;
  wire stage_3_gclk   = dut.dynamic_accumulator.stage_3_gclk;
  wire stage_4_gclk   = dut.dynamic_accumulator.stage_4_gclk;
  wire [3:0] nibble_0 = dut.dynamic_accumulator.stage_0;
  wire [3:0] nibble_1 = dut.dynamic_accumulator.stage_1;
  wire [3:0] nibble_2 = dut.dynamic_accumulator.stage_2;
  wire [3:0] nibble_3 = dut.dynamic_accumulator.stage_3;
  wire [3:0] nibble_4 = dut.dynamic_accumulator.stage_4;
  // Full-vector hierarchical reference (iverilog part-selects of
  // hierarchical references do not track the source signal reliably).
  wire [4:0] dyn_stage_we_full = dut.dynamic_accumulator.stage_write_enable;
  wire [2:0] dyn_stage_we = dyn_stage_we_full[4:2];

  // GCLK rising-edge counters (delta-sampled around each window).
  integer conv_gclk_edges = 0;
  integer dyn_gclk_edges = 0;
  integer s2_gclk_edges = 0;
  integer s3_gclk_edges = 0;
  integer s4_gclk_edges = 0;

  always @(posedge conv_bank_gclk) conv_gclk_edges = conv_gclk_edges + 1;
  always @(posedge dyn_bank_gclk)  dyn_gclk_edges  = dyn_gclk_edges + 1;
  always @(posedge stage_2_gclk)   s2_gclk_edges   = s2_gclk_edges + 1;
  always @(posedge stage_3_gclk)   s3_gclk_edges   = s3_gclk_edges + 1;
  always @(posedge stage_4_gclk)   s4_gclk_edges   = s4_gclk_edges + 1;

  // Per-window sampled metrics (negedge-sampled, so no edge races).
  integer conv_gate_cycles = 0;
  integer dyn_gate_cycles = 0;
  integer s2_writes = 0;
  integer s3_writes = 0;
  integer s4_writes = 0;
  integer nibble_flips [0:4];
  reg [3:0] prev_nibble [0:4];
  reg in_window = 1'b0;

  // Golden accumulator model for functional self-checking.
  reg [19:0] golden_acc = 20'b0;
  reg        golden_ovf = 1'b0;
  integer errors = 0;
  integer checked = 0;

  integer window_cycles = 0;

  // Mirror of the core product path for the golden model.
  reg  [7:0] golden_data = 8'h00;
  reg        golden_signed = 1'b0;
  wire [7:0] golden_product;
  wire [19:0] golden_addend;
  int4_multiplier golden_multiplier (
      .multiplicand(golden_data[3:0]),
      .multiplier  (golden_data[7:4]),
      .signed_mode (golden_signed),
      .product     (golden_product)
  );
  product_extender golden_extender (
      .product         (golden_product),
      .signed_mode     (golden_signed),
      .extended_product(golden_addend)
  );

  function [2:0] popcount4;
    input [3:0] v;
    begin
      popcount4 = {2'b0, v[0]} + {2'b0, v[1]} + {2'b0, v[2]} + {2'b0, v[3]};
    end
  endfunction

  function [3:0] nibble_value;
    input integer k;
    begin
      case (k)
        0: nibble_value = nibble_0;
        1: nibble_value = nibble_1;
        2: nibble_value = nibble_2;
        3: nibble_value = nibble_3;
        default: nibble_value = nibble_4;
      endcase
    end
  endfunction

  task sample_metrics;
    integer k;
    begin
      if (in_window) begin
        window_cycles = window_cycles + 1;
        if (conv_gate) conv_gate_cycles = conv_gate_cycles + 1;
        if (dyn_gate)  dyn_gate_cycles  = dyn_gate_cycles + 1;
        if (dyn_stage_we_full[2]) s2_writes = s2_writes + 1;
        if (dyn_stage_we_full[3]) s3_writes = s3_writes + 1;
        if (dyn_stage_we_full[4]) s4_writes = s4_writes + 1;
        for (k = 0; k <= 4; k = k + 1) begin
          nibble_flips[k] = nibble_flips[k] +
              popcount4(nibble_value(k) ^ prev_nibble[k]);
          prev_nibble[k] = nibble_value(k);
        end
      end
    end
  endtask

  // ---- stimulus helpers -------------------------------------------------

  task drive_cycle;
    input       rv;
    input [2:0] rc;
    input [7:0] rd;
    input       rsm;
    begin
      @(negedge clk);
      request_valid       <= rv;
      request_command     <= rc;
      request_data        <= rd;
      request_signed_mode <= rsm;
      request_from_bist   <= 1'b0;
      #1;
      sample_metrics;
      check_golden(rv, rc);
      @(posedge clk);
    end
  endtask

  task check_golden;
    input       rv;
    input [2:0] rc;
    reg [20:0] full;
    reg        event_ofl;
    begin
      if (!in_window) begin
        golden_acc  = 20'b0;
        golden_ovf  = 1'b0;
      end else if (rv && (rc == COMMAND_MAC) && !done) begin
        // Every window MAC is accepted (no zero-skip, no done, always ready).
        // Compare against the core first: at this sample point the core
        // output reflects every MAC committed so far, including this one's
        // predecessor but not this one (it commits at the upcoming posedge).
        checked = checked + 1;
        if ((accumulator_value !== golden_acc) ||
            (accumulator_overflow !== golden_ovf)) begin
          errors = errors + 1;
          if (errors < 20) begin
            $display("GOLDEN MISMATCH cycle-window %0d: av=%h (want %h) ovf=%b (want %b)",
                     window_cycles, accumulator_value, golden_acc,
                     accumulator_overflow, golden_ovf);
          end
        end
        full = {1'b0, golden_acc} + {1'b0, golden_addend};
        if (golden_signed) begin
          event_ofl = (golden_acc[19] == golden_addend[19]) &&
                      (full[19] != golden_acc[19]);
        end else begin
          event_ofl = full[20];
        end
        golden_acc = full[19:0];
        golden_ovf = golden_ovf | event_ofl;
      end
    end
  endtask

  // The 8192-MAC mixed stream (identical definition to the other TBs).
  function [7:0] mixed_data;
    input integer i;
    input [15:0] lfsr;
    begin
      if (i < 2048)       mixed_data = {lfsr[7:4], lfsr[3:0]};
      else if (i < 4096)  mixed_data = ((i & 3) == 0) ? {i[3:0], i[7:4]}
                                                      : 8'h00;
      else if (i < 6144)  mixed_data = i[0] ? 8'hf1 : 8'h71;
      else                mixed_data = {i[7:4], i[3:0]};
    end
  endfunction

  // ---- per-mode measurement run -----------------------------------------

  integer conv_gclk_snap, dyn_gclk_snap, s2_snap, s3_snap, s4_snap;
  integer mode_conv_gclk, mode_dyn_gclk, mode_s2, mode_s3, mode_s4;
  integer mode_window, mode_conv_gate, mode_dyn_gate;
  integer mode_s2w, mode_s3w, mode_s4w;
  integer mode_flips [0:4];

  task measure_mode;
    input [1:0] mode;
    integer i;
    reg [7:0] d;
    reg [15:0] lfsr;
    integer k;
    begin
      // Configure the mode (outside every measurement window).
      @(negedge clk);
      request_valid       <= 1'b1;
      request_command     <= COMMAND_CLEAR;
      request_data        <= {5'b00000, 1'b0, mode};
      request_signed_mode <= 1'b0;
      golden_signed       = 1'b0;
      #1;
      @(posedge clk);
      drive_cycle(1'b0, 3'b000, 8'h00, 1'b0);  // idle separator

      // Snapshot counters at a settled point (no edges between here and the
      // first MAC's posedge: the gates are closed on the idle separator).
      conv_gclk_snap = conv_gclk_edges;
      dyn_gclk_snap  = dyn_gclk_edges;
      s2_snap = s2_gclk_edges;
      s3_snap = s3_gclk_edges;
      s4_snap = s4_gclk_edges;
      mode_conv_gate = 0; mode_dyn_gate = 0;
      mode_s2w = 0; mode_s3w = 0; mode_s4w = 0;
      mode_window = 0;
      for (k = 0; k <= 4; k = k + 1) begin
        nibble_flips[k] = 0;
        prev_nibble[k]  = nibble_value(k);
      end

      // ---- measured window: 8192 back-to-back MACs ----
      lfsr = 16'h1ace;
      in_window = 1'b1;
      for (i = 0; i < 8192; i = i + 1) begin
        d = mixed_data(i, lfsr);
        if (i < 2048) begin
          lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        end
        golden_data = d;
        drive_cycle(1'b1, COMMAND_MAC, d, 1'b0);
      end
      in_window = 1'b0;
      // One gates-closed idle cycle: every window GCLK edge has now landed
      // in the counters, so the delta reads below are race-free.
      drive_cycle(1'b0, 3'b000, 8'h00, 1'b0);

      mode_window     = window_cycles;
      mode_conv_gate  = conv_gate_cycles;
      mode_dyn_gate   = dyn_gate_cycles;
      mode_conv_gclk  = conv_gclk_edges - conv_gclk_snap;
      mode_dyn_gclk   = dyn_gclk_edges - dyn_gclk_snap;
      mode_s2 = s2_gclk_edges - s2_snap;
      mode_s3 = s3_gclk_edges - s3_snap;
      mode_s4 = s4_gclk_edges - s4_snap;
      mode_s2w = s2_writes; mode_s3w = s3_writes; mode_s4w = s4_writes;
      for (k = 0; k <= 4; k = k + 1) begin
        mode_flips[k] = nibble_flips[k];
      end

      // Terminate the transaction so the next CLEAR starts clean.
      drive_cycle(1'b1, COMMAND_MAC_LAST, 8'h00, 1'b0);
      drive_cycle(1'b1, COMMAND_FINISH, 8'h00, 1'b0);
      drive_cycle(1'b0, 3'b000, 8'h00, 1'b0);

      print_report(mode);
      window_cycles = 0;
      conv_gate_cycles = 0; dyn_gate_cycles = 0;
      s2_writes = 0; s3_writes = 0; s4_writes = 0;
    end
  endtask

  function integer pct;
    input integer part;
    input integer whole;
    begin
      if (whole == 0) pct = 0;
      else pct = (1000 * part) / whole;  // tenths of a percent
    end
  endfunction

  task print_report;
    input [1:0] mode;
    reg [136:1] name;
    integer base_posedges;
    begin
      case (mode)
        2'b00: name = "conventional";
        2'b01: name = "dynamic-8  ";
        2'b10: name = "dynamic-12 ";
        default: name = "dynamic-16 ";
      endcase
      $display("");
      $display("=== mode %b (%0s): %0d window cycles ===",
               mode, name, mode_window);
      $display("bank GATE high cycles: conventional %0d (%0d.%0d%%), dynamic %0d (%0d.%0d%%)",
               mode_conv_gate, pct(mode_conv_gate, mode_window) / 10,
               pct(mode_conv_gate, mode_window) % 10,
               mode_dyn_gate, pct(mode_dyn_gate, mode_window) / 10,
               pct(mode_dyn_gate, mode_window) % 10);
      $display("GCLK rising edges: conv bank %0d, dyn bank %0d, stage2 %0d, stage3 %0d, stage4 %0d",
               mode_conv_gclk, mode_dyn_gclk, mode_s2, mode_s3, mode_s4);
      $display("stage write events: stage2 %0d, stage3 %0d, stage4 %0d",
               mode_s2w, mode_s3w, mode_s4w);
      $display("per-nibble bit toggles: s0 %0d, s1 %0d, s2 %0d, s3 %0d, s4 %0d",
               mode_flips[0], mode_flips[1], mode_flips[2],
               mode_flips[3], mode_flips[4]);
      base_posedges = mode_window;  // baseline: 1 posedge (2 toggles)/cycle
      $display("clock-edge reduction vs always-on baseline (2 toggles per FF per MAC):");
      $display("  conv bank (21 FFs)      : %0d.%0d%%  (%0d/%0d posedges)",
               pct(base_posedges - mode_conv_gclk, base_posedges) / 10,
               pct(base_posedges - mode_conv_gclk, base_posedges) % 10,
               mode_conv_gclk, base_posedges);
      $display("  dyn s0+s1+ovf (9 FFs)   : %0d.%0d%%  (%0d/%0d posedges)",
               pct(base_posedges - mode_dyn_gclk, base_posedges) / 10,
               pct(base_posedges - mode_dyn_gclk, base_posedges) % 10,
               mode_dyn_gclk, base_posedges);
      $display("  dyn stage2 (4 FFs)      : %0d.%0d%%  (%0d/%0d posedges)",
               pct(base_posedges - mode_s2, base_posedges) / 10,
               pct(base_posedges - mode_s2, base_posedges) % 10,
               mode_s2, base_posedges);
      $display("  dyn stage3 (4 FFs)      : %0d.%0d%%  (%0d/%0d posedges)",
               pct(base_posedges - mode_s3, base_posedges) / 10,
               pct(base_posedges - mode_s3, base_posedges) % 10,
               mode_s3, base_posedges);
      $display("  dyn stage4 (4 FFs)      : %0d.%0d%%  (%0d/%0d posedges)",
               pct(base_posedges - mode_s4, base_posedges) / 10,
               pct(base_posedges - mode_s4, base_posedges) % 10,
               mode_s4, base_posedges);

      // Design-intent checks: an unselected bank's clock never opens during
      // a pure MAC stream, and cold stages only clock on real events.
      if (mode == 2'b00) begin
        if (mode_dyn_gclk != 0 || mode_s2 != 0 || mode_s3 != 0 ||
            mode_s4 != 0) begin
          errors = errors + 1;
          $display("FAIL: dynamic bank clocked while conventional selected");
        end
      end else begin
        if (mode_conv_gclk != 0) begin
          errors = errors + 1;
          $display("FAIL: conventional bank clocked while dynamic selected");
        end
        if (mode_s2 != mode_s2w || mode_s3 != mode_s3w ||
            mode_s4 != mode_s4w) begin
          errors = errors + 1;
          $display("FAIL: stage GCLK edge count != stage write event count");
        end
      end
    end
  endtask

  integer mi;
  initial begin
    nibble_flips[0] = 0; nibble_flips[1] = 0; nibble_flips[2] = 0;
    nibble_flips[3] = 0; nibble_flips[4] = 0;
    prev_nibble[0] = 4'h0; prev_nibble[1] = 4'h0; prev_nibble[2] = 4'h0;
    prev_nibble[3] = 4'h0; prev_nibble[4] = 4'h0;

    // Asynchronous reset entry: a real 1 -> 0 negedge at time zero.
    rst_n = 1'b0;
    repeat (3) begin
      @(negedge clk);
      #1;
      @(posedge clk);
    end
    rst_n = 1'b1;
    @(negedge clk);
    request_valid <= 1'b0;
    #1;
    @(posedge clk);

    $display("P2 ICG gating-activity metrics (mixed stream, 8192 MACs per mode, zero-skip off)");

    measure_mode(2'b00);  // conventional
    measure_mode(2'b01);  // dynamic-8
    measure_mode(2'b10);  // dynamic-12
    measure_mode(2'b11);  // dynamic-16

    if (errors == 0) begin
      $display("");
      $display("PASS: p2_gating_metrics_tb — golden accumulator exact over %0d checked MACs, all gating-intent checks passed",
               checked);
      $finish;
    end else begin
      $display("");
      $display("FAIL: p2_gating_metrics_tb — %0d errors over %0d checked MACs",
               errors, checked);
      $fatal(1, "p2_gating_metrics_tb failed");
    end
  end

endmodule

`default_nettype wire
