/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// P3 core-level READ protocol testbench.
//
// The event-scheduled core (dut, src/tiny_int_core.v) and a frozen copy of
// the released conventional/dynamic core (tiny_int_core_ref,
// test/p3_ref/tiny_int_core_ref.v) are driven with IDENTICAL request
// streams. Checks:
//
//   1. Every READ response byte equals the reference core's response byte
//      for the same accepted READ (pairwise FIFO comparison), for all eight
//      selectors, including reads issued back-to-back and reads issued in
//      the middle of dense MAC storms.
//   2. DUT READ response latency is bounded (asserted <= 6 cycles; the
//      design guarantees exactly 2).
//   3. MAC acceptance never stalls: request_ready tracks rst_n on both
//      cores, and pair_count / done / last_product / count_overflow /
//      protocol_error / accumulator_overflow / latched_signed_mode /
//      accumulator_value match the reference continuously, so a flush never
//      drops or delays a MAC.
//   4. Protocol rejection parity (reserved commands, post-done commands).
//   5. Asynchronous reset clears both cores identically, including the DUT's
//      pending response pipeline.
module p3_core_read_tb;
  reg        clk;
  reg        rst_n;

  reg        request_valid;
  wire       dut_request_ready;
  wire       ref_request_ready;
  reg [2:0]  request_command;
  reg [7:0]  request_data;
  reg        request_signed_mode;

  wire [7:0] dut_multiplier_product;
  wire [19:0] dut_extended_product;
  wire [19:0] dut_accumulator_value;
  wire        dut_latched_signed_mode;
  wire [7:0]  dut_response_data;
  wire        dut_response_valid;
  wire [7:0]  dut_pair_count;
  wire        dut_done;
  wire [7:0]  dut_last_product;
  wire        dut_accumulator_overflow;
  wire        dut_count_overflow;
  wire        dut_protocol_error;

  wire [7:0] ref_multiplier_product;
  wire [19:0] ref_extended_product;
  wire [19:0] ref_accumulator_value;
  wire        ref_latched_signed_mode;
  wire [7:0]  ref_response_data;
  wire        ref_response_valid;
  wire [7:0]  ref_pair_count;
  wire        ref_done;
  wire [7:0]  ref_last_product;
  wire        ref_accumulator_overflow;
  wire        ref_count_overflow;
  wire        ref_protocol_error;

  localparam [2:0] COMMAND_FINISH   = 3'b000;
  localparam [2:0] COMMAND_CLEAR    = 3'b001;
  localparam [2:0] COMMAND_MAC      = 3'b010;
  localparam [2:0] COMMAND_MAC_LAST = 3'b011;
  localparam [2:0] COMMAND_READ     = 3'b100;

  integer cycle_count;
  integer error_count;
  reg     checking;
  reg [15:0] lfsr;
  integer i;

  // Response queues: one entry per accepted READ on each core.
  reg [7:0] ref_resp_queue [0:63];
  integer   accept_cycle_queue [0:63];
  integer   resp_head;
  integer   resp_tail;
  integer   lat_head;
  integer   lat_tail;
  integer   max_read_latency;

  tiny_int_core dut (
      .clk                 (clk),
      .rst_n               (rst_n),
      .request_valid       (request_valid),
      .request_ready       (dut_request_ready),
      .request_command     (request_command),
      .request_data        (request_data),
      .request_signed_mode (request_signed_mode),
      .request_from_bist   (1'b0),
      .multiplier_product  (dut_multiplier_product),
      .extended_product    (dut_extended_product),
      .accumulator_value   (dut_accumulator_value),
      .latched_signed_mode (dut_latched_signed_mode),
      .response_data       (dut_response_data),
      .response_valid      (dut_response_valid),
      .pair_count          (dut_pair_count),
      .done                (dut_done),
      .last_product        (dut_last_product),
      .accumulator_overflow(dut_accumulator_overflow),
      .count_overflow      (dut_count_overflow),
      .protocol_error      (dut_protocol_error)
  );

  tiny_int_core_ref ref_core (
      .clk                 (clk),
      .rst_n               (rst_n),
      .request_valid       (request_valid),
      .request_ready       (ref_request_ready),
      .request_command     (request_command),
      .request_data        (request_data),
      .request_signed_mode (request_signed_mode),
      .request_from_bist   (1'b0),
      .multiplier_product  (ref_multiplier_product),
      .extended_product    (ref_extended_product),
      .accumulator_value   (ref_accumulator_value),
      .latched_signed_mode (ref_latched_signed_mode),
      .response_data       (ref_response_data),
      .response_valid      (ref_response_valid),
      .pair_count          (ref_pair_count),
      .done                (ref_done),
      .last_product        (ref_last_product),
      .accumulator_overflow(ref_accumulator_overflow),
      .count_overflow      (ref_count_overflow),
      .protocol_error      (ref_protocol_error)
  );

  always #5 clk = ~clk;

  always @(negedge clk) begin
    if (checking) begin
      cycle_count = cycle_count + 1;
      #2 sample;
    end
  end

  task sample;
    begin
      // Continuous architectural equivalence.
      if (dut_request_ready !== ref_request_ready) begin
        $display("FAIL[%0t] cycle=%0d request_ready dut=%b ref=%b",
                 $time, cycle_count, dut_request_ready,
                 ref_request_ready);
        error_count = error_count + 1;
      end
      if (dut_pair_count !== ref_pair_count) begin
        $display("FAIL[%0t] cycle=%0d pair_count dut=%02x ref=%02x",
                 $time, cycle_count, dut_pair_count, ref_pair_count);
        error_count = error_count + 1;
      end
      if (dut_done !== ref_done) begin
        $display("FAIL[%0t] cycle=%0d done dut=%b ref=%b",
                 $time, cycle_count, dut_done, ref_done);
        error_count = error_count + 1;
      end
      if (dut_last_product !== ref_last_product) begin
        $display("FAIL[%0t] cycle=%0d last_product dut=%02x ref=%02x",
                 $time, cycle_count, dut_last_product, ref_last_product);
        error_count = error_count + 1;
      end
      if (dut_count_overflow !== ref_count_overflow) begin
        $display("FAIL[%0t] cycle=%0d count_overflow dut=%b ref=%b",
                 $time, cycle_count, dut_count_overflow,
                 ref_count_overflow);
        error_count = error_count + 1;
      end
      if (dut_protocol_error !== ref_protocol_error) begin
        $display("FAIL[%0t] cycle=%0d protocol_error dut=%b ref=%b",
                 $time, cycle_count, dut_protocol_error,
                 ref_protocol_error);
        error_count = error_count + 1;
      end
      if (dut_accumulator_overflow !== ref_accumulator_overflow) begin
        $display("FAIL[%0t] cycle=%0d sticky overflow dut=%b ref=%b",
                 $time, cycle_count, dut_accumulator_overflow,
                 ref_accumulator_overflow);
        error_count = error_count + 1;
      end
      if (dut_latched_signed_mode !== ref_latched_signed_mode) begin
        $display("FAIL[%0t] cycle=%0d latched_signed_mode dut=%b ref=%b",
                 $time, cycle_count, dut_latched_signed_mode,
                 ref_latched_signed_mode);
        error_count = error_count + 1;
      end
      if (dut_accumulator_value !== ref_accumulator_value) begin
        $display("FAIL[%0t] cycle=%0d accumulator_value dut=%05x ref=%05x",
                 $time, cycle_count, dut_accumulator_value,
                 ref_accumulator_value);
        error_count = error_count + 1;
      end

      // Response capture: both cores emit one response per accepted READ.
      if (ref_response_valid) begin
        if (((resp_tail + 1) & 63) == resp_head) begin
          $display("FAIL[%0t] response queue overflow", $time);
          error_count = error_count + 1;
        end else begin
          ref_resp_queue[resp_tail] = ref_response_data;
          resp_tail = (resp_tail + 1) & 63;
        end
      end
      if (dut_response_valid) begin
        if (resp_head == resp_tail) begin
          $display("FAIL[%0t] DUT response with no pending reference response",
                   $time);
          error_count = error_count + 1;
        end else begin
          if (dut_response_data !== ref_resp_queue[resp_head]) begin
            $display("FAIL[%0t] cycle=%0d READ response dut=%02x ref=%02x",
                     $time, cycle_count, dut_response_data,
                     ref_resp_queue[resp_head]);
            error_count = error_count + 1;
          end
          resp_head = (resp_head + 1) & 63;
        end
        // Latency bound (design guarantees exactly 2 cycles).
        if (lat_head == lat_tail) begin
          $display("FAIL[%0t] DUT response with no recorded acceptance", $time);
          error_count = error_count + 1;
        end else begin
          if ((cycle_count - accept_cycle_queue[lat_head]) > 6) begin
            $display("FAIL[%0t] READ response latency %0d exceeds 6 cycles",
                     $time, cycle_count - accept_cycle_queue[lat_head]);
            error_count = error_count + 1;
          end
          if ((cycle_count - accept_cycle_queue[lat_head]) >
              max_read_latency)
            max_read_latency = cycle_count - accept_cycle_queue[lat_head];
          lat_head = (lat_head + 1) & 63;
        end
      end
    end
  endtask

  // READ acceptance bookkeeping at the clock edge. cycle_count was last
  // sampled at the negedge before the acceptance posedge; response_valid is
  // observed by the sampler two negedges later, giving the documented
  // two-cycle latency.
  always @(posedge clk) begin
    if (checking && rst_n && request_valid &&
        (request_command == COMMAND_READ)) begin
      accept_cycle_queue[lat_tail] = cycle_count;
      lat_tail = (lat_tail + 1) & 63;
    end
  end

  task drive_command;
    input [2:0] command;
    input [7:0] data;
    input       signed_mode;
    begin
      @(negedge clk);
      request_valid       = 1'b1;
      request_command     = command;
      request_data        = data;
      request_signed_mode = signed_mode;
      @(posedge clk);
    end
  endtask

  task drive_idle;
    begin
      @(negedge clk);
      request_valid = 1'b0;
      @(posedge clk);
    end
  endtask

  task do_reset;
    begin
      @(negedge clk);
      rst_n = 1'b0;
      request_valid = 1'b0;
      repeat (2) @(negedge clk);
      #2;
      if ((dut_pair_count !== 8'h00) || (ref_pair_count !== 8'h00) ||
          dut_response_valid || ref_response_valid ||
          (dut_accumulator_value !== 20'b0) ||
          (ref_accumulator_value !== 20'b0)) begin
        $display("FAIL[%0t] reset did not clear both cores", $time);
        error_count = error_count + 1;
      end
      // A reset discards in-flight responses on both cores alike.
      resp_head = 0;
      resp_tail = 0;
      lat_head  = 0;
      lat_tail  = 0;
      rst_n = 1'b1;
      @(posedge clk);
    end
  endtask

  // One randomized command per cycle; requests stay valid every cycle so
  // MAC acceptance must remain 1/cycle even across READ flushes.
  task run_random_stream;
    input integer count;
    reg [3:0] op;
    begin
      for (i = 0; i < count; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        op   = lfsr[3:0];
        case (op)
          4'd0, 4'd1, 4'd2, 4'd3, 4'd4, 4'd5,
          4'd6:  drive_command(COMMAND_MAC, lfsr[15:8], lfsr[8]);
          4'd7:  drive_command(COMMAND_MAC_LAST, lfsr[15:8], lfsr[8]);
          4'd8:  drive_command(COMMAND_FINISH, 8'h00, 1'b0);
          4'd9:  drive_command(COMMAND_READ, {5'b0, lfsr[6:4]}, 1'b0);
          4'd10: drive_command(COMMAND_CLEAR,
                               {lfsr[4], lfsr[6:5]}, lfsr[8]);
          4'd11: drive_command(COMMAND_READ, 8'h00, 1'b0);
          4'd12: drive_command(COMMAND_READ, 8'h07, 1'b0);
          4'd13, 4'd14: drive_command(3'b101 | {1'b0, lfsr[2:1]},
                                      8'hff, 1'b0);
          default: drive_command(COMMAND_MAC, lfsr[15:8], lfsr[8]);
        endcase
      end
      drive_idle;
    end
  endtask

  // Eight consecutive READ cycles: the uniform two-cycle latency keeps the
  // responses collision-free and in order.
  task run_read_burst;
    begin
      for (i = 0; i < 8; i = i + 1) begin
        drive_command(COMMAND_READ, i[2:0], 1'b0);
      end
      drive_idle;
      repeat (8) @(negedge clk);
    end
  endtask

  initial begin
    clk = 1'b0;
    rst_n = 1'b0;
    request_valid = 1'b0;
    request_command = 3'b0;
    request_data = 8'b0;
    request_signed_mode = 1'b0;
    checking = 1'b0;
    cycle_count = 0;
    error_count = 0;
    resp_head = 0;
    resp_tail = 0;
    lat_head  = 0;
    lat_tail  = 0;
    max_read_latency = 0;
    lfsr = 16'h1ace;

    fork
      begin : watchdog
        repeat (2000000) @(posedge clk);
        $display("FAIL watchdog timeout");
        $finish_and_return(1);
      end
    join_none

    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    @(negedge clk);
    checking = 1;

    $display("PHASE directed-transaction");
    drive_command(COMMAND_CLEAR, 8'b000, 1'b1);
    for (i = 0; i < 100; i = i + 1) begin
      drive_command(COMMAND_MAC, {i[3:0], i[7:4]}, 1'b1);
    end
    for (i = 0; i < 8; i = i + 1) begin
      drive_command(COMMAND_READ, i[2:0], 1'b0);
    end
    drive_command(COMMAND_MAC_LAST, 8'h71, 1'b1);
    drive_command(COMMAND_READ, 8'h05, 1'b0);
    drive_command(COMMAND_FINISH, 8'h00, 1'b0);
    drive_command(COMMAND_READ, 8'h04, 1'b0);
    drive_command(COMMAND_READ, 8'h03, 1'b0);
    drive_idle;

    $display("PHASE unsigned-overflow-read");
    drive_command(COMMAND_CLEAR, 8'b000, 1'b0);
    for (i = 0; i < 400; i = i + 1) begin
      drive_command(COMMAND_MAC, 8'hff, 1'b0);
      if ((i & 63) == 63)
        drive_command(COMMAND_READ, i[1:0], 1'b0);
    end
    for (i = 0; i < 8; i = i + 1) begin
      drive_command(COMMAND_READ, i[2:0], 1'b0);
    end
    drive_idle;

    $display("PHASE signed-overflow-read");
    drive_command(COMMAND_CLEAR, 8'b000, 1'b1);
    for (i = 0; i < 2000; i = i + 1) begin
      drive_command(COMMAND_MAC, 8'h77, 1'b1);
    end
    for (i = 0; i < 8; i = i + 1) begin
      drive_command(COMMAND_READ, i[2:0], 1'b0);
    end
    drive_idle;

    $display("PHASE read-burst");
    run_read_burst;
    run_read_burst;

    $display("PHASE protocol-rejection-parity");
    drive_command(COMMAND_CLEAR, 8'b001, 1'b0);
    drive_command(COMMAND_MAC, 8'h25, 1'b0);
    drive_command(3'b101, 8'hff, 1'b0);
    drive_command(3'b110, 8'h00, 1'b0);
    drive_command(3'b111, 8'h00, 1'b0);
    drive_command(COMMAND_READ, 8'h04, 1'b0);
    drive_command(COMMAND_MAC_LAST, 8'h42, 1'b0);
    drive_command(COMMAND_MAC, 8'h99, 1'b0);
    drive_command(COMMAND_FINISH, 8'h00, 1'b0);
    drive_command(COMMAND_READ, 8'h04, 1'b0);
    drive_command(COMMAND_READ, 8'h03, 1'b0);
    drive_idle;

    $display("PHASE randomized-mixed-stream");
    drive_command(COMMAND_CLEAR, 8'b000, 1'b0);
    run_random_stream(4000);

    $display("PHASE reset-mid-stream");
    do_reset;
    drive_command(COMMAND_CLEAR, 8'b010, 1'b1);
    for (i = 0; i < 50; i = i + 1) begin
      drive_command(COMMAND_MAC, 8'hf1, 1'b1);
    end
    drive_command(COMMAND_READ, 8'h02, 1'b0);
    for (i = 0; i < 50; i = i + 1) begin
      drive_command(COMMAND_MAC, 8'h71, 1'b1);
    end
    drive_command(COMMAND_READ, 8'h00, 1'b0);
    drive_idle;
    repeat (4) @(negedge clk);

    if ((resp_head != resp_tail) || (lat_head != lat_tail)) begin
      $display("FAIL unmatched READ responses: %0d pending",
               (resp_tail - resp_head) & 63);
      error_count = error_count + 1;
    end
    if (error_count == 0) begin
      $display("PASS p3_core_read_tb: all READ responses match the reference core, max READ latency %0d cycles (bound 6), MACs never stalled (%0d cycles)",
               max_read_latency, cycle_count);
      $finish_and_return(0);
    end else begin
      $display("FAIL p3_core_read_tb: %0d errors over %0d cycles",
               error_count, cycle_count);
      $finish_and_return(1);
    end
  end

endmodule

`default_nettype wire
