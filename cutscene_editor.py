__author__ = "Fox Cunning"

from tkinter import Canvas
from typing import List

from PIL import Image, ImageTk

import colour
from appJar import appjar
from debug import log
from helpers import Point2D
from palette_editor import PaletteEditor
from rom import ROM


class CutsceneEditor:
    """
    Graphical editor for "cutscenes". Allows editing nametables and attribute tables.
    """

    def __init__(self, app: appjar.gui, rom: ROM, palette_editor: PaletteEditor):
        self.bank: int = 0
        self.nametable_address: int = 0
        self.attributes_address: int = 0
        self._width: int = 0
        self._height: int = 0
        self.palette_index: int = 0
        self.patterns_address: int = 0

        # We cache these for speed and readability
        self.canvas_cutscene: Canvas = app.getCanvasWidget("CE_Canvas_Cutscene")
        self.canvas_patterns: Canvas = app.getCanvasWidget("CE_Canvas_Patterns")
        self.canvas_palettes: Canvas = app.getCanvasWidget("CE_Canvas_Palettes")

        # Selection from colours
        self._selected_palette: int = 0
        # Selection from patterns (if 2x2, then this is the top-left tile)
        self._selected_pattern: int = 0
        # Selection from nametable (if 2x2, then this is the top-left tile)
        self._selected_tile: int = 0

        self._unsaved_changes: bool = False

        # Canvas item IDs
        self._patterns: List[int] = [0] * 256
        # Image cache
        image = Image.new('P', (16, 16), 0)  # Empty image just for initialisation
        self._pattern_cache: List[Image] = [image] * 256
        self._pattern_image_cache: List[ImageTk.PhotoImage] = [ImageTk.PhotoImage(image)] * 256

        # Canvas item IDs
        self._palette_items: List[int] = [0] * 16

        # Canvas item ID, PhotoImage cache
        self._tiles: List[int] = [0] * (32 * 30)
        self._tile_image_cache: List[ImageTk.PhotoImage] = [ImageTk.PhotoImage(image)] * (32 * 30)

        # Nametable entries, same as how they appear in ROM
        self.nametable: bytearray = bytearray()
        # Attribute values, one per tile so NOT as they appear in ROM
        # These can be matched to nametable tiles so that nametables[t] uses palette attributes[t]
        self.attributes: bytearray = bytearray()

        # IDs of tkinter items added to canvases indicate current selection
        self._cutscene_rectangle: int = 0
        self._pattern_rectangle: int = 0
        self._palette_rectangle: int = 0

        # 0: 1x1 tile, 1: 2x2 tiles
        self._selection_size: int = 0

        # Last modified tile on the cutscene, used for drag-editing
        self._last_modified: Point2D = Point2D(-1, -1)

        self.rom: ROM = rom
        self.palette_editor = palette_editor
        self.app: appjar.gui = app

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

    def show_window(self, bank: int, nametable_address: int, attributes_address: int, width: int, height: int):
        """
        Shows the graphical editor for a cutscene.

        Parameters
        ----------
        bank: int
            Bank number where the name and attribute tables are found

        nametable_address: int
            Address of the nametable

        attributes_address: int
            Address of the attribute table

        width: int
            Horizontal tile count (1-32)

        height: int
            Vertical tile count (1-30)
        """
        self.bank = bank
        self.nametable_address = nametable_address
        self.attributes_address = attributes_address
        self._width = width
        self._height = height

        self._unsaved_changes = False

        # Resize the drawing area according to the size of the cutscene
        self.app.getScrollPaneWidget("CE_Pane_Cutscene").canvas.configure(width=512)

        # Load nametables
        # TODO Add support for nametables that don't fill the screen
        self.nametable.clear()
        self.nametable = self.rom.read_bytes(bank, nametable_address, 960)

        # Load attributes
        data = self.rom.read_bytes(bank, attributes_address, 64)
        self.attributes.clear()
        size = 32 * 30
        self.attributes = bytearray(size)

        for a in range(64):
            top_left = data[a] & 0x03
            top_right = (data[a] >> 2) & 0x03
            bottom_left = (data[a] >> 4) & 0x03
            bottom_right = data[a] >> 6

            tile_x = (a << 2) % 32
            tile_y = (a >> 3) << 2

            tile = (tile_x % 32) + (tile_y * 32)
            self._assign_attributes(tile, top_left)

            tile = ((tile_x + 2) % 32) + (tile_y * 32)
            self._assign_attributes(tile, top_right)

            tile = (tile_x % 32) + ((tile_y + 2) * 32)
            self._assign_attributes(tile, bottom_left)

            tile = ((tile_x + 2) % 32) + ((tile_y + 2) * 32)
            self._assign_attributes(tile, bottom_right)

        self.select_pattern(0, 0)
        self.select_palette(0)
        self.select_tile(0, 0)

        self._last_modified.x = -1
        self._last_modified.y = -1

        # Draw the scene on the canvas
        self.draw_cutscene()

        # This will also set the event handlers for the cutscene canvas
        self.set_selection_size(0)

        self.canvas_patterns.bind("<Button-1>", self._patterns_click, add="")
        self.canvas_palettes.bind("<Button-1>", self._palettes_click, add="")

        # Show sub-window
        self.app.showSubWindow("Cutscene_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def set_selection_size(self, size: int) -> None:
        """
        Sets the tile/pattern selection/editing size to 1x1 or 2x2.

        Parameters
        ----------
        size: int
            0: 1x1, 1: 2x2
        """
        # We will use separate event handlers to speed up the reaction to click and drag on the nametables

        if size == 0:
            self._selection_size = 0

            # Change button colours
            self.app.button("CE_Cutscene_1x1", bg=colour.WHITE)
            self.app.button("CE_Cutscene_2x2", bg=colour.DARK_GREY)

            # Updating selections will also resize the indicator rectangle
            pattern = Point2D(self._selected_pattern % 16, self._selected_pattern >> 4)
            tile = Point2D(self._selected_tile % 32, self._selected_tile >> 5)

            self.select_pattern(pattern.x, pattern.y)
            self.select_tile(tile.x, tile.y)

            # Event handlers for 1x1 selection
            self.canvas_cutscene.bind("<ButtonPress-1>", self._nametable_mouse_1_down, add="")
            self.canvas_cutscene.bind("<B1-Motion>", self._nametable_mouse_1_drag, add="")
            self.canvas_cutscene.bind("<Button-3>", self._nametable_mouse_3, add="")

        else:
            self._selection_size = 1

            self.app.button("CE_Cutscene_1x1", bg=colour.DARK_GREY)
            self.app.button("CE_Cutscene_2x2", bg=colour.WHITE)

            # Change tile selection to the top-left tile in any 2x2 group
            tile = Point2D(self._selected_tile % 32, self._selected_tile >> 5)
            tile.x = tile.x - (tile.x % 2)
            tile.y = tile.y - (tile.y % 2)

            # Change the pattern selection if we are near a border
            pattern = Point2D(self._selected_pattern % 16, self._selected_pattern >> 4)
            if pattern.x > 14:
                pattern.x = 14
            if pattern.y > 14:
                pattern.y = 14

            # Updating selections will also resize the indicator rectangle
            self.select_pattern(pattern.x, pattern.y)
            self.select_tile(tile.x, tile.y)

            # Set 2x2 event handlers
            self.canvas_cutscene.bind("<ButtonPress-1>", self._nametable_mouse_1_down_2x2, add="")
            self.canvas_cutscene.bind("<B1-Motion>", self._nametable_mouse_1_drag_2x2, add="")
            self.canvas_cutscene.bind("<Button-3>", self._nametable_mouse_3, add="")

    # ------------------------------------------------------------------------------------------------------------------

    def _assign_attributes(self, tile: int, attribute: int) -> None:
        """
        Assigns the given attributes to a 2x2 set of tiles, starting from the given one.

        Parameters
        ----------
        tile: int
            Index of the top-left tile in the attributes array

        attribute: int
            Value of the attribute (i.e. palette index) to assign (0-3)
        """
        max_size = len(self.attributes)

        if tile < max_size:
            self.attributes[tile] = attribute
        tile = tile + 1
        if tile < max_size:
            self.attributes[tile] = attribute
        tile = tile + 31
        if tile < max_size:
            self.attributes[tile] = attribute
        tile = tile + 1
        if tile < max_size:
            self.attributes[tile] = attribute

    # ------------------------------------------------------------------------------------------------------------------

    def close_window(self) -> bool:
        """
        Hides the window.

        Returns
        -------
        bool
            True if the window was closed. False if the action was cancelled by the user.
        """
        # Ask to confirm if there are unsaved changes
        if self._unsaved_changes is True:
            if self.app.yesNoBox("Cutscene Editor", "Are you sure you want to close the cutscene editor?\n" +
                                                    "All unsaved changes will be lost.", "Cutscene_Editor") is False:
                return False

        self.app.hideSubWindow("Cutscene_Editor", False)

        # Clear patterns list
        self._patterns = [0] * 256
        image = ImageTk.PhotoImage(Image.new('P', (16, 16), 0))
        self._pattern_cache = [image] * 256

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def load_palette(self, palette_index: int) -> None:
        self.palette_index = palette_index
        self._selected_palette = 0

        # Show colours on the canvas
        palette = self.palette_editor.palettes[palette_index]
        cell_x = 0

        for c in range(16):
            rgb = bytes(self.palette_editor.get_colour(palette[c]))

            colour_string = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
            if self._palette_items[c] > 0:
                self.canvas_palettes.itemconfig(self._palette_items[c], fill=colour_string)
            else:
                self._palette_items[c] = self.canvas_palettes.create_rectangle(cell_x, 0, cell_x + 15, 17,
                                                                               fill=colour_string, outline="#000000",
                                                                               width=1)
            cell_x = cell_x + 16

    # ------------------------------------------------------------------------------------------------------------------

    def load_patterns(self, bank: int, address: int, count: int, first: int) -> None:
        """
        Loads a set of patterns from ROM and adds them to the patterns canvas.

        Parameters
        ----------
        bank: int
            Bank number to load from

        address: int
            Address of the first pattern

        count: int
            Number of patterns to load

        first: int
            Index of the first pattern in the PPU (0 - 255)
        """
        # Use currently selected palette
        colours = self.palette_editor.sub_palette(self.palette_index, self._selected_palette)

        # Load 8x8 patterns
        while count > 0 and first < 256:
            # Create an empty 16x16 image (we will upscale the pattern and copy it here)
            image_2x = Image.new('P', (16, 16), 0)

            # Load pixel data into a PIL image
            pixels = bytes(self.rom.read_pattern(bank, address))
            image_1x = Image.frombytes('P', (8, 8), pixels)

            image_1x.putpalette(colours)
            image_2x.putpalette(colours)

            # Scale the image
            image_2x.paste(image_1x.resize((16, 16), Image.NONE))

            # Calculate coordinates depending on item index
            x = (first % 16) << 4
            y = (first >> 4) << 4

            # Cache the image for quicker drawing and future editing
            self._pattern_cache[first] = image_2x

            # Paste this pattern to the appropriate canvas at the right position
            self._pattern_image_cache[first] = ImageTk.PhotoImage(self._pattern_cache[first])
            if self._patterns[first] > 0:
                # Update an existing image item
                self.canvas_patterns.itemconfig(self._patterns[first], image=self._pattern_image_cache[first])
            else:
                # Create a new image item if there wasn't one yet
                self._patterns[first] = self.canvas_patterns.create_image(x, y, anchor="nw",
                                                                          image=self._pattern_image_cache[first])
                # self._patterns[first] = self.app.addCanvasImage("CE_Canvas_Patterns", x + 8, y + 8,
                #                                                image=self._pattern_image_cache[first])

            # Advance to the next pattern
            first = first + 1
            address = address + 0x10
            count = count - 1

        if self._pattern_rectangle > 0:
            # Raise selection rectangle
            self.canvas_patterns.tag_raise(self._pattern_rectangle)
        else:
            # Add a selection rectangle
            selection_x = (self._selected_pattern << 3) % 256
            selection_y = (self._selected_pattern >> 4) << 3
            size = 16 + (15 * self._selection_size)
            self._pattern_rectangle = self.app.addCanvasRectangle("CE_Canvas_Patterns", selection_x + 1,
                                                                  selection_y + 1,
                                                                  size, size, outline="#FFFFFF", width=2)

        # TODO Redraw the cutscene using the new patterns, if needed

    # ------------------------------------------------------------------------------------------------------------------

    def draw_cutscene(self) -> None:
        """
        Fills the cutscene canvas with patterns according to the name and attribute tables.
        """
        # x2 scale: double the tile size both vertically and horizontally
        width = 512
        height = 480

        x = 0
        y = 0

        tile = 0

        while y < height and tile < len(self.nametable):
            pattern = self.nametable[tile]

            # Get the colours for this tile from the attributes list
            attribute = self.attributes[tile]
            colours = self.palette_editor.sub_palette(self.palette_index, attribute)

            # Replace the cached image's palette with the correct one
            try:
                image = self._pattern_cache[pattern]
                image.putpalette(colours)

                self._tile_image_cache[tile] = ImageTk.PhotoImage(image)
                if self._tiles[tile] == 0:
                    self._tiles[tile] = self.app.addCanvasImage("CE_Canvas_Cutscene", x + 8, y + 8,
                                                                self._tile_image_cache[tile])
                else:
                    self.canvas_cutscene.itemconfig(self._tiles[tile], image=self._tile_image_cache[tile])

            except KeyError:
                # Add a "marked" image like a cross or something to indicate there has been an error?
                pass

            # Next tile to the right
            tile = tile + 1
            x = x + 16
            # If we reach the end of the line, move to the next line
            if x >= width:
                x = 0
                y = y + 16

        # Add a grid "overlay"
        for x in range(1, 31):
            line_x = x << 5
            self.app.addCanvasLine("CE_Canvas_Cutscene", line_x, 0, line_x, 480, fill="#7E7E7E", width=1)
        for y in range(1, 29):
            line_y = y << 5
            self.app.addCanvasLine("CE_Canvas_Cutscene", 0, line_y, 512, line_y, fill="#7E7E7E", width=1)

        # Add a selection rectangle
        selection_x = (self._selected_tile << 4) % 512
        selection_y = (self._selected_tile >> 5) << 4
        size = 16 + (15 * self._selection_size)

        if self._cutscene_rectangle > 0:
            self.canvas_cutscene.coords(self._cutscene_rectangle, selection_x + 1, selection_y + 1,
                                        selection_x + size, selection_y + size)
            self.canvas_cutscene.tag_raise(self._cutscene_rectangle)
        else:
            self._cutscene_rectangle = self.app.addCanvasRectangle("CE_Canvas_Cutscene",
                                                                   selection_x + 1, selection_y + 1,
                                                                   size, size, outline="#FFFFFF", width=2)

    # ------------------------------------------------------------------------------------------------------------------

    def select_palette(self, palette: int) -> None:
        """
        Select a palette (0-3).
        """
        if 0 <= palette <= 3:

            if palette != self._selected_palette:
                # Change pattern colours if needed
                rgb = self.palette_editor.sub_palette(self.palette_index, palette)

                for p in range(256):
                    image = self._pattern_cache[p]
                    image.putpalette(rgb)
                    if self._patterns[p] > 0:
                        self._pattern_image_cache[p] = ImageTk.PhotoImage(image)
                        self.canvas_patterns.itemconfig(self._patterns[p], image=self._pattern_image_cache[p])

            self._selected_palette = palette

            selection_x = (palette << 6) + 1

            self.app.label("CE_Palette_Info", f"Palette: {palette}")

            if self._palette_rectangle > 0:
                self.canvas_palettes.coords(self._palette_rectangle, selection_x, 1, selection_x + 63, 17)
                self.canvas_palettes.tag_raise(self._palette_rectangle)
            else:
                self._palette_rectangle = self.canvas_palettes.create_rectangle(selection_x, 1, selection_x + 63, 17,
                                                                                outline="#FFFFFF", width=2)

    # ------------------------------------------------------------------------------------------------------------------

    def select_pattern(self, x: int, y: int) -> None:
        """
        Select a pattern (or a 2x2 group of patterns).
        """
        # Make sure we stay within the canvas
        if self._selection_size == 1:
            # 2x2
            if x > 14:
                x = 14
            if y > 14:
                y = 14

        # Selection canvas contains 16x16 patterns
        # (tile X index % number of tiles in a row) + (tile Y index / number of tiles in a column)
        self._selected_pattern = (x % 16) + (y << 4)

        self.app.label("CE_Pattern_Info", f"Pattern: 0x{self._selected_pattern:02X}")

        if self._pattern_rectangle > 0:
            selection_x = (x << 4) + 1  # base X = tile X index * tile width in pixels
            selection_y = (y << 4) + 1  # base Y = tile Y index * tile height in pixels
            size = 16 + (15 * self._selection_size)
            self.canvas_patterns.coords(self._pattern_rectangle, selection_x, selection_y,
                                        selection_x + size, selection_y + size)

    # ------------------------------------------------------------------------------------------------------------------

    def select_tile(self, x: int, y: int) -> []:
        """
        Select a tile (or 2x2 group of tiles) from the nametable.

        Parameters
        ----------
        x: int
            Horizontal index of the tile (0-31)

        y: int
            Vertical index of the tile (0-29)

        Returns
        -------
        list
            A tuple containing nametable entry (i.e. pattern index) and attribute value at the given coordinates
        """
        # (tile X index % number of tiles in a row) + (tile Y index / number of tiles in a column)
        self._selected_tile = (x % 32) + (y << 5)
        # self.info(f"Tile at: {x}, {y} = {self.selected_tile}")
        self.app.label("CE_Info_Cutscene", f"Selection: {x}, {y} [0x{(0x2000 + self._selected_tile):04X}] " +
                       f"| Pattern 0x{self.nametable[self._selected_tile]:02X} " +
                       f"| Palette {self.attributes[self._selected_tile]}")

        if self._cutscene_rectangle > 0:
            selection_x = (x << 4) + 1
            selection_y = (y << 4) + 1
            size = 16 + (15 * self._selection_size)
            self.canvas_cutscene.coords(self._cutscene_rectangle, selection_x, selection_y,
                                        selection_x + size, selection_y + size)

        return [self.nametable[self._selected_tile], self.attributes[self._selected_tile]]

    # ------------------------------------------------------------------------------------------------------------------

    def _nametable_mouse_1_down(self, event: any) -> None:
        """
        Callback for left button down on cutscene canvas, when selection size is 1x1.
        """
        self._last_modified.x = event.x >> 4
        self._last_modified.y = event.y >> 4

        self.edit_nametable_entry(self._last_modified.x, self._last_modified.y, self._selected_pattern)

    # ------------------------------------------------------------------------------------------------------------------

    def _nametable_mouse_1_down_2x2(self, event: any) -> None:
        """
        Callback for left button down on cutscene canvas, when selection size is 2x2.
        """
        # We treat the canvas as if it contained half the tiles
        # Do as if each tile was twice the size on each axis, then multiply by the scaling factor
        # This ensures we always select the top-left tile of each 2x2 group
        self._last_modified.x = (event.x >> 5) << 1
        self._last_modified.y = (event.y >> 5) << 1

        self.info(f"Mouse: {event.x}, {event.y}, tile: {self._last_modified.x}, {self._last_modified.y}")

        # The selection should always be the top-left tile of a 2x2 "super-tile"
        self.edit_nametable_entry(self._last_modified.x + 1, self._last_modified.y + 1, self._selected_pattern + 17)
        self.edit_nametable_entry(self._last_modified.x, self._last_modified.y + 1, self._selected_pattern + 16)
        self.edit_nametable_entry(self._last_modified.x + 1, self._last_modified.y, self._selected_pattern + 1)
        # We leave the top-left last so that the selection rectangle will be based on its position
        self.edit_nametable_entry(self._last_modified.x, self._last_modified.y, self._selected_pattern)

    # ------------------------------------------------------------------------------------------------------------------

    def _nametable_mouse_1_drag(self, event: any) -> None:
        """
        Callback for left button drag on cutscene canvas, when selection size is 1x1.
        """
        x = event.x >> 4
        y = event.y >> 4

        if x == self._last_modified.x and y == self._last_modified.y:
            return
        else:
            self._last_modified.x = x
            self._last_modified.y = y
            self.edit_nametable_entry(x, y, self._selected_pattern)

    # ------------------------------------------------------------------------------------------------------------------

    def _nametable_mouse_1_drag_2x2(self, event: any) -> None:
        """
        Callback for left button drag on cutscene canvas, when selection size is 2x2.
        """
        x = (event.x >> 5) << 1
        y = (event.y >> 5) << 1

        if x == self._last_modified.x and y == self._last_modified.y:
            return
        else:
            self._last_modified.x = x
            self._last_modified.y = y
            # Bottom-right
            self.edit_nametable_entry(x + 1, y + 1, self._selected_pattern + 17)
            # Bottom-left
            self.edit_nametable_entry(x, y + 1, self._selected_pattern + 16)
            # Top-right
            self.edit_nametable_entry(x + 1, y, self._selected_pattern + 1)
            # Top-left
            self.edit_nametable_entry(x, y, self._selected_pattern)

    # ------------------------------------------------------------------------------------------------------------------

    def _nametable_mouse_3(self, event: any) -> None:
        """
        Callback for right mouse click on cutscene canvas.
        Selects the pattern and attribute used for that tile.
        1x1 selection version.
        """
        x = event.x >> 4
        y = event.y >> 4

        tile_data = self.select_tile(x, y)

        self.select_pattern(tile_data[0] % 16, tile_data[0] >> 4)
        self.select_palette(tile_data[1])

    # ------------------------------------------------------------------------------------------------------------------

    def _nametable_mouse_3_2x2(self, event: any) -> None:
        """
        Callback for right mouse click on cutscene canvas.
        Selects the pattern and attribute used for that tile.
        2x2 selection version.
        """
        x = (event.x >> 5) << 1
        y = (event.y >> 5) << 1

        tile_data = self.select_tile(x, y)
        self.select_pattern(tile_data[0] % 16, tile_data[0] >> 4)
        self.select_palette(tile_data[1])

    # ------------------------------------------------------------------------------------------------------------------

    def _patterns_click(self, event: any) -> None:
        """
        Callback for left mouse click on the patterns canvas, when the selection size is 1x2.
        """
        # Formula: x = (mouse x / tile width in pixels), y = (mouse y / tile height in pixels)
        x = event.x >> 4
        y = event.y >> 4
        # self.info(f"x: {event.x}, y: {event.y} - select {x}, {y}")
        self.select_pattern(x, y)

    # ------------------------------------------------------------------------------------------------------------------

    def _palettes_click(self, event: any) -> None:
        """
        Callback for left click on the palettes canvas.
        """
        # There is only one row of 256 pixels with 4 entries (64 pixels each)
        # Entry index = mouse position / pixel width of each entry
        self.select_palette(event.x >> 6)

    # ------------------------------------------------------------------------------------------------------------------

    def _update_attribute(self, x: int, y: int, palette: int) -> None:
        t = (x % 32) + (y << 5)

        self.attributes[t] = palette
        colours = self.palette_editor.sub_palette(self.palette_index, palette)

        pattern = self.nametable[t]
        new_image = self._pattern_cache[pattern]
        new_image.putpalette(colours)

        self._tile_image_cache[t] = ImageTk.PhotoImage(new_image)

        # X position on canvas = X index * width in pixels
        # Y position on canvas = Y index * height in pixels
        # item_position = Point2D(x=x << 4, y=y << 4)

        self.canvas_cutscene.itemconfig(self._tiles[t], image=self._tile_image_cache[t])

    # ------------------------------------------------------------------------------------------------------------------

    def edit_nametable_entry(self, x: int, y: int, pattern: int) -> None:
        """
        Assigns a pattern to a tile in the nametable.

        Parameters
        ----------
        x: int
            Horizontal index of the tile (0-31)

        y: int
            Vertical index of the tile (0-29)

        pattern: int
            Index of the new pattern (0-255)
        """
        # (tile X index % number of tiles in a row) + (tile Y index * number of tiles in a column)
        t = (x % 32) + (y << 5)
        self.nametable[t] = pattern

        # Get the attribute table for these coordinates
        sub_palette = self.attributes[t]

        if self._selected_palette != sub_palette:
            # We are changing the palette, which affects other tiles
            # Get the top-left tile of this 2x2 group
            top_left = Point2D(x - (x % 2), y - (y % 2))
            # Update the palette for the whole group
            sub_palette = self._selected_palette

            self._update_attribute(top_left.x, top_left.y, sub_palette)
            self._update_attribute(top_left.x + 1, top_left.y, sub_palette)
            self._update_attribute(top_left.x, top_left.y + 1, sub_palette)
            self._update_attribute(top_left.x + 1, top_left.y + 1, sub_palette)

        else:
            # Palette didn't change: only update this tile
            sub_palette = self._selected_palette
            colours = self.palette_editor.sub_palette(self.palette_index, sub_palette)

            new_image = self._pattern_cache[pattern]
            new_image.putpalette(colours)
            self._tile_image_cache[t] = ImageTk.PhotoImage(new_image)

            # X position on canvas = X index * width in pixels
            # Y position on canvas = Y index * height in pixels
            # item_position = Point2D(x=x << 4, y=y << 4)

            self.canvas_cutscene.itemconfig(self._tiles[t], image=self._tile_image_cache[t])

        self.select_tile(x, y)

        self._unsaved_changes = True

    # ------------------------------------------------------------------------------------------------------------------

    def save_nametable(self) -> bool:
        success: bool = True

        # TODO Add support for scenes that don't fill the whole screen
        self.rom.write_bytes(self.bank, self.nametable_address, self.nametable)

        return success

    # ------------------------------------------------------------------------------------------------------------------

    def save_attributes(self) -> bool:
        success: bool = True

        data = bytearray()

        size = len(self.attributes)

        shift = [0, 2, 4, 6]

        # Convert attribute per tile to PPU format
        for a in range(64):
            # Each value is (bottom-right << 6) | (bottom-left << 4) | (top-right << 2) | (top-left << 0)
            attribute = 0

            # Get the top-left tile for this attribute entry
            # Each attribute pertains to 4x4 tiles and there are 8x8 attributes
            # So tile x = (attribute % 8) * 4, tile y = (attribute / 8) * 4
            x = (a % 8) << 2
            y = (a >> 3) << 2

            # We are considering a 32 * 32 tile area, so tile = (x % 32) + (y * 32)
            top_right = (x % 32) + (y << 5)

            # Get the other corner tiles in this 4x4 square
            tiles = [top_right, top_right + 2, top_right + 64, top_right + 66]

            for t in range(4):
                if tiles[t] < size:
                    attribute = attribute | (self.attributes[tiles[t]] << shift[t])

            data.append(attribute)

        # TODO Actually save
        self.info(f"Attribute table: {data.hex()}")

        self._unsaved_changes = False

        return success

    # ------------------------------------------------------------------------------------------------------------------

    def export_to_file(self, file_name: str) -> None:
        data = self.nametable[:960]

        table_size = len(self.attributes)
        shift = [0, 2, 4, 6]

        # Convert attribute per tile to PPU format
        for a in range(64):
            # Each value is (bottom-right << 6) | (bottom-left << 4) | (top-right << 2) | (top-left << 0)
            attribute = 0

            # Get the top-left tile for this attribute entry
            # Each attribute pertains to 4x4 tiles and there are 8x8 attributes
            # So tile x = (attribute % 8) * 4, tile y = (attribute / 8) * 4
            x = (a % 8) << 2
            y = (a >> 3) << 2

            # We are considering a 32 * 32 tile area, so tile = (x % 32) + (y * 32)
            top_right = (x % 32) + (y << 5)

            # Get the other corner tiles in this 4x4 square
            tiles = [top_right, top_right + 2, top_right + 64, top_right + 66]

            for t in range(4):
                if tiles[t] < table_size:
                    attribute = attribute | (self.attributes[tiles[t]] << shift[t])

            data.append(attribute)

        # Open file for writing
        try:
            file = open(file_name, "wb")
            if file is not None:
                file.write(data)
                file.close()

        except OSError as error:
            self.app.errorBox("Export Cutscene", f"ERROR: {error.strerror}.")

    # ------------------------------------------------------------------------------------------------------------------

    def import_from_file(self, file_name: str) -> None:
        try:
            file = open(file_name, "rb")
            data = file.read()
            file.close()

            # Read nametables
            # TODO Add support for nametables that don't fill the screen
            self.nametable.clear()
            self.nametable = bytearray(data[:960])

            # Read attributes
            self.attributes.clear()
            size = 960
            self.attributes = bytearray(size)

            data = data[960:]

            for a in range(64):
                top_left = data[a] & 0x03
                top_right = (data[a] >> 2) & 0x03
                bottom_left = (data[a] >> 4) & 0x03
                bottom_right = data[a] >> 6

                tile_x = (a << 2) % 32
                tile_y = (a >> 3) << 2

                tile = (tile_x % 32) + (tile_y * 32)
                self._assign_attributes(tile, top_left)

                tile = ((tile_x + 2) % 32) + (tile_y * 32)
                self._assign_attributes(tile, top_right)

                tile = (tile_x % 32) + ((tile_y + 2) * 32)
                self._assign_attributes(tile, bottom_left)

                tile = ((tile_x + 2) % 32) + ((tile_y + 2) * 32)
                self._assign_attributes(tile, bottom_right)

            # Redraw the scene
            self.draw_cutscene()

        except IndexError:
            self.app.errorBox("Import Cutscene", "ERROR: Invalid data, EOF encountered.")

        except OSError as error:
            self.app.errorBox("Import Cutscene", f"ERROR: {error.strerror}.")
