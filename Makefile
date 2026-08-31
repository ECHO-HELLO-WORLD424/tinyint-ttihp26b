# Run Cocotb tests from the repository root.
#
#   make test=ALL
#   make test=int4_multiplier

test ?= ALL

.DEFAULT_GOAL := test-suite
.PHONY: test-suite clean

test-suite:
	$(MAKE) -C test test=$(test)

clean:
	$(MAKE) -C test clean
