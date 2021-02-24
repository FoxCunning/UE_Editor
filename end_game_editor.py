__author__ = "Fox Cunning"

import tkinter
from dataclasses import dataclass
from typing import List, Optional

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
    # Tile position on the screen
    x: int = 0
    y: int = 0
    # Screen index where this line is shown (opening credits only)
    # screen: int = 0
    # ASCII version of the text
    text: str = ""


# ----------------------------------------------------------------------------------------------------------------------

class EndGameEditor:

    # ------------------------------------------------------------------------------------------------------------------

    def __init__(self, app: gui, settings: EditorSettings, rom: ROM, palette_editor: PaletteEditor):
        self.app = app
        self.settings = settings
        self.rom = rom
        self.palette_editor = palette_editor

        # Each "screen" is a subset of lines, delimited by an empty line with Y position = 30
        self._opening_credits_screens: List[List[CreditLine]] = []
        self._opening_credits_lines: List[CreditLine] = []
        # Index for _opening_credits_screens
        self._selected_opening_screen: int = 0
        self._selected_opening_line: int = 0

        # CHR set used for opening credits: address, first character, count (bank is always 0xE)
        self._opening_credits_charset = [0xB200, 0x0A, 30]  # Will be set to all zeroes if not supported by ROM
        self._canvas_opening: Optional[tkinter.Canvas] = None
        self._canvas_tileset: Optional[tkinter.Canvas] = None
        # Cached PIL Image instances
        self._opening_tiles: List[ImageTk.PhotoImage] = []
        # Canvas item IDs
        self._opening_items: List[int] = []             # Preview canvas items
        self._opening_tileset_items: List[int] = []     # Tileset canvas items
        self._opening_tileset_rect: int = 0             # Rectangle for tile picker selection

        self._opening_selected_tile: int = 0            # Index of the currently selected tile

        # CHR set used for ending credits: ROM bank, address, first character, count
        self._end_credits_charset = [0xD, 0xBF00, 0x8A, 32]
        self._end_credits_lines: List[CreditLine] = []
        self._canvas_end: Optional[tkinter.Canvas] = None
        # Cached PIL Image instances
        self._end_tiles: List[ImageTk.PhotoImage] = []
        # Canvas item IDs
        self._end_items: List[int] = []
        self._selected_end_line: int = 0

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
            generator = self.app.subWindow("Credits_Editor", size=[600, 386], padding=[2, 2],
                                           title="Ultima: Exodus - Credits Editor",
                                           resizable=False, modal=False, blocking=False,
                                           bg=colour.DARK_GREY, fg=colour.WHITE,
                                           stopFunction=self.close_credits_window)

        self._unsaved_credits = False
        app = self.app
        font_bold = font.Font(font="TkFixedFont", size=11, weight="bold")
        font_mono = font.Font(font="TkFixedFont", size=10)

        # --- END Credits ---

        # Bank and address of CHR set
        self._end_credits_charset[0] = self.rom.read_byte(0xF, 0xE3FD)
        hi = self.rom.read_byte(0xF, 0xE402)
        lo = self.rom.read_byte(0xF, 0xE406)
        self._end_credits_charset[1] = (hi << 8) | lo

        # Destination in the PPU, we use this to calculate the index of the first character
        hi = self.rom.read_byte(0xF, 0xE40A)
        lo = self.rom.read_byte(0xF, 0xE40E)
        address = (hi << 8) | lo
        self._end_credits_charset[2] = (address - 0x1000) >> 4

        # Number of characters to load
        hi = self.rom.read_byte(0xF, 0xE412)
        lo = self.rom.read_byte(0xF, 0xE416)
        self._end_credits_charset[3] = ((hi << 8) | lo) >> 4

        # 32 canvas items used to preview a line of text
        self._end_items = [0] * 32

        count = self._read_end_credits()
        end_credits_list: List[str] = []
        for i in range(count):
            text = self._end_credits_lines[i].text
            if len(text) > 22:
                text = self._end_credits_lines[i].text[:22] + '\u2026'
            end_credits_list.append(f"#{i:03} '{text}'")

        # --- OPENING Credits ---

        # Make sure the ROM supports the extra patterns
        if self.rom.read_bytes(0xE, 0xB804, 3) != b'\x20\xE0\xB3':
            self.info("ROM does not support extra tiles in opening credits.")
            self._opening_credits_charset = [0, 0, 0]
        else:
            # Source address of CHR tileset
            hi = self.rom.read_byte(0xE, 0xB3E1)
            lo = self.rom.read_byte(0xE, 0xB3E5)
            self._opening_credits_charset[0] = (hi << 8) | lo
            # Destination address in PPU
            hi = self.rom.read_byte(0xE, 0xB3E9)
            lo = self.rom.read_byte(0xE, 0xB3ED)
            address = (hi << 8) | lo
            # Calculate first tile index using destination address
            self._opening_credits_charset[1] = (address >> 4) & 0xFF
            # Tile count = byte count / size of one tile (16 bytes)
            hi = self.rom.read_byte(0xE, 0xB3F5)
            lo = self.rom.read_byte(0xE, 0xB3F1)
            self._opening_credits_charset[2] = ((hi << 8) | lo) >> 4

        # 32 x 30 canvas items used to preview a whole screen
        self._opening_items = [0] * 960

        count = self._read_opening_credits()
        opening_credits_list: List[str] = self.opening_credits_list(count)

        with generator:

            with app.frame("EC_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0):

                app.button("EC_Apply", self._end_credits_input, image="res/floppy.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=1, sticky="W", tooltip="Save all changes")
                app.button("EC_Reload", self._end_credits_input, image="res/reload.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=2, sticky="W", tooltip="Reload from ROM buffer")
                app.button("EC_Close", self._end_credits_input, image="res/close.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=3, sticky="W", tooltip="Discard changes and close")

                app.canvas("EC_Canvas_Space", width=64, height=1, row=0, column=4)

                app.optionBox("EC_Option_Credits", ["Opening Credits", "End Credits"], change=self._end_credits_input,
                              row=0, column=5, font=11, sticky="E", width=24)

            with app.frameStack("EC_Stack", row=1, column=0, bg=colour.DARK_GREY):

                # OPENING CREDITS --------------------------------------------------------------------------------------

                with app.frame("EC_Frame_Opening_Credits", padding=[4, 2], bg=colour.DARK_GREEN, fg=colour.WHITE):

                    with app.frame("OC_Frame_Top", padding=[2, 2], sticky="NEW", row=0, column=0, colspan=2):
                        app.label("OC_Label_Address", "Extra tileset addr.:", row=0, column=0, font=10)
                        app.entry("OC_Tiles_Address", f"0x{self._opening_credits_charset[0]:04X}",
                                  submit=self._opening_credits_input, width=7, limit=6,
                                  row=0, column=1, sticky="W", font=9, bg=colour.MEDIUM_GREEN, fg=colour.WHITE)
                        app.label("OC_Label_Count", "Tiles count:", row=0, column=2, font=10)
                        app.entry("OC_Tiles_Count", self._opening_credits_charset[2], kind="numeric", limit=3,
                                  submit=self._opening_credits_input,
                                  row=0, column=3, sticky="W", font=9, width=6, bg=colour.MEDIUM_GREEN, fg=colour.WHITE)
                        app.label("OC_Label_First", "First tile ID:", row=0, column=4, font=10)
                        app.entry("OC_Tiles_First", f"0x{self._opening_credits_charset[1]:02X}",
                                  submit=self._opening_credits_input, width=7, limit=6,
                                  row=0, column=5, sticky="W", font=9, bg=colour.MEDIUM_GREEN, fg=colour.WHITE)
                        app.button("OC_Reload_Tiles", self._opening_credits_input, image="res/reload-small.gif",
                                   tooltip="Reload tilesets", bg=colour.MEDIUM_GREEN, sticky="W",
                                   row=0, column=6)

                    with app.frame("OC_Frame_Left", padding=[2, 2], sticky="NWS", row=1, column=0):
                        app.label("OC_Label_1", "Preview:", sticky="WE", row=0, column=0, font=12)
                        app.canvas("OC_Canvas_Preview", width=256, height=240, bg=colour.BLACK, sticky="N",
                                   row=1, column=0)

                    with app.frame("OC_Frame_Right", padding=[2, 2], sticky="NWS", row=1, column=1):
                        app.listBox("OC_List_Credits", opening_credits_list, height=6, width=28,
                                    multi=False, group=True,
                                    bg=colour.MEDIUM_GREEN, fg=colour.WHITE, change=self._opening_credits_input,
                                    row=0, column=0, rowspan=5, sticky="NWS", font=font_mono)

                        app.button("OC_Add", self._opening_credits_input, image="res/new-small.gif", sticky="NW",
                                   tooltip="Add a new screen",
                                   row=0, column=1, bg=colour.MEDIUM_GREEN)
                        app.button("OC_Remove", self._opening_credits_input, image="res/cross_red-small.gif",
                                   tooltip="Delete selected screen", sticky="NW",
                                   row=1, column=1, bg=colour.MEDIUM_GREEN)
                        app.button("OC_Delimiter", self._opening_credits_input, image="res/delimiter-small.gif",
                                   tooltip="Add a screen delimiter", sticky="NW",
                                   row=2, column=1, bg=colour.MEDIUM_GREEN)
                        app.button("OC_Move_Up", self._opening_credits_input, image="res/arrow_up-small.gif",
                                   tooltip="Move selection up", sticky="NSW",
                                   row=3, column=1, bg=colour.MEDIUM_GREEN)
                        app.button("OC_Move_Down", self._opening_credits_input, image="res/arrow_down-small.gif",
                                   tooltip="Move selection down", sticky="NSW",
                                   row=4, column=1, bg=colour.MEDIUM_GREEN)

                        with app.frame("OC_Frame_Position", padding=[2, 2], sticky="WE", row=5, column=0, colspan=2):
                            app.label("OC_Label_X", "X:", sticky="W", row=0, column=0, font=10)
                            app.entry("OC_Offset_X", 0, kind="numeric", limit=3, sticky="W",
                                      change=self._opening_credits_input,
                                      row=0, column=1, width=3, font=9, bg=colour.MEDIUM_GREEN, fg=colour.WHITE)
                            app.label("OC_Label_Y", "Y:", sticky="W", row=0, column=2, font=10)
                            app.entry("OC_Offset_Y", 0, kind="numeric", limit=3, sticky="W",
                                      change=self._opening_credits_input,
                                      row=0, column=3, width=3, font=9, bg=colour.MEDIUM_GREEN, fg=colour.WHITE)
                            app.button("OC_Centre_Line", self._opening_credits_input, text="\u2906 Centre Text \u2907",
                                       row=0, column=4, font=10, sticky="W", bg=colour.MEDIUM_GREEN, fg=colour.WHITE)

                        app.textArea("OC_Line_Text", "", width=32, height=3, bg=colour.MEDIUM_GREEN, fg=colour.WHITE,
                                     change=self._opening_credits_input,
                                     row=6, column=0, colspan=2, sticky="NW", font=font_bold)
                        app.canvas("OC_Canvas_Tileset", width=256, height=64, sticky="N", bg="#808080",
                                   row=7, column=0, colspan=2).bind("<ButtonRelease-1>", self._opening_tileset_click)

                # END CREDITS ------------------------------------------------------------------------------------------

                with app.frame("EC_Frame_End_Credits", padding=[4, 2], bg=colour.DARK_NAVY, fg=colour.WHITE):

                    with app.frame("EC_Frame_CHR", padding=[2, 2], row=0, column=0):

                        app.label("EC_Label_0", "CHR Set Bank:", sticky="E", row=0, column=0, font=10)
                        app.entry("EC_CHR_Bank", f"0x{self._end_credits_charset[0]:02X}",
                                  submit=self._opening_credits_input,
                                  sticky="W", width=6, row=0, column=1, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_1", "Address:", sticky="E", row=0, column=2, font=10)
                        app.entry("EC_CHR_Address", f"0x{self._end_credits_charset[1]:04X}",
                                  submit=self._opening_credits_input,
                                  row=0, column=3, sticky="W", width=8, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_2", "Characters:", sticky="E", row=0, column=4, font=10)
                        app.entry("EC_CHR_Count", self._end_credits_charset[3], kind="numeric", limit=4,
                                  submit=self._opening_credits_input,
                                  row=0, column=5, sticky="W", width=4, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_3", "First Character:", sticky="E", row=0, column=6, font=10)
                        app.entry("EC_CHR_First", f"0x{self._end_credits_charset[2]:02X}", limit=4,
                                  submit=self._end_credits_input, sticky="W",
                                  row=0, column=7, width=4, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.button("EC_Update_CHR", self._end_credits_input, image="res/reload-small.gif", sticky="W",
                                   row=0, column=8, tooltip="Update CHR Set", bg=colour.LIGHT_NAVY)

                    with app.frame("EC_Frame_List", padding=[4, 4], row=1, column=0):

                        app.listBox("EC_List_Credits", end_credits_list, change=self._end_credits_input,
                                    bg=colour.MEDIUM_NAVY, fg=colour.WHITE, multi=False, group=True,
                                    row=0, column=0, rowspan=4, colspan=2, width=30, height=10, font=font_mono)

                        app.label("EC_Label_4", "X Offset:", sticky="E", row=0, column=2, font=11)
                        app.entry("EC_Line_X", 0, kind="numeric", limit=4, sticky="W", width=4,
                                  change=self._end_credits_input,
                                  row=0, column=3, font=10, bg=colour.MEDIUM_NAVY, fg=colour.WHITE)
                        app.button("EC_Centre_Line", self._end_credits_input, text="\u2906 Centre Text \u2907",
                                   row=0, column=4, font=10, sticky="W", bg=colour.MEDIUM_NAVY, fg=colour.WHITE)

                        app.textArea("EC_Line_Text", "", sticky="NEWS", bg=colour.MEDIUM_NAVY, fg=colour.WHITE,
                                     row=1, column=2, colspan=3, height=5, font=font_bold
                                     ).bind("<KeyRelease>", lambda _e: self._end_credits_input("EC_Line_Text"), add='')
                        app.label("EC_Label_5", "'~' = End of line", sticky="NW",
                                  row=2, column=2, colspan=3, font=9)
                        app.label("EC_Label_6", "Newline = End of credits", sticky="NW",
                                  row=3, column=2, colspan=3, font=9)

                        app.button("EC_Button_Up", self._end_credits_input, image="res/arrow_up-small.gif", height=16,
                                   row=4, column=0, sticky="NEW")
                        app.button("EC_Button_Down", self._end_credits_input, image="res/arrow_down-small.gif",
                                   row=4, column=1, height=16, sticky="NEW")

                    app.label("EC_Label_7", "Preview:", sticky="WE", row=2, column=0, font=12)
                    app.canvas("EC_Canvas_Preview", map=None, width=512, height=16, bg=colour.BLACK,
                               row=3, column=0, sticky="N")

        self._canvas_opening = app.getCanvasWidget("OC_Canvas_Preview")
        self._canvas_tileset = app.getCanvasWidget("OC_Canvas_Tileset")
        self._canvas_end = app.getCanvasWidget("EC_Canvas_Preview")

        self._canvas_tileset.bind("<Motion>", self._opening_tileset_move)

        app.setCanvasCursor("OC_Canvas_Tileset", "hand1")

        self._load_opening_patterns()
        self._load_end_patterns()

        # Enable/disable widgets
        if self._opening_credits_charset[0] == 0:
            app.disableEntry("OC_Tiles_Address")
            app.disableEntry("OC_Tiles_Count")
            app.disableEntry("OC_Tiles_First")

        app.showSubWindow("Credits_Editor")

        # Default selection
        self._selected_opening_screen = -1
        app.setOptionBox("EC_Option_Credits", 0, callFunction=True)
        app.selectListItemAtPos("OC_List_Credits", 1, callFunction=True)

    # ------------------------------------------------------------------------------------------------------------------

    def show_end_game_window(self) -> None:
        self.app.infoBox("Endgame Editor", "Not yet implemented, sorry!")

    # ------------------------------------------------------------------------------------------------------------------

    def close_credits_window(self) -> None:
        self.app.hideSubWindow("Credits_Editor", useStopFunction=False)
        self.app.emptySubWindow("Credits_Editor")

        # Cleanup
        self._canvas_opening = None
        self._canvas_tileset = None
        self._opening_credits_screens = []
        self._opening_items = []
        self._opening_tiles = []
        self._opening_credits_lines = []
        self._opening_tileset_items = []

        self._end_credits_lines = []
        self._canvas_end = None
        self._end_tiles = []
        self._end_items = []

    # ------------------------------------------------------------------------------------------------------------------

    def opening_credits_list(self, count) -> List[str]:
        opening_credits_list: List[str] = []
        for i in range(count):
            if self._opening_credits_lines[i].y == 0x1E:
                opening_credits_list.append(f"#{i:03} ----------------------")
            else:
                text = self._opening_credits_lines[i].text
                if len(text) > 20:
                    text = self._opening_credits_lines[i].text[:19] + '\u2026'
                opening_credits_list.append(f"#{i:03} '{text}'")

        return opening_credits_list

    # ------------------------------------------------------------------------------------------------------------------

    def _opening_credits_input(self, widget: str) -> None:
        if widget == "OC_List_Credits":     # --------------------------------------------------------------------------
            selection = self.app.getListBoxPos(widget)

            if len(selection) < 1:
                return

            self._selected_opening_line = selection[0]
            line = self._opening_credits_lines[self._selected_opening_line]

            # Keep track of what the previously selected screen was: we will only update if we switch to another one
            prev_screen = self._selected_opening_screen

            # Set selected screen for the current line
            for s in range(len(self._opening_credits_screens)):
                if line in self._opening_credits_screens[s]:
                    self._selected_opening_screen = s

            self.app.clearEntry("OC_Offset_X", callFunction=False, setFocus=False)
            self.app.clearEntry("OC_Offset_Y", callFunction=False, setFocus=False)
            self.app.clearTextArea("OC_Line_Text", callFunction=False)

            self.app.setEntry("OC_Offset_X", line.x, callFunction=False)
            self.app.setEntry("OC_Offset_Y", line.y, callFunction=False)
            self.app.setTextArea("OC_Line_Text", line.text, callFunction=False)

            # Update preview
            if self._selected_opening_screen != prev_screen:
                self._draw_opening_preview(self._selected_opening_screen)

        elif widget == "OC_Line_Text":  # ------------------------------------------------------------------------------
            self._opening_credits_lines[self._selected_opening_line].text = self.app.getTextArea(widget).upper()
            # Update list item
            item = self._opening_credits_lines[self._selected_opening_line]
            self.app.setListItemAtPos("OC_List_Credits", self._selected_opening_line,
                                      f"#{self._selected_opening_line:03} " +
                                      ("----------------------" if item.y == 0x1E else f"'{item.text[:19]}'"))
            # Update preview
            self._draw_opening_preview(self._selected_opening_screen)

        elif widget == "OC_Offset_X":   # ------------------------------------------------------------------------------
            try:
                value = int(self.app.getEntry(widget))
                if 0 <= value <= 31:
                    self._opening_credits_lines[self._selected_opening_line].x = value
                    self._draw_opening_preview(self._selected_opening_screen)
                else:
                    self.app.soundError()
                    self.app.getEntryWidget(widget).selection_range(0, "end")
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget(widget).selection_range(0, "end")
            except TypeError:
                return

        elif widget == "OC_Offset_Y":   # ------------------------------------------------------------------------------
            try:
                value = int(self.app.getEntry(widget))
                if 0 <= value <= 31:
                    self._opening_credits_lines[self._selected_opening_line].y = value
                    self._draw_opening_preview(self._selected_opening_screen)
                else:
                    self.app.soundError()
                    self.app.getEntryWidget(widget).selection_range(0, "end")
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget(widget).selection_range(0, "end")
            except TypeError:
                return

        elif widget == "OC_Centre_Line":    # --------------------------------------------------------------------------
            line = self._opening_credits_lines[self._selected_opening_line]
            text = text_editor.ascii_to_exodus(line.text)
            value = len(text) - (1 if text[-1] == 0xFF else 0)
            self.app.clearEntry("OC_Offset_X", callFunction=False, setFocus=False)
            line.x = 16 - (value >> 1)
            self.app.setEntry("OC_Offset_X", line.x)
            self._draw_opening_preview(self._selected_opening_screen)

        elif widget == "OC_Remove":     # ------------------------------------------------------------------------------
            del self._opening_credits_lines[self._selected_opening_line]
            self.app.removeListItemAtPos("OC_List_Credits", self._selected_opening_line)
            self._split_opening_screens()
            self._draw_opening_preview(self._selected_opening_screen)

        elif widget == "OC_Delimiter":  # ------------------------------------------------------------------------------
            self._opening_credits_lines.insert(self._selected_opening_line, CreditLine(0, 0x1E, ""))
            # Recreate the list
            self.app.clearListBox("OC_List_Credits", False)
            self.app.addListItems("OC_List_Credits", self.opening_credits_list(len(self._opening_credits_lines)), False)
            self.app.selectListItemAtPos("OC_List_Credits", self._selected_opening_line, callFunction=True)
            # Update preview
            self._split_opening_screens()
            self._draw_opening_preview(self._selected_opening_screen)

        elif widget == "OC_Add":    # ----------------------------------------------------------------------------------
            self._opening_credits_lines.insert(self._selected_opening_line, CreditLine(12, 1, "NEW LINE"))
            # Recreate the list
            self.app.clearListBox("OC_List_Credits", False)
            self.app.addListItems("OC_List_Credits", self.opening_credits_list(len(self._opening_credits_lines)), False)
            self.app.selectListItemAtPos("OC_List_Credits", self._selected_opening_line, callFunction=True)
            # Update preview
            self._split_opening_screens()
            self._draw_opening_preview(self._selected_opening_screen)

        elif widget == "OC_Move_Up":    # ------------------------------------------------------------------------------
            if self._selected_opening_line == 0:
                return

            line_above = self._opening_credits_lines[self._selected_opening_line - 1]
            y_above = line_above.y
            y_below = self._opening_credits_lines[self._selected_opening_line].y

            self._opening_credits_lines[self._selected_opening_line - 1] =\
                self._opening_credits_lines[self._selected_opening_line]
            self._opening_credits_lines[self._selected_opening_line] = line_above

            # Exchange the Y values
            self._opening_credits_lines[self._selected_opening_line].y = y_below
            self._opening_credits_lines[self._selected_opening_line - 1].y = y_above

            # Recreate the list
            self.app.clearListBox("OC_List_Credits", False)
            self.app.addListItems("OC_List_Credits", self.opening_credits_list(len(self._opening_credits_lines)), False)
            self.app.selectListItemAtPos("OC_List_Credits", self._selected_opening_line, callFunction=True)

            self.app.selectListItemAtPos("OC_List_Credits", self._selected_opening_line - 1, True)

            # Update preview
            self._split_opening_screens()
            self._draw_opening_preview(self._selected_opening_screen)

        elif widget == "OC_Move_Down":  # ------------------------------------------------------------------------------
            if self._selected_opening_line >= len(self._opening_credits_lines):
                return

            line_below = self._opening_credits_lines[self._selected_opening_line + 1]
            y_below = line_below.y
            y_above = self._opening_credits_lines[self._selected_opening_line].y

            self._opening_credits_lines[self._selected_opening_line + 1] =\
                self._opening_credits_lines[self._selected_opening_line]
            self._opening_credits_lines[self._selected_opening_line] = line_below

            # Exchange the Y values
            self._opening_credits_lines[self._selected_opening_line].y = y_above
            self._opening_credits_lines[self._selected_opening_line + 1].y = y_below

            # Recreate the list
            self.app.clearListBox("OC_List_Credits", False)
            self.app.addListItems("OC_List_Credits", self.opening_credits_list(len(self._opening_credits_lines)), False)
            self.app.selectListItemAtPos("OC_List_Credits", self._selected_opening_line, callFunction=True)

            self.app.selectListItemAtPos("OC_List_Credits", self._selected_opening_line, True)

            # Update preview
            self._split_opening_screens()
            self._draw_opening_preview(self._selected_opening_screen)

        elif widget == "OC_Reload_Tiles" or widget[:9] == "OC_Tiles_":  # ----------------------------------------------
            self._load_opening_patterns()
            self._draw_opening_preview(self._selected_opening_screen)

        else:   # ------------------------------------------------------------------------------------------------------
            self.warning(f"Unimplemented input from Opening Credits widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _end_credits_input(self, widget: str) -> None:
        if widget == "EC_Apply":    # ----------------------------------------------------------------------------------
            if self._save_end_credits() and self._save_opening_credits():
                self._unsaved_credits = False
                self.app.setStatusbar("Credits data saved")
                if self.settings.get("close sub-window after saving"):
                    self.close_credits_window()

        elif widget == "EC_Close":  # ----------------------------------------------------------------------------------
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

            self._selected_end_line = index = selection[0]

            self.app.clearEntry("EC_Line_X", callFunction=False, setFocus=False)
            self.app.setEntry("EC_Line_X", self._end_credits_lines[index].x, callFunction=False)

            self.app.clearTextArea("EC_Line_Text", callFunction=False)
            self.app.setTextArea("EC_Line_Text", self._end_credits_lines[index].text.upper(), callFunction=False)

            # Update list item and also redraw the preview
            text = self._end_credits_lines[self._selected_end_line].text.upper()
            if len(text) > 22:
                text = text[:22] + '\u2026'
            self.app.setListItemAtPos(widget, self._selected_end_line, f"#{self._selected_end_line:03} '{text}'")

            self._draw_end_preview(index)

        elif widget == "EC_Line_Text":  # ------------------------------------------------------------------------------
            self._end_credits_lines[self._selected_end_line].text = self.app.getTextArea(widget).upper()

            # Update list item and also redraw the preview
            text = self._end_credits_lines[self._selected_end_line].text
            if len(text) > 22:
                text = text[:22] + '\u2026'
            self.app.setListItemAtPos("EC_List_Credits", self._selected_end_line,
                                      f"#{self._selected_end_line:03} '{text}'")

            self._draw_end_preview(self._selected_end_line)
            self._unsaved_credits = True

        elif widget == "EC_Button_Up":  # ------------------------------------------------------------------------------
            if self._selected_end_line == 0:
                # Already at the top
                return

            line_above = self._end_credits_lines[self._selected_end_line - 1]
            selected_line = self._end_credits_lines[self._selected_end_line]

            # Swap lines
            self._end_credits_lines[self._selected_end_line - 1] = selected_line
            self._end_credits_lines[self._selected_end_line] = line_above

            # Update list
            self.app.setListItemAtPos("EC_List_Credits", self._selected_end_line - 1,
                                      f"#{(self._selected_end_line - 1):03} '{selected_line.text}'")
            self.app.setListItemAtPos("EC_List_Credits", self._selected_end_line,
                                      f"#{self._selected_end_line:03} '{line_above.text}'")

            self._unsaved_credits = True

            # Re-select moved line
            self.app.selectListItemAtPos("EC_List_Credits", self._selected_end_line - 1, callFunction=True)
            self.app.getListBoxWidget("EC_List_Credits").selection_set(self._selected_end_line)

        elif widget == "EC_Button_Down":    # --------------------------------------------------------------------------
            if self._selected_end_line >= len(self._end_credits_lines) - 1:
                # Already at the bottom
                return

            line_below = self._end_credits_lines[self._selected_end_line + 1]
            selected_line = self._end_credits_lines[self._selected_end_line]

            # Swap lines
            self._end_credits_lines[self._selected_end_line + 1] = selected_line
            self._end_credits_lines[self._selected_end_line] = line_below

            # Update list
            self.app.setListItemAtPos("EC_List_Credits", self._selected_end_line + 1,
                                      f"#{(self._selected_end_line + 1):03} '{selected_line.text}'")
            self.app.setListItemAtPos("EC_List_Credits", self._selected_end_line,
                                      f"#{self._selected_end_line:03} '{line_below.text}'")

            self._unsaved_credits = True

            # Re-select moved line
            self.app.selectListItemAtPos("EC_List_Credits", self._selected_end_line + 1, callFunction=True)
            self.app.getListBoxWidget("EC_List_Credits").selection_set(self._selected_end_line)

        elif widget == "EC_Line_X":     # ------------------------------------------------------------------------------
            value = self.app.getEntry(widget)
            if value is not None:
                self._end_credits_lines[self._selected_end_line].x = int(value)
                self._draw_end_preview(self._selected_end_line)
                self._unsaved_credits = True

        elif widget == "EC_Centre_Line":    # --------------------------------------------------------------------------
            text = text_editor.ascii_to_exodus(self._end_credits_lines[self._selected_end_line].text)
            size = len(text[:32])
            self._end_credits_lines[self._selected_end_line].x = 16 - (size >> 1)
            self._draw_end_preview(self._selected_end_line)
            self._unsaved_credits = True

        elif (widget == "EC_CHR_Bank" or widget == "EC_CHR_Address" or widget == "EC_CHR_Count" or
              widget == "EC_CHR_First" or widget == "EC_Update_CHR"):   # ----------------------------------------------
            self._load_end_patterns()
            self._draw_end_preview(self._selected_end_line)
            self._unsaved_credits = True

        elif widget == "EC_Reload":     # ------------------------------------------------------------------------------
            if self._unsaved_credits:
                if not self.app.yesNoBox("Credits Editor", "Are you sure you want to reload all data from ROM?\n" +
                                         "Any changes made so far will be lost.", "Credits_Editor"):
                    return

            self._unsaved_credits = False

            # Bank and address of CHR set
            self._end_credits_charset[0] = self.rom.read_byte(0xF, 0xE3FD)
            hi = self.rom.read_byte(0xF, 0xE402)
            lo = self.rom.read_byte(0xF, 0xE406)
            self._end_credits_charset[1] = (hi << 8) | lo

            # Destination in the PPU, we use this to calculate the index of the first character
            hi = self.rom.read_byte(0xF, 0xE40A)
            lo = self.rom.read_byte(0xF, 0xE40E)
            address = (hi << 8) | lo
            self._end_credits_charset[2] = (address - 0x1000) >> 4

            # Number of characters to load
            hi = self.rom.read_byte(0xF, 0xE412)
            lo = self.rom.read_byte(0xF, 0xE416)
            self._end_credits_charset[3] = ((hi << 8) | lo) >> 4

            # Re-read all credit lines
            count = self._read_end_credits()
            end_credits_list: List[str] = []
            for i in range(count):
                text = self._end_credits_lines[i].text
                if len(text) > 22:
                    text = self._end_credits_lines[i].text[:22] + '\u2026'
                end_credits_list.append(f"#{i:03} '{text}'")

            self.app.clearEntry("EC_CHR_Bank", callFunction=False, setFocus=False)
            self.app.clearEntry("EC_CHR_Address", callFunction=False, setFocus=False)
            self.app.clearEntry("EC_CHR_Count", callFunction=False, setFocus=False)
            self.app.clearEntry("EC_CHR_First", callFunction=False, setFocus=False)

            self.app.setEntry("EC_CHR_Bank", f"0x{self._end_credits_charset[0]:02X}", callFunction=False)
            self.app.setEntry("EC_CHR_Address", f"0x{self._end_credits_charset[1]:04X}", callFunction=False)
            self.app.setEntry("EC_CHR_Count", self._end_credits_charset[3], callFunction=False)
            self.app.setEntry("EC_CHR_First", f"0x{self._end_credits_charset[2]:02X}", callFunction=False)

            self._load_end_patterns()

            self.app.clearListBox("EC_List_Credits", callFunction=False)
            self.app.addListItems("EC_List_Credits", end_credits_list, select=False)
            self.app.selectListItemAtPos("EC_List_Credits", 0, callFunction=True)

        else:   # ------------------------------------------------------------------------------------------------------
            self.warning(f"Unimplemented input from Credits Editor widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _opening_tileset_click(self, _event) -> None:
        value = text_editor.exodus_to_ascii(bytearray([self._opening_selected_tile]))
        widget = self.app.getTextAreaWidget("OC_Line_Text")
        widget.insert(widget.index(tkinter.INSERT), value)

    # ------------------------------------------------------------------------------------------------------------------

    def _opening_tileset_move(self, event) -> None:
        x = event.x >> 3
        y = event.y >> 3
        t = x + (y << 5)
        if t == self._opening_selected_tile:
            # Selection unchanged
            return

        self._opening_selected_tile = t

        x = x << 3
        y = y << 3
        self._canvas_tileset.coords(self._opening_tileset_rect, x, y, x + 7, y + 7)

    # ------------------------------------------------------------------------------------------------------------------

    def _save_opening_credits(self) -> bool:
        """
        Returns
        -------
        bool
            True if data was successfully saved. False if something prevents saving (e.g. won't fit in ROM).
        """
        # We will store all data here until we know it's safe to transfer to the ROM buffer
        buffer = bytearray()

        for line in self._opening_credits_lines:
            buffer.append(line.x)
            buffer.append(line.y)
            if line.y == 0x1E:  # End of screen
                buffer.append(0xFF)
            elif line.y == 0x1F:  # End of credits
                buffer.append(0xFF)
                break
            else:
                buffer += text_editor.ascii_to_exodus(line.text)

        # Make sure the "end of credits" marker is present
        if buffer[-2:] != b'\x1F\xFF':
            buffer.append(0x00)
            buffer.append(0x1F)
            buffer.append(0xFF)

        # And finally make sure it will fit in the allocated space
        if len(buffer) > 235:
            self.app.errorBox("Credits Editor", "Buffer overflow: the opening credits will not fit in ROM.\n" +
                              f"There are {len(buffer) - 253} extra bytes.", "Credits_Editor")
            return False

        # Now se can safely save our data to ROM
        self.rom.write_bytes(0xE, 0xBB2D, buffer)

        # If the ROM supports it, save extra tileset data
        if self._opening_credits_charset[0] != 0:
            lo = self._opening_credits_charset[0] & 0xFF
            hi = self._opening_credits_charset[0] >> 8

            self.rom.write_byte(0xE, 0xB3E1, hi)
            self.rom.write_byte(0xE, 0xB3E5, lo)

            lo = (self._opening_credits_charset[1] << 4) & 0xFF
            hi = 0x10 | (self._opening_credits_charset[1] >> 4)

            self.rom.write_byte(0xE, 0xB3E9, hi)
            self.rom.write_byte(0xE, 0xB3ED, lo)

            size = self._opening_credits_charset[2] << 4
            lo = size & 0xFF
            hi = size >> 8

            self.rom.write_byte(0xE, 0xB3F1, lo)
            self.rom.write_byte(0xE, 0xB3F5, hi)

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def _read_opening_credits(self) -> int:
        self._opening_credits_lines.clear()

        address = 0xBB2D

        while True:
            line = CreditLine()

            line.x = self.rom.read_byte(0xE, address)
            address += 1

            line.y = self.rom.read_byte(0xE, address)
            address += 1

            text = bytearray()
            while address < 0xBC17:
                value = self.rom.read_byte(0xE, address)
                address += 1
                text.append(value)
                if value == 0xFF:   # End of line
                    line.text = text_editor.exodus_to_ascii(text)
                    break

            self._opening_credits_lines.append(line)

            if line.y == 0x1F:  # End of credits
                break

        self._split_opening_screens()

        return len(self._opening_credits_lines) - 1

    # ------------------------------------------------------------------------------------------------------------------

    def _split_opening_screens(self) -> None:
        self._opening_credits_screens.clear()

        screen: List[CreditLine] = []

        for line in self._opening_credits_lines:
            if line.y == 0x1E:
                self._opening_credits_screens.append(screen)
                screen = []
            elif line.y == 0x1F:
                self._opening_credits_screens.append(screen)
                return
            else:
                screen.append(line)

    # ------------------------------------------------------------------------------------------------------------------

    def _save_end_credits(self) -> bool:

        # Create a buffer with all the encoded text, then make sure it fits the allocated area
        buffer = bytearray()

        # We will give a warning if there is no credits termination character 0xFD in any string
        terminator_found: bool = False

        for line in self._end_credits_lines:
            buffer.append(line.x)
            text = text_editor.ascii_to_exodus(line.text)

            buffer = buffer + text

            if not terminator_found and text.rfind(0xFD) != -1:
                terminator_found = True

            # Make sure each string has the mandatory string termination character
            if text[-1] != 0xFF:
                buffer.append(0xFF)

        if len(buffer) > 1253:
            self.app.errorBox("Credits Editor", "Buffer overflow: the end credits will not fit in ROM.\n" +
                              f"There are {len(buffer) - 1253} extra characters.", "Credits_Editor")
            return False

        if not terminator_found:
            if not self.app.yesNoBox("Credits Editor", "None of the credit strings contain a 'newline' " +
                                     "character.\nThis means the credits will read parts of the ROM beyond the text." +
                                     "\nAre you sure you want to continue?", "Credits_Editor"):
                return False

        # Merge this buffer into the ROM buffer
        self.rom.write_bytes(0x6, 0x9A1B, buffer)

        # Save patterns bank, address, destination and size
        self.rom.write_byte(0xF, 0xE3FD, self._end_credits_charset[0])
        hi = self._end_credits_charset[1] >> 8
        lo = self._end_credits_charset[1] & 0x00FF
        self.rom.write_byte(0xF, 0xE402, hi)
        self.rom.write_byte(0xF, 0xE406, lo)

        # Destination in the PPU, we use this to calculate the index of the first character
        address = 0x1000 | (self._end_credits_charset[2] << 4)
        self.rom.write_byte(0xF, 0xE40A, address >> 8)
        self.rom.write_byte(0xF, 0xE40E, address & 0x00FF)

        # Number of bytes in the charset
        count = self._end_credits_charset[3] << 4
        self.rom.write_byte(0xF, 0xE412, count >> 8)
        self.rom.write_byte(0xF, 0xE416, count & 0x00FF)

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def _read_end_credits(self) -> int:
        """
        Returns
        -------
        int
            The number of credit lines found in ROM.
        """
        self._end_credits_lines = []

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

            self._end_credits_lines.append(line)
            count += 1

        return count

    # ------------------------------------------------------------------------------------------------------------------

    def _load_opening_patterns(self) -> None:
        """
        Reads pattern data used for the opening credits and stores it in image instances that can be used on a canvas.
        """
        # The ending credits use the "map" palette 1
        colours = self.palette_editor.sub_palette(8, 1)

        self._opening_tiles = []

        # First, load the default map patterns
        address = 0x8000
        for i in range(256):
            pixels = bytes(self.rom.read_pattern(0xA, address))
            address += 16  # Each pattern is 16 bytes long

            image_1x = Image.frombytes('P', (8, 8), pixels)
            image_1x.putpalette(colours)

            # Cache this image
            self._opening_tiles.append(ImageTk.PhotoImage(image_1x))

        if self._opening_credits_charset[0] == 0:
            # ROM does not support extra patterns for the opening credits
            return

        # Import the extra tiles used for the opening credits and overwrite cache as necessary
        try:
            address = int(self.app.getEntry("OC_Tiles_Address"), 16)
            if address < 0x8000 or address > 0xBFFF:
                self.app.soundError()
                self.app.getEntryWidget("OC_Tiles_Address").selection_range(0, "end")
                return
            self._opening_credits_charset[0] = address

        except ValueError:
            self.app.soundError()
            self.app.getEntryWidget("OC_Tiles_Address").selection_range(0, "end")
            return
        except TypeError:
            return

        try:
            first = int(self.app.getEntry("OC_Tiles_First"), 16)
            if first < 0:
                self.app.soundError()
                self.app.getEntryWidget("OC_Tiles_First").selection_range(0, "end")
                return
            self._opening_credits_charset[1] = first

        except ValueError:
            self.app.soundError()
            self.app.getEntryWidget("OC_Tiles_First").selection_range(0, "end")
            return
        except TypeError:
            return

        try:
            count = int(self.app.getEntry("OC_Tiles_Count"))
            if count < 0 or count > 255:
                self.app.soundError()
                self.app.getEntryWidget("OC_Tiles_Count").selection_range(0, "end")
                return
            self._opening_credits_charset[2] = count

        except ValueError:
            self.app.soundError()
            self.app.getEntryWidget("OC_Tiles_Count").selection_range(0, "end")
            return
        except TypeError:
            return

        if first + count > 255:
            self.app.errorBox("Opening Credits",
                              "Tileset overflow: please check count and first character index.",
                              "Credits_Editor")
            return

        for i in range(first, first + count):
            pixels = bytes(self.rom.read_pattern(0xE, address))
            address += 16  # Each pattern is 16 bytes long

            image_1x = Image.frombytes('P', (8, 8), pixels)

            image_1x.putpalette(colours)

            # Cache this image
            self._opening_tiles[i] = ImageTk.PhotoImage(image_1x)

        # Show the entire tileset in our tile picker
        canvas = self.app.getCanvasWidget("OC_Canvas_Tileset")

        self._opening_tileset_items = [0] * 256

        x = 0   # X position on canvas
        y = 0   # Y position on canvas
        i = 0   # Item index / CHR ID
        for tile in self._opening_tiles:

            if self._opening_tileset_items[i] > 0:
                # Item exists: update image
                canvas.itemconfigure(self._opening_tileset_items[i], image=tile)
            else:
                # Create new item
                self._opening_tileset_items[i] = canvas.create_image(x, y, anchor="nw", image=tile)

            # Advance coordinates
            x += 8
            if x >= 256:
                x = 0
                y += 8
            i += 1

        # Selection rectangle
        self._opening_selected_tile = 0
        self._opening_tileset_rect = canvas.create_rectangle(0, 0, 7, 7, width=1, outline="#FF1010")

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
        except (ValueError, TypeError):
            bank = 0xD
        if bank > 0xFF:
            self.app.soundError()
            self.app.getEntryWidget("EC_CHR_Bank").selection_range(0, "end")
            bank = 0xD

        self._end_credits_charset[0] = bank

        try:
            address = int(self.app.getEntry("EC_CHR_Address"), 16)
        except (ValueError, TypeError):
            address = 0xBE00

        self._end_credits_charset[1] = address

        try:
            count = int(self.app.getEntry("EC_CHR_Count"))
        except TypeError or ValueError:
            count = 32

        try:
            first_chr = int(self.app.getEntry("EC_CHR_First"), 16)
        except (ValueError, TypeError):
            first_chr = 0x8A

        if first_chr + count > 256:
            count = 32
            first_chr = 0x8A
            self.app.errorBox("End Credits", "Character set overflow: please check count and first character index.",
                              "Credits_Editor")

        self._end_credits_charset[2] = first_chr
        self._end_credits_charset[3] = count

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

    def _draw_opening_preview(self, index: int) -> None:
        """

        Parameters
        ----------
        index: int
            Index of the screen (list of lines) to be previewed
        """
        # Clear screen first
        for item in self._opening_items:
            if item > 0:
                self._canvas_opening.itemconfigure(item, image=self._opening_tiles[0])

        # Preview the currently selected screen
        for line in self._opening_credits_screens[index]:
            text = text_editor.ascii_to_exodus(line.text)
            x = line.x
            y = line.y

            # Index within the string of bytes for the current line
            t = 0
            start = x + (y << 5)
            for pos in range(start, start + len(text)):
                if pos >= 960:    # Avoid drawing outside the screen
                    break

                # Draw text
                if text[t] == 0xFD or text[t] == 0xFF:
                    # Skip to next line
                    break
                else:
                    character = text[t]

                if self._opening_items[pos] > 0:
                    # Item exists: update image
                    self._canvas_opening.itemconfigure(self._opening_items[pos], image=self._opening_tiles[character])
                else:
                    # Create canvas item
                    self._opening_items[pos] = self._canvas_opening.create_image(x << 3, y << 3, anchor="nw",
                                                                                 image=self._opening_tiles[character])
                x += 1

                # Next byte in current string
                t += 1

    # ------------------------------------------------------------------------------------------------------------------

    def _draw_end_preview(self, index: int) -> None:
        text = text_editor.ascii_to_exodus(self._end_credits_lines[index].text)
        x = self._end_credits_lines[index].x

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
