// =============================================================================
// rtl_v6/jedi_ant_diode.v
// Macro-internal input antenna protection diode hook (sg13g2_antennanp)
// Guardrail G2 & G3: (* keep = 1, dont_touch = "true" *)
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

(* keep = 1, dont_touch = "true" *)
module jedi_ant_diode (
    input wire pin_i
);
`ifdef SYNTH_IHP_SG13G2
    (* keep = 1, dont_touch = "true" *)
    sg13g2_antennanp u_ant (
        .A (pin_i)
    );
`else
    wire _unused_ok = &{1'b0, pin_i};
`endif
endmodule
`default_nettype wire
