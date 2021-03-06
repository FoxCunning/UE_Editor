__author__ = "Fox Cunning"

import configparser
import os
import threading
import time
import tkinter
import re

import pyo

from dataclasses import dataclass, field
from tkinter import Canvas
from typing import List, Tuple, Union, Optional

import colour
from APU.APU import APU
from appJar import gui
from appJar.appjar import ItemLookupError
from debug import log
from editor_settings import EditorSettings
from rom import ROM

# Note definitions as read from ROM
from undo_redo import UndoRedo

_notes: List[int] = []

# TODO Create note names based on the period (with approximation), in case they had been modified in ROM
_NOTE_NAMES = ["C2 ", "C#2", "D2 ", "D#2", "E2 ", "F2 ", "F#2", "G2 ", "G#2", "A2 ", "A#2", "B2 ",
               "C3 ", "C#3", "D3 ", "D#3", "E3 ", "F3 ", "F#3", "G3 ", "G#3", "A3 ", "A#3", "B3 ",
               "C4 ", "C#4", "D4 ", "D#4", "E4 ", "F4 ", "F#4", "G4 ", "G#4", "A4 ", "A#4", "B4 ",
               "C5 ", "C#5", "D5 ", "D#5", "E5 ", "F5 ", "F#5", "G5 ", "G#5", "A5 ", "A#5", "B5 ",
               "C6 ", "C#6", "D6 ", "D#6", "E6 ", "F6 ", "F#6", "G6 ", "G#6", "A6 ", "A#6", "B6 "]

# This is to quickly get a duty representation based on the register's value
_DUTY = ["12.5%", "  25%", "  50%", "  75%"]

# Envelope lookup tables, one per envelope level (0-8) containing each one value per volume level (0-F)
# This will be a lot quicker than calculating output levels every frame
_ENV_TABLE = [[0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0],
              [0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x1, 0x1, 0x1, 0x1, 0x1, 0x1, 0x1, 0x1],
              [0x0, 0x0, 0x0, 0x0, 0x1, 0x1, 0x1, 0x1, 0x2, 0x2, 0x2, 0x2, 0x3, 0x3, 0x3, 0x3],
              [0x0, 0x0, 0x0, 0x0, 0x1, 0x1, 0x1, 0x1, 0x3, 0x3, 0x3, 0x3, 0x4, 0x4, 0x4, 0x4],
              [0x0, 0x0, 0x1, 0x1, 0x2, 0x2, 0x3, 0x3, 0x4, 0x4, 0x5, 0x5, 0x6, 0x6, 0x7, 0x7],
              [0x0, 0x0, 0x1, 0x1, 0x2, 0x2, 0x3, 0x3, 0x5, 0x5, 0x6, 0x6, 0x7, 0x7, 0x8, 0x8],
              [0x0, 0x0, 0x1, 0x1, 0x3, 0x3, 0x4, 0x4, 0x6, 0x6, 0x7, 0x7, 0x9, 0x9, 0xA, 0xA],
              [0x0, 0x0, 0x1, 0x1, 0x3, 0x3, 0x4, 0x4, 0x7, 0x7, 0x8, 0x8, 0xA, 0xA, 0xB, 0xB],
              [0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF]]


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

        return (self.envelope[envelope_id][volume_id] & 0x1F) >> 1

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

    def __init__(self, index: int = 0, duration: int = 0, name: str = ""):
        global _notes

        self.index: int = index
        self.duration: int = duration

        if name != "":
            if len(name) < 3:
                name = name + ' '
            try:
                self.index = _NOTE_NAMES.index(name.upper())
            except ValueError:
                pass

        # From the NESDev Wiki:
        # frequency = fCPU/(16*(period+1))
        # fCPU = 1.789773 MHz for NTSC, 1.662607 MHz for PAL, and 1.773448 MHz for Dendy
        period = 0x6AB  # A default value to use until notes are loaded
        try:
            period = _notes[self.index]
        except IndexError:
            pass
        finally:
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
    CHANNEL_VOLUME: int = 0xFB
    SELECT_INSTRUMENT: int = 0xFC
    SET_VIBRATO: int = 0xFD
    REST: int = 0xFE
    REWIND: int = 0xFF

    def __init__(self, raw: bytearray = bytearray()):
        self.control: int = raw[0]

        if self.control < 0xF0:
            self.note = Note(raw[0], raw[1])
        else:
            self.note = Note()

        # How many bytes does this entry take, control byte included
        self.size: int = len(raw)

        # Raw bytes forming this entry
        self.raw: bytearray = raw

        self.loop_position: int = 0

    # "set" functions automatically update the raw value (except for the rewind offset), without risking to modify
    # the element's type

    def set_volume(self, level: int) -> None:
        if self.control == TrackDataEntry.CHANNEL_VOLUME:
            self.raw[1] = level

    def set_instrument(self, index: int) -> None:
        if self.control == TrackDataEntry.SELECT_INSTRUMENT:
            self.raw[1] = index

    def set_vibrato(self, octave: bool, speed: int, factor: int) -> None:
        if self.control == TrackDataEntry.SET_VIBRATO:
            self.raw[1] = 0 if octave else 0xFF
            self.raw[2], self.raw[3] = speed, factor

    def set_rest(self, duration: int) -> None:
        if self.control == TrackDataEntry.REST:
            self.raw[1] = duration

    def set_rewind(self, position: int) -> None:
        if self.control == TrackDataEntry.REWIND:
            self.loop_position = position
        # NOTE: raw value must be calculated from the instance holding the array with all the elements,
        #   this at the moment happens before saving to ROM

    def set_note(self, index: int, duration: int) -> None:
        if self.control < 0xF0:
            self.note = Note(index, duration)
            self.raw[0], self.raw[1] = index, duration

    def change_type(self, new_type: int, values: Tuple[Union[int, bool]] = None) -> None:
        """
        Changes to the desired type of element.

        Parameters
        ----------
        new_type: int
            CHANNEL_VOLUME, SELECT_INSTRUMENT, SET_VIBRATO, REST, REWIND or note index
        values: Tuple[Union[int, bool]]
            An optional list of values for the desired element type
        """
        if values is None:
            size = 0
        else:
            size = len(values)
        if new_type < 0xF0:
            value = values[0] if size > 0 else 0
            duration = values[1] if size > 1 else 7
            self.note = Note(value, duration)
            self.raw = bytearray([value, duration])
            self.control = value

        elif new_type == TrackDataEntry.CHANNEL_VOLUME:
            self.control = new_type
            value = values[0] if size > 0 else 15
            self.raw = bytearray([TrackDataEntry.CHANNEL_VOLUME, value])

        elif new_type == TrackDataEntry.SELECT_INSTRUMENT:
            self.control = new_type
            value = values[0] if size > 0 else 15
            self.raw = bytearray([TrackDataEntry.SELECT_INSTRUMENT, value])

        elif new_type == TrackDataEntry.SET_VIBRATO:
            self.control = new_type
            octave = values[0] if size > 0 else False
            value = values[1] if size > 1 else 0
            factor = values[2] if size > 2 else 0
            self.raw = bytearray([TrackDataEntry.SET_VIBRATO, 0 if octave is True else 0xFF, value, factor])

        elif new_type == TrackDataEntry.REST:
            self.control = new_type
            duration = values[0] if size > 0 else 7
            self.raw = bytearray([TrackDataEntry.REST, duration])

        elif new_type == TrackDataEntry.REWIND:
            self.control = new_type
            value = values[0] if size > 0 else 0
            self.loop_position = value
            self.raw = bytearray([TrackDataEntry.REWIND, 0, 0, 0])

    @classmethod
    def new_volume(cls, level: int):
        return cls(bytearray([0xFB, level & 0x0F]))

    @classmethod
    def new_instrument(cls, index: int):
        return cls(bytearray([0xFC, index]))

    @classmethod
    def new_vibrato(cls, higher_octave: bool, speed: int, factor: int):
        if speed < 2:
            return cls(bytearray([0xFD, 0 if higher_octave else 0xFF, 0, 0]))
        else:
            return cls(bytearray([0xFD, 0 if higher_octave is True else 0xFF, speed, factor]))

    @classmethod
    def new_rest(cls, duration: int):
        return cls(bytearray([0xFE, duration]))

    @classmethod
    def new_rewind(cls, _position: int, offset: int = 0):
        # NOTE: Offset must be recalculated when adding or removing elements
        # The offset is the difference between the position (in number of bytes) of the rewind element and the position
        # where we want to jump to
        # In order to know where the rewind element is, we need to sum the sizes of every previous element
        return cls(bytearray([0xFF, 0, offset & 0x00FF, offset >> 8]))

    @classmethod
    def new_note(cls, index: int = 0, duration: int = 0, name: str = ""):
        if name != "":
            note = Note(duration=duration, name=name)
        else:
            note = Note(index, duration)

        return cls(bytearray([note.index, note.duration]))


# ----------------------------------------------------------------------------------------------------------------------

class MusicEditor:

    def __init__(self, app: gui, rom: ROM, settings: EditorSettings, apu: APU, sound_server: pyo.Server):
        self.app = app
        self.rom = rom

        # --- Common ---
        self._bank: int = 8  # Default value, changes upon opening an edit window
        self._settings = settings

        # --- Track Editor ---
        self._track_address: List[int] = [0, 0, 0, 0]
        # Index of the track in ROM, within the current bank, useful when allocating space
        self._track_index: int = 0
        self._selected_channel: int = 0
        self._selected_element: int = 0
        self._track_undo: UndoRedo = UndoRedo()
        # Each action can undo or redo a variable number of tasks, for example if a selection of 4 items are deleted
        #   4 undo actions will be created, but a single "Undo" must undo all of them at once, so we would add 4
        #   to this list in that case
        self._track_undo_count: List[int] = []
        self._track_redo_count: List[int] = []

        # --- Instrument Editor ---
        self._instruments: List[Instrument] = []
        self._selected_instrument: int = 0
        self._test_channel: int = 1
        self._instrument_undo: UndoRedo = UndoRedo()
        self._instrument_undo_count: List[int] = []
        self._instrument_redo_count: List[int] = []

        # --- General ---
        self.sound_server = sound_server
        self.apu = apu

        self._triangle_volume = 0.5

        self.track_titles: List[List[str]] = [["- No Tracks -"], ["- No Tracks-"]]

        # --- GUI ---
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

        # Each of the two ROM banks used for music contain two tables of period values for each note
        self._note_period_lo: bytearray = bytearray()
        self._note_period_hi: bytearray = bytearray()

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

    def is_playing(self) -> bool:
        return self._playing

    # ------------------------------------------------------------------------------------------------------------------

    def _save_current_track_title(self) -> None:
        # If any definition filename matches the currently loaded ROM filename, then use that one
        file_name = os.path.basename(self.rom.path).rsplit('.')[0] + "_audio.ini"
        if os.path.exists(os.path.dirname(self.rom.path) + '/' + file_name):
            file_name = os.path.dirname(self.rom.path) + '/' + file_name
        elif os.path.exists("audio.ini"):
            file_name = "audio.ini"

        title: str = f"{self.app.getEntry('SE_Track_Name')}"
        if len(title) < 1:
            # Nothing to save
            return

        parser = configparser.ConfigParser()
        try:
            parser.read(file_name)
            if not parser.has_section(f"BANK_{self._bank}"):
                parser.add_section(f"BANK_{self._bank}")
            parser.set(f"BANK_{self._bank}", f"{self._track_index}", title.replace('%', '%%'))

            parser.write(open(file_name, "w"))

        except ValueError:
            self.app.warningBox("Track Editor", f"Invalid track title '{title}'.")

        except configparser.ParsingError as error:
            self.error(f"Error parsing track names: '{error}'.")

        except IOError as error:
            self.error(f"Could not save track name to file: '{error}'.")

        self.track_titles[self._bank - 8][self._track_index] = title

        # Update option boxes in main window tabs
        self.app.changeOptionBox("Battlefield_Option_Music", self.track_titles[0] + self.track_titles[1])
        self.app.changeOptionBox("CE_Param_2_00", self.track_titles[0] + self.track_titles[1])
        self.app.setOptionBox("ST_Music_Bank", self._bank - 8, callFunction=True)

    # ------------------------------------------------------------------------------------------------------------------

    def read_track_titles(self) -> List[List[str]]:
        """
        Reads track titles from music.txt, or <ROM name>_music.txt if present.

        Returns
        -------
        List[List[str]]
            Two lists of strings corresponding to track titles in banks 8 and 9 respectively
        """
        track_titles: List[List[str]] = [[], []]

        # If any definition filename matches the currently loaded ROM filename, then use that one
        file_name = os.path.basename(self.rom.path).rsplit('.')[0] + "_audio.ini"
        if os.path.exists(os.path.dirname(self.rom.path) + '/' + file_name):
            file_name = os.path.dirname(self.rom.path) + '/' + file_name
        elif os.path.exists("audio.ini"):
            file_name = "audio.ini"

        # Get number of tracks in bank 8 from ROM
        bank_8_count = self.rom.read_byte(0x8, 0x8001)

        # Default names when no files found
        for t in range(bank_8_count):
            track_titles[0].append(f"Bank #08 Track #{t:02}")
        for t in range(4):
            track_titles[1].append(f"Bank #09 Track #{t:02}")

        if not os.path.exists(file_name):
            self.track_titles = track_titles
            return track_titles

        try:
            parser = configparser.ConfigParser()
            parser.read(file_name)

            if parser.has_section("BANK_8"):
                for t in range(bank_8_count):
                    track_titles[0][t] = parser.get("BANK_8", f"{t}", fallback=f"Bank #08 Track #{t:02}")
            if parser.has_section("BANK_9"):
                for t in range(4):
                    track_titles[1][t] = parser.get("BANK_9", f"{t}", fallback=f"Bank #08 Track #{t:02}")

        except configparser.ParsingError as error:
            self.app.errorBox("Music Editor", f"Could not parse track titles from file '{file_name}': {error}")
            self.track_titles = track_titles
            return track_titles

        self.track_titles = track_titles
        return track_titles

    # ------------------------------------------------------------------------------------------------------------------

    def close_track_editor(self) -> bool:
        if self._unsaved_changes_track is True:
            if self.app.yesNoBox("Track Editor", "Are you sure you want to close the Track Editor?\n" +
                                                 "Any unsaved changes will be lost.", "Track_Editor") is False:
                return False

        try:
            self.app.destroySubWindow("Track_Info")
        except ItemLookupError:
            pass

        # If playing, stop and wait for the thread to finish
        self.stop_playback()

        self.app.hideSubWindow("Track_Editor", useStopFunction=False)
        self.app.emptySubWindow("Track_Editor")

        self._track_undo.clear()
        self._track_undo_count = []
        self._track_redo_count = []

        self._unsaved_changes_track = False

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def close_instrument_editor(self) -> bool:
        if self._unsaved_changes_instrument is True:
            if self.app.yesNoBox("Instrument Editor", "Are you sure you want to close the Instrument Editor?\n" +
                                                      "Any unsaved changes will be lost.",
                                 "Instrument_Editor") is False:
                return False

        try:
            self.app.destroySubWindow("Instrument_Info")
        except ItemLookupError:
            pass

        # If playing test notes, stop and wait for the thread to finish
        self.stop_playback()

        self.app.hideSubWindow("Instrument_Editor", useStopFunction=False)
        self.app.emptySubWindow("Instrument_Editor")

        self._instrument_undo.clear()
        self._instrument_undo_count = []
        self._instrument_redo_count = []

        self._unsaved_changes_instrument = False

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
                self.sound_server.stop()

            if self._slow_event.is_set():
                self.warning("Slow playback detected! This may be due to too many non-note events in a track, or " +
                             "a slow machine, or slow audio host API.")

        self.apu.reset()
        self.apu.stop()

    # ------------------------------------------------------------------------------------------------------------------

    def start_playback(self, update_tracker: bool = False, seek: bool = False, tracks=None) -> None:
        # self._stop_event.clear()

        self._playing = True

        if update_tracker:
            if self._update_thread.is_alive():
                self.warning("UI Update thread already running!")
            else:
                self._update_thread = threading.Thread(target=self._tracker_update_loop, args=())
                self._update_thread.start()

        if self._play_thread.is_alive():
            self.warning("Playback thread already running!")
        else:
            if seek and self._selected_channel > -1 and self._selected_element > 0:
                self._play_thread = threading.Thread(target=self._play_loop,
                                                     args=((self._selected_channel, self._selected_element), tracks,))
            else:
                self._play_thread = threading.Thread(target=self._play_loop, args=((0, 0), tracks,))

            self.apu.reset()
            self.apu.play()
            self._play_thread.start()

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
        self._track_index = track

        self._selected_channel = 0

        self.app.showSubWindow("PE_Progress")
        self.app.setLabel("PE_Progress_Label", "Loading...")
        self.app.setMeter("PE_Progress_Meter", 0)
        self.app.topLevel.update()

        # Load note period tables
        # Interestingly, there seem to be 78 entries for high byte but only 60 for low byte... we'll let it overflow
        # like it would in the game for an "invalid" note index
        if bank == 8:
            self._note_period_hi = self.rom.read_bytes(bank, 0x85AF, 78)
            self._note_period_lo = self.rom.read_bytes(bank, 0x85FD, 78)
        else:
            self._note_period_hi = self.rom.read_bytes(bank, 0x85B2, 78)
            self._note_period_lo = self.rom.read_bytes(bank, 0x8600, 78)

        try:
            self.app.getFrameWidget("SE_Frame_Buttons")
            window_exists = True
        except ItemLookupError:
            window_exists = False

        # Get this track's address
        address = (track << 3) + (0x8051 if bank == 8 else 0x8052)
        for t in range(4):
            self._track_address[t] = self.rom.read_word(bank, address)
            address += 2

        # Read instrument data
        self.read_instrument_data()

        self.app.setMeter("PE_Progress_Meter", 10)
        self.app.topLevel.update()

        instrument_names: List[str] = []
        i = 0
        for instrument in self._instruments:
            instrument_names.append(f"{i:02X} {instrument.name if len(instrument.name) > 0 else '(no name)'}")
            i += 1

        # Read or re-read track titles
        self.read_track_titles()

        self.app.setMeter("PE_Progress_Meter", 20)
        self.app.topLevel.update()

        # Read track data for all tracks
        self.read_track_data(0)
        self.app.setMeter("PE_Progress_Meter", 30)
        self.app.topLevel.update()
        self.read_track_data(1)
        self.app.setMeter("PE_Progress_Meter", 40)
        self.app.topLevel.update()
        self.read_track_data(2)
        self.app.setMeter("PE_Progress_Meter", 50)
        self.app.topLevel.update()
        self.read_track_data(3)
        self.app.setMeter("PE_Progress_Meter", 60)
        self.app.topLevel.update()

        if window_exists:
            self.app.showSubWindow("Track_Editor")
            self.app.setMeter("PE_Progress_Meter", 100)
            self.app.topLevel.update()
            return

        with self.app.subWindow("Track_Editor"):

            # Buttons
            with self.app.frame("SE_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0):
                # Left
                self.app.button("SE_Button_Apply", self._track_input, image="res/floppy.gif", width=32, height=32,
                                tooltip="Apply changes to all channels", bg=colour.PALE_NAVY,
                                sticky="W", row=0, column=0)
                self.app.button("SE_Button_Import", self._track_input, image="res/import.gif", width=32, height=32,
                                tooltip="Import track data from file", bg=colour.PALE_NAVY,
                                sticky="W", row=0, column=1)
                self.app.button("SE_Button_Export", self._track_input, image="res/export.gif", width=32, height=32,
                                tooltip="Export track data to file", bg=colour.PALE_NAVY,
                                sticky="W", row=0, column=2)
                self.app.button("SE_Button_Reload", self._track_input, image="res/reload.gif", width=32, height=32,
                                tooltip="Reload track data from ROM", bg=colour.PALE_NAVY,
                                sticky="W", row=0, column=3)
                self.app.button("SE_Button_Undo", self._track_input, image="res/undo.gif", width=32, height=32,
                                tooltip="Undo last action", bg=colour.PALE_NAVY,
                                sticky="W", row=0, column=4).configure(state="disabled")
                self.app.button("SE_Button_Redo", self._track_input, image="res/redo.gif", width=32, height=32,
                                tooltip="Redo last action", bg=colour.PALE_NAVY,
                                sticky="W", row=0, column=5).configure(state="disabled")
                self.app.button("SE_Button_Cancel", self._track_input, image="res/close.gif", width=32, height=32,
                                tooltip="Cancel / Close window", bg=colour.PALE_NAVY,
                                sticky="W", row=0, column=6)

                self.app.canvas("SE_Temp", width=250, height=20, row=0, column=7)

                # Right
                self.app.button("SE_Play_Stop", self._track_input, image="res/stop_play.gif", width=32, height=32,
                                tooltip="Start / Stop track playback", bg=colour.PALE_GREEN,
                                sticky="E", row=0, column=8)
                self.app.button("SE_Button_Rewind", self._track_input, image="res/rewind.gif", width=32, height=32,
                                tooltip="Jump to the first element of each channel", bg=colour.PALE_GREEN,
                                sticky="E", row=0, column=9)
                self.app.button("SE_Play_Seek", self._track_input, image="res/play.gif", width=32, height=32,
                                tooltip="Start playback from selection", bg=colour.PALE_GREEN,
                                sticky="E", row=0, column=10)
                self.app.button("SE_Button_Info", self._track_input, image="res/info.gif", width=32, height=32,
                                tooltip="Show track info/statistics", bg=colour.PALE_GREEN,
                                sticky="E", row=0, column=11)

            # Editing
            with self.app.frame("SE_Frame_Editing", sticky="NEWS", row=1, column=0):
                # Editable track info
                with self.app.labelFrame("SE_Frame_Track_Info", name="Track Info", padding=[4, 2],
                                         row=0, column=0, rowspan=2):
                    self.app.entry("SE_Track_Name", f"{self.track_titles[bank - 8][track]}", width=24,
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
                    self.app.label("SE_Selection_Info", "Channel - Element -", sticky="W",
                                   row=0, column=0, font=9)
                    self.app.button("SE_Change_Element", self._element_input, image="res/change_element_type.gif",
                                    tooltip="Change selected element's type", bg=colour.DARK_NAVY,
                                    sticky="WE", row=1, column=0, font=9)

                # Element editing controls
                with self.app.frameStack("SE_Stack_Editing", start=0, row=1, column=1):
                    # 0: No selection
                    with self.app.frame("SE_Frame_Empty", padding=[4, 4], bg=colour.DARK_NAVY, fg=colour.WHITE):
                        self.app.label("SE_Label_No_Selection", "No selection", font=12)

                    # 1: Edit volume
                    with self.app.frame("SE_Frame_Volume", padding=[4, 4], bg=colour.DARK_BLUE, fg=colour.PALE_LIME):
                        self.app.label("SE_Label_Volume_Element", "EDIT VOLUME", sticky="NW",
                                       row=0, column=0, colspan=2, font=11)
                        self.app.label("SE_Label_Edit_Volume", "Value: ", sticky="E", row=1, column=0, font=10)
                        self.app.entry("SE_Entry_Volume", "0", submit=self._element_input,
                                       sticky="W", width=3, row=1, column=1, font=9)

                        self.app.button("SE_Apply_Volume", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.DARK_BLUE,
                                        sticky="SEW", row=1, column=0, colspan=2)

                    # 2: Edit note
                    with self.app.frame("SE_Frame_Note", padding=[4, 4], bg=colour.BLACK, fg=colour.PALE_ORANGE):
                        self.app.label("SE_Label_Note", "EDIT NOTE", sticky="NW", colspan=3, font=11)

                        self.app.label("SE_Label_Note_Value", "Value:", sticky="SE", row=0, column=0, font=10)
                        self.app.entry("SE_Note_Value", " ", submit=self._element_input,
                                       width=4, sticky="SW", row=0, column=1, font=9)

                        self.app.label("SE_Label_Note_Duration", "Duration:", sticky="SE", row=0, column=2, font=10)
                        self.app.entry("SE_Note_Duration", " ", submit=self._element_input,
                                       width=4, sticky="SW", row=0, column=3, font=9)

                        self.app.button("SE_Apply_Note", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.BLACK,
                                        sticky="SEW", row=1, column=0, colspan=4)

                    # 3: Edit rest
                    with self.app.frame("SE_Frame_Rest", padding=[4, 4], bg=colour.DARK_OLIVE, fg=colour.PALE_MAGENTA):
                        self.app.label("SE_Label_Rest_Element", "EDIT REST", sticky="NW",
                                       row=0, column=0, colspan=2, font=11)
                        self.app.label("SE_Label_Edit_Rest", "Duration:", sticky="E", row=1, column=0, font=10)
                        self.app.entry("SE_Rest_Duration", "0", submit=self._element_input,
                                       sticky="W", width=3, row=1, column=1, font=9)

                        self.app.button("SE_Apply_Rest", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.DARK_OLIVE,
                                        sticky="SEW", row=1, column=0, colspan=2)

                    # 4: Edit vibrato
                    with self.app.frame("SE_Frame_Vibrato", padding=[4, 4], bg=colour.DARK_VIOLET, fg=colour.PALE_PINK):
                        self.app.label("SE_Label_Vibrato", "EDIT VIBRATO", sticky="NW", colspan=3, font=11)

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

                    # 5: Edit instrument
                    with self.app.frame("SE_Frame_Instrument", padding=[4, 4], bg=colour.DARK_ORANGE,
                                        fg=colour.PALE_TEAL):
                        self.app.label("SE_Label_Instrument", "EDIT INSTRUMENT", sticky="NW",
                                       row=0, column=0, font=11)

                        self.app.listBox("SE_Select_Instrument", instrument_names, change=self._element_input,
                                         bg=colour.DARK_ORANGE, fg=colour.PALE_TEAL, group=True, multi=False,
                                         fixed_scrollbar=True, width=27, height=9, sticky="W", row=1, column=0, font=9)

                    # 6: Edit rewind
                    with self.app.frame("SE_Frame_Rewind", padding=[4, 4], bg=colour.DARK_MAGENTA,
                                        fg=colour.PALE_VIOLET):
                        self.app.label("SE_Label_Rewind", "EDIT REWIND", sticky="NW",
                                       row=0, column=0, colspan=2, font=11)

                        self.app.label("SE_Label_Edit_Rewind", "Rewind to element:",
                                       sticky="E", row=1, column=0, font=10)
                        self.app.entry("SE_Rewind_Value", "0", submit=self._element_input,
                                       sticky="W", width=3, row=1, column=1, font=9)

                        self.app.button("SE_Apply_Rewind", self._element_input, image="res/check_green-small.gif",
                                        tooltip="Apply Changes", bg=colour.DARK_MAGENTA,
                                        sticky="SEW", row=1, column=0, colspan=2)

                    # 7: Change element type
                    with self.app.frame("SE_Frame_Element_Type", padding=[4, 4], bg=colour.DARK_BROWN, fg=colour.WHITE):
                        self.app.label("SE_Label_Change_Type", "CHANGE SELECTED TO:", sticky="NW",
                                       row=0, column=0, colspan=3, font=11)

                        self.app.button("SE_Change_To_Note", self._element_input, image="res/note_element.gif",
                                        tooltip="Change to Note", bg=colour.BLACK,
                                        sticky="E", row=1, column=0)
                        self.app.button("SE_Change_To_Volume", self._element_input, image="res/volume_element.gif",
                                        tooltip="Change to Volume", bg=colour.DARK_BLUE,
                                        sticky="", row=1, column=1)
                        self.app.button("SE_Change_To_Instrument", self._element_input,
                                        image="res/instrument_element.gif",
                                        tooltip="Change to Instrument", bg=colour.DARK_ORANGE,
                                        sticky="W", row=1, column=2)

                        self.app.button("SE_Change_To_Vibrato", self._element_input, image="res/vibrato_element.gif",
                                        tooltip="Change to Vibrato", bg=colour.DARK_VIOLET,
                                        sticky="E", row=2, column=0)
                        self.app.button("SE_Change_To_Rest", self._element_input, image="res/rest_element.gif",
                                        tooltip="Change to Rest", bg=colour.DARK_OLIVE,
                                        sticky="", row=2, column=1)
                        self.app.button("SE_Change_To_Rewind", self._element_input, image="res/rewind_element.gif",
                                        tooltip="Change to Rewind", bg=colour.DARK_MAGENTA,
                                        sticky="W", row=2, column=2)

                        self.app.button("SE_Cancel_Change_Element", self._element_input, tooltip="Cancel Change",
                                        image="res/cross_red-small.gif", bg=colour.DARK_BROWN,
                                        sticky="SEW", row=3, column=0, colspan=3)

                    # 8: Edit multiple
                    with self.app.frame("SE_Frame_Multiple", padding=[4, 4], bg=colour.DARK_VIOLET, fg=colour.WHITE):
                        self.app.label("SE_Label_Multiple", "MULTIPLE SELECTION", sticky="NW",
                                       row=0, column=0, colspan=3, font=11)

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
                with self.app.frame("SE_Frame_Selection", padding=[4, 1], row=0, column=2, rowspan=2):
                    self.app.label("SE_Label_Select", "Quick Selection", sticky="NEW", row=0, column=0, font=10)

                    with self.app.frame("SE_Frame_Selection_Buttons", padding=[4, 1], row=1, column=0):
                        self.app.button("SE_Select_Channel_0", self._track_input, image="res/square_0.gif",
                                        bg=colour.MEDIUM_GREEN, row=0, column=0)
                        self.app.button("SE_Select_Channel_1", self._track_input, image="res/square_1.gif",
                                        bg=colour.DARK_NAVY, row=0, column=1)
                        self.app.button("SE_Select_Channel_2", self._track_input, image="res/triangle_wave.gif",
                                        bg=colour.DARK_NAVY, row=0, column=2)
                        self.app.button("SE_Select_Channel_3", self._track_input, image="res/noise_wave.gif",
                                        bg=colour.DARK_NAVY, row=0, column=3)

                    with self.app.frame("SE_Frame_Selection_Values", padding=[4, 1], row=2, column=0):
                        self.app.label("SE_Label_Select_From", "All notes from:", sticky="E", row=0, column=0, font=10)
                        self.app.entry("SE_Select_From", "C2", submit=self._track_input, width=4,
                                       sticky="W", row=0, column=1, font=9)
                        self.app.label("SE_Label_Select_To", " to: ", sticky="E", row=0, column=2, font=10)
                        self.app.entry("SE_Select_To", "C3", submit=self._track_input, width=4,
                                       sticky="W", row=0, column=3, font=9)

                    self.app.button("SE_Apply_Notes_Selection", self._track_input, image="res/check_green-small.gif",
                                    tooltip="Apply Selection", bg=colour.DARK_NAVY, sticky="SEW", row=3, column=0)

                    with self.app.frame("SE_Frame_Selection_Type", padding=[4, 1], row=4, column=0):
                        self.app.label("SE_Label_Select_Types", "All elements of type:", sticky="E",
                                       row=0, column=0, font=10)
                        self.app.optionBox("SE_Select_Type", ["Volume", "Instrument", "Vibrato", "Rest", "Note",
                                                              "Others"], sticky="W", row=0, column=1, font=9)

                    self.app.button("SE_Apply_Type_Selection", self._track_input, image="res/check_green-small.gif",
                                    tooltip="Apply Selection", bg=colour.DARK_NAVY, sticky="SEW", row=5, column=0)

                    self.app.button("SE_Clear_Selection", self._track_input, image="res/clear_selection-small.gif",
                                    tooltip="Clear Selection",
                                    bg=colour.DARK_VIOLET, sticky="SEW", row=6, column=0)

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

        self.app.setMeter("PE_Progress_Meter", 80)
        self.app.topLevel.update()

        # Set the volume slider to the current amp factor
        self.app.setScale("SE_Master_Volume", int(self.sound_server.amp * 100), callFunction=False)
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
        self.app.getListBoxWidget(f"SE_List_Channel_0").bind("<Button-3>",
                                                             lambda event: self._element_right_click(event, 0), add='')
        self.app.getListBoxWidget(f"SE_List_Channel_1").bind("<Button-3>",
                                                             lambda event: self._element_right_click(event, 1), add='')
        self.app.getListBoxWidget(f"SE_List_Channel_2").bind("<Button-3>",
                                                             lambda event: self._element_right_click(event, 2), add='')
        self.app.getListBoxWidget(f"SE_List_Channel_3").bind("<Button-3>",
                                                             lambda event: self._element_right_click(event, 3), add='')

        self.app.setMeter("PE_Progress_Meter", 90)
        self.app.topLevel.update()

        self.track_info(0)
        self.track_info(1)
        self.track_info(2)
        self.track_info(3)

        self._unsaved_changes_track = False
        self.app.showSubWindow("Track_Editor")

        self.app.setMeter("PE_Progress_Meter", 100)
        self.app.topLevel.update()

        # Hotkey bindings
        sw = self.app.openSubWindow("Track_Editor")
        sw.bind("<Control-z>", self._undo_track_action, add='')
        sw.bind("<Control-y>", self._redo_track_action, add='')

        self.app.hideSubWindow("PE_Progress")
        self.app.setFocus("SE_Track_Name")

    # ------------------------------------------------------------------------------------------------------------------

    def show_track_info(self) -> None:
        """
        Creates the info window if necessary, then shows it
        """
        try:
            self.app.openSubWindow("Track_Info")
            window_exists = True
        except ItemLookupError:
            window_exists = False

        track_info: List[str] = []
        channel_names = ["Square Channel 0:", "Square Channel 1:", "Triangle Channel:", "Noise Channel:"]

        # Calculate each channel's frame count
        for c in range(4):
            frames = 0
            notes = 0
            rests = 0
            instruments = 0
            volumes = 0

            for e in self._track_data[c]:
                if e.raw[0] == 0xFE:
                    frames += e.raw[1]
                    rests += 1
                elif e.raw[0] == 0xFC:
                    instruments += 1
                elif e.raw[0] == 0xFB:
                    volumes += 1
                elif e.raw[0] < 0xF0:
                    frames += e.raw[1]
                    notes += 1

            track_info.append(channel_names[c])
            track_info.append(f"    {frames} frames")
            track_info.append(f"    {notes} notes")
            track_info.append(f"    {rests} rests")
            track_info.append(f"    {volumes} volume changes")
            track_info.append(f"    {instruments} instrument changes")
            track_info.append(" ")

        if window_exists:
            self.app.showSubWindow("Track_Info")
        else:
            # Create sub-window
            with self.app.subWindow("Track_Info", title="Track Info / Statistics", padding=[2, 2], size=[320, 240],
                                    resizable=False, modal=True, blocking=True, bg=colour.DARK_BLUE, fg=colour.WHITE):
                self.app.label("TI_Label_Title", "Name: " + self.app.getEntry("SE_Track_Name"), sticky="NEW",
                               row=0, column=0, font=11)
                self.app.label("TI_Label_Index", f"Track #{self._track_index} on bank {self._bank}", sticky="NEW",
                               row=1, column=0, font=10)
                self.app.listBox("TI_List_Info", track_info, height=10, sticky="NEWS", row=2, column=0, font=9)

        self.app.showSubWindow("Track_Info")
        self.app.getEntryWidget("SE_Track_Name").focus_set()

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

        # Load note period tables
        # Interestingly, there seem to be 78 entries for high byte but only 60 for low byte... we'll let it overflow
        # like it would in the game for an "invalid" note index
        if bank == 8:
            self._note_period_hi = self.rom.read_bytes(bank, 0x85AF, 78)
            self._note_period_lo = self.rom.read_bytes(bank, 0x85FD, 78)
        else:
            self._note_period_hi = self.rom.read_bytes(bank, 0x85B2, 78)
            self._note_period_lo = self.rom.read_bytes(bank, 0x8600, 78)

        self.read_instrument_data()

        self._test_channel = 1  # Square channel

        instruments_list: List[str] = []
        for i in range(len(self._instruments)):
            instruments_list.append(f"{i:02X} {self._instruments[i].name}")

        with self.app.subWindow("Instrument_Editor"):

            # Buttons
            with self.app.frame("IE_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0, colspan=3):
                self.app.button("IE_Button_Apply", self._instruments_input, image="res/floppy.gif", width=32, height=32,
                                tooltip="Apply changes to all instruments", bg=colour.MEDIUM_GREY,
                                row=0, column=0)
                self.app.button("IE_Button_Import", self._instruments_input, image="res/import.gif",
                                tooltip="Import instruments from file", bg=colour.MEDIUM_GREY, width=32, height=32,
                                row=0, column=1)
                self.app.button("IE_Button_Export", self._instruments_input, image="res/export.gif",
                                tooltip="Export instruments to file", bg=colour.MEDIUM_GREY, width=32, height=32,
                                row=0, column=2)
                self.app.button("IE_Button_Cancel", self._instruments_input, image="res/close.gif", width=32, height=32,
                                tooltip="Cancel / Close window", bg=colour.MEDIUM_GREY,
                                row=0, column=3)

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
                self.app.button("IE_Button_Channel", self._instruments_input, image="res/square_wave.gif",
                                bg=colour.MEDIUM_ORANGE, tooltip="Square Wave Channel",
                                sticky="W", row=0, column=0)

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

                self.app.button("IE_Show_Info", self._instruments_input, image="res/info.gif",
                                tooltip="Show instrument usage and other info", bg=colour.LIGHT_ORANGE,
                                sticky="E", row=2, column=0)
                self.app.button("IE_Play_Stop", self._instruments_input, image="res/play.gif",
                                width=32, height=32, bg=colour.LIGHT_ORANGE, sticky="E", row=3, column=0)

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
                                     multi=False, group=True, bg=colour.DARK_RED, fg=colour.WHITE,
                                     sticky="S", row=1, column=c, font=9)
                    self.app.getListBoxWidget(f"IE_List_Envelope_{e}").configure(font="TkFixedFont")

                    # Buttons
                    self.app.button(f"IE_Move_Left_{e}", self._instruments_input, image="res/arrow_left-long.gif",
                                    tooltip="Move value to the previous envelope",
                                    height=16, sticky="SEW", row=2, column=c, bg=colour.LIGHT_ORANGE)
                    self.app.button(f"IE_Move_Right_{e}", self._instruments_input, image="res/arrow_right-long.gif",
                                    tooltip="Move value to the next envelope",
                                    height=16, sticky="NEW", row=3, column=c, bg=colour.LIGHT_ORANGE)

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

    def export_instrument_data(self, file_name: str) -> bool:
        try:
            fd = open(file_name, "wb")
        except IOError as error:
            self.app.errorBox("Export Instruments", f"Error opening file '{file_name}': {error}.",
                              "Instrument_Editor")
            return False

        count = 0
        for i in self._instruments:
            buffer = bytearray()

            buffer.append(len(i.name))
            buffer += bytes(i.name, "utf-8")

            for e in i.envelope:
                buffer.append(len(e))
                buffer += e

            fd.write(buffer)
            count += 1

        fd.close()

        self.app.infoBox("Export Instruments", f"{count} instruments have been successfully saved to file.",
                         "Instrument_Editor")

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def import_instrument_data(self, file_name: str) -> bool:
        try:
            fd = open(file_name, "rb")
        except IOError as error:
            self.app.errorBox("Import Instruments", f"Error opening file '{file_name}': {error}.",
                              "Instrument_Editor")
            return False

        count = 0

        for i in self._instruments:
            # Read name length
            size = fd.read(1)
            if len(size) < 1:
                break
            # Name string
            data = fd.read(size[0])
            if len(data) < 1:
                break

            try:
                i.name = str(data, "utf-8")
            except UnicodeDecodeError:
                i.name = "(No Name)"

            # Envelopes
            for e in range(3):
                size = fd.read(1)
                if len(size) < 1:
                    break
                data = fd.read(size[0])
                # Don't change the size of the envelopes
                old_size = len(i.envelope[e])
                for v in range(1, old_size):
                    if v < size[0]:
                        i.envelope[e][v] = data[v]
                    else:
                        i.envelope[e][v] = 0

            count += 1

        fd.close()

        self.app.infoBox("Import Instruments", f"{count} instruments have been successfully imported.",
                         "Instrument_Editor")

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def save_instrument_data(self) -> bool:
        success = True

        parser = configparser.ConfigParser()

        file_name = os.path.basename(self.rom.path).rsplit('.')[0] + "_instruments.ini"
        if os.path.exists(os.path.dirname(self.rom.path) + '/' + file_name):
            file_name = os.path.dirname(self.rom.path) + '/' + file_name
            parser.read(file_name)
        elif os.path.exists(file_name):
            parser.read(file_name)
        elif os.path.exists("instruments.ini"):
            file_name = "instruments.ini"
            parser.read("instruments.ini")

        if not parser.has_section(f"BANK_{self._bank}"):
            parser.add_section(f"BANK_{self._bank}")

        section = parser[f"BANK_{self._bank}"]

        for i in range(len(self._instruments)):
            # Save envelopes
            for e in range(3):
                address = self._instruments[i].envelope_address[e]
                self.rom.write_bytes(self._bank, address, self._instruments[i].envelope[e])

            # Add name to ini file
            name = self._instruments[i].name
            if name != "(no name)":
                try:
                    section[f"{i}"] = self._instruments[i].name.replace('%', '%%')
                except ValueError:
                    self.app.warningBox("Instrument Editor", f"Invalid instrument name '{name}'.")

        try:
            with open(file_name, "w") as names_file:
                parser.write(names_file, False)
        except IOError as error:
            self.app.warningBox("Instrument Editor", f"Could not write instrument names to file:\n{error.strerror}")

        return success

    # ------------------------------------------------------------------------------------------------------------------

    def save_track_data(self) -> bool:
        success: bool = True

        # Save track name to INI file
        self._save_current_track_title()

        # We will need to re-allocate space for all the tracks in the current bank
        if self._bank == 8:
            track_count = 11

            # "Muted" tracks will point to this address
            muted_address = 0x8639

            pointer_table = 0x8051

            # (start address, size)
            memory_map = [(0x87C7, 1528), (0x8EAA, 1054), (0x9342, 1038), (0x9833, 1419), (0x9EAB, 1036), (0xA35E, 640),
                          (0xA74B, 694), (0xAA52, 720), (0xADC1, 1704), (0xB4FA, 1164), (0xB968, 1562), (0xBFD0, 32)]

        elif self._bank == 9:
            track_count = 4

            muted_address = 0x863C

            pointer_table = 0x8052

            memory_map = [(0x8797, 4124), (0x9840, 78), (0x98D1, 44), (0xAC5A, 200), (0xADB3, 1164), (0xB2DE, 1020),
                          (0x98FD, 14), (0x991B, 138), (0x99A5, 494), (0x9B93, 558)]

        else:
            # Other banks are not supported
            return False

        # Some channels will share the same address between different songs
        # For this reason, we keep track of where has each address been moved to, and keep them in sync
        # (old address, new address, data)
        processed: List[Tuple[int, int, bytearray]] = [(-1, -1, bytearray())]

        for i in range(track_count):

            # Pointers, one per channel
            channel_address: List[int] = []
            for c in range(4):
                if i == self._track_index:
                    # The edited track won't be read from ROM of course. Instead, we generate byte data from it.

                    # Before creating the buffer, we need to calculate the correct value for the rewind point
                    if self._track_data[c][-1].control != TrackDataEntry.REWIND:
                        self.warning(f"Channel {c} does not end with a REWIND element!")
                        loop_position = 0
                        self._track_data.append(TrackDataEntry.new_rewind(0))
                    else:
                        loop_position = self._track_data[c][-1].loop_position

                    # Go through the data from the last element to the first, counting bytes until we reach our target
                    #   element
                    offset: int = 4
                    position: int = len(self._track_data[c])
                    for element in reversed(self._track_data[c]):
                        if position == loop_position:
                            break
                        else:
                            offset -= len(element.raw)
                        position -= 1

                    if offset > 0:
                        offset = 0

                    self._track_data[c][-1].raw = bytearray([0xFF, 00]) + \
                        bytearray(offset.to_bytes(2, "little", signed=True))

                    buffer: bytearray = bytearray()
                    for element in self._track_data[c]:
                        data = element.raw.copy()

                        # Bank 9 subtracts 50 to each instrument's index, so we did when loading the track
                        #   Now we have to reverse that
                        if data[0] == 0xFC and self._bank == 9:
                            data[1] += 50

                        buffer += data

                    # Allocate memory for the current track: discard addresses and re-allocate
                    channel_address.append(-1)

                    # Also read the address from the entry widget to see if this is a "muted" track
                    try:
                        address = self._track_address[c]
                        if address == muted_address:
                            # Make sure this is actually a muted channel, don't just rely on size:
                            #   data should be FC 00 FB 08 FE 40 FF 00 FE FF
                            if len(self._track_data[c]) == 4:
                                if (self._track_data[c][0].raw[0] == 0xFC and
                                        self._track_data[c][1].raw[0] == 0xFB and
                                        self._track_data[c][2].raw[0] == 0xFE and
                                        self._track_data[c][3].raw[0] == 0xFF):
                                    channel_address[c] = muted_address

                    except ValueError:
                        pass

                else:
                    pointer = self.rom.read_word(self._bank, pointer_table + (2 * c) + (8 * i))
                    channel_address.append(pointer)

                    # Buffer all channels
                    buffer: bytearray = bytearray()
                    while 1:
                        command = self.rom.read_byte(self._bank, pointer)
                        buffer.append(command)
                        pointer += 1

                        # One-byte commands
                        if command <= 0xF0 == 0xFB or command == 0xFC or command == 0xFE:
                            buffer.append(self.rom.read_byte(self._bank, pointer))
                            pointer += 1

                        # Three-byte command
                        elif command == 0xFD:
                            buffer += self.rom.read_bytes(self._bank, pointer, 3)
                            pointer += 3

                        # The Rewind command is the last: read its parameters and end the loop
                        elif command == 0xFF:
                            buffer += self.rom.read_bytes(self._bank, pointer, 3)
                            break

                        # Everything else is ignored

                # Now we have data and pointers
                # First, we make sure this isn't a "muted" track
                if channel_address[c] == muted_address:
                    # In this case, we only need to update the pointer table
                    self.rom.write_word(self._bank, pointer_table + (2 * c) + (8 * i), channel_address[c])
                    continue

                # Now let's see if a track with the same address had already been processed
                already_processed = False
                for p in processed:
                    if p[0] != -1 and p[0] == channel_address[c] and p[1] != 0:
                        # A match has been found: let's simply update the pointer
                        channel_address[c] = p[1]
                        already_processed = True

                if not already_processed:
                    # No matches: find the smallest space this would fit into
                    size = len(buffer)
                    chunk: int = -1
                    smallest: int = 65535
                    for m in range(len(memory_map)):
                        difference = memory_map[m][1] - size
                        if difference < 0:
                            # Won't fit
                            continue
                        elif difference == 0:
                            # Perfect fit, stop here
                            chunk = m
                            break
                        else:
                            if difference < smallest:
                                # Best so far, but keep looking
                                smallest = difference
                                chunk = m

                    if chunk == -1:
                        # This channel won't fit anywhere
                        self.error(f"Channel {c} of track {i} does not fit in ROM.")
                        success = False
                    else:
                        # Save this channel to its new address
                        new_address = memory_map[chunk][0]
                        if 0xBFF0 >= new_address >= 0x8000:
                            processed.append((channel_address[c], new_address, buffer))
                        channel_address[c] = new_address

                        # self.info(f"DEBUG: Allocating track {i} channel {c} to: 0x{new_address:04X}.")

                        # Reduce the chunk size and advance its start address
                        memory_map[chunk] = (memory_map[chunk][0] + size, memory_map[chunk][1] - size)

                # Channel has been processed: update the pointer table with its new address
                self.rom.write_word(self._bank, pointer_table + (2 * c) + (8 * i), channel_address[c])

        if success:
            for p in processed:
                if p[1] < 0 or len(p[2]) < 1:
                    continue
                self.info(f"DEBUG: Saving {len(p[2])} bytes to: ${self._bank:02X}:{p[1]:04X}.")
                self.rom.write_bytes(self._bank, p[1], p[2])

        return success

    # ------------------------------------------------------------------------------------------------------------------

    def read_track_data(self, channel: int) -> List[TrackDataEntry]:
        track: List[TrackDataEntry] = []

        address = self._track_address[channel]

        loop_found = False

        if self._bank == 9:
            # Bank 9 subtracts this value from each instrument's index
            instrument_offset = 50
        else:
            instrument_offset = 0

        while not loop_found:
            control_byte = self.rom.read_byte(self._bank, address)
            address = address + 1

            if control_byte == 0xFB:  # FB - VOLUME
                value = self.rom.read_byte(self._bank, address)
                address += 1
                data = TrackDataEntry.new_volume(value)
                # data.raw = bytearray([0xFB, value])

            elif control_byte == 0xFC:  # FC - INSTRUMENT
                value = self.rom.read_byte(self._bank, address) - instrument_offset
                if value < 0:
                    self.warning(f"Invalid instrument index: {value} found.")
                    value = 0
                address += 1
                data = TrackDataEntry.new_instrument(value)
                # data.raw = bytearray([0xFC, value])

            elif control_byte == 0xFD:  # FD - VIBRATO
                triangle_octave = self.rom.read_byte(self._bank, address)
                address += 1

                speed = self.rom.read_byte(self._bank, address)
                address += 1

                factor = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackDataEntry.new_vibrato(triangle_octave < 0xFF, speed, factor)
                # data.raw = bytearray([0xFD, triangle_octave, speed, factor])

            elif control_byte == 0xFE:  # FE - REST
                value = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackDataEntry.new_rest(value)
                # data.raw = bytearray([0xFE, value])

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

                # Calculate item index based on each item's size, counting backwards
                loop_position: int = len(track)  # Start from the end
                byte_count: int = 0
                for element in reversed(track):
                    if byte_count <= offset:
                        break
                    byte_count -= len(element.raw)
                    loop_position -= 1

                if loop_position < 0:
                    loop_position = 0
                data = TrackDataEntry.new_rewind(loop_position)
                data.raw = bytearray([0xFF, 0])
                data.raw += offset.to_bytes(2, "little", signed=True)
                loop_found = True

            elif control_byte >= 0xF0:  # F0-FA - IGNORED
                value = self.rom.read_byte(self._bank, address)
                address += 1

                data = TrackDataEntry(bytearray([value]))

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

                # data.raw = bytearray([index, duration])

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
            instrument_count = 13
            address = [0x8646, 0x8660, 0x867A]

        # Open names file, if there is one
        parser = configparser.ConfigParser()
        file_name = os.path.basename(self.rom.path).rsplit('.')[0] + "_instruments.ini"
        if os.path.exists(os.path.dirname(self.rom.path) + '/' + file_name):
            file_name = os.path.dirname(self.rom.path) + '/' + file_name
            parser.read(file_name)
        elif os.path.exists(file_name):
            parser.read(file_name)
        elif os.path.exists("instruments.ini"):
            file_name = "instruments.ini"
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

            instrument.name = parser.get(f"BANK_{self._bank}", f"{i}", fallback="(no name)")[:24]

            self._instruments.append(instrument)

            # Next instrument
            address[0] += 2
            address[1] += 2
            address[2] += 2

    # ------------------------------------------------------------------------------------------------------------------

    def _update_undo_buttons(self, editor: int) -> None:
        if editor == 0:  # Track Editor
            if len(self._track_undo_count) < 1:
                self.app.disableButton("SE_Button_Undo")
                self.app.setButtonTooltip("SE_Button_Undo", "Nothing to Undo")
            else:
                self.app.enableButton("SE_Button_Undo")
                self.app.setButtonTooltip("SE_Button_Undo", "Undo: " + self._track_undo.get_undo_text())

            if len(self._track_redo_count) < 1:
                self.app.disableButton("SE_Button_Redo")
                self.app.setButtonTooltip("SE_Button_Redo", "Nothing to Redo")
            else:
                self.app.enableButton("SE_Button_Redo")
                self.app.setButtonTooltip("SE_Button_Redo", "Redo: " + self._track_undo.get_redo_text())

        elif editor == 1:  # Instrument Editor
            self.info("Undo/Redo functionality not yet implemented for Instrument Editor.")

        else:
            self.warning(f"Invalid editor index {editor} for _update_undo_buttons.")

    # ------------------------------------------------------------------------------------------------------------------

    def _update_element_info(self, channel: int, element: int) -> None:
        widget = f"SE_List_Channel_{channel}"

        t = self._track_data[channel][element]

        text = f"{element:03X} - {t.raw[0]:02X} - "

        if t.control == TrackDataEntry.CHANNEL_VOLUME:
            text += f"{t.raw[1]:02X} - -- - --"
            description = f"VOL {t.raw[1]:02}"
            bg = colour.DARK_BLUE
            fg = colour.LIGHT_ORANGE

        elif t.control == TrackDataEntry.SELECT_INSTRUMENT:
            text += f"{t.raw[1]:02X} - -- - --\n"
            description = f"INS {self._instruments[t.raw[1]].name[:19]}"
            bg = colour.DARK_ORANGE
            fg = colour.PALE_TEAL

        elif t.control == TrackDataEntry.SET_VIBRATO:
            text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
            description = f"VIB {'O^, ' if t.raw[1] < 0xFF else ''} S:{t.raw[2]}, F:{t.raw[3]}"
            bg = colour.DARK_VIOLET
            fg = colour.PALE_PINK

        elif t.control == TrackDataEntry.REST:
            text += f"{t.raw[1]:02X} - -- - --"
            description = f"REST {t.raw[1]}"
            bg = colour.DARK_OLIVE
            fg = colour.PALE_MAGENTA

        elif t.control == TrackDataEntry.REWIND:
            text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
            description = f"RWD {t.loop_position}"
            bg = colour.DARK_MAGENTA
            fg = colour.PALE_VIOLET

        elif t.control < 0xF0:
            text += f"{t.raw[1]:02X} - -- - --"
            description = f"       {_NOTE_NAMES[t.raw[0]]} {t.raw[1]:02}"
            bg = "#171717"
            fg = colour.PALE_GREEN

        else:
            text += "-- - -- - --"
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
                description = f"VOL {t.raw[1]:02}"
                bg = colour.DARK_BLUE
                fg = colour.LIGHT_ORANGE

            elif t.control == TrackDataEntry.SELECT_INSTRUMENT:
                text += f"{t.raw[1]:02X} - -- - --\n"
                try:
                    description = f"INS {self._instruments[t.raw[1]].name[:19]}"
                except IndexError:
                    self.warning(f"Could not find name for instrument #{t.raw[1]}")
                    description = f"INS #{t.raw[1]:02}"
                bg = colour.DARK_ORANGE
                fg = colour.PALE_TEAL

            elif t.control == TrackDataEntry.SET_VIBRATO:
                text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
                description = f"VIB {'O^, ' if t.raw[1] < 0xFF else ''} S:{t.raw[2]}, F:{t.raw[3]}"
                bg = colour.DARK_VIOLET
                fg = colour.PALE_PINK

            elif t.control == TrackDataEntry.REST:
                text += f"{t.raw[1]:02X} - -- - --"
                description = f"REST {t.raw[1]}"
                bg = colour.DARK_OLIVE
                fg = colour.PALE_MAGENTA

            elif t.control == TrackDataEntry.REWIND:
                text += f"{t.raw[1]:02X} - {t.raw[2]:02X} - {t.raw[3]:02X}"
                description = f"RWD {t.loop_position}"
                bg = colour.DARK_MAGENTA
                fg = colour.PALE_VIOLET

            elif t.control < 0xF0:
                text += f"{t.raw[1]:02X} - -- - --"
                description = f"       {_NOTE_NAMES[t.raw[0]]} {t.raw[1]:02}"
                bg = "#171717"
                fg = colour.PALE_GREEN

            else:
                text += "-- - -- - --"
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

    def instrument_usage(self, instrument_index: int) -> List[str]:
        """
        Parameters
        ----------
        instrument_index: int
            Index of the instrument whose usage statistics we want

        Returns
        -------
        List[str]:
            A list of track names, in the instrument's bank, that contain at least one reference to its index
        """
        tracks: List[str] = []

        pointers = 0x8051 if self._bank == 8 else 0x8052

        if self._bank == 8:
            # Read number of tracks from ROM
            track_count = self.rom.read_byte(0x8, 0x8001)
            offset = 0
        else:
            track_count = 4
            offset = 50  # Bank 9 subtracts this value from instrument indices

        for t in range(track_count):
            # Each track has four channel pointers
            for c in range(4):
                # Get this channel's address
                pointer = pointers + (2 * c) + (4 * t)
                address = self.rom.read_word(self._bank, pointer)
                # Read data, looking for instrument commands
                while 1:
                    value = self.rom.read_byte(self._bank, address)

                    if value == 0xFF:  # REWIND
                        break
                    elif value == 0xFE:  # REST
                        address += 2
                    elif value == 0xFD:  # VIBRATO
                        address += 4
                    elif value == 0xFC:  # INSTRUMENT
                        if self.rom.read_byte(self._bank, address + 1) == instrument_index + offset:
                            # Found a reference, we don't need any more
                            if t < len(self.track_titles[self._bank - 8]):
                                tracks.append(f"{t:02}: '{self.track_titles[self._bank - 8][t]}'")
                            else:
                                tracks.append(f"{t:02}: '(No Name)'")
                            break
                        address += 2
                    elif value == 0xFB:  # VOLUME
                        address += 2
                    elif value < 0xF0:  # Notes
                        address += 2
                    else:  # Anything else
                        address += 1

        return tracks

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

    def instrument_by_name(self, name: str, fallback: int = 0) -> int:
        """
        Parameters
        ----------
        name: str
            Name of the instrument, <u>case sensitive</u>
        fallback: int
            A fallback value if there are no instruments with that name

        Returns
        -------
        int:
            The index of the instrument with the desired name, or the fallback value if not found.
        """
        for i in range(len(self._instruments)):
            if self._instruments[i].name == name:
                return i

        return fallback

    # ------------------------------------------------------------------------------------------------------------------

    def _undo_track_action(self, _event: any = None) -> None:
        if len(self._track_undo_count) < 1:
            self.app.soundError()
            return

        count = self._track_undo_count.pop()
        self._track_redo_count.append(count)
        result = self._track_undo.undo(count)
        # We expect the result to be a channel index
        if len(result) == 1 and result[0] is not None:
            self.track_info(result[0])
        else:
            # Some methods do not return a value, so we don't know which channel was affected
            # Or maybe more than one channel was affected, so we just update everything
            self.track_info(0)
            self.track_info(1)
            self.track_info(2)
            self.track_info(3)

        self._update_undo_buttons(0)

    # ------------------------------------------------------------------------------------------------------------------

    def _redo_track_action(self, _event: any = None) -> None:
        if len(self._track_redo_count) < 1:
            self.app.soundError()
            return

        count = self._track_redo_count.pop()
        self._track_undo_count.append(count)
        result = self._track_undo.redo(count)

        if len(result) == 1 and result[0] is not None:
            self.track_info(result[0])
        else:
            self.track_info(0)
            self.track_info(1)
            self.track_info(2)
            self.track_info(3)

        self._update_undo_buttons(0)

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

    def _delete_track_element(self, channel: int, entry: int) -> int:
        """
        Removes an element from a channel.
        Parameters
        ----------
        channel: int
            Channel number(0-3)
        entry: int
            Index of the element to be removed
        Returns
        -------
        The channel index.
        """
        self._track_data[channel].pop(entry)
        return channel

    # ------------------------------------------------------------------------------------------------------------------

    def _create_track_element(self, channel: int, position: int, element_type: int,
                              values: Tuple[Union[bool, int]]) -> int:
        if element_type == TrackDataEntry.CHANNEL_VOLUME:
            data = TrackDataEntry.new_volume(values[0])
        elif element_type == TrackDataEntry.SELECT_INSTRUMENT:
            data = TrackDataEntry.new_instrument(values[0])
        elif element_type == TrackDataEntry.SET_VIBRATO:
            data = TrackDataEntry.new_vibrato(values[0], values[1], values[2])
        elif element_type == TrackDataEntry.REST:
            data = TrackDataEntry.new_rest(values[0])
        elif element_type == TrackDataEntry.REWIND:
            data = TrackDataEntry.new_rewind()
        elif element_type < 0xF0:
            data = TrackDataEntry.new_note(values[0], values[1])
        else:
            data = TrackDataEntry(bytearray(values[0]))

        self._track_data[channel].insert(position, data)

        return channel

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
        # Undoable action: change note value / duration
        if widget == "SE_Apply_Note" or widget == "SE_Note_Value" or widget == "SE_Note_Duration":  # ------------------
            # Get selected element
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control > 0xEF:
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

            # DO: change value (channel, index, [value, duration])
            # UNDO: change value (channel, index, [old value, old duration])
            channel = self._selected_channel
            index = self._selected_element
            old_values = element.raw.copy()
            self._track_undo(self._change_element_value, (channel, index, bytearray([value, duration])),
                             (channel, index, old_values), text=f"Modify note (Channel {channel})")
            self._track_undo_count.append(1)
            self._track_redo_count = []

            # Update UI
            self._update_undo_buttons(0)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

            self._unsaved_changes_track = True

        # Undoable action
        elif widget == "SE_Apply_Volume" or widget == "SE_Entry_Volume":    # ------------------------------------------
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

            # DO: change value (channel, index, [new value])
            # UNDO: change value (channel, index, [old value])
            channel = self._selected_channel
            index = self._selected_element
            old_value = element.raw[1]
            self._track_undo(self._change_element_value, (channel, index, bytearray([value])),
                             (channel, index, bytearray([old_value])), text=f"Volume (Channel {channel})")
            self._track_undo_count.append(1)
            self._track_redo_count = []

            # Update UI
            self._update_undo_buttons(0)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

            self._unsaved_changes_track = True

        # Undoable action
        elif widget == "SE_Select_Instrument":  # ----------------------------------------------------------------------
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.SELECT_INSTRUMENT:
                return

            value = self.app.getListBoxPos(widget)
            if len(value) > 0:
                # element.set_instrument(value[0])
                # DO: change value (channel, index, [new value])
                # UNDO: change value (channel, index, [old value])
                channel = self._selected_channel
                index = self._selected_element
                old_value = element.raw[1]
                self._track_undo(self._change_element_value, (channel, index, bytearray([value[0]])),
                                 (channel, index, bytearray([old_value])),
                                 text=f"Change instrument (Channel {channel})")
                self._track_undo_count.append(1)
                self._track_redo_count = []

                # Update undo/redo buttons
                self._update_undo_buttons(0)
                # Update just this entry
                self._update_element_info(self._selected_channel, self._selected_element)
                # Re-select it
                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

                self._unsaved_changes_track = True

        # Undoable action
        elif widget == "SE_Apply_Rest" or widget == "SE_Rest_Duration":     # ------------------------------------------
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

            # element.set_rest(value)
            # DO: change value (channel, index, [new value])
            # UNDO: change value (channel, index, [old value])
            channel = self._selected_channel
            index = self._selected_element
            old_value = element.raw[1]
            self._track_undo(self._change_element_value, (channel, index, bytearray([value])),
                             (channel, index, bytearray([old_value])), text=f"Rest duration (Channel {channel})")
            self._track_undo_count.append(1)
            self._track_redo_count = []

            # Update UI
            self._update_undo_buttons(0)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

            self._unsaved_changes_track = True

        # Undoable action
        elif widget == "SE_Apply_Vibrato" or widget == "SE_Vibrato_Speed" or widget == "SE_Vibrato_Factor":     # ------
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
            # element.set_vibrato(octave, speed, factor)

            # DO: change value (channel, index, new values)
            # UNDO: change value (channel, index, old values)
            channel = self._selected_channel
            index = self._selected_element
            new_values = bytearray([0 if octave else 0xFF, speed, factor])
            old_values = element.raw[1:]
            self._track_undo(self._change_element_value, (channel, index, new_values),
                             (channel, index, old_values), text=f"Set vibrato (Channel {channel})")
            self._track_undo_count.append(1)
            self._track_redo_count = []

            # Update UI
            self._update_undo_buttons(0)

            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

            self._unsaved_changes_track = True

        # Undoable action
        elif widget == "SE_Triangle_Octave":    # ----------------------------------------------------------------------
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.SET_VIBRATO:
                return

            octave = self.app.getCheckBox("SE_Triangle_Octave")
            speed = element.raw[2]
            factor = element.raw[3]

            # element.set_vibrato(octave, speed, factor)
            # DO: change value (channel, index, new values)
            # UNDO: change value (channel, index, old values)
            channel = self._selected_channel
            index = self._selected_element
            new_values = bytearray([0 if octave else 0xFF, speed, factor])
            old_values = element.raw[1:]
            self._track_undo(self._change_element_value, (channel, index, new_values),
                             (channel, index, old_values), text=f"Set vibrato (Channel {channel})")
            self._track_undo_count.append(1)
            self._track_redo_count = []

            # Update UI
            self._update_undo_buttons(0)
            self._update_element_info(self._selected_channel, self._selected_element)
            self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

            self._unsaved_changes_track = True

        # Undoable action
        elif widget == "SE_Apply_Rewind" or widget == "SE_Rewind_Value":    # ------------------------------------------
            element, selection = self._get_selected_element()

            if self._selected_element < 0 or element.control != TrackDataEntry.REWIND:
                return

            try:
                value = int(self.app.getEntry("SE_Rewind_Value"), 10)
                if value < 0 or value > len(self._track_data[self._selected_channel]):
                    self.app.soundError()
                    self.app.getEntryWidget("SE_Rewind_Value").selection_range(0, tkinter.END)

                else:
                    self._track_undo(element.set_rewind, (value,),
                                     (element.loop_position,), text=f"Set rewind (Channel {self._selected_channel})")
                    self._track_undo_count.append(1)
                    self._track_redo_count = []
                    element.loop_position = value
                    self._unsaved_changes_track = True

            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Rewind_Value").selection_range(0, tkinter.END)

            finally:
                # Update UI
                self._update_undo_buttons(0)
                self._update_element_info(self._selected_channel, self._selected_element)
                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection, callFunction=False)

        # This just shows the element type selection buttons
        elif widget == "SE_Change_Element":     # ----------------------------------------------------------------------
            if self._selected_channel > -1 and self._selected_element > -1:
                self.app.selectFrame("SE_Stack_Editing", 7, callFunction=False)

        # TODO Support multiple selections?
        # Undoable actions: change element type
        # DO: change type (channel, index, new type)
        # UNDO: change type (channel, index, old type, old values)
        elif widget[:13] == "SE_Change_To_":

            channel = self._selected_channel
            index = self._selected_element

            # Get the old type and values
            element = self._track_data[channel][index]
            old_type = element.raw[0]
            old_values = element.raw[1:]

            if widget == "SE_Change_To_Note":
                new_type = 0

            elif widget == "SE_Change_To_Volume":
                new_type = TrackDataEntry.CHANNEL_VOLUME

            elif widget == "SE_Change_To_Instrument":
                new_type = TrackDataEntry.SELECT_INSTRUMENT

            elif widget == "SE_Change_To_Vibrato":
                new_type = TrackDataEntry.SET_VIBRATO

            elif widget == "SE_Change_To_Rest":
                new_type = TrackDataEntry.REST

            elif widget == "SE_Change_To_Rewind":
                if not self.app.yesNoBox("Change Track Element",
                                         "Are you sure you want to change this entry to a REWIND element?\n" +
                                         "This will permanently erase everything past this element.",
                                         "Track_Editor"):
                    return
                new_type = TrackDataEntry.REWIND
            else:
                new_type = 0xF0

            # self._change_element_type(self._selected_channel, self._selected_element, new_type)
            self._track_undo(self._change_element_type, (channel, index, new_type),
                             (channel, index, old_type, old_values), text=f"Change element type (Channel {channel})")
            self._track_undo_count.append(1)
            self._track_redo_count = []
            self._update_undo_buttons(0)

        # Undoable action: increase the duration of a group of notes
        elif widget == "SE_Duration_Up":    # --------------------------------------------------------------------------
            channel = self._selected_channel
            selection = self.app.getListBoxPos(f"SE_List_Channel_{channel}")

            # Some items may not be notes, others may be already at max duration, so we need to create a new
            #   selection that only contains items we can actually modify
            final_selection: List[int] = []

            if len(selection) > 0:
                sorted_selection = list(set([i >> 1 for i in selection]))
                sorted_selection.sort(reverse=True)
                for index in sorted_selection:
                    element = self._track_data[channel][index]
                    # Only add notes with duration less than 255 to our final selection
                    if element.raw[0] < 0xF0 and element.raw[1] < 0xFF:
                        final_selection.append(index)

            # Now we can process these "filtered" items
            for index in final_selection:
                element = self._track_data[channel][index]

                # Create undo action
                old_values = element.raw.copy()
                new_values = bytearray([old_values[0], old_values[1] + 1])
                self._track_undo(self._change_element_value, (channel, index, new_values),
                                 (channel, index, old_values), text=f"Increase note duration (Channel {channel})")
                # Update this element's entry in the list box and (re-)select it
                self._update_element_info(channel, index)
                self.app.selectListItemAtPos(f"SE_List_Channel_{channel}", index << 1, callFunction=False)

            if len(final_selection) > 0:
                self._track_undo_count.append(len(final_selection))
                self._track_redo_count = []
                # Update undo buttons
                self._update_undo_buttons(0)
                # (Re-)select these items

        # Undoable action: decrease the duration of a group of notes
        elif widget == "SE_Duration_Down":  # --------------------------------------------------------------------------
            channel = self._selected_channel
            selection = self.app.getListBoxPos(f"SE_List_Channel_{channel}")

            # Some items may not be notes, others may be already at minimum duration, so we need to create a new
            #   selection that only contains items we can actually modify
            final_selection: List[int] = []

            if len(selection) > 0:
                sorted_selection = list(set([i >> 1 for i in selection]))
                sorted_selection.sort(reverse=True)
                for index in sorted_selection:
                    element = self._track_data[channel][index]
                    # Only add notes with duration more than 0 to our final selection
                    if element.raw[0] < 0xF0 and element.raw[1] > 0:
                        final_selection.append(index)

            # Now we can process these "filtered" items
            for index in final_selection:
                element = self._track_data[channel][index]

                # Create undo action
                old_values = element.raw.copy()
                new_values = bytearray([old_values[0], old_values[1] - 1])
                self._track_undo(self._change_element_value, (channel, index, new_values),
                                 (channel, index, old_values), text=f"Decrease note duration (Channel {channel})")
                # Update this element's entry in the list box and (re-)select it
                self._update_element_info(channel, index)
                self.app.selectListItemAtPos(f"SE_List_Channel_{channel}", index << 1, callFunction=False)

            if len(final_selection) > 0:
                self._track_undo_count.append(len(final_selection))
                self._track_redo_count = []
                # Update undo buttons
                self._update_undo_buttons(0)
                # (Re-)select these items

        # Undoable action: increase the pitch of a group of notes one semitone
        elif widget == "SE_Semitone_Up":    # --------------------------------------------------------------------------
            channel = self._selected_channel
            selection = self.app.getListBoxPos(f"SE_List_Channel_{channel}")

            # Some items may not be notes, others may be already the highest note, so we need to create a new
            #   selection that only contains items we can actually modify
            final_selection: List[int] = []
            if len(selection) > 0:
                sorted_selection = list(set([i >> 1 for i in selection]))
                sorted_selection.sort(reverse=True)
                for index in sorted_selection:
                    element = self._track_data[channel][index]
                    # Only add notes with duration higher than 0 to our final selection
                    if element.raw[0] < len(_NOTE_NAMES):
                        final_selection.append(index)

            # Now we can process these "filtered" items
            for index in final_selection:
                element = self._track_data[channel][index]

                # Make sure it's within the range of possible notes
                old_values = element.raw.copy()
                new_values = bytearray([old_values[0] + 1, old_values[1]])

                if new_values[0] < len(_NOTE_NAMES):
                    # Create undo action
                    self._track_undo(self._change_element_value, (channel, index, new_values),
                                     (channel, index, old_values), text=f"Increase note pitch (Channel {channel})")
                    # Update this element's entry in the list box and (re-)select it
                    self._update_element_info(channel, index)
                    self.app.selectListItemAtPos(f"SE_List_Channel_{channel}", index << 1, callFunction=False)

            if len(final_selection) > 0:
                self._track_undo_count.append(len(final_selection))
                self._track_redo_count = []
                # Update undo buttons
                self._update_undo_buttons(0)
                # (Re-)select these items

        # Undoable action: decrease the pitch of a group of notes one semitone
        elif widget == "SE_Semitone_Down":      # ----------------------------------------------------------------------
            channel = self._selected_channel
            selection = self.app.getListBoxPos(f"SE_List_Channel_{channel}")

            # Some items may not be notes, others may be already the lowest note, so we need to create a new
            #   selection that only contains items we can actually modify
            final_selection: List[int] = []
            if len(selection) > 0:
                sorted_selection = list(set([i >> 1 for i in selection]))
                sorted_selection.sort(reverse=True)
                for index in sorted_selection:
                    element = self._track_data[channel][index]
                    # Only add notes with duration more than 0 to our final selection
                    if 0 < element.raw[0] < 0xF0:
                        final_selection.append(index)

            # Now we can process these "filtered" items
            for index in final_selection:
                element = self._track_data[channel][index]

                old_values = element.raw.copy()

                # Don't change notes that are already the lowest possible
                if old_values[0] > 0:
                    new_values = bytearray([old_values[0] - 1, old_values[1]])

                    # Create undo action
                    self._track_undo(self._change_element_value, (channel, index, new_values),
                                     (channel, index, old_values), text=f"Decrease note pitch (Channel {channel})")
                    # Update this element's entry in the list box and (re-)select it
                    self._update_element_info(channel, index)
                    self.app.selectListItemAtPos(f"SE_List_Channel_{channel}", index << 1, callFunction=False)

            if len(final_selection) > 0:
                self._track_undo_count.append(len(final_selection))
                self._track_redo_count = []
                # Update undo buttons
                self._update_undo_buttons(0)
                # (Re-)select these items

        elif widget == "SE_Cancel_Change_Element":
            # Simply re-select the current selection
            self._element_selection(None, self._selected_channel)

        else:
            self.info(f"Unimplemented callback for Element widget: '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _change_element_type(self, channel: int, element_index: int, new_type: int,
                             values: Tuple[Union[int, bool]] = None) -> int:
        try:
            element = self._track_data[channel][element_index]
            element.change_type(new_type, values)
            self._update_element_info(channel, element_index)
            self.app.selectListItemAtPos(f"SE_List_Channel_{channel}", element_index << 1,
                                         callFunction=True)
            self._element_selection(None, channel)

            # self._recalculate_rewind_point(channel)
            # This will be done before saving to ROM

            # If this is now a rewind point, delete everything that comes after that
            if new_type == TrackDataEntry.REWIND:
                self._track_data[channel] = self._track_data[channel][:element_index + 1]
                self.track_info(channel)
            else:
                self._update_element_info(channel, len(self._track_data[channel]) - 1)

            self._unsaved_changes_track = True

            return channel

        except IndexError:
            self.app.soundError()
            return channel

    # ------------------------------------------------------------------------------------------------------------------

    def _change_element_value(self, channel: int, element_index: int, new_values: bytearray) -> int:
        try:
            element = self._track_data[channel][element_index]

            if element.control < 0xF0:
                element.set_note(new_values[0], new_values[1])
            else:
                raw = element.raw[:1] + new_values
                self._track_data[channel][element_index] = TrackDataEntry(raw)

        except IndexError:
            self.app.soundError()
        finally:
            return channel

    # ------------------------------------------------------------------------------------------------------------------

    def _element_selection(self, _event: any, channel: int) -> None:
        """
        Callback on left mouse button release on a channel's list
        """
        self._selected_channel = channel
        selection = self.app.getListBoxPos(f"SE_List_Channel_{self._selected_channel}")

        if len(selection) < 1:  # Nothing selected
            self.app.firstFrame("SE_Stack_Editing", callFunction=False)
            self.app.setLabel("SE_Selection_Info", "Channel - Element -")
        elif len(selection) > 1:  # Multiple selection
            self.app.lastFrame("SE_Stack_Editing", callFunction=False)
            # This will point to the first element selected
            self._selected_element = selection[0] >> 1
            self.app.setLabel("SE_Selection_Info",
                              f"Channel {self._selected_channel} Element (multiple)")
        else:
            # Get the index of the selected element, keeping in mind that each occupies two lines
            element = self._track_data[channel][selection[0] >> 1]
            self._selected_element = selection[0] >> 1

            self.app.setLabel("SE_Selection_Info",
                              f"Channel {self._selected_channel} Element {self._selected_element:03X}")

            # Get the type of this element and choose an appropriate frame
            if element.control < 0xF0:
                self.app.selectFrame("SE_Stack_Editing", 2, callFunction=False)

                self.app.clearEntry("SE_Note_Value", callFunction=False, setFocus=True)
                self.app.clearEntry("SE_Note_Duration", callFunction=False, setFocus=False)

                self.app.setEntry("SE_Note_Value", _NOTE_NAMES[element.note.index], callFunction=False)
                self.app.setEntry("SE_Note_Duration", f"{element.note.duration}", callFunction=False)

                self.app.getEntryWidget("SE_Note_Value").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            elif element.control == TrackDataEntry.CHANNEL_VOLUME:
                self.app.selectFrame("SE_Stack_Editing", 1, callFunction=False)

                self.app.clearEntry("SE_Entry_Volume", callFunction=False, setFocus=True)
                self.app.setEntry("SE_Entry_Volume", element.raw[1], callFunction=False)
                self.app.getEntryWidget("SE_Entry_Volume").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            elif element.control == TrackDataEntry.REST:
                self.app.selectFrame("SE_Stack_Editing", 3, callFunction=False)

                self.app.clearEntry("SE_Rest_Duration", callFunction=False, setFocus=True)
                self.app.setEntry("SE_Rest_Duration", element.raw[1], callFunction=False)
                self.app.getEntryWidget("SE_Rest_Duration").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            elif element.control == TrackDataEntry.SET_VIBRATO:
                self.app.selectFrame("SE_Stack_Editing", 4, callFunction=False)

                self.app.setCheckBox("SE_Triangle_Octave", element.raw[1] < 0xFF, callFunction=False)

                self.app.clearEntry("SE_Vibrato_Speed", callFunction=False, setFocus=True)
                self.app.clearEntry("SE_Vibrato_Factor", callFunction=False, setFocus=False)

                self.app.setEntry("SE_Vibrato_Speed", element.raw[2], callFunction=False)
                self.app.setEntry("SE_Vibrato_Factor", element.raw[3], callFunction=False)

                self.app.getEntryWidget("SE_Vibrato_Speed").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            elif element.control == TrackDataEntry.SELECT_INSTRUMENT:
                self.app.selectFrame("SE_Stack_Editing", 5, callFunction=False)
                self.app.selectListItemAtPos("SE_Select_Instrument", element.raw[1], callFunction=False)

            elif element.control == TrackDataEntry.REWIND:
                self.app.selectFrame("SE_Stack_Editing", 6, callFunction=False)

                self.app.clearEntry("SE_Rewind_Value", callFunction=False, setFocus=True)
                self.app.setEntry("SE_Rewind_Value", element.loop_position, callFunction=False)
                self.app.getEntryWidget("SE_Rewind_Value").selection_range(0, tkinter.END)

                self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}",
                                             selection[0], callFunction=False)

            else:
                self.app.firstFrame("SE_Stack_Editing", callFunction=False)

            # Highlight the selected channel
            self._track_input(f"SE_Select_Channel_{self._selected_channel}")

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
            self._track_input(f"SE_Delete_Element_{self._selected_channel}")
            return

        if len(selection) > 1:
            # Multiple-selection-only keys
            return

        else:
            # Single-selection-only keys
            return

    # ------------------------------------------------------------------------------------------------------------------

    def _element_insert_new(self, channel: int, position: int, element_type: int, values: Tuple) -> None:
        # DO: create element (channel, position, type, values)
        self._track_undo(self._create_track_element, (channel, position, element_type, values),
                         # UNDO: delete element (channel, position)
                         (channel, position), self._delete_track_element,
                         text=f"Insert new element (Channel {channel})")
        self._track_undo_count.append(1)
        self._track_redo_count = []
        self._update_undo_buttons(0)

        # Update UI
        self.track_info(channel)
        self.app.selectListItemAtPos(f"SE_List_Channel_{channel}", position << 1, callFunction=False)
        self._element_selection(None, channel)

        self._unsaved_changes_track = True

    # ------------------------------------------------------------------------------------------------------------------

    def _element_right_click(self, event: any, channel: int) -> None:
        # This is the position in the track, which is half the position in the list
        position = event.widget.nearest(event.y) >> 1

        # Copy the previous note if any, or use default values below
        value = 30
        duration = 7
        for e in reversed(self._track_data[channel][:position]):
            if e.control < 0xF0:
                value = e.note.index
                duration = e.note.duration
                break

        self._element_insert_new(channel, position, value, (value, duration))

    # ------------------------------------------------------------------------------------------------------------------

    def _track_input(self, widget: str) -> None:
        if widget == "SE_Button_Apply":     # --------------------------------------------------------------------------
            if not self.save_track_data():
                self.app.errorBox("Save Track Data", "Error saving track data. This usually means the current\n" +
                                  "song is too large to be contained in ROM.\nTry again after reducing its size.",
                                  "Track_Editor")
            else:
                self._unsaved_changes_track = False
                self.close_track_editor()

        elif widget == "SE_Button_Cancel":  # --------------------------------------------------------------------------
            self.close_track_editor()

        elif widget == "SE_Button_Info":    # --------------------------------------------------------------------------
            self.show_track_info()

        elif widget == "SE_Button_Rewind":      # ----------------------------------------------------------------------
            self.app.selectListItemAtPos("SE_List_Channel_3", 0, callFunction=False)
            self.app.selectListItemAtPos("SE_List_Channel_2", 0, callFunction=False)
            self.app.selectListItemAtPos("SE_List_Channel_1", 0, callFunction=False)
            self.app.selectListItemAtPos("SE_List_Channel_0", 0, callFunction=False)
            self._selected_channel = 0
            self._selected_element = 0
            self.track_info(0)

        elif widget == "SE_Play_Stop":  # ------------------------------------------------------------------------------
            if self._play_thread.is_alive():
                self.stop_playback()
                self.app.setButtonImage(widget, "res/stop_play.gif")

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

                self.start_playback(True)
                self.app.setButtonImage(widget, "res/stop.gif")

        elif widget == "SE_Play_Seek":  # ------------------------------------------------------------------------------
            if not self._play_thread.is_alive():
                # Leaving multiple selection active during playback messes up the interface
                self.app.setListBoxMulti(f"SE_List_Channel_0", multi=False)
                self.app.setListBoxMulti(f"SE_List_Channel_1", multi=False)
                self.app.setListBoxMulti(f"SE_List_Channel_2", multi=False)
                self.app.setListBoxMulti(f"SE_List_Channel_3", multi=False)
                self.app.setListBoxGroup(f"SE_List_Channel_0", group=True)
                self.app.setListBoxGroup(f"SE_List_Channel_1", group=True)
                self.app.setListBoxGroup(f"SE_List_Channel_2", group=True)
                self.app.setListBoxGroup(f"SE_List_Channel_3", group=True)
                self.start_playback(True, seek=True)
                self.app.setButtonImage("SE_Play_Stop", "res/stop.gif")

        elif widget == "SE_Button_Reload":  # --------------------------------------------------------------------------
            if not self.app.yesNoBox("Reload from ROM", "Are you sure you want to reload all channels from ROM?\n" +
                                     "This operation cannot be undone.", "Track_Editor"):
                return

            # Re-read pointers from ROM
            address = (self._track_index << 3) + 0x8051 if self._bank == 8 else 0x8052
            for t in range(4):
                self._track_address[t] = self.rom.read_word(self._bank, address)
                address += 2

            self._track_undo.clear()
            self._track_undo_count = []
            self._track_redo_count = []

            self.read_track_data(0)
            self.track_info(0)
            self.read_track_data(1)
            self.track_info(1)
            self.read_track_data(2)
            self.track_info(2)
            self.read_track_data(3)
            self.track_info(3)

            self._unsaved_changes_track = False

        elif widget[:18] == "SE_Reload_Channel_":   # ------------------------------------------------------------------
            channel = int(widget[-1], 10)
            try:
                address = int(self.app.getEntry(f"SE_Channel_Address_{channel}"), 16)
                self._track_address[channel] = address
            except ValueError:
                self.app.getEntryWidget(f"SE_Channel_Address_{channel}").selection_range(0, tkinter.END)
                self.app.soundError()
                return

            if not self.app.yesNoBox("Reload from ROM", f"Are you sure you want to reload channel {channel} from " +
                                                        f"bank {self._bank} address 0x{address:04X}?\n" +
                                                        "This operation cannot be undone.", "Track_Editor"):
                return

            self._track_undo.clear()
            self._track_undo_count = []
            self._track_redo_count = []

            self.read_track_data(channel)
            self.track_info(channel)

            self._unsaved_changes_track = True

        elif widget == "SE_Button_Import":  # --------------------------------------------------------------------------
            path = self._settings.get("last music import path")
            file_name = self.app.openBox("Import track data", path,
                                         [("Ultima Exodus binary files", "*.bin"),
                                          ("FamiStudio text files", "*.txt"),
                                          ("All Files", "*.*")],
                                         asFile=False, parent="Track_Editor", multiple=False)
            if file_name != "":
                self._settings.set("last music import path", os.path.dirname(file_name))
                # Choose type of import depending on the extension
                if file_name.rsplit('.')[-1].lower() == "txt":
                    self._read_famistudio_text(file_name)
                else:
                    self._read_track_from_file(file_name)

                # Not undoable: clear undo stack
                self._track_undo.clear()
                self._track_undo_count = []
                self._track_redo_count = []
                self._update_undo_buttons(0)

                self._unsaved_changes_track = True

        elif widget == "SE_Button_Export":  # --------------------------------------------------------------------------
            path = self._settings.get("last music import path")
            file_name = self.app.saveBox("Export track data", "", path, "*.bin",
                                         [("Ultima Exodus binary files", "*.bin"),
                                          ("FamiStudio text files", "*.txt"),
                                          ("All Files", "*.*")],
                                         asFile=False, parent="Track_Editor")
            if file_name != "":
                self._settings.set("last music import path", os.path.dirname(file_name))
                # Choose type of import depending on the extension
                if file_name.rsplit('.')[-1].lower() == "txt":
                    self.warning("NOT IMPLEMENTED")
                    return
                else:
                    self._save_track_to_file(file_name)

        elif widget == "SE_Button_Undo":    # --------------------------------------------------------------------------
            self._undo_track_action()

        elif widget == "SE_Button_Redo":    # --------------------------------------------------------------------------
            self._redo_track_action()

        elif widget == "SE_Apply_Type_Selection":   # ------------------------------------------------------------------
            # Get element type
            selected_type = self._get_selection_index("SE_Select_Type")
            types = [TrackDataEntry.CHANNEL_VOLUME, TrackDataEntry.SELECT_INSTRUMENT, TrackDataEntry.SET_VIBRATO,
                     TrackDataEntry.REST, 0, -1]
            selected_type = types[selected_type]
            # Gather a list of indices for all elements matching the desired type
            selected_elements: List[int] = []
            i = 0
            for e in self._track_data[self._selected_channel]:
                if selected_type == -1 and 0xF0 <= e.raw[0] < 0xFB:
                    selected_elements.append(i)
                elif selected_type < 0xF0 and e.raw[0] < 0xF0:
                    selected_elements.append(i)
                elif e.control == selected_type:
                    selected_elements.append(i)

                i += 1

            w = self.app.getListBoxWidget(f"SE_List_Channel_{self._selected_channel}")
            # Deselect everything first
            w.selection_clear(0, tkinter.END)
            for e in selected_elements:
                # Add these indices to the current selection
                w.selection_set(e << 1)

            if len(selected_elements) > 0:
                self._selected_element = selected_elements[0]
                self.app.lastFrame("SE_Stack_Editing")

            self._unsaved_changes_track = True

        elif widget == "SE_Clear_Selection":    # ----------------------------------------------------------------------
            self.app.deselectAllListItems(f"SE_List_Channel_{self._selected_channel}")
            self._element_selection(None, self._selected_channel)

        elif widget[:17] == "SE_Clear_Channel_":    # ------------------------------------------------------------------
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

            # Not undoable: clear the undo stack
            self._track_undo.clear()
            self._track_undo_count = []
            self._track_redo_count = []
            self._update_undo_buttons(0)

            # Clear channel by creating a new one with minimal elements
            self._track_data[channel] = []
            self._track_data[channel].append(TrackDataEntry.new_instrument(0))
            self._track_data[channel].append(TrackDataEntry.new_volume(0))
            self._track_data[channel].append(TrackDataEntry.new_rest(7))
            self._track_data[channel].append(TrackDataEntry.new_rewind(0))

            # Change address to the default "muted track" one
            self.app.clearEntry(f"SE_Channel_Address_{channel}", callFunction=False, setFocus=False)
            address = 0x8639 if self._bank == 8 else 0x863C
            self.app.setEntry(f"SE_Channel_Address_{channel}", f"0x{address:04X}", callFunction=False)
            self._track_address[channel] = address

            # Update list
            self.track_info(channel)
            self.app.selectListItemAtPos(f"SE_List_Channel_{channel}", 0, callFunction=True)

            self._unsaved_changes_track = True

        # Undoable action
        # DO: delete element (channel, index)
        # UNDO: create element (channel, index, type, values)
        elif widget[:18] == "SE_Delete_Element_":   # ------------------------------------------------------------------
            channel = self._selected_channel
            selection = self.app.getListBoxPos(f"SE_List_Channel_{channel}")

            if len(selection) > 0:
                sorted_selection = list(set([i >> 1 for i in selection]))
                sorted_selection.sort(reverse=True)
                for index in sorted_selection:

                    # We need to know what the deleted element was if we want to be able to undo this action
                    deleted = self._track_data[channel][index]
                    if (deleted.control == TrackDataEntry.CHANNEL_VOLUME or
                            deleted.control == TrackDataEntry.SELECT_INSTRUMENT or
                            deleted.control == TrackDataEntry.REWIND or
                            deleted.control == TrackDataEntry.REST):

                        values = [deleted.raw[1]]

                    elif deleted.control == TrackDataEntry.SET_VIBRATO:
                        values = [deleted.raw[1] < 0xFF, deleted.raw[2], deleted.raw[3]]

                    elif deleted.control < 0xF0:
                        values = [deleted.note.index, deleted.note.duration]

                    else:
                        values = deleted.raw[0]

                    # DO
                    self._track_undo(self._delete_track_element, (channel, index),
                                     # UNDO
                                     (channel, index, deleted.control, values), self._create_track_element,
                                     text=f"Delete elements (Channel {channel})")

                    # self._delete_track_element(self._selected_channel, entry >> 1)

                self._track_undo_count.append(len(sorted_selection))
                self._update_undo_buttons(0)

                # Show updated elements list
                self.track_info(self._selected_channel)
                # Select the item above the first one that was selected
                if selection[0] < len(self._track_data[self._selected_channel]):
                    self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", selection[0])
                else:
                    self.app.selectListItemAtPos(f"SE_List_Channel_{self._selected_channel}", 0)

                self._unsaved_changes_track = True

        elif widget == "SE_Select_From" or widget == "SE_Select_To" or widget == "SE_Apply_Notes_Selection":    # ------
            # Get and validate to/from note index
            from_note = self.app.getEntry("SE_Select_From").upper()
            to_note = self.app.getEntry("SE_Select_To").upper()
            if len(from_note) < 3:
                from_note += ' '
            if len(to_note) < 3:
                to_note += ' '

            try:
                from_value = _NOTE_NAMES.index(from_note)
            except IndexError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Select_From").slection_range(0, tkinter.END)
                return

            try:
                to_value = _NOTE_NAMES.index(to_note)
            except IndexError:
                self.app.soundError()
                self.app.getEntryWidget("SE_Select_From").slection_range(0, tkinter.END)
                return

            # Select all note events with those values
            list_box = f"SE_List_Channel_{self._selected_channel}"
            for e in range(len(self._track_data[self._selected_channel])):
                if from_value <= self._track_data[self._selected_channel][e].raw[0] <= to_value:
                    self.app.selectListItemAtPos(list_box, e << 1, callFunction=False)

            self._element_selection(None, self._selected_channel)

        elif widget[:16] == "SE_Insert_Above_":     # ------------------------------------------------------------------
            channel = int(widget[-1], 10)

            # This is the position in the track, which is half the position in the list
            try:
                position = self.app.getListBoxPos(f"SE_List_Channel_{channel}")[0] >> 1
            except IndexError:
                # No selection
                return

            # Copy the previous note if any, or use default values below
            value = 30
            duration = 7
            for e in reversed(self._track_data[channel][:position]):
                if e.control < 0xF0:
                    value = e.note.index
                    duration = e.note.duration
                    break

            self._element_insert_new(channel, position, value, (value, duration))

        elif widget[:16] == "SE_Insert_Below_":     # ------------------------------------------------------------------
            channel = int(widget[-1], 10)

            # This is the position in the track, which is half the position in the list
            try:
                position = (self.app.getListBoxPos(f"SE_List_Channel_{channel}")[0] >> 1) + 1
            except IndexError:
                # No selection
                return

            # Copy the previous note if any, or use default values below
            value = 30
            duration = 7
            for e in reversed(self._track_data[channel][:position]):
                if e.control < 0xF0:
                    value = e.note.index
                    duration = e.note.duration
                    break

            self._element_insert_new(channel, position, value, (value, duration))

        elif widget[:18] == "SE_Select_Channel_":   # ------------------------------------------------------------------
            channel = int(widget[-1], 10)

            # Highlight this and un-highlight the others
            for i in range(4):
                self.app.button(f"SE_Select_Channel_{i}", bg=colour.DARK_NAVY if i != channel else colour.MEDIUM_GREEN)
            self._selected_channel = channel

        else:   # ------------------------------------------------------------------------------------------------------
            self.info(f"Unimplemented callback for Track widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _instruments_input(self, widget: str) -> None:
        if widget == "IE_Button_Apply":     # --------------------------------------------------------------------------
            self.save_instrument_data()
            self._unsaved_changes_instrument = False
            self.close_instrument_editor()

        elif widget == "IE_Button_Import":  # --------------------------------------------------------------------------
            self.stop_playback()
            path = self._settings.get("last music import path")
            file_name = self.app.openBox("Import instrument data", path,
                                         [("Ultima Exodus binary files", "*.bin"),
                                          ("All Files", "*.*")],
                                         asFile=False, parent="Track_Editor")
            if file_name != "":
                self._settings.set("last music import path", os.path.dirname(file_name))
                if self.import_instrument_data(file_name):
                    self.app.setStatusbar("Instrument data loaded from file")

            # Refresh UI
            instruments_list: List[str] = []
            for i in range(len(self._instruments)):
                instruments_list.append(f"{i:02X} {self._instruments[i].name}")
            self.app.clearListBox("IE_List_Instrument", callFunction=False)
            self.app.addListItems("IE_List_Instrument", instruments_list, select=False)
            self.app.getListBoxWidget("IE_List_Instrument").selection_set(self._selected_instrument)
            self.instrument_info()

        elif widget == "IE_Button_Export":  # --------------------------------------------------------------------------
            self.stop_playback()
            path = self._settings.get("last music import path")
            file_name = self.app.saveBox("Export instrument data", "", path, "*.bin",
                                         [("Ultima Exodus binary files", "*.bin"),
                                          ("All Files", "*.*")],
                                         asFile=False, parent="Track_Editor")
            if file_name != "":
                self._settings.set("last music import path", os.path.dirname(file_name))
                if self.export_instrument_data(file_name):
                    self.app.setStatusbar("Instrument data saved to file")

        elif widget == "IE_Button_Cancel":  # --------------------------------------------------------------------------
            self.close_instrument_editor()

        elif widget == "IE_List_Instrument":    # ----------------------------------------------------------------------
            selection = self.app.getListBoxPos(widget)
            if len(selection) < 1:
                return
            self._selected_instrument = selection[0]
            self.instrument_info()
            self._restart_instrument_test()

        elif widget == "IE_Show_Info":  # ------------------------------------------------------------------------------
            if self._selected_instrument < 0:
                return

            instrument = self._instruments[self._selected_instrument]
            name = f"Instrument #{self._selected_instrument:02}: {instrument.name}"
            address = f"Pointers: ${self._bank:02X}:{instrument.envelope_address[0]:04X}, " + \
                      f"{instrument.envelope_address[1]:04X}, {instrument.envelope_address[2]:04X}"
            sizes = [instrument.envelope[e][0] for e in range(3)]
            size = f"Size: {sizes[0] + sizes[1] + sizes[2]} {sizes}"
            try:
                self.app.setLabel("II_Label_Name", name)
                self.app.setLabel("II_Label_Address", address)
                self.app.setLabel("II_Label_Size", size)
            except ItemLookupError:
                with self.app.subWindow("Instrument_Info", modal=True, size=[320, 200], padding=[2, 2],
                                        title="Instrument Info", bg=colour.DARK_ORANGE, fg=colour.WHITE, blocking=True):

                    self.app.label("II_Label_Name", name, sticky="NEW", colspan=2, row=0, column=0, font=11)

                    self.app.label("II_Label_Address", address, sticky="NE", row=1, column=1, font=10)
                    self.app.label("II_Label_Size", size, sticky="NW", row=1, column=0, font=10)

                    self.app.label("II_Label_Usage", "Used in tracks:", sticky="SW", row=2, column=0, font=11)
                    self.app.listBox("II_List_Tracks", ["Please wait..."], bg=colour.BLACK, fg=colour.LIGHT_LIME,
                                     height=8, sticky="SEW", row=3, column=0, colspan=2, font=10)
            finally:
                # Find all tracks using this instrument
                tracks_list = self.instrument_usage(self._selected_instrument)
                self.app.clearListBox("II_List_Tracks", callFunction=False)
                self.app.addListItems("II_List_Tracks", tracks_list, select=False)
                # Show info window
                self.app.showSubWindow("Instrument_Info", follow=True)
                self.app.getEntryWidget("IE_Instrument_Name").focus_set()

        elif widget == "IE_Update_Name":    # --------------------------------------------------------------------------
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

            self._unsaved_changes_instrument = True

        # Move envelope entry to next envelope
        elif widget[:13] == "IE_Move_Right":    # ----------------------------------------------------------------------
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

            self._unsaved_changes_instrument = True

        # Envelope entry selected
        elif widget[:17] == "IE_List_Envelope_":    # ------------------------------------------------------------------
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

        elif widget[:8] == "IE_Duty_":  # ------------------------------------------------------------------------------
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

        elif widget[:10] == "IE_Volume_":   # --------------------------------------------------------------------------
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

        elif widget == "IE_Button_Channel":     # ----------------------------------------------------------------------
            self._test_channel += 1
            if self._test_channel > 3:
                self._test_channel = 1

            image = ["", "res/square_wave.gif", "res/triangle_wave.gif", "res/noise_wave.gif"]
            tooltip = ["", "Square Wave Channel", "Triangle Wave Channel", "Noise Wave Channel"]

            self.app.setButtonImage(widget, image[self._test_channel])
            self.app.setButtonTooltip(widget, tooltip[self._test_channel])

            self._restart_instrument_test()

        elif widget == "IE_Button_Semiquaver":  # ----------------------------------------------------------------------
            self._test_speed = 0
            self.app.button("IE_Button_Semiquaver", bg=colour.WHITE)
            self.app.button("IE_Button_Crotchet", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Minim", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Crotchet":    # ----------------------------------------------------------------------
            self._test_speed = 1
            self.app.button("IE_Button_Semiquaver", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Crotchet", bg=colour.WHITE)
            self.app.button("IE_Button_Minim", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Minim":   # --------------------------------------------------------------------------
            self._test_speed = 2
            self.app.button("IE_Button_Semiquaver", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Crotchet", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Minim", bg=colour.WHITE)
            self._restart_instrument_test()

        elif widget == "IE_Button_One_Note":    # ----------------------------------------------------------------------
            self._test_notes = 0
            self.app.button("IE_Button_One_Note", bg=colour.WHITE)
            self.app.button("IE_Button_Scale", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Arpeggio", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Scale":   # --------------------------------------------------------------------------
            self._test_notes = 1
            self.app.button("IE_Button_One_Note", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Scale", bg=colour.WHITE)
            self.app.button("IE_Button_Arpeggio", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Arpeggio":    # ----------------------------------------------------------------------
            self._test_notes = 2
            self.app.button("IE_Button_One_Note", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Scale", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Arpeggio", bg=colour.WHITE)
            self._restart_instrument_test()

        elif widget == "IE_Button_Treble":  # --------------------------------------------------------------------------
            self._test_octave = 0
            self.app.button("IE_Button_Treble", bg=colour.WHITE)
            self.app.button("IE_Button_Alto", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Bass", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Alto":    # --------------------------------------------------------------------------
            self._test_octave = 1
            self.app.button("IE_Button_Treble", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Alto", bg=colour.WHITE)
            self.app.button("IE_Button_Bass", bg=colour.DARK_GREY)
            self._restart_instrument_test()

        elif widget == "IE_Button_Bass":    # --------------------------------------------------------------------------
            self._test_octave = 2
            self.app.button("IE_Button_Treble", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Alto", bg=colour.DARK_GREY)
            self.app.button("IE_Button_Bass", bg=colour.WHITE)
            self._restart_instrument_test()

        elif widget == "IE_Play_Stop":  # ------------------------------------------------------------------------------
            if self._play_thread.is_alive():
                self.stop_playback()
                self.app.setButtonImage(widget, "res/play.gif")
            else:
                note_length = 7 + (self._test_speed << 4)
                # Build some test data
                tracks: List[List] = [[], [], [], []]

                for c in range(4):
                    if c == self._test_channel:
                        tracks[c] = [TrackDataEntry.new_volume(15)]
                        tracks[c].append(TrackDataEntry.new_instrument(self._selected_instrument))
                        if self._test_octave == 2:
                            base_note = 0x0C
                        elif self._test_octave == 1:
                            base_note = 0x18
                        else:
                            base_note = 0x24

                        if self._test_notes == 0:  # Single note loop
                            tracks[c].append(TrackDataEntry.new_note(base_note + 7, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 7, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 7, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 7, note_length))
                        elif self._test_notes == 1:  # Scale
                            tracks[c].append(TrackDataEntry.new_note(base_note, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 2, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 4, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 5, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 7, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 9, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 11, note_length))
                        else:  # Arpeggio
                            tracks[c].append(TrackDataEntry.new_note(base_note, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 4, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 7, note_length))
                            tracks[c].append(TrackDataEntry.new_note(base_note + 4, note_length))
                        tracks[c].append(TrackDataEntry.new_rewind(2))
                    else:
                        # "Mute" other channels
                        tracks[c] = [TrackDataEntry.new_volume(0)]
                        tracks[c].append(TrackDataEntry.new_vibrato(False, 0, 0))
                        tracks[c].append(TrackDataEntry.new_instrument(0))
                        tracks[c].append(TrackDataEntry.new_rest(note_length))
                        tracks[c].append(TrackDataEntry.new_rewind(0))

                self.start_playback(False, False, tracks)
                self.app.setButtonImage(widget, "res/stop.gif")

        else:   # ------------------------------------------------------------------------------------------------------
            self.info(f"Unimplemented callback for Instrument widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _set_master_volume(self, _event: any = None) -> None:
        """
        Callback for left mouse button release on master volume widget.
        """
        value = self.app.getScale("SE_Master_Volume") / 100
        self.sound_server.setAmp(value)

    # ------------------------------------------------------------------------------------------------------------------

    def _set_triangle_volume(self, _event: any = None) -> None:
        """
        Callback for left mouse button release on triangle channel volume widget.
        """
        self._triangle_volume = self.app.getScale("SE_Triangle_Volume") / 100
        self.apu.set_triangle_volume(self._triangle_volume)

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

    def get_data_size(self, **kwargs) -> int:
        """
        Reads music data to calculate its size.

        Parameters
        ----------
        kwargs: Dict[str, Any]
            address: The address where to start reading
            bank: The bank where the channel data is found
            channel: Alternatively, read the currently loaded channel

        Returns
        -------
        int
            The size, in bytes, of this track's data
        """
        size = 0

        address = kwargs.pop("address", -1)
        bank = kwargs.pop("bank", -1)
        channel = kwargs.pop("channel", -1)

        if 0xBFF0 >= address >= 0x8000:
            if bank < 8 or bank > 9:
                self.error(f"get_data_size: Invalid bank #{bank}.")
                return -1

            while 1:
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

        elif -1 < channel < 4:
            for e in self._track_data[channel]:
                if (e.control == TrackDataEntry.CHANNEL_VOLUME or e.control == TrackDataEntry.REST or
                        e.control == TrackDataEntry.SELECT_INSTRUMENT or e.control < 0xF0):
                    size += 2

                elif e.control == TrackDataEntry.SET_VIBRATO:
                    size += 4

                elif e.control == TrackDataEntry.REWIND:
                    size += 4
                    break

                else:
                    size += 1

        else:
            self.error(f"get_data_size: Invalid parameters '{kwargs}'.")
            return -1

        return size

    # ------------------------------------------------------------------------------------------------------------------

    def _read_track_from_file(self, file_name: str) -> bool:
        success = True

        try:
            fd = open(file_name, "rb")

            buffer: bytes = fd.read()
            file_size = len(buffer)
            file_position: int = 0

            fd.close()
        except IOError as error:
            self.app.errorBox("Import binary file", f"Error reading from binary file '{file_name}': {error}.")
            return False

        tracks: List[List[TrackDataEntry]] = [[], [], [], []]

        for channel in range(4):
            loop_found = False

            while not loop_found:
                if file_position >= file_size:
                    break

                control_byte = buffer[file_position]
                file_position += 1

                try:
                    if control_byte == 0xFB:  # FB - VOLUME
                        value = buffer[file_position]
                        file_position += 1
                        data = TrackDataEntry.new_volume(value)

                    elif control_byte == 0xFC:  # FC - INSTRUMENT
                        value = buffer[file_position]
                        if value < 0:
                            self.warning(f"Invalid instrument index: {value} found.")
                            value = 0
                        file_position += 1
                        data = TrackDataEntry.new_instrument(value)

                    elif control_byte == 0xFD:  # FD - VIBRATO
                        triangle_octave = buffer[file_position]
                        file_position += 1

                        speed = buffer[file_position]
                        file_position += 1

                        factor = buffer[file_position]
                        file_position += 1

                        data = TrackDataEntry.new_vibrato(triangle_octave < 0xFF, speed, factor)
                        # data.raw = bytearray([0xFD, triangle_octave, speed, factor])

                    elif control_byte == 0xFE:  # FE - REST
                        value = buffer[file_position]
                        file_position += 1

                        data = TrackDataEntry.new_rest(value)
                        # data.raw = bytearray([0xFE, value])

                    elif control_byte == 0xFF:  # FF - REWIND
                        # Skip next byte (always zero, unused)
                        file_position += 1

                        # Read signed offset (usually negative)
                        signed_value = bytearray([buffer[file_position], buffer[file_position + 1]])
                        offset = int.from_bytes(signed_value, "little", signed=True)
                        file_position += 2

                        if offset > 0:
                            self.app.warningBox("Track Editor",
                                                f"Found positive rewind offset ({offset}) for channel {channel}.\n" +
                                                "This may have undesired effects.", "Track_Editor")

                        # Calculate item index based on each item's size, counting backwards
                        loop_position: int = len(tracks[channel])  # Start from the end
                        byte_count: int = 0
                        for element in reversed(tracks[channel]):
                            if byte_count <= offset:
                                break
                            byte_count -= len(element.raw)
                            loop_position -= 1

                        if loop_position < 0:
                            loop_position = 0
                        data = TrackDataEntry.new_rewind(loop_position)
                        data.raw = bytearray([0xFF, 0])
                        data.raw += offset.to_bytes(2, "little", signed=True)
                        loop_found = True

                    elif control_byte >= 0xF0:  # F0-FA - IGNORED
                        value = buffer[file_position]
                        file_position += 1

                        data = TrackDataEntry(bytearray([value]))

                    else:  # 00-EF - NOTE
                        index = control_byte

                        duration = buffer[file_position]
                        file_position += 1

                        if index > len(_notes):
                            self.warning(f"Invalid note: ${control_byte:02X} for channel {channel} at " +
                                         f"0x{file_position:X} in file '{file_name}'.")
                            data = TrackDataEntry.new_note(0, 0)
                        else:
                            data = TrackDataEntry.new_note(index, duration)

                except IndexError:
                    break

                tracks[channel].append(data)

        for channel in range(4):
            if len(tracks[channel]) < 1:
                self.app.warningBox("Import binary file", "File truncated, or missing REWIND value for one or more " +
                                    "tracks.", "Track_Editor")
                success = False
                break

        if success:
            self._track_data = tracks

        self.track_info(0)
        self.track_info(1)
        self.track_info(2)
        self.track_info(3)

        return success

    # ------------------------------------------------------------------------------------------------------------------

    def _save_track_to_file(self, file_name: str) -> bool:
        """
        Exports the current track to a raw binary file, which is how it would appear in ROM.
        Parameters
        ----------
        file_name: str
            Full path to export to
        Returns
        -------
        bool
            True if data was successfully saved, False otherwise.
        """
        success: bool = True

        # If file has no extension, add ".bin"
        if file_name.rfind('.') < 0:
            file_name += ".bin"

        try:
            fd = open(file_name, "wb")

            for channel in range(4):
                # Calculate rewind offset for this channel
                if self._track_data[channel][-1].control != TrackDataEntry.REWIND:
                    self.warning(f"Channel {channel} does not end with a REWIND element!")
                    loop_position = 0
                    self._track_data.append(TrackDataEntry.new_rewind(0))
                else:
                    loop_position = self._track_data[channel][-1].loop_position

                # Go through the data from the last element to the first, counting bytes until we reach our target
                #   element
                offset: int = 4
                position: int = len(self._track_data[channel])
                for element in reversed(self._track_data[channel]):
                    if position == loop_position:
                        break
                    else:
                        offset -= len(element.raw)
                    position -= 1

                if offset > 0:
                    offset = 0

                self._track_data[channel][-1].raw = bytearray([0xFF, 00]) + \
                    bytearray(offset.to_bytes(2, "little", signed=True))

                # Write channel data
                for element in self._track_data[channel]:
                    fd.write(element.raw)

            fd.close()
        except IOError as error:
            self.app.errorBox("Track Editor", f"Error exporting data to '{file_name}': {error}.")
            success = False

        return success

    # ------------------------------------------------------------------------------------------------------------------

    @dataclass(init=True, repr=False)
    class FMSNote:
        # These are all the supported parameters
        time: int
        value: str = ""
        instrument: str = ""
        volume: int = -1
        vibrato_speed: int = -1
        vibrato_depth: int = -1

    # ------------------------------------------------------------------------------------------------------------------

    class FMSPattern:
        """
        Properties
        ----------
        name: str
            Pattern name, mandatory

        length: int
            Total duration of this pattern, (notes * duration)

        note_length: int
            The duration of each note, in frames

        events: List[MusicEditor.FMSNote]
            The list of events/notes in this pattern
        """
        VIBRATO_FACTOR: bytearray = bytearray([0, 240, 220, 204, 188, 176, 160, 142,
                                               128, 86, 64, 42, 30, 20, 12, 2])

        def __init__(self, name: str, length: int = 10, note_length: int = 10):
            self.name: str = name
            self.note_length: int = note_length
            self.length: int = length

            self.events: List[MusicEditor.FMSNote] = []

        def to_track_data(self, instruments=None) -> List[TrackDataEntry]:
            if instruments is None:
                instruments: List[(int, str)] = []

            converted: List[TrackDataEntry] = []

            pattern_duration = self.length * self.note_length

            # Some events happen in the middle of a note, which is not supported by the game's music driver
            # To work around it, we stop the note short, and re-start the same note after the event
            # Note that this will only sound about right if the envelope doesn't end in a much lower volume
            last_note_value = ""

            # We won't create an instrument change event if the instrument is not actually changing
            last_instrument = ""

            # If the first event doesn't start at time 0, then we must add a rest
            # Unfortunately that is not 100% compatible with FamiStudio, but can be fixed manually after importing
            if len(self.events) > 0 and self.events[0].time != 0:
                try:
                    converted.append(TrackDataEntry.new_rest(self.events[1].time))
                except IndexError:
                    converted.append(TrackDataEntry.new_rest(self.note_length))

            # We need to keep track of this in order to look ahead when calculating note durations
            event_index = 0

            for e in self.events:
                if e.value == "Stop":
                    # We only need a rest if this isn't immediately followed by a note
                    if event_index >= len(self.events) - 1:
                        # At the end of the pattern: calculate how long before the end and use that as our duration
                        duration = (self.length * self.note_length) - e.time
                        if duration > 0:
                            converted.append(TrackDataEntry.new_rest(duration))

                    elif self.events[event_index + 1].time > e.time + 1:
                        # Not immediately followed by something else: we add a rest to fill the gap
                        duration = self.events[event_index + 1].time - e.time
                        # If the duration would be too long, split this into several rests
                        if duration < 256:
                            converted.append(TrackDataEntry.new_rest(duration))
                        else:
                            factor = duration >> 2
                            if factor == 0:
                                factor = 1
                            while duration > 255:
                                duration -= factor
                                converted.append(TrackDataEntry.new_rest(factor))

                    # In any case, clear the last note value
                    last_note_value = ""

                else:
                    # Any event that happen at the same time as a note must be added first
                    if e.instrument != "":
                        # Skip event if instrument is still the same, but only if there is a note at the same time
                        if e.instrument != last_instrument and e.value != "":
                            last_instrument = e.instrument
                            # If there is an instrument with a matching name, use that instrument's index
                            instrument_id = 0
                            for i in instruments:
                                if i[1] == e.instrument:
                                    instrument_id = i[0]
                                    break
                            converted.append(TrackDataEntry.new_instrument(instrument_id))

                    if e.volume > -1:
                        converted.append(TrackDataEntry.new_volume(e.volume))

                    if e.vibrato_depth > -1 and e.vibrato_speed > -1:
                        # Use a pre-calculated conversion table for this value
                        if e.vibrato_depth > 15:
                            e.vibrato_depth = 15

                        converted.append(TrackDataEntry.new_vibrato(
                            False, e.vibrato_speed, MusicEditor.FMSPattern.VIBRATO_FACTOR[e.vibrato_depth]))

                    if e.value == "":
                        # This event is likely interrupting a note, and we'll need to re-play it after
                        note_value = last_note_value
                    else:
                        # This event happens as a new note starts: we add the note after the event
                        last_note_value = e.value
                        note_value = e.value

                    # Calculate the note's duration based on the next event's time
                    duration = self.note_length
                    try:
                        duration = self.events[event_index + 1].time - e.time

                    except IndexError:
                        # This was the last event, so we let it run until the end of the pattern
                        duration = pattern_duration - e.time
                    finally:
                        if note_value != "":
                            converted.append(TrackDataEntry.new_note(duration=duration, name=note_value.upper()))
                        else:
                            # No previous notes: add a rest instead
                            converted.append(TrackDataEntry.new_rest(duration))

                event_index += 1

            return converted

    # ------------------------------------------------------------------------------------------------------------------

    def _read_famistudio_text(self, file_name: str) -> List[List[TrackDataEntry]]:
        # One list per channel
        track_data: List[List[TrackDataEntry]] = [[], [], [], []]
        # We will buffer the whole file
        buffer: List[str] = []

        # We will skip the envelopes here and only keep track of instrument names, which we can use to see if
        #   there is a matching instrument name
        instruments: List[(int, str)] = []

        loop_point = 0
        note_length = 10
        # Default pattern length, in number of notes
        default_pattern_length = 1

        # (index, pattern length, note length)
        custom_pattern_lengths: List[Tuple[int, int, int]] = []

        # We will only import the first song for now
        # TODO Scan for songs first and ask which one to import
        found_songs = 0

        # Index of the channel (0-3) we are currently processing
        channel = -1

        # We want a list of patterns per channel
        patterns: List[List[MusicEditor.FMSPattern]] = [[], [], [], []]

        current_pattern: MusicEditor.FMSPattern = MusicEditor.FMSPattern("")

        # Each channel will have a list of pattern instances, referenced by name
        pattern_instances: List[List[str]] = [[], [], [], []]

        try:
            fd = open(file_name, "r")

            # Buffer everything
            buffer = [line.rstrip() for line in fd]

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

        expression = re.compile(r'''((?:[^ "']|"[^"]*"|'[^']*')+)''')

        for line in buffer:
            # Process lines
            parts = expression.split(line)[1::2]

            object_name = parts[0].lstrip()

            if object_name == "DPCMSample" or parts[0] == "DPCMMapping":
                # Ignore there, not supported by the driver
                continue

            elif object_name == "Arpeggio":
                # Maybe we'll add support for this at some point
                continue

            elif object_name == "Instrument":
                try:
                    name = parts[1].split('=')[1].replace('"', '')
                    instruments.append((len(instruments), name))
                except IndexError:
                    continue

            elif object_name == "Envelope":
                # We're not importing instruments here
                continue

            elif object_name == "Song":
                found_songs += 1
                if found_songs > 1:
                    # We're only importing one song for now
                    break

                # Extract the parameters we can use
                try:
                    for p in parts[1:]:
                        if p[:9] == "LoopPoint":
                            loop_point = int(p.split('=')[1].replace('"', ''))
                        elif p[:10] == "NoteLength":
                            note_length = int(p.split('=')[1].replace('"', ''))
                        elif p[:13] == "PatternLength":
                            default_pattern_length = int(p.split('=')[1].replace('"', ''))

                except IndexError:
                    continue

            elif object_name == "PatternCustomSettings":
                i = -1  # Index
                nl = note_length  # Custom note length
                pl = default_pattern_length  # Custom pattern length
                try:
                    for p in parts[1:]:
                        if p == "Time":
                            i = int(p.split('=')[1].replace('"', ''), 10)
                        elif p == "NoteLength":
                            nl = int(p.split('=')[1].replace('"', ''), 10)
                        elif p == "Length":
                            pl = int(p.split('=')[1].replace('"', ''), 10)
                    if i > -1:
                        custom_pattern_lengths.append((i, pl, nl))

                except ValueError:
                    continue

            elif object_name == "Channel":
                try:
                    name = parts[1].split('=')[1].replace('"', '')
                    if name == "Square1":
                        channel = 0
                    elif name == "Square2":
                        channel = 1
                    elif name == "Triangle":
                        channel = 2
                    elif name == "Noise":
                        channel = 3
                    else:
                        channel = -1
                except IndexError:
                    continue

            elif object_name == "Pattern":
                try:
                    # Create a new pattern and add it to this channel's patterns list
                    name = parts[1].split('=')[1].replace('"', '')

                    pattern_index = len(patterns)
                    pl = default_pattern_length
                    nl = note_length
                    for c in custom_pattern_lengths:
                        if c[0] == pattern_index:
                            pl = c[1]
                            nl = c[2]

                    current_pattern = MusicEditor.FMSPattern(name, pl, nl)
                    patterns[channel].append(current_pattern)
                except IndexError:
                    continue

            elif object_name == "Note":
                if current_pattern.name != "":
                    try:
                        note = MusicEditor.FMSNote(0)

                        for p in parts[1:]:
                            attribute = p.split('=')
                            if attribute[0] == "Time":
                                note.time = int(attribute[1].replace('"', ''), 10)
                            elif attribute[0] == "Value":
                                note.value = attribute[1].replace('"', '')
                            elif attribute[0] == "Instrument":
                                note.instrument = attribute[1].replace('"', '')
                            elif attribute[0] == "Volume":
                                note.volume = int(attribute[1].replace('"', ''), 10)
                            elif attribute[0] == "VibratoSpeed":
                                note.vibrato_speed = int(attribute[1].replace('"', ''), 10)
                            elif attribute[0] == "VibratoDepth":
                                note.vibrato_depth = int(attribute[1].replace('"', ''), 10)

                        current_pattern.events.append(note)

                    except IndexError or ValueError:
                        continue

            elif object_name == "PatternInstance":
                if current_pattern.name != "" and channel != -1:
                    try:
                        name = parts[2].split('=')[1].replace('"', '')
                        pattern_instances[channel].append(name)
                    except IndexError:
                        continue

        # Convert all patterns
        square0_patterns: List[List[TrackDataEntry]] = []
        square1_patterns: List[List[TrackDataEntry]] = []
        triangle_patterns: List[List[TrackDataEntry]] = []
        noise_patterns: List[List[TrackDataEntry]] = []

        for p in patterns[0]:
            square0_patterns.append(p.to_track_data(instruments))
        for p in patterns[1]:
            square1_patterns.append(p.to_track_data(instruments))
        for p in patterns[2]:
            triangle_patterns.append(p.to_track_data(instruments))
        for p in patterns[3]:
            noise_patterns.append(p.to_track_data())

        # Create track data from pattern instances

        # TODO
        #   #1 Support "empty" patterns?
        #   They appear as "holes" in the list of instances, where for example there is no entry with Time="0"
        #   #2 Calculate the correct loop point

        # ---  Square 0 ---

        channel = 0
        self._track_data[channel] = []
        for name in pattern_instances[channel]:
            # Find the pattern with this name
            for p in range(len(patterns[channel])):
                if patterns[channel][p].name == name:
                    # Add it to the channel's track
                    self._track_data[channel] = self._track_data[channel] + square0_patterns[p]
                    break

        # Add a rewind event at the end
        self._track_data[0].append(TrackDataEntry.new_rewind(loop_point))

        self.track_info(channel)

        # --- Square 1 ---

        channel = 1
        self._track_data[channel] = []
        for name in pattern_instances[channel]:
            for p in range(len(patterns[channel])):
                if patterns[channel][p].name == name:
                    self._track_data[channel] = self._track_data[channel] + square1_patterns[p]
                    break
        self._track_data[channel].append(TrackDataEntry.new_rewind(loop_point))

        self.track_info(channel)

        # --- Triangle ---

        channel = 2
        self._track_data[channel] = []
        for name in pattern_instances[channel]:
            for p in range(len(patterns[channel])):
                if patterns[channel][p].name == name:
                    self._track_data[channel] = self._track_data[channel] + triangle_patterns[p]
                    break
        self._track_data[channel].append(TrackDataEntry.new_rewind(loop_point))

        self.track_info(channel)

        # --- Noise ---

        channel = 3
        self._track_data[channel] = []
        for name in pattern_instances[channel]:
            for p in range(len(patterns[channel])):
                if patterns[channel][p].name == name:
                    self._track_data[channel] = self._track_data[channel] + noise_patterns[p]
                    break
        self._track_data[channel].append(TrackDataEntry.new_rewind(loop_point))

        self.track_info(channel)

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

            for c in range(4):
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

    def _play_loop(self, seek: Tuple[int, int] = (0, 0), tracks: Optional[List[List[TrackDataEntry]]] = None) -> None:
        """
        The playback loop, which should run in its own thread.
        Parameters
        ----------
        seek: Tuple[int, int]
            A tuple (channel, index) used to start playing from a specific point in this track
        """
        # TODO Fix the sudden pitch jumps that happen on or after a rest in the Triangle channel
        if tracks is None:
            tracks = self._track_data

        # --- Init code ---
        if self.sound_server.getIsBooted() < 1:
            self.sound_server.boot()
            # Give the sound server some time to boot
            time.sleep(0.5)
            if not self.sound_server.getIsBooted():
                time.sleep(1.5)

        if not self.sound_server.getIsStarted():
            self.sound_server.start()
            time.sleep(.2)

        self.apu.set_triangle_volume(self._triangle_volume)

        # Approximate NTSC timing
        frame_interval = 0.016  # 1 / 60

        channel_volume = bytearray([0, 0, 0, 0])
        note_volume = bytearray([0, 0, 0, 0])
        channel_instrument: List[Instrument] = [Instrument(), Instrument(), Instrument(), Instrument()]
        # Each channel has a set of 3 triggers that control when to switch to the next envelope
        envelope_triggers = [bytearray([0, 0, 0]),
                             bytearray([0, 0, 0]),
                             bytearray([0, 0, 0]),
                             bytearray([0, 0, 0])]

        # This controls the difference between the "base" note period and each entry in the vibrato table
        vibrato_factor = bytearray([0, 0, 0, 0])
        # How much to increment the counter, affects how soon we will switch to the next period entry in the table
        # These are 16-bit values
        vibrato_increment = [0, 0, 0, 0]
        vibrato_counter = [0, 0, 0, 0]
        # Low byte of note period will be taken from this table at each frame
        vibrato_table = [bytearray([0, 0, 0, 0, 0, 0, 0, 0]),
                         bytearray([0, 0, 0, 0, 0, 0, 0, 0]),
                         bytearray([0, 0, 0, 0, 0, 0, 0, 0]),
                         bytearray([0, 0, 0, 0, 0, 0, 0, 0])]

        # Read the register masks from ROM
        reg_mask: List[bytearray] = [bytearray(), bytearray(), bytearray(), bytearray()]
        if self._bank == 8:
            reg_mask[0] = self.rom.read_bytes(0x8, 0x859F, 4)
            reg_mask[1] = self.rom.read_bytes(0x8, 0x85A3, 4)
            reg_mask[2] = self.rom.read_bytes(0x8, 0x85A7, 4)
            reg_mask[3] = self.rom.read_bytes(0x8, 0x85AB, 4)
        elif self._bank == 9:
            reg_mask[0] = self.rom.read_bytes(0x9, 0x85A3, 4)
            reg_mask[1] = self.rom.read_bytes(0x9, 0x85A7, 4)
            reg_mask[2] = self.rom.read_bytes(0x9, 0x85AB, 4)
            reg_mask[3] = self.rom.read_bytes(0x9, 0x85AF, 4)
        else:
            self.app.errorBox("Music Editor", f"Unsupported ROM bank {self._bank}.", "Music_Editor")
            return

        # At the end of each play loop, these values will be written to the corresponding APU registers of their
        # respective channels
        reg_0 = bytearray([reg_mask[0][0], reg_mask[0][1], reg_mask[0][2], reg_mask[0][3]])
        reg_1 = bytearray([reg_mask[1][0], reg_mask[1][1], reg_mask[1][2], reg_mask[1][3]])
        reg_2 = bytearray([reg_mask[2][0], reg_mask[2][1], reg_mask[2][2], reg_mask[2][3]])
        reg_3 = bytearray([reg_mask[3][0], reg_mask[3][1], reg_mask[3][2], reg_mask[3][3]])

        # Initialise APU registers
        self.apu.pulse_0.write_reg0(reg_mask[0][0])
        self.apu.pulse_0.write_reg1(reg_mask[0][1])
        self.apu.pulse_0.write_reg2(reg_mask[0][2])
        self.apu.pulse_0.write_reg3(reg_mask[0][3])

        self.apu.pulse_1.write_reg0(reg_mask[1][0])
        self.apu.pulse_1.write_reg1(reg_mask[1][1])
        self.apu.pulse_1.write_reg2(reg_mask[1][2])
        self.apu.pulse_1.write_reg3(reg_mask[1][3])

        self.apu.triangle.write_reg0(reg_mask[2][0])
        self.apu.triangle.write_reg2(reg_mask[2][2])
        self.apu.triangle.write_reg3(reg_mask[2][3])

        self.apu.noise.write_reg0(reg_mask[3][0])
        self.apu.noise.write_reg2(reg_mask[3][2])
        self.apu.noise.write_reg3(reg_mask[3][3])

        # Pre-allocate some variables so we don't need a lot of malloc during the loop
        # Envelope size, three envelopes per instrument, one instrument per channel
        size_0: bytearray = bytearray([0, 0, 0, 0])
        size_1: bytearray = bytearray([0, 0, 0, 0])
        size_2: bytearray = bytearray([0, 0, 0, 0])
        tmp_int: int
        tmp_vol: int        # Volume before attenuation

        triangle_octave: bool = False

        self._track_counter = [0, 0, 0, 0]
        self._track_position = [0, 0, 0, 0]

        # --- Seek code ---

        if seek[1] != 0:
            # Process the seek channel's elements keeping count of how many frames they take, until we reach the
            #   seek point. We also change the initial values of counters, volumes, instruments and vibrato.
            c = seek[0]
            self._track_position[c] = seek[1]
            element_index = 0
            target_frames = 0

            for e in tracks[c]:
                if element_index == seek[1]:
                    break

                if e.control == TrackDataEntry.CHANNEL_VOLUME:
                    channel_volume[c] = e.raw[1]

                elif e.control == TrackDataEntry.SELECT_INSTRUMENT:
                    channel_instrument[c] = self._instruments[e.raw[1]]

                elif e.control == TrackDataEntry.SET_VIBRATO and c < 3:
                    vibrato_factor[c] = e.raw[2]
                    # Use vibrato_speed to set the counters
                    if e.raw[3] < 2:
                        # Disable vibrato
                        vibrato_counter[c] = 0
                        vibrato_increment[c] = 0
                    else:
                        # Enable vibrato
                        vibrato_increment[c] = 0x800 // e.raw[2]
                        vibrato_counter[c] = 0x200

                    if c == 2:
                        triangle_octave = e.raw[1] < 0xFF

                elif e.control == TrackDataEntry.REST:
                    target_frames += e.raw[1]

                elif e.control == TrackDataEntry.REWIND:
                    # This means we are trying to seek from the end of the track.
                    #   Nice try, but we'll start from 0 instead.
                    target_frames = 0
                    self._track_counter[c] = 1
                    self._track_position[c] = 0
                    break

                elif e.raw[0] < 0xF0:
                    target_frames += e.note.duration

                element_index += 1

            # Now we go through all the other channels to find what element is playing after the desired amount of
            #   frames has passed.
            for c in range(4):
                if c == seek[0]:
                    continue  # Skip the seek channel, we have already processed that

                frames = 0
                element_index = 0
                for e in tracks[c]:
                    if frames == target_frames:
                        # Start this channel exactly from here
                        self._track_position[c] = element_index
                        self._track_counter[c] = 1
                        break

                    if frames > target_frames:
                        # Start in the middle of this element, e.g. during a rest of while a note is playing.
                        self._track_position[c] = element_index
                        # We need to calculate how many frames into the rest/note we need to be to stay in sync.
                        self._track_counter[c] = 1 + (frames - target_frames)
                        break

                    if e.control == TrackDataEntry.CHANNEL_VOLUME:
                        channel_volume[c] = e.raw[1]

                    elif e.control == TrackDataEntry.SELECT_INSTRUMENT:
                        channel_instrument[c] = self._instruments[e.raw[1]]

                        # Store each envelope's size, it will be used to calculate trigger points when a note is played
                        size_0[c] = channel_instrument[c].size(0)
                        size_1[c] = channel_instrument[c].size(1)
                        size_2[c] = channel_instrument[c].size(2)

                    elif e.control == TrackDataEntry.SET_VIBRATO and c < 3:
                        vibrato_factor[c] = e.raw[3]
                        # Use vibrato_speed to set the counters
                        if e.raw[1] < 2:
                            # Disable vibrato
                            vibrato_counter[c] = 0
                            vibrato_increment[c] = 0
                        else:
                            # Enable vibrato
                            vibrato_increment[c] = 0x800 // e.raw[1]
                            vibrato_counter[c] = 0x200

                        if c == 2:
                            if e.raw[1] == 0xFF:
                                triangle_octave = True
                            else:
                                triangle_octave = False

                    elif e.control == TrackDataEntry.REST:
                        frames += e.raw[1]

                    elif e.control == TrackDataEntry.REWIND:
                        # TODO Detect and prevent endless loops if there are no notes or rests
                        element_index = e.loop_position

                    elif e.raw[0] < 0xF0:
                        frames += e.note.duration

                        # Now we set "trigger points" for the instrument's envelope

                        # Trigger 0 is the note duration
                        envelope_triggers[c][0] = e.raw[1]

                        # Trigger 1 is trigger 0 - the size of envelope 0
                        # This means just enough time to play all the values in env.0 before we switch to env.1
                        envelope_triggers[c][1] = e.raw[1] - size_0[c] if e.raw[1] > size_0[c] else 0

                        # Trigger 2
                        tmp_int = envelope_triggers[c][1] - size_2[c] if envelope_triggers[c][1] > size_2[c] else 0

                        if tmp_int > size_1[c]:
                            tmp_int = size_1[c]

                        envelope_triggers[c][2] = envelope_triggers[c][1] - tmp_int

                        note_volume[c] = channel_volume[c]

                    element_index += 1

        # --- End of seek code ---

        c = 0  # Currently playing channel

        # A partially unrolled loop is necessary for a fast enough playback
        while self._playing:
            start_time = time.time()

            # ---------------------------------------- PULSE 0 ---------------------------------------------------------

            # Note that the initial value should be 1, so on the first iteration we immediately read
            # the first segment
            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = tracks[c][self._track_position[c]]

                # Interpret this data

                # Go from the most to least common
                if track_data.raw[0] < 0xF0:        # PULSE 0 NOTE
                    period_lo = self._note_period_lo[track_data.raw[0]]
                    period_hi = self._note_period_hi[track_data.raw[0]]

                    # Do the same vibrato calculations done by the game's music engine
                    # Basically, it creates a table of 8 values for the low byte of the note period, and cycles
                    # through them at a rate that depends on the vibrato speed ("increment" value)
                    vibrato_value = (period_lo >> 3) | ((period_hi & 0x03) << 5)
                    
                    tmp_int = vibrato_value // vibrato_factor[c] if vibrato_factor[c] > 0 else 0

                    # Timer High register value is written as-is
                    reg_3[c] = period_hi

                    # Put the low byte in the vibrato table, positions 0 and 4
                    vibrato_table[c][0] = vibrato_table[c][4] = period_lo
                    # Entries 1 and 3 add the offset
                    vibrato_table[c][1] = vibrato_table[c][3] = (period_lo + tmp_int) % 256
                    # Entry 2 adds the offset again
                    vibrato_table[c][2] = (vibrato_table[c][3] + tmp_int) % 256
                    # Entries 5 and 7 subtract the offset instead
                    vibrato_table[c][5] = vibrato_table[c][7] = period_lo - tmp_int
                    # Finally entry 6 subtracts it again
                    vibrato_table[c][6] = (vibrato_table[c][5] - tmp_int) % 256

                    # Setting the counter will end the "event reading" loop
                    self._track_counter[c] = track_data.raw[1]

                    # Now we set "trigger points" for the instrument's envelope

                    # Trigger 0 is the note duration
                    envelope_triggers[c][0] = track_data.raw[1]

                    # Trigger 1 is trigger 0 - the size of envelope 0
                    # This means just enough time to play all the values in env.0 before we switch to env.1
                    envelope_triggers[c][1] = track_data.raw[1] - size_0[c] if track_data.raw[1] > size_0[c] else 0

                    # Trigger 2
                    tmp_int = envelope_triggers[c][1] - size_2[c] if envelope_triggers[c][1] > size_2[c] else 0

                    if tmp_int > size_1[c]:
                        tmp_int = size_1[c]

                    envelope_triggers[c][2] = envelope_triggers[c][1] - tmp_int

                    note_volume[c] = channel_volume[c]

                elif track_data.control == 0xFE:    # PULSE 0 REST
                    # The "data read" loop should end after setting this
                    self._track_counter[c] = track_data.raw[1]

                    # Skip all the envelope trigger stuff, it has no effect anyway...

                    # This should effectively mute the channel
                    reg_0[c] = reg_mask[c][0]
                    reg_1[c] = reg_mask[c][1]
                    reg_2[c] = reg_mask[c][2]
                    reg_3[c] = reg_mask[c][3]

                    envelope_triggers[c][0] = track_data.raw[1]
                    envelope_triggers[c][1] = 0
                    envelope_triggers[c][2] = 0

                    note_volume[c] = 0

                elif track_data.control == 0xFC:    # PULSE 0 INSTRUMENT
                    channel_instrument[c] = self._instruments[track_data.raw[1]]

                    # Store each envelope's size, it will be used to calculate trigger points when a note is played
                    size_0[c] = channel_instrument[c].size(0)
                    size_1[c] = channel_instrument[c].size(1)
                    size_2[c] = channel_instrument[c].size(2)

                elif track_data.control == 0xFB:    # PULSE 0 VOLUME
                    channel_volume[c] = note_volume[c] = track_data.raw[1]

                elif track_data.control == 0xFD:    # PULSE 0 VIBRATO
                    vibrato_factor[c] = track_data.raw[3]

                    if track_data.raw[2] < 2:
                        # Disable vibrato if speed is less than 2
                        vibrato_increment[c] = 0
                        vibrato_counter[c] = 0
                    else:
                        vibrato_increment[c] = 0x0800 // track_data.raw[2]
                        vibrato_counter[c] = 0x0200

                elif track_data.control == 0xFF:    # PULSE 0 REWIND/END
                    self._track_position[c] = track_data.loop_position - 1

                self._track_position[c] += 1

            # Note/Rest found or still playing one: generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note

                # Use vibrato table and counters to set the Timer Low register
                vibrato_counter[c] += vibrato_increment[c]
                tmp_int = (vibrato_counter[c] >> 8) & 0x07
                reg_2[c] = vibrato_table[c][tmp_int]

                # The value for timer high was written when the note event was encountered, and is not modified here

                # Use instrument envelopes and channel volume to control register 0

                if self._track_counter[c] >= envelope_triggers[c][1]:       # Envelope 0
                    # Index within the envelope is: trigger - remaining note duration
                    tmp_int = (envelope_triggers[c][0] - self._track_counter[c]) + 1
                    if tmp_int > size_0[c]:
                        tmp_int = size_0[c]
                    tmp_vol = channel_instrument[c].envelope[0][tmp_int]

                elif self._track_counter[c] >= envelope_triggers[c][2]:     # Envelope 1
                    tmp_int = (envelope_triggers[c][1] - self._track_counter[c]) + 1
                    if tmp_int > size_1[c]:
                        tmp_int = size_1[c]
                    tmp_vol = channel_instrument[c].envelope[1][tmp_int]

                else:                                                       # Envelope 2
                    tmp_int = (envelope_triggers[c][2] - self._track_counter[c]) + 1
                    if tmp_int > size_2[c]:
                        tmp_int = size_2[c]
                    tmp_vol = channel_instrument[c].envelope[2][tmp_int]

                # Now we must calculate the output based on the envelope and channel volume, but instead of doing
                # the actual calculation, we use lookup tables
                # tmp_vol bits 7-6 = duty, tmp_vol bits 5-1 = volume table to use, bit 0 ignored
                reg_0[c] = (tmp_vol & 0xC0) | _ENV_TABLE[(tmp_vol & 0x1F) >> 1][note_volume[c]]

                # Finally write registers
                self.apu.pulse_0.write_reg0(reg_0[c] | reg_mask[c][0])
                # self.apu.pulse_0.write_reg1(reg_1[c] | reg_mask[c][1]) We can skip this, it's not used
                self.apu.pulse_0.write_reg2(reg_2[c])
                self.apu.pulse_0.write_reg3(reg_3[c])

            # ---------------------------------------- PULSE 1 ---------------------------------------------------------

            c = 1

            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = tracks[c][self._track_position[c]]

                if track_data.raw[0] < 0xF0:  # PULSE 1 NOTE
                    period_lo = self._note_period_lo[track_data.raw[0]]
                    period_hi = self._note_period_hi[track_data.raw[0]]

                    # Do the same vibrato calculations done by the game's music engine
                    # Basically, it creates a table of 8 values for the low byte of the note period, and cycles
                    # through them at a rate that depends on the vibrato speed ("increment" value)
                    vibrato_value = (period_lo >> 3) | ((period_hi & 0x03) << 5)

                    tmp_int = vibrato_value // vibrato_factor[c] if vibrato_factor[c] > 0 else 0

                    # Timer High register value is written as-is
                    reg_3[c] = period_hi

                    # Put the low byte in the vibrato table, positions 0 and 4
                    vibrato_table[c][0] = vibrato_table[c][4] = period_lo
                    # Entries 1 and 3 add the offset
                    vibrato_table[c][1] = vibrato_table[c][3] = (period_lo + tmp_int) % 256
                    # Entry 2 adds the offset again
                    vibrato_table[c][2] = (vibrato_table[c][3] + tmp_int) % 256
                    # Entries 5 and 7 subtract the offset instead
                    vibrato_table[c][5] = vibrato_table[c][7] = period_lo - tmp_int
                    # Finally entry 6 subtracts it again
                    vibrato_table[c][6] = (vibrato_table[c][5] - tmp_int) % 256

                    # Setting the counter will end the "event reading" loop
                    self._track_counter[c] = track_data.raw[1]

                    # Now we set "trigger points" for the instrument's envelope

                    # Trigger 0 is the note duration
                    envelope_triggers[c][0] = track_data.raw[1]

                    # Trigger 1 is trigger 0 - the size of envelope 0
                    # This means just enough time to play all the values in env.0 before we switch to env.1
                    envelope_triggers[c][1] = track_data.raw[1] - size_0[c] if track_data.raw[1] > size_0[c] else 0

                    # Trigger 2
                    tmp_int = envelope_triggers[c][1] - size_2[c] if envelope_triggers[c][1] > size_2[c] else 0

                    if tmp_int > size_1[c]:
                        tmp_int = size_1[c]

                    envelope_triggers[c][2] = envelope_triggers[c][1] - tmp_int

                    note_volume[c] = channel_volume[c]

                elif track_data.control == 0xFE:  # PULSE 1 REST
                    # The "data read" loop should end after setting this
                    self._track_counter[c] = track_data.raw[1]

                    # Skip all the envelope trigger stuff, it has no effect anyway...

                    # This should effectively mute the channel
                    reg_0[c] = reg_mask[c][0]
                    reg_1[c] = reg_mask[c][1]
                    reg_2[c] = reg_mask[c][2]
                    reg_3[c] = reg_mask[c][3]

                    envelope_triggers[c][0] = track_data.raw[1]
                    envelope_triggers[c][1] = 0
                    envelope_triggers[c][2] = 0

                    note_volume[c] = 0

                elif track_data.control == 0xFC:  # PULSE 1 INSTRUMENT
                    channel_instrument[c] = self._instruments[track_data.raw[1]]

                    # Store each envelope's size, it will be used to calculate trigger points when a note is played
                    size_0[c] = channel_instrument[c].size(0)
                    size_1[c] = channel_instrument[c].size(1)
                    size_2[c] = channel_instrument[c].size(2)

                elif track_data.control == 0xFB:  # PULSE 1 VOLUME
                    channel_volume[c] = note_volume[c] = track_data.raw[1]

                elif track_data.control == 0xFD:  # PULSE 1 VIBRATO
                    vibrato_factor[c] = track_data.raw[3]

                    if track_data.raw[2] < 2:
                        # Disable vibrato if speed is less than 2
                        vibrato_increment[c] = 0
                        vibrato_counter[c] = 0
                    else:
                        vibrato_increment[c] = 0x0800 // track_data.raw[2]
                        vibrato_counter[c] = 0x0200

                elif track_data.control == 0xFF:  # PULSE 1 REWIND/END
                    self._track_position[c] = track_data.loop_position - 1

                self._track_position[c] += 1

            # Note/Rest found or still playing one: generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note

                # Use vibrato table and counters to set the Timer Low register
                vibrato_counter[c] += vibrato_increment[c]
                tmp_int = (vibrato_counter[c] >> 8) & 0x07
                reg_2[c] = vibrato_table[c][tmp_int]

                # The value for timer high was written when the note event was encountered, and is not modified here

                # Use instrument envelopes and channel volume to control register 0

                if self._track_counter[c] >= envelope_triggers[c][1]:  # Envelope 0
                    # Index within the envelope is: trigger - remaining note duration
                    tmp_int = (envelope_triggers[c][0] - self._track_counter[c]) + 1
                    if tmp_int > size_0[c]:
                        tmp_int = size_0[c]
                    tmp_vol = channel_instrument[c].envelope[0][tmp_int]

                elif self._track_counter[c] >= envelope_triggers[c][2]:  # Envelope 1
                    tmp_int = (envelope_triggers[c][1] - self._track_counter[c]) + 1
                    if tmp_int > size_1[c]:
                        tmp_int = size_1[c]
                    tmp_vol = channel_instrument[c].envelope[1][tmp_int]

                else:  # Envelope 2
                    tmp_int = (envelope_triggers[c][2] - self._track_counter[c]) + 1
                    if tmp_int > size_2[c]:
                        tmp_int = size_2[c]
                    tmp_vol = channel_instrument[c].envelope[2][tmp_int]

                # Now we must calculate the output based on the envelope and channel volume, but instead of doing
                # the actual calculation, we use lookup tables
                # tmp_vol bits 7-6 = duty, tmp_vol bits 5-1 = volume table to use, bit 0 ignored
                reg_0[c] = (tmp_vol & 0xC0) | _ENV_TABLE[(tmp_vol & 0x1F) >> 1][note_volume[c]]

                # Finally write registers
                self.apu.pulse_1.write_reg0(reg_0[c] | reg_mask[c][0])
                # self.apu.pulse_1.write_reg1(reg_1[c] | reg_mask[c][1]) We can skip this, it's not used
                self.apu.pulse_1.write_reg2(reg_2[c])
                self.apu.pulse_1.write_reg3(reg_3[c])

            # ---------------------------------------- TRIANGLE --------------------------------------------------------

            c = 2

            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = tracks[c][self._track_position[c]]

                # Interpret this data

                # Go from the most to least common
                if track_data.raw[0] < 0xF0:  # TRIANGLE NOTE
                    note_index = track_data.raw[0] + (12 if triangle_octave else 0)
                    period_lo = self._note_period_lo[note_index]
                    period_hi = self._note_period_hi[note_index]

                    # Do the same vibrato calculations done by the game's music engine
                    # Basically, it creates a table of 8 values for the low byte of the note period, and cycles
                    # through them at a rate that depends on the vibrato speed ("increment" value)
                    vibrato_value = (period_lo >> 3) | ((period_hi & 0x03) << 5)

                    tmp_int = vibrato_value // vibrato_factor[c] if vibrato_factor[c] > 0 else 0

                    # Timer High register value is written as-is
                    reg_3[c] = period_hi

                    # Put the low byte in the vibrato table, positions 0 and 4
                    vibrato_table[c][0] = vibrato_table[c][4] = period_lo
                    # Entries 1 and 3 add the offset
                    vibrato_table[c][1] = vibrato_table[c][3] = period_lo + tmp_int
                    # Entry 2 adds the offset again
                    vibrato_table[c][2] = (vibrato_table[c][3] + tmp_int) % 256
                    # Entries 5 and 7 subtract the offset instead
                    vibrato_table[c][5] = vibrato_table[c][7] = period_lo - tmp_int
                    # Finally entry 6 subtracts it again
                    vibrato_table[c][6] = (vibrato_table[c][5] - tmp_int) % 256

                    # Setting the counter will end the "event reading" loop
                    self._track_counter[c] = track_data.raw[1]

                    # Now we set "trigger points" for the instrument's envelope

                    # Trigger 0 is the note duration
                    envelope_triggers[c][0] = track_data.raw[1]

                    # Trigger 1 is trigger 0 - the size of envelope 0
                    # This means just enough time to play all the values in env.0 before we switch to env.1
                    envelope_triggers[c][1] = track_data.raw[1] - size_0[c] if track_data.raw[1] > size_0[c] else 0

                    # Trigger 2
                    tmp_int = envelope_triggers[c][1] - size_2[c] if envelope_triggers[c][1] > size_2[c] else 0

                    if tmp_int > size_1[c]:
                        tmp_int = size_1[c]

                    envelope_triggers[c][2] = envelope_triggers[c][1] - tmp_int

                    note_volume[c] = channel_volume[c]

                elif track_data.control == 0xFE:  # TRIANGLE REST
                    # The "data read" loop should end after setting this
                    self._track_counter[c] = track_data.raw[1]

                    # Skip all the envelope trigger stuff, it has no effect anyway...

                    # This should effectively mute the channel
                    reg_0[c] = reg_mask[c][0]
                    reg_1[c] = reg_mask[c][1]
                    reg_2[c] = reg_mask[c][2]
                    reg_3[c] = reg_mask[c][3]

                    envelope_triggers[c][0] = track_data.raw[1]
                    envelope_triggers[c][1] = 0
                    envelope_triggers[c][2] = 0

                    note_volume[c] = 0

                elif track_data.control == 0xFC:  # TRIANGLE INSTRUMENT
                    channel_instrument[c] = self._instruments[track_data.raw[1]]

                    # Store each envelope's size, it will be used to calculate trigger points when a note is played
                    size_0[c] = channel_instrument[c].size(0)
                    size_1[c] = channel_instrument[c].size(1)
                    size_2[c] = channel_instrument[c].size(2)

                elif track_data.control == 0xFB:  # TRIANGLE VOLUME
                    channel_volume[c] = note_volume[c] = track_data.raw[1]

                elif track_data.control == 0xFD:  # TRIANGLE VIBRATO
                    # +12 semitones if value is not FF
                    triangle_octave = (track_data.raw[1] < 0xFF)

                    vibrato_factor[c] = track_data.raw[3]

                    if track_data.raw[2] < 2:
                        # Disable vibrato if speed is less than 2
                        vibrato_increment[c] = 0
                        vibrato_counter[c] = 0
                    else:
                        vibrato_increment[c] = 0x0800 // track_data.raw[2]
                        vibrato_counter[c] = 0x0200

                elif track_data.control == 0xFF:  # TRIANGLE REWIND/END
                    self._track_position[c] = track_data.loop_position - 1

                self._track_position[c] += 1

            # Note/Rest found or still playing one: generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note

                # Use vibrato table and counters to set the Timer Low register
                vibrato_counter[c] += vibrato_increment[c]
                tmp_int = (vibrato_counter[c] >> 8) & 0x07
                reg_2[c] = vibrato_table[c][tmp_int]

                # The value for timer high was written when the note event was encountered, and is not modified here

                # Use instrument envelopes and channel volume to control register 0

                if self._track_counter[c] >= envelope_triggers[c][1]:  # Envelope 0
                    # Index within the envelope is: trigger - remaining note duration
                    tmp_int = (envelope_triggers[c][0] - self._track_counter[c]) + 1
                    if tmp_int > size_0[c]:
                        tmp_int = size_0[c]
                    tmp_vol = channel_instrument[c].envelope[0][tmp_int]

                elif self._track_counter[c] >= envelope_triggers[c][2]:  # Envelope 1
                    tmp_int = (envelope_triggers[c][1] - self._track_counter[c]) + 1
                    if tmp_int > size_1[c]:
                        tmp_int = size_1[c]
                    tmp_vol = channel_instrument[c].envelope[1][tmp_int]

                else:  # Envelope 2
                    tmp_int = (envelope_triggers[c][2] - self._track_counter[c]) + 1
                    if tmp_int > size_2[c]:
                        tmp_int = size_2[c]
                    tmp_vol = channel_instrument[c].envelope[2][tmp_int]

                # The Triangle channel has no volume: it will be turned off unless "volume" is 15
                reg_0[c] = tmp_vol if note_volume[c] == 0xF else 0x80

                # Finally write registers
                self.apu.triangle.write_reg0((reg_0[c] & 0x8C) | reg_mask[c][0])
                self.apu.triangle.write_reg2(reg_2[c])
                self.apu.triangle.write_reg3(reg_3[c])

            # The triangle channel is muted on the last frame of any note
            else:
                reg_0[c] = 0x80

                # Finally write registers
                self.apu.triangle.write_reg0((reg_0[c] & 0x8C) | reg_mask[c][0])
                self.apu.triangle.write_reg2(reg_2[c])
                self.apu.triangle.write_reg3(reg_3[c])

            # ----------------------------------------- NOISE ----------------------------------------------------------

            c = 3

            self._track_counter[c] -= 1

            # Keep reading data segments until we find a rest or a note
            while self._track_counter[c] < 1:
                track_data = tracks[c][self._track_position[c]]

                if track_data.raw[0] < 0xF0:  # NOISE "NOTE"
                    reg_2[c] = track_data.raw[0] & 0x0F
                    reg_0[c] = reg_mask[c][0]

                    # Note: the noise channel has no vibrato

                    # Setting the counter will end the "event reading" loop
                    self._track_counter[c] = track_data.raw[1]

                    # Now we set "trigger points" for the instrument's envelope

                    # Trigger 0 is the note duration
                    envelope_triggers[c][0] = track_data.raw[1]

                    # Trigger 1 is trigger 0 - the size of envelope 0
                    # This means just enough time to play all the values in env.0 before we switch to env.1
                    envelope_triggers[c][1] = track_data.raw[1] - size_0[c] if track_data.raw[1] > size_0[c] else 0

                    # Trigger 2
                    tmp_int = envelope_triggers[c][1] - size_2[c] if envelope_triggers[c][1] > size_2[c] else 0

                    if tmp_int > size_1[c]:
                        tmp_int = size_1[c]

                    envelope_triggers[c][2] = envelope_triggers[c][1] - tmp_int

                    note_volume[c] = channel_volume[c]

                elif track_data.control == 0xFE:  # NOISE REST
                    # The "data read" loop should end after setting this
                    self._track_counter[c] = track_data.raw[1]

                    # Skip all the envelope trigger stuff, it has no effect anyway...

                    # This should effectively mute the channel
                    reg_0[c] = reg_mask[c][0]
                    reg_1[c] = reg_mask[c][1]
                    reg_2[c] = reg_mask[c][2]
                    reg_3[c] = reg_mask[c][3]

                    envelope_triggers[c][0] = track_data.raw[1]
                    envelope_triggers[c][1] = 0
                    envelope_triggers[c][2] = 0

                    note_volume[c] = 0

                elif track_data.control == 0xFC:  # NOISE INSTRUMENT
                    channel_instrument[c] = self._instruments[track_data.raw[1]]

                    # Store each envelope's size, it will be used to calculate trigger points when a note is played
                    size_0[c] = channel_instrument[c].size(0)
                    size_1[c] = channel_instrument[c].size(1)
                    size_2[c] = channel_instrument[c].size(2)

                elif track_data.control == 0xFB:  # NOISE VOLUME
                    channel_volume[c] = note_volume[c] = track_data.raw[1]

                elif track_data.control == 0xFD:  # NOISE VIBRATO
                    # There is no vibrato for the noise channel
                    pass

                elif track_data.control == 0xFF:  # NOISE REWIND/END
                    self._track_position[c] = track_data.loop_position - 1

                self._track_position[c] += 1

            # Note/Rest found or still playing one: generate / manipulate sound
            if self._track_counter[c] > 1:
                # Keep playing the current note

                # The value for timer high was written when the note event was encountered, and is not modified here

                # Use instrument envelopes and channel volume to control register 0

                if self._track_counter[c] >= envelope_triggers[c][1]:  # Envelope 0
                    # Index within the envelope is: trigger - remaining note duration
                    tmp_int = (envelope_triggers[c][0] - self._track_counter[c]) + 1
                    if tmp_int > size_0[c]:
                        tmp_int = size_0[c]
                    tmp_vol = channel_instrument[c].envelope[0][tmp_int]

                elif self._track_counter[c] >= envelope_triggers[c][2]:  # Envelope 1
                    tmp_int = (envelope_triggers[c][1] - self._track_counter[c]) + 1
                    if tmp_int > size_1[c]:
                        tmp_int = size_1[c]
                    tmp_vol = channel_instrument[c].envelope[1][tmp_int]

                else:  # Envelope 2
                    tmp_int = (envelope_triggers[c][2] - self._track_counter[c]) + 1
                    if tmp_int > size_2[c]:
                        tmp_int = size_2[c]
                    tmp_vol = channel_instrument[c].envelope[2][tmp_int]

                # Now we must calculate the output based on the envelope and channel volume, but instead of doing
                # the actual calculation, we use lookup tables
                # tmp_vol bits 7-6 = duty, tmp_vol bits 5-1 = volume table to use, bit 0 ignored
                reg_0[c] = (tmp_vol & 0xC0) | _ENV_TABLE[(tmp_vol & 0x1F) >> 1][note_volume[c]]

                # Finally write registers
                self.apu.noise.write_reg0(reg_0[c] | reg_mask[c][0])
                self.apu.noise.write_reg2(reg_2[c])
                self.apu.noise.write_reg3(reg_3[c])

            # ------------------------------------------ END -----------------------------------------------------------
            # Restart from channel 0
            c = 0

            interval = frame_interval - (time.time() - start_time)
            if interval > 0:
                time.sleep(interval)
            else:
                self._slow_event.set()

        # End
        self.sound_server.stop()
