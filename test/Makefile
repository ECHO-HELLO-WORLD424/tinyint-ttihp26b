# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
FST ?= -fst # Use more efficient FST format
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = tt_um_echoworld424_tpv.v tpv_cells.v tpv_delay_line.v \
                  tpv_rca16.v tpv_checker.v tpv_pattern_gen.v tpv_ro_canary.v

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD				= sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))

else

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DSIM
# GL tests run at a slower clock and with the RO loops stalled (see test.py)
export GL_TEST := yes

# iverilog cannot execute the $setuphold/$recrem timing checks used by the
# IHP cell models: their delayed_* timing nets stay undriven (X) and poison
# every flip-flop, and -gspecify specify-block processing is prohibitively
# slow. Patch the library for functional GL simulation: drop the specify
# blocks and drive the models from the real ports.
GL_STDCELL_PATCHED = $(SIM_BUILD)/sg13g2_stdcell_patched.v

# The canary RO loops are asynchronous free-running structures: in zero-delay
# functional GL simulation the simulator cannot handle them. Strip the loop
# cells from the simulation netlist (their counters remain and are held at
# zero by reset, which is exactly what the GL tests assert).
GL_NETLIST = $(SIM_BUILD)/gate_level_gl.v

VERILOG_SOURCES += $(GL_STDCELL_PATCHED)
VERILOG_SOURCES += $(GL_NETLIST)

endif

# Allow sharing configuration between design and testbench via `include`:
COMPILE_ARGS 		+= -I$(SRC_DIR)

# Simulation-only gate delay (ns) so the ring-oscillator canaries toggle in
# RTL simulation. Never defined for synthesis.
COMPILE_ARGS 		+= -DTPV_GDELAY=1

# Include the testbench sources:
VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb

# List test modules to run, separated by commas and without the .py suffix:
COCOTB_TEST_MODULES = test

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

# Patch rules must come after the include so they do not become the default
# goal (the first target in a Makefile wins).
$(GL_STDCELL_PATCHED): $(PDK_ROOT)/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/sg13g2_stdcell.v
	@mkdir -p $(dir $@)
	@sed -E '/^[[:space:]]*specify/,/^[[:space:]]*endspecify/d; s/delayed_([A-Za-z_][A-Za-z_0-9]*)/\1/g' $< > $@

$(GL_NETLIST): $(PWD)/gate_level_netlist.v $(PWD)/strip_ro_cells.py
	@mkdir -p $(dir $@)
	@python3 $(PWD)/strip_ro_cells.py $< $@
