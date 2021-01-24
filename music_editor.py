__author__ = "Fox Cunning"

import configparser
import os
import threading
import time

import pyo

from dataclasses import dataclass, field
from tkinter import Canvas
from typing import List, Tuple

import colour
from appJar import gui
from appJar.appjar import ItemLookupError
from debug import log
from rom import ROM


# Note definitions as read from ROM
_notes: List[int] = []

# TODO Create note names based on the period (with approximation)
_NOTE_NAMES = ["C2 ", "C#2", "D2 ", "D#2", "E2 ", "F2 ", "F#2", "G2 ", "G#2", "A2 ", "A#2", "B2 ",
               "C3 ", "C#3", "D3 ", "D#3", "E3 ", "F3 ", "F#3", "G3 ", "G#3", "A3 ", "A#3", "B3 ",
               "C4 ", "C#4", "D4 ", "D#4", "E4 ", "F4 ", "F#4", "G4 ", "G#4", "A4 ", "A#4", "B4 ",
               "C5 ", "C#5", "D5 ", "D#5", "E5 ", "F5 ", "F#5", "G5 ", "G#5", "A5 ", "A#5", "B5 ",
               "C6 ", "C#6", "D6 ", "D#6", "E6 ", "F6 ", "F#6", "G6 ", "G#6", "A6 ", "A#6", "B6 "]

# This is to quickly get a duty representation based on the register's value
_DUTY = ["12.5%", "  25%", "  50%", "  75%"]


# ----------------------------------------------------------------------------------------------------------------------

@dataclass(init=True, repr=False)
class Instrument:
    name: str = ""
    # Keep track of the address so we can more easily write data back to the ROM buffer
    envelope_address: List[int] = field(default_factory=list)
    envelope: List[bytearray] = field(default_factory=list)

    def duty(self, envelope_id: int, duty_id: int) -> int:
        if duty_id > self.envelope[envelope_id][0]:
            duty_id = self.envelope[envelope_id][0]

        try:
            return self.envelope[envelope_id][duty_id] >> 6
        except IndexError:
            log(1, "Instrument", f"Invalid index for envelope #{envelope_id}, duty id: {duty_id}")
            return 0

    def volume(self, envelope_id: int, volume_id: int) -> int:
        if volume_id > self.envelope[envelope_id][0]:
            volume_id = self.envelope[envelope_id][0]

        return (self.envelope[envelope_id][volume_id] & 0x3F) >> 1

    def size(self, envelope_id: int) -> int:
        return self.envelope[envelope_id][0]


# ----------------------------------------------------------------------------------------------------------------------

class Note:
    """
    Properties
    ----------
    frequency: float
        Pre-calculated frequency, in Hz

    index: int
        Index of this note as found in the period table in ROM

    duration: int
        Number of frames this note will be played for
    """
    CPU_FREQ: int = 1789773

    def __init__(self, index: int = 0, duration: int = 0):
        global _notes

        self._index: int = index
        self.duration: int = duration

        # From the NESDev Wiki:
        # frequency = fCPU/(16*(period+1))
        # fCPU = 1.789773 MHz for NTSC, 1.662607 MHz for PAL, and 1.773448 MHz for Dendy
        if index < len(_notes):
            period = _notes[index]
        else:
            period = 0x6AB  # A default value to use until notes are loaded

        self.frequency: int = int(self.CPU_FREQ / ((period + 1) << 4))


# ----------------------------------------------------------------------------------------------------------------------

@dataclass(init=True, repr=False)
class TrackData:
    """
    Properties
    ----------
    function: int
        Function of this data segment

    params: int
        Up to 3 parameters for this data segment
    """
    # Function values:
    PLAY_NOTE: int = 0
    CHANNEL_VOLUME: int = 0xFB
    SELECT_INSTRUMENT: int = 0xFC
    SET_VIBRATO: int = 0xFD
    REST: int = 0xFE
    REWIND: int = 0xFF

    function: int = 0

    channel_volume: int = 0
    instrument_index: int = 0
    # Index of the item to loop from
    loop_position: int = 0
    vibrato_speed: int = 0
    vibrato_factor: int = 0
    rest_duration: int = 0
    # Play notes 12 semitones higher if True
    triangle_octave: bool = False
    note_value: Note = Note()

    # How many bytes does this entry take
    size: int = 1

    # Raw bytes forming this entry
    raw: bytearray = bytearray()

    @classmethod
    def volume(cls, level: int):
        return cls(function=cls.CHANNEL_VOLUME, channel_volume=level & 0x0F, size=2)

    @classmethod
    def instrument(cls, index: int):
        return cls(function=cls.SELECT_INSTRUMENT, instrument_index=index, size=2)

    @classmethod
    def vibrato(cls, higher_octave: bool, speed: int, factor: int):
        if speed < 2:
            return cls(function=cls.SET_VIBRATO, triangle_octave=higher_octave, vibrato_speed=0,
                       vibrato_factor=0, size=4)
        else:
            return cls(function=cls.SET_VIBRATO, triangle_octave=higher_octave, vibrato_speed=speed,
                       vibrato_factor=factor, size=4)

    @classmethod
    def rest(cls, duration: int):
        return cls(function=cls.REST, rest_duration=duration, size=2)

    @classmethod
    def rewind(cls, position: int):
        return cls(function=cls.REWIND, loop_position=position, size=4)

    @classmethod
    def note(cls, index: int, duration: int):
        return cls(function=cls.PLAY_NOTE, note_value=Note(index, duration), size=2)


# ----------------------------------------------------------------------------------------------------------------------

class MusicEditor:

    def __init__(self, app: gui, rom: ROM):
        self.app = app
        self.rom = rom

        self._bank: int = 8

        # --- Track Editor ---
        self._track_address: List[int] = [0, 0, 0, 0]
        self._selected_channel: int = 0

        # --- Instrument Editor ---
        self._instruments: List[Instrument] = []
        self._selected_instrument: int = 0

        # TODO Allow users to choose sample rate, buffer size and Windows host API?
        self._sound_server: pyo.Server = pyo.Server(sr=22050, duplex=0, nchnls=1, buffersize=1024).boot()

        self.track_titles: List[str] = ["- No Tracks -"]

        # These are to quickly access our canvas widgets
        self._canvas_graph: Canvas = Canvas()
        self._canvas_envelope: List[Canvas] = []

        # Canvas item indices
        self._full_graph_line = 0
        # Rectangles used to display an envelope's volume levels, one list per canvas
        self._volume_bars: List[List[int]] = [[], [], []]
        # Lines used to display an envelope's duty cycles, one per canvas
        self._duty_lines: List[int] = [0, 0, 0]

        self._unsaved_changes_instrument: bool = False
        self._unsaved_changes_track: bool = False

        # Used during playback
        self._track_data: List[List[TrackData]] = [[], [], [], []]
        self._track_position: List[int] = [0, 0, 0, 0]

        # Starts from 1 and is decreased each frame. When 0, read next data segment.
        self._track_counter: List[int] = [1, 1, 1, 1]

        # Used for testing instruments
        self._test_octave: int = 0  # 0: Treble, 1: Alto, 2: Bass
        self._test_notes: int = 0   # 0: Single note loop, 1: Scales, 2: Arpeggios
        self._test_speed: int = 0   # 0: Short notes, 1: Medium notes, 3: Long notes

        # Threading
        self._play_thread: threading.Thread = threading.Thread()
        self._update_thread: threading.Thread = threading.Thread()
        self._stop_event: threading.Event = threading.Event()   # Signals the playback thread that it should stop
        self._slow_event: threading.Event = threading.Event()   # Used by the playback thread to signal slow processing
        self._playing: bool = False

        # Read notes period table
        _notes.clear()
        address_hi = 0x85AF
        address_lo = 0x85FD
        for n in range(60):
            hi = self.rom.read_byte(0x8, address_hi)
            lo = self.rom.read_byte(0x8, address_lo)
            _notes.append((hi << 8) | lo)
            address_lo += 1
            address_hi += 1

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

    def error(self, message: str):
        log(2, f"{self.__class__.__name__}", message)

    # ------------------------------------------------------------------------------------------------------------------

    def warning(self, message: str):
        log(3, f"{self.__class__.__name__}", message)

    # ------------------------------------------------------------------------------------------------------------------

    def info(self, message: str):
        log(4, f"{self.__class__.__name__}", message)

    # ------------------------------------------------------------------------------------------------------------------

    def read_track_titles(self) -> List[str]:
        """
        Reads track titles from music.txt, or <ROM name>_music.txt if present.

        Returns
        -------
        List[str]
            A list of strings corresponding to track titles.
        """
        track_titles: List[str] = []

        # If any definition filename matches the currently loaded ROM filename, then use that one
        rom_file = os.path.basename(self.rom.path).rsplit('.')[0].lower()

        if os.path.exists(f"{rom_file}_music.txt"):
            file_name = f"{rom_file}_music.txt"
        else:
            file_name = "music.txt"

        try:
            file = open(file_name, "r")
            track_titles = file.readlines()
            file.close()

            for m in range(len(track_titles)):
                track_titles[m] = track_titles[m].rstrip("\n\a\r")

        except OSError as error:
            self.error(f"Could not read '{file_name}': {error.strerror}.")
            for t in range(12):
                track_titles.append(f"Unnamed track #{t:02}")

        self.track_titles = track_titles

        return track_titles

    # ------------------------------------------------------------------------------------------------------------------

    def close_track_editor(self) -> bool:
        if self._unsaved_changes_track is True:
            if self.app.yesNoBox("Track Editor", "Are you sure you want to close the Track Editor?\n" +
                                 "Any unsaved changes will be lost.", "Track_Editor") is False:
                return False

        # If playing test notes, stop and wait for the thread to finish
        self.stop_playback()
        if self._sound_server.getIsStarted():
            self._sound_server.stop()
        if self._sound_server.getIsBooted():
            self._sound_server.shutdown()

        self.app.hideSubWindow("Track_Editor")
        self.app.emptySubWindow("Track_Editor")

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def close_instrument_editor(self) -> bool:
        if self._unsaved_changes_instrument is True:
            if self.app.yesNoBox("Instrument Editor", "Are you sure you want to close the Instrument Editor?\n" +
                                 "Any unsaved changes will be lost.", "Instrument_Editor") is False:
                return False

        # If playing test notes, stop and wait for the thread to finish
        self.stop_playback()
        if self._sound_server.getIsStarted():
            self._sound_server.stop()
        if self._sound_server.getIsBooted():
            self._sound_server.shutdown()

        self.app.hideSubWindow("Instrument_Editor")
        self.app.emptySubWindow("Instrument_Editor")

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def stop_playback(self) -> None:
        self._playing = False
        if self._update_thread.is_alive():
            self._update_thread.join()

        if self._play_thread.is_alive():
            # self._stop_event.set()
            self._play_thread.join()
            if self._slow_event.is_set():
                self.warning("Slow playback detected! This may be due to too many non-note events in a track, or " +
                             "a slow machine, or slow audio host API.")

    # ------------------------------------------------------------------------------------------------------------------

    def start_playback(self, update_tracker: bool = False) -> None:
        # self._stop_event.clear()
        self._playing = True
        self._play_thread = threading.Thread(target=self._play_loop, args=())
        self._play_thread.start()
        if update_tracker:
            self._update_thread = threading.Thread(target=self._tracker_update_loop, args=())
            self._update_thread.start()

    # ------------------------------------------------------------------------------------------------------------------

    def show_track_editor(self, bank: int, track: int) -> None:
        """
        Shows the Track Editor window and loads the specified track.

        Parameters
        ----------
        bank: int
            ROM bank where the track resides (8 or 9)

        track: int
            Index of the track *in this bank* (0-10)
        """
        self._bank = bank

        try:
            self.app.getFrameWidget("SE_Frame_Buttons")
            window_exists = True
        except ItemLookupError:
            window_exists = False

        # Get this track's address
        address = 0x8051 + (track << 3)
        for t in range(4):
            self._track_address[t] = self.rom.read_word(bank, address)
            address += 2

        # Read instrument data
        if len(self._instruments) < 1:
            self.read_instrument_data()

        # Read track data for all tracks
        self.read_track_data(0)
        self.read_track_data(1)
        self.read_track_data(2)
        self.read_track_data(3)
        # self.info(f"Loading track #{track} from ${bank:02X}:{self._track_address[0]:04X}")

        if window_exists:
            self.app.showSubWindow("Track_Editor")
            return

        with self.app.subWindow("Track_Editor"):

            # Buttons
            with self.app.frame("SE_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0):
                # Left
                with self.app.frame("SE_Frame_File", padding=[4, 2], sticky="NW", row=0, column=0):
                    self.app.button("SE_Button_Apply", self._track_input, image="res/floppy.gif", width=32, height=32,
                                    tooltip="Apply changes to all channels", bg=colour.MEDIUM_GREY,
                                    row=0, column=0)
                    self.app.button("SE_Button_Reload", self._track_input, image="res/reload.gif", width=32, height=32,
                                    tooltip="Reload track data from ROM", bg=colour.MEDIUM_GREY,
                                    row=0, column=1)
                    self.app.button("SE_Button_Cancel", self._track_input, image="res/close.gif", width=32, height=32,
                                    tooltip="Cancel / Close window", bg=colour.MEDIUM_GREY,
                                    row=0, column=2)
                # Spacer
                self.app.label("SE_Label_Space", " ", sticky="NEWS", row=0, column=1)

                # Right
                with self.app.frame("SE_Frame_Play_Controls", padding=[4, 2], sticky="NE", row=0, column=2):
                    self.app.button("SE_Play_Stop", self._track_input, image="res/play.gif", width=32, height=32,
                                    tooltip="Start / Stop track playback", bg=colour.MEDIUM_GREY,
                                    row=0, column=0)

            # Channels
            with self.app.frame("SE_Frame_Channels", padding=[4, 2], sticky="NEW", row=1, column=0):
                channel_names = ["Square 0", "Square 1", "Triangle", "Noise"]
                for c in range(4):
                    self.app.label(f"SE_Label_Channel_{c}", channel_names[c], sticky="SEW",
                                   row=0, column=c, font=10)
                    self.app.listBox(f"SE_List_Channel_{c}", None, multi=False, group=True, fixed_scrollbar=True,
                                     width=24, height=20, sticky="NEW", bg=colour.BLACK, fg=colour.MEDIUM_GREY,
                                     row=1, column=c, font=9).configure(font="TkFixedFont")

        self.track_info(0)
        self.track_info(1)
        self.track_info(2)
        self.track_info(3)

        self.app.showSubWindow("Track_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def show_instrument_editor(self, bank: int) -> None:
        self._bank = bank

        window_exists = True
        try:
            self.app.getFrameWidget("IE_Frame_Buttons")
        except ItemLookupError:
            self.app.emptySubWindow("Instrument_Editor")
            self._canvas_envelope = []
            self._volume_bars = [[], [], []]
            self._duty_lines = [0, 0, 0]
            self._full_graph_line = 0
            window_exists = False

        if window_exists is True:
            # Just show window if it already exists
            self.read_instrument_data()
            self._selected_instrument = 0
            self.instrument_info()
            self.app.showSubWindow("Instrument_Editor")
            return

        self.read_instrument_data()

        instruments_list: List[str] = []
        for i in range(len(self._instruments)):
            instruments_list.append(f"{i:02X} {self._instruments[i].name}")

        with self.app.subWindow("Instrument_Editor"):

            # Buttons
            with self.app.frame("IE_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0, colspan=3):
                self.app.button("IE_Button_Apply", self._instruments_input, image="res/floppy.gif", width=32, height=32,
                                tooltip="Apply changes to all instruments", bg=colour.MEDIUM_GREY,
                                row=0, column=0)
                self.app.button("IE_Button_Cancel", self._instruments_input, image="res/close.gif", width=32, height=32,
                                tooltip="Cancel / Close window", bg=colour.MEDIUM_GREY,
                                row=0, column=1)

            # Selection / Name
            with self.app.frame("IE_Frame_Selection", padding=[2, 1], sticky="NEW", row=1, column=0):
                self.app.listBox("IE_List_Instrument", instruments_list, change=self._instruments_input, multi=False,
                                 group=True, sticky="SW", width=28, height=8, row=0, column=0, colspan=2, font=9)
                self.app.getListBoxWidget("IE_List_Instrument").configure(font="TkFixedFont")

                self.app.entry("IE_Instrument_Name", "(no name)", submit=self._update_instrument_name,
                               sticky="SEW", row=1, column=0, font=10)
                self.app.button("IE_Update_Name", self._instruments_input, image="res/reload-small.gif",
                                sticky="S", width=16, height=16, tooltip="Update list", row=1, column=1)

            # Play buttons
            with self.app.frame("IE_Frame_Play_Buttons", padding=[2, 2], sticky="NEW", row=1, column=1):
                self.app.button("IE_Button_Semiquaver", self._instruments_input, image="res/semiquaver.gif",
                                bg=colour.WHITE if self._test_speed == 0 else colour.DARK_GREY,
                                tooltip="Short notes", sticky="W", row=0, column=1)
                self.app.button("IE_Button_Crotchet", self._instruments_input, image="res/crotchet.gif",
                                bg=colour.WHITE if self._test_speed == 1 else colour.DARK_GREY,
                                tooltip="Medium length notes", sticky="W", row=0, column=2)
                self.app.button("IE_Button_Minim", self._instruments_input, image="res/minim.gif",
                                bg=colour.WHITE if self._test_speed == 2 else colour.DARK_GREY,
                                tooltip="Long notes", sticky="W", row=0, column=3)

                self.app.button("IE_Button_One_Note", self._instruments_input, image="res/one_note.gif",
                                bg=colour.WHITE if self._test_notes == 0 else colour.DARK_GREY,
                                tooltip="Loop single note", sticky="W", row=2, column=1)
                self.app.button("IE_Button_Scale", self._instruments_input, image="res/scale.gif",
                                bg=colour.WHITE if self._test_notes == 1 else colour.DARK_GREY,
                                tooltip="Play scales", sticky="W", row=2, column=2)
                self.app.button("IE_Button_Arpeggio", self._instruments_input, image="res/arpeggio.gif",
                                bg=colour.WHITE if self._test_notes == 2 else colour.DARK_GREY,
                                tooltip="Play arpeggios", sticky="W", row=2, column=3)

                self.app.button("IE_Button_Treble", self._instruments_input, image="res/treble.gif",
                                bg=colour.WHITE if self._test_octave == 0 else colour.DARK_GREY,
                                tooltip="Use higher octaves", sticky="W", row=3, column=1)
                self.app.button("IE_Button_Alto", self._instruments_input, image="res/alto.gif",
                                bg=colour.WHITE if self._test_octave == 1 else colour.DARK_GREY,
                                tooltip="Use middle octaves", sticky="W", row=3, column=2)
                self.app.button("IE_Button_Bass", self._instruments_input, image="res/bass.gif",
                                bg=colour.WHITE if self._test_octave == 2 else colour.DARK_GREY,
                                tooltip="Use lower octaves", sticky="W", row=3, column=3)

                self.app.button("IE_Play_Stop", self._instruments_input, image="res/play.gif",
                                width=32, height=32, bg=colour.MEDIUM_GREY, sticky="E", row=3, column=0)

            # Full Volume / Duty cycle graph
            with self.app.frame("IE_Frame_Graph", padding=[2, 1], sticky="NEW", row=1, column=2):
                self.app.canvas("IE_Canvas_Graph", width=456, height=160, row=0, column=0, bg=colour.BLACK)
                self._canvas_graph = self.app.getCanvasWidget("IE_Canvas_Graph")

            # Envelope data
            with self.app.frame("IE_Frame_Envelope_Data", padding=[4, 1], sticky="NWS", row=2, column=0, colspan=3):
                canvas_width = 162
                list_width = 12

                for e in range(3):
                    # List
                    c = e * 2
                    self.app.label(f"IE_Label_Envelope_{e}", f"Envelope {e}", sticky="W", row=0, column=c, font=10)
                    self.app.listBox(f"IE_List_Envelope_{e}", None, width=list_width, height=8, rows=8,
                                     change=self._instruments_input, fixed_scrollbar=True,
                                     multi=False, group=True, bg=colour.DARK_GREY, fg=colour.WHITE,
                                     sticky="S", row=1, column=c, font=9)
                    self.app.getListBoxWidget(f"IE_List_Envelope_{e}").configure(font="TkFixedFont")

                    # Buttons
                    self.app.button(f"IE_Move_Left_{e}", self._instruments_input, image="res/arrow_left-long.gif",
                                    tooltip="Move value to the previous envelope",
                                    height=16, sticky="SEW", row=2, column=c, bg=colour.MEDIUM_GREY)
                    self.app.button(f"IE_Move_Right_{e}", self._instruments_input, image="res/arrow_right-long.gif",
                                    tooltip="Move value to the next envelope",
                                    height=16, sticky="NEW", row=3, column=c, bg=colour.MEDIUM_GREY)

                    # Canvas and controls
                    self.app.canvas(f"IE_Canvas_Envelope_{e}", width=canvas_width, height=140, bg=colour.BLACK,
                                    sticky="S", row=1, column=c + 1)

                    with self.app.frame(f"IE_Frame_Controls_{e}", padding=[1, 1], sticky="NEWS", stretch="BOTH",
                                        expand="BOTH",
                                        row=2, column=c + 1, rowspan=2):
                        self.app.image(f"IE_Image_Duty_{e}", "res/duty-small.gif",
                                       sticky="W", row=0, column=0)
                        self.app.image(f"IE_Image_Volume_{e}", "res/volume-small.gif",
                                       sticky="W", row=1, column=0)

                        self.app.option(f"IE_Duty_{e}", ["12.5%", "25%", "50%", "75%"], change=self._instruments_input,
                                        bg=colour.DARK_RED, fg=colour.PALE_RED,
                                        width=12, sticky="WE", row=0, column=1, font=9)
                        self.app.scale(f"IE_Volume_{e}", range=(0, 8), change=self._instruments_input,
                                       bg=colour.DARK_RED, fg=colour.PALE_BLUE,
                                       sticky="WE", row=1, column=1, font=9)
                    self.app.showScaleIntervals(f"IE_Volume_{e}", 1)
                    self.app.getScaleWidget(f"IE_Volume_{e}").bind("<ButtonRelease-1>", self._draw_full_graph, add='+')

                    self._canvas_envelope.append(self.app.getCanvasWidget(f"IE_Canvas_Envelope_{e}"))

        self._selected_instrument = 0
        self.instrument_info()
        self.app.showSubWindow("Instrument_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def save_instrument_data(self) -> bool:
        success = True

        parser = configparser.ConfigParser()
        parser.add_section("NAMES")
        section = parser["NAMES"]

        for i in range(len(self._instruments)):
            # Save envelopes
            for e in range(3):
                address = self._instruments[i].envelope_address[e]
                self.rom.write_bytes(self._bank, address, self._instruments[i].envelope[e])

            # Add name to ini file
            name = self._instruments[i].name
            if name != "(no name)":
                section[f"{i}"] = self._instruments[i].name

        file_name = os.path.basename(self.rom.path).rsplit('.')[0] + "_instruments.ini"
        try:
            with open(file_name, "w") as names_file:
                parser.write(names_file, False)
        except IOError as error:
            self.app.warningBox("Instrument Editor", f"Could not write instrument names to file:\n{error.strerror}")

        # TODO Save actual data to ROM buffer

        return success

    # ------------------------------------------------------------------------------------------------------------------

    def read_track_data(self, channel: int) -> List[TrackData]:
        track: List[TrackData] = []

        address = self._track_address[channel]

        loop_found = False

        while not loop_found:
            control_byte = self.rom.read_byte(self._bank, address)
            address = address + 1

            if control_byte == 0xFB:                        # FB - VOLUME
                value = self.rom.read_byte(self._bank, address)
                address += 1
                data = TrackData.volume(value)
                data.raw = bytearray([0xFB, value])

            elif control_byte == 0xFC:                      # FC - INSTRUMENT
                value = self.rom.read_byte(self._bank, address)
                address += 1
                data = TrackData.instrument(value)
                data.raw = bytearray([0xFC, value])

            elif control_byte == 0xFD:                      # FD - VIBRATO
                triangle_octave = self.rom.read_byte(self._bank, address)
                address += 1

                speed = self.rom.read_byte(self._bank, address)
                address += 1

                factor = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackData.vibrato(triangle_octave < 0xFF, speed, factor)
                data.raw = bytearray([0xFD, triangle_octave, speed, factor])

            elif control_byte == 0xFE:                      # FE - REST
                value = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackData.rest(value)
                data.raw = bytearray([0xFE, value])

            elif control_byte == 0xFF:                      # FF - REWIND
                # Skip next byte (always zero, unused)
                address += 1

                # Read signed offset (usually negative)
                offset = self.rom.read_signed_word(self._bank, address)
                address += 2

                if offset > 0:
                    self.app.warningBox("Track Editor",
                                        f"Found positive rewind offset ({offset}) for channel {channel}.\n" +
                                        "This may have undesired effects.", "Track_Editor")

                # TODO Calculate item index based on each item's size, counting backwards
                data = TrackData.rewind(0)  # Use 0 for now
                data.raw = bytearray([0xFF, 0])
                data.raw += offset.to_bytes(2, "little", signed=True)
                loop_found = True

            elif control_byte >= 0xF0:                      # F0-FA - IGNORED
                value = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackData(function=value)
                data.raw = bytearray([value])

            else:                                           # 00-EF - NOTE
                index = control_byte

                duration = self.rom.read_byte(self._bank, address)
                address += 1

                if index > len(_notes):
                    self.warning(
                        f"Invalid note: ${control_byte:02X} for channel {channel} at ${self._bank:02X}:{address-2:04X}")
                    data = TrackData.note(0, 0)
                else:
                    data = TrackData.note(index, duration)

                data.raw = bytearray([index, duration])

            track.append(data)

        self._track_data[channel] = track

        return track

    # ------------------------------------------------------------------------------------------------------------------

    def read_instrument_data(self) -> None:
        """
        Reads instrument data from ROM buffer, and instrument names from ini file.
        """
        bank = self._bank

        if bank == 8:
            instrument_count = 50
            # Each instrument defines three duty/volume envelopes
            address = [0x8643, 0x86A7, 0x870B]
        else:
            self.info("Bank 9 not yet implemented.")
            return

        # Open names file, if there is one
        parser = configparser.ConfigParser()
        file_name = os.path.basename(self.rom.path).rsplit('.')[0] + "_instruments.ini"
        if os.path.exists(file_name):
            parser.read(file_name)

        # Clear previous instruments
        self._instruments.clear()

        for i in range(instrument_count):
            instrument: Instrument = Instrument()

            instrument.envelope_address.clear()
            for e in range(3):
                # Envelope pointer
                envelope_address = self.rom.read_word(bank, address[e])
                instrument.envelope_address.append(envelope_address)

                # Envelope data
                # Note that, like in the actual music engine, the first entry is the size
                size = self.rom.read_byte(bank, envelope_address)
                data = self.rom.read_bytes(bank, envelope_address, size + 1)
                instrument.envelope.append(data)

            instrument.name = parser.get("NAMES", f"{i}", fallback="(no name)")[:24]

            self._instruments.append(instrument)

            # Next instrument
            address[0] += 2
            address[1] += 2
            address[2] += 2

    # ------------------------------------------------------------------------------------------------------------------

    def track_info(self, channel: int) -> None:
        widget = f"SE_List_Channel_{channel}"

        self.app.clearListBox(widget, callFunction=False)

        i = 0
        for t in self._track_data[channel]:
            text = f"{i:03X} - {t.raw[0]:02X} - "

            if t.function == TrackData.CHANNEL_VOLUME:
                text += f"{t.raw[1]:02X} - -- - --"
                description = f"VOL {t.channel_volume:02}"
                bg = colour.DARK_BLUE
                fg = colour.PALE_LIME

            elif t.function == TrackData.SELECT_INSTRUMENT:
                text += f"{t.raw[1]:02X} - -- - --\n"
                description = f"INS {self._instruments[t.instrument_index].name[:19]}"
                bg = colour.DARK_ORANGE
                fg = colour.PALE_TEAL

            elif t.function == TrackData.SET_VIBRATO:
                text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
                description = f"VIB {'T^, ' if t.triangle_octave else ''} {t.vibrato_speed}, {t.vibrato_factor}"
                bg = colour.DARK_VIOLET
                fg = colour.PALE_PINK

            elif t.function == TrackData.REST:
                text += f"{t.raw[1]:02X} - -- - --"
                description = f"REST {t.rest_duration}"
                bg = colour.DARK_OLIVE
                fg = colour.PALE_MAGENTA

            elif t.function == TrackData.REWIND:
                text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
                description = f"RWD {t.loop_position}"
                bg = colour.DARK_MAGENTA
                fg = colour.PALE_VIOLET

            elif t.function == TrackData.PLAY_NOTE:
                text += f"{t.raw[1]:02X} - -- - --"
                description = f"       {_NOTE_NAMES[t.raw[0]]} {t.raw[1]:02}"
                bg = "#171717"
                fg = colour.PALE_ORANGE

            else:
                text += f"-- - -- - --"
                description = f"IGNORED"
                bg = colour.DARK_RED
                fg = colour.PALE_RED

            self.app.addListItem(widget, text, None, select=False)
            self.app.addListItem(widget, description, None, select=False)
            self.app.setListItemAtPosBg(widget, i + 1, bg)
            self.app.setListItemAtPosFg(widget, i + 1, fg)

            i += 2

    # ------------------------------------------------------------------------------------------------------------------

    def instrument_info(self) -> None:
        instrument = self._instruments[self._selected_instrument]

        self.app.clearEntry("IE_Instrument_Name", callFunction=False, setFocus=False)
        self.app.setEntry("IE_Instrument_Name", instrument.name, callFunction=False)

        # List this instrument's envelope values
        for e in range(3):
            self.app.clearListBox(f"IE_List_Envelope_{e}")
            envelope = instrument.envelope[e]
            for i in range(1, envelope[0] + 1):
                duty = envelope[i] >> 6
                volume = (envelope[i] & 0x3F) >> 1
                self.app.addListItem(f"IE_List_Envelope_{e}", f"{(i - 1):02X} {_DUTY[duty]} v{volume}", None, False)

            # Select first item in each list
            self.app.selectListItemAtPos(f"IE_List_Envelope_{e}", 0, True)

        # Update the graphs
        self._draw_volume_graph(0)
        self._draw_volume_graph(1)
        self._draw_volume_graph(2)

        self._draw_duty_graph(0)
        self._draw_duty_graph(1)
        self._draw_duty_graph(2)

        self._draw_full_graph()

    # ------------------------------------------------------------------------------------------------------------------

    def _update_instrument_name(self, widget: str) -> None:
        name = self.app.getEntry(widget)[:24]
        if len(name) < 1:
            name = "(no name)"
        self._instruments[self._selected_instrument].name = name

        # Update entry in the list
        self.app.setListItemAtPos("IE_List_Instrument", self._selected_instrument,
                                  f"{self._selected_instrument:02X} {name}")
        self.app.selectListItemAtPos("IE_List_Instrument", self._selected_instrument, callFunction=False)

        self._unsaved_changes_instrument = True

    # ------------------------------------------------------------------------------------------------------------------

    def _move_envelope(self, src: int, dst: int, item: int) -> None:
        """
        Moves an element between two envelopes in the currently selected instrument.

        Parameters
        ----------
        src: int
            Index of the source envelope (0-2)
        dst: int
            Index of the destination envelope (0-2)
        item: int
            Index of the item to transfer
        """
        instrument = self._instruments[self._selected_instrument]

        # Don't allow removing the last element
        if instrument.envelope[src][0] < 2:
            return

        # Remove from source envelope
        value = instrument.envelope[src].pop(item)
        # Decrement count
        instrument.envelope[src][0] -= 1

        # Add to destination envelope
        instrument.envelope[dst].append(value)
        # Increment count
        instrument.envelope[dst][0] += 1

    # ------------------------------------------------------------------------------------------------------------------

    def _track_input(self, widget: str) -> None:
        if widget == "SE_Play_Stop":
            if self._play_thread.is_alive():
                self.stop_playback()
                self.app.setButtonImage(widget, "res/play.gif")
            else:
                self.start_playback(True)
                self.app.setButtonImage(widget, "res/stop.gif")

        else:
            self.info(f"Unimplemented callback for widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _instruments_input(self, widget: str) -> None:
        if widget == "IE_Button_Apply":
            self.save_instrument_data()
            self._unsaved_changes_instrument = False
            self.close_instrument_editor()

        elif widget == "IE_Button_Cancel":
            self.close_instrument_editor()

        elif widget == "IE_List_Instrument":
            selection = self.app.getListBoxPos(widget)
            if len(selection) < 1:
                return
            self._selected_instrument = selection[0]
            self.instrument_info()
            self._restart_instrument_test()

        elif widget == "IE_Update_Name":
            self._update_instrument_name("IE_Instrument_Name")

        # Move envelope entry to previous envelope
        elif widget[:13] == "IE_Move_Left_":
            src = int(widget[-1], 10)   # Index of source envelope
            dst = (src - 1) % 3         # Index of destination envelope

            # Index of the selected element in the list
            selection = self.app.getListBoxPos(f"IE_List_Envelope_{src}")

            if len(selection) < 1:
                # Empty list
                return

            instrument = self._instruments[self._selected_instrument]

            # Don't allow removing the last element
            if instrument.envelope[src][0] < 2:
                return

            self._move_envelope(src, dst, selection[0] + 1)

            # Update UI
            self.instrument_info()

        # Move envelope entry to next envelope
        elif widget[:13] == "IE_Move_Right":
            src = int(widget[-1], 10)  # Index of source envelope
            dst = (src + 1) % 3  # Index of destination envelope

            # Index of the selected element in the list
            selection = self.app.getListBoxPos(f"IE_List_Envelope_{src}")

            if len(selection) < 1:
                # Empty list
                return

            instrument = self._instruments[self._selected_instrument]

            # Don't allow removing the last element
            if instrument.envelope[src][0] < 2:
                return

            self._move_envelope(src, dst, selection[0] + 1)

            # Update UI
            self.instrument_info()

        # Envelope entry selected
        elif widget[:17] == "IE_List_Envelope_":
            envelope_id = int(widget[-1], 10)
            instrument = self._instruments[self._selected_instrument]
            envelope = instrument.envelope[envelope_id]
            selection = self.app.getListBoxPos(widget)

            if len(selection) < 1:
                # Empty list
                return

            item = selection[0] + 1

            # Show this envelope's values in the widgets...
            duty = envelope[item] >> 6
            volume = (envelope[item] & 0x3F) >> 1
            if volume > 8:
                volume = 8
            self.app.setOptionBox(f"IE_Duty_{envelope_id}", duty, callFunction=False)
            self.app.setScale(f"IE_Volume_{envelope_id}", volume, callFunction=False)

        elif widget[:8] == "IE_Duty_":
            envelope_id = int(widget[-1], 10)
            instrument = self._instruments[self._selected_instrument]
            envelope = instrument.envelope[envelope_id]
            selection = self.app.getListBoxPos(f"IE_List_Envelope_{envelope_id}")
            if len(selection) < 1:
                # Empty list
                return

            item = selection[0] + 1

            # Change value
            value = self._get_selection_index(widget)
            volume = envelope[item] & 0x3F
            envelope[item] = volume | (value << 6)
            # Update list
            self.app.setListItemAtPos(f"IE_List_Envelope_{envelope_id}", selection[0],
                                      f"{selection[0]:02X} {_DUTY[value]} v{volume >> 1}")
            self.app.selectListItemAtPos(f"IE_List_Envelope_{envelope_id}", selection[0], callFunction=False)
            # Update graphs
            self._draw_duty_graph(envelope_id)
            self._draw_full_graph()

            self._unsaved_changes_instrument = True

        elif widget[:10] == "IE_Volume_":
            envelope_id = int(widget[-1], 10)
            instrument = self._instruments[self._selected_instrument]
            envelope = instrument.envelope[envelope_id]
            selection = self.app.getListBoxPos(f"IE_List_Envelope_{envelope_id}")
            if len(selection) < 1:
                # Empty list
                return

            item = selection[0] + 1

            # Change value
            value = self.app.getScale(widget)
            duty = (envelope[item] & 0xC0)
            envelope[item] = duty | ((value & 0x1F) << 1)
            # Update list
            self.app.setListItemAtPos(f"IE_List_Envelope_{envelope_id}", selection[0],
                                      f"{selection[0]:02X} {_DUTY[duty >> 6]} v{value}")
            self.app.selectListItemAtPos(f"IE_List_Envelope_{envelope_id}", selection[0], callFunction=False)
            # Update graph
            self._draw_volume_graph(envelope_id)
            # Don't update the full graph here: the button release callback will take care of that

            self._unsaved_changes_instrument = True

        elif widget == "IE_Button_Semiquaver":
            self._test_speed = 0
            self.app.button("IE_Button_Semiquaver", bg=colour.WHITE)
            self.app.button("IE_Button_Crotchet", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Minim", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Crotchet":
            self._test_speed = 1
            self.app.button("IE_Button_Semiquaver", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Crotchet", bg=colour.WHITE)
            self.app.button("IE_Button_Minim", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Minim":
            self._test_speed = 2
            self.app.button("IE_Button_Semiquaver", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Crotchet", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Minim", bg=colour.WHITE)
            self._restart_instrument_test()

        elif widget == "IE_Button_One_Note":
            self._test_notes = 0
            self.app.button("IE_Button_One_Note", bg=colour.WHITE)
            self.app.button("IE_Button_Scale", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Arpeggio", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Scale":
            self._test_notes = 1
            self.app.button("IE_Button_One_Note", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Scale", bg=colour.WHITE)
            self.app.button("IE_Button_Arpeggio", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Arpeggio":
            self._test_notes = 2
            self.app.button("IE_Button_One_Note", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Scale", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Arpeggio", bg=colour.WHITE)
            self._restart_instrument_test()

        elif widget == "IE_Button_Treble":
            self._test_octave = 0
            self.app.button("IE_Button_Treble", bg=colour.WHITE)
            self.app.button("IE_Button_Alto", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Bass", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Alto":
            self._test_octave = 1
            self.app.button("IE_Button_Treble", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Alto", bg=colour.WHITE)
            self.app.button("IE_Button_Bass", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Bass":
            self._test_octave = 2
            self.app.button("IE_Button_Treble", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Alto", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Bass", bg=colour.WHITE)
            self._restart_instrument_test()

        elif widget == "IE_Play_Stop":
            if self._play_thread.is_alive():
                self.stop_playback()
                self.app.setButtonImage(widget, "res/play.gif")
            else:
                note_length = 7 + (self._test_speed << 4)
                # Build some test data
                self._track_data[0] = []
                self._track_data[0].append(TrackData.volume(15))
                self._track_data[0].append(TrackData.instrument(self._selected_instrument))
                if self._test_octave == 2:
                    base_note = 0x0C
                elif self._test_octave == 1:
                    base_note = 0x18
                else:
                    base_note = 0x24

                if self._test_notes == 0:
                    self._track_data[0].append(TrackData.note(base_note + 7, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 7, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 7, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 7, note_length))
                elif self._test_notes == 1:
                    self._track_data[0].append(TrackData.note(base_note, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 2, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 4, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 5, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 7, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 9, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 11, note_length))
                else:
                    self._track_data[0].append(TrackData.note(base_note, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 4, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 7, note_length))
                    self._track_data[0].append(TrackData.note(base_note + 4, note_length))
                self._track_data[0].append(TrackData.rewind(2))
                # "Mute" other channels
                self._track_data[1] = []
                self._track_data[1].append(TrackData.volume(0))
                self._track_data[1].append(TrackData.rest(note_length))
                self._track_data[1].append(TrackData.rewind(0))
                self._track_data[2] = []
                self._track_data[2].append(TrackData.volume(0))
                self._track_data[2].append(TrackData.rest(note_length))
                self._track_data[2].append(TrackData.rewind(0))
                self._track_data[3] = []
                self._track_data[3].append(TrackData.volume(0))
                self._track_data[3].append(TrackData.rest(note_length))
                self._track_data[3].append(TrackData.rewind(0))

                self.start_playback(False)
                self.app.setButtonImage(widget, "res/stop.gif")

        else:
            self.info(f"Unimplemented callback for widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _draw_full_graph(self, event: any = None) -> None:     # noqa
        # Ignore the event parameter, it's there just so we can use this as a callback for Tkinter widgets

        width = self._canvas_graph.winfo_reqwidth()

        base_height = self._canvas_graph.winfo_reqheight() - 10

        vertical_step = base_height >> 3

        instrument = self._instruments[self._selected_instrument]

        line_width = 2

        # Calculate the number of items that we want to draw (one per each entry in each envelope)
        count = instrument.envelope[0][0] + instrument.envelope[1][0] + instrument.envelope[2][0]

        # Calculate the width of each segment in our line
        length = int(width / count)
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
        trail     tail
        _______________
            length
        """

        points = []

        e = 0   # Envelope index
        i = 1   # Item index

        x = 0   # Start from the left of the canvas

        for _ in range(count):
            duty = instrument.duty(e, i)
            volume = instrument.volume(e, i)

            # Starting points
            points.append((x, base_height))

            # Move right a bit
            points.append((x + trail, base_height))

            # Go up, depending on volume
            y = base_height - (volume * vertical_step)
            points.append((x + trail, y))

            # Draw the "hat", depending on duty
            points.append((x + trail + hat[duty], y))

            # Go back down
            points.append((x + trail + hat[duty], base_height))

            # Move to the end of this line
            points.append((x + length, base_height))

            # Next line will start here
            x = x + length
            i += 1

            if i > instrument.envelope[e][0]:
                i = 1
                e += 1
                if e > 2:
                    break

        flat = [a for x in points for a in x]
        if self._full_graph_line > 0:
            self._canvas_graph.coords(self._full_graph_line, *flat)
            self._canvas_graph.itemconfigure(self._full_graph_line, width=line_width)
        else:
            self._full_graph_line = self._canvas_graph.create_line(*flat, width=line_width, fill=colour.PALE_LIME)

    # ------------------------------------------------------------------------------------------------------------------

    def _draw_duty_graph(self, envelope_id: int) -> None:
        instrument = self._instruments[self._selected_instrument]
        envelope = instrument.envelope[envelope_id]

        canvas = self._canvas_envelope[envelope_id]

        # This will be the length of each "segment" of the line
        canvas_width = canvas.winfo_reqwidth()
        length = int(canvas_width / envelope[0])
        if length < 5:
            length = 5

        base_height = 32

        points = []

        for d in range(1, len(envelope)):
            duty = envelope[d] >> 6

            # Starting point
            x = (d - 1) * length
            y = base_height - (duty << 3)
            points.append((x, y))

            # End point
            points.append((x + length, y))

        flat = [a for x in points for a in x]

        if self._duty_lines[envelope_id] > 0:
            # Update existing line
            canvas.coords(self._duty_lines[envelope_id], *flat)
        else:
            # Create a new line
            self._duty_lines[envelope_id] = canvas.create_line(*flat, fill=colour.PALE_RED)

    # ------------------------------------------------------------------------------------------------------------------

    def _draw_volume_graph(self, envelope_id: int) -> None:
        instrument = self._instruments[self._selected_instrument]
        envelope = instrument.envelope[envelope_id]

        canvas = self._canvas_envelope[envelope_id]
        volume_bars = self._volume_bars[envelope_id]

        # Each bar's width will depend on how many entries are in this envelope, and how big the canvas is
        # Note: the canvas is 140x140
        width = int(canvas.winfo_reqwidth() / envelope[0])
        if width < 4:
            width = 4

        canvas_height = canvas.winfo_reqheight()
        v_ratio = int(canvas_height / 8) - 4
        min_height = canvas_height - 4

        for v in range(1, len(envelope)):
            value = (envelope[v] & 0x3F) >> 1

            x = (v - 1) * width
            y = canvas_height - (v_ratio * value) + 2
            if y > min_height:
                y = min_height

            # Check if there is already a canvas item for this bar
            if len(volume_bars) < v:
                bar = canvas.create_rectangle(x + 1, y, x + width - 1, 142, width=1,
                                              outline=colour.WHITE, fill=colour.PALE_BLUE)
                volume_bars.append(bar)
            elif volume_bars[v - 1] < 1:
                volume_bars[v - 1] = canvas.create_rectangle(x + 1, y, x + width - 1, 142, width=1,
                                                             outline=colour.WHITE, fill=colour.PALE_BLUE)
                canvas.itemconfigure(volume_bars[v], state="normal")
            else:
                canvas.coords(volume_bars[v - 1], x + 1, y, x + width - 1, 142)
                canvas.itemconfigure(volume_bars[v - 1], state="normal")

        # Hide unused bars
        for b in range(len(envelope) - 1, len(volume_bars)):
            if volume_bars[b] > 0:
                canvas.itemconfigure(volume_bars[b], state="hidden")

    # ------------------------------------------------------------------------------------------------------------------

    def _restart_instrument_test(self) -> None:
        """
        Restarts playback, if it was running, applying any new options.
        """
        if self._play_thread.is_alive():
            self.stop_playback()
            self._instruments_input("IE_Play_Stop")

    # ------------------------------------------------------------------------------------------------------------------

    def _tracker_update_loop(self) -> None:
        # Approximate NTSC timing
        frame_interval = 0.0166  # 1 / 60

        last_played: List[int] = [self._track_position[0],
                                  self._track_position[1],
                                  self._track_position[2],
                                  self._track_position[3]]

        widgets: List[str] = ["SE_List_Channel_0", "SE_List_Channel_1", "SE_List_Channel_2", "SE_List_Channel_3"]

        self.app.selectListItemAtPos(widgets[0], (last_played[0] << 1) + 1, callFunction=False)
        self.app.selectListItemAtPos(widgets[1], (last_played[1] << 1) + 1, callFunction=False)
        self.app.selectListItemAtPos(widgets[2], (last_played[2] << 1) + 1, callFunction=False)
        self.app.selectListItemAtPos(widgets[3], (last_played[3] << 1) + 1, callFunction=False)

        while self._playing:
            start_time = time.time()

            for c in range(3):
                if self._track_position[c] == last_played[c]:
                    pass
                else:
                    # Select currently playing item
                    last_played[c] = self._track_position[c]
                    self.app.selectListItemAtPos(widgets[c], (last_played[c] << 1) + 1, callFunction=False)

            interval = frame_interval - (time.time() - start_time)
            if interval >= 0:
                time.sleep(interval)

    # ------------------------------------------------------------------------------------------------------------------

    def _play_loop(self) -> None:
        if self._sound_server.getIsBooted() < 1:
            self._sound_server.boot()

        if self._sound_server.getIsStarted():
            # Already playing
            return

        self._sound_server.amp = 0.50
        self._sound_server.start()

        # Approximate NTSC timing
        frame_interval = 0.0166  # 1 / 60

        # Pre-build square wave tables
        # 12.5% duty
        table_d0: List[Tuple[int, float]] = [(0, 0), (1, 1), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0), (7, 0),
                                             (8, 0), (9, 1), (10, 0), (11, 0), (12, 0), (13, 0), (14, 0), (15, 0)]

        # 25% duty / 75%
        # table_d1 = [(0, 0), (1, 1), (2, 1), (3, 0), (4, 0), (5, 0), (6, 0), (7, 0)]
        table_d1 = table_d0.copy()
        table_d1[2] = (2, 1)
        table_d1[9] = (9, 1)

        # 50% duty
        # table_d2 = [(0, 0), (1, 1), (2, 1), (3, 1), (4, 1), (5, 0), (6, 0), (7, 0)]
        table_d2 = table_d1.copy()
        table_d2[3] = (3, 1)
        table_d2[4] = (4, 1)
        table_d2[10] = (10, 1)
        table_d2[11] = (11, 1)

        """
        table_flat = table_d0.copy()
        table_flat[1] = (1, 0)
        table_flat[9] = (9, 0)
        """

        # Pre-calculated volume levels table (volume can be 0-15)
        volume_tables: List[List[float]] = [[0, 0, 0, 0, 0, 0, 0, 0, 0],                        # 0: Muted
                                            [0.0] + [round(x / 48, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 44, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 40, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 36, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 32, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 28, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 26, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 24, 2) for x in range(1, 9)],    # 8: Half volume
                                            [0.0] + [round(x / 22, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 20, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 18, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 16, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 15, 2) for x in range(1, 9)],
                                            [0.0] + [round(x / 14, 2) for x in range(1, 9)],
                                            [0.0] + [x / 13 for x in range(1, 9)]]               # 15: Max volume

        # All channels start muted
        channel_volume = [volume_tables[0], volume_tables[0], volume_tables[0], volume_tables[0]]

        wave_table = [pyo.LinTable(table_d2, size=32),      # Square wave 0
                      pyo.LinTable(table_d2, size=32),      # Square wave 1
                      pyo.TriangleTable(order=1, size=32).mul(0.2),  # Triangle wave, more or less...
                      pyo.LinTable(table_d2, size=32)]      # Noise wave
        # wave_table[2].view()

        channel_instrument: List[int] = [0] * 4
        # Envelope trigger points
        channel_triggers: List[List[int]] = [[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]]

        channel_freq: List[int] = [0, 0, 0, 0]
        channel_oscillator: List[pyo.Osc] = [
            pyo.Osc(table=wave_table[0], freq=channel_freq[0], phase=[0, 0], interp=0).out(),
            pyo.Osc(table=wave_table[1], freq=channel_freq[1], phase=[0, 0], interp=0).out(),
            pyo.Osc(table=wave_table[2], freq=channel_freq[2], phase=[0, 0], interp=0).out(),
            pyo.Osc(table=wave_table[3], freq=channel_freq[3], phase=[0, 0], interp=0).out()]

        self._track_counter = [1, 1, 1, 1]      # Count down from here
        self._track_position = [0, 0, 0, 0]     # Start from the first item in the track

        self._slow_event.clear()

        # Triangle channel's notes will go up one octave when this is True
        # Instead of changing the note index, like in the game, we will halve the frequency when not set
        triangle_octave = False

        c = 0   # Currently playing channel

        # while not self._stop_event.is_set():
        while self._playing:
            start_time = time.time()

            # Putting these in a loop will slow playback down significantly. Sorry!

            # --- SQUARE WAVE 0 ---

            # Note that the initial value should be 1, so on the first iteration we immediately read
            # the first segment
            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = self._track_data[c][self._track_position[c]]
                self._track_position[c] += 1

                # Interpret this data

                # Notes are the most common
                if track_data.function == TrackData.PLAY_NOTE:
                    self._track_counter[c] = track_data.note_value.duration     # This will end this loop

                    # Frequency
                    channel_oscillator[c].setFreq(track_data.note_value.frequency)

                    instrument = self._instruments[channel_instrument[c]]

                    # Envelope trigger points for the current instrument
                    # This tell us when to switch to the next envelope
                    channel_triggers[c][0] = track_data.note_value.duration

                    channel_triggers[c][1] = track_data.note_value.duration - instrument.size(0)
                    if channel_triggers[c][1] < 0:
                        channel_triggers[c][1] = 0

                    value = channel_triggers[c][1] - instrument.size(2)
                    if value < 0:
                        value = 0

                    # Take the smallest between this value of the size of the previous envelope
                    if value >= instrument.size(1):
                        value = instrument.size(1)

                    channel_triggers[c][2] = channel_triggers[c][1] - value

                # Rests are the second most common item in any track
                elif track_data.function == TrackData.REST:
                    self._track_counter[c] = track_data.rest_duration
                    # Use flat wave to generate the "silence" rather than lowering the volume
                    # wave_table[c].replace(table_flat)
                    channel_oscillator[c].setFreq(0)

                elif track_data.function == TrackData.SELECT_INSTRUMENT:
                    channel_instrument[c] = track_data.instrument_index
                    # Counter is now 0

                elif track_data.function == TrackData.SET_VIBRATO:
                    # TODO Implement vibrato
                    # Change triangle channel octave offset
                    triangle_octave = track_data.triangle_octave

                elif track_data.function == TrackData.CHANNEL_VOLUME:
                    # The triangle channel is only either on or off
                    channel_volume[c] = volume_tables[track_data.channel_volume]
                    # Note that counter will be 0 now, so we will read another segment

                elif track_data.function == TrackData.REWIND:
                    # TODO Terminate playback if loop option unchecked, something like:
                    # if not self._loop:
                    #   self._playing = False
                    self._track_position[c] = track_data.loop_position
                    # Counter should now be 0

                # Ignore anything else ($3C-$FA control bytes)

            # Generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note

                # Choose one of the 3 envelopes in the current instrument based on trigger points
                envelope = 0
                if self._track_counter[c] < channel_triggers[c][1]:
                    if self._track_counter[c] < channel_triggers[c][2]:
                        envelope = 2
                    else:
                        envelope = 1

                index = channel_triggers[c][envelope] - self._track_counter[c] + 1
                if index > self._instruments[channel_instrument[c]].envelope[envelope][0]:
                    index = self._instruments[channel_instrument[c]].envelope[envelope][0]
                elif index < 0:
                    index = 1

                # duty = self._instruments[channel_instrument[c]].duty(envelope, index)
                duty = self._instruments[channel_instrument[c]].envelope[envelope][index] >> 6
                # Use pre-calculated volume levels
                volume = channel_volume[c][(self._instruments[channel_instrument[c]].envelope[envelope][index] &
                                            0x3F) >> 1]

                # Update duty cycle and volume according to envelopes
                if duty == 0:       # 12.5% duty
                    table_d0[1] = (1, volume)
                    table_d0[8] = (8, volume)
                    wave_table[c].replace(table_d0)
                elif duty == 2:     # 50% duty
                    table_d2[1] = (1, volume)
                    table_d2[2] = (2, volume)
                    table_d2[3] = (3, volume)
                    table_d2[4] = (4, volume)
                    table_d2[8] = (8, volume)
                    table_d2[9] = (9, volume)
                    table_d2[10] = (10, volume)
                    table_d2[11] = (11, volume)
                    wave_table[c].replace(table_d2)
                else:               # 25% and 75% duty
                    table_d1[1] = (1, volume)
                    table_d1[2] = (2, volume)
                    table_d1[8] = (8, volume)
                    table_d1[9] = (9, volume)
                    wave_table[c].replace(table_d1)

            # --- SQUARE WAVE 1 ---
            c = 1

            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = self._track_data[c][self._track_position[c]]
                self._track_position[c] += 1

                if track_data.function == TrackData.PLAY_NOTE:
                    self._track_counter[c] = track_data.note_value.duration  # This will end this loop

                    # Frequency
                    channel_oscillator[c].setFreq(track_data.note_value.frequency)

                    instrument = self._instruments[channel_instrument[c]]

                    # Envelope trigger points for the current instrument
                    # This tell us when to switch to the next envelope
                    channel_triggers[c][0] = track_data.note_value.duration

                    channel_triggers[c][1] = track_data.note_value.duration - instrument.size(0)
                    if channel_triggers[c][1] < 0:
                        channel_triggers[c][1] = 0

                    value = channel_triggers[c][1] - instrument.size(2)
                    if value < 0:
                        value = 0

                    # Take the smallest between this value of the size of the previous envelope
                    if value >= instrument.size(1):
                        value = instrument.size(1)

                    channel_triggers[c][2] = channel_triggers[c][1] - value

                elif track_data.function == TrackData.REST:
                    self._track_counter[c] = track_data.rest_duration
                    # Use flat wave to generate the "silence" rather than lowering the volume
                    # wave_table[c].replace(table_flat)
                    channel_oscillator[c].setFreq(0)

                elif track_data.function == TrackData.SELECT_INSTRUMENT:
                    channel_instrument[c] = track_data.instrument_index

                elif track_data.function == TrackData.SET_VIBRATO:
                    # TODO Implement vibrato / change triangle channel octave offset
                    pass

                elif track_data.function == TrackData.CHANNEL_VOLUME:
                    channel_volume[c] = volume_tables[track_data.channel_volume]
                    # Note that counter will be 0 now, so we will read another segment

                elif track_data.function == TrackData.REWIND:
                    self._track_position[c] = track_data.loop_position

                # Ignore anything else ($3C-$FA control bytes)

            # Generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note

                # Choose one of the 3 envelopes in the current instrument based on trigger points
                envelope = 0
                if self._track_counter[c] < channel_triggers[c][1]:
                    if self._track_counter[c] < channel_triggers[c][2]:
                        envelope = 2
                    else:
                        envelope = 1

                index = channel_triggers[c][envelope] - self._track_counter[c] + 1
                if index > self._instruments[channel_instrument[c]].envelope[envelope][0]:
                    index = self._instruments[channel_instrument[c]].envelope[envelope][0]
                elif index < 0:
                    index = 1

                # duty = self._instruments[channel_instrument[c]].duty(envelope, index)
                duty = self._instruments[channel_instrument[c]].envelope[envelope][index] >> 6
                # Use pre-calculated volume levels
                volume = channel_volume[c][(self._instruments[channel_instrument[c]].envelope[envelope][index] &
                                            0x3F) >> 1]

                # Update duty cycle and volume according to envelopes
                if duty == 0:  # 12.5% duty
                    table_d0[1] = (1, volume)
                    table_d0[8] = (8, volume)
                    wave_table[c].replace(table_d0)
                elif duty == 2:  # 50% duty
                    table_d2[1] = (1, volume)
                    table_d2[2] = (2, volume)
                    table_d2[3] = (3, volume)
                    table_d2[4] = (4, volume)
                    table_d2[8] = (8, volume)
                    table_d2[9] = (9, volume)
                    table_d2[10] = (10, volume)
                    table_d2[11] = (11, volume)
                    wave_table[c].replace(table_d2)
                else:  # 25% and 75% duty
                    table_d1[1] = (1, volume)
                    table_d1[2] = (2, volume)
                    table_d1[8] = (8, volume)
                    table_d1[9] = (9, volume)
                    wave_table[c].replace(table_d1)

            # --- TRIANGLE WAVE ---
            c = 2

            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = self._track_data[c][self._track_position[c]]
                self._track_position[c] += 1

                if track_data.function == TrackData.PLAY_NOTE:
                    self._track_counter[c] = track_data.note_value.duration  # This will end this loop

                    # Frequency
                    if triangle_octave is True:
                        channel_oscillator[c].setFreq(track_data.note_value.frequency << 1)
                    else:
                        channel_oscillator[c].setFreq(track_data.note_value.frequency)

                    # This channel does not use instruments / envelopes, because it does not have volume / duty

                elif track_data.function == TrackData.REST:
                    self._track_counter[c] = track_data.rest_duration
                    # Use flat wave to generate the "silence" rather than lowering the volume
                    # wave_table[c].replace(table_flat)
                    channel_oscillator[c].setFreq(0)

                elif track_data.function == TrackData.SELECT_INSTRUMENT:
                    channel_instrument[c] = track_data.instrument_index

                elif track_data.function == TrackData.SET_VIBRATO:
                    # TODO Implement vibrato
                    # Change triangle channel octave offset
                    if track_data.raw[1] == 0xFF:
                        triangle_octave = True
                    else:
                        triangle_octave = False

                elif track_data.function == TrackData.CHANNEL_VOLUME:
                    if track_data.channel_volume == 15:
                        wave_table[c].setOrder(1)
                        wave_table[c].mul(0.25)
                    else:
                        wave_table[c].setOrder(0)
                    # Note that counter will be 0 now, so we will read another segment

                elif track_data.function == TrackData.REWIND:
                    self._track_position[c] = track_data.loop_position

                # Ignore anything else ($3C-$FA control bytes)

            # Generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note
                # TODO Vibrato?
                pass

            # --- End of channel data ---

            # Restart from channel 0
            c = 0

            interval = frame_interval - (time.time() - start_time)
            if interval >= 0:
                time.sleep(interval)
            else:
                self._slow_event.set()

        # --- End of playback loop ---

        channel_oscillator[0].stop()
        channel_oscillator[1].stop()
        channel_oscillator[2].stop()
        channel_oscillator[3].stop()

        # self.info("Sound playback thread terminated.")
        self._sound_server.stop()
