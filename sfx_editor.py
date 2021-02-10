__author__ = "Fox Cunning"

import configparser
import os
import threading
import time
import tkinter
from typing import Optional, Tuple, List

import appJar
import colour
from APU.APU import APU
from debug import log
from editor_settings import EditorSettings
# ----------------------------------------------------------------------------------------------------------------------
from music_editor import MusicEditor
from rom import ROM

_NOISE_FREQ_TABLE = [4811.2, 2405.6, 1202.8, 601.4, 300.7, 200.5, 150.4, 120.3,
                     95.3, 75.8, 50.6, 37.9, 25.3, 18.9, 9.5, 4.7]

_VOLUME_TABLE = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75]


class SFXEditor:

    # ------------------------------------------------------------------------------------------------------------------

    def __init__(self, app: appJar.gui, settings: EditorSettings, rom: ROM, music_editor: MusicEditor):
        self.app = app
        self.rom = rom
        self.settings = settings

        # We need to access the Pyo server, and stop music playback before playing a SFX
        self._music_editor = music_editor

        self.sfx_names: List[str] = []

        self._unsaved_changes: bool = False

        self._sfx_id = -1

        # Values from the four-byte sfx entries table
        self._volume_only: bool = False
        self._channel: int = 0
        self._size: int = 0
        self._address: int = 0

        # First four bytes from sound data
        self._setup_values: bytearray = bytearray()

        # The rest of the data
        self._sfx_data: bytearray = bytearray()

        self.apu: APU = APU()

        self._play_thread: threading.Thread = threading.Thread()
        self._playing: bool = True

        # Playback: current position in the data array
        self._sfx_pos: int = 0

        # Canvas reference and item IDs
        self._canvas_sfx: tkinter.Canvas = tkinter.Canvas()
        self._volume_line: int = 0
        self._timer_line: int = 0

        # Detect and fix data size bug
        if self.rom.read_word(0x9, 0xA007) == 0x76A8:
            self.info("Fixing SFX data size bug.")
            data = [0x29, 0x03, 0x0A, 0x0A, 0xAA, 0xB9, 0x6B, 0xA1, 0x9D, 0xA8, 0x76, 0xC8, 0xB9, 0x6B, 0xA1, 0x9D,
                    0x9B, 0x76, 0xC8, 0xB9, 0x6B, 0xA1, 0x9D, 0x98, 0x76, 0xC8, 0xB9, 0x6B, 0xA1, 0x9D, 0x99, 0x76,
                    0xC8, 0xBD, 0x98, 0x76, 0x85, 0xF0, 0xBD, 0x99, 0x76, 0x85, 0xF1, 0xA0, 0x00, 0xB1, 0xF0, 0x9D,
                    0x00, 0x40, 0xC8, 0xB1, 0xF0, 0x9D, 0x01, 0x40, 0xC8, 0xB1, 0xF0, 0x9D, 0x02, 0x40, 0xC8, 0xB1,
                    0xF0, 0x9D, 0x03, 0x40, 0xC8, 0x98, 0x9D, 0x9A, 0x76, 0x60]
            self.rom.write_bytes(0x9, 0xA006, bytearray(data))

    # ------------------------------------------------------------------------------------------------------------------

    def error(self, message: str):
        log(2, f"{self.__class__.__name__}", message)

    # ------------------------------------------------------------------------------------------------------------------

    def warning(self, message: str):
        log(3, f"{self.__class__.__name__}", message)

    # ------------------------------------------------------------------------------------------------------------------

    def info(self, message: str):
        log(4, f"{self.__class__.__name__}", message)

    # ------------------------------------------------------------------------------------------------------------------

    def close_window(self) -> bool:
        self._unsaved_changes = False

        self.app.emptySubWindow("SFX_Editor")
        self._volume_line = 0
        self._timer_line = 0

        if self._play_thread.is_alive():
            self._size = 0
            self._play_thread.join(500)
        if self._play_thread.is_alive():
            self.warning("Could not stop audio playback thread!")

        # self.app.destroySubWindow("SFX_Editor")
        self.app.hideSubWindow("SFX_Editor", useStopFunction=False)

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def show_window(self, sfx_id: int) -> None:
        """
        Parameters
        ----------
        sfx_id: int
            Index of the sound effect to edit
        """
        self._sfx_id = sfx_id

        # Check if window already exists
        try:
            self.app.openSubWindow("SFX_Editor")
            self.close_window()
            generator = self.app.subWindow("SFX_Editor")

        except appJar.appjar.ItemLookupError:
            self._volume_line = 0
            self._timer_line = 0

            generator = self.app.subWindow("SFX_Editor", size=[600, 460], padding=[2, 2], title="Sound Effect Editor",
                                           resizable=False, modal=False, blocking=False,
                                           bg=colour.DARK_ORANGE, fg=colour.WHITE, stopFunction=self.close_window)

        with generator:
            with self.app.frame("XE_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0, colspan=2):
                self.app.button("XE_Apply", self._sfx_input, image="res/floppy.gif", bg=colour.LIGHT_ORANGE,
                                row=0, column=1)
                self.app.button("XE_Reload", self._sfx_input, image="res/reload.gif", bg=colour.LIGHT_ORANGE,
                                row=0, column=2)
                self.app.button("XE_Close", self._sfx_input, image="res/close.gif", bg=colour.LIGHT_ORANGE,
                                row=0, column=3)

                self.app.label("XE_Label_SFX_Name", "Name:", sticky="WE", row=0, column=4, font=11)
                self.app.entry("XE_SFX_Name", f"{self.sfx_names[sfx_id]}", bg=colour.MEDIUM_ORANGE, fg=colour.WHITE,
                               row=0, column=5, width=20, font=12)

                self.app.button("XE_Play_Stop", self._sfx_input, image="res/play.gif", bg=colour.LIGHT_ORANGE,
                                row=0, column=6)

            with self.app.frame("XE_Frame_Setup", padding=[2, 2], sticky="NW", row=1, column=0):
                self.app.label("XE_Label_Channel_0", "Channel", sticky="W",
                               row=0, column=0, font=11)
                self.app.button("XE_Channel_0", self._sfx_input, image="res/square_0.gif", bg=colour.LIGHT_ORANGE,
                                row=0, column=1)
                self.app.button("XE_Channel_1", self._sfx_input, image="res/square_1.gif", bg=colour.DARK_ORANGE,
                                row=0, column=2)
                self.app.button("XE_Channel_2", self._sfx_input, image="res/triangle_wave.gif", bg=colour.DARK_ORANGE,
                                row=0, column=3)
                self.app.button("XE_Channel_3", self._sfx_input, image="res/noise_wave.gif", bg=colour.DARK_ORANGE,
                                row=0, column=4)

                self.app.label("XE_Label_Channel_1", "Setup values:", sticky="SEW", row=1, column=0, colspan=5, font=11)

                with self.app.frameStack("XE_Stack_Channel", sticky="NW", row=2, column=0, colspan=5):
                    # Square channels setup panel ----------------------------------------------------------------------
                    with self.app.frame("XE_Frame_Square_Setup", padding=[2, 1],
                                        bg=colour.DARK_ORANGE, fg=colour.WHITE):
                        self.app.label("XE_Label_S0", "Duty Cycle", sticky="E", row=0, column=0, font=10)
                        self.app.optionBox("XE_Duty_Cycle", ["12.5%", "25%", "50%", "75%"], width=12, sticky="W",
                                           row=0, column=1, font=9, change=self._sfx_input)
                        self.app.label("XE_Pulse_Label_LC_Flag", "Length Ctr Halt", sticky="E",
                                       row=1, column=0, font=10)
                        self.app.checkBox("XE_Pulse_LC_Flag", True, name="", sticky="W",
                                          selectcolor=colour.MEDIUM_ORANGE, change=self._sfx_input,
                                          row=1, column=1)
                        self.app.label("XE_Pulse_Label_CV_Flag", "Constant Volume", sticky="E",
                                       row=2, column=0, font=10)
                        self.app.checkBox("XE_Pulse_CV_Flag", True, name="", sticky="W",
                                          selectcolor=colour.MEDIUM_ORANGE, change=self._sfx_input,
                                          row=2, column=1)
                        self.app.label("XE_Pulse_Label_0", "Volume: 00", sticky="SE", row=3, column=0, font=10)
                        self.app.scale("XE_Pulse_Volume", direction="horizontal", range=[0, 15], value=0, increment=1,
                                       sticky="W", show=False, bg=colour.DARK_ORANGE,
                                       row=3, column=1, font=9).bind("<ButtonRelease-1>", lambda _e:
                                                                     self._sfx_input("XE_Pulse_Volume"))
                        self.app.label("XE_Label_Sweep_Enabled", "Enable Sweep", sticky="E",
                                       row=4, column=0, font=10)
                        self.app.checkBox("XE_Sweep_Enable", False, name="", sticky="W",
                                          selectcolor=colour.MEDIUM_ORANGE, change=self._sfx_input,
                                          row=4, column=1)
                        self.app.label("XE_Pulse_Label_1", "Sweep Period: 00", sticky="SE", row=5, column=0, font=10)
                        self.app.scale("XE_Sweep_Period", direction="horizontal", range=[0, 7], value=0, increment=1,
                                       sticky="W", show=False, bg=colour.DARK_ORANGE,
                                       row=5, column=1, font=9).bind("<ButtonRelease-1>", lambda _e:
                                                                     self._sfx_input("XE_Sweep_Period"))
                        self.app.label("XE_Label_Sweep_Negate", "Negative Sweep", sticky="E",
                                       row=6, column=0, font=10)
                        self.app.checkBox("XE_Sweep_Negate", False, name="", sticky="W",
                                          selectcolor=colour.MEDIUM_ORANGE, change=self._sfx_input,
                                          row=6, column=1)
                        self.app.label("XE_Pulse_Label_2", "Shift Count: 00", sticky="SE", row=7, column=0, font=10)
                        self.app.scale("XE_Sweep_Shift", direction="horizontal", range=[0, 7], value=0, increment=1,
                                       sticky="W", show=False, bg=colour.DARK_ORANGE,
                                       row=7, column=1, font=9).bind("<ButtonRelease-1>", lambda _e:
                                                                     self._sfx_input("XE_Sweep_Shift"))
                        self.app.label("XE_Pulse_Label_3", "Timer Value", sticky="E", row=8, column=0, font=10)
                        self.app.entry("XE_Pulse_Timer", 0, change=self._sfx_input, width=6, sticky="W",
                                       kind="numeric", limit=5,
                                       row=8, column=1, font=9, bg=colour.MEDIUM_ORANGE, fg=colour.WHITE)
                        self.app.label("XE_Pulse_Freq", "Frequency: 0.000 Hz", sticky="WE",
                                       row=9, column=0, colspan=2, font=10, fg=colour.LIGHT_LIME)
                        self.app.label("XE_Pulse_Label_4", "Length Ctr Load: 00", sticky="SE",
                                       row=10, column=0, font=10)
                        self.app.scale("XE_Pulse_Length_Load", direction="horizontal", range=[0, 31], value=0,
                                       increment=1, sticky="W", show=False, bg=colour.DARK_ORANGE,
                                       row=10, column=1, font=9).bind("<ButtonRelease-1>", lambda _e:
                                                                      self._sfx_input("XE_Pulse_Length_Load"))
                    # Triangle channel setup panel ---------------------------------------------------------------------
                    with self.app.frame("XE_Frame_Triangle_Setup", padding=[2, 2],
                                        bg=colour.DARK_ORANGE, fg=colour.WHITE):
                        self.app.label("XE_Triangle_Label_Control_Flag", "Control Flag", sticky="E",
                                       row=0, column=0, font=10)
                        self.app.checkBox("XE_Triangle_Control_Flag", name="", sticky="W",
                                          selectcolor=colour.MEDIUM_ORANGE, change=self._sfx_input,
                                          row=0, column=1)
                        self.app.label("XE_Triangle_Label_0", "Linear Ctr Load", sticky="NE", row=1, column=0, font=10)
                        self.app.entry("XE_Linear_Load", 0, change=self._sfx_input, width=6, sticky="NW",
                                       kind="numeric", limit=5,
                                       row=1, column=1, font=9, bg=colour.MEDIUM_ORANGE, fg=colour.WHITE)
                        self.app.label("XE_Triangle_Label_1", "Timer Value", sticky="NE", row=2, column=0, font=10)
                        self.app.entry("XE_Triangle_Timer", 0, change=self._sfx_input, width=6, sticky="NW",
                                       kind="numeric", limit=5,
                                       row=2, column=1, font=9, bg=colour.MEDIUM_ORANGE, fg=colour.WHITE)
                        self.app.label("XE_Triangle_Freq", "Frequency: 0 Hz", sticky="NEW",
                                       row=3, column=0, colspan=2, font=10, fg=colour.LIGHT_LIME)
                        self.app.label("XE_Triangle_Label_2", "Length Ctr Reload", sticky="NE",
                                       row=4, column=0, font=10)
                        self.app.entry("XE_Triangle_Length_Load", 0, change=self._sfx_input, width=6, sticky="NW",
                                       kind="numeric", limit=5,
                                       row=4, column=1, font=9, bg=colour.MEDIUM_ORANGE, fg=colour.WHITE)
                    # Noise channel setup panel ------------------------------------------------------------------------
                    with self.app.frame("XE_Frame_Noise_Setup", padding=[2, 2],
                                        bg=colour.DARK_ORANGE, fg=colour.WHITE):
                        self.app.label("XE_Noise_Label_LC_Flag", "LC Halt", sticky="E", row=0, column=0, font=10)
                        self.app.checkBox("XE_Noise_LC_Flag", False, name="", sticky="W",
                                          selectcolor=colour.MEDIUM_ORANGE, change=self._sfx_input,
                                          row=0, column=1)
                        self.app.label("XE_Noise_Label_CV_Flag", "Constant Volume", sticky="E",
                                       row=1, column=0, font=10)
                        self.app.checkBox("XE_Noise_CV_Flag", True, name="", sticky="W",
                                          selectcolor=colour.MEDIUM_ORANGE, change=self._sfx_input,
                                          row=1, column=1)
                        self.app.label("XE_Noise_Label_0", "Volume: 00", sticky="NE", row=2, column=0, font=10)
                        self.app.scale("XE_Noise_Volume", direction="horizontal", range=[0, 15], value=0, increment=1,
                                       sticky="NW", show=False, bg=colour.DARK_ORANGE,
                                       row=2, column=1, font=9).bind("<ButtonRelease-1>", lambda _e:
                                                                     self._sfx_input("XE_Noise_Volume"))
                        self.app.label("XE_Label_Noise_Loop", "Loop Noise", sticky="E", row=3, column=0, font=10)
                        self.app.checkBox("XE_Noise_Loop", True, name="", sticky="W",
                                          selectcolor=colour.MEDIUM_ORANGE, change=self._sfx_input,
                                          row=3, column=1)
                        self.app.label("XE_Noise_Label_1", "Noise Period: 00", sticky="NE", row=4, column=0, font=10)
                        self.app.scale("XE_Noise_Period", direction="horizontal", range=[0, 15], value=0, increment=1,
                                       sticky="NW", show=False, bg=colour.DARK_ORANGE,
                                       row=4, column=1, font=9).bind("<ButtonRelease-1>", lambda _e:
                                                                     self._sfx_input("XE_Noise_Period"))
                        self.app.label("XE_Noise_Freq", "Frequency: 0.00 Hz", sticky="WE",
                                       row=5, column=0, colspan=2, font=10, fg=colour.LIGHT_LIME)
                        self.app.label("XE_Noise_Label_2", "Length Ctr Load: 00", sticky="NE",
                                       row=6, column=0, font=10)
                        self.app.scale("XE_Noise_Load", direction="horizontal", range=[0, 31], value=0, increment=1,
                                       sticky="NW", show=False, bg=colour.DARK_ORANGE,
                                       row=6, column=1, font=9).bind("<ButtonRelease-1>", lambda _e:
                                                                     self._sfx_input("XE_Noise_Load"))

            # Data entry selection -------------------------------------------------------------------------------------
            with self.app.frame("XE_Frame_Data", sticky="NW", padding=[2, 2], row=1, column=1):
                with self.app.frame("XE_Frame_Data_Left", sticky="W", padding=[2, 2], row=0, column=0):
                    self.app.label("XE_Data_Label_0", "Data Size", sticky="W", row=0, column=0, font=10)
                    self.app.entry("XE_Data_Size", 1, kind="numeric", limit=4, width=4, sticky="W",
                                   row=0, column=1, font=9, submit=self._sfx_input)
                    self.app.listBox("XE_Data_List", [], width=12, height=10, sticky="W", change=self._sfx_input,
                                     bg=colour.MEDIUM_ORANGE, fg=colour.WHITE,
                                     row=1, column=0, colspan=2, multi=False, group=True, font=9)

                # Data controls ----------------------------------------------------------------------------------------
                with self.app.frame("XE_Frame_Data_Right", sticky="WE", padding=[2, 2], row=0, column=1):

                    # --- Register 0

                    self.app.label("XE_Data_Label_1", "Duty", sticky="NEW", row=0, column=0, font=10)
                    self.app.optionBox("XE_Data_Duty", ["12.5%", "25%", "50%", "75%"], change=self._data_input,
                                       row=0, column=1, width=8, sticky="NW", font=9)

                    self.app.checkBox("XE_Data_LC_Flag", True, name="Length Ctr Halt", sticky="NW",
                                      selectcolor=colour.MEDIUM_ORANGE, change=self._data_input,
                                      row=1, column=0, colspan=2, font=10)
                    self.app.checkBox("XE_Data_CV_Flag", True, name="Constant Volume", sticky="NW",
                                      selectcolor=colour.MEDIUM_ORANGE, change=self._data_input,
                                      row=2, column=0, colspan=2, font=10)

                    self.app.label("XE_Data_Label_2", "Volume: 00", sticky="NE", row=3, column=0, font=10)
                    self.app.scale("XE_Data_Reg_0", direction="horizontal", range=[0, 15], value=0, increment=1,
                                   sticky="NW", show=False, bg=colour.DARK_ORANGE,
                                   row=3, column=1, font=9).bind("<ButtonRelease-1>", lambda _e:
                                                                 self._data_input("XE_Data_Reg_0"))

                    # --- Register 2

                    self.app.checkBox("XE_Data_Noise_Mode", False, text="Loop Noise", sticky="NW",
                                      selectcolor=colour.MEDIUM_ORANGE, change=self._data_input,
                                      row=4, column=0, colspan=2, font=10)

                    self.app.label("XE_Data_Label_3", "Period Value", sticky="NE", row=5, column=0, font=10)
                    self.app.entry("XE_Data_Reg_2", 0, change=self._data_input, width=6, sticky="NW",
                                   kind="numeric", limit=5,
                                   row=5, column=1, font=9, bg=colour.MEDIUM_ORANGE, fg=colour.WHITE)
                    self.app.label("XE_Data_Freq", "Frequency: 0 Hz", sticky="NEW",
                                   row=6, column=0, colspan=2, font=10, fg=colour.LIGHT_LIME)

                # Volume / Timer envelope Graph

                with self.app.frame("XE_Frame_Data_Bottom", sticky="W", padding=[1, 1], row=1, column=0, colspan=2):
                    self.app.canvas("XE_Canvas_SFX", map=None, width=320, height=200, bg=colour.BLACK,
                                    row=0, column=0)

        self._canvas_sfx = self.app.getCanvasWidget("XE_Canvas_SFX")

        self.read_sfx_data()

        self._sfx_info()

        # Draw graph
        self._draw_sfx_graph()

        self.app.showSubWindow("SFX_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def _get_selection_index(self, widget: str) -> int:
        """
        Returns
        -------
        int:
            The index of the currently selected option from an OptionBox widget
        """
        value = "(nothing)"
        try:
            value = self.app.getOptionBox(widget)
            box = self.app.getOptionBoxWidget(widget)
            return box.options.index(value)
        except ValueError as error:
            self.error(f"ERROR: Getting selection index for '{value}' in '{widget}': {error}.")
            return 0

    # ------------------------------------------------------------------------------------------------------------------

    def _data_input(self, widget: str) -> None:
        # Get the selection index and calculate the position in the array depending on whether we use the first byte
        # only or both bytes
        selection = self.app.getListBoxPos("XE_Data_List")
        if len(selection) < 1:
            pos = 0
            index = 0
        else:
            index = selection[0]
            pos = selection[0] * (1 if self._volume_only else 2)

        # Process event according to which widget has generated it

        if widget == "XE_Data_Duty":    # ------------------------------------------------------------------------------
            value = self._get_selection_index(widget)

            reg_value = self._sfx_data[pos] & 0x3F
            self._sfx_data[pos] = reg_value | (value << 6)

            self._unsaved_changes = True
            self._update_data_list(index)
            self._draw_sfx_graph(draw_period=False)

        elif widget == "XE_Data_LC_Flag":   # --------------------------------------------------------------------------
            flag = self.app.getCheckBox(widget)

            # For the Triangle channel, this is the Control flag instead
            if self._channel == 2:
                reg_value = self._sfx_data[pos] & 0x7F
                self._sfx_data[pos] = reg_value | (0x80 if flag else 0)

            else:
                reg_value = self._sfx_data[pos] & 0xDF

                self._sfx_data[pos] = reg_value | (0x20 if flag else 0)

                # There is no Length Counter Load control to enable/disable: the second byte only controls the period

            self._unsaved_changes = True
            self._update_data_list(index)

        elif widget == "XE_Data_CV_Flag":   # --------------------------------------------------------------------------
            flag = self.app.getCheckBox(widget)

            reg_value = self._sfx_data[pos] & 0xEF
            self._sfx_data[pos] = reg_value | (0x10 if flag else 0)

            # Switch between volume and envelope labels
            volume = self._sfx_data[pos] & 0x0F
            if (self._sfx_data[pos] & 0x10) > 0:
                # Constant Volume
                self.app.setLabel("XE_Data_Label_2", f"  Volume: {volume:02}")
            else:
                # Envelope Enabled
                self.app.setLabel("XE_Data_Label_2", f"Envelope: {volume:02}")

            self._unsaved_changes = True
            self._update_data_list(index)
            self._draw_sfx_graph(draw_period=False)

        elif widget == "XE_Data_Reg_0":     # --------------------------------------------------------------------------
            value = self.app.getScale(widget)

            reg_value = self._sfx_data[pos] & 0xF0
            self._sfx_data[pos] = reg_value | value

            if (self._sfx_data[pos] & 0x10) > 0:
                # Constant Volume
                self.app.setLabel("XE_Data_Label_2", f"  Volume: {value:02}")
            else:
                # Envelope Enabled
                self.app.setLabel("XE_Data_Label_2", f"Envelope: {value:02}")

            self._unsaved_changes = True
            self._update_data_list(index)
            self._draw_sfx_graph(draw_period=False)

        elif widget == "XE_Data_Noise_Mode":    # ----------------------------------------------------------------------
            pos += 1
            flag = self.app.getCheckBox(widget)

            reg_value = self._sfx_data[pos] & 0x7F
            self._sfx_data[pos] = reg_value | (0x80 if flag else 0)

            # Update frequency
            period = self._sfx_data[pos] & 0x0F

            freq = round(_NOISE_FREQ_TABLE[period] / (1 if flag else 93), 2)
            self.app.setLabel("XE_Data_Freq", f"Frequency: {freq} Hz")

            self._unsaved_changes = True
            self._update_data_list(index)
            self._draw_sfx_graph(draw_volume=False)

        elif widget == "XE_Data_Reg_2":     # --------------------------------------------------------------------------
            pos += 1

            value = self.app.getEntry(widget)
            if value is None:
                return

            # The Noise channel treats the period value differently
            if self._channel == 3:
                period = int(value) & 0x0F

                # Mode flag
                flag = (self._sfx_data[pos] & 0x80) > 0

                reg_value = self._sfx_data[pos] & 0xF0
                self._sfx_data[pos] = reg_value | period

                # Update frequency display
                freq = round(_NOISE_FREQ_TABLE[period] / (1 if flag else 93), 2)

            # For all other channels, we need the whole timer value in order to display the correct frequency
            else:
                self._sfx_data[pos] = int(value) & 0xFF

                timer = ((self._setup_values[3] & 0x07) << 8) | self._sfx_data[pos]
                freq = round(1789773 / ((timer + 1) << (5 if self._channel == 2 else 4)), 2)

            self.app.setLabel("XE_Data_Freq", f"Frequency: {freq} Hz")
            self._unsaved_changes = True
            self._update_data_list(index)
            self._draw_sfx_graph(draw_volume=False)

        else:   # ------------------------------------------------------------------------------------------------------
            self.info(f"Unimplemented input from setup widget: '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _sfx_input(self, widget: str) -> None:
        if widget == "XE_Apply":    # ----------------------------------------------------------------------------------
            if self.save_sfx_data():
                self.app.setStatusbar("Sound effects saved")
                self._unsaved_changes = False
                if self.settings.get("close sub-window after saving"):
                    self.app.hideSubWindow("SFX_Editor", useStopFunction=True)

        elif widget == "XE_Close":  # ----------------------------------------------------------------------------------
            if self._unsaved_changes:
                if not self.app.yesNoBox("SFX Editor", "Are you sure you want to close this window?\n" +
                                                       "Any unsaved changes will be lost.", "SFX_Editor"):
                    return

            self._unsaved_changes = False
            self.app.hideSubWindow("SFX_Editor", useStopFunction=True)

        elif widget == "XE_Play_Stop":  # ------------------------------------------------------------------------------
            if self._play_thread.is_alive():
                self.stop_playback()
            else:
                self.app.setButtonImage("XE_Play_Stop", "res/stop.gif")
                self.app.setButtonTooltip("XE_Play_Stop", "Stop playback")
                self._play_sfx()

        elif widget[:11] == "XE_Channel_":  # --------------------------------------------------------------------------
            new_channel = int(widget[-1], 10)
            if new_channel != self._channel:
                self._channel = new_channel
                self._sfx_info()

                selection = self.app.getListBoxPos("XE_Data_List")
                if len(selection) > 0:
                    self._event_info(selection[0])

                self._draw_sfx_graph()

                self._unsaved_changes = True

        elif widget == "XE_Duty_Cycle":     # --------------------------------------------------------------------------
            value = self._get_selection_index(widget)

            if value == self._setup_values[0] >> 6:
                # No change
                return

            register_value = self._setup_values[0] & 0x3F
            self._setup_values[0] = (value << 6) | register_value

            self._draw_sfx_graph(draw_period=False)
            self._unsaved_changes = True

        elif widget == "XE_Pulse_LC_Flag":  # --------------------------------------------------------------------------
            flag = self.app.getCheckBox(widget)

            if flag == (self._setup_values[0] & 0x20) > 0:
                # No change
                return

            register_value = self._setup_values[0] & 0xDF
            self._setup_values[0] = register_value | (0x20 if flag else 0)

            if flag:
                self.app.disableScale("XE_Pulse_Length_Load")
            else:
                self.app.enableScale("XE_Pulse_Length_Load")

            # This only affects the duration of the sound, so no need to redraw the graph

            self._unsaved_changes = True

        elif widget == "XE_Pulse_CV_Flag":  # --------------------------------------------------------------------------
            flag = self.app.getCheckBox(widget)

            if flag == ((self._setup_values[0] & 0x10) > 0):
                # No change
                return

            register_value = self._setup_values[0] & 0xEF
            self._setup_values[0] = register_value | (0x10 if flag else 0)

            value = self._setup_values[0] & 0x0F
            self.app.setLabel("XE_Pulse_Label_0", f"{'Volume' if flag else 'Env. Period'}: {value:02}")

            self._draw_sfx_graph(draw_period=False)
            self._unsaved_changes = True

        elif widget == "XE_Pulse_Volume":   # --------------------------------------------------------------------------
            value = self.app.getScale(widget) & 0x0F
            register_value = self._setup_values[0] & 0xF0   # The other bits in the same register

            flag = (self._setup_values[0] & 0x10) > 0
            self.app.setLabel("XE_Pulse_Label_0", f"{'Volume' if flag else 'Env. Period'}: {value:02}")

            self._setup_values[0] = register_value | value

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_period=False)

        elif widget == "XE_Sweep_Enable":   # --------------------------------------------------------------------------
            flag = self.app.getCheckBox(widget)

            if flag == ((self._setup_values[1] & 0x80) > 0):
                return

            register_value = self._setup_values[1] & 0x7F
            self._setup_values[1] = register_value | (0x80 if flag else 0)

            if flag:
                self.app.enableScale("XE_Sweep_Period")
                self.app.enableScale("XE_Sweep_Shift")
            else:
                self.app.disableScale("XE_Sweep_Period")
                self.app.disableScale("XE_Sweep_Shift")

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_volume=False)

        elif widget == "XE_Sweep_Period":   # --------------------------------------------------------------------------
            value = self.app.getScale(widget)

            if value == (self._setup_values[1] & 0x70) >> 4:
                return

            register_value = self._setup_values[1] & 0x8F
            self._setup_values = register_value | (value << 4)

            self.app.setLabel("XE_Pulse_Label_1", f"Sweep Period: {value:02}")

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_volume=False)

        elif widget == "XE_Sweep_Negate":   # --------------------------------------------------------------------------
            flag = self.app.getCheckBox(widget)

            if flag == ((self._setup_values[1] & 0x1) > 0):
                return

            register_value = self._setup_values[1] & 0xF7
            self._setup_values[1] = register_value | (0x08 if flag else 0)

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_volume=False)

        elif widget == "XE_Sweep_Shift":    # --------------------------------------------------------------------------
            value = self.app.getScale(widget)

            if value == self._setup_values[1] & 0x07:
                return

            register_value = self._setup_values[1] & 0xF8
            self._setup_values[1] = register_value | value

            self.app.setLabel("XE_Pulse_Label_2", f"Shift Count: {value:02}")

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_volume=False)

        elif widget == "XE_Pulse_Timer":    # --------------------------------------------------------------------------
            try:
                value = int(self.app.getEntry(widget)) & 0x7FF
                self._setup_values[2] = value & 0x0FF
                self._setup_values[3] = (self._setup_values[3] & 0xF8) | (value >> 8)

                freq: float = 1789773 / ((value + 1) << 4)
                self.app.setLabel("XE_Pulse_Freq", f"Frequency: {round(freq, 2)} Hz")
            except TypeError:
                return

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_volume=False)

        elif widget == "XE_Pulse_Length_Load":  # ----------------------------------------------------------------------
            value = self.app.getScale(widget)
            register_value = self._setup_values[3] & 0xF8

            self.app.setLabel("XE_Pulse_Label_4", f"Length Ctr Load: {value:02}")

            self._setup_values[3] = register_value | (value << 3)

            self._unsaved_changes = True

        elif widget == "XE_Triangle_Control_Flag":  # ------------------------------------------------------------------
            flag = self.app.getCheckBox(widget)

            if flag == ((self._setup_values[0] & 0x80) > 0):
                return

            register_value = self._setup_values[0] & 0x7F
            self._setup_values[0] = register_value | (0x80 if flag else 0)

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_period=False)

        elif widget == "XE_Linear_Load":    # --------------------------------------------------------------------------
            value = self.app.getEntry(widget)

            if value is None or int(value) == self._setup_values[0] & 0x7F:
                return

            register_value = self._setup_values[0] & 0x80
            self._setup_values[0] = register_value | int(value)

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_period=False)

        elif widget == "XE_Triangle_Timer":     # ----------------------------------------------------------------------
            value = self.app.getEntry(widget)

            if value is None:
                return

            timer_low = int(value) & 0x0FF
            timer_high = int(value) >> 8

            self._setup_values[2] = timer_low
            self._setup_values[3] = (self._setup_values[3] & 0xF8) | timer_high

            freq = 1789773 / (int(value + 1) << 5)

            self.app.setLabel("XE_Triangle_Freq", f"Frequency: {round(freq, 2)} Hz")

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_volume=False)

        elif widget == "XE_Noise_LC_Flag":  # --------------------------------------------------------------------------
            value = 0x20 if self.app.getCheckBox(widget) else 0x00

            if value == 0:
                self.app.enableScale("XE_Noise_Load")
            else:
                self.app.disableScale("XE_Noise_Load")

            self._setup_values[0] = (self._setup_values[0] & 0x1F) | value

            self._unsaved_changes = True

        elif widget == "XE_Noise_CV_Flag":  # --------------------------------------------------------------------------
            value = 0x10 if self.app.getCheckBox(widget) else 0x00
            volume = self._setup_values[0] & 0x0F

            if value == 0:
                # If the Constant Volume flag is clear, than this is the envelope period instead of volume
                self.app.setLabel("XE_Noise_Label_0", f"Env. Period: {volume:02}")
            else:
                self.app.setLabel("XE_Noise_Label_0", f"Volume: {volume:02}")

            self._setup_values[0] = (self._setup_values[0] & 0x2F) | value

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_period=False)

        elif widget == "XE_Noise_Volume":   # --------------------------------------------------------------------------
            value: int = self.app.getScale(widget)

            # If the Constant Volume flag is clear, than this is the envelope period instead of volume
            if (self._setup_values[0] & 0x10) > 0:
                self.app.setLabel("XE_Noise_Label_0", f"Volume: {value:02}")
            else:
                self.app.setLabel("XE_Noise_Label_0", f"Env. Period: {value:02}")

            self._setup_values[0] = (self._setup_values[0] & 0xF0) | (value & 0x0F)

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_period=False)

        elif widget == "XE_Noise_Loop":
            value = 0x80 if self.app.getCheckBox(widget) else 0x00

            self._setup_values[2] = (self._setup_values[2] & 0x0F) | value

            self._unsaved_changes = True

        elif widget == "XE_Noise_Period":   # --------------------------------------------------------------------------
            value: int = self.app.getScale(widget)
            freq = _NOISE_FREQ_TABLE[value]

            self.app.setLabel("XE_Noise_Label_1", f"Period: {value:02}")
            self.app.setLabel("XE_Noise_Freq", f"Frequency: {freq} Hz")

            self._setup_values[2] = (self._setup_values[0] & 0xF0) | value

            self._unsaved_changes = True
            self._draw_sfx_graph(draw_volume=False)

        elif widget == "XE_Noise_Load":     # --------------------------------------------------------------------------
            value = self.app.getScale(widget)
            self.app.setLabel("XE_Noise_Label_2", f"Length Ctr Load: {value:02}")

            self._setup_values[3] = value << 3

            self._unsaved_changes = True

        elif widget == "XE_Data_Size":  # ------------------------------------------------------------------------------
            value = self.app.getEntry(widget)

            if value is None or int(value) == self._size or value < 1 or value > 64:
                return

            if value < self._size:
                if not self.app.yesNoBox("SFX Editor", "Are you sure you want to reduce sound data size?\n" +
                                         "The extra events will be permanently deleted.", "SFX_Editor"):
                    return

                # Decrease size
                byte_size = int(value) * (1 if self._volume_only else 2)
                self._sfx_data = self._sfx_data[0:byte_size]

            else:
                # Increase size, create copy of last event to fill the rest
                new_events = self._sfx_data[-1:] if self._volume_only else self._sfx_data[-2:]
                diff = int(value) - self._size
                self._sfx_data = self._sfx_data + (new_events * diff)

            self._size = int(value)
            self._update_data_list()
            self._draw_sfx_graph()

        elif widget == "XE_Data_List":  # ------------------------------------------------------------------------------
            selection = self.app.getListBoxPos(widget)
            if len(selection) > 0:
                self._event_info(selection[0])

        else:
            self.info(f"Unimplemented input from setup widget: '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def get_sfx_info(self, sfx_id: int) -> Tuple[int, int, bool, int]:
        """
        Returns
        -------
        Tuple[int, bool]
            A tuple (channel, address, volume only flag, number of events).
        """
        ptr = 0xA16B + (sfx_id << 2)

        # Read sfx entry from table in ROM buffer

        value = self.rom.read_byte(0x9, ptr)
        volume_only = (value & 0x10) > 0
        channel = value & 0x3
        size = self.rom.read_byte(0x9, ptr + 1)
        address = self.rom.read_word(0x9, ptr + 2)

        return channel, address, volume_only, size

    # ------------------------------------------------------------------------------------------------------------------

    def read_sfx_names(self) -> List[str]:
        # By default, everything is unnamed
        self.sfx_names = []

        for s in range(52):
            self.sfx_names.append(f"(No Name)")

        # If any definition filename matches the currently loaded ROM filename, then use that one
        file_name = os.path.basename(self.rom.path).rsplit('.')[0] + "_audio.ini"
        if os.path.exists(os.path.dirname(self.rom.path) + '/' + file_name):
            file_name = os.path.dirname(self.rom.path) + '/' + file_name
        elif os.path.exists("audio.ini"):
            file_name = "audio.ini"

        parser = configparser.ConfigParser()
        parser.read(file_name)

        if parser.has_section("SFX"):
            section = parser["SFX"]
            for s in range(52):
                name = section.get(f"{s}", "")
                if name != "":
                    self.sfx_names[s] = name

        return self.sfx_names

    # ------------------------------------------------------------------------------------------------------------------

    def read_sfx_data(self, sfx_id: Optional[int] = None) -> Tuple[bool, int, int]:
        """
        Reads an entry from the sfx table in bank 9.
        Parameters
        ----------
        sfx_id: Optional[int]
            Index of the entry to read; re-reads currently loaded sfx if not specified.

        Returns
        -------
        Tuple[bool, int, int]
            A tuple (volume only flag, channel number, data address).
        """
        if sfx_id is None:
            sfx_id = self._sfx_id

        if 52 < sfx_id < 0:
            self.warning(f"Invalid Sound Effect Id requested: {sfx_id}.")
            return False, 0, 0

        address = 0xA16B + (sfx_id << 2)

        # Read sfx entry from table in ROM buffer

        value = self.rom.read_byte(0x9, address)
        self._volume_only = (value & 0x10) > 0
        self._channel = value & 0x3

        self._size = self.rom.read_byte(0x9, address + 1)

        self._address = self.rom.read_word(0x9, address + 2)

        # Read sound data
        address = self._address

        # First four bytes are the "setup" values used to initialise the registers
        self._setup_values = self.rom.read_bytes(0x9, address, 4)

        self._sfx_data.clear()

        address += 4
        for _ in range(self._size):
            self._sfx_data.append(self.rom.read_byte(0x9, address))
            address += 1
            if not self._volume_only:
                self._sfx_data.append(self.rom.read_byte(0x9, address))
                address += 1

        return self._volume_only, self._channel, self._address

    # ------------------------------------------------------------------------------------------------------------------

    def save_sfx_data(self) -> bool:
        """
        Returns
        -------
        bool
            True if save successful, False otherwise (e.g. no room for event data)
        """
        name = self.app.getEntry("XE_SFX_Name")
        if name is None or len(name) < 1:
            name = "(No Name)"
        else:
            # Save name in INI file
            # If any definition filename matches the currently loaded ROM filename, then use that one
            file_name = os.path.basename(self.rom.path).rsplit('.')[0] + "_audio.ini"
            if os.path.exists(os.path.dirname(self.rom.path) + '/' + file_name):
                file_name = os.path.dirname(self.rom.path) + '/' + file_name
            elif os.path.exists("audio.ini"):
                file_name = "audio.ini"

            parser = configparser.ConfigParser()
            parser.read(file_name)

            if not parser.has_section("SFX"):
                parser.add_section("SFX")

            parser.set("SFX", f"{self._sfx_id}", name)

        # Update SFX tab list
        self.app.setOptionBox("ST_Option_SFX", self._sfx_id, value=f"0x{self._sfx_id:02X} {name}", callFunction=False)

        # Map of valid ROM areas in Bank 9 where we can save our data
        # Tuple: start address, size
        memory = [(0xA23B, 2590), (0xA050, 176)]

        # One buffer per memory area, we will only copy them to ROM if all data can be allocated successfully
        buffers = [bytearray(), bytearray()]

        # We will also recreate the table locally before copying it to ROM
        table = bytearray()

        # Go through all the sound effects and re-allocate them
        for i in range(52):
            if i == self._sfx_id:
                # Save our new data
                size = self._size
                table.append(self._channel | (0x80 if self._volume_only else 0))
                data = self._setup_values + self._sfx_data
            else:
                # Read data from ROM
                ptr = 0xA16B + (i << 2)

                size = self.rom.read_byte(0x9, ptr + 1)

                channel = self.rom.read_byte(0x9, ptr)
                table.append(channel)

                old_address = self.rom.read_word(0x9, ptr + 2)
                # 4 bytes of "setup values", then either 1 byte per event (volume only flag) or 2 bytes per event
                data = self.rom.read_bytes(0x9, old_address, 4 + (size * (1 if (channel & 0x10) > 0 else 2)))

            # Write number of events in the table
            table.append(size)
            # Get data size in bytes
            data_size = len(data)

            # See if it fits in the first area
            if data_size <= memory[0][1]:
                mem = 0
            elif data_size <= memory[1][1]:
                mem = 1
            else:
                self.app.errorBox("SFX Editor", f"Error saving sound effect #{i}: out of memory in ROM bank 9.",
                                  "SFX_Editor")
                return False

            new_address = memory[mem][0]
            table.append(new_address & 0x00FF)  # Low byte
            table.append(new_address >> 8)      # High byte

            # Advance the first available address and reduce size for the selected area
            memory[mem] = new_address + data_size, memory[mem][1] - data_size

            # Save data to our local buffer
            buffers[mem] += data

        # Memory successfully allocated, we can write both table and data to ROM
        self.rom.write_bytes(0x9, 0xA16B, table)
        self.rom.write_bytes(0x9, 0xA23B, buffers[0])
        if len(buffers[1]) > 0:
            self.rom.write_bytes(0x9, 0xA050, buffers[1])

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def _sfx_info(self) -> None:
        if self._channel == 3:      # Noise channel
            self.app.selectFrame("XE_Stack_Channel", 2)
        elif self._channel == 2:    # Triangle channel
            self.app.selectFrame("XE_Stack_Channel", 1)
        else:                       # Pulse channels
            self.app.selectFrame("XE_Stack_Channel", 0)

        # Highlight current channel
        for c in range(4):
            self.app.setButtonBg(f"XE_Channel_{c}", colour.LIGHT_ORANGE if self._channel == c else colour.DARK_ORANGE)

        # Set widgets according to sfx setup data

        if self._channel == 3:      # Noise
            lc_flag = (self._setup_values[0] & 0x20) > 0
            cv_flag = (self._setup_values[0] & 0x10) > 0
            volume = self._setup_values[0] & 0x0F
            loop = (self._setup_values[2] & 0x80) > 0
            period = self._setup_values[2] & 0x0F
            length_ctr_load = self._setup_values[3] >> 3

            self.app.setCheckBox("XE_Noise_LC_Flag", lc_flag, callFunction=False)
            self.app.setCheckBox("XE_Noise_CV_Flag", cv_flag, callFunction=False)

            self.app.setScale("XE_Noise_Volume", volume, callFunction=False)
            # If the Constant Volume flag is clear, than this is the envelope period instead of volume
            if (self._setup_values[0] & 0x10) > 0:
                self.app.setLabel("XE_Noise_Label_0", f"Volume: {volume:02}")
            else:
                self.app.setLabel("XE_Noise_Label_0", f"Env. Period: {volume:02}")

            self.app.setCheckBox("XE_Noise_Loop", loop, callFunction=False)

            self.app.setScale("XE_Noise_Period", period)
            freq = _NOISE_FREQ_TABLE[period]

            self.app.setLabel("XE_Noise_Label_1", f"Period: {period:02}")
            self.app.setLabel("XE_Noise_Freq", f"Frequency: {freq} Hz")

            self.app.setScale("XE_Noise_Load", length_ctr_load)
            self.app.setLabel("XE_Noise_Label_2", f"Length Ctr Load: {length_ctr_load:02}")
            if lc_flag:
                self.app.disableScale("XE_Noise_Load")
            else:
                self.app.enableScale("XE_Noise_Load")

        elif self._channel == 2:    # Triangle
            control_flag: bool = (self._setup_values[0] & 0x80) > 0
            linear_ctr_reload: int = self._setup_values[0] & 0x7F

            timer_value: int = self._setup_values[2] | ((self._setup_values[3] & 0x3) << 8)
            frequency = 1789773 / ((timer_value + 1) << 5)

            length_ctr_load: int = (self._setup_values[3] & 0xF8) >> 3

            self.app.setCheckBox("XE_Triangle_Control_Flag", control_flag, callFunction=False)

            self.app.clearEntry("XE_Linear_Load", callFunction=False, setFocus=False)
            self.app.setEntry("XE_Linear_Load", linear_ctr_reload, callFunction=False)

            self.app.clearEntry("XE_Triangle_Timer", callFunction=False, setFocus=False)
            self.app.setEntry("XE_Triangle_Timer", timer_value, callFunction=False)
            self.app.setLabel("XE_Triangle_Freq", f"Frequency: {round(frequency, 2)} Hz")

            self.app.clearEntry("XE_Triangle_Length_Load", callFunction=False, setFocus=False)
            self.app.setEntry("XE_Triangle_Length_Load", length_ctr_load, callFunction=False)

        else:                       # Pulse
            duty = (self._setup_values[0] >> 6)
            lc_flag = (self._setup_values[0] & 0x20) > 0
            cv_flag = (self._setup_values[0] & 0x10) > 0
            volume = self._setup_values[0] & 0x0F

            sweep_enable = (self._setup_values[1] & 0x80) > 0
            sweep_period = (self._setup_values[1] & 0x70) >> 4
            sweep_negate = (self._setup_values[1] & 0x08) > 0
            sweep_shift = self._setup_values[1] & 0x3

            timer = self._setup_values[2] | ((self._setup_values[3] & 0x03) << 8)

            length_ctr_load = self._setup_values[3] >> 3

            self.app.setOptionBox("XE_Duty_Cycle", duty, callFunction=False)
            self.app.setCheckBox("XE_Pulse_LC_Flag", lc_flag, callFunction=False)
            self.app.setCheckBox("XE_Pulse_CV_Flag", cv_flag, callFunction=False)
            self.app.setScale("XE_Pulse_Volume", volume)

            self.app.setLabel("XE_Pulse_Label_0", f"{'Volume' if cv_flag else 'Env. Period'}: {volume:02}")

            self.app.setCheckBox("XE_Sweep_Enable", sweep_enable, callFunction=False)

            self.app.setLabel("XE_Pulse_Label_1", f"Sweep Period: {sweep_period:02}")
            self.app.setScale("XE_Sweep_Period", sweep_period, callFunction=False)

            self.app.setCheckBox("XE_Sweep_Negate", sweep_negate, callFunction=False)

            self.app.setLabel("XE_Pulse_Label_2", f"Shift Count: {sweep_shift:02}")
            self.app.setScale("XE_Sweep_Shift", sweep_shift, callFunction=False)

            if sweep_enable:
                self.app.enableScale("XE_Sweep_Period")
                self.app.enableScale("XE_Sweep_Shift")
            else:
                self.app.disableScale("XE_Sweep_Period")
                self.app.disableScale("XE_Sweep_Shift")

            self.app.clearEntry("XE_Pulse_Timer", callFunction=False, setFocus=False)
            self.app.setEntry("XE_Pulse_Timer", timer, callFunction=False)
            freq: float = 1789773 / ((timer + 1) << 4)
            self.app.setLabel("XE_Pulse_Freq", f"Frequency: {round(freq, 2)} Hz")

            self.app.setScale("XE_Pulse_Length_Load", length_ctr_load)

            self.app.setLabel("XE_Pulse_Label_4", f"Length Ctr Load: {length_ctr_load:02}")
            if lc_flag:
                self.app.disableScale("XE_Pulse_Length_Load")
            else:
                self.app.enableScale("XE_Pulse_Length_Load")

        self._update_data_list()

    # ------------------------------------------------------------------------------------------------------------------

    def _update_data_list(self, event_index: Optional[int] = None) -> None:
        # Only update one item if event_index is specified
        if event_index is not None:
            v = event_index * (1 if self._volume_only else 2)
            text = f"#{event_index:02}: ${self._sfx_data[v]:02X}"
            if not self._volume_only:
                text += f", ${self._sfx_data[v + 1]:02X}"

            self.app.setListItemAtPos("XE_Data_List", event_index, text)
            self.app.selectListItemAtPos("XE_Data_List", event_index, callFunction=False)

            return

        # Otherwise list all data entries
        self.app.clearEntry("XE_Data_Size", callFunction=False, setFocus=False)
        self.app.setEntry("XE_Data_Size", self._size, callFunction=False)

        self.app.clearListBox("XE_Data_List")
        index = 0
        v = 0
        while index < self._size:
            text = f"#{index:02}: ${self._sfx_data[v]:02X}"
            v += 1
            if not self._volume_only:
                text += f", ${self._sfx_data[v]:02X}"
                v += 1

            self.app.addListItems("XE_Data_List", [text], False)
            index += 1

        # Select top entry
        self.app.selectListItemAtPos("XE_Data_List", 0, callFunction=True)

    # ------------------------------------------------------------------------------------------------------------------

    def _event_info(self, event_id: int) -> None:
        # --- Register 0
        index = event_id * (1 if self._volume_only else 2)

        # --- Reg 0, bits 7, 6
        # Only Pulse channels have this
        if self._channel < 2:
            duty = self._sfx_data[index] >> 6
            self.app.enableOptionBox("XE_Data_Duty")
            self.app.setOptionBox("XE_Data_Duty", duty, callFunction=False)
        else:
            self.app.disableOptionBox("XE_Data_Duty")

        # --- Reg 0, bits 5, 4
        if self._channel != 2:
            lc_flag = (self._sfx_data[index] & 0x20) > 0
            self.app.setCheckBoxText("XE_Data_LC_Flag", "Length Ctr Halt")
            self.app.setCheckBox("XE_Data_LC_Flag", lc_flag, callFunction=False)

            cv_flag = (self._sfx_data[index] & 0x10) > 0
            self.app.enableCheckBox("XE_Data_CV_Flag")
            self.app.setCheckBox("XE_Data_CV_Flag", cv_flag, callFunction=False)

        # --- Reg 0, bit 7
        # For the Triangle channel, use the LC Flag widget for the Control Flag instead, then disable the CV widget
        else:
            control_flag = (self._sfx_data[index] & 0x80) > 0
            self.app.setCheckBoxText("XE_Data_LC_Flag", "Control Flag")
            self.app.setCheckBox("XE_Data_LC_Flag", control_flag, callFunction=False)
            self.app.disableCheckBox("XE_Data_CV_Flag")

        # --- Reg 0, bits 3-0
        if self._channel != 2:
            volume = self._sfx_data[index] & 0x0F
            if (self._sfx_data[index] & 0x10) > 0:
                # Constant Volume
                self.app.setLabel("XE_Data_Label_2", f"Volume: {volume:02}")
            else:
                # Envelope Enabled
                self.app.setLabel("XE_Data_Label_2", f"Env. Period: {volume:02}")
            self.app.setScaleRange("XE_Data_Reg_0", 0, 15)
            self.app.setScale("XE_Data_Reg_0", volume, callFunction=False)

        # --- Reg 0, bit 7-0
        # For the Triangle channel, this is the linear counter reload value
        else:
            linear_ctr_reload = self._sfx_data[index] & 0x7F
            self.app.setLabel("XE_Data_Label_2", f"Linear Ctr: {linear_ctr_reload:02}")
            self.app.setScaleRange("XE_Data_Reg_0", 0, 0x7F)
            self.app.setScale("XE_Data_Reg_0", linear_ctr_reload, callFunction=False)

        # --- Register 2
        index += 1

        self.app.clearEntry("XE_Data_Reg_2", callFunction=False, setFocus=False)

        # --- Reg 2, bit 7 and 3-0
        # The Noise channel uses the period value differently
        if self._channel == 3:
            noise_mode = (self._sfx_data[index] & 0x80) > 0
            self.app.enableCheckBox("XE_Data_Noise_Mode")
            self.app.setCheckBox("XE_Data_Noise_Mode", noise_mode, callFunction=False)

            period = self._sfx_data[index] & 0x0F

            freq = round(_NOISE_FREQ_TABLE[period] / (1 if noise_mode else 93), 2)

        # --- Reg 2, bits 7-0
        else:
            period = self._sfx_data[index]
            timer_high = self._setup_values[3] & 0x03
            timer = (timer_high << 8) | period
            freq = round(1789773 / ((timer + 1) << (5 if self._channel == 2 else 4)), 2)

            self.app.disableCheckBox("XE_Data_Noise_Mode")

        self.app.setEntry("XE_Data_Reg_2", period, callFunction=False)
        self.app.setLabel("XE_Data_Freq", f"Frequency: {freq} Hz")

    # ------------------------------------------------------------------------------------------------------------------

    def _play_sfx(self) -> None:
        if not self._music_editor.sound_server.getIsBooted():
            self._music_editor.sound_server.boot()
        if not self._music_editor.sound_server.getIsStarted():
            self._music_editor.sound_server.start()

        # Mute channels
        self.apu.reset()

        self.apu.play()

        # Set initial values
        if self._channel == 0:
            apu_channel = self.apu.pulse_0
        elif self._channel == 1:
            apu_channel = self.apu.pulse_1
        elif self._channel == 2:
            apu_channel = self.apu.triangle
        else:
            apu_channel = self.apu.noise

        apu_channel.write_reg0(self._setup_values[0])
        apu_channel.write_reg1(self._setup_values[1])
        apu_channel.write_reg2(self._setup_values[2])
        apu_channel.write_reg3(self._setup_values[3])

        self._sfx_pos = 0

        # self.info(f"Playing {self._size} events ({len(self._sfx_data)} bytes)")
        self._play_thread = threading.Thread(target=self._data_step, args=(apu_channel,))
        self._play_thread.start()

    # ------------------------------------------------------------------------------------------------------------------

    def _data_step(self, apu_channel) -> None:

        frame_interval = .0166
        size = len(self._sfx_data)

        while self._sfx_pos < size:
            start_time = time.time()

            # print(f"Step: {self._sfx_pos}")

            # self.info(f"REG0:${self._sfx_data[self._sfx_pos]}")
            apu_channel.write_reg0(self._sfx_data[self._sfx_pos])
            self._sfx_pos += 1

            if not self._volume_only:
                # self.info(f"REG2:${self._sfx_data[self._sfx_pos]}")
                apu_channel.write_reg2(self._sfx_data[self._sfx_pos])
                self._sfx_pos += 1

            interval = frame_interval - (time.time() - start_time)
            if interval > 0:
                time.sleep(interval)

        # print("Stopping playback...")
        self.stop_playback()

    # ------------------------------------------------------------------------------------------------------------------

    def stop_playback(self) -> None:
        self.apu.stop()

        try:
            self.app.setButtonImage("XE_Play_Stop", "res/play.gif")
            self.app.setButtonTooltip("XE_Play_Stop", "Start playback")
        except appJar.appjar.ItemLookupError:
            return

    # ------------------------------------------------------------------------------------------------------------------

    def _draw_sfx_graph(self, draw_volume: bool = True, draw_period: bool = True) -> None:
        # This will be similar to the code used in the Instrument Editor
        width = self._canvas_sfx.winfo_reqwidth()

        base_height = self._canvas_sfx.winfo_reqheight() - 10

        vertical_step = base_height >> 5

        line_width = 1

        # Calculate the width of each segment in our line
        length = width // (self._size + 1)
        if length < 8:
            length = 8
            line_width = 1  # Make the line thinner if it gets too crowded
        trail = length >> 2
        # One for each duty value, we consider 25% and 75% to be the same, for simplicity
        hat = [trail >> 1, trail, length >> 1, trail]
        """
              hat
              ___
             |   |
        _____|   |_____
        trail     tail      tail = trail
        _______________
            length
        """

        volume_points = []
        timer_points = []
        timer = 0
        x = 0  # Start from the left of the canvas

        # TODO Use envelope values instead of volume if enabled
        # TODO Sweep unit values for timer if enabled

        # Setup values first
        if draw_volume:
            if self._channel < 2:
                duty = self._setup_values[0] >> 6
            else:
                duty = 3

            volume = self._setup_values[0] & 0x0F

            # Starting points
            volume_points.append((x, base_height))

            # Move right a bit
            volume_points.append((x + trail, base_height))

            # Go up, depending on volume
            y = base_height - (volume * vertical_step)
            volume_points.append((x + trail, y))

            # Draw the "hat", depending on duty
            volume_points.append((x + trail + hat[duty], y))

            # Go back down
            volume_points.append((x + trail + hat[duty], base_height))

            # Move to the end of this line
            volume_points.append((x + length, base_height))

        if draw_period:
            if self._channel == 3:
                timer = self._setup_values[2] & 0x0F
                y = (timer << 3) + 10
            else:
                timer = self._setup_values[2]
                y = ((timer + 1) >> 2) + 10

            timer_points.append((x, y))

        # Next line will start here
        x = x + length

        # Now for the entries...
        d = 0   # Position in the array, since entries can be either one- or two-byte long
        for i in range(self._size):
            if draw_volume:
                duty = 3 if self._channel > 1 else self._sfx_data[d] >> 6
                volume = self._sfx_data[d] & 0x0F

                volume_points.append((x, base_height))
                volume_points.append((x + trail, base_height))
                y = base_height - (volume * vertical_step)
                volume_points.append((x + trail, y))
                volume_points.append((x + trail + hat[duty], y))
                volume_points.append((x + trail + hat[duty], base_height))
                volume_points.append((x + length, base_height))

            d += 1
            x = x + length

            if self._volume_only:
                # Use sweep unit value, if enabled
                # ...otherwise, use the previous timer value
                if draw_period:
                    if self._channel == 3:  # The noise channel has a different use of its period value
                        y = (timer << 2) + 10
                    else:
                        y = ((timer + 1) >> 2) + 10
                    timer_points.append((x, y))

            else:
                if draw_period:
                    if self._channel == 3:
                        timer = self._sfx_data[d] & 0x0F
                        y = (timer << 3) + 10
                    else:
                        timer = self._sfx_data[d]
                        y = ((timer + 1) >> 2) + 10
                    timer_points.append((x, y))

                # If only updating volume, this value is simply ignored
                d += 1

        # Make sure we cover the whole graph area horizontally
        if draw_volume:
            last = volume_points[-1]
            volume_points[-1] = (320, last[1])

            flat = [a for x in volume_points for a in x]
            if self._volume_line > 0:
                self._canvas_sfx.coords(self._volume_line, *flat)
                self._canvas_sfx.itemconfigure(self._volume_line, width=line_width)
            else:
                self._volume_line = self._canvas_sfx.create_line(*flat, width=line_width, fill=colour.LIGHT_ORANGE)

        if draw_period:
            last = timer_points[-1]
            timer_points[-1] = (320, last[1])

            flat = [a for x in timer_points for a in x]
            if self._timer_line > 0:
                self._canvas_sfx.coords(self._timer_line, *flat)
                self._canvas_sfx.itemconfigure(self._timer_line, width=line_width)
            else:
                self._timer_line = self._canvas_sfx.create_line(*flat, width=line_width, fill=colour.LIGHT_GREEN)

        # Make sure the timer line is always drawn on top of the volume/duty bars
        if not draw_period and self._timer_line > 0:
            self._canvas_sfx.tag_raise(self._timer_line)
