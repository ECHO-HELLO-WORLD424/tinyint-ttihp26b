# Run Cocotb tests from the repository root.
#
#   make test=ALL
#   make test=int4_multiplier
#   make play

test ?= ALL

.DEFAULT_GOAL := test-suite
.PHONY: test-suite play clean

test-suite:
	$(MAKE) -C test test=$(test)

# Start a command-line simulator for manually driving pins and clocks.
play:
	$(MAKE) -C test interactive

clean:
	$(MAKE) -C test clean
