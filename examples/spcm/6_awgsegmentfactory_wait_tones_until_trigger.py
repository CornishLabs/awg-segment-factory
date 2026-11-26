"""
Single-segment, two-channel Spectrum sequence-mode wait-trigger example.

Uploads one 40 us segment containing RF tones on H/CH0 and V/CH1, then starts
the card immediately. The only sequence step is a `wait_trig` step, so the tone
segment keeps looping while the card is armed even if no external trigger arrives.
"""

from __future__ import annotations

import time

import spcm
from spcm import units

from awgsegmentfactory import (
    QIRtoSamplesSegmentCompiler,
    AWGPhysicalSetupInfo,
    AWGProgramBuilder,
    quantize_resolved_ir,
    upload_sequence_program,
)

from common import print_quantization_report


SAMPLE_RATE_HZ = 625e6
SEGMENT_S = 40e-6
STEP_SAMPLES = 64
FULL_SCALE_MV = 1000.0

#"""
H_FREQS_HZ = [
    92e6,
    96e6,
    100e6,
    104e6,
    108e6,
]
H_AMPS_MV = [
    1.4*48.0,
    1.4*57.0,
    1.4*59.0,
    1.4*57.0,
    1.4*50.0,
]

# V is a one-tone channel for now; extend both lists together for multiple tones.
V_FREQS_HZ = [
    110e6,
]
V_AMPS_MV = [
    130.0,
]
#"""



# SINGLE TWEEZER AT ORIGIN
"""
H_FREQS_HZ = [
    105.55e6,
]
H_AMPS_MV = [
    1.4*48.0
]

# V is a one-tone channel for now; extend both lists together for multiple tones.
V_FREQS_HZ = [
    98.475e6,
]
V_AMPS_MV = [
    130.0,
]
"""

if len(H_FREQS_HZ) != len(H_AMPS_MV):
    raise ValueError("H_FREQS_HZ and H_AMPS_MV must have the same length")
if len(V_FREQS_HZ) != len(V_AMPS_MV):
    raise ValueError("V_FREQS_HZ and V_AMPS_MV must have the same length")

physical_setup = AWGPhysicalSetupInfo(logical_to_hardware_map={"H": 0, "V": 1})

builder = (
    AWGProgramBuilder()
    .logical_channel("H")
    .logical_channel("V")
    .define(
        "H_wait_tones",
        logical_channel="H",
        freqs=H_FREQS_HZ,
        amps=H_AMPS_MV,
        phases="auto",
    )
    .define(
        "V_wait_tones",
        logical_channel="V",
        freqs=V_FREQS_HZ,
        amps=V_AMPS_MV,
        phases="auto",
    )
)

builder.segment("wait_tones", mode="wait_trig")
builder.tones("H").use_def("H_wait_tones")
builder.tones("V").use_def("V_wait_tones")
builder.hold(time=SEGMENT_S)

ir = builder.build_resolved_ir(sample_rate_hz=SAMPLE_RATE_HZ)
q = quantize_resolved_ir(
    ir,
    segment_quantum_s=SEGMENT_S,
    step_samples=STEP_SAMPLES,
)

with spcm.Card(card_type=spcm.SPCM_TYPE_AO, verbose=False) as card:
    card.card_mode(spcm.SPC_REP_STD_SEQUENCE)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0 | spcm.CHANNEL1)
    channels.enable(True)
    channels.output_load(50 * units.ohm)
    channels.amp(FULL_SCALE_MV * units.mV)
    channels.stop_level(spcm.SPCM_STOPLVL_HOLDLAST)

    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_EXT0)
    trigger.ext0_mode(spcm.SPC_TM_POS)
    trigger.ext0_level0(0.3 * units.V)
    trigger.ext0_coupling(spcm.COUPLING_DC)
    trigger.termination(1)  # 50 Ohm
    trigger.delay(0)

    clock = spcm.Clock(card)
    clock.mode(spcm.SPC_CM_INTPLL)
    clock.sample_rate(SAMPLE_RATE_HZ * units.Hz)
    clock.clock_output(False)

    # Quantize once with the card's exact DAC scaling.
    full_scale = int(card.max_sample_value()) - 1
    slots_compiler = QIRtoSamplesSegmentCompiler(
        quantised=q,
        physical_setup=physical_setup,
        full_scale_mv=FULL_SCALE_MV,
        full_scale=full_scale,
    )
    slots_compiler.compile_to_card_int16()

    print(
        f"compiled segments: {len(slots_compiler.segments)} | "
        f"steps: {len(slots_compiler.steps)}"
    )
    print_quantization_report(slots_compiler)
    print(
        "Notes:\n"
        "- The program has one wait_trig step whose next step is itself.\n"
        "- The forced start trigger begins output immediately.\n"
        "- EXT0 can release the wait condition, but playback returns to the same tone segment.\n"
    )

    _session = upload_sequence_program(slots_compiler, mode="cpu", card=card)
    print("sequence written; starting card (Ctrl+C to stop)")

    card.timeout(0)
    card.start(spcm.M2CMD_CARD_ENABLETRIGGER, spcm.M2CMD_CARD_FORCETRIGGER)
    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        card.stop()
