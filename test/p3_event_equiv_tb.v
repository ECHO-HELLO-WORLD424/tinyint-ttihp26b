/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// P3 represented-value invariant testbench.
//
// The event-scheduled accumulator (dut) and the released conventional
// accumulator (golden) are driven with identical MAC/clear/load/flush/reset
// streams. EVERY cycle the following are checked:
//
//   1. golden_value == {stage_4, stage_3, stage_2, stage_1, stage_0}
//                      + cnt_2*256 + cnt_3*4096 + cnt_4*65536  (mod 2^20,
//      counters interpreted signed) -- the represented-value invariant.
//   2. canonical_value == golden_value (the correction chain is exact).
//   3. canonical_valid == (cnt_2 == 0 && cnt_3 == 0 && cnt_4 == 0).
//   4. The final canonicalization push out of stage 4 is zero.
//   5. Sticky accumulator_overflow == golden sticky (bit-exact per MAC).
//
// After every stream a flush is forced and the STORED bank (not just the
// represented value) must equal the golden value exactly with all counters
// cleared. Workloads: the released power-activity mixed 8192-MAC signed
// stream (LFSR / sparse / +-7,-1 / ramp quarters), unsigned 0xff, signed
// 0x11, signed 0x00 runs, randomized clear/load/flush injection, mid-stream
// asynchronous reset, directed nibble-boundary walks, and 30k-MAC one-sided
// carry/borrow storms that exercise the counter saturation guard.
module p3_event_equiv_tb;
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
  wire [19:0] golden_addition_result;
  wire        golden_addition_carry;
  wire        golden_addition_overflow;
  wire        golden_overflow;

  wire [19:0] stored_value;
  wire [19:0] canonical_value;
  wire        canonical_valid;
  wire        dut_overflow;
  wire [4:0]  stage_write_enable;
  wire        cold_write_active;

  // Multiplier/extender leafs reproduce the core addend contract so the
  // workload "data" bytes are converted exactly like the real core does.
  reg  [7:0]  mac_data;
  wire [7:0]  mac_product;
  wire [19:0] mac_extended;

  integer i;
  integer cycle_count;
  integer error_count;
  reg     checking;
  reg [15:0] lfsr;

  integer cnt2_val;
  integer cnt3_val;
  integer cnt4_val;
  reg [19:0] represented;
  reg [19:0] invariant_value;
  integer max_abs_cnt2;
  integer max_abs_cnt3;
  integer max_abs_cnt4;

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
      .addition_result     (golden_addition_result),
      .addition_carry      (golden_addition_carry),
      .addition_overflow   (golden_addition_overflow),
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

  always @(negedge clk) begin
    if (checking) begin
      cycle_count = cycle_count + 1;
      #2 verify_state;
    end
  end

  task verify_state;
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

      represented = {dut.stage_4, dut.stage_3, dut.stage_2,
                     dut.stage_1, dut.stage_0};
      invariant_value = represented + (cnt2_val << 8) + (cnt3_val << 12) +
                        (cnt4_val << 16);

      if (invariant_value !== golden_value) begin
        $display("FAIL[%0t] cycle=%0d represented-value invariant: golden=%05x represented=%05x cnt2=%0d cnt3=%0d cnt4=%0d invariant=%05x",
                 $time, cycle_count, golden_value, represented,
                 cnt2_val, cnt3_val, cnt4_val, invariant_value);
        error_count = error_count + 1;
      end
      if (canonical_value !== golden_value) begin
        $display("FAIL[%0t] cycle=%0d canonical_value=%05x golden=%05x",
                 $time, cycle_count, canonical_value, golden_value);
        error_count = error_count + 1;
      end
      if (canonical_valid !== ((cnt2_val == 0) && (cnt3_val == 0) &&
                               (cnt4_val == 0))) begin
        $display("FAIL[%0t] cycle=%0d canonical_valid=%b counters=%0d/%0d/%0d",
                 $time, cycle_count, canonical_valid,
                 cnt2_val, cnt3_val, cnt4_val);
        error_count = error_count + 1;
      end
      if (dut_overflow !== golden_overflow) begin
        $display("FAIL[%0t] cycle=%0d sticky overflow dut=%b golden=%b",
                 $time, cycle_count, dut_overflow, golden_overflow);
        if (error_count < 3) begin
          $display("       state: golden=%05x canonical=%05x addend=%05x signed=%b accumulate=%b flush=%b",
                   golden_value, canonical_value, addend, signed_mode,
                   accumulate, flush);
          $display("       stages=%h %h %h %h %h cnt=%0d %0d %0d",
                   dut.stage_4, dut.stage_3, dut.stage_2, dut.stage_1,
                   dut.stage_0, cnt2_val, cnt3_val, cnt4_val);
          $display("       chains: canon_sum4=%b result_sum3=%0d result_sum4=%0d result_sign=%b drain_sum2=%0d drain_sum4=%0d drain_wrap4=%0d tick=%b%b%b",
                   dut.canonical_sum_4, dut.result_sum_3, dut.result_sum_4,
                   dut.result_sum_4[3], dut.drain_sum_2, dut.drain_sum_4,
                   dut.drain_wrap_4, dut.tick_2, dut.tick_3, dut.tick_4);
          $display("       golden inputs: result=%05x carry=%b ofl=%b",
                   golden_addition_result, golden_addition_carry,
                   golden_addition_overflow);
        end
        error_count = error_count + 1;
      end
      if (accumulate &&
          (dut.addition_overflow !== golden.addition_overflow)) begin
        $display("FAIL[%0t] cycle=%0d per-MAC overflow formula diverges: dut=%b golden=%b",
                 $time, cycle_count, dut.addition_overflow,
                 golden.addition_overflow);
        $display("       state: golden=%05x canonical=%05x addend=%05x signed=%b",
                 golden_value, canonical_value, addend, signed_mode);
        $display("       driver: mac_data=%02x mac_product=%02x mac_extended=%05x",
                 mac_data, mac_product, mac_extended);
        $display("       stages=%h %h %h %h %h cnt=%0d %0d %0d result_sum4=%0d sign=%b",
                 dut.stage_4, dut.stage_3, dut.stage_2, dut.stage_1,
                 dut.stage_0, cnt2_val, cnt3_val, cnt4_val,
                 dut.result_sum_4, dut.result_sum_4[3]);
        error_count = error_count + 1;
      end
    end
  endtask

  task do_idle_cycle;
    begin
      @(negedge clk);
      accumulate = 1'b0;
      clear      = 1'b0;
      load       = 1'b0;
      flush      = 1'b0;
      @(posedge clk);
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

  task do_accumulate_raw;
    input [19:0] value;
    begin
      @(negedge clk);
      accumulate = 1'b1;
      addend     = value;
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

  task do_load;
    input [19:0] value;
    begin
      @(negedge clk);
      accumulate = 1'b0;
      clear      = 1'b0;
      load       = 1'b1;
      load_value = value;
      flush      = 1'b0;
      @(negedge clk);
      load       = 1'b0;
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
          (dut.cnt_4 !== 5'sd0)) begin
        $display("FAIL[%0t] counters not cleared by flush: %b %b %b",
                 $time, cycle_count, dut.cnt_2, dut.cnt_3, dut.cnt_4);
        error_count = error_count + 1;
      end
      if (!canonical_valid) begin
        $display("FAIL[%0t] canonical_valid low after flush", $time);
        error_count = error_count + 1;
      end
    end
  endtask

  task report_counters;
    input [8*32-1:0] name;
    begin
      $display("  %-24s max|cnt2|=%0d max|cnt3|=%0d max|cnt4|=%0d",
               name, max_abs_cnt2, max_abs_cnt3, max_abs_cnt4);
      max_abs_cnt2 = 0;
      max_abs_cnt3 = 0;
      max_abs_cnt4 = 0;
    end
  endtask

  // The released power-activity stream: 8192 signed MACs in four quarters
  // (dense LFSR, 75%-zero sparse, +7/-1 alternation, nibble ramp).
  task run_mixed_8192;
    begin
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
      do_idle_cycle();
    end
  endtask

  task run_constant_data;
    input [7:0] data;
    input integer count;
    begin
      for (i = 0; i < count; i = i + 1) begin
        do_accumulate_data(data);
      end
      do_idle_cycle();
    end
  endtask

  // Randomized operation mix with clear/load/flush injection and occasional
  // accumulate+flush coincidence.
  task run_random_stream;
    input integer count;
    reg [3:0] op;
    begin
      for (i = 0; i < count; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        op = lfsr[3:0];
        if (op < 4'd9) begin
          signed_mode = lfsr[8];
          do_accumulate_data(lfsr[15:8]);
        end else if (op == 4'd9) begin
          do_clear;
        end else if (op == 4'd10) begin
          do_load({lfsr[15:12], lfsr[11:8], lfsr[7:4], lfsr[3:0]});
        end else if (op == 4'd11) begin
          signed_mode = lfsr[8];
          // Accumulate and flush on the same cycle: the event must fold.
          @(negedge clk);
          mac_data = lfsr[15:8];
          #1;
          accumulate = 1'b1;
          addend     = mac_extended;
          flush      = 1'b1;
          clear      = 1'b0;
          load       = 1'b0;
          @(posedge clk);
          @(negedge clk);
          flush      = 1'b0;
          @(posedge clk);
        end else begin
          do_flush_and_verify;
        end
      end
      do_idle_cycle();
    end
  endtask

  // Directed nibble-boundary walk: load values that sit on wrap edges, then
  // long one-sided +/-1 walks so every stage crosses 0x0/0xF repeatedly.
  task run_boundary_walks;
    integer j;
    begin
      signed_mode = 1'b1;
      for (i = 0; i < 12; i = i + 1) begin
        case (i[3:0])
          4'd0:  do_load(20'h00000);
          4'd1:  do_load(20'h0000f);
          4'd2:  do_load(20'h00010);
          4'd3:  do_load(20'h000ff);
          4'd4:  do_load(20'h00fff);
          4'd5:  do_load(20'h01000);
          4'd6:  do_load(20'h7ffff);
          4'd7:  do_load(20'h80000);
          4'd8:  do_load(20'hfff0f);
          4'd9:  do_load(20'hffff0);
          4'd10: do_load(20'hfffff);
          default: do_load(20'ha5a5a);
        endcase
        for (j = 0; j < 40; j = j + 1) begin
          do_accumulate_raw(20'hfffff);
        end
        for (j = 0; j < 40; j = j + 1) begin
          do_accumulate_raw(20'h00001);
        end
        for (j = 0; j < 40; j = j + 1) begin
          do_accumulate_raw(20'hfffff);
        end
      end
      do_idle_cycle();
    end
  endtask

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
    max_abs_cnt2 = 0;
    max_abs_cnt3 = 0;
    max_abs_cnt4 = 0;
    lfsr = 16'h1ace;

    // Global watchdog.
    fork
      begin : watchdog
        repeat (4000000) @(posedge clk);
        $display("FAIL watchdog timeout");
        $finish_and_return(1);
      end
    join_none

    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    @(negedge clk);
    checking = 1;

    $display("WORKLOAD mixed-8192-signed");
    do_clear;
    run_mixed_8192;
    do_flush_and_verify;
    report_counters("mixed-8192-signed");

    $display("WORKLOAD unsigned-ff-4096");
    do_clear;
    signed_mode = 1'b0;
    run_constant_data(8'hff, 4096);
    do_flush_and_verify;
    report_counters("unsigned-ff-4096");

    $display("WORKLOAD signed-11-4096");
    do_clear;
    signed_mode = 1'b1;
    run_constant_data(8'h11, 4096);
    do_flush_and_verify;
    report_counters("signed-11-4096");

    $display("WORKLOAD signed-00-4096");
    do_clear;
    signed_mode = 1'b1;
    run_constant_data(8'h00, 4096);
    do_flush_and_verify;
    report_counters("signed-00-4096");

    $display("WORKLOAD random-clear-load-flush");
    do_clear;
    run_random_stream(20000);
    do_flush_and_verify;
    report_counters("random-clear-load-flush");

    $display("WORKLOAD carry-storm-30k-unsigned-ff");
    do_clear;
    signed_mode = 1'b0;
    run_constant_data(8'hff, 30000);
    do_flush_and_verify;
    report_counters("carry-storm-30k-unsigned-ff");

    $display("WORKLOAD borrow-storm-30k-signed-f1");
    do_clear;
    signed_mode = 1'b1;
    run_constant_data(8'hf1, 30000);
    do_flush_and_verify;
    report_counters("borrow-storm-30k-signed-f1");

    $display("WORKLOAD boundary-walks");
    do_clear;
    run_boundary_walks;
    do_flush_and_verify;
    report_counters("boundary-walks");

    $display("WORKLOAD async-reset-mid-stream");
    do_clear;
    signed_mode = 1'b1;
    for (i = 0; i < 300; i = i + 1) begin
      do_accumulate_data(8'hf1);
    end
    // Asynchronous reset between edges with inputs still toggling.
    @(negedge clk);
    accumulate = 1'b1;
    addend = mac_extended;
    #2 rst_n = 1'b0;
    repeat (2) @(negedge clk);
    #2;
    if ((golden_value !== 20'b0) || (stored_value !== 20'b0) ||
        (dut.cnt_2 !== 5'sd0) || (dut.cnt_3 !== 5'sd0) ||
        (dut.cnt_4 !== 5'sd0)) begin
      $display("FAIL async reset did not clear both accumulators");
      error_count = error_count + 1;
    end
    rst_n = 1'b1;
    for (i = 0; i < 300; i = i + 1) begin
      do_accumulate_data(8'h71);
    end
    do_flush_and_verify;
    report_counters("async-reset-mid-stream");

    if (error_count == 0) begin
      $display("PASS p3_event_equiv_tb: represented-value invariant held on every cycle of every workload (%0d cycles checked)",
               cycle_count);
      $finish_and_return(0);
    end else begin
      $display("FAIL p3_event_equiv_tb: %0d errors over %0d cycles",
               error_count, cycle_count);
      $finish_and_return(1);
    end
  end

endmodule

`default_nettype wire
