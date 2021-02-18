__author__ = "Fox Cunning"

import pyo

# Lookup tables
_NOISE_VOLUME = [0., .06, .12, .18, .24, .30, .36, .42, .48, .54, .6, .66, .72, .78, .84, .9]
_PULSE_VOLUME = [0., .03, .06, .09, .12, .15, .18, .21, .24, .27, .3, .33, .36, .39, .42, .45]

_LENGTH_COUNTER_LOAD = [10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14,
                        12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30]

"""
_NOISE_FREQ = [4811.2, 2405.6, 1202.8, 601.4, 300.7, 200.5, 150.4, 120.3,
               95.3, 75.8, 50.6, 37.9, 25.3, 18.9, 9.5, 4.7]

_NOISE_FREQ_0 = [51.733, 25.866, 12.933, 6.466, 3.233, 2.155, 1.617, 1.293,
                 1.024, .815, .544, .407, .203, 18.9, .102, .05]
"""

_NOISE_FREQ = [[12.933, 6.466, 3.233, 1.616, .808, .538, .404, .323,            # Mode clear
                .256, .203, .136, .101, .068, .05, .025, .012],

               [1202.8, 601.4, 300.7, 150.35, 75.175, 50.125, 37.6, 30.075,     # Mode set
                23.825, 18.95, 12.65, 9.475, 6.325, 4.725, 2.375, 1.175]]


# ----------------------------------------------------------------------------------------------------------------------

class PulseChannel:

    def __init__(self):
        # Register 0: $4000 / $4004
        self.duty_cycle: int = 0
        self.length_ctr_halt: bool = False
        self.constant_volume: bool = False
        self.volume_envelope: int = 0

        # Register 1: $4001 / $4005
        self.sweep_enabled: bool = False
        self.sweep_period: int = 0
        self.sweep_negate: bool = False
        self.sweep_shift: int = 0

        # Register 2: $4002 / $4006
        self.timer_low: int = 0

        # Register 3: $4003 / $4007
        self.timer_high: int = 0
        self.length_ctr_load = 0

        self._length_ctr: int = 0

        # Create one table per duty cycle value
        self.sequence = [[(0, 0.), (7, 0.), (8, 1.), (16, 1.), (17, 0.)],  # 12.5% Duty
                         [(0, 0.), (7, 0.), (8, 1.), (24, 1.), (25, 0.)],  # 25% Duty
                         [(0, 0.), (7, 0.), (8, 1.), (40, 1.), (41, 0.)],  # 50% Duty
                         [(0, 1.), (7, 1.), (8, 0.), (16, 0.), (17, 1.)]]  # 75% Duty

        self.linear_table = pyo.LinTable(self.sequence[2], size=64)

        # Pulse wave output
        self.output = pyo.Osc(self.linear_table, 0, interp=1, mul=0)

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg0(self, value: int) -> None:
        """
        Writes a value to register 0 ($4000 / $4004)

        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        duty = value >> 6
        self.linear_table.replace(self.sequence[duty])

        self.length_ctr_halt = (value & 0x20) > 0
        if self.length_ctr_halt:
            self.length_ctr_load = 0

        self.constant_volume = (value & 0x10) > 0
        self.volume_envelope = value & 0x0F

        if self.constant_volume:
            self.output.setMul(_PULSE_VOLUME[self.volume_envelope])
        else:
            # TODO Envelope
            pass

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg1(self, value: int) -> None:
        """
        Writes a value to register 0 ($4000 / $4004)

        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        self.sweep_enabled = (value & 0x80) > 0

        self.sweep_period = (value >> 4) & 0x07

        self.sweep_negate = (value & 0x08) > 0

        self.sweep_shift = value & 0x07

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg2(self, value: int) -> None:
        """
        Writes a value to register 2 ($4002 / $4006)

        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        self.timer_low = value

        self.output.setFreq(1789773 / (((value | self.timer_high) + 1) << 4))

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg3(self, value: int) -> None:
        """
        Writes a value to register 3 ($4003 / $4007)

        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        self.timer_high = (value & 0x07) << 8
        self.length_ctr_load = value >> 3

        self.output.setFreq(1789773 / (((self.timer_high | self.timer_low) + 1) << 4))

        # TODO Restart envelope, if enabled

    # ------------------------------------------------------------------------------------------------------------------

    def half_frame(self) -> None:
        """
        Clocks the Sweep Unit and Length Counter (if enabled).
        """
        pass

    # ------------------------------------------------------------------------------------------------------------------

    def quarter_frame(self) -> None:
        """
        Clocks the Envelope for this channel (if enabled).
        """
        pass


# ----------------------------------------------------------------------------------------------------------------------

class TriangleChannel:
    def __init__(self):
        # Register 0 ($4008)
        self.control_flag: bool = False
        self.linear_ctr_reload_value: int = 0

        # Register 2 ($400A)
        self.timer_low: int = 0

        # Register 3 ($400B)
        self.timer_high: int = 0
        self.length_ctr_load: int = 0

        self._length_ctr: int = 0
        self._linear_ctr: int = 0
        self._linear_ctr_reload_flag: bool = False

        # --- Using LFO gives a full triangle wave ---
        self.output = pyo.LFO(freq=0, sharp=1, type=3, mul=0)

        # --- Or we can create a half-triangle using a linear table ---
        # seq = [(0, 1.), (31, 0.), (32, 0.), (63, 1.)]
        # self.linear_table = pyo.LinTable(seq, 64)
        # self.output = pyo.Osc(self.linear_table, freq=0, interp=0, mul=0)

        self.volume: float = 1.

    # ------------------------------------------------------------------------------------------------------------------

    def half_frame(self) -> None:
        """
        Clocks the Length Counter (if enabled).
        """
        if not self.control_flag:
            if self._length_ctr > 0:
                self._length_ctr -= 1

        if self._linear_ctr == 0 and self._length_ctr == 0:
            # Mute channel when the counter has reached zero
            if self.output.mul > 0:
                self.output.setMul(0)
        elif self.output.mul == 0:
            self.output.setMul(self.volume)

    # ------------------------------------------------------------------------------------------------------------------

    def quarter_frame(self) -> None:
        """
        Clocks the linear counter (if enabled).
        """
        if self._linear_ctr_reload_flag:
            self._linear_ctr = self.linear_ctr_reload_value
        elif self._linear_ctr > 0:
            self._linear_ctr -= 1

        if not self.control_flag:
            self._linear_ctr_reload_flag = False

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg0(self, value: int) -> None:
        """
        Writes a value to register 0 ($4008)

        Parameters
        ----------
        value: int
            Byte value to write to the register:
            C RRR RRRR
            C = Linear Counter Control Flag / Length Counter Halt Flag
             RRR RRRR = Linear Counter Reload Value
        """
        self.control_flag = (value & 0x80) > 0
        self._length_ctr = 0

        # self.output.setMul(self.volume)

        self.linear_ctr_reload_value = value & 0x7F

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg1(self, value: int) -> None:
        pass

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg2(self, value: int) -> None:
        """
        Writes a value to register 2 ($400A)

        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        self.timer_low = value

        self.output.setFreq(1789773 / (((value | self.timer_high) + 1) << 5))

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg3(self, value: int) -> None:
        """
        Writes a value to register 3 ($400B)

        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        self.timer_high = (value & 0x07) << 8
        self.length_ctr_load = _LENGTH_COUNTER_LOAD[value >> 3]

        self.output.setFreq(1789773 / (((self.timer_high | self.timer_low) + 1) << 5))

        self._linear_ctr_reload_flag = True
        if not self.control_flag:
            self._length_ctr = self.length_ctr_load
            # self.output.setMul(self.volume)


# ----------------------------------------------------------------------------------------------------------------------

class NoiseChannel:
    def __init__(self):
        # Register 0 ($400C)
        self.length_ctr_halt: bool = False
        self.constant_volume: bool = False
        self.volume_envelope: int = 0

        # Register 1 ($400E)
        self.mode: int = 0
        self.period: int = 0

        # Register 2 ($400F)
        self.length_ctr_load: int = 0

        self._length_ctr: int = 0

        # Nasty tricks will have to be used here...

        print("Generating noise wave tables...")

        seq_0 = []
        sr = 1
        prev_val = -1
        for i in range(0, 32767 * 2, 2):
            val = (sr & 1) ^ 1
            if val != prev_val:
                seq_0.append((i, val))
                seq_0.append((i + 1, val))

            feedback = ((sr & 1) ^ ((sr >> 1) & 1)) % 2
            sr = (sr >> 1) | (feedback << 14)

        seq_1 = []
        prev_val = -1
        for i in range(0, 93 * 2, 2):
            val = (sr & 1) ^ 1
            if val != prev_val:
                seq_1.append((i, val))
                seq_1.append((i + 1, val))

            feedback = ((sr & 1) ^ ((sr >> 6) & 1)) % 2
            sr = (sr >> 1) | (feedback << 14)

        self.table = []
        self.table.append(pyo.LinTable(seq_0, 32767 * 2))
        self.table.append(pyo.LinTable(seq_1, 93 * 2))

        print("...done!")

        self.output = pyo.Osc(self.table[0], freq=0, phase=0, interp=1, mul=0)

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg0(self, value: int) -> None:
        """
        Writes a value to Register 0 ($400C)
        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        self.length_ctr_halt = (value & 0x20) > 0
        if self.length_ctr_halt:
            self.length_ctr_load = 0

        self.constant_volume = (value & 0x10) > 0
        self.volume_envelope = value & 0x0F

        if self.constant_volume:
            self.output.setMul(_NOISE_VOLUME[self.volume_envelope])
        else:
            # TODO Envelope
            pass

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg1(self, value: int) -> None:
        pass

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg2(self, value: int) -> None:
        """
        Writes a value to register 2 ($400E)

        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        old_mode = self.mode

        self.mode = value >> 7
        self.period = value & 0x0F

        if old_mode != self.mode:
            self.output.setTable(self.table[self.mode])

        self.output.setFreq(_NOISE_FREQ[self.mode][self.period])

    # ------------------------------------------------------------------------------------------------------------------

    def write_reg3(self, value: int) -> None:
        """
        Writes a value to register 3 ($400F)

        Parameters
        ----------
        value: int
            Byte value to write to the register
        """
        self.length_ctr_load = value >> 3

        # TODO Restart envelope

    # ------------------------------------------------------------------------------------------------------------------

    def half_frame(self) -> None:
        """
        Clocks the Sweep Unit and Length Counter (if enabled).
        """
        pass

    # ------------------------------------------------------------------------------------------------------------------

    def quarter_frame(self) -> None:
        """
        Clocks the Envelope for this channel (if enabled).
        """
        pass


# ----------------------------------------------------------------------------------------------------------------------

class APU:

    # ------------------------------------------------------------------------------------------------------------------

    def __init__(self):
        self._ticks: int = 0

        self.pulse_0: PulseChannel = PulseChannel()
        self.pulse_1: PulseChannel = PulseChannel()
        self.triangle: TriangleChannel = TriangleChannel()
        self.noise: NoiseChannel = NoiseChannel()
        self.pattern: pyo.Pattern = pyo.Pattern(self.clock, time=0.004)

    # ------------------------------------------------------------------------------------------------------------------

    def reset(self) -> None:
        self.pulse_0.write_reg0(0x30)
        self.pulse_0.write_reg1(0)
        self.pulse_0.write_reg2(0)
        self.pulse_0.write_reg3(0)
        self.pulse_1.write_reg0(0x30)
        self.pulse_1.write_reg1(0)
        self.pulse_1.write_reg2(0)
        self.pulse_1.write_reg3(0)
        self.triangle.write_reg0(0x80)
        self.triangle.write_reg2(0)
        self.triangle.write_reg3(0)
        self.noise.write_reg0(0x30)
        self.noise.write_reg2(0)
        self.noise.write_reg3(0)

    # ------------------------------------------------------------------------------------------------------------------

    def play(self) -> None:
        if not self.pulse_0.output.isOutputting():
            self.pulse_0.output.out()
        if not self.pulse_1.output.isOutputting():
            self.pulse_1.output.out()
        if not self.triangle.output.isOutputting():
            self.triangle.output.out()
        if not self.noise.output.isOutputting():
            self.noise.output.out()
        if not self.pattern.isPlaying():
            self.pattern.play()

    # ------------------------------------------------------------------------------------------------------------------

    def stop(self) -> None:
        if self.pattern.isPlaying():
            self.pattern.stop()
        if self.pulse_0.output.isOutputting():
            self.pulse_0.output.stop()
        if self.pulse_1.output.isOutputting():
            self.pulse_1.output.stop()
        if self.triangle.output.isOutputting():
            self.triangle.output.stop()
        if self.noise.output.isOutputting():
            self.noise.output.stop()

    # ------------------------------------------------------------------------------------------------------------------

    def clock(self) -> None:
        """
        250 Hz clock: call this 250 times / sec, or every 0.004 seconds (4ms).
        """

        # Clock envelopes
        self.pulse_0.quarter_frame()
        self.pulse_1.quarter_frame()
        self.triangle.quarter_frame()
        self.noise.quarter_frame()

        self._ticks += 1
        if self._ticks > 3:
            self._ticks = 0

        elif self._ticks == 1 or self._ticks == 3:
            self.pulse_0.half_frame()
            self.pulse_1.half_frame()
            self.triangle.half_frame()
            self.noise.half_frame()

    # ------------------------------------------------------------------------------------------------------------------

    def set_triangle_volume(self, value: float) -> None:
        if value > 1.:
            value = 1.
        elif value < 0.:
            value = 0.

        self.triangle.volume = value
