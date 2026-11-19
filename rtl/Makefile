SIM ?= verilator
TOPLEVEL_LANG ?= verilog
VERILOG_SOURCES += $(CURDIR)/odos_gate_core.sv
COCOTB_TOPLEVEL = odos_gate_core
COCOTB_TEST_MODULES = test_odos_gate_cocotb
COMPILE_ARGS += --trace --trace-structs -GL_ROM_HEX=\"$(CURDIR)/rom/l_vec_q2_30.hex\" -GG3_ROM_HEX=\"$(CURDIR)/rom/g3_vec_q2_30.hex\"
SIM_ARGS += --trace
export PYTHONPATH := $(CURDIR):$(CURDIR)/..:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
