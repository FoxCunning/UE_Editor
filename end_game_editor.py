__author__ = "Fox Cunning"

from dataclasses import dataclass
from typing import List

import appJar
import colour
from tkinter import font
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
        # Canvas item IDs
        self._end_tiles: List[int] = []

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
            generator = self.app.subWindow("Credits_Editor", size=[600, 460], padding=[2, 2], title="Credits Editor",
                                           resizable=False, modal=False, blocking=False,
                                           bg=colour.DARK_GREY, fg=colour.WHITE,
                                           stopFunction=self.close_credits_window)

        app = self.app
        font_bold = font.Font(font="TkFixedFont", size=11, weight="bold")

        # 32 canvas items used to preview a line of text
        self._end_tiles = [0] * 32

        with generator:
            with app.frame("EC_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0):
                app.button("EC_Apply", self._credits_input, image="res/floppy.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=1, tooltip="Save all changes")
                app.button("EC_Reload", self._credits_input, image="res/reload.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=2, tooltip="Reload from ROM buffer")
                app.button("EC_Close", self._credits_input, image="res/close.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=3, tooltip="Discard changes and close")

            app.optionBox("EC_Option_Credits", ["Opening Credits", "End Credits"], change=self._credits_input,
                          row=1, column=0, font=10, sticky="N", width=24)

            with app.frameStack("EC_Stack", row=2, column=0, bg=colour.DARK_GREY):

                with app.frame("EC_Frame_Opening_Credits", padding=[4, 2], bg=colour.DARK_GREEN, fg=colour.WHITE):
                    app.label("OC_Label_0", "NOT YET IMPLEMENTED", font=12)

                with app.frame("EC_Frame_End_Credits", padding=[4, 2], bg=colour.DARK_NAVY, fg=colour.WHITE):

                    with app.frame("EC_Frame_CHR", padding=[2, 2], row=0, column=0):
                        app.label("EC_Label_0", "CHR Set Bank:", sticky="E", row=0, column=0, font=10)
                        app.entry("EC_CHR_Bank", "0xD", submit=self._credits_input, sticky="W", width=6,
                                  row=0, column=1, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_1", "Address:", sticky="E", row=0, column=2, font=10)
                        app.entry("EC_CHR_Address", "0xBE00", submit=self._credits_input, sticky="W", width=8,
                                  row=0, column=3, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_2", "Characters:", sticky="E", row=0, column=4, font=10)
                        app.entry("EC_CHR_Count", 26, kind="numeric", limit=4, submit=self._credits_input, sticky="W",
                                  row=0, column=5, width=4, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.label("EC_Label_3", "First Character:", sticky="E", row=0, column=6, font=10)
                        app.entry("EC_CHR_First", "0x8A", limit=4, submit=self._credits_input, sticky="W",
                                  row=0, column=7, width=4, bg=colour.MEDIUM_NAVY, fg=colour.WHITE, font=9)

                        app.button("EC_Update_CHR", self._credits_input, image="res/reload-small.gif", sticky="W",
                                   row=0, column=8, tooltip="Update CHR Set", bg=colour.LIGHT_NAVY)

                    with app.frame("EC_Frame_List", padding=[4, 4], row=1, column=0):
                        app.listBox("EC_List_Credits", ["TEST #0", "TEST #1"], change=self._credits_input,
                                    bg=colour.MEDIUM_NAVY, fg=colour.WHITE, multi=False, group=True,
                                    row=0, column=0, rowspan=2, width=24, height=10, font=10)

                        app.label("EC_Label_4", "X Offset:", sticky="E", row=0, column=1, font=11)
                        app.entry("EC_Line_X", 0, kind="numeric", limit=4, sticky="W", width=4,
                                  row=0, column=2, font=10, bg=colour.MEDIUM_NAVY, fg=colour.WHITE)

                        app.textArea("EC_Line_Text", "TEST #0", sticky="NEWS",
                                     row=1, column=1, colspan=3, font=font_bold,
                                     bg=colour.MEDIUM_NAVY, fg=colour.WHITE)

                    app.canvas("EC_Canvas_Preview", map=None, width=512, height=16, bg=colour.BLACK,
                               row=2, column=0, sticky="N")

        self._canvas_end = app.getCanvasWidget("EC_Canvas_Preview")

        # TODO Remove this once the opening credits widgets have been added
        app.setOptionBox("EC_Option_Credits", 1, callFunction=True)

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

        self._opening_credit_lines = []

    # ------------------------------------------------------------------------------------------------------------------

    def _credits_input(self, widget: str) -> None:
        if widget == "EC_Close":    # ----------------------------------------------------------------------------------
            self.close_credits_window()

        elif widget == "EC_Option_Credits":
            index = self._get_selection_index(widget)
            self.app.selectFrame("EC_Stack", index, callFunction=False)

        else:   # ------------------------------------------------------------------------------------------------------
            self.warning(f"Unimplemented input from Credits Editor widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _read_end_credits(self) -> None:
        pass

    # ------------------------------------------------------------------------------------------------------------------

    def _load_end_patterns(self) -> None:
        """
        Reads pattern data used for the end credits and stores it in image instances that can be used on a canvas.
        """
        pass
