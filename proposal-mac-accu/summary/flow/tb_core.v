`timescale 1ns / 1ps

// Core-level gate simulation for the variant power comparison. Drives the
// same 8192-MAC mixed stream as the released power_activity_tb through the
// tiny_int_core request ports. +MODE selects the CLEAR payload (0..3),
// +VCD the dump file.
module tb_core;
  reg clk = 1'b0;
  reg rst_n = 1'b0;
  reg request_valid = 1'b0;
  wire request_ready;
  reg [2:0] request_command = 3'b000;
  reg [7:0] request_data = 8'b0;
  reg request_signed_mode = 1'b0;
  reg request_from_bist = 1'b0;

  wire [7:0] multiplier_product;
  wire [19:0] extended_product;
  wire [19:0] accumulator_value;
  wire latched_signed_mode;
  wire [7:0] response_data;
  wire response_valid;
  wire [7:0] pair_count;
  wire done;
  wire [7:0] last_product;
  wire accumulator_overflow;
  wire count_overflow;
  wire protocol_error;

  tiny_int_core dut (
      .clk(clk), .rst_n(rst_n),
      .request_valid(request_valid), .request_ready(request_ready),
      .request_command(request_command), .request_data(request_data),
      .request_signed_mode(request_signed_mode),
      .request_from_bist(request_from_bist),
      .multiplier_product(multiplier_product),
      .extended_product(extended_product),
      .accumulator_value(accumulator_value),
      .latched_signed_mode(latched_signed_mode),
      .response_data(response_data), .response_valid(response_valid),
      .pair_count(pair_count), .done(done), .last_product(last_product),
      .accumulator_overflow(accumulator_overflow),
      .count_overflow(count_overflow), .protocol_error(protocol_error)
  );

  always #10 clk = ~clk;

  integer mode, i, j;
  reg [15:0] lfsr;
  reg [8*256-1:0] vcd_name;

  initial begin
    if (!$value$plusargs("MODE=%d", mode)) mode = 1;
    if (!$value$plusargs("VCD=%s", vcd_name)) vcd_name = "core.vcd";
    $dumpfile(vcd_name);
    $dumpvars(0, tb_core);

    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    // CLEAR with the requested mode, signed, zero-skip off.
    @(negedge clk);
    request_valid = 1'b1;
    request_command = 3'b001;
    request_data = mode[1:0];
    request_signed_mode = 1'b1;
    @(negedge clk);
    request_command = 3'b010;

    lfsr = 16'h1ace;
    for (i = 0; i < 8192; i = i + 1) begin
      if (i < 2048) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        request_data = {lfsr[7:4], lfsr[3:0]};
      end else if (i < 4096) begin
        request_data = ((i & 3) == 0) ? {i[3:0], i[7:4]} : 8'h00;
      end else if (i < 6144) begin
        request_data = i[0] ? 8'hf1 : 8'h71;
      end else begin
        request_data = {i[7:4], i[3:0]};
      end
      request_valid = 1'b1;
      @(negedge clk);
    end
    request_valid = 1'b0;
    repeat (4) @(negedge clk);
    $finish;
  end
endmodule
