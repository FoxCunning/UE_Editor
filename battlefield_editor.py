__author__ = "Fox Cunning"

from tkinter import Canvas
from typing import List

from PIL import Image, ImageTk

import colour
from appJar import gui


# ----------------------------------------------------------------------------------------------------------------------
from appJar.appjar import ItemLookupError
from debug import log
from palette_editor import PaletteEditor
from rom import ROM


class BattlefieldEditor:

    # ------------------------------------------------------------------------------------------------------------------

    def __init__(self, app: gui, rom: ROM, palette_editor: PaletteEditor):
        self.app = app
        self.rom = rom
        self.palette_editor = palette_editor

        self._unsaved_changes = False

        self._map_address: List[int] = []

        # TODO Maybe read these from a customised (optional) text file
        self._map_names: List[str] = ["Grass", "Brush", "Forest", "Player vs Sea Monsters",
                                      "Player vs Pirate Ship", "Door", "Stone Floor 1", "Lava",
                                      "Wall", "Table", "Chest", "Stone Floor 2", "Wall Top", "Castle / Dungeon",
                                      "Dungeon Entrance", "Town", "Player Ship vs Sea Monsters",
                                      "Player Ship vs Pirate Ship",
                                      "Player Ship vs Land Enemies"]

        # Pattern info
        self._pattern_info: List[str] = ["Normal", "Normal", "Normal", "Water", "Blocking", "Normal", "Normal",
                                         "Normal", "Blocking", "Blocking", "Normal", "Normal", "Blocking", "Normal",
                                         "Normal", "Normal"]

        # Map being currently edited. Only modify this in show_window() and close_window().
        self._selected_map = 0

        # Current pick to put on the map when drawing
        self._selected_tile = 0
        # Index of the last map entry that was modified or selected
        self._last_edited = 0

        # Logical map data (i.e. tile indices 0x0-0xF)
        self._map_data: List[int] = []

        self._grid_colour = "#C0C0C0"

        # Image cache
        self._patterns_cache: List[ImageTk.PhotoImage] = []

        # Canvas item IDs
        self._tiles_grid: List[int] = [0] * 16
        self._tile_items: List[int] = [0] * 16
        self._tile_rectangle: int = 0
        self._map_grid: List[int] = [0] * 8 * 12
        self._map_items: List[int] = [0] * 9 * 13
        self._map_rectangle: int = 0

        self._canvas_tiles: Canvas = Canvas()
        self._canvas_map: Canvas = Canvas()

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

        # Create widgets if needed
        try:
            self.app.getCanvasWidget("BE_Canvas_Map")
        except ItemLookupError:
            self._create_widgets()

        self._canvas_tiles = self.app.getCanvasWidget("BE_Canvas_Tiles")
        self._canvas_tiles.bind("<Button-1>", self._tiles_left_click, add='')

        self._canvas_map = self.app.getCanvasWidget("BE_Canvas_Map")
        self._canvas_map.bind("<ButtonPress-1>", self._map_left_down, add='')
        self._canvas_map.bind("<B1-Motion>", self._map_left_drag, add='')
        self._canvas_map.bind("<Button-3>", self._map_right_click, add='')

        self._load_patterns()
        self._read_map_data(self._map_address[map_index])

        self.draw_map()

        # Default selections
        self.select_map(0)
        self.select_pattern(0)

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

        # Clear image cache
        self._patterns_cache: List[ImageTk.PhotoImage] = []

        # Reset canvas item IDs
        self._tiles_grid: List[int] = [0] * 16
        self._tile_items: List[int] = [0] * 16
        self._tile_rectangle: int = 0
        self._map_grid: List[int] = [0] * 8 * 12
        self._map_items: List[int] = [0] * 9 * 13
        self._map_rectangle: int = 0

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

            with self.app.frame("BE_Frame_Controls", padding=[4, 1], row=1, column=0):
                self.app.checkBox("BE_Check_Grid", True, name="Show grid", change=self.map_input,
                                  row=0, column=0, sticky="W")
                self.app.button("BE_Grid_Colour", self.map_input, name="Change Grid Colour", row=0, column=1, font=9)

            with self.app.frame("BE_Frame_Tiles", padding=[4, 2], row=2, column=0):
                self.app.canvas("BE_Canvas_Tiles", width=256, height=64, row=0, column=0, bg="#808080")
                self.app.setCanvasCursor("BE_Canvas_Tiles", "hand2")
                self.app.label("BE_Tile_Info", "", sticky="WE", row=1, column=0, font=10, fg=colour.BLACK)

            with self.app.frame("BE_Frame_Map", padding=[4, 2], row=3, column=0):
                self.app.canvas("BE_Canvas_Map", width=288, height=416, row=0, column=0, colspan=2, bg="#808080")
                self.app.setCanvasCursor("BE_Canvas_Map", "pencil")

    # ------------------------------------------------------------------------------------------------------------------

    def _load_patterns(self) -> None:
        # First, create a list of pattern addresses using the "default" tileset
        addresses: List[int] = []
        for p in range(16):
            addresses.append(0x8A40 + (p * 64))  # Each 2x2 tile is 64 bytes long

        banks: List[int] = [0xA] * 16  # Bank $0A by default

        if self.rom.has_feature("map tilesets"):
            # v1.09+ map tiles

            # The same substitutions to Town maps apply
            # The tables at $0A:B600 and $0B:B868 have the same format:
            # Source address in ROM, destination address in PPU, number of bytes to transfer
            address = 0xB642
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6
            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # Further substitutions are in bank $0B
            address = 0xB868
            pattern_address = self.rom.read_word(0xB, address)
            tile_index = (self.rom.read_word(0xB, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xB, address + 4) >> 6
            for t in range(tile_count):
                banks[tile_index] = 0xB
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            address = 0xB86E
            pattern_address = self.rom.read_word(0xB, address)
            tile_index = (self.rom.read_word(0xB, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xB, address + 4) >> 6
            for t in range(tile_count):
                banks[tile_index] = 0xB
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            address = 0xB874
            pattern_address = self.rom.read_word(0xB, address)
            tile_index = (self.rom.read_word(0xB, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xB, address + 4) >> 6
            for t in range(tile_count):
                banks[tile_index] = 0xB
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            address = 0xB87A
            pattern_address = self.rom.read_word(0xB, address)
            tile_index = (self.rom.read_word(0xB, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xB, address + 4) >> 6
            for t in range(tile_count):
                banks[tile_index] = 0xB
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

        else:
            # TODO Hardcoded tile substitutions
            self.app.warningBox("Battlefield Editor", "Tile substitutions not implemented for this ROM.",
                                parent="Battlefield_Editor")
            # TODO Detect vanilla game and use its hardcoded substitutions + "blank" ship tile
            pass

        # Now we have a full list of pattern addresses, we can use it to create our images
        tile_index = 0
        map_palette = self.palette_editor.palettes[0]
        self._patterns_cache.clear()

        for a in addresses:
            # Get palette index for this tile from table in ROM at 0D:856D
            palette_index = self.rom.read_byte(0x0D, 0x856D + tile_index) * 4
            colours = []
            for c in range(palette_index, palette_index + 4):
                colour_index = map_palette[c]
                rgb = bytearray(self.palette_editor.get_colour(colour_index))
                colours.append(rgb[0])  # Red
                colours.append(rgb[1])  # Green
                colours.append(rgb[2])  # Blue

            # We will combine the four patterns in a single up-scaled 32x32 image and then cache it
            tile = Image.new('P', (32, 32), 0)
            tile.putpalette(colours)

            # Top-left pattern
            pixels = bytes(bytearray(self.rom.read_pattern(banks[tile_index], a)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image.resize((16, 16), Image.NONE), (0, 0))
            # Bottom-left pattern
            pixels = bytes(bytearray(self.rom.read_pattern(banks[tile_index], a + 0x10)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image.resize((16, 16), Image.NONE), (0, 16))
            # Top-right pattern
            pixels = bytes(bytearray(self.rom.read_pattern(banks[tile_index], a + 0x20)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image.resize((16, 16), Image.NONE), (16, 0))
            # Bottom-right pattern
            pixels = bytes(bytearray(self.rom.read_pattern(banks[tile_index], a + 0x30)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image.resize((16, 16), Image.NONE), (16, 16))

            image = ImageTk.PhotoImage(tile)
            self._patterns_cache.append(image)

            # Show this tile in the tile pattern canvas (8 x 2 tiles)
            x = 16 + (32 * (tile_index % 8))
            y = 16 + (32 * (tile_index >> 3))
            if self._tile_items[tile_index] > 0:
                self._canvas_tiles.itemconfigure(self._tile_items[tile_index], image=image)
            else:
                self._tile_items[tile_index] = self.app.addCanvasImage("BE_Canvas_Tiles", x, y, image)

            # Next tile
            tile_index = tile_index + 1

        # Show / create grid lines
        grid_index = 0
        # 7 vertical lines
        for x in range(1, 8):
            if self._tiles_grid[grid_index] > 0:
                self._canvas_tiles.tag_raise(self._tiles_grid[grid_index])
            else:
                left = x << 5
                self._tiles_grid[grid_index] = self._canvas_tiles.create_line(left, 0, left, 64, fill=self._grid_colour)

            # Next item
            grid_index = grid_index + 1

        # Just 1 horizontal line is needed
        if self._tiles_grid[grid_index] > 0:
            self._canvas_tiles.tag_raise(self._tiles_grid[grid_index])
        else:
            self._tiles_grid[grid_index] = self._canvas_tiles.create_line(0, 32, 256, 32, fill=self._grid_colour)

        if self._tile_rectangle > 0:
            self._canvas_tiles.tag_raise(self._tile_rectangle)

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

    def get_map_names(self) -> List[str]:
        return self._map_names.copy()

    # ------------------------------------------------------------------------------------------------------------------

    def save_tab_data(self) -> None:
        """
        Saves battle music ID and table with map pointers.
        """
        # Save address table
        if self.rom.read_byte(0xF, 0xC7ED) == 0xBD:
            table_address = self.rom.read_word(0xF, 0xC7EE)
        else:
            if self.app.yesNoBox("Battlefield Editor", "Couldn't read battlefield maps address table pointer.\n" +
                                 "Do you want to continue using default value?", parent="Battlefield_Editor") is True:
                table_address = 0xCEAC
            else:
                table_address = -1

        if table_address >= 0xC000:
            for a in range(19):
                self.rom.write_word(0xF, table_address, self._map_address[a])
                table_address = table_address + 2

        elif table_address != -1:
            # Don't warn if action cancelled
            self.warning(f"Invalid address for battlefield map pointers: 0x{table_address:04X}.")

        # Save battle music ID
        if self.rom.read_byte(0xF, 0xC7F7) == 0xA9:
            music_id = self._get_selection_index("Battlefield_Option_Music")
            self.rom.write_byte(0xF, 0xC7F8, music_id | 0x80)

    # ------------------------------------------------------------------------------------------------------------------

    def map_input(self, widget: str) -> None:
        if widget == "BE_Button_Cancel":
            self.close_window()

        if widget == "BE_Button_Save":
            self.save_map_data()
            self.app.soundWarning()
            self.close_window()

        elif widget == "BE_Grid_Colour":
            # Pick a new colour
            self._grid_colour = self.app.colourBox(self._grid_colour, parent="Battlefield_Editor")
            # Update both grids
            for item in self._tiles_grid:
                if item > 0:
                    self._canvas_tiles.itemconfigure(item, fill=self._grid_colour)
            for item in self._map_grid:
                if item > 0:
                    self._canvas_map.itemconfigure(item, fill=self._grid_colour)

        elif widget == "BE_Check_Grid":
            if self.app.getCheckBox(widget) is True:
                # Show grid items
                for item in self._tiles_grid:
                    if item > 0:
                        self._canvas_tiles.itemconfigure(item, state="normal")
                for item in self._map_grid:
                    if item > 0:
                        self._canvas_map.itemconfigure(item, state="normal")
            else:
                # Hide grid items
                for item in self._tiles_grid:
                    if item > 0:
                        self._canvas_tiles.itemconfigure(item, state="hidden")
                for item in self._map_grid:
                    if item > 0:
                        self._canvas_map.itemconfigure(item, state="hidden")

        else:
            self.warning(f"Unimplemented input from map widget: '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def read_tab_data(self) -> None:
        """
        Reads battle music ID and table with map pointers.
        """
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

    def set_map_address(self, address: int, map_index: int = -1) -> None:
        if map_index == -1:
            map_index = self._selected_map

        if address < 0x8000 or address > 0xBFFF:
            self.warning(f"Invalid address 0x{address:04X} for battlefield map #{map_index}.")

        self._map_address[map_index] = address

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

    def save_map_data(self) -> None:
        address = self._map_address[self._selected_map]

        # Skip the first row
        address = address + 16
        t = 0
        # We will also skip the first column, and anything after the first 10 tiles in each row
        for y in range(13):
            for x in range(16):
                if x == 0:
                    # Skip first column
                    address = address + 1
                    continue

                if x > 9:
                    # Skip last 6 bytes
                    address = address + 1
                    continue

                self.rom.write_byte(0x4, address, self._map_data[t])
                t = t + 1
                address = address + 1

        self._unsaved_changes = False

    # ------------------------------------------------------------------------------------------------------------------

    def draw_map(self) -> None:
        """
        Populates the map canvas with patterns and draws /creates the grid if required.
        """
        tile_index = 0
        for y in range(13):
            for x in range(9):
                tile_id = self._map_data[tile_index]

                # If this item already existed, only change the image
                if self._map_items[tile_index] > 0:
                    self._canvas_map.itemconfigure(self._map_items[tile_index], image=self._patterns_cache[tile_id])
                else:
                    self._map_items[tile_index] = self._canvas_map.create_image(x << 5, y << 5,
                                                                                image=self._patterns_cache[tile_id],
                                                                                anchor="nw")
                # Next tile
                tile_index = tile_index + 1

        # Show / create / hide grid as needed
        if self.app.getCheckBox("BE_Check_Grid") is True:
            # Show / create
            grid_index = 0
            # 8 vertical lines
            for x in range(1, 9):
                if self._map_grid[grid_index] > 0:
                    self._canvas_map.itemconfigure(self._map_grid[grid_index], state="normal")
                    self._canvas_map.tag_raise(self._map_grid[grid_index])
                else:
                    left = x << 5
                    self._map_grid[grid_index] = self._canvas_map.create_line(left, 0, left, 416,
                                                                              fill=self._grid_colour)

                # Next line
                grid_index = grid_index + 1

            # 12 horizontal lines
            for y in range(1, 13):
                if self._map_grid[grid_index] > 0:
                    self._canvas_map.itemconfigure(self._map_grid[grid_index], state="normal")
                    self._canvas_map.tag_raise(self._map_grid[grid_index])
                else:
                    top = y << 5
                    self._map_grid[grid_index] = self._canvas_map.create_line(0, top, 288, top,
                                                                              fill=self._grid_colour)

                # Next line
                grid_index = grid_index + 1

        # Raise selection rectangle if it exists
        if self._tile_rectangle > 0:
            self._canvas_tiles.tag_raise(self._tile_rectangle)

    # ------------------------------------------------------------------------------------------------------------------

    def select_pattern(self, tile_index: int) -> None:
        """
        Moves the selection rectangle around the given tile and shows info about the selection.
        The selection rectangle will be created if needed.
        """
        self._selected_tile = tile_index

        # Calculate coordinates on the canvas, keep in mind there are 8x2 patterns, 32x32 pixels each
        x = (tile_index % 8) << 5
        y = (tile_index >> 3) << 5

        if self._tile_rectangle > 0:
            # Update coordinates of existing rectangle
            self._canvas_tiles.coords(self._tile_rectangle, x + 1, y + 1, x + 31, y + 31)
        else:
            # Create a rectangle at the selection's coordinates
            self._tile_rectangle = self._canvas_tiles.create_rectangle(x + 1, y + 1, x + 31, y + 31,
                                                                       width=2, outline="#FF3030")

        self.app.setLabel("BE_Tile_Info", f"Selected: {self._pattern_info[tile_index]} tile #0x{tile_index:02X}")

    # ------------------------------------------------------------------------------------------------------------------

    def select_map(self, selection_index: int) -> None:
        """
        Moves the selection rectangle around the given map square.
        The selection rectangle will be created if needed.
        """
        self._last_edited = selection_index

        # Calculate coordinates on the canvas, keep in mind there are 9x13 patterns, 32x32 pixels each
        x = (selection_index % 9) << 5
        y = (int(selection_index / 9)) << 5

        if self._map_rectangle > 0:
            # Update coordinates of existing rectangle
            self._canvas_map.coords(self._map_rectangle, x + 1, y + 1, x + 31, y + 31)
        else:
            # Create a rectangle at the selection's coordinates
            self._map_rectangle = self._canvas_map.create_rectangle(x + 1, y + 1, x + 31, y + 31,
                                                                    width=2, outline="#FF3030")

    # ------------------------------------------------------------------------------------------------------------------

    def _tiles_left_click(self, event: any) -> None:
        """
        Callback for left mouse click on the tile picker canvas.
        """
        # Calculate tile index depending on position
        x = event.x >> 5
        y = event.y >> 5
        self.select_pattern(x + (y << 3))

    # ------------------------------------------------------------------------------------------------------------------

    def _map_left_drag(self, event: any) -> None:
        # Prevent dragging outside the canvas
        if event.x < 0 or event.x >= 288 or event.y < 0 or event.y >= 416:
            return

        # Calculate tile index
        x = event.x >> 5
        y = event.y >> 5
        t = x + (y * 9)

        # Avoid re-editing same tile we are already on
        if t == self._last_edited:
            return

        self._map_edit_tile(t)

        # Move selection rectangle
        if self._map_rectangle > 0:
            x = (x << 5) + 1
            y = (y << 5) + 1
            self._canvas_map.coords(self._map_rectangle, x, y, x + 30, y + 30)

    # ------------------------------------------------------------------------------------------------------------------

    def _map_left_down(self, event: any) -> None:
        # Calculate tile index
        x = event.x >> 5
        y = event.y >> 5
        t = x + (y * 9)
        self._last_edited = t
        self._map_edit_tile(t)

        # Move selection rectangle
        if self._map_rectangle > 0:
            x = (x << 5) + 1
            y = (y << 5) + 1
            self._canvas_map.coords(self._map_rectangle, x, y, x + 30, y + 30)

    # ------------------------------------------------------------------------------------------------------------------

    def _map_right_click(self, event: any) -> None:
        # Calculate tile index
        x = event.x >> 5
        y = event.y >> 5
        t = x + (y * 9)

        self.select_map(t)
        self.select_pattern(self._map_data[t])

    # ------------------------------------------------------------------------------------------------------------------

    def _map_edit_tile(self, tile: int) -> None:
        self._map_data[tile] = self._selected_tile
        if self._map_items[tile] > 0:
            self._canvas_map.itemconfigure(self._map_items[tile], image=self._patterns_cache[self._selected_tile])
