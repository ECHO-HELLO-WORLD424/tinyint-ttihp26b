/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// P3 event-scheduled maintenance-domain accumulator ("deferred carry/borrow").
//
// The hot path (stages 0/1) accumulates every MAC exactly like the baseline
// dynamic-8 low stages. A carry/borrow crossing out of bit 7 is NOT written
// into stage 2 at MAC time; it is latched into a signed event counter:
//
//   cnt_2 += +1 on an increment (carry) crossing, -1 on a decrement (borrow).
//
// Cold stages (2/3/4) are updated off the hot path by a maintenance engine:
//   - A free-running 3-bit divider schedules one maintenance tick every 8 clk
//     cycles. A tick fires only when pending work exists and processes the
//     lowest stage with a nonzero counter: stage_k_new = (stage_k + cnt_k)
//     mod 16, with the nibble wrap pushed as +-1 into cnt_{k+1}. The same-
//     cycle hot event (if any) is folded into the stage-2 drain, so a tick
//     always clears cnt_2.
//   - Saturation guard: if a counter update would leave the 5-bit two's
//     complement range [-16, +15], the affected stage is drained on that very
//     cycle (out of order, possibly cascading 2 -> 3 -> 4). At the cadence-8
//     divider this guard is unreachable for cnt_2 (at most 8 events can occur
//     between ticks, so |cnt_2| <= 8) but is reachable for cnt_3/cnt_4 under
//     sustained one-sided event streams; it is lossless because the arriving
//     push is folded into the same-cycle drain.
//   - `flush` forces a full single-cycle canonicalization (all three stages
//     drained, counters cleared). The core asserts it when a READ response
//     must observe committed canonical state. Because the flush folds every
//     pending counter and any same-cycle event in one cycle, it converges
//     unconditionally, even while MACs (and their events) keep flowing.
//
// The REPRESENTED value
//   {stage_4, stage_3, stage_2, stage_1, stage_0}
//     + cnt_2*2^8 + cnt_3*2^12 + cnt_4*2^16   (mod 2^20, counters signed)
// always equals the true accumulated value; between drains the STORED state
// alone may be stale. `canonical_value` exposes the combinational correction
// chain (nibble + counter per stage); its inputs change only when the cold
// domain changes, so it stays nearly static on the hot path.
//
// Sticky overflow is maintained per MAC on the hot path with the exact
// baseline formulas evaluated on canonical values:
//   unsigned: a wrap pushed out of stage 4 (carry out of bit 19) of the
//             event-folded canonicalization, minus wraps already pending in
//             the counters (those belong to earlier MACs that latched them);
//   signed:   (canonical[19] == addend[19]) && (result[19] != canonical[19]).
// Maintenance drains re-latch a positive stage-4 wrap in unsigned mode
// (redundant but defensive); a borrow out of stage 4 is dropped per 20-bit
// modulo semantics (note the canonicalization of a value that wrapped past
// 2^20 legitimately pushes +-1 out of stage 4; that drop is the modulo
// reduction, and the per-MAC overflow formulas above are what the sticky
// flag tracks).
//
// Clocking: every state bit is updated inside the normal posedge clk block;
// cold stages use registered write enables (`if (tick_k) stage_k <= ...`).
// No gated clocks and no latches are used. Nibble-wrap pushes are derived by
// slicing the top bits of each signed nibble sum (floor(sum / 16)).
module tiny_int_event_accumulator (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        clear,
    input  wire        load,
    input  wire        accumulate,
    input  wire        signed_mode,
    input  wire [19:0] load_value,
    input  wire [19:0] addend,
    input  wire        flush,
    output wire [19:0] accumulator_value,   // stored, possibly stale-encoded
    output wire [19:0] canonical_value,     // represented + counters, corrected
    output wire        canonical_valid,     // no pending maintenance work
    output reg         accumulator_overflow,
    output wire [4:0]  stage_write_enable,  // {s4,s3,s2,s1,s0} write intent
    output wire        cold_write_active    // a maintenance/flush cold write
);

  reg [3:0] stage_0;
  reg [3:0] stage_1;
  reg [3:0] stage_2;
  reg [3:0] stage_3;
  reg [3:0] stage_4;

  // Signed event counters, one per cold stage. Range [-16, +15]; the
  // saturation guard keeps updates lossless at the range edges.
  reg signed [4:0] cnt_2;
  reg signed [4:0] cnt_3;
  reg signed [4:0] cnt_4;

  reg [2:0] maint_phase;

  assign accumulator_value = {stage_4, stage_3, stage_2, stage_1, stage_0};

  // ------------------------------------------------------------------
  // Hot path: stage 0/1 adds and the crossing-event capture. The event
  // detection is bit-identical to the baseline dynamic-8 policy; in signed
  // mode the sign-extended addend makes addend[19] the product sign, in
  // unsigned mode addend[19] is constant zero so only carry events occur.
  // ------------------------------------------------------------------
  wire [4:0] stage_0_addition =
      {1'b0, stage_0} + {1'b0, addend[3:0]};
  wire [4:0] stage_1_addition =
      {1'b0, stage_1} + {1'b0, addend[7:4]} + stage_0_addition[4];

  wire increment_event = !addend[19] && stage_1_addition[4];
  wire decrement_event =  addend[19] && !stage_1_addition[4];

  wire signed [1:0] hot_event =
      accumulate ? (increment_event ? 2'sd1 :
                    decrement_event ? -2'sd1 :
                                      2'sd0)
                 : 2'sd0;

  // ------------------------------------------------------------------
  // Canonical correction chain (no event folded): the canonical cold value
  // is {stage_4, stage_3, stage_2} + cnt_2 + 16*cnt_3 + 256*cnt_4, reduced
  // mod 4096 one nibble at a time. The final push out of stage 4 is the
  // number of whole 2^20 wraps still pending in the counters
  // (pending_wrap_4); it is the modulo-2^20 reduction, not an error.
  // ------------------------------------------------------------------
  wire signed [5:0] canonical_sum_2 =
      {2'b00, stage_2} + {{1{cnt_2[4]}}, cnt_2};
  wire signed [2:0] canonical_push_2 =
      {{1{canonical_sum_2[5]}}, canonical_sum_2[5:4]};
  wire signed [5:0] canonical_sum_3 =
      {2'b00, stage_3} + {{1{cnt_3[4]}}, cnt_3} +
      {{3{canonical_push_2[2]}}, canonical_push_2};
  wire signed [2:0] canonical_push_3 =
      {{1{canonical_sum_3[5]}}, canonical_sum_3[5:4]};
  wire signed [6:0] canonical_sum_4 =
      {3'b000, stage_4} + {{2{cnt_4[4]}}, cnt_4} +
      {{4{canonical_push_3[2]}}, canonical_push_3};

  assign canonical_value = {canonical_sum_4[3:0], canonical_sum_3[3:0],
                            canonical_sum_2[3:0], stage_1, stage_0};

  // Pending 2^20 wraps: the final push of the canonical chain equals the
  // number of whole 2^20 wraps the not-yet-drained counters carry. It must
  // be subtracted from chain pushes to obtain the carry of an individual
  // MAC (the represented value is only defined modulo 2^20).
  wire signed [2:0] pending_wrap_4 = canonical_sum_4[6:4];

  wire pending_2 = (cnt_2 != 5'sd0);
  wire pending_3 = (cnt_3 != 5'sd0);
  wire pending_4 = (cnt_4 != 5'sd0);
  assign canonical_valid = !pending_2 && !pending_3 && !pending_4;

  // ------------------------------------------------------------------
  // Maintenance scheduling. One stage per divider tick, lowest counter
  // first; `flush` forces every stage on that cycle.
  // ------------------------------------------------------------------
  wire divider_tick = (maint_phase == 3'b000);

  // Lossless saturation guard: drain the affected stage on the same cycle
  // the overflowing update would occur (see module header).
  wire cnt_2_event_overflow =
      accumulate && ((increment_event && (cnt_2 == 5'sd15)) ||
                     (decrement_event && (cnt_2 == -5'sd16)));

  wire tick_2 = flush || cnt_2_event_overflow ||
                (divider_tick && pending_2);

  // Stage-2 drain: fold the same-cycle hot event so cnt_2 always clears.
  wire signed [6:0] drain_sum_2 =
      {3'b000, stage_2} + {{2{cnt_2[4]}}, cnt_2} +
      {{5{hot_event[1]}}, hot_event};
  wire signed [2:0] drain_push_2 = drain_sum_2[6:4];

  wire signed [6:0] cnt_3_push_sum =
      {{2{cnt_3[4]}}, cnt_3} + {{4{drain_push_2[2]}}, drain_push_2};
  wire cnt_3_push_overflow =
      tick_2 && ((cnt_3_push_sum > 7'sd15) || (cnt_3_push_sum < -7'sd16));

  wire tick_3 = flush || cnt_3_push_overflow ||
                (divider_tick && !pending_2 && pending_3);

  // Stage-3 drain: folds the arriving push only when stage 2 drained too.
  wire signed [6:0] drain_sum_3 =
      {3'b000, stage_3} + {{2{cnt_3[4]}}, cnt_3} +
      (tick_2 ? {{4{drain_push_2[2]}}, drain_push_2} : 7'sd0);
  wire signed [2:0] drain_push_3 = drain_sum_3[6:4];

  wire signed [6:0] cnt_4_push_sum =
      {{2{cnt_4[4]}}, cnt_4} + {{4{drain_push_3[2]}}, drain_push_3};
  wire cnt_4_push_overflow =
      tick_3 && ((cnt_4_push_sum > 7'sd15) || (cnt_4_push_sum < -7'sd16));

  wire tick_4 = flush || cnt_4_push_overflow ||
                (divider_tick && !pending_2 && !pending_3 && pending_4);

  // Stage-4 drain: a wrap out of stage 4 is dropped (20-bit modulo) and a
  // positive wrap is a discarded carry (unsigned overflow event).
  wire signed [6:0] drain_sum_4 =
      {3'b000, stage_4} + {{2{cnt_4[4]}}, cnt_4} +
      (tick_3 ? {{4{drain_push_3[2]}}, drain_push_3} : 7'sd0);
  wire signed [2:0] drain_wrap_4 = drain_sum_4[6:4];

  // ------------------------------------------------------------------
  // Per-MAC overflow evaluation on the event-folded canonicalization
  // (what the canonical value becomes once this MAC's event is folded in).
  // This is exactly the baseline 20-bit addition observed on canonical
  // state, so the sticky flag matches the conventional bank bit for bit.
  // ------------------------------------------------------------------
  wire signed [6:0] result_sum_3 =
      {3'b000, stage_3} + {{2{cnt_3[4]}}, cnt_3} +
      {{4{drain_push_2[2]}}, drain_push_2};
  wire signed [2:0] result_push_3 = result_sum_3[6:4];
  wire signed [6:0] result_sum_4 =
      {3'b000, stage_4} + {{2{cnt_4[4]}}, cnt_4} +
      {{4{result_push_3[2]}}, result_push_3};
  wire signed [2:0] result_wrap_4 = result_sum_4[6:4];

  // Exact per-MAC unsigned carry: the event-folded chain push minus the
  // wraps already pending in the counters. The signed formula needs no
  // correction because it compares mod-2^20 sign bits only.
  wire signed [3:0] result_mac_carry =
      {result_wrap_4[2], result_wrap_4} -
      {pending_wrap_4[2], pending_wrap_4};
  wire signed_addition_overflow =
      (canonical_value[19] == addend[19]) &&
      (result_sum_4[3] != canonical_value[19]);
  wire addition_overflow = signed_mode ? signed_addition_overflow
                                       : (result_mac_carry > 4'sd0);

  // ------------------------------------------------------------------
  // State update. clear/load/reset write every register including the event
  // counters and the divider. Cold stages update only on their tick; hot
  // stages update on every accepted accumulate.
  // ------------------------------------------------------------------
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      stage_0              <= 4'b0;
      stage_1              <= 4'b0;
      stage_2              <= 4'b0;
      stage_3              <= 4'b0;
      stage_4              <= 4'b0;
      cnt_2                <= 5'sd0;
      cnt_3                <= 5'sd0;
      cnt_4                <= 5'sd0;
      accumulator_overflow <= 1'b0;
      maint_phase          <= 3'b0;
    end else if (clear) begin
      stage_0              <= 4'b0;
      stage_1              <= 4'b0;
      stage_2              <= 4'b0;
      stage_3              <= 4'b0;
      stage_4              <= 4'b0;
      cnt_2                <= 5'sd0;
      cnt_3                <= 5'sd0;
      cnt_4                <= 5'sd0;
      accumulator_overflow <= 1'b0;
      maint_phase          <= 3'b0;
    end else if (load) begin
      stage_0              <= load_value[3:0];
      stage_1              <= load_value[7:4];
      stage_2              <= load_value[11:8];
      stage_3              <= load_value[15:12];
      stage_4              <= load_value[19:16];
      cnt_2                <= 5'sd0;
      cnt_3                <= 5'sd0;
      cnt_4                <= 5'sd0;
      accumulator_overflow <= 1'b0;
      maint_phase          <= 3'b0;
    end else begin
      stage_0 <= accumulate ? stage_0_addition[3:0] : stage_0;
      stage_1 <= accumulate ? stage_1_addition[3:0] : stage_1;

      // Registered clock-enable style: cold nibbles only change state when
      // their maintenance tick (or a forced flush) fires.
      if (tick_2) begin
        stage_2 <= drain_sum_2[3:0];
      end
      if (tick_3) begin
        stage_3 <= drain_sum_3[3:0];
      end
      if (tick_4) begin
        stage_4 <= drain_sum_4[3:0];
      end

      cnt_2 <= tick_2 ? 5'sd0
                      : (cnt_2 + {{3{hot_event[1]}}, hot_event});
      cnt_3 <= tick_3 ? 5'sd0
                      : (cnt_3 + (tick_2 ? {{2{drain_push_2[2]}}, drain_push_2}
                                         : 5'sd0));
      cnt_4 <= tick_4 ? 5'sd0
                      : (cnt_4 + (tick_3 ? {{2{drain_push_3[2]}}, drain_push_3}
                                         : 5'sd0));

      accumulator_overflow <= accumulator_overflow |
                              (accumulate && addition_overflow) |
                              (!signed_mode && tick_4 &&
                               (({drain_wrap_4[2], drain_wrap_4} -
                                 {pending_wrap_4[2], pending_wrap_4}) >
                                4'sd0));

      maint_phase <= maint_phase + 3'd1;
    end
  end

  assign stage_write_enable = {tick_4, tick_3, tick_2, accumulate, accumulate};
  assign cold_write_active = tick_2 || tick_3 || tick_4;

endmodule

`default_nettype wire
