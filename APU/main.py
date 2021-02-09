"""
A small test program for the APU emulator module.
"""

import pyo

from APU import APU

_PULSE_REG0 = [0x3C, 0x3A, 0x3A, 0x3A, 0x38, 0x38, 0x30, 0x30]
_PULSE_REG2 = [0x44, 0x54, 0x44, 0x04, 0x04, 0x04, 0x04, 0x04]

_NOISE_REG0 = [0x3F, 0x3F, 0x3F, 0x3F, 0x3F, 0x3F,
               0x38, 0x38, 0x38, 0x38, 0x38, 0x38,
               0x38, 0x38, 0x38, 0x38, 0x38, 0x38,
               0x34, 0x34, 0x34, 0x34, 0x34, 0x34,
               0x34, 0x34, 0x34, 0x34, 0x34, 0x34]

_NOISE_REG2 = [0x0F, 0x0F, 0x0F, 0x0F, 0x0F, 0x0F,
               0x08, 0x08, 0x08, 0x08, 0x08, 0x08,
               0x06, 0x06, 0x06, 0x06, 0x06, 0x06,
               0x04, 0x04, 0x04, 0x04, 0x04, 0x04,
               0x04, 0x04, 0x04, 0x04, 0x04, 0x04]

pulse_ctr = 0
noise_ctr = 0


def write_values(apu_instance: APU):
    global noise_ctr, pulse_ctr

    apu_instance.noise.write_reg0(_NOISE_REG0[noise_ctr])
    apu_instance.noise.write_reg2(_NOISE_REG2[noise_ctr])

    noise_ctr += 1
    if noise_ctr >= len(_NOISE_REG0):
        noise_ctr = 0

    apu_instance.pulse_0.write_reg0(_PULSE_REG0[pulse_ctr])
    apu_instance.pulse_0.write_reg2(_PULSE_REG2[pulse_ctr])

    pulse_ctr += 1
    if pulse_ctr >= len(_PULSE_REG0):
        pulse_ctr = 0


if __name__ == '__main__':
    server = pyo.Server(48000, nchnls=1).boot()

    apu = APU()

    # DEBUG
    # test = pyo.LFO(freq=200, type=2, mul=0.5).out()

    # 240 Hz clock
    pattern = pyo.Pattern(function=apu.clock, time=0.004).play()

    # Period = $3F8 -> Frequency should be 110 Hz
    apu.pulse_0.write_reg0(0x30)
    # apu.pulse_0.write_reg1(0x00)
    apu.pulse_0.write_reg2(0x20)
    apu.pulse_0.write_reg3(0x01)

    apu.triangle.write_reg0(0xFF)
    apu.triangle.write_reg2(0xFB)
    apu.triangle.write_reg3(0xF1)

    apu.noise.write_reg0(0x3F)
    apu.noise.write_reg2(0x04)
    apu.noise.write_reg3(0x01)

    server.start()

    pyo.Noise()

    # Change values every 1/60th of a second
    change = pyo.Pattern(function=write_values, time=0.0166, arg=apu).play()

    selector = pyo.Selector([apu.pulse_0.output, apu.pulse_1.output, apu.triangle.output, apu.noise.output]).out()
    selector.setMode(1)
    selector.ctrl()

    # view = pyo.Spectrum(apu.pulse_0.output)
    view = pyo.Scope([apu.pulse_0.output, apu.triangle.output, apu.noise.output])

    # server.gui(locals())

    server.gui(locals())

    view.stop()
    change.stop()
    pattern.stop()
    server.stop()
