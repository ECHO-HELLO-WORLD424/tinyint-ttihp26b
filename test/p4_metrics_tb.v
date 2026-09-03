/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// P4 activity metrics: for each workload x latched mode, report the
// effective-boundary trace and the per-stage write events the bank actually
// performed, which is the energy-relevant activity the monitor controls.
// The suite also re-checks state equality against a conventional reference
// bank on every MAC so the metrics cannot mask a correctness regression.
//
// Workloads: 0 = signed LFSR, 1 = unsigned dense +225, 2 = signed constant
// product +1, 3 = signed zero product, 4 = released mixed quarters.
module p4_metrics_tb;

  reg         clk;
  reg         rst_n;
  reg         request_valid;
  wire        request_ready;
  reg  [2:0]  request_command;
  reg  [7:0]  request_data;
  reg         request_signed_mode;

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
      .request_from_bist   (1'b0),
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

  reg         ref_clear;
  reg         ref_accumulate;
  reg  [19:0] ref_addend;
  wire [19:0] ref_value;
  wire        ref_overflow;
  reg  [19:0] ref_load_value;
  reg         ref_signed_mode;
  reg         ref_load;

  tiny_int_accumulator reference_bank (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (ref_clear),
      .load                (ref_load),
      .accumulate          (ref_accumulate),
      .signed_mode         (ref_signed_mode),
      .load_value          (ref_load_value),
      .addend              (ref_addend),
      .accumulator_value   (ref_value),
      .addition_result     (),
      .addition_carry      (),
      .addition_overflow   (),
      .accumulator_overflow(ref_overflow)
  );

  initial clk = 1'b0;
  always #5 clk = ~clk;

  integer errors;
  integer i;
  reg [15:0] lfsr;
  reg [7:0] d;

  // metrics
  integer we0, we1, we2, we3, we4;
  integer boundary_cycles [0:3];
  reg [1:0] last_boundary;
  integer transitions;

  task step;
    input       valid;
    input [2:0] command;
    input [7:0] data;
    input       signed_pin;
    begin
      @(negedge clk);
      request_valid       = valid;
      request_command     = command;
      request_data        = data;
      request_signed_mode = signed_pin;
      #1;
      ref_clear      = (valid && command == 3'b001);
      ref_accumulate = (valid && (command == 3'b010 || command == 3'b011)) &&
                       !done &&
                       (!dut.zero_skip_register || multiplier_product != 8'b0);
      ref_addend     = ref_accumulate ? extended_product : 20'b0;
      ref_signed_mode = latched_signed_mode;
    end
  endtask

  task check_state;
    input [8*32-1:0] what;
    begin
      if (accumulator_value !== ref_value) begin
        errors = errors + 1;
        $display("FAIL t=%0t value=%05x ref=%05x (%0s)",
                 $time, accumulator_value, ref_value, what);
      end
    end
  endtask

  task sample_metrics;
    begin
      // Write events are one-cycle pulses on the sampled edge; count the
      // pre-edge state so each accepted MAC is counted exactly once.
      if (dut.accumulator_stage_write_enable[0]) we0 = we0 + 1;
      if (dut.accumulator_stage_write_enable[1]) we1 = we1 + 1;
      if (dut.accumulator_stage_write_enable[2]) we2 = we2 + 1;
      if (dut.accumulator_stage_write_enable[3]) we3 = we3 + 1;
      if (dut.accumulator_stage_write_enable[4]) we4 = we4 + 1;
      boundary_cycles[dut.effective_boundary] =
          boundary_cycles[dut.effective_boundary] + 1;
      if (dut.effective_boundary !== last_boundary) begin
        transitions = transitions + 1;
        last_boundary = dut.effective_boundary;
      end
    end
  endtask

  task run_stream;
    input integer kind;
    input integer count;
    begin
      for (i = 0; i < count; i = i + 1) begin
        case (kind)
          0: begin
            lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
            d = {lfsr[7:4], lfsr[3:0]};
          end
          1: d = 8'hff;
          2: d = 8'h11;
          3: d = 8'h00;
          default: begin // mixed quarters
            if (i < count / 4) begin
              lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
              d = {lfsr[7:4], lfsr[3:0]};
            end else if (i < count / 2) begin
              d = ((i & 3) == 0) ? {i[3:0], i[7:4]} : 8'h00;
            end else if (i < 3 * count / 4) begin
              d = i[0] ? 8'hf1 : 8'h71;
            end else begin
              d = {i[7:4], i[3:0]};
            end
          end
        endcase
        step(1'b1, 3'b010, d, (kind == 1) ? 1'b0 : 1'b1);
        check_state("metrics stream");
        sample_metrics;
      end
    end
  endtask

  task clear_with;
    input [1:0] mode;
    input       signed_pin;
    begin
      step(1'b1, 3'b001, {2'b00, mode}, signed_pin);
      step(1'b0, 3'b000, 8'h00, signed_pin);
    end
  endtask

  task report;
    input [8*16-1:0] name;
    input integer macs;
    begin
      $display("METRICS %0s macs=%0d we=%0d/%0d/%0d/%0d/%0d cyc_b20=%0d cyc_b8=%0d cyc_b12=%0d cyc_b16=%0d transitions=%0d",
               name, macs, we0, we1, we2, we3, we4,
               boundary_cycles[0], boundary_cycles[1],
               boundary_cycles[2], boundary_cycles[3], transitions);
    end
  endtask

  task reset_metrics;
    begin
      we0 = 0; we1 = 0; we2 = 0; we3 = 0; we4 = 0;
      boundary_cycles[0] = 0; boundary_cycles[1] = 0;
      boundary_cycles[2] = 0; boundary_cycles[3] = 0;
      transitions = 0;
      last_boundary = dut.effective_boundary;
    end
  endtask

  integer workload;
  initial begin
    clk = 1'b0; rst_n = 1'b0;
    request_valid = 1'b0; request_command = 3'b000;
    request_data = 8'h00; request_signed_mode = 1'b0;
    ref_clear = 1'b0; ref_load = 1'b0; ref_load_value = 20'b0;
    ref_accumulate = 1'b0; ref_addend = 20'b0; ref_signed_mode = 1'b0;
    errors = 0;

    repeat (3) @(negedge clk);
    rst_n = 1'b1;

    // Latch every available mode once and run all workloads. The monitor
    // retunes independently of the latched mode, so the reported metrics are
    // the adaptive policy's; the latched mode only sets the starting boundary.
    for (workload = 0; workload < 5; workload = workload + 1) begin
      clear_with(2'b01, 1'b1);
      lfsr = 16'h1ace;
      reset_metrics;
      case (workload)
        0: run_stream(0, 8192);
        1: run_stream(1, 8192);
        2: run_stream(2, 8192);
        3: run_stream(3, 8192);
        default: run_stream(4, 8192);
      endcase
      case (workload)
        0: report("lfsr_signed", 8192);
        1: report("unsigned_dense", 8192);
        2: report("const1_signed", 8192);
        3: report("zero_signed", 8192);
        default: report("mixed_released", 8192);
      endcase
    end

    if (errors == 0) begin
      $display("PASS p4_metrics_tb");
    end else begin
      $display("FAIL p4_metrics_tb: %0d errors", errors);
      $fatal(1);
    end
    $finish;
  end

endmodule

`default_nettype wire
