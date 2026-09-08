`default_nettype none
`timescale 1ns / 1ps

/* Cocotb testbench for the interactive timing-prediction test vehicle
 * emulator (tools/chip_emulate.py).
 *
 * Unlike test/tb.v this testbench:
 *   - is driven entirely from Python (no clock is generated in HDL), so the
 *     host can set pins and step one clock cycle at a time;
 *   - optionally annotates a per-corner SDF (+sdf=<path>) for PVT simulation
 *     of the post-route netlist;
 *   - optionally dumps a waveform (+waves=<path>, level 1: pin traffic only).
 *
 * Plusargs:
 *   +sdf=<file>    annotate this SDF on the DUT scope (PVT backend)
 *   +waves=<file>  write an FST waveform
 */
module tb_emulator ();

  /* rst_n starts HIGH so that the emulator's first write of 0 produces a real
     1->0 edge: the design's asynchronous resets (including the ring-oscillator
     ripple counters, which are clocked by the RO itself) need that edge. */
  reg         clk    = 1'b0;
  reg         rst_n  = 1'b1;
  reg         ena    = 1'b1;
  reg  [ 7:0] ui_in  = 8'h00;
  reg  [ 7:0] uio_in = 8'h00;
  wire [ 7:0] uo_out;
  wire [ 7:0] uio_out;
  wire [ 7:0] uio_oe;

  reg [1023:0] sdf_path  = 0;
  reg [1023:0] wave_path = 0;

  initial begin
`ifdef TPV_SDF
    if ($value$plusargs("sdf=%s", sdf_path)) begin
      $display("[emulator] annotating SDF %0s", sdf_path);
      $sdf_annotate(sdf_path, tb_emulator.user_project);
    end else begin
      $display("[emulator] WARNING: SDF build without +sdf (zero-delay netlist)");
    end
`else
    if ($value$plusargs("sdf=%s", sdf_path)) begin
      $display("[emulator] ignoring +sdf=%0s (RTL build)", sdf_path);
    end
`endif
    if ($value$plusargs("waves=%s", wave_path)) begin
      $display("[emulator] dumping waves to %0s", wave_path);
      $dumpfile(wave_path);
      $dumpvars(1, tb_emulator);
    end
  end

  tt_um_echoworld424_tpv user_project (
      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

endmodule
