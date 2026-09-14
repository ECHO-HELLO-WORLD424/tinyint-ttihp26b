/*
 * tt_fpga_pico2ice - FPGA harness for the pico2-ice (iCE40UP5K) board.
 *
 * FPGA-only verification wrapper for tt_um_echoworld424_tpv. This file is not
 * part of the ASIC submission and is not listed in info.yaml.
 *
 * The pico2-ice (Rev2) wires only 15 FPGA user I/O pins to the RP2350:
 *
 *   FPGA pin 35  <- RP2350 GPIO21  clk     (RP2350 CLK_GPOUT0)
 *   FPGA pin 20  <- RP2350 GPIO22  rst_n
 *   FPGA pin 27  <- RP2350 GPIO20  ui_cfg  (ui_in[7] in run, serial ui_in load)
 *   FPGA pins 19,18,21,23,25,26,9,11 <-> RP2350 GPIOs : uio[7:0]
 *   FPGA pins 14,15,16,17 -> RP2350 GPIO7..4 : uo_out[3:0]
 *
 * uio_in[7:0] carries configuration bits [15:8] during reset and the status
 * byte during run, exactly as on the ASIC. ui_in[7:0] has no parallel path on
 * this board, so it is loaded serially on ui_cfg during reset (MSB first, one
 * bit shifted per rising clk edge) and held for the design's configuration
 * capture edge. While rst_n is low, uo[0] mirrors clk so the host can align
 * the serial load to the clock.
 *
 * The RTL asserts uio_oe one clock before the cfg capture edge (boot[1]), so
 * on a real board the host driver and the fresh status output would contend
 * on the uio pads during that cycle. The harness samples uio_in while rst_n
 * is low and holds it for the design, which is the documented host contract
 * ("keep configuration pins stable through the first three clocks"); this
 * keeps the FPGA verification deterministic without changing design logic.
 */
`default_nettype none

module tt_fpga_pico2ice (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       ui_cfg,
    inout  wire [7:0] uio,
    output wire [3:0] uo
);

  wire [7:0] uio_in_w;
  wire [7:0] uio_out_w;
  wire [7:0] uio_oe_w;
  wire [7:0] uo_out_w;

  /* Mirrors the boot counter in tt_um_echoworld424_tpv so ui_cfg is routed
     to ui_in[7] (FREEZE) only after the configuration capture edge. */
  reg [1:0] boot;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) boot <= 2'd0;
    else if (boot != 2'd3) boot <= boot + 2'd1;
  end

  /* Serial ui_in[7:0] loader: shifts while in reset, holds afterwards. */
  reg [7:0] ui_shift;
  always @(posedge clk) begin
    if (!rst_n) ui_shift <= {ui_shift[6:0], ui_cfg};
  end

  /* Host contract model: the configuration byte on uio is stable while
     rst_n is low, so latch it there and hold it through the cfg capture. */
  reg [7:0] uio_cfg;
  always @(posedge clk) begin
    if (!rst_n) uio_cfg <= uio_in_w;
  end

  wire [7:0] ui_in_w = (boot == 2'd3) ? {ui_cfg, ui_shift[6:0]} : ui_shift;

  SB_IO #(
      .PIN_TYPE(6'b1010_01)
  ) uio_pins[7:0] (
      .PACKAGE_PIN(uio),
      .OUTPUT_ENABLE(uio_oe_w),
      .D_OUT_0(uio_out_w),
      .D_IN_0(uio_in_w)
  );

  tt_um_echoworld424_tpv user_project (
      .ui_in  (ui_in_w),
      .uo_out (uo_out_w),
      .uio_in (uio_cfg),
      .uio_out(uio_out_w),
      .uio_oe (uio_oe_w),
      .ena    (1'b1),
      .clk    (clk),
      .rst_n  (rst_n)
  );

  assign uo = rst_n ? uo_out_w[3:0] : {3'b000, clk};

endmodule
