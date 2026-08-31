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
`endif

endmodule
