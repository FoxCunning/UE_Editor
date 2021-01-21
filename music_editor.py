__author__ = "Fox Cunning"

import os
from dataclasses import dataclass, field
from typing import List

import colour
from appJar import gui
from appJar.appjar import ItemLookupError
from debug import log
from rom import ROM


# ----------------------------------------------------------------------------------------------------------------------

@dataclass(init=True, repr=False)
class Instrument:
    envelope_address: List[int] = field(default_factory=list)
    envelope: List[bytearray] = field(default_factory=list)


# ----------------------------------------------------------------------------------------------------------------------

class MusicEditor:

    def __init__(self, app: gui, rom: ROM):
        self.app = app
        self.rom = rom

        self._bank: int = 8

        self._instruments: List[Instrument] = []
        self._selected_instrument: int = 0

        self.track_titles: List[str] = ["- No Tracks -"]

        self._unsaved_changes_instrument: bool = False

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

    def read_track_data(self, track: int):
        pass

    # ------------------------------------------------------------------------------------------------------------------

    def close_instrument_editor(self) -> bool:
        if self._unsaved_changes_instrument is True:
            if self.app.yesNoBox("Instruments Editor", "Are you sure you want to close the Instrument Editor?\n" +
                                 "Any unsaved changes will be lost.", "Instrument_Editor") is False:
                return False

        self.app.hideSubWindow("Instrument_Editor")
        self.app.emptySubWindow("Instrument_Editor")

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def show_instrument_editor(self, bank: int) -> None:
        self._bank = bank

        window_exists = True
        try:
            self.app.getFrameWidget("IE_Frame_Buttons")
        except ItemLookupError:
            self.app.emptySubWindow("Instrument_Editor")
            window_exists = False

        if window_exists is True:
            # Just show window if it already exists
            self.read_instrument_data()
            self._selected_instrument = 0
            self.instrument_info()
            self.app.showSubWindow("Instrument_Editor")
            return

        if bank == 8:
            count = 50
        else:
            self.info("Bank 9 not yet implemented.")
            return

        # TODO Use user-defined instrument names
        instruments_list: List[str] = []
        for i in range(count):
            instruments_list.append(f"0x{i:02X} (no name)")

        with self.app.subWindow("Instrument_Editor"):

            # Buttons
            with self.app.frame("IE_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0, colspan=2):
                self.app.button("IE_Button_Apply", self._instruments_input, image="res/floppy.gif", width=32, height=32,
                                tooltip="Apply changes to all instruments",
                                row=0, column=0)
                self.app.button("IE_Button_Cancel", self._instruments_input, image="res/close.gif", width=32, height=32,
                                tooltip="Cancel / Close window",
                                row=0, column=1)

            # Selection / Name
            with self.app.frame("IE_Frame_Selection", padding=[2, 1], sticky="NEW", row=1, column=0):
                self.app.label("IE_Label_Instrument", "Instrument:", sticky="SW", row=0, column=0, font=11)
                self.app.optionBox("IE_Option_Instrument", instruments_list, change=self._instruments_input,
                                   sticky="SW", width=16, row=0, column=1, colspan=2, font=10)
                self.app.entry("IE_Instrument_Name", "(no name)", width=12, sticky="SW", row=1, column=1)
                self.app.button("IE_Update_Name", self._instruments_input, image="res/reload-small.gif",
                                sticky="S", width=16, height=16, tooltip="Update list", row=1, column=2)

            # Volume / Duty cycle graph
            with self.app.frame("IE_Frame_Graph", padding=[2, 1], sticky="NEW", row=1, column=1):
                self.app.canvas("IE_Canvas_Graph", width=320, height=120, row=0, column=0, bg=colour.BLACK)

            # Envelope data
            with self.app.frame("IE_Frame_Envelope_Data", padding=[8, 1], sticky="NWS", row=2, column=0, colspan=2):
                canvas_width = 140
                list_width = 16

                for e in range(3):
                    self.app.label(f"IE_Label_Envelope_{e}", f"Envelope {e}", sticky="W", row=0, column=e*2, font=10)
                    self.app.listBox(f"IE_List_Envelope_{e}", None, width=list_width, height=8, rows=8,
                                     change=self._instruments_input,
                                     multi=False, group=True, bg=colour.DARK_GREY, fg=colour.WHITE,
                                     sticky="S", row=1, column=e*2, font=9)
                    self.app.getListBoxWidget(f"IE_List_Envelope_{e}").configure(font="TkFixedFont")

                    self.app.canvas(f"IE_Canvas_Envelope_{e}", width=canvas_width, height=140, bg=colour.BLACK,
                                    sticky="S", row=1, column=(e * 2) + 1)

                    self.app.label(f"IE_Label_Duty_{e}", "Duty", fg=colour.PALE_TEAL,
                                   sticky="E", row=2, column=e*2, font=10)
                    self.app.label(f"IE_Label_Volume_{e}", "Volume", fg=colour.PALE_ORANGE,
                                   sticky="E", row=3, column=e*2, font=10)

                    self.app.option(f"IE_Duty_{e}", ["12.5%", "25%", "50%", "75%"], change=self._instruments_input,
                                    bg=colour.DARK_RED, fg=colour.PALE_TEAL,
                                    sticky="WE", row=2, column=(e * 2) + 1, font=9)
                    self.app.scale(f"IE_Volume_{e}", range=(0, 8), change=self._instruments_input,
                                   bg=colour.DARK_RED, fg=colour.PALE_ORANGE,
                                   sticky="WE", row=3, column=(e * 2) + 1, font=9)
                    self.app.showScaleIntervals(f"IE_Volume_{e}", 1)

        self.read_instrument_data()

        self._selected_instrument = 0
        self.instrument_info()
        self.app.showSubWindow("Instrument_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def read_instrument_data(self) -> None:
        bank = self._bank

        if bank == 8:
            instrument_count = 50
            # Each instrument defines three duty/volume envelopes
            address = [0x8643, 0x86A7, 0x870B]
        else:
            self.info("Bank 9 not yet implemented.")
            return

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

            self._instruments.append(instrument)

            # Next instrument
            address[0] += 2
            address[1] += 2
            address[2] += 2

    # ------------------------------------------------------------------------------------------------------------------

    def instrument_info(self) -> None:
        instrument = self._instruments[self._selected_instrument]

        # List this instrument's envelope values
        for e in range(3):
            self.app.clearListBox(f"IE_List_Envelope_{e}")
            envelope = instrument.envelope[e]
            for i in range(1, envelope[0] + 1):
                duty = envelope[i] >> 6
                volume = (envelope[i] & 0x3F) >> 1
                self.app.addListItem(f"IE_List_Envelope_{e}", f"{i-1} - D:{duty} V:{volume}", None, False)

            # Select first item in each list
            self.app.selectListItemAtPos(f"IE_List_Envelope_{e}", 0, True)

    # ------------------------------------------------------------------------------------------------------------------

    def _instruments_input(self, widget: str) -> None:
        if widget == "IE_Button_Cancel":
            self.close_instrument_editor()

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

            # TODO ...and then update the graph

        elif widget[:10] == "IE_Volume_":
            envelope_id = int(widget[-1], 10)
            instrument = self._instruments[self._selected_instrument]
            envelope = instrument.envelope[envelope_id]
            selection = self.app.getListBoxPos(widget)
            if len(selection) < 1:
                # Empty list
                return

            item = selection[0] + 1

            # TODO Change value
            # TODO Update graph

        else:
            self.info(f"Unimplemented callback for widget '{widget}'.")
