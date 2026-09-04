`default_nettype none
`timescale 1ns / 1ps

/* SDF-annotated timing simulation of the full post-route design
 * (PRE_SILICON_ACTION_PLAN P1.2, and an RO cross-check for P1.3).
 *
 * Unlike the zero-delay functional GL suite (test/, specify blocks stripped,
 * RO loops removed), this testbench:
 *   - compiles with -gspecify against a timing-safe stdcell library
 *     (tools/sdf/make_sdf_lib.py: IOPATH arcs kept, timing checks removed),
 *   - annotates the LibreLane-generated corner SDF (INTERCONNECT + IOPATH),
 *   - keeps the ring-oscillator loops live, so their counters tick.
 *
 * Protocol (same as the cocotb suite / datasheet): config while rst_n low,
 * hold until 3 cycles after release, run N frames, freeze, read 16 bytes.
 *
 * Plusargs:
 *   +period=<ns>        clock period
 *   +segs=<8-bit hex>   segment taps (bits 2k..2k+1 = seg k)
 *   +pat=<0..3>         pattern class
 *   +winsel=<0..3>      canary window select
 *   +nframes=<N>        number of measured operations
 *   +sdf=<path>         SDF file to annotate (optional; no arg = zero delay)
 *
 * Prints RESULT <field>=<value> lines for the driver to parse.
 */

module tb_sdfsim ();

  reg clk = 0;
  reg rst_n = 0;
  reg ena = 1;
  reg [7:0] ui_in = 0;
  reg [7:0] uio_in = 0;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  localparam FRAME = 19;

  integer period_ns = 20;
  integer nframes = 50;
  reg [15:0] word = 0;
  reg [1023:0] sdf_path = 0;
  reg have_sdf = 0;

  reg [7:0] tmp8 = 0;
  reg [1:0] tmp2a = 0;
  reg [1:0] tmp2b = 0;
  reg [1:0] tmp2c = 0;
  reg tmp1 = 0;

  tt_um_echoworld424_tpv dut (
      .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in), .uio_out(uio_out),
      .uio_oe(uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  initial begin
    if ($value$plusargs("period=%d", period_ns)) ;
    if ($value$plusargs("nframes=%d", nframes)) ;
    if ($value$plusargs("segs=%h", tmp8)) word[7:0] = tmp8;
    if ($value$plusargs("pat=%d", tmp2a)) word[9:8] = tmp2a;
    if ($value$plusargs("cansel=%d", tmp2b)) word[11:10] = tmp2b;
    if ($value$plusargs("winsel=%d", tmp2c)) word[13:12] = tmp2c;
    if ($value$plusargs("forcecan=%d", tmp1)) word[14] = tmp1;
    have_sdf = $value$plusargs("sdf=%s", sdf_path);
    if (have_sdf) begin
      $display("SDF annotating %0s", sdf_path);
      $sdf_annotate(sdf_path, dut);
    end else begin
      $display("SDF none (zero-delay reference run)");
    end
  end

  task cyc(input integer n);
    integer i;
    begin
      for (i = 0; i < n; i = i + 1) begin
        #(period_ns / 2.0) clk = 1;
        #(period_ns - period_ns / 2.0) clk = 0;
      end
    end
  endtask

  /* Read all 16 status bytes via the auto-incrementing pointer (inline in
     the main initial block below; pointer uo[3:0] auto-increments). */

  reg [7:0] vals [0:15];
  integer i;
  integer filled;
  integer err_cnt, gen_cnt, mat_cnt, ops_cnt;
  reg [7:0] cfg_echo, stat, err_dut;

  initial begin
    // reset + config phase
    rst_n = 0;
    ui_in = word[7:0];
    uio_in = word[15:8];
    cyc(4);
    rst_n = 1;
    cyc(3);          // boot window; cfg commits at the boot==2 edge
    ui_in = 0;       // release config pins (freeze low)
    uio_in = 0;
    cyc(8);

    // run nframes measured operations
    cyc(nframes * FRAME);

    // freeze + read status bytes
    ui_in = 8'h80;
    #(3 * period_ns);
    for (i = 0; i < 16; i = i + 1) vals[i] = 8'h00;
    filled = 0;
    for (i = 0; i < 64; i = i + 1) begin
      #(period_ns / 2.0) clk = 1;
      #(period_ns / 2.0);
      vals[uo_out[3:0]] = uio_out;
      filled = filled | (1 << uo_out[3:0]);
      clk = 0;
      if (filled == 16'hFFFF) i = 64;
    end
    ui_in = 8'h00;

    err_cnt = vals[0] | (vals[1] << 8);
    gen_cnt = vals[2] | (vals[3] << 8);
    mat_cnt = vals[4] | (vals[5] << 8);
    ops_cnt = vals[6] | (vals[7] << 8);
    cfg_echo = vals[8];
    stat = vals[9];
    err_dut = vals[10];

    $display("RESULT period_ns=%0d", period_ns);
    $display("RESULT segs=%h pat=%0d winsel=%0d", word[7:0], word[9:8], word[13:12]);
    $display("RESULT ops=%0d", ops_cnt);
    $display("RESULT err_cnt=%0d", err_cnt);
    $display("RESULT gen_cnt=%0d", gen_cnt);
    $display("RESULT mat_cnt=%0d", mat_cnt);
    $display("RESULT cfg_echo=%h", cfg_echo);
    $display("RESULT stat=%h", stat);
    $display("RESULT err_dut=%h", err_dut);
    $finish;
  end

endmodule
