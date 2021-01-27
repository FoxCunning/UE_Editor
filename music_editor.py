__author__ = "Fox Cunning"

import configparser
import os
import sys
import threading
import time
import tkinter

import pyo

from dataclasses import dataclass, field
from tkinter import Canvas
from typing import List, Tuple

import colour
from appJar import gui
from appJar.appjar import ItemLookupError
from debug import log
from editor_settings import EditorSettings
from rom import ROM

# Note definitions as read from ROM
_notes: List[int] = []

# TODO Create note names based on the period (with approximation), in case they had been modified in ROM
_NOTE_NAMES = ["C2 ", "C#2", "D2 ", "D#2", "E2 ", "F2 ", "F#2", "G2 ", "G#2", "A2 ", "A#2", "B2 ",
               "C3 ", "C#3", "D3 ", "D#3", "E3 ", "F3 ", "F#3", "G3 ", "G#3", "A3 ", "A#3", "B3 ",
               "C4 ", "C#4", "D4 ", "D#4", "E4 ", "F4 ", "F#4", "G4 ", "G#4", "A4 ", "A#4", "B4 ",
               "C5 ", "C#5", "D5 ", "D#5", "E5 ", "F5 ", "F#5", "G5 ", "G#5", "A5 ", "A#5", "B5 ",
               "C6 ", "C#6", "D6 ", "D#6", "E6 ", "F6 ", "F#6", "G6 ", "G#6", "A6 ", "A#6", "B6 "]

# This is to quickly get a duty representation based on the register's value
_DUTY = ["12.5%", "  25%", "  50%", "  75%"]


# ----------------------------------------------------------------------------------------------------------------------

@dataclass(init=True, repr=False)
class MemoryChunk:
    """
    A class used to form a memory map used to allocate space for music tracks.

    Properties
    ----------
    channel_pointer: List[int]
        A list of four pointers, one per channel
    channel_size: List[int]
        The size, in bytes, of each channel's data
    """
    channel_pointer: List[int] = field(default_factory=list)
    channel_size: List[int] = field(default_factory=list)


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

        self.index: int = index
        self.duration: int = duration

        # From the NESDev Wiki:
        # frequency = fCPU/(16*(period+1))
        # fCPU = 1.789773 MHz for NTSC, 1.662607 MHz for PAL, and 1.773448 MHz for Dendy
        if index < len(_notes):
            period = _notes[index]
        else:
            period = 0x6AB  # A default value to use until notes are loaded

        self.frequency: int = self.CPU_FREQ // ((period + 1) << 4)


# ----------------------------------------------------------------------------------------------------------------------

class TrackDataEntry:
    """
    Represents one entry in one channel's data.

    Properties
    ----------
    function: int
        Function of this data segment

    params: int
        Up to 3 parameters for this data segment
    """
    # Control values:
    PLAY_NOTE: int = 0
    CHANNEL_VOLUME: int = 0xFB
    SELECT_INSTRUMENT: int = 0xFC
    SET_VIBRATO: int = 0xFD
    REST: int = 0xFE
    REWIND: int = 0xFF

    def __init__(self, control: int = 0, channel_volume: int = 0, instrument_index: int = 0, loop_position: int = 0,
                 vibrato_speed: int = 0, vibrato_factor: int = 0, rest_duration: int = 0, triangle_octave: bool = False,
                 note: Note = Note(), size: int = 0, raw: bytearray = bytearray()):
        self.control: int = control

        self.channel_volume: int = channel_volume
        self.instrument_index: int = instrument_index
        # Index of the item to loop from
        self.loop_position: int = loop_position
        self.vibrato_speed: int = vibrato_speed
        self.vibrato_factor: int = vibrato_factor
        self.rest_duration: int = rest_duration
        # Play notes 12 semitones higher if True
        self.triangle_octave: bool = triangle_octave
        self.note_value: Note = note

        # How many bytes does this entry take
        self.size: int = size

        # Raw bytes forming this entry
        self.raw: bytearray = raw

    # "set" functions automatically update the raw value (except for the rewind offset)

    def set_volume(self, level: int) -> None:
        self.channel_volume = level
        self.raw[1] = level

    def set_instrument(self, index: int) -> None:
        self.instrument_index = index
        self.raw[1] = index

    def set_vibrato(self, octave: bool, speed: int, factor: int) -> None:
        self.triangle_octave = octave
        self.vibrato_speed = speed
        self.vibrato_factor = factor
        self.raw[1] = 0 if octave else 0xFF
        self.raw[2], self.raw[3] = speed, factor

    def set_rest(self, duration: int) -> None:
        self.rest_duration = duration
        self.raw[1] = duration

    def set_rewind(self, position: int) -> None:
        self.loop_position = position
        # TODO raw value must be calculated from the instance holding the array with all the elements

    def set_note(self, index: int, duration: int) -> None:
        self.note_value = Note(index, duration)
        self.raw[0], self.raw[1] = index, duration

    @classmethod
    def new_volume(cls, level: int):
        return cls(control=cls.CHANNEL_VOLUME, channel_volume=level & 0x0F, size=2,
                   raw=bytearray([0xFB, (level << 4) | 0x0F]))

    @classmethod
    def new_instrument(cls, index: int):
        return cls(control=cls.SELECT_INSTRUMENT, instrument_index=index, size=2,
                   raw=bytearray([0xFC, index]))

    @classmethod
    def new_vibrato(cls, higher_octave: bool, speed: int, factor: int):
        if speed < 2:
            return cls(control=cls.SET_VIBRATO, triangle_octave=higher_octave, vibrato_speed=0,
                       vibrato_factor=0, size=4,
                       raw=bytearray([0xFD, 0 if higher_octave else 0xFF, 0, 0]))
        else:
            return cls(control=cls.SET_VIBRATO, triangle_octave=higher_octave, vibrato_speed=speed,
                       vibrato_factor=factor, size=4,
                       raw=bytearray([0xFD, 0 if higher_octave else 0xFF, speed, factor]))

    @classmethod
    def new_rest(cls, duration: int):
        return cls(control=cls.REST, rest_duration=duration, size=2,
                   raw=bytearray([0xFE, duration]))

    @classmethod
    def new_rewind(cls, position: int, offset: int = 0):
        # TODO Offset must be recalculated when adding or removing elements
        # The offset is the difference between the position (in number of bytes) of the rewind element and the position
        # where we want to jump to
        # In order to know where the rewind element is, we need to sum the sizes of every previous element

        return cls(control=cls.REWIND, loop_position=position, size=4,
                   raw=bytearray([0xFF, 0, offset & 0x00FF, offset >> 8]))

    @classmethod
    def new_note(cls, index: int, duration: int):
        return cls(control=cls.PLAY_NOTE, note=Note(index, duration), size=2,
                   raw=bytearray([index, duration]))


# ----------------------------------------------------------------------------------------------------------------------

class MusicEditor:

    def __init__(self, app: gui, rom: ROM, settings: EditorSettings):
        self.app = app
        self.rom = rom

        self._bank: int = 8

        # --- Track Editor ---
        self._track_address: List[int] = [0, 0, 0, 0]
        self._selected_channel: int = 0
        self._selected_element: int = 0

        # --- Instrument Editor ---
        self._instruments: List[Instrument] = []
        self._selected_instrument: int = 0

        # TODO Allow users to choose more options via settings
        if sys.platform == "win32":
            self._sound_server: pyo.Server = pyo.Server(sr=settings.get("sample rate"), duplex=0, nchnls=1,
                                                        winhost=settings.get("audio host"), buffersize=1024).boot()
        else:
            self._sound_server: pyo.Server = pyo.Server(sr=settings.get("sample rate"), duplex=0, nchnls=1,
                                                        buffersize=1024).boot()
        self._sound_server.setAmp(0.2)

        self._triangle_volume = 0.2

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
        self._track_data: List[List[TrackDataEntry]] = [[], [], [], []]
        self._track_position: List[int] = [0, 0, 0, 0]

        # Starts from 1 and is decreased each frame. When 0, read next data segment.
        self._track_counter: List[int] = [1, 1, 1, 1]

        # Used for testing instruments
        self._test_octave: int = 0  # 0: Treble, 1: Alto, 2: Bass
        self._test_notes: int = 0  # 0: Single note loop, 1: Scales, 2: Arpeggios
        self._test_speed: int = 0  # 0: Short notes, 1: Medium notes, 3: Long notes

        # Threading
        self._play_thread: threading.Thread = threading.Thread()
        self._update_thread: threading.Thread = threading.Thread()
        self._stop_event: threading.Event = threading.Event()  # Signals the playback thread that it should stop
        self._slow_event: threading.Event = threading.Event()  # Used by the playback thread to signal slow processing
        self._playing: bool = False

        # Read music pointers and calculate size of each track
        # This will be needed when saving track data to ROM
        self._memory_map_8: List[MemoryChunk] = []

        base_pointer = 0x8051
        # There is a maximum of 11 tracks in bank 8
        for t in range(11):
            addresses = [self.rom.read_word(0x8, base_pointer), self.rom.read_word(0x8, base_pointer + 2),
                         self.rom.read_word(0x8, base_pointer + 4), self.rom.read_word(0x8, base_pointer + 6)]
            size = [self.get_data_size(0x8, addresses[0]), self.get_data_size(0x8, addresses[1]),
                    self.get_data_size(0x8, addresses[1]), self.get_data_size(0x8, addresses[2])]
            self._memory_map_8.append(MemoryChunk(addresses, size))
            base_pointer += 8

        # ...and there is room for 9 pointers in bank 9
        self._memory_map_9: List[MemoryChunk] = []
        base_pointer = 0x8051
        # There is a maximum of 11 tracks in bank 8
        for t in range(9):
            addresses = [self.rom.read_word(0x9, base_pointer), self.rom.read_word(0x9, base_pointer + 2),
                         self.rom.read_word(0x9, base_pointer + 4), self.rom.read_word(0x9, base_pointer + 6)]
            size = [self.get_data_size(0x9, addresses[0]), self.get_data_size(0x9, addresses[1]),
                    self.get_data_size(0x9, addresses[1]), self.get_data_size(0x9, addresses[2])]
            self._memory_map_9.append(MemoryChunk(addresses, size))
            base_pointer += 8

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
                                                      "Any unsaved changes will be lost.",
                                 "Instrument_Editor") is False:
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
            self._update_thread.join(1)
            if self._update_thread.is_alive():
                self.warning("Timeout waiting for UI update thread.")

        if self._play_thread.is_alive():
            self._play_thread.join(1)
            if self._play_thread.is_alive():
                self.warning("Timeout waiting for playback thread.")
                self._sound_server.stop()

            if self._slow_event.is_set():
                self.warning("Slow playback detected! This may be due to too many non-note events in a track, or " +
                             "a slow machine, or slow audio host API.")

    # ------------------------------------------------------------------------------------------------------------------

    def start_playback(self, update_tracker: bool = False) -> None:
        # self._stop_event.clear()
        self._playing = True

        if self._play_thread.is_alive():
            self.warning("Playback thread already running!")
        else:
            self._play_thread = threading.Thread(target=self._play_loop, args=())
            self._play_thread.start()

        if update_tracker:
            if self._update_thread.is_alive():
                self.warning("UI Update thread already running!")
            else:
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

        instrument_names: List[str] = []
        i = 0
        for instrument in self._instruments:
            instrument_names.append(f"{i:02X} {instrument.name if len(instrument.name) > 0 else '(no name)'}")
            i += 1

        # Read track data for all tracks
        self.read_track_data(0)
        self.read_track_data(1)
        self.read_track_data(2)
        self.read_track_data(3)

        if window_exists:
            self.app.showSubWindow("Track_Editor")
            return

        with self.app.subWindow("Track_Editor"):

            # Buttons
            with self.app.frame("SE_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0):
                # Left
                self.app.button("SE_Button_Apply", self._track_input, image="res/floppy.gif", width=32, height=32,
                                tooltip="Apply changes to all channels", bg=colour.MEDIUM_GREY,
                                sticky="W", row=0, column=0)
                self.app.button("SE_Button_Import", self._track_input, image="res/import.gif", width=32, height=32,
                                tooltip="Import FamiStudio / FamiTracker text file", bg=colour.MEDIUM_GREY,
                                sticky="W", row=0, column=1)
                self.app.button("SE_Button_Export", self._track_input, image="res/import.gif", width=32, height=32,
                                tooltip="Export to FamiStudio / FamiTracker text file", bg=colour.MEDIUM_GREY,
                                sticky="W", row=0, column=2)
                self.app.button("SE_Button_Reload", self._track_input, image="res/reload.gif", width=32, height=32,
                                tooltip="Reload track data from ROM", bg=colour.MEDIUM_GREY,
                                sticky="W", row=0, column=3)
                self.app.button("SE_Button_Cancel", self._track_input, image="res/close.gif", width=32, height=32,
                                tooltip="Cancel / Close window", bg=colour.MEDIUM_GREY,
                                sticky="W", row=0, column=4)

                self.app.canvas("SE_Temp", width=250, height=20, row=0, column=5)

                # Right
                self.app.button("SE_Play_Stop", self._track_input, image="res/play.gif", width=32, height=32,
                                tooltip="Start / Stop track playback", bg=colour.MEDIUM_GREY,
                                sticky="E", row=0, column=6)
                self.app.button("SE_Button_Rewind", self._track_input, image="res/rewind.gif", width=32, height=32,
                                tooltip="Jump to the first element of each channel", bg=colour.MEDIUM_GREY,
                                sticky="E", row=0, column=7)
                self.app.button("SE_Button_Info", self._track_input, image="res/info.gif", width=32, height=32,
                                tooltip="Show track info/statistics", bg=colour.MEDIUM_GREY,
                                sticky="E", row=0, column=8)

            # Editing
            with self.app.frame("SE_Frame_Editing", sticky="NEWS", row=1, column=0):
                # Editable track info
                with self.app.labelFrame("SE_Frame_Track_Info", name="Track Info", padding=[4, 2],
                                         row=0, column=0, rowspan=2):
                    self.app.entry("SE_Track_Name", f"{self.read_track_titles()[track]}", width=24,
                                   row=0, column=0, colspan=3, font=9)

                    self.app.image("SE_Image_Channel_Address_0", "res/square_0.gif", sticky="E", row=1, column=0)
                    self.app.entry("SE_Channel_Address_0", "", width=8, row=1, column=1, font=10)
                    self.app.button("SE_Reload_Channel_0", self._track_input, image="res/reload-small.gif",
                                    tooltip="Reload channel from this address",
                                    bg=colour.MEDIUM_BLUE, sticky="W", row=1, column=2)

                    self.app.image("SE_Label_Channel_Address_1", "res/square_1.gif", sticky="E", row=2, column=0)
                    self.app.entry("SE_Channel_Address_1", "", width=8, row=2, column=1, font=10)
                    self.app.button("SE_Reload_Channel_1", self._track_input, image="res/reload-small.gif",
                                    tooltip="Reload channel from this address",
                                    bg=colour.MEDIUM_BLUE, sticky="W", row=2, column=2)

                    self.app.image("SE_Image_Channel_Address_2", "res/triangle_wave.gif", sticky="E", row=3, column=0)
                    self.app.entry("SE_Channel_Address_2", "", width=8, row=3, column=1, font=10)
                    self.app.button("SE_Reload_Channel_2", self._track_input, image="res/reload-small.gif",
                                    tooltip="Reload channel from this address",
                                    bg=colour.MEDIUM_BLUE, sticky="W", row=3, column=2)

                    self.app.image("SE_Label_Channel_Address_3", "res/noise_wave.gif", sticky="E", row=4, column=0)
                    self.app.entry("SE_Channel_Address_3", "", width=8, row=4, column=1, font=10)
                    self.app.button("SE_Reload_Channel_3", self._track_input, image="res/reload-small.gif",
                                    tooltip="Reload channel from this address",
                                    bg=colour.MEDIUM_BLUE, sticky="W", row=4, column=2)

                # Selection info
                with self.app.frame("SE_Frame_Selection_Info", padding=[4, 0], row=0, column=1, fg=colour.PALE_ORANGE):
                    self.app.label("SE_Selection_Info_Channel", "Channel: (no selection)", sticky="W",
                                   row=0, column=0, font=9)
                    self.app.label("SE_Selection_Info_Element", "Element: (no selection)", sticky="W",
                                   row=1, column=0, font=9)

                # Element editing controls
                with self.app.frameStack("SE_Stack_Editing", start=0, row=1, column=1):
                    with self.app.frame("SE_Frame_Empty", padding=[4, 4], bg=colour.DARK_NAVY, fg=colour.WHITE):
                        self.app.label("SE_Label_No_Selection", "No selection", font=12)

                    # Edit volume
                    with self.app.frame("SE_Frame_Volume", padding=[4, 4], bg=colour.DARK_BLUE, fg=colour.PALE_LIME):
                        self.app.label("SE_Label_Volume_Element", "EDIT VOLUME", sticky="NW",
                                       row=0, column=0, colspan=2, font=12)
                        self.app.label("SE_Label_Edit_Volume", "Value: ", sticky="E", row=1, column=0, font=10)
                        self.app.entry("SE_Entry_Volume", "0", submit=self._element_input,
                                       sticky="W", width=3, row=1, column=1, font=9)

                        self.app.button("SE_Apply_Volume", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.DARK_BLUE,
                                        sticky="SEW", row=1, column=0, colspan=2)

                    # Edit note
                    with self.app.frame("SE_Frame_Note", padding=[4, 4], bg=colour.BLACK, fg=colour.PALE_ORANGE):
                        self.app.label("SE_Label_Note", "EDIT NOTE", sticky="NW", colspan=3, font=12)

                        self.app.label("SE_Label_Note_Value", "Value:", sticky="SE", row=0, column=0, font=10)
                        self.app.entry("SE_Note_Value", " ", submit=self._element_input,
                                       width=4, sticky="SW", row=0, column=1, font=9)

                        self.app.label("SE_Label_Note_Duration", "Duration:", sticky="SE", row=0, column=2, font=10)
                        self.app.entry("SE_Note_Duration", " ", submit=self._element_input,
                                       width=4, sticky="SW", row=0, column=3, font=9)

                        self.app.button("SE_Apply_Note", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.BLACK,
                                        sticky="SEW", row=1, column=0, colspan=4)

                    # Edit rest
                    with self.app.frame("SE_Frame_Rest", padding=[4, 4], bg=colour.DARK_OLIVE, fg=colour.PALE_MAGENTA):
                        self.app.label("SE_Label_Rest_Element", "EDIT REST", sticky="NW",
                                       row=0, column=0, colspan=2, font=12)
                        self.app.label("SE_Label_Edit_Rest", "Duration:", sticky="E", row=1, column=0, font=10)
                        self.app.entry("SE_Rest_Duration", "0", submit=self._element_input,
                                       sticky="W", width=3, row=1, column=1, font=9)

                        self.app.button("SE_Apply_Rest", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.DARK_OLIVE,
                                        sticky="SEW", row=1, column=0, colspan=2)

                    # Edit vibrato
                    with self.app.frame("SE_Frame_Vibrato", padding=[4, 4], bg=colour.DARK_VIOLET, fg=colour.PALE_PINK):
                        self.app.label("SE_Label_Vibrato", "EDIT VIBRATO", sticky="NW", colspan=3, font=12)

                        self.app.checkBox("SE_Triangle_Octave", False, text="Triangle Octave Up",
                                          change=self._element_input, selectcolor=colour.MEDIUM_VIOLET,
                                          sticky="SEW", row=0, column=0, colspan=4, font=10)

                        self.app.label("SE_Label_Vibrato_Speed", "Speed:", sticky="SE", row=1, column=0, font=10)
                        self.app.entry("SE_Vibrato_Speed", " ", submit=self._element_input,
                                       width=4, sticky="SW", row=1, column=1, font=9)

                        self.app.label("SE_Label_Vibrato_Factor", "Factor:", sticky="SE", row=1, column=2, font=10)
                        self.app.entry("SE_Vibrato_Factor", " ", submit=self._element_input,
                                       width=4, sticky="SW", row=1, column=3, font=9)

                        self.app.button("SE_Apply_Vibrato", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.DARK_VIOLET,
                                        sticky="SEW", row=2, column=0, colspan=4)

                    # Edit instrument
                    with self.app.frame("SE_Frame_Instrument", padding=[4, 4], bg=colour.DARK_ORANGE,
                                        fg=colour.PALE_TEAL):
                        self.app.label("SE_Label_Instrument", "EDIT INSTRUMENT", sticky="NW",
                                       row=0, column=0, font=12)

                        self.app.listBox("SE_Select_Instrument", instrument_names, change=self._element_input,
                                         bg=colour.DARK_ORANGE, fg=colour.PALE_TEAL, group=True, multi=False,
                                         fixed_scrollbar=True, width=27, height=9, sticky="W", row=1, column=0, font=9)

                    # Edit rewind
                    with self.app.frame("SE_Frame_Rewind", padding=[4, 4], bg=colour.DARK_MAGENTA,
                                        fg=colour.PALE_VIOLET):
                        self.app.label("SE_Label_Rewind", "EDIT REWIND", sticky="NW",
                                       row=0, column=0, colspan=2, font=12)

                        self.app.label("SE_Label_Edit_Rewind", "Rewind to element:",
                                       sticky="E", row=1, column=0, font=10)
                        self.app.entry("SE_Rewind_Value", "0", submit=self._element_input,
                                       sticky="W", width=3, row=1, column=1, font=9)

                        self.app.button("SE_Apply_Rewind", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.DARK_MAGENTA,
                                        sticky="SEW", row=1, column=0, colspan=2)

                    # Edit multiple
                    with self.app.frame("SE_Frame_Multiple", padding=[4, 4], bg=colour.DARK_VIOLET, fg=colour.WHITE):
                        self.app.label("SE_Label_Multiple", "MULTIPLE SELECTION", sticky="NW",
                                       row=0, column=0, colspan=3, font=12)

                        self.app.label("SE_Label_Change_Duration", "Change note duration:",
                                       sticky="SE", row=1, column=0, font=10)
                        self.app.button("SE_Duration_Up", self._element_input, image="res/note_duration_up.gif",
                                        bg=colour.DARK_BLUE, sticky="SW", row=1, column=1)
                        self.app.button("SE_Duration_Down", self._element_input, image="res/note_duration_down.gif",
                                        bg=colour.DARK_BLUE, sticky="SW", row=1, column=2)

                        self.app.label("SE_Label_Shift", "Shift notes:", sticky="SE", row=2, column=0, font=10)
                        self.app.button("SE_Semitone_Up", self._element_input, image="res/semitone_up.gif",
                                        bg=colour.DARK_BLUE, sticky="SW", row=2, column=1)
                        self.app.button("SE_Semitone_Down", self._element_input, image="res/semitone_down.gif",
                                        bg=colour.DARK_BLUE, sticky="SW", row=2, column=2)

                # Selection controls
                with self.app.frame("SE_Frame_Selection", padding=[4, 2], row=0, column=2, rowspan=2):
                    self.app.label("SE_Label_Select", "Select Notes", sticky="NEW", row=0, column=0, font=12)

                    with self.app.frame("SE_Frame_Selection_Buttons", padding=[4, 2], row=1, column=0):
                        self.app.button("SE_Select_Channel_0", self._track_input, image="res/square_0.gif",
                                        bg=colour.MEDIUM_GREEN, row=0, column=0)
                        self.app.button("SE_Select_Channel_1", self._track_input, image="res/square_1.gif",
                                        bg=colour.DARK_NAVY, row=0, column=1)
                        self.app.button("SE_Select_Channel_2", self._track_input, image="res/triangle_wave.gif",
                                        bg=colour.DARK_NAVY, row=0, column=2)
                        self.app.button("SE_Select_Channel_3", self._track_input, image="res/noise_wave.gif",
                                        bg=colour.DARK_NAVY, row=0, column=3)

                    with self.app.frame("SE_Frame_Selection_Values", padding=[4, 2], row=2, column=0):
                        self.app.label("SE_Label_Select_From", "All notes from:", sticky="E", row=0, column=0, font=10)
                        self.app.entry("SE_Select_From", "C2", change=self._track_input, width=4,
                                       sticky="W", row=0, column=1, font=9)
                        self.app.label("SE_Label_Select_To", " to: ", sticky="E", row=0, column=2, font=10)
                        self.app.entry("SE_Select_To", "C3", change=self._track_input, width=4,
                                       sticky="W", row=0, column=3, font=9)

                    self.app.button("SE_Apply_Selection", self._track_input, image="res/check_green-small.gif",
                                    tooltip="Apply Selection",
                                    bg=colour.DARK_NAVY, sticky="SEW", row=3, column=0)
                    self.app.button("SE_Clear_Selection", self._track_input, image="res/clear_selection-small.gif",
                                    tooltip="Clear Selection",
                                    bg=colour.DARK_VIOLET, sticky="SEW", row=4, column=0)

                # Volume controls
                with self.app.frame("SE_Frame_Volumes", padding=[8, 2], row=0, column=3, rowspan=2):
                    self.app.label("SE_Label_Volume", "Master Volume", sticky="NE", row=0, column=0, font=10)
                    self.app.scale("SE_Master_Volume", bg=colour.DARK_BLUE, fg=colour.WHITE,
                                   direction="vertical", show=True, interval=20,
                                   range=(100, 0), length=200, sticky="NEW", row=1, column=0, font=9).bind(
                        "<ButtonRelease-1>", self._set_master_volume, add='+')

                    self.app.label("SE_Label_Triangle_Volume", "Triangle Channel", sticky="NE",
                                   row=0, column=1, font=10)
                    self.app.scale("SE_Triangle_Volume", bg=colour.DARK_BLUE, fg=colour.WHITE,
                                   direction="vertical", show=True, interval=20,
                                   range=(100, 0), length=200, sticky="NEW", row=1, column=1, font=9).bind(
                        "<ButtonRelease-1>", self._set_triangle_volume, add='+')

            # Channels
            with self.app.frame("SE_Frame_Channels", padding=[4, 2], sticky="NEW", row=2, column=0):
                channel_names = ["Square 0", "Square 1", "Triangle", "Noise"]
                for c in range(4):
                    self.app.label(f"SE_Label_Channel_{c}", channel_names[c], sticky="SEW",
                                   row=0, column=c, font=10)
                    self.app.listBox(f"SE_List_Channel_{c}", None, multi=True, group=False, fixed_scrollbar=True,
                                     width=24, height=20, sticky="NEW", bg=colour.BLACK, fg=colour.MEDIUM_GREY,
                                     row=1, column=c, font=9).configure(font="TkFixedFont")
                    self.app.getListBoxWidget(f"SE_List_Channel_{c}").bind("<Key>", self._element_hotkey, add='+')

                    with self.app.frame(f"SE_Frame_Buttons_{c}", padding=[2, 1], sticky="NEW", row=2, column=c):
                        self.app.button(f"SE_Clear_Channel_{c}", self._track_input, image="res/clear_channel.gif",
                                        tooltip="Clear this channel",
                                        height=32, bg=colour.PALE_RED, sticky="NEW", row=0, column=0)
                        self.app.button(f"SE_Delete_Element_{c}", self._track_input, image="res/delete_element.gif",
                                        tooltip="Delete selected element(s)",
                                        height=32, bg=colour.PALE_RED, sticky="NEW", row=0, column=1)
                        self.app.button(f"SE_Insert_Above_{c}", self._track_input, image="res/insert_above.gif",
                                        tooltip="Create new element above selection",
                                        height=32, bg=colour.PALE_NAVY, sticky="NEW", row=0, column=2)
                        self.app.button(f"SE_Insert_Below_{c}", self._track_input, image="res/insert_below.gif",
                                        tooltip="Create new element below selection",
                                        height=32, bg=colour.PALE_NAVY, sticky="NEW", row=0, column=3)

        # Set the volume slider to the current amp factor
        self.app.setScale("SE_Master_Volume", int(self._sound_server.amp * 100), callFunction=False)
        self.app.setScale("SE_Triangle_Volume", int(self._triangle_volume * 100), callFunction=False)

        # Some operations are better done once the mouse button is released, rather than continuously while it's down
        self.app.getListBoxWidget(f"SE_List_Channel_0").bind("<ButtonRelease-1>",
                                                             lambda event: self._element_selection(event, 0), add='+')
        self.app.getListBoxWidget(f"SE_List_Channel_1").bind("<ButtonRelease-1>",
                                                             lambda event: self._element_selection(event, 1), add='+')
        self.app.getListBoxWidget(f"SE_List_Channel_2").bind("<ButtonRelease-1>",
                                                             lambda event: self._element_selection(event, 2), add='+')
        self.app.getListBoxWidget(f"SE_List_Channel_3").bind("<ButtonRelease-1>",
                                                             lambda event: self._element_selection(event, 3), add='+')
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

    def read_track_data(self, channel: int) -> List[TrackDataEntry]:
        track: List[TrackDataEntry] = []

        address = self._track_address[channel]

        loop_found = False

        while not loop_found:
            control_byte = self.rom.read_byte(self._bank, address)
            address = address + 1

            if control_byte == 0xFB:  # FB - VOLUME
                value = self.rom.read_byte(self._bank, address)
                address += 1
                data = TrackDataEntry.new_volume(value)
                data.raw = bytearray([0xFB, value])

            elif control_byte == 0xFC:  # FC - INSTRUMENT
                value = self.rom.read_byte(self._bank, address)
                address += 1
                data = TrackDataEntry.new_instrument(value)
                data.raw = bytearray([0xFC, value])

            elif control_byte == 0xFD:  # FD - VIBRATO
                triangle_octave = self.rom.read_byte(self._bank, address)
                address += 1

                speed = self.rom.read_byte(self._bank, address)
                address += 1

                factor = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackDataEntry.new_vibrato(triangle_octave < 0xFF, speed, factor)
                data.raw = bytearray([0xFD, triangle_octave, speed, factor])

            elif control_byte == 0xFE:  # FE - REST
                value = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackDataEntry.new_rest(value)
                data.raw = bytearray([0xFE, value])

            elif control_byte == 0xFF:  # FF - REWIND
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
                data = TrackDataEntry.new_rewind(0)  # Use 0 for now
                data.raw = bytearray([0xFF, 0])
                data.raw += offset.to_bytes(2, "little", signed=True)
                loop_found = True

            elif control_byte >= 0xF0:  # F0-FA - IGNORED
                value = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackDataEntry(control=value)
                data.raw = bytearray([value])

            else:  # 00-EF - NOTE
                index = control_byte

                duration = self.rom.read_byte(self._bank, address)
                address += 1

                if index > len(_notes):
                    self.warning(f"Invalid note: ${control_byte:02X} for channel {channel} at " +
                                 f"${self._bank:02X}:{address - 2:04X}")
                    data = TrackDataEntry.new_note(0, 0)
                else:
                    data = TrackDataEntry.new_note(index, duration)

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

    def _update_element_info(self, channel: int, element: int) -> None:
        widget = f"SE_List_Channel_{channel}"

        t = self._track_data[channel][element]

        text = f"{element:03X} - {t.raw[0]:02X} - "

        if t.control == TrackDataEntry.CHANNEL_VOLUME:
            text += f"{t.raw[1]:02X} - -- - --"
            description = f"VOL {t.channel_volume:02}"
            bg = colour.DARK_BLUE
            fg = colour.LIGHT_ORANGE

        elif t.control == TrackDataEntry.SELECT_INSTRUMENT:
            text += f"{t.raw[1]:02X} - -- - --\n"
            description = f"INS {self._instruments[t.instrument_index].name[:19]}"
            bg = colour.DARK_ORANGE
            fg = colour.PALE_TEAL

        elif t.control == TrackDataEntry.SET_VIBRATO:
            text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
            description = f"VIB {'T^, ' if t.triangle_octave else ''} S:{t.vibrato_speed}, F:{t.vibrato_factor}"
            bg = colour.DARK_VIOLET
            fg = colour.PALE_PINK

        elif t.control == TrackDataEntry.REST:
            text += f"{t.raw[1]:02X} - -- - --"
            description = f"REST {t.rest_duration}"
            bg = colour.DARK_OLIVE
            fg = colour.PALE_MAGENTA

        elif t.control == TrackDataEntry.REWIND:
            text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
            description = f"RWD {t.loop_position}"
            bg = colour.DARK_MAGENTA
            fg = colour.PALE_VIOLET

        elif t.control == TrackDataEntry.PLAY_NOTE:
            text += f"{t.raw[1]:02X} - -- - --"
            description = f"       {_NOTE_NAMES[t.raw[0]]} {t.raw[1]:02}"
            bg = "#171717"
            fg = colour.PALE_GREEN

        else:
            text += f"-- - -- - --"
            description = f"IGNORED"
            bg = colour.DARK_RED
            fg = colour.PALE_RED

        i = element << 1
        self.app.setListItemAtPos(widget, i, text)
        self.app.setListItemAtPos(widget, i + 1, description)
        self.app.setListItemAtPosBg(widget, i + 1, bg)
        self.app.setListItemAtPosFg(widget, i + 1, fg)

    # ------------------------------------------------------------------------------------------------------------------

    def track_info(self, channel: int) -> None:
        # Show address first
        self.app.clearEntry(f"SE_Channel_Address_{channel}", callFunction=False, setFocus=False)
        self.app.setEntry(f"SE_Channel_Address_{channel}", f"0x{self._track_address[channel]:04X}", callFunction=False)

        # Show elements list
        widget = f"SE_List_Channel_{channel}"

        self.app.clearListBox(widget, callFunction=False)

        # There are 2 list items per each 1 element, so we keep count separately and avoid too many calculations
        # in order to have a faster refresh
        i = 0  # List item index
        e = 0  # Element index

        for t in self._track_data[channel]:
            text = f"{e:03X} - {t.raw[0]:02X} - "

            if t.control == TrackDataEntry.CHANNEL_VOLUME:
                text += f"{t.raw[1]:02X} - -- - --"
                description = f"VOL {t.channel_volume:02}"
                bg = colour.DARK_BLUE
                fg = colour.LIGHT_ORANGE

            elif t.control == TrackDataEntry.SELECT_INSTRUMENT:
                text += f"{t.raw[1]:02X} - -- - --\n"
                description = f"INS {self._instruments[t.instrument_index].name[:19]}"
                bg = colour.DARK_ORANGE
                fg = colour.PALE_TEAL

            elif t.control == TrackDataEntry.SET_VIBRATO:
                text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
                description = f"VIB {'T^, ' if t.triangle_octave else ''} S:{t.vibrato_speed}, F:{t.vibrato_factor}"
                bg = colour.DARK_VIOLET
                fg = colour.PALE_PINK

            elif t.control == TrackDataEntry.REST:
                text += f"{t.raw[1]:02X} - -- - --"
                description = f"REST {t.rest_duration}"
                bg = colour.DARK_OLIVE
                fg = colour.PALE_MAGENTA

            elif t.control == TrackDataEntry.REWIND:
                text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
                description = f"RWD {t.loop_position}"
                bg = colour.DARK_MAGENTA
                fg = colour.PALE_VIOLET

            elif t.control == TrackDataEntry.PLAY_NOTE:
                text += f"{t.raw[1]:02X} - -- - --"
                description = f"       {_NOTE_NAMES[t.raw[0]]} {t.raw[1]:02}"
                bg = "#171717"
                fg = colour.PALE_GREEN

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
            e += 1

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

    def _track_entry_delete(self, channel: int, entry: int) -> None:
        self._track_data[channel].pop(entry)

    # ------------------------------------------------------------------------------------------------------------------

    def _get_selected_element(self) -> Tuple[TrackDataEntry, int]:
        """

        Returns
        -------
        (int, TrackDataEntry, int)
            A tuple: index of the  currently selected element, corresponding TrackDataEntry instance, position
            in the list box.
            An invalid selection returns -1 index and position
        """
        if self._selected_element < 0:
            return TrackDataEntry(), -1

        element = self._track_data[self._selected_channel][self._selected_element]

        return element, self._selected_element << 1

    # ------------------------------------------------------------------------------------------------------------------

    def _element_input(self, widget: str) -> None:
        if widget == "SE_Apply_Note" or widget == "SE_Note_Value" or widget == "SE_Note_Duration":
            # Get selected element
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.PLAY_NOTE:
                return

            try:
                name = self.app.getEntry("SE_Note_Value").upper()
                if len(name) < 3:
                    name += ' '
                value = _NOTE_NAMES.index(name)
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Note_Value").selection_range(0, tkinter.END)
                return

            try:
                duration = int(self.app.getEntry("SE_Note_Duration"), 10)
                if duration < 1 or duration > 255:
                    self.app.soundError()
                    self.app.getEntryWidget("SE_Note_Duration").selection_range(0, tkinter.END)
                    self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection,
                                                 callFunction=False)
                    return
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Note_Duration").selection_range(0, tkinter.END)
                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)
                return

            element.set_note(value, duration)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

        elif widget == "SE_Apply_Volume" or widget == "SE_Entry_Volume":
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.CHANNEL_VOLUME:
                return

            try:
                value = int(self.app.getEntry("SE_Entry_Volume"), 10)

                if value < 0 or value > 15:
                    self.app.soundError()
                    self.app.getEntryWidget("SE_Entry_Volume").selection_range(0, tkinter.END)
                    self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection,
                                                 callFunction=False)
                    return
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Entry_Volume").selection_range(0, tkinter.END)
                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)
                return

            element.set_volume(value)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

        elif widget == "SE_Select_Instrument":
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.SELECT_INSTRUMENT:
                return

            value = self.app.getListBoxPos(widget)
            if len(value) > 0:
                element.set_instrument(value[0])
                # Update just this entry
                self._update_element_info(self._selected_channel, self._selected_element)
                # Re-select it
                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

        elif widget == "SE_Apply_Rest" or widget == "SE_Rest_Duration":
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.REST:
                return

            try:
                value = int(self.app.getEntry("SE_Rest_Duration"), 10)
                if value < 0 or value > 255:
                    self.app.soundError()
                    self.app.getEntryWidget("SE_Rest_Duration").selection_range(0, tkinter.END)
                    self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection,
                                                 callFunction=False)
                    return
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Rest_Duration").selection_range(0, tkinter.END)
                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)
                return

            element.set_rest(value)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

        elif widget == "SE_Apply_Vibrato" or widget == "SE_Vibrato_Speed" or widget == "SE_Vibrato_Factor":
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.SET_VIBRATO:
                return

            try:
                speed = int(self.app.getEntry("SE_Vibrato_Speed"), 10)
                if speed < 0 or speed > 255:
                    self.app.soundError()
                    self.app.getEntryWidget("SE_Vibrato_Speed").selection_range(0, tkinter.END)
                    self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection,
                                                 callFunction=False)
                    return
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Vibrato_Speed").selection_range(0, tkinter.END)
                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)
                return

            try:
                factor = int(self.app.getEntry("SE_Vibrato_Factor"), 10)
                if factor < 0 or speed > 255:
                    self.app.soundError()
                    self.app.getEntryWidget("SE_Vibrato_Factor").selection_range(0, tkinter.END)
                    self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection,
                                                 callFunction=False)
                    return
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Vibrato_Factor").selection_range(0, tkinter.END)
                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)
                return

            octave = self.app.getCheckBox("SE_Triangle_Octave")

            element.set_vibrato(octave, speed, factor)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

        elif widget == "SE_Triangle_Octave":
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.SET_VIBRATO:
                return

            octave = self.app.getCheckBox("SE_Triangle_Octave")
            speed = element.vibrato_speed
            factor = element.vibrato_factor
            element.set_vibrato(octave, speed, factor)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

        else:
            self.info(f"Unimplemented callback for Element widget: '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _element_selection(self, _event: any, channel: int) -> None:
        """
        Callback on left mouse button release on a channel's list
        """
        self._selected_channel = channel
        selection = self.app.getListBoxPos(f"SE_List_Channel_{self._selected_channel}")

        if len(selection) < 1:      # Nothing selected
            self.app.firstFrame("SE_Stack_Editing", callFunction=False)
            self.app.setLabel("SE_Selection_Info_Channel", "Channel: (no selection)")
            self.app.setLabel("SE_Selection_Info_Element", "Element: (no selection)")
        elif len(selection) > 1:    # Multiple selection
            self.app.lastFrame("SE_Stack_Editing", callFunction=False)
            self.app.setLabel("SE_Selection_Info_Channel", f"Channel: {self._selected_channel}")
            # This will point to the first element selected
            self._selected_element = selection[0] >> 1
        else:
            # Get the index of the selected element, keeping in mind that each occupies two lines
            element = self._track_data[channel][selection[0] >> 1]
            self._selected_element = selection[0] >> 1

            self.app.setLabel("SE_Selection_Info_Channel", f"Channel: {self._selected_channel}")
            self.app.setLabel("SE_Selection_Info_Element", f"Element: {self._selected_element:03X}")

            # Get the type of this element and choose an appropriate frame
            if element.control == TrackDataEntry.PLAY_NOTE:
                self.app.selectFrame("SE_Stack_Editing", 2, callFunction=False)

                self.app.clearEntry("SE_Note_Value", callFunction=False, setFocus=True)
                self.app.clearEntry("SE_Note_Duration", callFunction=False, setFocus=False)

                self.app.setEntry("SE_Note_Value", _NOTE_NAMES[element.note_value.index], callFunction=False)
                self.app.setEntry("SE_Note_Duration", f"{element.note_value.duration}", callFunction=False)

                self.app.getEntryWidget("SE_Note_Value").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            elif element.control == TrackDataEntry.CHANNEL_VOLUME:
                self.app.selectFrame("SE_Stack_Editing", 1, callFunction=False)

                self.app.clearEntry("SE_Entry_Volume", callFunction=False, setFocus=True)
                self.app.setEntry("SE_Entry_Volume", element.channel_volume, callFunction=False)
                self.app.getEntryWidget("SE_Entry_Volume").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            elif element.control == TrackDataEntry.REST:
                self.app.selectFrame("SE_Stack_Editing", 3, callFunction=False)

                self.app.clearEntry("SE_Rest_Duration", callFunction=False, setFocus=True)
                self.app.setEntry("SE_Rest_Duration", element.rest_duration, callFunction=False)
                self.app.getEntryWidget("SE_Rest_Duration").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            elif element.control == TrackDataEntry.SET_VIBRATO:
                self.app.selectFrame("SE_Stack_Editing", 4, callFunction=False)

                self.app.setCheckBox("SE_Triangle_Octave", element.triangle_octave, callFunction=False)

                self.app.clearEntry("SE_Vibrato_Speed", callFunction=False, setFocus=True)
                self.app.clearEntry("SE_Vibrato_Factor", callFunction=False, setFocus=False)

                self.app.setEntry("SE_Vibrato_Speed", element.vibrato_speed, callFunction=False)
                self.app.setEntry("SE_Vibrato_Factor", element.vibrato_factor, callFunction=False)

                self.app.getEntryWidget("SE_Vibrato_Speed").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            elif element.control == TrackDataEntry.SELECT_INSTRUMENT:
                self.app.selectFrame("SE_Stack_Editing", 5, callFunction=False)
                self.app.selectListItemAtPos("SE_Select_Instrument", element.instrument_index, callFunction=False)

            elif element.control == TrackDataEntry.REWIND:
                self.app.selectFrame("SE_Stack_Editing", 6, callFunction=False)

                self.app.clearEntry("SE_Rewind_Value", callFunction=False, setFocus=True)
                self.app.setEntry("SE_Rewind_Value", element.loop_position, callFunction=False)
                self.app.getEntryWidget("SE_Rewind_Value").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            else:
                self.app.firstFrame("SE_Stack_Editing", callFunction=False)

    # ------------------------------------------------------------------------------------------------------------------

    def _element_hotkey(self, event: any) -> None:
        # Get selection
        selection = self.app.getListBoxPos(f"SE_List_Channel_{self._selected_channel}")

        # Since we have two entries per element, we need to divide each item index by two
        for e in range(len(selection)):
            selection[e] = selection[e] // 2

        # Then we need to remove any duplicates
        selection = list(dict.fromkeys(selection))

        # Reverse the selection: it's safer to process items down in the list first
        selection.sort(reverse=True)

        # Single- and multi- selection keys
        if event.keycode == 0x2E or event.keycode == 0x08:  # Delete
            for entry in selection:
                self._track_entry_delete(self._selected_channel, entry)
            self.track_info(self._selected_channel)

            return

        if len(selection) > 1:
            # Multiple-selection-only keys
            return

        else:
            # Single-selection-only keys
            return

    # ------------------------------------------------------------------------------------------------------------------

    def _track_input(self, widget: str) -> None:
        if widget == "SE_Button_Cancel":
            self.close_track_editor()

        elif widget == "SE_Play_Stop":
            if self._play_thread.is_alive():
                self.stop_playback()
                self.app.enableScale("SE_Triangle_Volume")
                self.app.setButtonImage(widget, "res/play.gif")

                self.app.setListBoxMulti(f"SE_List_Channel_0", multi=True)
                self.app.setListBoxMulti(f"SE_List_Channel_1", multi=True)
                self.app.setListBoxMulti(f"SE_List_Channel_2", multi=True)
                self.app.setListBoxMulti(f"SE_List_Channel_3", multi=True)
                self.app.setListBoxGroup(f"SE_List_Channel_0", group=False)
                self.app.setListBoxGroup(f"SE_List_Channel_1", group=False)
                self.app.setListBoxGroup(f"SE_List_Channel_2", group=False)
                self.app.setListBoxGroup(f"SE_List_Channel_3", group=False)

            else:
                # Leaving multiple selection active during playback messes up the interface
                self.app.setListBoxMulti(f"SE_List_Channel_0", multi=False)
                self.app.setListBoxMulti(f"SE_List_Channel_1", multi=False)
                self.app.setListBoxMulti(f"SE_List_Channel_2", multi=False)
                self.app.setListBoxMulti(f"SE_List_Channel_3", multi=False)
                self.app.setListBoxGroup(f"SE_List_Channel_0", group=True)
                self.app.setListBoxGroup(f"SE_List_Channel_1", group=True)
                self.app.setListBoxGroup(f"SE_List_Channel_2", group=True)
                self.app.setListBoxGroup(f"SE_List_Channel_3", group=True)

                self.app.disableScale("SE_Triangle_Volume")
                self.start_playback(True)
                self.app.setButtonImage(widget, "res/stop.gif")

        elif widget[:17] == "SE_Clear_Channel_":
            # Don't do this during playback
            if self._playing:
                self.app.soundError()
                return

            channel = int(widget[-1])
            channel_name = ["Square 0", "Square 1", "Triangle", "Noise"]

            # Confirm first
            if not self.app.yesNoBox("Clear Channel", f"Are you sure you want to clear the {channel_name[channel]} " +
                                                      "channel?\nThis operation cannot be undone, except reloading " +
                                                      "the whole channel from ROM (use the button next to the " +
                                                      "address value in the upper-left frame).",
                                                      "Track_Editor"):
                return

            # Clear channel by creating a new one with minimal elements
            self._track_data[channel] = []
            self._track_data[channel].append(TrackDataEntry.new_instrument(0))
            self._track_data[channel].append(TrackDataEntry.new_volume(0))
            self._track_data[channel].append(TrackDataEntry.new_rest(7))
            self._track_data[channel].append(TrackDataEntry.new_rewind(0))

            # Update list
            self.track_info(channel)
            self.app.selectListItemAtPos(f"SE_List_Channel_{channel}", 0, callFunction=True)

        else:
            self.info(f"Unimplemented callback for Track widget '{widget}'.")

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
            src = int(widget[-1], 10)  # Index of source envelope
            dst = (src - 1) % 3  # Index of destination envelope

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
                self._track_data[0].append(TrackDataEntry.new_volume(15))
                self._track_data[0].append(TrackDataEntry.new_instrument(self._selected_instrument))
                if self._test_octave == 2:
                    base_note = 0x0C
                elif self._test_octave == 1:
                    base_note = 0x18
                else:
                    base_note = 0x24

                if self._test_notes == 0:       # Single note loop
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 7, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 7, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 7, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 7, note_length))
                elif self._test_notes == 1:     # Scale
                    self._track_data[0].append(TrackDataEntry.new_note(base_note, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 2, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 4, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 5, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 7, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 9, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 11, note_length))
                else:                           # Arpeggio
                    self._track_data[0].append(TrackDataEntry.new_note(base_note, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 4, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 7, note_length))
                    self._track_data[0].append(TrackDataEntry.new_note(base_note + 4, note_length))
                self._track_data[0].append(TrackDataEntry.new_rewind(2))
                # "Mute" other channels
                self._track_data[1] = []
                self._track_data[1].append(TrackDataEntry.new_volume(0))
                self._track_data[1].append(TrackDataEntry.new_rest(note_length))
                self._track_data[1].append(TrackDataEntry.new_rewind(0))
                self._track_data[2] = []
                self._track_data[2].append(TrackDataEntry.new_volume(0))
                self._track_data[2].append(TrackDataEntry.new_rest(note_length))
                self._track_data[2].append(TrackDataEntry.new_rewind(0))
                self._track_data[3] = []
                self._track_data[3].append(TrackDataEntry.new_volume(0))
                self._track_data[3].append(TrackDataEntry.new_rest(note_length))
                self._track_data[3].append(TrackDataEntry.new_rewind(0))

                self.start_playback(False)
                self.app.setButtonImage(widget, "res/stop.gif")

        else:
            self.info(f"Unimplemented callback for Instrument widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _set_master_volume(self, _event: any = None) -> None:
        """
        Callback for left mouse button release on master volume widget.
        """
        value = self.app.getScale("SE_Master_Volume") / 100
        self._sound_server.setAmp(value)

    # ------------------------------------------------------------------------------------------------------------------

    def _set_triangle_volume(self, _event: any = None) -> None:
        """
        Callback for left mouse button release on triangle channel volume widget.
        """
        self._triangle_volume = self.app.getScale("SE_Triangle_Volume") / 100

    # ------------------------------------------------------------------------------------------------------------------

    def _draw_full_graph(self, _event: any = None) -> None:
        # Ignore the event parameter, it's there just so we can use this as a callback for Tkinter widgets

        width = self._canvas_graph.winfo_reqwidth()

        base_height = self._canvas_graph.winfo_reqheight() - 10

        vertical_step = base_height >> 3

        instrument = self._instruments[self._selected_instrument]

        line_width = 2

        # Calculate the number of items that we want to draw (one per each entry in each envelope)
        count = instrument.envelope[0][0] + instrument.envelope[1][0] + instrument.envelope[2][0]

        # Calculate the width of each segment in our line
        length = width // count
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

        e = 0  # Envelope index
        i = 1  # Item index

        x = 0  # Start from the left of the canvas

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
        length = canvas_width // envelope[0]
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
        width = canvas.winfo_reqwidth() // envelope[0]
        if width < 4:
            width = 4

        canvas_height = canvas.winfo_reqheight()
        v_ratio = (canvas_height // 8) - 4
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

    def get_data_size(self, bank: int, address: int) -> int:
        """
        Reads music data to calculate its size.

        Parameters
        ----------
        address: int
            The address where to start reading

        bank: int
            The bank where the channel data is found

        Returns
        -------
        int
            The size, in bytes, of this track's data
        """
        size = 0

        if bank == 8:
            # Tuple: start address, end address
            memory_blocks = [(0x87C7, 0x8DBE),
                             (0x8639, 0x8642),
                             (0x8EAA, 0x92C7),
                             (0x9342, 0x974F),
                             (0x9833, 0x9DBD),
                             (0x9EAB, 0xA2B6),
                             (0xA35E, 0xA5DD),
                             (0xA74B, 0xAA00),
                             (0xAA52, 0xAD21),
                             (0xADC1, 0xB468),
                             (0xB4FA, 0xB985),
                             (0xB968, 0xBF9F),
                             (0xBFD0, 0xBFEF)]
        elif bank == 9:
            # TODO Implement bank 9
            return 0
        else:
            self.error(f"get_data_size: Unsupported bank {bank}.")
            return 0

        # Try to detect which memory block we are in
        block = -1
        for b in range(len(memory_blocks)):
            if memory_blocks[b][0] <= address < memory_blocks[b][1]:
                block = b
                break

        if block < 0:
            self.error(f"Music data at ${bank:02X}:{address:04X} is outside of allocated memory area!")
            return 0

        # TODO Define better memory boundaries to avoid reading over code/unrelated data
        while address < memory_blocks[block][1]:
            control_byte = self.rom.read_byte(bank, address)

            if control_byte == 0xFB or control_byte == 0xFC or control_byte == 0xFE:
                size += 2
                address += 2

            elif control_byte == 0xFD:
                size += 4
                address += 4

            elif control_byte == 0xFF:
                size += 4
                break

            elif control_byte < 0xF0:
                size += 2
                address += 2

            else:
                size += 1
                address += 1

        return size

    # ------------------------------------------------------------------------------------------------------------------

    def _read_famistudio_text(self, file_name: str) -> List[List[TrackDataEntry]]:
        track_data: List[List[TrackDataEntry]] = [[], [], [], []]
        buffer: List[str] = []

        try:
            fd = open(file_name, "r")

            # TODO Buffer everything
            buffer = fd.readlines()

            fd.close()
        except IOError:
            self.app.errorBox("Track Editor", f"Could not open file: '{file_name}'.")

        if len(buffer) < 1:
            self.app.errorBox("Track Editor", f"Invalid FamiStudio text file: '{file_name}'.")
            return track_data

        # Read the first object, it must be "Project"
        line = buffer.pop(0)
        if line.split(' ')[0] != "Project":
            self.app.errorBox("Track Editor", f"Invalid FamiStudio text file: '{file_name}'.")
            return track_data

        for line in buffer:
            # TODO Process lines
            pass

        return track_data

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
                    self.app.selectListItemAtPos(widgets[c], (last_played[c] << 1) - 1, callFunction=False)

            interval = frame_interval - (time.time() - start_time)
            if interval > 0:
                time.sleep(interval)

    # ------------------------------------------------------------------------------------------------------------------

    def _play_loop(self) -> None:
        if self._sound_server.getIsBooted() < 1:
            self._sound_server.boot()
            # Give the sound server some time to boot
            time.sleep(0.5)
            if not self._sound_server.getIsBooted():
                time.sleep(1.5)

        if self._sound_server.getIsStarted():
            # Already playing
            return

        self._sound_server.amp = 0.50
        self._sound_server.start()

        # Approximate NTSC timing
        frame_interval = 0.0166  # 1 / 60

        # Pre-build square wave tables
        flat_table: List[Tuple[int, float]] = [(x, 0.0) for x in range(16)]

        # 12.5% duty
        table_d0 = flat_table.copy()

        # 25% duty / 75%
        table_d1 = table_d0.copy()
        table_d1[2] = (2, 1)
        table_d1[9] = (10, 1)

        # 50% duty
        table_d2 = table_d1.copy()
        table_d2[3] = (3, 1)
        table_d2[4] = (4, 1)
        table_d2[10] = (11, 1)
        table_d2[11] = (12, 1)

        # Vibrato stuff
        vibrato_factor: List[int] = [0, 0, 0, 0]
        vibrato_counter: List[int] = [0, 0, 0, 0]
        vibrato_increment: List[int] = [0, 0, 0, 0]
        vibrato_table: List[List[int]] = [[0] * 8, [0] * 8, [0] * 8, [0] * 8]

        # Pre-calculated volume levels table (volume can be 0-15)
        volume_tables: List[List[float]] = [[0, 0, 0, 0, 0, 0, 0, 0, 0],  # 0: Muted
                                            [0.0] + [round(x / 82, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 80, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 78, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 74, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 72, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 70, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 68, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 64, 3) for x in range(1, 9)],  # 8: Half volume
                                            [0.0] + [round(x / 62, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 60, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 58, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 56, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 54, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 52, 3) for x in range(1, 9)],
                                            [0.0] + [round(x / 50, 3) for x in range(1, 9)]]  # 15: Max volume

        # All channels start muted
        channel_volume = [volume_tables[0], volume_tables[0], volume_tables[0], volume_tables[0]]

        wave_table = [pyo.LinTable(flat_table, size=32),  # Square wave 0
                      pyo.LinTable(flat_table, size=32),  # Square wave 1
                      pyo.TriangleTable(order=1, size=32).mul(self._triangle_volume),  # Triangle wave, more or less...
                      pyo.LinTable(flat_table, size=32)]  # Noise wave
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

        self._track_counter = [1, 1, 1, 1]  # Count down from here
        self._track_position = [0, 0, 0, 0]  # Start from the first item in the track

        self._slow_event.clear()

        # Triangle channel's notes will go up one octave when this is True
        # Instead of changing the note index, like in the game, we will halve the frequency when not set
        triangle_octave = False

        c = 0  # Currently playing channel

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

                # Interpret this data

                # Notes are the most common
                if track_data.control == TrackDataEntry.PLAY_NOTE:
                    self._track_counter[c] = track_data.note_value.duration  # This will end this loop

                    # Frequency
                    # Note that in the game's music driver vibrato affects the period written to the registers, which in
                    # turn will affect the frequency. A higher period means a lower frequency.
                    # Here we are dealing directly with frequencies, so for the sake of speed we will use
                    # an approximation of that effect.
                    # Also note that a lower factor means "more vibrato".
                    if vibrato_factor[c] > 1:
                        divided = (track_data.note_value.frequency // vibrato_factor[c]) >> 4
                        vibrato_table[c][0], vibrato_table[c][4] = \
                            track_data.note_value.frequency, track_data.note_value.frequency

                        vibrato_table[c][1] = track_data.note_value.frequency - divided
                        vibrato_table[c][3] = vibrato_table[c][1]
                        vibrato_table[c][2] = vibrato_table[c][3] - divided

                        vibrato_table[c][5] = vibrato_table[c][4] + divided
                        vibrato_table[c][7] = vibrato_table[c][5]
                        vibrato_table[c][6] = vibrato_table[c][5] + divided

                        # Don't set the frequency here, do it during playback using the vibrato table
                    else:
                        channel_oscillator[c].setFreq(track_data.note_value.frequency)

                    # Instrument
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
                elif track_data.control == TrackDataEntry.REST:
                    self._track_counter[c] = track_data.rest_duration
                    # Use flat wave to generate the "silence" rather than lowering the volume
                    # wave_table[c].replace(table_flat)
                    vibrato_table[c] = [0, 0, 0, 0, 0, 0, 0, 0]
                    channel_oscillator[c].setFreq(0)

                elif track_data.control == TrackDataEntry.SELECT_INSTRUMENT:
                    channel_instrument[c] = track_data.instrument_index
                    # Counter is now 0

                elif track_data.control == TrackDataEntry.SET_VIBRATO:
                    vibrato_factor[c] = track_data.vibrato_factor
                    # Use vibrato_speed to set the counters
                    if track_data.vibrato_speed < 2:
                        # Disable vibrato
                        vibrato_counter[c] = 0
                        vibrato_increment[c] = 0
                    else:
                        # Enable vibrato
                        vibrato_increment[c] = 0x800 // track_data.vibrato_speed
                        vibrato_counter[c] = 0x200

                elif track_data.control == TrackDataEntry.CHANNEL_VOLUME:
                    channel_volume[c] = volume_tables[track_data.channel_volume]
                    # Note that counter will be 0 now, so we will read another segment

                elif track_data.control == TrackDataEntry.REWIND:
                    self._track_position[c] = track_data.loop_position - 1
                    # Counter should now be 0

                # Ignore anything else ($3C-$FA control bytes)
                self._track_position[c] += 1

            # Generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note
                if vibrato_factor[c] > 1:
                    # Use vibrato table and counters
                    vibrato_counter[c] += vibrato_increment[c]
                    channel_oscillator[c].setFreq(vibrato_table[c][vibrato_counter[c] & 0x0007])

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
                    table_d0[9] = (9, volume)
                    wave_table[c].replace(table_d0)
                elif duty == 2:  # 50% duty
                    table_d2[1] = (1, volume)
                    table_d2[2] = (2, volume)
                    table_d2[3] = (3, volume)
                    table_d2[4] = (4, volume)
                    table_d2[9] = (9, volume)
                    table_d2[10] = (10, volume)
                    table_d2[11] = (11, volume)
                    table_d2[12] = (12, volume)
                    wave_table[c].replace(table_d2)
                else:  # 25% / 75% duty
                    table_d1[1] = (1, volume)
                    table_d1[2] = (2, volume)
                    table_d1[9] = (9, volume)
                    table_d1[10] = (10, volume)
                    wave_table[c].replace(table_d1)

            # --- SQUARE WAVE 1 ---
            c = 1

            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = self._track_data[c][self._track_position[c]]

                if track_data.control == TrackDataEntry.PLAY_NOTE:
                    self._track_counter[c] = track_data.note_value.duration  # This will end this loop

                    # Frequency
                    if vibrato_factor[c] > 1:
                        divided = (track_data.note_value.frequency // vibrato_factor[c]) >> 4
                        vibrato_table[c][0], vibrato_table[c][4] = \
                            track_data.note_value.frequency, track_data.note_value.frequency

                        vibrato_table[c][1] = track_data.note_value.frequency - divided
                        vibrato_table[c][3] = vibrato_table[c][1]
                        vibrato_table[c][2] = vibrato_table[c][3] - divided

                        vibrato_table[c][5] = vibrato_table[c][4] + divided
                        vibrato_table[c][7] = vibrato_table[c][5]
                        vibrato_table[c][6] = vibrato_table[c][5] + divided

                        # Don't set the frequency here, do it during playback using the vibrato table
                    else:
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

                elif track_data.control == TrackDataEntry.REST:
                    self._track_counter[c] = track_data.rest_duration
                    # Use flat wave to generate the "silence" rather than lowering the volume
                    vibrato_table[c] = [0, 0, 0, 0, 0, 0, 0, 0]
                    channel_oscillator[c].setFreq(0)

                elif track_data.control == TrackDataEntry.SELECT_INSTRUMENT:
                    channel_instrument[c] = track_data.instrument_index

                elif track_data.control == TrackDataEntry.SET_VIBRATO:
                    vibrato_factor[c] = track_data.vibrato_factor
                    # Use vibrato_speed to set the counters
                    if track_data.vibrato_speed < 2:
                        # Disable vibrato
                        vibrato_counter[c] = 0
                        vibrato_increment[c] = 0
                    else:
                        # Enable vibrato
                        vibrato_increment[c] = 0x800 // track_data.vibrato_speed
                        vibrato_counter[c] = 0x200

                elif track_data.control == TrackDataEntry.CHANNEL_VOLUME:
                    channel_volume[c] = volume_tables[track_data.channel_volume]
                    # Note that counter will be 0 now, so we will read another segment

                elif track_data.control == TrackDataEntry.REWIND:
                    self._track_position[c] = track_data.loop_position - 1

                # Ignore anything else ($3C-$FA control bytes)
                self._track_position[c] += 1

            # Generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note
                if vibrato_factor[c] > 1:
                    # Use vibrato table and counters
                    vibrato_counter[c] += vibrato_increment[c]
                    channel_oscillator[c].setFreq(vibrato_table[c][vibrato_counter[c] & 0x0007])

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
                    table_d0[9] = (9, volume)
                    wave_table[c].replace(table_d0)
                elif duty == 2:  # 50% duty
                    table_d2[1] = (1, volume)
                    table_d2[2] = (2, volume)
                    table_d2[3] = (3, volume)
                    table_d2[4] = (4, volume)
                    table_d2[9] = (9, volume)
                    table_d2[10] = (10, volume)
                    table_d2[11] = (11, volume)
                    table_d2[12] = (12, volume)
                    wave_table[c].replace(table_d2)
                else:  # 25% and 75% duty
                    table_d1[1] = (1, volume)
                    table_d1[2] = (2, volume)
                    table_d1[9] = (9, volume)
                    table_d1[10] = (10, volume)
                    wave_table[c].replace(table_d1)

            # --- TRIANGLE WAVE ---
            c = 2

            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = self._track_data[c][self._track_position[c]]

                if track_data.control == TrackDataEntry.PLAY_NOTE:
                    self._track_counter[c] = track_data.note_value.duration  # This will end this loop

                    # Frequency
                    if vibrato_factor[c] > 1:  # Vibrato enabled
                        divided = (track_data.note_value.frequency // vibrato_factor[c]) >> 4
                        vibrato_table[c][0], vibrato_table[c][4] = \
                            track_data.note_value.frequency, track_data.note_value.frequency

                        vibrato_table[c][0] = \
                            track_data.note_value.frequency >> 1 if triangle_octave is True \
                            else track_data.note_value.frequency

                        vibrato_table[c][1] = track_data.note_value.frequency - divided
                        vibrato_table[c][3] = vibrato_table[c][1]
                        vibrato_table[c][2] = vibrato_table[c][3] - divided

                        vibrato_table[c][4] = vibrato_table[c][0]
                        vibrato_table[c][5] = vibrato_table[c][4] + divided
                        vibrato_table[c][7] = vibrato_table[c][5]
                        vibrato_table[c][6] = vibrato_table[c][5] + divided

                        # In this case we don't set the frequency here: we do it during playback using the vibrato table

                    else:  # Vibrato disabled
                        if triangle_octave is True:
                            channel_oscillator[c].setFreq(track_data.note_value.frequency)
                        else:
                            channel_oscillator[c].setFreq(track_data.note_value.frequency >> 1)

                    # This channel does not use instruments / envelopes, because it does not have volume / duty

                elif track_data.control == TrackDataEntry.REST:
                    self._track_counter[c] = track_data.rest_duration
                    # Use flat wave to generate the "silence" rather than lowering the volume
                    vibrato_table[c] = [0, 0, 0, 0, 0, 0, 0, 0]
                    channel_oscillator[c].setFreq(0)

                elif track_data.control == TrackDataEntry.SELECT_INSTRUMENT:
                    channel_instrument[c] = track_data.instrument_index

                elif track_data.control == TrackDataEntry.SET_VIBRATO:
                    # Change triangle channel octave offset
                    if track_data.raw[1] == 0xFF:
                        triangle_octave = True
                    else:
                        triangle_octave = False

                    vibrato_factor[c] = track_data.vibrato_factor
                    # Use vibrato_speed to set the counters
                    if track_data.vibrato_speed < 2:
                        # Disable vibrato
                        vibrato_counter[c] = 0
                        vibrato_increment[c] = 0
                    else:
                        # Enable vibrato
                        vibrato_increment[c] = 0x800 // track_data.vibrato_speed
                        vibrato_counter[c] = 0x200

                elif track_data.control == TrackDataEntry.CHANNEL_VOLUME:
                    if track_data.channel_volume == 15:
                        wave_table[c].setOrder(1)
                        wave_table[c].mul(self._triangle_volume)
                    else:
                        wave_table[c].setOrder(0)
                    # Note that counter will be 0 now, so we will read another segment

                elif track_data.control == TrackDataEntry.REWIND:
                    self._track_position[c] = track_data.loop_position - 1

                # Ignore anything else ($3C-$FA control bytes)
                self._track_position[c] += 1

            # Generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note
                if vibrato_factor[c] > 1:
                    # Use vibrato table and counters
                    vibrato_counter[c] += vibrato_increment[c]
                    channel_oscillator[c].setFreq(vibrato_table[c][vibrato_counter[c] & 0x0007])
            else:
                channel_oscillator[c].setFreq(0)

            # --- End of channel data ---

            # TODO --- NOISE CHANNEL ---

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
