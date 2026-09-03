# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
FST ?= -fst # Use more efficient FST format
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = int4_multiplier.v product_extender.v tiny_int_accumulator.v tiny_int_protocol.v tt_um_echo_hello_world424_tinyint.v
DYNAMIC_ACCUMULATOR_SOURCE ?= $(SRC_DIR)/tiny_int_dynamic_accumulator.v
EVENT_ACCUMULATOR_SOURCE ?= $(SRC_DIR)/tiny_int_event_accumulator.v
CORE_SOURCE ?= $(SRC_DIR)/tiny_int_core.v

# Test selection:
#   make test=ALL              Run every test_<module>.py file.
#   make test=int4_multiplier  Run test_int4_multiplier.py only.
test ?= ALL
TEST_FILES := $(sort $(wildcard test_*.py))
TEST_MODULES := $(basename $(notdir $(TEST_FILES)))
AVAILABLE_TESTS := $(patsubst test_%,%,$(TEST_MODULES))

ifeq ($(test),ALL)
SELECTED_TEST_MODULES := $(TEST_MODULES)
else
SELECTED_TEST_MODULES := $(filter test_$(test),$(TEST_MODULES))
ifeq ($(SELECTED_TEST_MODULES),)
$(error Unknown test module '$(test)'. Available modules: $(AVAILABLE_TESTS), or ALL)
endif
endif

empty :=
space := $(empty) $(empty)
comma := ,
COCOTB_TEST_MODULES := $(subst $(space),$(comma),$(strip $(SELECTED_TEST_MODULES)))

.DEFAULT_GOAL := test-suite
.PHONY: test-suite interactive
test-suite: sim

# Keep the interactive cocotb module out of TEST_FILES/test=ALL: unlike the
# regression tests it deliberately waits for commands on standard input. Pass
# the module on make's command line so cocotb's recursive make preserves it.
interactive:
	$(MAKE) sim COCOTB_TEST_MODULES=interactive COCOTB_RESULTS_FILE=interactive_results.xml

# P3 proposal self-checking iverilog testbenches (standalone, no cocotb).
#   make p3-equiv     represented-value invariant vs the conventional bank
#   make p3-metrics   maintenance-domain activity metrics
#   make p3-core-read core-level READ protocol vs a frozen reference core
P3_SIM_BUILD ?= sim_build/p3
P3_LEAF_SOURCES = $(SRC_DIR)/int4_multiplier.v $(SRC_DIR)/product_extender.v \
                  $(SRC_DIR)/tiny_int_accumulator.v
P3_EVENT_SOURCES = $(P3_LEAF_SOURCES) $(EVENT_ACCUMULATOR_SOURCE)

p3-equiv: $(P3_EVENT_SOURCES) p3_event_equiv_tb.v
	@mkdir -p $(P3_SIM_BUILD)
	iverilog -g2012 -o $(P3_SIM_BUILD)/p3_event_equiv.vvp \
	    $(P3_EVENT_SOURCES) p3_event_equiv_tb.v
	vvp $(P3_SIM_BUILD)/p3_event_equiv.vvp

p3-metrics: $(P3_EVENT_SOURCES) p3_event_metrics_tb.v
	@mkdir -p $(P3_SIM_BUILD)
	iverilog -g2012 -o $(P3_SIM_BUILD)/p3_event_metrics.vvp \
	    $(P3_EVENT_SOURCES) p3_event_metrics_tb.v
	vvp $(P3_SIM_BUILD)/p3_event_metrics.vvp

p3-core-read: $(P3_LEAF_SOURCES) $(EVENT_ACCUMULATOR_SOURCE) \
              $(DYNAMIC_ACCUMULATOR_SOURCE) $(CORE_SOURCE) \
              p3_ref/tiny_int_core_ref.v p3_core_read_tb.v
	@mkdir -p $(P3_SIM_BUILD)
	iverilog -g2012 -o $(P3_SIM_BUILD)/p3_core_read.vvp \
	    $(P3_LEAF_SOURCES) $(EVENT_ACCUMULATOR_SOURCE) \
	    $(DYNAMIC_ACCUMULATOR_SOURCE) $(CORE_SOURCE) \
	    p3_ref/tiny_int_core_ref.v p3_core_read_tb.v
	vvp $(P3_SIM_BUILD)/p3_core_read.vvp

.PHONY: p3-equiv p3-metrics p3-core-read

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD				= sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
VERILOG_SOURCES += $(DYNAMIC_ACCUMULATOR_SOURCE)
VERILOG_SOURCES += $(EVENT_ACCUMULATOR_SOURCE)
VERILOG_SOURCES += $(CORE_SOURCE)

else

# Leaf-module tests cannot run against the flattened gate-level netlist.
# Keep exhaustive multiplier coverage in RTL and exercise the physical top-level
# interface in gate mode.
COCOTB_TEST_MODULES = test_core_multistage_gate,test_dot_product_engine,test_mode_latching

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DSIM
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13g2/libs.ref/sg13g2_io/verilog/sg13g2_io.v
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/sg13g2_stdcell.v

# this gets copied in by the GDS action workflow
GATE_NETLIST ?= $(PWD)/gate_level_netlist.v
VERILOG_SOURCES += $(GATE_NETLIST)

endif

# Allow sharing configuration between design and testbench via `include`:
COMPILE_ARGS 		+= -I$(SRC_DIR)

# Include the testbench sources:
VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb

# Extend Cocotb's clean target to cover every artifact created by the local
# test workflow, independent of the selected simulator or RTL/gate-level mode.
clean::
	$(RM) -rf sim_build __pycache__ .pytest_cache
	$(RM) -f results.xml interactive_results.xml *.fst *.fst.hier *.vcd

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
