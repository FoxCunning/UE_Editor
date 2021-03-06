__author__ = "Fox Cunning"

import tkinter
from typing import List, Optional

import appJar
import colour
from appJar import gui
from debug import log
from editor_settings import EditorSettings
from palette_editor import PaletteEditor
from rom import ROM
from undo_redo import UndoRedo


class TileEditor:

    _DRAW: int = 0
    _FILL: int = 1

    # ------------------------------------------------------------------------------------------------------------------
    def __init__(self, app: gui, settings: EditorSettings, rom: ROM, palette_editor: PaletteEditor):
        self.app = app
        self.settings = settings
        self.rom = rom
        self.palette_editor = palette_editor

        self._bank: int = 0
        self._address: int = 0

        self._palette: int = 0
        self._colours = []
        self._selected_colour: int = 0
        self._selected_palette: int = 0

        # Canvas references
        self._drawing: Optional[tkinter.Canvas] = None

        # Canvas item IDs
        self._rectangles: List[int] = []    # Each filled rectangle will represent a pixel
        self._grid: List[int] = []
        self._pixels: Optional[bytearray] = None

        self._palette_rectangle: int = 0     # A rectangle surrounding the selected colour

        self._tool: int = 0

        # Undo / Redo

        # We keep track of how many tiles are modified with a single operation, for the undo/redo manager
        self._modified_pixels: int = 0

        # Last modified pixel, used to prevent unnecessary actions when drag-drawing
        self._last_edited: int = -1

        self._undo_redo: Optional[UndoRedo] = None
        # These keep count of how many actions to process in each single undo/redo
        self._undo_actions: List[int] = []
        self._redo_actions: List[int] = []

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

    def hide(self) -> None:
        self.app.hideSubWindow("Tile_Editor")
        self.app.emptySubWindow("Tile_Editor")

        self._drawing = None
        self._grid = []
        self._rectangles = []
        self._pixels = None
        self._colours = []

        self._undo_redo = None
        self._undo_actions = []
        self._redo_actions = []

    # ------------------------------------------------------------------------------------------------------------------

    def show(self, bank: int, address: int, palette: int) -> None:
        self._bank = bank
        self._address = address
        self._palette = palette

        # Allocate memory for "pixels" and other canvas items in the drawing area
        self._rectangles = [0] * 64
        self._grid = [0] * 14

        # Check if window already exists
        try:
            self.app.getFrameWidget("TL_Frame_Buttons")
            self.app.showSubWindow("Tile_Editor")
            return

        except appJar.appjar.ItemLookupError:
            generator = self.app.subWindow("Tile_Editor", size=[286, 220], padding=[2, 2], title="Edit CHR Tile",
                                           resizable=False, modal=True, blocking=True,
                                           bg=colour.DARK_GREY, fg=colour.WHITE,
                                           stopFunction=self.hide)
        app = self.app

        with generator:

            with app.frame("TL_Frame_Buttons", padding=[2, 2], sticky="NEW", row=0, column=0, colspan=3):
                app.button("TL_Apply", self._input, image="res/floppy.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=1, sticky="W", tooltip="Save all changes")
                app.button("TL_Reload", self._input, image="res/reload.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=2, sticky="W", tooltip="Reload from ROM")
                app.button("TL_Close", self._input, image="res/close.gif", bg=colour.MEDIUM_GREY,
                           row=0, column=3, sticky="W", tooltip="Discard changes and close")

                app.canvas("TL_Separator", width=16, height=1, row=0, column=4)

                app.button("TL_Undo", self._undo, image="res/undo.gif", width=32, height=32,
                           tooltip="Nothing to Undo",
                           sticky="E", row=0, column=5)
                app.button("TL_Redo", self._redo, image="res/redo.gif", width=32, height=32,
                           tooltip="Nothing to Redo",
                           sticky="E", row=0, column=6)

            with app.frame("TL_Frame_Palette", padding=[4, 4], sticky="NW", row=1, column=0):
                app.canvas("TL_Canvas_Palette", width=32, height=128, bg=colour.BLACK
                           ).bind("<ButtonRelease-1>", self._palette_left_click)

            with app.frame("TL_Frame_Drawing", padding=[4, 4], sticky="NW", row=1, column=1):
                self._drawing = app.canvas("TL_Canvas_Drawing", width=128, height=128, bg=colour.BLACK)

            with app.frame("TL_Frame_Tools", padding=[4, 4], sticky="NE", row=1, column=2):
                app.button("TL_Tool_Draw", self._input, image="res/pencil.gif", sticky="N", bg=colour.WHITE,
                           row=0, column=0, colspan=2)
                app.button("TL_Tool_Fill", self._input, image="res/bucket.gif", sticky="N", bg=colour.MEDIUM_GREY,
                           row=1, column=0, colspan=2)

                app.button("TL_Move_Left", self._input, image="res/arrow_left-small.gif", tooltip="Move image left",
                           sticky="NE", row=2, column=0)
                app.button("TL_Move_Right", self._input, image="res/arrow_right-small.gif", tooltip="Move image right",
                           sticky="NE", row=2, column=1)
                app.button("TL_Move_Up", self._input, image="res/arrow_up-small.gif", tooltip="Move image up",
                           sticky="NE", row=3, column=0)
                app.button("TL_Move_Down", self._input, image="res/arrow_down-small.gif", tooltip="Move image down",
                           sticky="NE", row=3, column=1)

        self._load_pattern()
        self._select_tool(TileEditor._DRAW)

        self._undo_redo = UndoRedo()

        self._drawing.bind("<ButtonPress-1>", self._drawing_left_down)
        self._drawing.bind("<ButtonRelease-1>", self._drawing_left_up)
        self._drawing.bind("<B1-Motion>", self._drawing_left_drag)
        self._drawing.bind("<ButtonPress-3>", self._drawing_right_click)

        self._show_palette()
        self._select_colour(0, 1)

        # This is causing problems at the moment...
        """
        sw = app.openSubWindow("Tile_Editor")
        sw.bind("<Control-z>", self._undo, add='')
        sw.bind("<Control-y>", self._redo, add='')
        """

        app.disableButton("TL_Undo")
        app.disableButton("TL_Redo")

        app.showSubWindow("Tile_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def _input(self, widget: str) -> None:
        if widget == "TL_Apply":    # ----------------------------------------------------------------------------------
            self.rom.write_pattern(self._bank, self._address, self._pixels)

            if self.settings.get("close sub-window after saving"):
                self.hide()

        elif widget == "TL_Close":  # ----------------------------------------------------------------------------------
            self.hide()

        elif widget == "TL_Tool_Draw":  # ------------------------------------------------------------------------------
            self._select_tool(TileEditor._DRAW)

        elif widget == "TL_Tool_Fill":  # ------------------------------------------------------------------------------
            self._select_tool(TileEditor._FILL)

        elif widget == "TL_Move_Left":  # ------------------------------------------------------------------------------
            self._undo_redo(self._move_pixels, (7, 0), (1, 0), text="Move Image Left")
            self._undo_actions.append(1)
            self._redo_actions = []
            self._update_undo_buttons()

        elif widget == "TL_Move_Right":     # --------------------------------------------------------------------------
            self._undo_redo(self._move_pixels, (1, 0), (7, 0), text="Move Image Right")
            self._undo_actions.append(1)
            self._redo_actions = []
            self._update_undo_buttons()

        elif widget == "TL_Move_Up":    # ------------------------------------------------------------------------------
            self._undo_redo(self._move_pixels, (0, 7), (0, 1), text="Move Image Up")
            self._undo_actions.append(1)
            self._redo_actions = []
            self._update_undo_buttons()

        elif widget == "TL_Move_Down":  # ------------------------------------------------------------------------------
            self._undo_redo(self._move_pixels, (0, 1), (0, 7), text="Move Image Down")
            self._undo_actions.append(1)
            self._redo_actions = []
            self._update_undo_buttons()

        else:   # ------------------------------------------------------------------------------------------------------
            self.warning(f"Unimplemented input from Pattern Editor widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _load_pattern(self) -> None:
        self._pixels = self.rom.read_pattern(self._bank, self._address)

        colours = self.palette_editor.sub_palette(self._palette, 1)

        # Convert our RGB bytearray to strings
        self._colours = c = [f"#{colours[n]:02X}{colours[n+1]:02X}{colours[n+2]:02X}" for n in range(0, 12, 3)]

        x = y = 0
        i = 0
        for pixel in self._pixels:
            if self._rectangles[i] > 0:
                # Already exists in canvas: update colour
                self._drawing.itemconfigure(self._rectangles[i], fill=c[pixel])
            else:
                # Create a rectangle in our canvas and make it the colour of this pixel
                rx = x << 4
                ry = y << 4
                self._rectangles[i] = self._drawing.create_rectangle(rx, ry, rx + 16, ry + 16, width=0, fill=c[pixel])

            x += 1
            i += 1
            if x > 7:
                x = 0
                y += 1

        # Show the grid
        x = y = 16
        for i in range(7):
            # Horizontal
            if self._grid[i] > 0:
                self._drawing.tag_raise(self._grid[i])
            else:
                self._grid[i] = self._drawing.create_line(0, y, 128, y, dash=(4, 4), fill="#C0C0C0")
            y += 16
            # Vertical
            if self._grid[i + 7] > 0:
                self._drawing.tag_raise(self._grid[i + 7])
            else:
                self._grid[i + 7] = self._drawing.create_line(x, 0, x, 128, dash=(4, 4), fill="#C0C0C0")
            x += 16

    # ------------------------------------------------------------------------------------------------------------------

    def _select_tool(self, tool: int) -> None:
        self._tool = tool

        if tool == TileEditor._DRAW:
            self._drawing.configure(cursor="pencil")
            self.app.setButtonBg("TL_Tool_Draw", colour.WHITE)
            self.app.setButtonBg("TL_Tool_Fill", colour.MEDIUM_GREY)

        elif tool == TileEditor._FILL:
            self._drawing.configure(cursor="cross")
            self.app.setButtonBg("TL_Tool_Draw", colour.MEDIUM_GREY)
            self.app.setButtonBg("TL_Tool_Fill", colour.WHITE)

    # ------------------------------------------------------------------------------------------------------------------

    def _drawing_left_down(self, event) -> None:
        if self._tool == TileEditor._FILL:
            return

        # The image is "zoomed in" x16, so: (x / 16) + ((y / 16) * number of items in a row)
        pixel_index = (event.x >> 4) + ((event.y >> 4) << 3)

        self._last_edited = pixel_index

        old_colour = self._pixels[pixel_index]

        self._modified_pixels += 1

        self._undo_redo(self._change_pixel, (event.x, event.y, self._selected_colour),
                        (event.x, event.y, old_colour), text="Draw")

    # ------------------------------------------------------------------------------------------------------------------

    def _drawing_left_up(self, event) -> None:
        if self._tool == TileEditor._FILL:
            self._flood_fill(event.x, event.y, self._selected_colour)
            return

        self._undo_actions.append(self._modified_pixels)
        self._redo_actions = []
        self._modified_pixels = 0
        self._update_undo_buttons()

    # ------------------------------------------------------------------------------------------------------------------

    def _drawing_left_drag(self, event) -> None:
        if self._tool == TileEditor._FILL:
            return

        # Prevent dragging outside the canvas
        if event.x < 0 or event.x >= 128 or event.y < 0 or event.y >= 128:
            return

        # The image is "zoomed in" x16, so: (x / 16) + ((y / 16) * number of items in a row)
        pixel_index = (event.x >> 4) + ((event.y >> 4) << 3)

        self._last_edited = pixel_index

        old_colour = self._pixels[pixel_index]

        self._undo_redo(self._change_pixel, (event.x, event.y, self._selected_colour),
                        (event.x, event.y, old_colour), text="Draw")
        self._modified_pixels += 1

    # ------------------------------------------------------------------------------------------------------------------

    def _drawing_right_click(self, event) -> None:
        # The image is "zoomed in" x16, so: (x / 16) + ((y / 16) * number of items in a row)
        pixel_index = (event.x >> 4) + ((event.y >> 4) << 3)

        self._select_colour(self._pixels[pixel_index])

    # ------------------------------------------------------------------------------------------------------------------

    def _palette_left_click(self, event) -> None:
        # First we need to understand which palette was clicked on
        # The four palettes are in a 2x2 area of 32x128 pixels, each palette taking 16x64 pixels
        # ...and each "colour" takes 16x16 pixels
        x = event.x >> 4
        y = event.y >> 6
        palette = x + (y << 1)

        colours = self.palette_editor.sub_palette(self._palette, palette)

        # Convert our RGB bytearray to strings, this is now the new palette
        self._colours = [f"#{colours[n]:02X}{colours[n + 1]:02X}{colours[n + 2]:02X}" for n in range(0, 12, 3)]

        # Now get the index of the selected colour within this palette
        y = event.y >> 4

        if palette > 1:
            y -= 4

        self._select_colour(y, palette)

    # ------------------------------------------------------------------------------------------------------------------

    def _select_colour(self, c: int, p: Optional[int] = None) -> None:
        """
        Selects a colour from a palette
        """
        self._selected_colour = c

        if p is not None:
            previous_palette = self._selected_palette
            self._selected_palette = p
        else:
            previous_palette = p = self._selected_palette

        x = (p << 4) % 32
        y = c << 4
        if p > 1:
            y += 64
        self.app.getCanvasWidget("TL_Canvas_Palette").coords(self._palette_rectangle, x + 1, y + 1, x + 14, y + 14)

        # Change image colours if a new palette has been selected
        if p != previous_palette:
            self._recolour_image()

    # ------------------------------------------------------------------------------------------------------------------

    def _change_pixel(self, x: int, y: int, c: int) -> None:
        """
        Changes the colour of one pixel.

        Parameters
        ----------
        x: int
            x coordinate on 128x128 canvas
        y: int
            y coordinate on 128x128 canvas
        c: int
            Colour value (0-3)
        """
        # The image is "zoomed in" x16, so: (x / 16) + ((y / 16) * number of items in a row)
        pixel_index = (x >> 4) + ((y >> 4) << 3)
        self._pixels[pixel_index] = c

        # Update the canvas
        if self._rectangles[pixel_index] > 0:
            self._drawing.itemconfigure(self._rectangles[pixel_index], fill=self._colours[c])

    # ------------------------------------------------------------------------------------------------------------------

    def _flood_fill(self, x: int, y: int, c: int) -> None:
        """
        Fills an area with the specified colour.
        Parameters
        ----------
        x: int
            x coordinate of the starting pixel in the drawing canvas
        y: int
            y coordinate of the starting pixel in the drawing canvas
        c: int
            Colour index within the current palette
        """
        # Translate the coordinates from 128x128 canvas to 8x8 tile
        x = x >> 4
        y = y >> 4
        # List of coordinates that we'll need to visit
        queue = [(x, y)]

        index = x + (y << 3)
        old_clr = self._pixels[index]

        self._undo_redo(self._change_pixel, (x << 4, y << 4, c), (x << 4, y << 4, old_clr), text="Fill Area")
        self._modified_pixels += 1

        # Four-direction non-recursive flood-fill algorithm in a single non-nested loop

        while len(queue) > 0:
            x, y = queue.pop()

            # 1 Pixel to the left
            node_x = x - 1
            node_y = y

            index = node_x + (node_y << 3)
            if node_x >= 0 and self._pixels[index] == old_clr:
                self._undo_redo(self._change_pixel, (node_x << 4, node_y << 4, c),
                                (node_x << 4, node_y << 4, old_clr), text="Fill Area")
                self._modified_pixels += 1
                queue.append((node_x, node_y))

            # 1 Pixel to the right
            node_x = x + 1
            node_y = y

            index = node_x + (node_y << 3)
            if node_x < 8 and self._pixels[index] == old_clr:
                self._undo_redo(self._change_pixel, (node_x << 4, node_y << 4, c),
                                (node_x << 4, node_y << 4, old_clr), text="Fill Area")
                self._modified_pixels += 1
                queue.append((node_x, node_y))

            # 1 Pixel down
            node_x = x
            node_y = y + 1

            index = node_x + (node_y << 3)
            if node_y < 8 and self._pixels[index] == old_clr:
                self._undo_redo(self._change_pixel, (node_x << 4, node_y << 4, c),
                                (node_x << 4, node_y << 4, old_clr), text="Fill Area")
                self._modified_pixels += 1
                queue.append((node_x, node_y))

            # 1 Pixel up
            node_x = x
            node_y = y - 1

            index = node_x + (node_y << 3)
            if node_y >= 0 and self._pixels[index] == old_clr:
                self._undo_redo(self._change_pixel, (node_x << 4, node_y << 4, c),
                                (node_x << 4, node_y << 4, old_clr), text="Fill Area")
                self._modified_pixels += 1
                queue.append((node_x, node_y))

        self._undo_actions.append(self._modified_pixels)
        self._redo_actions = []
        self._modified_pixels = 0
        self._update_undo_buttons()

    # ------------------------------------------------------------------------------------------------------------------

    def _undo(self, _event=None) -> None:
        try:
            count = self._undo_actions.pop()
        except IndexError:
            return

        self._undo_redo.undo(count)

        self._redo_actions.append(count)
        self._update_undo_buttons()

    # ------------------------------------------------------------------------------------------------------------------

    def _redo(self, _event=None) -> None:
        try:
            count = self._redo_actions.pop()
        except IndexError:
            return

        self._undo_redo.redo(count)

        self._undo_actions.append(count)
        self._update_undo_buttons()

    # ------------------------------------------------------------------------------------------------------------------

    def _show_palette(self) -> None:
        # Make two columns of eight colours each (two palettes per column)

        canvas = self.app.getCanvasWidget("TL_Canvas_Palette")

        colours = self.palette_editor.sub_palette(self._palette, 0)
        # Convert our RGB bytearray to strings
        clr = [f"#{colours[n]:02X}{colours[n + 1]:02X}{colours[n + 2]:02X}" for n in range(0, 12, 3)]
        x = 2
        y = 2
        for c in range(4):
            canvas.create_rectangle(x, y, x + 12, y + 12, fill=clr[c])
            y += 16

        # Second palette
        colours = self.palette_editor.sub_palette(self._palette, 1)
        clr = [f"#{colours[n]:02X}{colours[n + 1]:02X}{colours[n + 2]:02X}" for n in range(0, 12, 3)]
        x = 16
        y = 2
        for c in range(4):
            canvas.create_rectangle(x, y, x + 12, y + 12, fill=clr[c])
            y += 16

        # Third palette
        colours = self.palette_editor.sub_palette(self._palette, 2)
        clr = [f"#{colours[n]:02X}{colours[n + 1]:02X}{colours[n + 2]:02X}" for n in range(0, 12, 3)]
        x = 2
        y = 64
        for c in range(4):
            canvas.create_rectangle(x, y, x + 12, y + 12, fill=clr[c])
            y += 16

        # Last palette
        colours = self.palette_editor.sub_palette(self._palette, 3)
        clr = [f"#{colours[n]:02X}{colours[n + 1]:02X}{colours[n + 2]:02X}" for n in range(0, 12, 3)]
        x = 16
        y = 64
        for c in range(4):
            canvas.create_rectangle(x, y, x + 12, y + 12, fill=clr[c])
            y += 16

        # Add a selection marker
        self._palette_rectangle = canvas.create_rectangle(1, 1, 15, 15, width=2, outline="#F03030")

    # ------------------------------------------------------------------------------------------------------------------

    def _recolour_image(self) -> None:
        """
        Updates the colours of each pixel to reflect a new palette selection
        """
        colours = self.palette_editor.sub_palette(self._palette, self._selected_palette)

        # Convert our RGB bytearray to strings
        self._colours = c = [f"#{colours[n]:02X}{colours[n + 1]:02X}{colours[n + 2]:02X}" for n in range(0, 12, 3)]

        x = y = 0
        i = 0
        for pixel in self._pixels:
            # We just assume these items already exist: do not call this method before the image has been loaded!
            self._drawing.itemconfigure(self._rectangles[i], fill=c[pixel])

            x += 1
            i += 1
            if x > 7:
                x = 0
                y += 1

    # ------------------------------------------------------------------------------------------------------------------

    def _update_undo_buttons(self) -> None:
        if len(self._undo_actions) < 1:
            self.app.disableButton("TL_Undo")
            self.app.setButtonTooltip("TL_Undo", "Nothing to Undo")
        else:
            self.app.enableButton("TL_Undo")
            self.app.setButtonTooltip("TL_Undo", "Undo " + self._undo_redo.get_undo_text())

        if len(self._redo_actions) < 1:
            self.app.disableButton("TL_Redo")
            self.app.setButtonTooltip("TL_Redo", "Nothing to Redo")
        else:
            self.app.enableButton("TL_Redo")
            self.app.setButtonTooltip("TL_Undo", "Undo " + self._undo_redo.get_redo_text())

    # ------------------------------------------------------------------------------------------------------------------

    def _move_pixels(self, dst_x: int, dst_y: int) -> None:
        # Create an empty 8x8 array of pixels as our destination
        moved = bytearray([0] * 64)

        # Copy all pixels to the destination coordinates, wrapping around
        for y in range(8):
            if dst_y > 7:   # Wrap around vertically
                dst_y = 0

            for x in range(8):
                if dst_x > 7:   # Wrap around horizontally
                    dst_x = 0

                c = self._pixels[x + (y << 3)]
                moved[dst_x + (dst_y << 3)] = c

                dst_x += 1

            dst_y += 1

        self._pixels = moved
        self._recolour_image()
