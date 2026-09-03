/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// P3 maintenance-domain activity metrics.
//
// Drives the exact released power-activity mixed stream (8192 signed MACs:
// dense LFSR, 75%-zero sparse, +7/-1 alternation, nibble ramp) into the
// event-scheduled accumulator while a conventional golden bank verifies the
// represented value, then reports:
//   - accepted MACs and hot-path stage-0/1 write events,
//   - cold register write events for stage 2/3/4 separately,
//   - cold_we (maintenance tick) cycles, split into divider ticks and
//     out-of-order (saturation-guard) ticks,
//   - max |cnt_2|, |cnt_3|, |cnt_4| observed,
//   - per-nibble state toggle counts (bit toggles and value changes).
// Cold-stage totals are asserted against the released dynamic-8 trace
// (599 / 107 / 104 bit toggles per 8192 MACs). A final flush must make the
// stored bank equal the golden value exactly. The 30k-MAC unsigned 0xff
// carry storm is measured afterward as a worst-case cadence reference.
module p3_event_metrics_tb;
  reg         clk;
  reg         rst_n;
  reg         clear;
  reg         load;
  reg         accumulate;
  reg         flush;
  reg         signed_mode;
  reg  [19:0] load_value;
  reg  [19:0] addend;

  wire [19:0] golden_value;
  wire [19:0] golden_result;
  wire        golden_carry;
  wire        golden_ofl;
  wire        golden_overflow;

  wire [19:0] stored_value;
  wire [19:0] canonical_value;
  wire        canonical_valid;
  wire        dut_overflow;
  wire [4:0]  stage_write_enable;
  wire        cold_write_active;

  reg  [7:0]  mac_data;
  wire [7:0]  mac_product;
  wire [19:0] mac_extended;

  integer i;
  integer cycle_count;
  integer error_count;
  reg     checking;

  // Metrics accumulators.
  integer mac_count;
  integer hot_write_0;
  integer hot_write_1;
  integer cold_write_2;
  integer cold_write_3;
  integer cold_write_4;
  integer cold_we_cycles;
  integer cold_we_divider;
  integer cold_we_emergency;
  integer max_abs_cnt2;
  integer max_abs_cnt3;
  integer max_abs_cnt4;
  integer bit_toggle_0;
  integer bit_toggle_1;
  integer bit_toggle_2;
  integer bit_toggle_3;
  integer bit_toggle_4;
  integer value_change_0;
  integer value_change_1;
  integer value_change_2;
  integer value_change_3;
  integer value_change_4;
  reg [3:0] prev_stage_0;
  reg [3:0] prev_stage_1;
  reg [3:0] prev_stage_2;
  reg [3:0] prev_stage_3;
  reg [3:0] prev_stage_4;
  reg       have_prev;

  integer cnt2_val;
  integer cnt3_val;
  integer cnt4_val;
  reg [19:0] represented;
  reg [19:0] invariant_value;

  tiny_int_accumulator golden (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (accumulate),
      .signed_mode         (signed_mode),
      .load_value          (load_value),
      .addend              (addend),
      .accumulator_value   (golden_value),
      .addition_result     (golden_result),
      .addition_carry      (golden_carry),
      .addition_overflow   (golden_ofl),
      .accumulator_overflow(golden_overflow)
  );

  tiny_int_event_accumulator dut (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (accumulate),
      .signed_mode         (signed_mode),
      .load_value          (load_value),
      .addend              (addend),
      .flush               (flush),
      .accumulator_value   (stored_value),
      .canonical_value     (canonical_value),
      .canonical_valid     (canonical_valid),
      .accumulator_overflow(dut_overflow),
      .stage_write_enable  (stage_write_enable),
      .cold_write_active   (cold_write_active)
  );

  int4_multiplier multiplier_leaf (
      .multiplicand(mac_data[3:0]),
      .multiplier  (mac_data[7:4]),
      .signed_mode (signed_mode),
      .product     (mac_product)
  );

  product_extender extender_leaf (
      .product         (mac_product),
      .signed_mode     (signed_mode),
      .extended_product(mac_extended)
  );

  always #5 clk = ~clk;

  function integer popcount4;
    input [3:0] value;
    begin
      popcount4 = value[0] + value[1] + value[2] + value[3];
    end
  endfunction

  // Sample every cycle at negedge+2 (registered state settled, stimulus
  // for the next edge not yet latched by the accumulators).
  always @(negedge clk) begin
    if (checking) begin
      cycle_count = cycle_count + 1;
      #2 sample;
    end
  end

  task sample;
    begin
      cnt2_val = $signed(dut.cnt_2);
      cnt3_val = $signed(dut.cnt_3);
      cnt4_val = $signed(dut.cnt_4);
      if (cnt2_val > max_abs_cnt2) max_abs_cnt2 = cnt2_val;
      if (-cnt2_val > max_abs_cnt2) max_abs_cnt2 = -cnt2_val;
      if (cnt3_val > max_abs_cnt3) max_abs_cnt3 = cnt3_val;
      if (-cnt3_val > max_abs_cnt3) max_abs_cnt3 = -cnt3_val;
      if (cnt4_val > max_abs_cnt4) max_abs_cnt4 = cnt4_val;
      if (-cnt4_val > max_abs_cnt4) max_abs_cnt4 = -cnt4_val;

      if (accumulate) mac_count = mac_count + 1;
      if (stage_write_enable[0]) hot_write_0 = hot_write_0 + 1;
      if (stage_write_enable[1]) hot_write_1 = hot_write_1 + 1;
      if (stage_write_enable[2]) cold_write_2 = cold_write_2 + 1;
      if (stage_write_enable[3]) cold_write_3 = cold_write_3 + 1;
      if (stage_write_enable[4]) cold_write_4 = cold_write_4 + 1;
      if (cold_write_active) begin
        cold_we_cycles = cold_we_cycles + 1;
        if (dut.maint_phase == 3'b000)
          cold_we_divider = cold_we_divider + 1;
        else
          cold_we_emergency = cold_we_emergency + 1;
      end

      if (have_prev) begin
        bit_toggle_0 = bit_toggle_0 +
            popcount4(dut.stage_0 ^ prev_stage_0);
        bit_toggle_1 = bit_toggle_1 +
            popcount4(dut.stage_1 ^ prev_stage_1);
        bit_toggle_2 = bit_toggle_2 +
            popcount4(dut.stage_2 ^ prev_stage_2);
        bit_toggle_3 = bit_toggle_3 +
            popcount4(dut.stage_3 ^ prev_stage_3);
        bit_toggle_4 = bit_toggle_4 +
            popcount4(dut.stage_4 ^ prev_stage_4);
        if (dut.stage_0 !== prev_stage_0)
          value_change_0 = value_change_0 + 1;
        if (dut.stage_1 !== prev_stage_1)
          value_change_1 = value_change_1 + 1;
        if (dut.stage_2 !== prev_stage_2)
          value_change_2 = value_change_2 + 1;
        if (dut.stage_3 !== prev_stage_3)
          value_change_3 = value_change_3 + 1;
        if (dut.stage_4 !== prev_stage_4)
          value_change_4 = value_change_4 + 1;
      end
      prev_stage_0 = dut.stage_0;
      prev_stage_1 = dut.stage_1;
      prev_stage_2 = dut.stage_2;
      prev_stage_3 = dut.stage_3;
      prev_stage_4 = dut.stage_4;
      have_prev    = 1'b1;

      // Correctness guard while measuring.
      represented = {dut.stage_4, dut.stage_3, dut.stage_2,
                     dut.stage_1, dut.stage_0};
      invariant_value = represented + (cnt2_val << 8) + (cnt3_val << 12) +
                        (cnt4_val << 16);
      if (invariant_value !== golden_value) begin
        $display("FAIL[%0t] cycle=%0d invariant golden=%05x represented=%05x cnt=%0d/%0d/%0d",
                 $time, cycle_count, golden_value, represented,
                 cnt2_val, cnt3_val, cnt4_val);
        error_count = error_count + 1;
      end
      if (canonical_value !== golden_value) begin
        $display("FAIL[%0t] cycle=%0d canonical=%05x golden=%05x",
                 $time, cycle_count, canonical_value, golden_value);
        error_count = error_count + 1;
      end
      if (dut_overflow !== golden_overflow) begin
        $display("FAIL[%0t] cycle=%0d sticky dut=%b golden=%b",
                 $time, cycle_count, dut_overflow, golden_overflow);
        error_count = error_count + 1;
      end
    end
  endtask

  task do_accumulate_data;
    input [7:0] data;
    begin
      @(negedge clk);
      mac_data = data;
      #1;
      accumulate = 1'b1;
      addend     = mac_extended;
      clear      = 1'b0;
      load       = 1'b0;
      flush      = 1'b0;
      @(posedge clk);
    end
  endtask

  task do_clear;
    begin
      @(negedge clk);
      accumulate = 1'b0;
      clear      = 1'b1;
      load       = 1'b0;
      flush      = 1'b0;
      @(negedge clk);
      clear      = 1'b0;
      @(posedge clk);
    end
  endtask

  task do_flush_and_verify;
    begin
      @(negedge clk);
      accumulate = 1'b0;
      clear      = 1'b0;
      load       = 1'b0;
      flush      = 1'b1;
      @(negedge clk);
      flush      = 1'b0;
      @(posedge clk);
      #2;
      if (stored_value !== golden_value) begin
        $display("FAIL[%0t] flushed stored=%05x golden=%05x",
                 $time, cycle_count, stored_value, golden_value);
        error_count = error_count + 1;
      end
      if ((dut.cnt_2 !== 5'sd0) || (dut.cnt_3 !== 5'sd0) ||
          (dut.cnt_4 !== 5'sd0) || !canonical_valid) begin
        $display("FAIL[%0t] flush left pending work", $time);
        error_count = error_count + 1;
      end
    end
  endtask

  task reset_metrics;
    begin
      mac_count        = 0;
      hot_write_0      = 0;
      hot_write_1      = 0;
      cold_write_2     = 0;
      cold_write_3     = 0;
      cold_write_4     = 0;
      cold_we_cycles   = 0;
      cold_we_divider  = 0;
      cold_we_emergency = 0;
      max_abs_cnt2     = 0;
      max_abs_cnt3     = 0;
      max_abs_cnt4     = 0;
      bit_toggle_0     = 0;
      bit_toggle_1     = 0;
      bit_toggle_2     = 0;
      bit_toggle_3     = 0;
      bit_toggle_4     = 0;
      value_change_0   = 0;
      value_change_1   = 0;
      value_change_2   = 0;
      value_change_3   = 0;
      value_change_4   = 0;
      have_prev        = 1'b0;
    end
  endtask

  task print_metrics;
    input [8*32-1:0] name;
    input integer macs;
    begin
      $display("METRICS %-24s macs=%0d", name, macs);
      $display("  hot writes: stage0=%0d stage1=%0d",
               hot_write_0, hot_write_1);
      $display("  cold writes: stage2=%0d stage3=%0d stage4=%0d (total %0d)",
               cold_write_2, cold_write_3, cold_write_4,
               cold_write_2 + cold_write_3 + cold_write_4);
      $display("  cold_we cycles: %0d (divider %0d, out-of-order %0d) of %0d cycles = %0.2f%% of cycles",
               cold_we_cycles, cold_we_divider, cold_we_emergency,
               cycle_count, (cycle_count > 0) ?
               (100.0 * cold_we_cycles) / cycle_count : 0.0);
      $display("  max|cnt|: cnt2=%0d cnt3=%0d cnt4=%0d",
               max_abs_cnt2, max_abs_cnt3, max_abs_cnt4);
      $display("  bit toggles: stage0=%0d stage1=%0d stage2=%0d stage3=%0d stage4=%0d",
               bit_toggle_0, bit_toggle_1, bit_toggle_2,
               bit_toggle_3, bit_toggle_4);
      $display("  value changes: stage0=%0d stage1=%0d stage2=%0d stage3=%0d stage4=%0d",
               value_change_0, value_change_1, value_change_2,
               value_change_3, value_change_4);
    end
  endtask

  reg [15:0] lfsr;

  initial begin
    clk = 1'b0;
    rst_n = 1'b0;
    clear = 1'b0;
    load = 1'b0;
    accumulate = 1'b0;
    flush = 1'b0;
    signed_mode = 1'b0;
    load_value = 20'b0;
    addend = 20'b0;
    mac_data = 8'b0;
    checking = 1'b0;
    cycle_count = 0;
    error_count = 0;
    reset_metrics;
    lfsr = 16'h1ace;

    fork
      begin : watchdog
        repeat (3000000) @(posedge clk);
        $display("FAIL watchdog timeout");
        $finish_and_return(1);
      end
    join_none

    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    @(negedge clk);
    checking = 1;

    // ---- Released mixed power-activity stream ----
    do_clear;
    reset_metrics;
    signed_mode = 1'b1;
    for (i = 0; i < 8192; i = i + 1) begin
      if (i < 2048) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        do_accumulate_data({lfsr[7:4], lfsr[3:0]});
      end else if (i < 4096) begin
        if ((i & 3) == 0)
          do_accumulate_data({i[3:0], i[7:4]});
        else
          do_accumulate_data(8'h00);
      end else if (i < 6144) begin
        if (i[0])
          do_accumulate_data(8'hf1);
        else
          do_accumulate_data(8'h71);
      end else begin
        do_accumulate_data({i[7:4], i[3:0]});
      end
    end
    do_idle_gap;
    print_metrics("mixed-8192-signed", mac_count);

    if (mac_count !== 8192) begin
      $display("FAIL expected 8192 accepted MACs, got %0d", mac_count);
      error_count = error_count + 1;
    end
    // Cold-stage activity must not exceed the released dynamic-8 trace
    // (bit toggles per 8192 MACs: dyn[11:8]=599, dyn[15:12]=107,
    //  dyn[19:16]=104).
    if (bit_toggle_2 > 599) begin
      $display("FAIL stage2 bit toggles %0d exceed baseline 599",
               bit_toggle_2);
      error_count = error_count + 1;
    end
    if (bit_toggle_3 > 107) begin
      $display("FAIL stage3 bit toggles %0d exceed baseline 107",
               bit_toggle_3);
      error_count = error_count + 1;
    end
    if (bit_toggle_4 > 104) begin
      $display("FAIL stage4 bit toggles %0d exceed baseline 104",
               bit_toggle_4);
      error_count = error_count + 1;
    end
    if (max_abs_cnt2 > 8) begin
      $display("FAIL |cnt2| reached %0d, divider bound is 8", max_abs_cnt2);
      error_count = error_count + 1;
    end

    do_flush_and_verify;
    $display("SUMMARY mixed cold bit-toggle reduction vs dynamic-8: stage2 %0d/599, stage3 %0d/107, stage4 %0d/104",
             bit_toggle_2, bit_toggle_3, bit_toggle_4);

    // ---- Worst-case cadence reference: 30k unsigned 0xff carry storm ----
    do_clear;
    reset_metrics;
    signed_mode = 1'b0;
    for (i = 0; i < 30000; i = i + 1) begin
      do_accumulate_data(8'hff);
    end
    do_idle_gap;
    print_metrics("carry-storm-30k", mac_count);
    do_flush_and_verify;

    if (error_count == 0) begin
      $display("PASS p3_event_metrics_tb");
      $finish_and_return(0);
    end else begin
      $display("FAIL p3_event_metrics_tb: %0d errors", error_count);
      $finish_and_return(1);
    end
  end

  task do_idle_gap;
    begin
      @(negedge clk);
      accumulate = 1'b0;
      clear      = 1'b0;
      load       = 1'b0;
      flush      = 1'b0;
      @(posedge clk);
    end
  endtask

endmodule

`default_nettype wire
