__author__ = "Fox Cunning"

from typing import List

from PIL import Image

import colour
from appJar import gui


# ----------------------------------------------------------------------------------------------------------------------
from appJar.appjar import ItemLookupError
from debug import log
from rom import ROM


class BattlefieldEditor:

    # ------------------------------------------------------------------------------------------------------------------

    def __init__(self, app: gui, rom: ROM):
        self.app = app
        self.rom = rom

        self._unsaved_changes = False

        self._map_address: List[int] = []

        # TODO Maybe read these from a customised (optional) text file
        self._map_names: List[str] = ["Grass", "Brush", "Forest", "North: Water, South: Land",
                                      "North: Ship, South: Land", "Door", "Stone Floor 1", "Lava",
                                      "Wall", "Table", "Chest", "Stone Floor 2", "Wall Top", "Castle / Dungeon",
                                      "Dungeon Entrance", "Town", "Player Ship", "Naval Battle",
                                      "North: Land, South: Ship"]

        # Map being currently edited. Only modify this in show_window() and close_window().
        self._selected_map = 0

        # Current pick to put on the map when drawing
        self._selected_tile = 0
        # Index of the last map entry that was modified or selected
        self._last_edited = 0

        # Logical map data (i.e. tile indices 0x0-0xF)
        self._map_data: List[int] = []

        # Image cache
        self._patterns_cache: List[Image] = []

        # Canvas item IDs
        self._tiles_grid: List[int] = [0] * 16
        self._tile_items: List[int] = [0] * 8
        self._tile_rectangle: int = 0
        self._map_grid: List[int] = [0] * 8 * 11
        self._map_items: List[int] = [0] * 9 * 12
        self._map_rectangle: int = 0

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

    def show_window(self, map_index: int = -1) -> None:
        """
        Opens the graphical battlefield editor.

        Parameters
        ----------
        map_index: int
            Index of the map to edit, or -1 to edit the last selected map
        """
        if map_index >= 0:
            self._selected_map = map_index
        else:
            map_index = self._selected_map

        self._read_map_data(self._map_address[map_index])

        # Create widgets if needed
        try:
            self.app.getCanvasWidget("BE_Canvas_Map")
        except ItemLookupError:
            self._create_widgets()
            # TODO Assign event handlers to canvases

        self.app.showSubWindow("Battlefield_Editor", hide=False)

    # ------------------------------------------------------------------------------------------------------------------

    def close_window(self) -> bool:
        """
        Closes the battlefield editor window and destroys its widgets.

        Returns
        -------
        bool
            True if the window was closed. False if cancelled by user.
        """
        if self._unsaved_changes is True:
            if self.app.yesNoBox("Battlefield Editor",
                                 "Are you sure you want to close this window?\nUnsaved changes will be lost.",
                                 parent="Battlefield_Editor") is False:
                return False

        self.app.hideSubWindow("Battlefield_Editor")
        self.app.emptySubWindow("Battlefield_Editor")

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def _create_widgets(self) -> None:
        with self.app.subWindow("Battlefield_Editor"):
            # noinspection PyArgumentList
            self.app.setStopFunction(self.close_window)

            with self.app.frame("BE_Frame_Buttons", padding=[4, 2], row=0, column=0):
                self.app.button("BE_Button_Save", self.map_input, image="res/floppy.gif", width=32, height=32,
                                tooltip="Save Changes and Close",
                                sticky="E", row=0, column=0)
                self.app.button("BE_Button_Cancel", self.map_input, image="res/close.gif", width=32, height=32,
                                tooltip="Cancel and Close Window",
                                sticky="W", row=0, column=1)

            with self.app.frame("BE_Frame_Tiles", padding=[4, 2], row=1, column=0):
                self.app.canvas("BE_Canvas_Tiles", width=256, height=64, row=0, column=0, bg="#808080")
                self.app.setCanvasCursor("BE_Canvas_Tiles", "hand2")
                self.app.label("BE_Tile_Info", "", sticky="WE", row=1, column=0, font=10, fg=colour.BLACK)

            with self.app.frame("BE_Frame_Map", padding=[4, 2], row=2, column=0):
                self.app.canvas("BE_Canvas_Map", width=288, height=384, row=0, column=0, bg="#808080")
                self.app.setCanvasCursor("BE_Canvas_Map", "pencil")

    # ------------------------------------------------------------------------------------------------------------------

    def _load_patterns(self) -> None:
        self.warning("Unimplemented function: _load_patterns.")

    # ------------------------------------------------------------------------------------------------------------------

    def get_map_names(self) -> List[str]:
        return self._map_names.copy()

    # ------------------------------------------------------------------------------------------------------------------

    def save_tab_data(self) -> None:
        self.warning("Unimplemented function: save_tab_data.")

    # ------------------------------------------------------------------------------------------------------------------

    def map_input(self, widget: str) -> None:
        if widget == "BE_Button_Cancel":
            self.close_window()

        else:
            self.warning(f"Unimplemented input from map widget: '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def read_tab_data(self) -> None:
        if self.rom.read_byte(0xF, 0xC7ED) == 0xBD:
            table_address = self.rom.read_word(0xF, 0xC7EE)
        else:
            self.warning("Couldn't read battlefield maps address table pointer.\nUsing default value.")
            table_address = 0xCEAC

        self._map_address.clear()
        for a in range(19):
            self._map_address.append(self.rom.read_word(0xF, table_address))
            table_address = table_address + 2

        # Battle music
        data = self.rom.read_bytes(0xF, 0xC7F7, 2)
        if data[0] == 0xA9:
            self.app.setOptionBox("Battlefield_Option_Music", data[1] & 0x7F, callFunction=False)

    # ------------------------------------------------------------------------------------------------------------------

    def get_map_address(self, map_index: int = -1) -> int:
        if map_index == -1:
            map_index = self._selected_map

        try:
            return self._map_address[map_index]
        except IndexError:
            return 0

    # ------------------------------------------------------------------------------------------------------------------

    def _read_map_data(self, address: int) -> None:
        # Clear previous data
        self._map_data.clear()

        # We need to skip the first and last row
        address = address + 16
        # We will also skip the first column, and anything after the first 10 tiles in each row
        for y in range(13):
            for x in range(16):
                if x == 0:
                    # Skip first column
                    address = address + 1
                    continue

                if x > 9:
                    address = address + 1
                    continue

                tile = self.rom.read_byte(0x4, address) & 0x0F
                self._map_data.append(tile)
                address = address + 1

    # ------------------------------------------------------------------------------------------------------------------

    def draw_map(self) -> None:
        pass
