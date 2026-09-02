`timescale 1ns / 1ps
`default_nettype none

// Side-by-side equivalence check: baseline data-gated dynamic accumulator vs
// the clock-gated prototype. Drives a deterministic mixed stream (dense LFSR,
// sparse, signed carry/borrow, counter ramp) through all three dynamic modes
// and asserts every observable settles to the same value every cycle.
module acc_clkgate_equiv_tb;
  reg clk = 1'b0;
  reg rst_n = 1'b0;
  reg clear = 1'b0;
  reg load = 1'b0;
  reg accumulate = 1'b0;
  reg signed_mode = 1'b1;
  integer signed_loop;
  reg [1:0] accumulator_mode = 2'b01;
  reg [19:0] load_value = 20'b0;
  reg [19:0] addend = 20'b0;

  wire [19:0] base_value;
  wire [19:0] base_result;
  wire        base_carry;
  wire        base_overflow;
  wire        base_acc_overflow;
  wire [19:0] cg_value;
  wire [19:0] cg_result;
  wire        cg_carry;
  wire        cg_overflow;
  wire        cg_acc_overflow;

  tiny_int_dynamic_accumulator baseline (
      .clk(clk), .rst_n(rst_n), .clear(clear), .load(load),
      .accumulate(accumulate), .signed_mode(signed_mode),
      .accumulator_mode(accumulator_mode), .load_value(load_value),
      .addend(addend),
      .accumulator_value(base_value), .addition_result(base_result),
      .addition_carry(base_carry), .addition_overflow(base_overflow),
      .accumulator_overflow(base_acc_overflow),
      .stage_write_enable()
  );

  tiny_int_dynamic_accumulator_clkgate clkgate (
      .clk(clk), .rst_n(rst_n), .clear(clear), .load(load),
      .accumulate(accumulate), .signed_mode(signed_mode),
      .accumulator_mode(accumulator_mode), .load_value(load_value),
      .addend(addend),
      .accumulator_value(cg_value), .addition_result(cg_result),
      .addition_carry(cg_carry), .addition_overflow(cg_overflow),
      .accumulator_overflow(cg_acc_overflow),
      .stage_write_enable()
  );

  always #5 clk = ~clk;

  reg [15:0] lfsr = 16'hace1;
  integer i;
  integer errors = 0;
  integer cycle = 0;
  integer mode;

  task check;
    begin
      cycle = cycle + 1;
      if (base_value !== cg_value ||
          base_result !== cg_result ||
          base_carry !== cg_carry ||
          base_overflow !== cg_overflow ||
          base_acc_overflow !== cg_acc_overflow) begin
        $display("MISMATCH cycle %0d mode=%0d addend=%h base=%h cg=%h",
                 cycle, mode, addend, base_value, cg_value);
        errors = errors + 1;
      end
    end
  endtask

  initial begin
    repeat (4) @(negedge clk);
    rst_n = 1'b1;

    for (mode = 0; mode < 3; mode = mode + 1) begin
      accumulator_mode = mode + 2'b01;  // dynamic-8, dynamic-12, dynamic-16
      @(negedge clk);
      clear = 1'b1;
      @(negedge clk);
      clear = 1'b0;

      // interleave some load operations to exercise the load path
      if (mode == 0) begin
        @(negedge clk);
        load = 1'b1;
        load_value = 20'h3a5c2;
        @(negedge clk);
        load = 1'b0;
        check;
      end

      // exercise both signed and unsigned operation
      for (signed_loop = 0; signed_loop <= 1; signed_loop = signed_loop + 1) begin
        signed_mode = signed_loop[0];
        // dense LFSR
        for (i = 0; i < 2048; i = i + 1) begin
          lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
          addend = signed_mode ? {{12{lfsr[7]}}, lfsr[7:0]} : {12'b0, lfsr[7:0]};
          @(negedge clk);
          accumulate = 1'b1;
          @(negedge clk);
          accumulate = 1'b0;
          check;
        end
        // sparse (75% zero)
        for (i = 0; i < 2048; i = i + 1) begin
          if ((i & 3) == 0)
            addend = signed_mode ? 20'h00071 : 20'h00071;
          else
            addend = 20'b0;
          @(negedge clk);
          accumulate = 1'b1;
          @(negedge clk);
          accumulate = 1'b0;
          check;
        end
        // signed carry/borrow alternation
        for (i = 0; i < 2048; i = i + 1) begin
          addend = signed_mode ? (i[0] ? 20'hffff1 : 20'h00007)
                               : (i[0] ? 20'h000f1 : 20'h00071);
          @(negedge clk);
          accumulate = 1'b1;
          @(negedge clk);
          accumulate = 1'b0;
          check;
        end
        // counter ramp
        for (i = 0; i < 2048; i = i + 1) begin
          addend = signed_mode ? {{12{i[7]}}, i[7:0]} : {12'b0, i[7:0]};
          @(negedge clk);
          accumulate = 1'b1;
          @(negedge clk);
          accumulate = 1'b0;
          check;
        end
      end
    end

    @(negedge clk);
    if (errors == 0)
      $display("PASS: clock-gated accumulator is bit-exact with baseline over %0d cycles", cycle);
    else
      $display("FAIL: %0d mismatches over %0d cycles", errors, cycle);
    $finish;
  end
endmodule

`default_nettype wire