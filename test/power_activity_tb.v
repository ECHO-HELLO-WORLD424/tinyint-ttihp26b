`timescale 1ns / 1ps

// Gate-level activity source for post-layout power comparison. Each run uses
// exactly the same pins and operand stream; only the CLEAR mode payload differs.
module power_activity_tb;
  reg clk = 1'b0;
  reg rst_n = 1'b0;
  reg ena = 1'b1;
  reg [7:0] ui_in = 8'b0;
  reg [7:0] uio_in = 8'b0;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  integer mode;
  integer i;
  reg [15:0] lfsr;
  reg [8*256-1:0] vcd_name;

  tt_um_echo_hello_world424_tinyint user_project (
      .ui_in(ui_in),
      .uo_out(uo_out),
      .uio_in(uio_in),
      .uio_out(uio_out),
      .uio_oe(uio_oe),
      .ena(ena),
      .clk(clk),
      .rst_n(rst_n)
  );

  always #10 clk = ~clk;

  task drive_command;
    input [2:0] command;
    input [7:0] data;
    begin
      @(negedge clk);
      ui_in = data;
      // Signed mode is held constant across all four comparison traces.
      uio_in = {3'b000, 1'b1, command, 1'b1};
    end
  endtask

  initial begin
    if (!$value$plusargs("MODE=%d", mode))
      mode = 0;
    if (!$value$plusargs("VCD=%s", vcd_name))
      vcd_name = "power_activity.vcd";
    if (mode < 0 || mode > 3) begin
      $display("ERROR: MODE must be 0 through 3");
      $finish_and_return(2);
    end

    $dumpfile(vcd_name);
    $dumpvars(0, power_activity_tb);

    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    drive_command(3'b001, mode[1:0]);

    // One accepted MAC per cycle. The common stream combines dense LFSR data,
    // 75%-zero sparse data, repeated signed carry/borrow patterns, and counter
    // ramps so the report is not biased to one transition distribution.
    lfsr = 16'h1ace;
    for (i = 0; i < 8192; i = i + 1) begin
      if (i < 2048) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        drive_command(3'b010, {lfsr[7:4], lfsr[3:0]});
      end else if (i < 4096) begin
        if ((i & 3) == 0)
          drive_command(3'b010, {i[3:0], i[7:4]});
        else
          drive_command(3'b010, 8'h00);
      end else if (i < 6144) begin
        if (i[0])
          drive_command(3'b010, 8'hf1); // -1, forcing borrow propagation
        else
          drive_command(3'b010, 8'h71); // +7, forcing carry propagation
      end else begin
        drive_command(3'b010, {i[7:4], i[3:0]});
      end
    end

    drive_command(3'b000, 8'h00);
    @(negedge clk);
    uio_in = 8'h10;
    ui_in = 8'h00;
    repeat (4) @(negedge clk);
    $finish;
  end
endmodule
