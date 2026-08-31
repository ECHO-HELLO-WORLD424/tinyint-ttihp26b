# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
FST ?= -fst # Use more efficient FST format
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = int4_multiplier.v product_extender.v tiny_int_core.v tiny_int_protocol.v tt_um_echo_hello_world424_tinyint.v

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
.PHONY: test-suite
test-suite: sim

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD				= sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))

else

# Leaf-module tests cannot run against the flattened gate-level netlist.
# Keep exhaustive multiplier coverage in RTL and exercise the physical top-level
# interface in gate mode.
COCOTB_TEST_MODULES = test_mode_latching

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DSIM
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13g2/libs.ref/sg13g2_io/verilog/sg13g2_io.v
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/sg13g2_stdcell.v

# this gets copied in by the GDS action workflow
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v

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
	$(RM) -f results.xml *.fst *.fst.hier *.vcd

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
