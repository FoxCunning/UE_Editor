__author__ = "Fox Cunning"

from dataclasses import dataclass
from typing import List

from PIL import Image, ImageTk

import appJar
import colour
from tkinter import font

import text_editor
from appJar import gui
from debug import log
from editor_settings import EditorSettings
from palette_editor import PaletteEditor
from rom import ROM


# ----------------------------------------------------------------------------------------------------------------------


@dataclass(init=True, repr=False)
class CreditLine:
    x: int = 0
    y: int = 0
    text: str = ""


# ----------------------------------------------------------------------------------------------------------------------

class EndGameEditor:

    # ------------------------------------------------------------------------------------------------------------------

    def __init__(self, app: gui, settings: EditorSettings, rom: ROM, palette_editor: PaletteEditor):
        self.app = app
        self.settings = settings
        self.rom = rom
        self.palette_editor = palette_editor

        self._opening_credit_lines: List[CreditLine] = []

        # Tuple: bank, address, count
        self._end_credit_charset = (0xD, 0xBF00, 26)
        self._end_credit_lines: List[CreditLine] = []
        self._canvas_end = None
        # Cached PIL Image instances
        self._end_tiles: List[ImageTk.PhotoImage] = []
        # Canvas item IDs
        self._end_items: List[int] = []
        self._selected_line_end: int = 0
        self._unsaved_credits: bool = False

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

    def show_credits_window(self) -> None:
        """
        Creates / shows the interface used to edit opening/ending credits.
        Allows changing the character sets, text and text position.
        """
        # Check if window already exists
        try:
            self.app.getFrameWidget("EC_Frame_Buttons")
            self.app.showSubWindow("Credits_Editor")
            return

        except appJar.appjar.ItemLookupError:
            generator = self.app.subWindow("Credits_Editor", size=[600, 400], padding=[2, 2],
                                           title="Ultima: Exodus - Credits Editor",
                                           resizable=False, modal=False, blocking=False,
                                           bg=colour.DARK_GREY, fg=colour.WHITE,
                                           stopFunction=self.close_credits_window)

        self._unsaved_credits = False
        app = self.app
        font_bold = font.Font(font="TkFixedFont", size=11, weight="bold")
        font_mono = font.Font(font="TkFixedFont", size=10)

        # Bank and address of CHR set
        chr_bank = self.rom.read_byte(0xF, 0xE3FD)
        hi = self.rom.read_byte(0xF, 0xE402)
        lo = self.rom.read_byte(0xF, 0xE406)
        chr_addr = (hi << 8) | lo

        # Destination in the PPU, we use this to calculate the index of the first character
        hi = self.rom.read_byte(0xF, 0xE40A)
        lo = self.rom.read_byte(0xF, 0xE40E)
        address = (hi << 8) | lo
        chr_first = (address - 0x1000) >> 4

        # Number of characters to load
        hi = self.rom.read_byte(0xF, 0xE412)
        lo = self.rom.read_byte(0xF, 0xE416)
        chr_count = ((hi << 8) | lo) >> 4

        # 32 canvas items used to preview a line of text
        self._end_items = [0] * 32

        count = self._read_end_credits()
        end_credits_list: List[str] = []
        for i in range(count):
            text = self._end_credit_lines[i].text
            if len(text) > 22:
                text = self._end_credit_lines[i].text[:22] + '\u2026'
            end_credits_list.append(f"#{i:03} '{text}'")

        with generator:

            with app.frame("EC_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0):

                app.button("EC_Apply", self._credits_input, image="res/floppy.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=1, sticky="W", tooltip="Save all changes")
                app.button("EC_Reload", self._credits_input, image="res/reload.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=2, sticky="W", tooltip="Reload from ROM buffer")
                app.button("EC_Close", self._credits_input, image="res/close.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=3, sticky="W", tooltip="Discard changes and close")

                app.canvas("EC_Canvas_Space", width=64, height=1, row=0, column=4)

                app.optionBox("EC_Option_Credits", ["Opening Credits", "End Credits"], change=self._credits_input,
                              row=0, column=5, font=11, sticky="E", width=24)

            with app.frameStack("EC_Stack", row=1, column=0, bg=colour.DARK_GREY):

                with app.frame("EC_Frame_Opening_Credits", padding=[4, 2], bg=colour.DARK_GREEN, fg=colour.WHITE):

                    app.label("OC_Label_0", "NOT YET IMPLEMENTED", row=0, column=0, font=12)

                    app.label("OC_Label_1", "Preview:", sticky="WE", row=1, column=0, font=12)
                    app.canvas("OC_Canvas_Preview", width=256, height=240, bg=colour.BLACK, sticky="N",
                               row=2, column=0)

                with app.frame("EC_Frame_End_Credits", padding=[4, 2], bg=colour.DARK_NAVY, fg=colour.WHITE):

                    with app.frame("EC_Frame_CHR", padding=[2, 2], row=0, column=0):

                        app.label("EC_Label_0", "CHR Set Bank:", sticky="E", row=0, column=0, font=10)
                        app.entry("EC_CHR_Bank", f"0x{chr_bank:02X}", submit=self._credits_input, sticky="W", width=6,
                                  row=0, column=1, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_1", "Address:", sticky="E", row=0, column=2, font=10)
                        app.entry("EC_CHR_Address", f"0x{chr_addr:04X}", submit=self._credits_input, sticky="W",
                                  row=0, column=3, width=8, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_2", "Characters:", sticky="E", row=0, column=4, font=10)
                        app.entry("EC_CHR_Count", chr_count, kind="numeric", limit=4, submit=self._credits_input,
                                  row=0, column=5, sticky="W", width=4, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_3", "First Character:", sticky="E", row=0, column=6, font=10)
                        app.entry("EC_CHR_First", f"0x{chr_first:02X}", limit=4, submit=self._credits_input, sticky="W",
                                  row=0, column=7, width=4, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.button("EC_Update_CHR", self._credits_input, image="res/reload-small.gif", sticky="W",
                                   row=0, column=8, tooltip="Update CHR Set", bg=colour.LIGHT_NAVY)

                    with app.frame("EC_Frame_List", padding=[4, 4], row=1, column=0):

                        app.listBox("EC_List_Credits", end_credits_list, change=self._credits_input,
                                    bg=colour.MEDIUM_NAVY, fg=colour.WHITE, multi=False, group=True,
                                    row=0, column=0, rowspan=4, width=30, height=10, font=font_mono)

                        app.label("EC_Label_4", "X Offset:", sticky="E", row=0, column=1, font=11)
                        app.entry("EC_Line_X", 0, kind="numeric", limit=4, sticky="W", width=4,
                                  change=self._credits_input,
                                  row=0, column=2, font=10, bg=colour.MEDIUM_NAVY, fg=colour.WHITE)
                        app.button("EC_Centre_Line", self._credits_input, text="\u2906 Centre Text \u2907", sticky="W",
                                   row=0, column=3, font=10, bg=colour.MEDIUM_NAVY, fg=colour.WHITE)

                        app.textArea("EC_Line_Text", "", sticky="NEWS", bg=colour.MEDIUM_NAVY, fg=colour.WHITE,
                                     row=1, column=1, colspan=3, height=5, font=font_bold
                                     ).bind("<KeyRelease>", lambda _e: self._credits_input("EC_Line_Text"), add='')
                        app.label("EC_Label_5", "'~' = End of line", sticky="NW",
                                  row=2, column=1, colspan=3, font=9)
                        app.label("EC_Label_6", "Newline = End of credits", sticky="NW",
                                  row=3, column=1, colspan=3, font=9)

                    app.label("EC_Label_7", "Preview:", sticky="WE", row=2, column=0, font=12)
                    app.canvas("EC_Canvas_Preview", map=None, width=512, height=16, bg=colour.BLACK,
                               row=3, column=0, sticky="N")

        self._canvas_end = app.getCanvasWidget("EC_Canvas_Preview")

        self._load_end_patterns()

        # TODO Remove these once the opening credits widgets have been added
        app.setOptionBox("EC_Option_Credits", 1, callFunction=True)
        app.selectListItemAtPos("EC_List_Credits", 0, callFunction=True)

        app.showSubWindow("Credits_Editor", follow=True)

    # ------------------------------------------------------------------------------------------------------------------

    def show_end_game_window(self) -> None:
        self.app.infoBox("Endgame Editor", "Not yet implemented, sorry!")

    # ------------------------------------------------------------------------------------------------------------------

    def close_credits_window(self) -> None:
        self.app.hideSubWindow("Credits_Editor", useStopFunction=False)
        self.app.emptySubWindow("Credits_Editor")

        # Cleanup
        self._end_credit_lines = []
        self._canvas_end = None
        self._end_tiles = []
        self._end_items = []

        self._opening_credit_lines = []

    # ------------------------------------------------------------------------------------------------------------------

    def _credits_input(self, widget: str) -> None:
        if widget == "EC_Close":    # ----------------------------------------------------------------------------------
            if self._unsaved_credits:
                if not self.app.yesNoBox("Credits Editor", "Are you sure you want to close this window?\n" +
                                         "Any unsaved changes will be lost.", "Credits_Editor"):
                    return
            self.close_credits_window()

        elif widget == "EC_Option_Credits":     # ----------------------------------------------------------------------
            index = self._get_selection_index(widget)
            self.app.selectFrame("EC_Stack", index, callFunction=False)

        elif widget == "EC_List_Credits":   # --------------------------------------------------------------------------
            selection = self.app.getListBoxPos(widget)

            if selection is None or len(selection) < 1:
                return

            self._selected_line_end = index = selection[0]

            self.app.clearEntry("EC_Line_X", callFunction=False, setFocus=False)
            self.app.setEntry("EC_Line_X", self._end_credit_lines[index].x, callFunction=False)

            self.app.clearTextArea("EC_Line_Text", callFunction=False)
            self.app.setTextArea("EC_Line_Text", self._end_credit_lines[index].text.upper(), callFunction=False)

            # Update list item and also redraw the preview
            text = self._end_credit_lines[self._selected_line_end].text.upper()
            if len(text) > 22:
                text = text[:22] + '\u2026'
            self.app.setListItemAtPos(widget, self._selected_line_end, f"#{self._selected_line_end:03} '{text}'")

            self._draw_end_preview(index)

        elif widget == "EC_Line_Text":  # ------------------------------------------------------------------------------
            self._end_credit_lines[self._selected_line_end].text = self.app.getTextArea(widget)
            self._draw_end_preview(self._selected_line_end)
            self._unsaved_credits = True

        elif widget == "EC_Line_X":     # ------------------------------------------------------------------------------
            value = self.app.getEntry(widget)
            if value is not None:
                self._end_credit_lines[self._selected_line_end].x = int(value)
                self._draw_end_preview(self._selected_line_end)
                self._unsaved_credits = True

        elif widget == "EC_Centre_Line":    # --------------------------------------------------------------------------
            text = text_editor.ascii_to_exodus(self._end_credit_lines[self._selected_line_end].text)
            size = len(text[:32])
            self._end_credit_lines[self._selected_line_end].x = 16 - (size >> 1)
            self._draw_end_preview(self._selected_line_end)
            self._unsaved_credits = True

        elif (widget == "EC_CHR_Bank" or widget == "EC_CHR_Address" or widget == "EC_CHR_Count" or
              widget == "EC_CHR_First" or widget == "EC_Update_CHR"):   # ----------------------------------------------
            self._load_end_patterns()
            self._draw_end_preview(self._selected_line_end)
            self._unsaved_credits = True

        elif widget == "EC_Reload":     # ------------------------------------------------------------------------------
            if self._unsaved_credits:
                if not self.app.yesNoBox("Credits Editor", "Are you sure you want to reload all data from ROM?\n" +
                                         "Any changes made so far will be lost.", "Credits_Editor"):
                    return

            self._unsaved_credits = False

            # Bank and address of CHR set
            chr_bank = self.rom.read_byte(0xF, 0xE3FD)
            hi = self.rom.read_byte(0xF, 0xE402)
            lo = self.rom.read_byte(0xF, 0xE406)
            chr_addr = (hi << 8) | lo

            # Destination in the PPU, we use this to calculate the index of the first character
            hi = self.rom.read_byte(0xF, 0xE40A)
            lo = self.rom.read_byte(0xF, 0xE40E)
            address = (hi << 8) | lo
            chr_first = (address - 0x1000) >> 4

            # Number of characters to load
            hi = self.rom.read_byte(0xF, 0xE412)
            lo = self.rom.read_byte(0xF, 0xE416)
            chr_count = ((hi << 8) | lo) >> 4

            # Re-read all credit lines
            count = self._read_end_credits()
            end_credits_list: List[str] = []
            for i in range(count):
                text = self._end_credit_lines[i].text
                if len(text) > 22:
                    text = self._end_credit_lines[i].text[:22] + '\u2026'
                end_credits_list.append(f"#{i:03} '{text}'")

            self.app.clearEntry("EC_CHR_Bank", callFunction=False, setFocus=False)
            self.app.clearEntry("EC_CHR_Address", callFunction=False, setFocus=False)
            self.app.clearEntry("EC_CHR_Count", callFunction=False, setFocus=False)
            self.app.clearEntry("EC_CHR_First", callFunction=False, setFocus=False)

            self.app.setEntry("EC_CHR_Bank", f"0x{chr_bank:02X}", callFunction=False)
            self.app.setEntry("EC_CHR_Address", f"0x{chr_addr:04X}", callFunction=False)
            self.app.setEntry("EC_CHR_Count", chr_count, callFunction=False)
            self.app.setEntry("EC_CHR_First", f"0x{chr_first:02X}", callFunction=False)

            self._load_end_patterns()

            self.app.clearListBox("EC_List_Credits", callFunction=False)
            self.app.addListItems("EC_List_Credits", end_credits_list, select=False)
            self.app.selectListItemAtPos("EC_List_Credits", 0, callFunction=True)

        else:   # ------------------------------------------------------------------------------------------------------
            self.warning(f"Unimplemented input from Credits Editor widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _read_end_credits(self) -> int:
        """
        Returns
        -------
        int
            The number of credit lines found in ROM.
        """
        self._end_credit_lines = []

        address = 0x9A1B
        count = 0
        while address < 0x9F00:
            line = CreditLine()

            line.x = self.rom.read_byte(0x6, address)
            if line.x == 0xFF:
                # End of text reached
                break
            address += 1

            # Read characters one by one until a string terminator is found
            text = bytearray()
            while True:
                character = self.rom.read_byte(0x6, address)
                text.append(character)
                address += 1
                if character == 0xFF or address > 0x9EFF:
                    break

            line.text = text_editor.exodus_to_ascii(text)

            self._end_credit_lines.append(line)
            count += 1

        return count

    # ------------------------------------------------------------------------------------------------------------------

    def _load_end_patterns(self) -> None:
        """
        Reads pattern data used for the end credits and stores it in image instances that can be used on a canvas.
        """
        # The ending credits use the "map" palette 1
        colours = self.palette_editor.sub_palette(0, 1)

        self._end_tiles = []

        # First, load the default map patterns
        address = 0x8000
        for i in range(256):
            pixels = bytes(self.rom.read_pattern(0xA, address))
            address += 16   # Each pattern is 16 bytes long

            # Create an empty 16x16 image (we will upscale the pattern and copy it here)
            image_2x = Image.new('P', (16, 16), 0)

            image_1x = Image.frombytes('P', (8, 8), pixels)

            image_1x.putpalette(colours)
            image_2x.putpalette(colours)

            # Scale the image
            image_2x.paste(image_1x.resize((16, 16), Image.NONE))

            # Cache this image
            self._end_tiles.append(ImageTk.PhotoImage(image_2x))

        # Import the custom fonts used for the end credits and overwrite cache as necessary

        try:
            bank = int(self.app.getEntry("EC_CHR_Bank"), 16)
        except ValueError:
            bank = 0xD
        if bank > 0xFF:
            self.app.soundError()
            self.app.getEntryWidget("EC_CHR_Bank").selection_range(0, "end")
            bank = 0xD

        try:
            address = int(self.app.getEntry("EC_CHR_Address"), 16)
        except ValueError:
            address = 0xBE00

        try:
            count = int(self.app.getEntry("EC_CHR_Count"))
        except TypeError or ValueError:
            count = 32

        try:
            first_chr = int(self.app.getEntry("EC_CHR_First"), 16)
        except ValueError:
            first_chr = 0x8A

        if first_chr + count > 256:
            count = 32
            first_chr = 0x8A
            self.app.errorBox("End Credits", "Character set overflow: please check count and first character index.",
                              "Credits_Editor")

        for i in range(first_chr, first_chr + count):
            pixels = bytes(self.rom.read_pattern(bank, address))
            address += 16  # Each pattern is 16 bytes long

            # Create an empty 16x16 image (we will upscale the pattern and copy it here)
            image_2x = Image.new('P', (16, 16), 0)

            image_1x = Image.frombytes('P', (8, 8), pixels)

            image_1x.putpalette(colours)
            image_2x.putpalette(colours)

            # Scale the image
            image_2x.paste(image_1x.resize((16, 16), Image.NONE))

            # Cache this image
            self._end_tiles[i] = ImageTk.PhotoImage(image_2x)

    # ------------------------------------------------------------------------------------------------------------------

    def _draw_end_preview(self, index: int) -> None:
        text = text_editor.ascii_to_exodus(self._end_credit_lines[index].text)
        x = self._end_credit_lines[index].x

        for pos in range(0, x):
            # Put blank characters before the string
            if self._end_items[pos] > 0:
                # Item exists, update image
                self._canvas_end.itemconfigure(self._end_items[pos], image=self._end_tiles[0])
            else:
                # Create item
                self._end_items[pos] = self._canvas_end.create_image(pos << 4, 0, anchor="nw", image=self._end_tiles[0])

        # Index within the string of bytes
        t = 0
        for pos in range(x, x + len(text)):
            if pos > 31:
                break

            # Draw text
            if text[t] == 0xFD or text[t] == 0xFF:
                character = 0
            else:
                character = text[t]

            if self._end_items[pos] > 0:
                # Item exists, update image
                self._canvas_end.itemconfigure(self._end_items[pos], image=self._end_tiles[character])
            else:
                # Create item
                self._end_items[pos] = self._canvas_end.create_image(pos << 4, 0, anchor="nw",
                                                                     image=self._end_tiles[character])

            # Next byte
            t += 1

        for pos in range(x + len(text), 32):
            # Put blank characters before the string
            if self._end_items[pos] > 0:
                # Item exists, update image
                self._canvas_end.itemconfigure(self._end_items[pos], image=self._end_tiles[0])
            else:
                # Create item
                self._end_items[pos] = self._canvas_end.create_image(pos << 4, 0, anchor="nw", image=self._end_tiles[0])
