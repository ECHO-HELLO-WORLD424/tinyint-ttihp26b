/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Accumulator-level equivalence testbench for the ICG clock-gating proposal.
// Runs the baseline tiny_int_accumulator / tiny_int_dynamic_accumulator side
// by side with their *_icg clock-gated variants, drives identical inputs and
// compares EVERY output port every cycle, bit-exact, including through
// clear/load/reset. Also sanity-checks the exported GATE signals and that an
// async reset reaches the FFs while every gate is closed (no clock edge).
//
// Workloads: the 8192-MAC mixed stream (four quarters), 4096 MACs of 8'hff
// unsigned, 4096 MACs of 8'h11 signed, and random clear/load injection, over
// all four accumulator modes and both signedness settings.
module p2_acc_equiv_tb;

  reg clk = 1'b0;
  reg clk_en = 1'b1;
  reg rst_n = 1'b1;  // deasserted first; the initial block creates the
                     // asynchronous negedge the FF resets need.

  reg        clear = 1'b0;
  reg        load = 1'b0;
  reg        accumulate = 1'b0;
  reg        signed_mode = 1'b0;
  reg [1:0]  accumulator_mode = 2'b00;
  reg [19:0] load_value = 20'b0;
  reg        bank_select = 1'b1;

  // Shared product path: identical addends reach all four accumulators.
  reg  [7:0] raw_data = 8'h00;
  wire [7:0] product;
  wire [19:0] addend;

  int4_multiplier multiplier_u (
      .multiplicand(raw_data[3:0]),
      .multiplier  (raw_data[7:4]),
      .signed_mode (signed_mode),
      .product     (product)
  );
  product_extender extender_u (
      .product         (product),
      .signed_mode     (signed_mode),
      .extended_product(addend)
  );

  // Conventional pair.
  wire [19:0] ref_conv_value;
  wire [19:0] ref_conv_result;
  wire        ref_conv_carry;
  wire        ref_conv_ofl_event;
  wire        ref_conv_ofl;
  wire [19:0] dut_conv_value;
  wire [19:0] dut_conv_result;
  wire        dut_conv_carry;
  wire        dut_conv_ofl_event;
  wire        dut_conv_ofl;
  wire        dut_conv_gclk_en;

  tiny_int_accumulator ref_conv (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (accumulate),
      .signed_mode         (signed_mode),
      .load_value          (load_value),
      .addend              (addend),
      .accumulator_value   (ref_conv_value),
      .addition_result     (ref_conv_result),
      .addition_carry      (ref_conv_carry),
      .addition_overflow   (ref_conv_ofl_event),
      .accumulator_overflow(ref_conv_ofl)
  );

  tiny_int_accumulator_icg dut_conv (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (accumulate),
      .signed_mode         (signed_mode),
      .load_value          (load_value),
      .addend              (addend),
      .accumulator_value   (dut_conv_value),
      .addition_result     (dut_conv_result),
      .addition_carry      (dut_conv_carry),
      .addition_overflow   (dut_conv_ofl_event),
      .accumulator_overflow(dut_conv_ofl),
      .bank_select         (bank_select),
      .bank_gclk_en        (dut_conv_gclk_en)
  );

  // Dynamic pair.
  wire [19:0] ref_dyn_value;
  wire [19:0] ref_dyn_result;
  wire        ref_dyn_carry;
  wire        ref_dyn_ofl_event;
  wire        ref_dyn_ofl;
  wire [4:0]  ref_dyn_stage_we;
  wire [19:0] dut_dyn_value;
  wire [19:0] dut_dyn_result;
  wire        dut_dyn_carry;
  wire        dut_dyn_ofl_event;
  wire        dut_dyn_ofl;
  wire [4:0]  dut_dyn_stage_we;
  wire        dut_dyn_gclk_en;
  wire [4:2]  dut_dyn_stage_gclk_en;

  tiny_int_dynamic_accumulator ref_dyn (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (accumulate),
      .signed_mode         (signed_mode),
      .accumulator_mode    (accumulator_mode),
      .load_value          (load_value),
      .addend              (addend),
      .accumulator_value   (ref_dyn_value),
      .addition_result     (ref_dyn_result),
      .addition_carry      (ref_dyn_carry),
      .addition_overflow   (ref_dyn_ofl_event),
      .accumulator_overflow(ref_dyn_ofl),
      .stage_write_enable  (ref_dyn_stage_we)
  );

  tiny_int_dynamic_accumulator_icg dut_dyn (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (accumulate),
      .signed_mode         (signed_mode),
      .accumulator_mode    (accumulator_mode),
      .load_value          (load_value),
      .addend              (addend),
      .accumulator_value   (dut_dyn_value),
      .addition_result     (dut_dyn_result),
      .addition_carry      (dut_dyn_carry),
      .addition_overflow   (dut_dyn_ofl_event),
      .accumulator_overflow(dut_dyn_ofl),
      .stage_write_enable  (dut_dyn_stage_we),
      .bank_gclk_en        (dut_dyn_gclk_en),
      .stage_gclk_en       (dut_dyn_stage_gclk_en)
  );

  always #5 clk = clk_en ? ~clk : clk;

  integer errors = 0;
  integer checks = 0;
  integer cycle = 0;
  integer mismatch_prints = 0;
  integer seed = 32'h1ace_5eed;

  task report_mismatch;
    input [95:0]  what;
    input [31:0]  expected;
    input [31:0]  actual;
    begin
      errors = errors + 1;
      if (mismatch_prints < 30) begin
        mismatch_prints = mismatch_prints + 1;
        $display("MISMATCH cycle %0d %0s: expected %h got %h",
                 cycle, what, expected, actual);
      end
    end
  endtask

  // Compare every output port of both pairs plus the exported GATE signals.
  task check_outputs;
    integer k;
    begin
      checks = checks + 1;

      if (ref_conv_value !== dut_conv_value)
        report_mismatch("conv.value", {4'b0, ref_conv_value},
                        {4'b0, dut_conv_value});
      if (ref_conv_result !== dut_conv_result)
        report_mismatch("conv.result", {4'b0, ref_conv_result},
                        {4'b0, dut_conv_result});
      if (ref_conv_carry !== dut_conv_carry)
        report_mismatch("conv.carry", {31'b0, ref_conv_carry},
                        {31'b0, dut_conv_carry});
      if (ref_conv_ofl_event !== dut_conv_ofl_event)
        report_mismatch("conv.ofl_event", {31'b0, ref_conv_ofl_event},
                        {31'b0, dut_conv_ofl_event});
      if (ref_conv_ofl !== dut_conv_ofl)
        report_mismatch("conv.ofl", {31'b0, ref_conv_ofl},
                        {31'b0, dut_conv_ofl});

      if (ref_dyn_value !== dut_dyn_value)
        report_mismatch("dyn.value", {4'b0, ref_dyn_value},
                        {4'b0, dut_dyn_value});
      if (ref_dyn_result !== dut_dyn_result)
        report_mismatch("dyn.result", {4'b0, ref_dyn_result},
                        {4'b0, dut_dyn_result});
      if (ref_dyn_carry !== dut_dyn_carry)
        report_mismatch("dyn.carry", {31'b0, ref_dyn_carry},
                        {31'b0, dut_dyn_carry});
      if (ref_dyn_ofl_event !== dut_dyn_ofl_event)
        report_mismatch("dyn.ofl_event", {31'b0, ref_dyn_ofl_event},
                        {31'b0, dut_dyn_ofl_event});
      if (ref_dyn_ofl !== dut_dyn_ofl)
        report_mismatch("dyn.ofl", {31'b0, ref_dyn_ofl},
                        {31'b0, dut_dyn_ofl});
      if (ref_dyn_stage_we !== dut_dyn_stage_we)
        report_mismatch("dyn.stage_we", {3'b0, ref_dyn_stage_we},
                        {3'b0, dut_dyn_stage_we});

      // GATE observability: the bank gate must be exactly
      // bank-selected accumulate|clear|load; the stage gates exactly
      // clear|load|stage_write_enable[k].
      if (dut_conv_gclk_en !==
          (bank_select & (accumulate | clear | load)))
        report_mismatch("conv.gate",
            {31'b0, bank_select & (accumulate | clear | load)},
            {31'b0, dut_conv_gclk_en});
      if (dut_dyn_gclk_en !== (accumulate | clear | load))
        report_mismatch("dyn.gate",
            {31'b0, accumulate | clear | load},
            {31'b0, dut_dyn_gclk_en});
      for (k = 2; k <= 4; k = k + 1) begin
        if (dut_dyn_stage_gclk_en[k] !==
            (clear | load | dut_dyn_stage_we[k]))
          report_mismatch("dyn.stage_gate",
              {30'b0, clear | load | dut_dyn_stage_we[k]},
              {30'b0, dut_dyn_stage_gclk_en[k]});
      end
    end
  endtask

  // Drive one cycle of identical inputs to both members of each pair.
  task drive_cycle;
    input        c;
    input        l;
    input        a;
    input [7:0]  d;
    input [19:0] lval;
    input        sm;
    input [1:0]  am;
    input        bs;
    begin
      @(negedge clk);
      clear            <= c;
      load             <= l;
      accumulate       <= a;
      raw_data         <= d;
      load_value       <= lval;
      signed_mode      <= sm;
      accumulator_mode <= am;
      bank_select      <= bs;
      #1;
      check_outputs;
      @(posedge clk);
      cycle = cycle + 1;
    end
  endtask

  // Async reset asserted while the clock is frozen and every GATE is closed:
  // the FFs must still clear, proving reset reaches them without the clock.
  task frozen_clock_reset_check;
    begin
      // Warm up nonzero state on the live clock first so the check is real.
      drive_cycle(1'b0, 1'b0, 1'b1, 8'h3c, 20'b0, 1'b0, 2'b01, 1'b1);
      drive_cycle(1'b0, 1'b0, 1'b1, 8'h3c, 20'b0, 1'b0, 2'b01, 1'b1);
      if (dut_conv_value === 20'b0 || dut_dyn_value === 20'b0) begin
        $display("WARNING: warm-up state unexpected at cycle %0d", cycle);
      end
      @(negedge clk);
      clear       <= 1'b0;
      load        <= 1'b0;
      accumulate  <= 1'b0;
      bank_select <= 1'b0;  // close the conventional bank gate
      clk_en      <= 1'b0;  // freeze the raw clock (gates closed everywhere)
      #2;
      rst_n <= 1'b0;        // async reset with no clock edge at all
      #6;
      #1;
      check_outputs;
      if (dut_conv_value !== 20'b0 || dut_dyn_value !== 20'b0 ||
          dut_conv_ofl !== 1'b0 || dut_dyn_ofl !== 1'b0) begin
        report_mismatch("frozen_reset", 32'b0, 32'hdead_beef);
      end
      rst_n <= 1'b1;
      #4;
      clk_en <= 1'b1;
      drive_cycle(1'b0, 1'b0, 1'b0, 8'h00, 20'b0, 1'b0, 2'b01, 1'b1);
    end
  endtask

  // The 8192-MAC mixed stream: four quarters with distinct data profiles.
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

  // One pass of the mixed stream. Random clear/load injection interleaves
  // with the accumulate flow (weights: accumulate 254/256, clear 1/256,
  // load 1/256).
  task run_mixed_stream;
    input       sm;
    input [1:0] am;
    input       inject;
    integer i;
    reg [15:0] lfsr;
    reg [7:0] d;
    reg [7:0] dice;
    begin
      lfsr = 16'h1ace;
      for (i = 0; i < 8192; i = i + 1) begin
        d = mixed_data(i, lfsr);
        if (i < 2048) begin
          lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        end
        dice = inject ? ($random(seed) & 8'hff) : 8'h00;
        if (dice == 8'h55) begin
          drive_cycle(1'b1, 1'b0, 1'b0, d, 20'b0, sm, am, 1'b1);
        end else if (dice == 8'haa) begin
          drive_cycle(1'b0, 1'b1, 1'b0, d,
                      $random(seed), sm, am, 1'b1);
        end else begin
          drive_cycle(1'b0, 1'b0, 1'b1, d, 20'b0, sm, am, 1'b1);
        end
      end
    end
  endtask

  // Constant-product streams.
  task run_const_stream;
    input [7:0] d;
    input       sm;
    input [1:0] am;
    integer i;
    begin
      for (i = 0; i < 4096; i = i + 1) begin
        drive_cycle(1'b0, 1'b0, 1'b1, d, 20'b0, sm, am, 1'b1);
      end
    end
  endtask

  // Random control fuzz: accumulate/clear/load/idle with random modes,
  // signedness, load values and data.
  task run_random_phase;
    integer i;
    integer dice;
    reg [7:0] d;
    begin
      for (i = 0; i < 8192; i = i + 1) begin
        dice = $random(seed);
        d = $random(seed);
        case (dice & 3)
          0: drive_cycle(1'b1, 1'b0, 1'b0, d, 20'b0,
                         $random(seed), $random(seed), 1'b1);
          1: drive_cycle(1'b0, 1'b1, 1'b0, d, $random(seed),
                         $random(seed), $random(seed), 1'b1);
          2: drive_cycle(1'b0, 1'b0, 1'b1, d, 20'b0,
                         $random(seed), $random(seed), 1'b1);
          default: drive_cycle(1'b0, 1'b0, 1'b0, d, 20'b0,
                         $random(seed), $random(seed), 1'b1);
        endcase
      end
    end
  endtask

  // Deselected-bank hold check for the conventional bank: with bank_select=0
  // the ICG clock stops; outputs must hold even while the addend toggles.
  task run_bank_select_phase;
    integer i;
    reg [7:0] d;
    begin
      // Put a known nonzero value into the conventional bank first.
      drive_cycle(1'b1, 1'b0, 1'b0, 8'h00, 20'b0, 1'b0, 2'b00, 1'b1);
      run_const_stream(8'h21, 1'b0, 2'b00);
      drive_cycle(1'b0, 1'b0, 1'b0, 8'h00, 20'b0, 1'b0, 2'b00, 1'b1);
      for (i = 0; i < 32; i = i + 1) begin
        d = $random(seed);
        drive_cycle(1'b0, 1'b0, 1'b0, d, 20'b0, 1'b0, 2'b00, 1'b0);
      end
      // Back to selected: the bank resumes accumulating normally.
      drive_cycle(1'b0, 1'b0, 1'b1, 8'h13, 20'b0, 1'b0, 2'b00, 1'b1);
      drive_cycle(1'b0, 1'b0, 1'b0, 8'h00, 20'b0, 1'b0, 2'b00, 1'b1);
    end
  endtask

  // One mid-stream reset pulse (clock live), exercising equivalence through
  // reset for every module.
  task mid_stream_reset;
    begin
      @(negedge clk);
      clear      <= 1'b0;
      load       <= 1'b0;
      accumulate <= 1'b0;
      rst_n      <= 1'b0;
      #1;
      check_outputs;
      @(posedge clk);
      cycle = cycle + 1;
      @(negedge clk);
      rst_n <= 1'b1;
      #1;
      check_outputs;
    end
  endtask

  integer sm;
  integer am;

  initial begin
    // Asynchronous reset entry: a real 1 -> 0 negedge at time zero.
    rst_n = 1'b0;
    clear = 1'b0; load = 1'b0; accumulate = 1'b0;
    raw_data = 8'h00; load_value = 20'b0;
    signed_mode = 1'b0; accumulator_mode = 2'b01; bank_select = 1'b0;
    repeat (3) begin
      @(negedge clk);
      #1;
      check_outputs;
      @(posedge clk);
      cycle = cycle + 1;
    end
    rst_n = 1'b1;

    frozen_clock_reset_check;

    // Full equivalence matrix: mixed stream over all modes x signedness,
    // with random clear/load injection.
    for (sm = 0; sm <= 1; sm = sm + 1) begin
      for (am = 0; am <= 3; am = am + 1) begin
        drive_cycle(1'b1, 1'b0, 1'b0, 8'h00, 20'b0, sm[0], am[1:0], 1'b1);
        run_mixed_stream(sm[0], am[1:0], 1'b1);
        drive_cycle(1'b0, 1'b0, 1'b0, 8'h00, 20'b0, sm[0], am[1:0], 1'b1);
      end
    end

    // 4096 MACs of 8'hff unsigned and 4096 of 8'h11 signed per mode.
    for (am = 0; am <= 3; am = am + 1) begin
      drive_cycle(1'b1, 1'b0, 1'b0, 8'h00, 20'b0, 1'b0, am[1:0], 1'b1);
      run_const_stream(8'hff, 1'b0, am[1:0]);
      drive_cycle(1'b1, 1'b0, 1'b0, 8'h00, 20'b0, 1'b1, am[1:0], 1'b1);
      run_const_stream(8'h11, 1'b1, am[1:0]);
    end

    // Random clear/load fuzz with mode and signedness churn.
    run_random_phase;

    // Deselected-bank hold behavior.
    run_bank_select_phase;

    // Equivalence through a live-clock reset in the middle of traffic.
    drive_cycle(1'b0, 1'b0, 1'b1, 8'h44, 20'b0, 1'b0, 2'b10, 1'b1);
    drive_cycle(1'b0, 1'b0, 1'b1, 8'h44, 20'b0, 1'b0, 2'b10, 1'b1);
    mid_stream_reset;
    drive_cycle(1'b0, 1'b0, 1'b1, 8'h44, 20'b0, 1'b0, 2'b10, 1'b1);
    drive_cycle(1'b0, 1'b0, 1'b0, 8'h00, 20'b0, 1'b0, 2'b10, 1'b1);

    // Final idle checks.
    repeat (4) begin
      drive_cycle(1'b0, 1'b0, 1'b0, 8'h00, 20'b0, 1'b0, 2'b11, 1'b1);
    end

    if (errors == 0) begin
      $display("PASS: p2_acc_equiv_tb %0d cycles, %0d comparison points, 0 mismatches",
               cycle, checks);
      $finish;
    end else begin
      $display("FAIL: p2_acc_equiv_tb %0d mismatches over %0d cycles (%0d comparison points)",
               errors, cycle, checks);
      $fatal(1, "p2_acc_equiv_tb failed");
    end
  end

endmodule

`default_nettype wire
