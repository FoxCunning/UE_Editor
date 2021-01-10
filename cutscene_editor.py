__author__ = "Fox Cunning"

from typing import List

from PIL import Image, ImageTk

from appJar import appjar
from debug import log
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
        self.width: int = 0
        self.height: int = 0
        self.palette_index: int = 0
        self.patterns_address: int = 0

        # Selection from colours
        self.selected_palette: int = 0
        # Selection from patterns (if 2x2, then this is the top-left tile)
        self.selected_pattern: int = 0
        # Selection from nametable (if 2x2, then this is the top-left tile)
        self.selected_tile: int = 0

        self.unsaved_changes: bool = False

        self.patterns: List[int] = [0] * 256
        image = Image.new('P', (16, 16), 0)
        self.pattern_cache: List[Image] = [image] * 256

        # Nametable entries, same as how they appear in ROM
        self.nametables: bytearray = bytearray()
        # Attribute values, one per tile so NOT as they appear in ROM
        # These can be matched to nametable tiles so that nametables[t] uses palette attributes[t]
        self.attributes: bytearray = bytearray()

        # IDs of tkinter items added to canvases indicate current selection
        self.cutscene_rectangle: int = 0
        self.pattern_rectangle: int = 0
        self.palette_rectangle: int = 0

        # 0: 1x1 tile, 1: 2x2 tiles
        self.selection_size: int = 0

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
            Horizontal tile count

        height: int
            Vertical tile count
        """
        self.bank = bank
        self.nametable_address = nametable_address
        self.attributes_address = attributes_address
        self.width = width
        self.height = height

        self.unsaved_changes = False

        self.app.clearCanvas("CE_Canvas_Cutscene")

        # Resize the drawing area according to the size of the cutscene
        self.app.getScrollPaneWidget("CE_Pane_Cutscene").canvas.configure(width=min([width*2, 512]))

        # Load nametables
        self.nametables.clear()
        self.nametables = self.rom.read_bytes(bank, nametable_address, min([1024, (width * height) >> 6]))

        # Load attributes
        data = self.rom.read_bytes(bank, attributes_address, 64)
        self.attributes.clear()
        size = 32*30
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

        # Draw the scene on the canvas
        self.draw_cutscene()

        # Add event handlers
        self.app.getCanvasWidget("CE_Canvas_Cutscene").bind("<Button-1>", self.nametable_click, add="")

        # Show sub-window
        self.app.showSubWindow("Cutscene_Editor")

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
        # TODO Ask to confirm if there are unsaved changes
        self.app.hideSubWindow("Cutscene_Editor", False)

        self.app.clearCanvas("CE_Canvas_Cutscene")
        self.app.clearCanvas("CE_Canvas_Patterns")
        self.app.clearCanvas("CE_Canvas_Palette")

        # Clear patterns list
        self.patterns = [0] * 256
        image = ImageTk.PhotoImage(Image.new('P', (16, 16), 0))
        self.pattern_cache = [image] * 256

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def load_palette(self, palette_index: int) -> None:
        self.palette_index = palette_index
        self.selected_palette = 0

        # Show colours on the canvas
        self.app.clearCanvas("CE_Canvas_Palette")
        canvas = self.app.getCanvasWidget("CE_Canvas_Palette")

        palette = self.palette_editor.palettes[palette_index]
        cell_x = 0

        for c in range(16):
            colour = bytes(self.palette_editor.get_colour(palette[c]))

            colour_string = f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}"
            canvas.create_rectangle(cell_x, 0, cell_x + 15, 17, fill=colour_string, outline="#000000",
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
        colours = self.palette_editor.sub_palette(self.palette_index, self.selected_palette)

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

            # If there is already an item at those coordinates in the canvas, erase it
            canvas = self.app.getCanvasWidget("CE_Canvas_Patterns")
            item = canvas.find_enclosed(x - 8, y - 8, x + 8, y + 8)
            if len(item) > 0:
                canvas.delete(item)

            # Paste this pattern to the appropriate canvas at the right position
            self.patterns[first] = self.app.addCanvasImage("CE_Canvas_Patterns", x + 8, y + 8,
                                                           ImageTk.PhotoImage(image_2x))
            # Cache the image for quicker drawing
            self.pattern_cache[first] = image_2x

            # Advance to the next pattern
            first = first + 1
            address = address + 0x10
            count = count - 1

        if self.pattern_rectangle > 0:
            # Raise selection rectangle
            self.app.getCanvasWidget("CE_Canvas_Patterns").tag_raise(self.pattern_rectangle)
        else:
            # Add a selection rectangle
            selection_x = (self.selected_pattern << 3) % 256
            selection_y = (self.selected_pattern >> 4) << 3
            size = 16 + (15 * self.selection_size)
            self.pattern_rectangle = self.app.addCanvasRectangle("CE_Canvas_Patterns", selection_x + 1,
                                                                 selection_y + 1,
                                                                 size, size, outline="#FFFFFF", width=2)

        # TODO Redraw the cutscene using the new patterns, if needed

    # ------------------------------------------------------------------------------------------------------------------

    def draw_cutscene(self) -> None:
        # canvas = self.app.getCanvasWidget("CE_Canvas_Cutscene")
        self.app.clearCanvas("CE_Canvas_Cutscene")

        # x2 scale
        width = self.width << 1
        height = self.height << 1

        x = 0
        y = 0

        tile = 0

        while y < height and tile < len(self.nametables):
            pattern = self.nametables[tile]

            # Get the colours for this tile from the attributes list
            attribute = self.attributes[tile]
            colours = self.palette_editor.sub_palette(self.palette_index, attribute)

            # Replace the cached image's palette with the correct one
            try:
                image = self.pattern_cache[pattern]
                image.putpalette(colours)

                self.app.addCanvasImage("CE_Canvas_Cutscene", x + 8, y + 8, ImageTk.PhotoImage(image))

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
        selection_x = (self.selected_tile << 4) % 512
        selection_y = (self.selected_tile >> 5) << 4
        size = 16 + (15 * self.selection_size)
        self.cutscene_rectangle = self.app.addCanvasRectangle("CE_Canvas_Cutscene", selection_x + 1, selection_y + 1,
                                                              size, size, outline="#FFFFFF", width=2)

    # ------------------------------------------------------------------------------------------------------------------

    def select_palette(self, palette: int) -> None:
        """
        Select a palette (0-3).
        """
        if 0 <= palette <= 3:
            self.selected_palette = palette

            canvas = self.app.getCanvasWidget("CE_Canvas_Palette")
            selection_x = (palette << 5) + 1

            if self.palette_rectangle > 0:
                canvas.coords(self.palette_rectangle, selection_x, 1, selection_x + 63, 17)
                canvas.tag_raise(self.palette_rectangle)
            else:
                self.palette_rectangle = canvas.create_rectangle(selection_x, 1, selection_x + 63, 17,
                                                                 outline="#FFFFFF", width=2)

    # ------------------------------------------------------------------------------------------------------------------

    def select_pattern(self, x: int, y: int) -> None:
        """
        Select a pattern (or a 2x2 group of patterns).
        """
        # Make sure we stay within the canvas
        if self.selection_size == 1:
            # 2x2
            if x > 14:
                x = x - 1
            if y > 14:
                y = y - 1

        # Selection canvas contains 16x16 patterns
        self.selected_pattern = (x % 16) + (y << 4)

        if self.pattern_rectangle > 0:
            selection_x = (x << 3) + 1
            selection_y = (y << 3) + 1
            size = 16 + (15 * self.selection_size)
            self.app.getCanvasWidget("CE_Canvas_Patterns").coords(self.cutscene_rectangle,
                                                                  selection_x, selection_y,
                                                                  selection_x + size, selection_y + size)

    # ------------------------------------------------------------------------------------------------------------------

    def select_tile(self, x: int, y: int) -> None:
        """
        Select a tile (or 2x2 group of tiles) from the nametable.

        Parameters
        ----------
        x: int
            Horizontal index of the tile (0-31)

        y: int
            Vertical index of the tile (0-29)
        """
        self.selected_tile = (x % 32) + (y << 5)
        # self.info(f"Tile at: {x}, {y} = {self.selected_tile}")
        self.app.label("CE_Info_Cutscene", f"Selection: {x}, {y} [0x{(0x2000 + self.selected_tile):04X}] " +
                       f"| Pattern 0x{self.nametables[self.selected_tile]:02X} " +
                       f"| Palette {self.attributes[self.selected_tile]}")

        if self.cutscene_rectangle > 0:
            selection_x = (x << 4) + 1
            selection_y = (y << 4) + 1
            size = 16 + (15 * self.selection_size)
            self.app.getCanvasWidget("CE_Canvas_Cutscene").coords(self.cutscene_rectangle,
                                                                  selection_x, selection_y,
                                                                  selection_x + size, selection_y + size)

    # ------------------------------------------------------------------------------------------------------------------

    def nametable_click(self, event: any) -> None:
        """
        Callback for left mouse button click on the nametable canvas.
        """
        x = event.x >> 4
        y = event.y >> 4
        self.info(f"x: {event.x}, y: {event.y} - select {x}, {y}")
        self.select_tile(x, y)
