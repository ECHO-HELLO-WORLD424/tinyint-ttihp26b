`default_nettype none
`timescale 1ns / 1ps

/* This testbench just instantiates the module and makes some convenient wires
   that can be driven / tested by the cocotb test.py.
*/
module tb ();

  // Dump the signals to a FST file. You can view it with gtkwave or surfer.
  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  // Wire up the inputs and outputs:
  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

`ifndef GL_TEST
  // Independent multiplier-leaf interface for exhaustive RTL arithmetic tests.
  // The synthesized gate-level netlist contains only the flattened TT top.
  reg  [3:0] multiplier_multiplicand;
  reg  [3:0] multiplier_multiplier;
  reg        multiplier_signed_mode;
  wire [7:0] multiplier_product;

  // Independent extension-leaf interface for exhaustive RTL tests.
  reg  [7:0]  extender_product;
  reg         extender_signed_mode;
  wire [19:0] extender_extended_product;

  // Observe the integrated multiplier-to-extension path without consuming
  // Tiny Tapeout output pins reserved for the final response interface.
  wire [19:0] integrated_extended_product;
  wire [19:0] integrated_accumulator_addition_result;
  wire [19:0] integrated_accumulator_value;
  wire [7:0]  integrated_multiplier_product;
  wire [7:0]  integrated_pair_count;
  wire        integrated_done;
  wire        integrated_count_overflow;
  wire        integrated_protocol_error;
  wire [19:0] integrated_accumulator_addend;
  wire [1:0]  integrated_accumulator_mode;
  wire        integrated_zero_skip;
  wire [4:0]  integrated_stage_write_enable;

  // Independent accumulator-leaf interface for state and arithmetic tests.
  reg         accumulator_clear;
  reg         accumulator_load;
  reg         accumulator_accumulate;
  reg         accumulator_signed_mode;
  reg  [19:0] accumulator_load_value;
  reg  [19:0] accumulator_addend;
  wire [19:0] accumulator_value;
  wire [19:0] accumulator_addition_result;
  wire        accumulator_addition_carry;
  wire        accumulator_addition_overflow;
  wire        accumulator_overflow;

  // Independent dynamic-accumulator interface. Keeping the leaf visible here
  // permits exhaustive state/event testing before it is integrated in core.
  reg         dynamic_clear;
  reg         dynamic_load;
  reg         dynamic_accumulate;
  reg         dynamic_signed_mode;
  reg  [1:0]  dynamic_accumulator_mode;
  reg  [19:0] dynamic_load_value;
  reg  [19:0] dynamic_addend;
  wire [19:0] dynamic_accumulator_value;
  wire [19:0] dynamic_addition_result;
  wire        dynamic_addition_carry;
  wire        dynamic_addition_overflow;
  wire        dynamic_accumulator_overflow;
  wire [4:0]  dynamic_stage_write_enable;
`endif

  tt_um_echo_hello_world424_tinyint user_project (
      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

`ifndef GL_TEST
  assign integrated_extended_product = user_project.extended_product;
  assign integrated_accumulator_value = user_project.accumulator_value;
  assign integrated_multiplier_product = user_project.multiplier_product;
  assign integrated_pair_count = user_project.pair_count;
  assign integrated_done = user_project.done;
  assign integrated_count_overflow = user_project.count_overflow;
  assign integrated_protocol_error = user_project.protocol_error;
`ifndef CORE_GATE_TEST
  assign integrated_accumulator_addition_result =
      user_project.core.accumulator_addition_result;
  assign integrated_accumulator_addend =
      user_project.core.accumulator_addend;
  assign integrated_accumulator_mode =
      user_project.core.accumulator_mode_register;
  assign integrated_zero_skip = user_project.core.zero_skip_register;
  assign integrated_stage_write_enable =
      user_project.core.accumulator_stage_write_enable;
`else
  assign integrated_accumulator_addition_result = 20'b0;
  assign integrated_accumulator_addend = 20'b0;
  assign integrated_accumulator_mode = 2'b0;
  assign integrated_zero_skip = 1'b0;
  assign integrated_stage_write_enable = 5'b0;
`endif

  int4_multiplier multiplier_dut (
      .multiplicand(multiplier_multiplicand),
      .multiplier  (multiplier_multiplier),
      .signed_mode (multiplier_signed_mode),
      .product     (multiplier_product)
  );

  product_extender extender_dut (
      .product         (extender_product),
      .signed_mode     (extender_signed_mode),
      .extended_product(extender_extended_product)
  );

  tiny_int_accumulator accumulator_dut (
      .clk              (clk),
      .rst_n            (rst_n),
      .clear            (accumulator_clear),
      .load             (accumulator_load),
      .accumulate       (accumulator_accumulate),
      .signed_mode      (accumulator_signed_mode),
      .load_value       (accumulator_load_value),
      .addend           (accumulator_addend),
      .accumulator_value(accumulator_value),
      .addition_result  (accumulator_addition_result),
      .addition_carry   (accumulator_addition_carry),
      .addition_overflow(accumulator_addition_overflow),
      .accumulator_overflow(accumulator_overflow)
  );

  tiny_int_dynamic_accumulator dynamic_accumulator_dut (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (dynamic_clear),
      .load                (dynamic_load),
      .accumulate          (dynamic_accumulate),
      .signed_mode         (dynamic_signed_mode),
      .accumulator_mode    (dynamic_accumulator_mode),
      .load_value          (dynamic_load_value),
      .addend              (dynamic_addend),
      .accumulator_value   (dynamic_accumulator_value),
      .addition_result     (dynamic_addition_result),
      .addition_carry      (dynamic_addition_carry),
      .addition_overflow   (dynamic_addition_overflow),
      .accumulator_overflow(dynamic_accumulator_overflow),
      .stage_write_enable  (dynamic_stage_write_enable)
  );
`endif

endmodule
