/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// P1 unified-bank two-compilation equivalence driver.
//
// The same testbench is compiled twice and the cycle logs are diffed:
//   1. Golden run:   iverilog -g2012 -DREF_CORE p1_core_equiv_tb.v
//                    test/p1_ref/tiny_int_core_ref.v (the pre-proposal
//                    composite core, renamed) plus the unchanged leaves
//                    int4_multiplier, product_extender, tiny_int_accumulator
//                    and tiny_int_dynamic_accumulator.
//   2. Proposal run: iverilog -g2012 p1_core_equiv_tb.v
//                    ../src/tiny_int_core.v ../src/tiny_int_unified_accumulator.v
//                    ../src/int4_multiplier.v ../src/product_extender.v
//
// With +define+REF_CORE the DUT is tiny_int_core_ref; without it the proposed
// tiny_int_core. Plusargs select the latched CLEAR mode payload (+MODE=0..3,
// data[1:0] = mode, data[2] = zero_skip), the stimulus stream (+WORKLOAD=0..6
// arithmetic streams, 4 = control interleavings with an async reset) and the
// log file (+OUT=<file>). One request is presented per cycle at negedge clk
// and every cycle appends one line of observables. The two logs for the same
// MODE/WORKLOAD pair must be byte-identical.
module p1_core_equiv_tb;

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

`ifdef REF_CORE
  tiny_int_core_ref dut (
`else
  tiny_int_core dut (
`endif
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

  // Arithmetic observation points that both core variants carry under the
  // same wire names (bank-muxed in the reference, direct in the proposal).
  wire [19:0] addition_result = dut.accumulator_addition_result;
  wire        addition_carry = dut.accumulator_addition_carry;
  wire        addition_overflow = dut.accumulator_addition_overflow;

  initial clk = 1'b0;
  always #5 clk = ~clk;

  integer fd;
  integer mode;
  integer workload;
  integer k;
  reg [15:0] lfsr;
  reg [8*256-1:0] out_name;

  // Sample the state committed by the edge that just passed, then present the
  // next request. Combinational outputs are logged before the new request is
  // applied, so every line describes exactly one completed cycle.
  task step;
    input       valid;
    input [2:0] command;
    input [7:0] data;
    input       signed_pin;
    begin
      @(negedge clk);
      $fdisplay(fd, "t=%0t val=%05x ovf=%b rsp=%02x rspv=%b cnt=%02x done=%b last=%02x covf=%b cof=%b perr=%b mult=%02x ext=%05x rdy=%b lsm=%b ares=%05x acry=%b aovf=%b",
                $time, accumulator_value, accumulator_overflow,
                response_data, response_valid, pair_count, done,
                last_product, accumulator_overflow, count_overflow,
                protocol_error, multiplier_product, extended_product,
                request_ready, latched_signed_mode,
                addition_result, addition_carry, addition_overflow);
      request_valid       = valid;
      request_command     = command;
      request_data        = data;
      request_signed_mode = signed_pin;
    end
  endtask

  // One accepted MAC per cycle. Kind selects the workload stream:
  // 0 = W_MIXED (LFSR, 75%-zero, +/- carry/borrow, nibble-ramp quarters),
  // 1 = W_UNSIGNED_DENSE, 2 = W_CONST1, 3 = W_ZERO.
  // stream_zero_skip latches zero_skip_register from CLEAR data[2], so the
  // skipped-MAC path (no accumulator write, count/last still update) is
  // covered by the equivalence matrix as well.
  task run_arith_stream;
    input integer kind;
    input integer count;
    input         stream_signed;
    input         stream_zero_skip;
    integer i;
    reg [7:0] d;
    begin
      lfsr = 16'h1ace;
      step(1'b1, 3'b001, {stream_zero_skip, mode[1:0]}, stream_signed);
      for (i = 0; i < count; i = i + 1) begin
        case (kind)
          0: begin
            if (i < 2048) begin
              d = {lfsr[7:4], lfsr[3:0]};
              lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
            end else if (i < 4096) begin
              d = ((i & 3) == 0) ? {i[3:0], i[7:4]} : 8'h00;
            end else if (i < 6144) begin
              d = i[0] ? 8'hf1 : 8'h71;
            end else begin
              d = {i[7:4], i[3:0]};
            end
          end
          1: d = 8'hff;
          2: d = 8'h11;
          default: d = 8'h00;
        endcase
        step(1'b1, 3'b010, d, stream_signed);
      end
    end
  endtask

  // Clear/READ/MAC_LAST interleavings, signed-pin wiggles,
  // done/rejection behaviour and an asynchronous reset in mid-stream. After
  // the reset is released without a CLEAR the configuration registers hold
  // their defaults, so the continuation exercises the boundary-20 policy in
  // the proposal against the conventional bank in the reference.
  task run_ctrl_stream;
    input stream_signed;
    integer i;
    reg [7:0] d;
    begin
      lfsr = 16'h1ace;
      step(1'b1, 3'b001, {1'b0, mode[1:0]}, stream_signed);
      for (i = 0; i < 64; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        step(1'b1, 3'b010, {lfsr[7:4], lfsr[3:0]}, stream_signed);
      end

      // READ every selector interleaved with MACs.
      for (i = 0; i < 8; i = i + 1) begin
        step(1'b1, 3'b100, {5'b00000, i[2:0]}, stream_signed);
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        step(1'b1, 3'b010, {lfsr[7:4], lfsr[3:0]}, stream_signed);
      end

      // Live pin changes must not alter a transaction until the next CLEAR.
      for (i = 0; i < 16; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        step(1'b1, 3'b010, {lfsr[7:4], lfsr[3:0]}, !stream_signed);
      end

      // MAC_LAST closes the transaction; further writes are rejected.
      lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
      step(1'b1, 3'b011, {lfsr[7:4], lfsr[3:0]}, stream_signed);
      step(1'b1, 3'b010, 8'h37, stream_signed);
      step(1'b1, 3'b000, 8'h00, stream_signed);
      step(1'b1, 3'b011, 8'h37, stream_signed);
      for (i = 0; i < 8; i = i + 1)
        step(1'b1, 3'b100, {5'b00000, i[2:0]}, stream_signed);
      step(1'b0, 3'b000, 8'h00, stream_signed);

      // A new transaction clears done and the protocol error sticky.
      step(1'b1, 3'b001, {1'b0, mode[1:0]}, stream_signed);
      for (i = 0; i < 32; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        step(1'b1, 3'b010, {lfsr[7:4], lfsr[3:0]}, stream_signed);
      end
      step(1'b1, 3'b000, 8'h00, stream_signed);
      step(1'b1, 3'b010, 8'h37, stream_signed);
      step(1'b1, 3'b100, 8'h04, stream_signed);
      step(1'b0, 3'b000, 8'h00, stream_signed);

      // Asynchronous reset while a MAC request is pending.
      step(1'b1, 3'b001, {1'b0, mode[1:0]}, stream_signed);
      for (i = 0; i < 100; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        step(1'b1, 3'b010, {lfsr[7:4], lfsr[3:0]}, stream_signed);
      end
      @(negedge clk);
      $fdisplay(fd, "t=%0t val=%05x ovf=%b rsp=%02x rspv=%b cnt=%02x done=%b last=%02x covf=%b cof=%b perr=%b mult=%02x ext=%05x rdy=%b lsm=%b ares=%05x acry=%b aovf=%b",
                $time, accumulator_value, accumulator_overflow,
                response_data, response_valid, pair_count, done,
                last_product, accumulator_overflow, count_overflow,
                protocol_error, multiplier_product, extended_product,
                request_ready, latched_signed_mode,
                addition_result, addition_carry, addition_overflow);
      request_valid       = 1'b1;
      request_command     = 3'b010;
      request_data        = 8'h37;
      request_signed_mode = stream_signed;
      #2 rst_n = 1'b0;

      // Release without CLEAR: defaults restored, continuation runs in
      // boundary-20/conventional mode with an unsigned addend path until the
      // next CLEAR relatches the mode under test.
      @(negedge clk);
      $fdisplay(fd, "t=%0t val=%05x ovf=%b rsp=%02x rspv=%b cnt=%02x done=%b last=%02x covf=%b cof=%b perr=%b mult=%02x ext=%05x rdy=%b lsm=%b ares=%05x acry=%b aovf=%b",
                $time, accumulator_value, accumulator_overflow,
                response_data, response_valid, pair_count, done,
                last_product, accumulator_overflow, count_overflow,
                protocol_error, multiplier_product, extended_product,
                request_ready, latched_signed_mode,
                addition_result, addition_carry, addition_overflow);
      rst_n               = 1'b1;
      request_signed_mode = 1'b0;
      for (i = 0; i < 50; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        step(1'b1, 3'b010, {lfsr[7:4], lfsr[3:0]}, 1'b0);
      end
      step(1'b1, 3'b001, {1'b0, mode[1:0]}, stream_signed);
      for (i = 0; i < 32; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        step(1'b1, 3'b010, {lfsr[7:4], lfsr[3:0]}, stream_signed);
      end
    end
  endtask

  // Common closing tail: MAC_LAST, rejection checks and a full READ sweep.
  task run_tail;
    input tail_signed;
    begin
      step(1'b1, 3'b011, 8'h21, tail_signed);
      step(1'b1, 3'b010, 8'h37, tail_signed);
      step(1'b1, 3'b000, 8'h00, tail_signed);
      for (k = 0; k < 8; k = k + 1)
        step(1'b1, 3'b100, {5'b00000, k[2:0]}, tail_signed);
      step(1'b0, 3'b000, 8'h00, tail_signed);
      step(1'b0, 3'b000, 8'h00, tail_signed);
    end
  endtask

  initial begin
    clk                 = 1'b0;
    rst_n               = 1'b0;
    request_valid       = 1'b0;
    request_command     = 3'b000;
    request_data        = 8'h00;
    request_signed_mode = 1'b0;

    if (!$value$plusargs("MODE=%d", mode)) mode = 0;
    if (!$value$plusargs("WORKLOAD=%d", workload)) workload = 0;
    if (!$value$plusargs("OUT=%s", out_name)) begin
      $fatal(1, "OUT=<file> plusarg is required");
    end
    if (mode < 0 || mode > 3) begin
      $fatal(1, "MODE must be 0 through 3");
    end

    fd = $fopen(out_name, "w");
    if (fd == 0) begin
      $fatal(1, "cannot open log file");
    end

    // Hold the asynchronous reset across several logged cycles.
    step(1'b0, 3'b000, 8'h00, 1'b0);
    step(1'b0, 3'b000, 8'h00, 1'b0);
    step(1'b0, 3'b000, 8'h00, 1'b0);
    rst_n = 1'b1;

    case (workload)
      0: run_arith_stream(0, 8192, 1'b1, 1'b0);
      1: run_arith_stream(1, 8192, 1'b0, 1'b0);
      2: run_arith_stream(2, 8192, 1'b1, 1'b0);
      3: run_arith_stream(3, 8192, 1'b1, 1'b0);
      4: run_ctrl_stream(1'b1);
      // Zero-skip-enabled variants: the CLEAR payload sets data[2], so the
      // 75%-zero quarter of W_MIXED skips most writes and W_ZERO skips every
      // write while pair_count/last_product still advance. The tail READ of
      // the configuration selector verifies the latched zero_skip bit.
      5: run_arith_stream(0, 8192, 1'b1, 1'b1);
      6: run_arith_stream(3, 8192, 1'b1, 1'b1);
      default: $fatal(1, "WORKLOAD must be 0 through 6");
    endcase

    run_tail(workload == 1 ? 1'b0 : 1'b1);

    $fclose(fd);
    $display("PASS p1_core_equiv mode=%0d workload=%0d", mode, workload);
    $finish;
  end

endmodule

`default_nettype wire
