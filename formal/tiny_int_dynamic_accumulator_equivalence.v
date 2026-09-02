`default_nettype none

module tiny_int_dynamic_accumulator_equivalence (
    input wire clk
);
  (* anyseq *) reg        rst_n;
  (* anyseq *) reg        clear;
  (* anyseq *) reg        load;
  (* anyseq *) reg        accumulate;
  (* anyseq *) reg        signed_mode;
  (* anyseq *) reg [1:0]  accumulator_mode;
  (* anyseq *) reg [19:0] load_value;
  (* anyseq *) reg [7:0]  raw_product;

  wire [19:0] addend = signed_mode ? {{12{raw_product[7]}}, raw_product}
                                          : {12'b0, raw_product};

  wire [19:0] conventional_value;
  wire [19:0] conventional_result;
  wire conventional_carry;
  wire conventional_overflow_event;
  wire conventional_overflow;

  wire [19:0] dynamic_value;
  wire [19:0] dynamic_result;
  wire dynamic_carry;
  wire dynamic_overflow_event;
  wire dynamic_overflow;
  wire [4:0] dynamic_stage_write_enable;

  tiny_int_accumulator conventional (
      .clk(clk),
      .rst_n(rst_n),
      .clear(clear),
      .load(load),
      .accumulate(accumulate),
      .signed_mode(signed_mode),
      .load_value(load_value),
      .addend(addend),
      .accumulator_value(conventional_value),
      .addition_result(conventional_result),
      .addition_carry(conventional_carry),
      .addition_overflow(conventional_overflow_event),
      .accumulator_overflow(conventional_overflow)
  );

  tiny_int_dynamic_accumulator dynamic (
      .clk(clk),
      .rst_n(rst_n),
      .clear(clear),
      .load(load),
      .accumulate(accumulate),
      .signed_mode(signed_mode),
      .accumulator_mode(accumulator_mode),
      .load_value(load_value),
      .addend(addend),
      .accumulator_value(dynamic_value),
      .addition_result(dynamic_result),
      .addition_carry(dynamic_carry),
      .addition_overflow(dynamic_overflow_event),
      .accumulator_overflow(dynamic_overflow),
      .stage_write_enable(dynamic_stage_write_enable)
  );

  initial assume (!rst_n);

  always @(posedge clk) begin
    if (!$initstate) begin
      assume (rst_n);
      assume (accumulator_mode == 2'b01 ||
              accumulator_mode == 2'b10 ||
              accumulator_mode == 2'b11);

      assert (dynamic_value == conventional_value);
      assert (dynamic_result == conventional_result);
      assert (dynamic_carry == conventional_carry);
      assert (dynamic_overflow_event == conventional_overflow_event);
      assert (dynamic_overflow == conventional_overflow);
    end
  end

  wire _unused = &{dynamic_stage_write_enable, 1'b0};
endmodule

`default_nettype wire
