`timescale 1ns / 1ps
`default_nettype none

// Exhaust every low-region residue and all 256 raw 8-bit products for both
// zero- and sign-extension at each supported boundary. The high state rotates
// through patterns that include local and full cold-stage wrap conditions.
module dynamic_accumulator_exhaustive_tb;
  reg         clk;
  reg         rst_n;
  reg         clear;
  reg         load;
  reg         accumulate;
  reg         signed_mode;
  reg  [1:0]  accumulator_mode;
  reg  [19:0] load_value;
  reg  [19:0] addend;
  wire [19:0] accumulator_value;
  wire [19:0] addition_result;
  wire        addition_carry;
  wire        addition_overflow;
  wire        accumulator_overflow;
  wire [4:0]  stage_write_enable;

  integer mode_index;
  integer residue;
  integer raw_product;
  integer low_width;
  integer residue_count;
  reg [1:0] mode;
  reg [19:0] state;
  reg [20:0] expected_full;
  reg expected_overflow;

  tiny_int_dynamic_accumulator dut (
      .clk(clk),
      .rst_n(rst_n),
      .clear(clear),
      .load(load),
      .accumulate(accumulate),
      .signed_mode(signed_mode),
      .accumulator_mode(accumulator_mode),
      .load_value(load_value),
      .addend(addend),
      .accumulator_value(accumulator_value),
      .addition_result(addition_result),
      .addition_carry(addition_carry),
      .addition_overflow(addition_overflow),
      .accumulator_overflow(accumulator_overflow),
      .stage_write_enable(stage_write_enable)
  );

  task clock_once;
    begin
      #1 clk = 1'b1;
      #1 clk = 1'b0;
    end
  endtask

  task check_current_addition;
    begin
      expected_full = {1'b0, state} + {1'b0, addend};
      #1;
      if (addition_result !== expected_full[19:0]) begin
        $display("RESULT mode=%b residue=%0d product=%02x signed=%b state=%05x expected=%05x actual=%05x",
                 mode, residue, raw_product, signed_mode, state,
                 expected_full[19:0], addition_result);
        $fatal(1);
      end
      if (addition_carry !== expected_full[20]) begin
        $display("CARRY mode=%b residue=%0d product=%02x signed=%b state=%05x expected=%b actual=%b",
                 mode, residue, raw_product, signed_mode, state,
                 expected_full[20], addition_carry);
        $fatal(1);
      end
      expected_overflow = signed_mode ?
          ((state[19] == addend[19]) &&
           (expected_full[19] != state[19])) : expected_full[20];
      if (addition_overflow !== expected_overflow) begin
        $display("OVERFLOW mode=%b residue=%0d product=%02x signed=%b state=%05x expected=%b actual=%b",
                 mode, residue, raw_product, signed_mode, state,
                 expected_overflow, addition_overflow);
        $fatal(1);
      end
    end
  endtask

  function [11:0] high_pattern_8;
    input [2:0] selector;
    begin
      case (selector)
        3'd0: high_pattern_8 = 12'h000;
        3'd1: high_pattern_8 = 12'h001;
        3'd2: high_pattern_8 = 12'h00f;
        3'd3: high_pattern_8 = 12'h0f0;
        3'd4: high_pattern_8 = 12'h0ff;
        3'd5: high_pattern_8 = 12'hf00;
        3'd6: high_pattern_8 = 12'hfff;
        default: high_pattern_8 = 12'ha5a;
      endcase
    end
  endfunction

  function [7:0] high_pattern_12;
    input [2:0] selector;
    begin
      case (selector)
        3'd0: high_pattern_12 = 8'h00;
        3'd1: high_pattern_12 = 8'h01;
        3'd2: high_pattern_12 = 8'h0f;
        3'd3: high_pattern_12 = 8'h10;
        3'd4: high_pattern_12 = 8'hf0;
        3'd5: high_pattern_12 = 8'hfe;
        3'd6: high_pattern_12 = 8'hff;
        default: high_pattern_12 = 8'ha5;
      endcase
    end
  endfunction

  function [3:0] high_pattern_16;
    input [2:0] selector;
    begin
      case (selector)
        3'd0: high_pattern_16 = 4'h0;
        3'd1: high_pattern_16 = 4'h1;
        3'd2: high_pattern_16 = 4'h7;
        3'd3: high_pattern_16 = 4'h8;
        3'd4: high_pattern_16 = 4'he;
        3'd5: high_pattern_16 = 4'hf;
        3'd6: high_pattern_16 = 4'ha;
        default: high_pattern_16 = 4'h5;
      endcase
    end
  endfunction

  initial begin
    clk = 1'b0;
    rst_n = 1'b0;
    clear = 1'b0;
    load = 1'b0;
    accumulate = 1'b0;
    signed_mode = 1'b0;
    accumulator_mode = 2'b01;
    load_value = 20'b0;
    addend = 20'b0;
    clock_once();
    rst_n = 1'b1;

    for (mode_index = 0; mode_index < 3; mode_index = mode_index + 1) begin
      case (mode_index)
        0: begin mode = 2'b01; low_width = 8;  residue_count = 256;   end
        1: begin mode = 2'b10; low_width = 12; residue_count = 4096;  end
        default: begin mode = 2'b11; low_width = 16; residue_count = 65536; end
      endcase
      accumulator_mode = mode;

      for (residue = 0; residue < residue_count; residue = residue + 1) begin
        case (mode)
          2'b01: state = {high_pattern_8(residue[2:0]), residue[7:0]};
          2'b10: state = {high_pattern_12(residue[2:0]), residue[11:0]};
          default: state = {high_pattern_16(residue[2:0]), residue[15:0]};
        endcase
        load_value = state;
        load = 1'b1;
        clock_once();
        load = 1'b0;

        for (raw_product = 0; raw_product < 256;
             raw_product = raw_product + 1) begin
          signed_mode = 1'b0;
          addend = {12'b0, raw_product[7:0]};
          check_current_addition();

          signed_mode = 1'b1;
          addend = {{12{raw_product[7]}}, raw_product[7:0]};
          check_current_addition();
        end
      end
      $display("PASS boundary=%0d exhaustive residues=%0d products=256 extensions=2",
               low_width, residue_count);
    end

    $display("PASS dynamic accumulator exhaustive one-step verification");
    $finish;
  end
endmodule

`default_nettype wire
