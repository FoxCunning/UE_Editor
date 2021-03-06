__author__ = "Fox Cunning"

import os
import tkinter
from dataclasses import dataclass
from typing import List, TextIO

from PIL import Image, ImageTk

import colour
from appJar import gui
from appJar.appjar import ItemLookupError

from editor_settings import EditorSettings
from debug import log
import lzss as lzss
import rle as rle
from helpers import Point2D
from palette_editor import PaletteEditor
from text_editor import TextEditor, read_text, ascii_to_exodus
from enemy_editor import EnemyEditor
from rom import ROM


# ------------------------------------------------------------------------------------------------------------------
from undo_redo import UndoRedo


@dataclass(init=True, repr=False)
class NPCData:
    """
    Data from a map's NPC table
    """
    sprite_id: int = 0xFF
    dialogue_id: int = 0xFF
    starting_x: int = 0xFF
    starting_y: int = 0xFF


# ------------------------------------------------------------------------------------------------------------------

@dataclass(init=True, repr=False)
class MapTableEntry:
    """
    Map Table
    Found at 0F:FEA0
    8 bytes per entry
    """
    bank: int = 0  # 1 byte ROM bank number
    data_pointer: int = 0   # 2 bytes address of map data
    npc_pointer: int = 0    # 2 bytes address of NPC data
    entry_y: int = 0    # 1 byte player entry point Y
    entry_x: int = 0    # 1 byte player entry point X
    flags: int = 0      # 1 byte flags/ID (bit 7 set = dungeon)


# ------------------------------------------------------------------------------------------------------------------

@dataclass(init=True, repr=False)
class DungeonData:
    # Each dungeon has one message per level
    # The message pointers are in 0D:AAF6
    message_pointers: List[int]  # Default: 0xAAF6 + (Dungeon ID * 8) + (Level * 2)

    # These point to uncompressed strings of text in bank $0D
    messages: List[str]

    # Mark and fountain IDs are simply stored in the order they are found in each dungeon, there is no set amount
    mark_ids: List[int]
    fountain_ids: List[int]

    # Each dungeon map has a pair of pointers to a list of IDs, by default in 0D:B95D
    # Map0_marks_ptr, Map0_fount_ptr, Map1_marks_ptr... etc.
    mark_pointer: int = 0x0000  # Default: 0xB95D + (Dungeon ID * 4)
    fountain_pointer: int = 0x0000  # Default: 0xB95D + 2 + (Dungeon ID * 4)


# ----------------------------------------------------------------------------------------------------------------------

def no_stop() -> bool:
    """
    Used for sub-windows that should only be closed programmatically

    Returns
    -------
    bool
        False
    """
    return False


# ------------------------------------------------------------------------------------------------------------------

class MapEditor:
    """
    Map Editor

    Attributes
    ----------
    rom: ROM
        Instance of the ROM handler
    app: gui
        Main AppJar GUI instance
    palette_editor: PaletteEditor
        Instance of the Palette Editor (used to colour map tiles and NPCs)
    """

    def __init__(self, rom: ROM, app: gui, palette_editor: PaletteEditor, text_editor: TextEditor,
                 enemy_editor: EnemyEditor, settings: EditorSettings):
        self.rom: ROM = rom
        self.app: gui = app
        self.text_editor = text_editor
        self.enemy_editor = enemy_editor
        self.settings = settings

        # Map data table from 0F:FEA0-FF6F
        self.map_table: List[MapTableEntry] = []

        # 1 byte per map in table at $FB9F (1.09+)
        self.tileset_table: bytearray = bytearray()

        self.read_map_tables()

        # Compression methods used in each bank
        self.bank_compression: List[str] = ["LZSS", "none", "RLE", "none", "none", "none", "none", "none",
                                            "none", "none", "none", "none", "none", "none", "none", "none"]

        # Try to guess bank compression based on bytecode
        _LZSS_SIGNATURE = bytearray([0xA9, 0x78, 0x85, 0x2A, 0xA9, 0x00, 0x85, 0x29, 0xA9, 0x00, 0x85, 0xB4])
        _RLE_SIGNATURE = bytearray([0xA0, 0x00, 0xB1, 0x29, 0xE6, 0x29, 0xD0, 0x02, 0xE6, 0x2A, 0xC9, 0x81])
        for bank in range(0, 0xF):
            bytecode = rom.read_bytes(bank, 0x8000, 12)
            if bytecode == _LZSS_SIGNATURE:
                self.bank_compression[bank] = "LZSS"
            elif bytecode == _RLE_SIGNATURE:
                self.bank_compression[bank] = "RLE"
            else:
                self.bank_compression[bank] = "none"

        # Index in the map table of the currently loaded map
        self.map_index: int = 0
        # Image cache for the current map's tileset
        self.tiles: List[ImageTk.PhotoImage] = []
        # 64x64 map data
        self.map = []

        # NPC Data for the current map
        self.npc_data: List[NPCData] = []

        # Index of the NPC currently being edited, taken from the npc_data list
        self.npc_index: int = -1

        # Index of the selected entrance / moongate from the listbox in the Entrance Editor sub-sub-window
        self.selected_entrance: int = -1
        self.selected_moongate: int = -1

        # List of entrances to other maps that are accessible from this one
        self.entrances: List[Point2D] = []

        # Moongate coordinates for map 0
        # The last entry contains the coordinates of Dawn
        self.moongates: List[Point2D] = []

        # ID of the tiles that should replace each Moongate when it disappears
        # The 9th entry is for Dawn
        self.moongate_replacements: List[int] = []

        # The tile ID that will be created with two new moons (i.e. the town tile for Dawn be default)
        self.dawn_tile: int = 0xF

        # Index of this map's custom palette, or dungeon's main colour value
        self.map_colour: int = 0

        # --- Dungeon-specific data ---

        # Dungeon level, also used to calculate offset to portion of map data to show
        self.dungeon_level: int = 0

        self.dungeon_data: List[DungeonData] = []
        self.read_dungeon_data()

        # --- UI ---

        # Canvas image references for this map's tiles, so we can edit them without clearing the whole map
        self.canvas_map_images: List[int] = []

        # There will also be images to mark the party starting point and entrances to other locations
        self.canvas_icon_start: int = -1
        self.canvas_icon_entrances: List[int] = []
        self.canvas_icon_moongates: List[int] = []
        self.canvas_icon_dawn: int = -1

        self.canvas_map: tkinter.Canvas = tkinter.Canvas()

        # A reference to the palette editor
        self.palette_editor: PaletteEditor = palette_editor

        # Currently selected "tool"
        self.tool: str = "draw"
        # Currently selected tile ID
        self.selected_tile_id: int = 0

        self.selected_npc_graphics: int = 0

        # Image cache for NPC sprites
        self.npc_sprites: List[ImageTk.PhotoImage] = []

        # Canvas image references for this map's NPCs, used to hide/show/edit the canvas without redrawing all of it
        self.canvas_npc_images = []

        # Read NPC Palette indices from 0C:BA08
        # Each entry contains: bits 0,1 = bottom palette | bits 2,3 = top palette
        self.npc_palette_indices = []

        # These will be saved when clicking on the map
        self._last_tile: Point2D = Point2D(0xFF, 0xFF)

        # Keep count of how many tiles have been modified by a single action (e.g. single click, drag-drawing,
        # flood fill, etc.) for undo/redo
        self._modified_tiles: int = 0

        self._undo_redo: UndoRedo = UndoRedo()
        self._undo_actions: List[int] = []
        self._redo_actions: List[int] = []

        # List of all location names, as read from locations txt file
        self.location_names: List[str] = []
        try:
            # TODO Use different list instead of default one if name matches ROM file
            locations_file: TextIO = open("location_names.txt", "r")
            location_names = locations_file.readlines()
            locations_file.close()
            for m in range(self.max_maps()):
                if m >= len(location_names):
                    self.location_names.append("(Unnamed)")
                else:
                    self.location_names.append(location_names[m].rstrip("\n\r\a"))
        except IOError as error:
            log(3, "EDITOR", f"Error reading location names: {error}.")
            for m in range(self.max_maps()):
                self.location_names.append(f"MAP{m:02}")

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

    def load_tiles(self, map_index: int = -1, map_colour: int = -1) -> None:
        """
        Loads and caches tile graphics for the selected map.

        Parameters
        ----------
        map_index: int
            Index of the map being loaded; reloads the tiles for the current map if not provided
        map_colour: int
            Index of the custom map palette, or value of dungeon colour; read from ROM if not provided
        """
        # Clear the tiles palette and image cache
        self.app.clearCanvas("ME_Canvas_Tiles")
        self.tiles.clear()

        if map_index < 0:
            map_index = self.map_index
        else:
            self.map_index = map_index

        # self.info(f"Loading tiles for map 0x{map_index:02X}...")

        if self.is_dungeon(map_index):
            if map_colour < 0:
                # Get custom dungeon colour from ROM
                # This will only have effect if the ROM supports it
                address = self.rom.read_word(0xB, 0x86AF)
                self.map_colour = self.rom.read_byte(0xB, address + (self.get_map_id()))
            else:
                self.map_colour = map_colour

            self._load_dungeon_tiles()
        else:
            if map_colour < 0:
                # Customised map colours
                # This will only have effect if the ROM supports it
                address = self.rom.read_word(0xF, 0xEE03)
                self.map_colour = self.rom.read_byte(0xF, address + self.map_index)
            else:
                self.map_colour = map_colour

            self._load_map_tiles()

        # Pick default tile (0)
        self.selected_tile_id = 0
        self.tile_info(0)

    # ------------------------------------------------------------------------------------------------------------------

    def _load_dungeon_tiles(self) -> None:
        """
        Loads and caches tile images for a dungeon map
        """
        self.info("Loading dungeon tileset...")

        # Custom dungeon colour
        if self.rom.has_feature("custom map colours"):
            if self.map_colour < 0x20 or self.map_colour > 0x2C:
                # Revert to default if invalid value was read
                self.map_colour = 0x28
            colours = self.palette_editor.get_colours([0x0F,
                                                       self.map_colour, self.map_colour - 0x10, self.map_colour - 0x20])

            self.app.enableOptionBox("ME_Option_Map_Colours")

            # Select this colour from the option box
            colours_list: List[str] = []
            for i in range(13):
                colours_list.append(f"0x{i + 0x20:02X}")
            self.app.changeOptionBox("ME_Option_Map_Colours", options=colours_list, index=(self.map_colour - 0x20),
                                     callFunction=False)

            # Show the custom colours in the canvas next to the option box
            self.app.clearCanvas("ME_Canvas_Map_Colours")
            # Colour 0 (bright)
            image = Image.new('P', (11, 16), 1)
            image.putpalette(colours)
            self.app.addCanvasImage("ME_Canvas_Map_Colours", 6, 9, ImageTk.PhotoImage(image))
            # Colour 1 (medium)
            image = Image.new('P', (11, 16), 2)
            image.putpalette(colours)
            self.app.addCanvasImage("ME_Canvas_Map_Colours", 18, 9, ImageTk.PhotoImage(image))
            # Colour 2 (dark)
            image = Image.new('P', (11, 16), 3)
            image.putpalette(colours)
            self.app.addCanvasImage("ME_Canvas_Map_Colours", 28, 9, ImageTk.PhotoImage(image))

        else:
            palette = self.palette_editor.palettes[14]
            colours = self.palette_editor.get_colours(palette[8:12])
            # Disable widget for custom map colours if ROM does not support it
            self.app.setOptionBox("ME_Option_Map_Colours", 0, callFunction=False)
            self.app.disableOptionBox("ME_Option_Map_Colours")

        # Create a new, empty (for now) tile image
        tile = Image.new('P', (16, 16), 0)
        tile.putpalette(colours)

        addresses = [
            0x9500,  # Wall
            0x9520,  # Door
            0x9510,  # Hidden Door
            0x9540,  # Stairs Up
            0x9530,  # Stairs Down
            0x9550,  # Stairs Up + Down
            0x8960,  # M: Mark
            0x88F0,  # F: Fountain
            0x89C0,  # S: Message Sign
            0x8A00,  # W: Wind
            0x8900,  # G: Gremlins
            0x88C0,  # C: Treasure Chest
            0x89D0,  # T: Trap
            0x8000,  # Regular Floor
            0x8950,  # L: Time Lord
            0x94C0  # Safe Floor
        ]

        for tile_index in range(16):
            # Load a 8x8 pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, addresses[tile_index])))

            # Upscale the image x2
            scaled = bytearray()
            in_offset = 0
            for y in range(8):

                # Copy this line
                for x in range(8):
                    value = pixels[in_offset + x]
                    # Duplicate this pixel
                    scaled.append(value)
                    scaled.append(value)

                # Copy the same line again
                for x in range(8):
                    value = pixels[in_offset + x]
                    # Duplicate this pixel
                    scaled.append(value)
                    scaled.append(value)

                # Move to next input line
                in_offset = in_offset + 8

            image = Image.frombytes('P', (16, 16), bytes(scaled))
            tile.paste(image, (0, 0))

            # Convert image to something we can put on a Canvas Widget, and cache it
            image = ImageTk.PhotoImage(tile)
            self.tiles.append(image)

            # Show this tile in the tile palette
            x = 8 + (16 * (tile_index % 8))
            y = 8 + (16 * (tile_index >> 3))
            self.app.addCanvasImage("ME_Canvas_Tiles", x, y, image)

    # ------------------------------------------------------------------------------------------------------------------

    def _load_map_tiles(self) -> None:
        """
        Loads and caches tile images for a non-dungeon map
        """
        # self.info("Loading town/castle/continent tileset...")

        # Make a copy of the palette instead of referencing it directly, to avoid modifications
        if self.map_index == 0x0F:
            map_palette = list(self.palette_editor.palettes[2])  # Ambrosia palette

        else:
            map_palette = list(self.palette_editor.palettes[0])  # Regular map palette

        # Customised map colours
        if self.rom.has_feature("custom map colours") is False:
            # Disable widget for custom map colours if ROM does not support it
            self.app.setOptionBox("ME_Option_Map_Colours", 0, callFunction=False)
            self.app.disableOptionBox("ME_Option_Map_Colours")
        else:
            self.app.enableOptionBox("ME_Option_Map_Colours")

        if self.map_colour > 0 and self.rom.has_feature("custom map colours"):
            # If not zero, load the two custom colours into the current palette
            # self.info(f"Loading custom map colour set #{self.map_colour}")
            address = 0xEDEE + (self.map_colour * 2)
            map_palette[9] = self.rom.read_byte(0xF, address)
            map_palette[10] = self.rom.read_byte(0xF, address + 1)

        # Show custom colours in the appropriate widget
        self.app.clearCanvas("ME_Canvas_Map_Colours")

        colours = []
        rgb = bytearray(self.palette_editor.get_colour(map_palette[9]))
        colours.append(rgb[0])
        colours.append(rgb[1])
        colours.append(rgb[2])
        image = Image.new('P', (16, 16), 0)
        image.putpalette(colours)
        self.app.addCanvasImage("ME_Canvas_Map_Colours", 9, 9, ImageTk.PhotoImage(image))

        colours.clear()
        rgb = bytearray(self.palette_editor.get_colour(map_palette[10]))
        colours.append(rgb[0])
        colours.append(rgb[1])
        colours.append(rgb[2])
        image = Image.new('P', (16, 16), 0)
        image.putpalette(colours)
        self.app.addCanvasImage("ME_Canvas_Map_Colours", 26, 9, ImageTk.PhotoImage(image))

        # Select this colour from the option box
        colours_list: List[str] = []
        for i in range(9):
            colours_list.append(f"0x{i:02X}")
        self.app.changeOptionBox("ME_Option_Map_Colours", options=colours_list, index=self.map_colour,
                                 callFunction=False)

        if self.rom.has_feature("map tilesets"):
            self._load_tile_patterns(map_palette)
        else:
            self._load_tile_patterns_hardcoded(map_palette)

    # ------------------------------------------------------------------------------------------------------------------

    def _load_tile_patterns(self, map_palette: List[int]) -> None:
        # Get the index of the tileset for this map
        tileset = self.tileset_table[self.map_index]

        # First, create a list of pattern addresses using the "default" tileset
        addresses: List[int] = []
        for p in range(16):
            addresses.append(0x8A40 + (p * 64))     # Each 2x2 tile is 64 bytes long

        # The first tile will be at PPU address $1A40, the last one at $1E40

        # Each entry in the table at $0A:B600 has the format: source address in bank $0A, destination address in PPU,
        # number of bytes to copy

        # Tile index is: (PPU address - $1A40) / 64
        # Number of tiles in this entry: (bytes to copy) / 64

        # Now replicate the subroutine at 0A:9D90 to enact the substitutions
        if tileset == 0:        # Continent 1 (e.g. Sosaria)
            # $B606
            address = 0xB606
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B60C
            address = 0xB60C
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $BC36
            address = 0xB636
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B63C
            address = 0xB63C
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

        elif tileset == 1:      # Continent 2 (e.g. Ambrosia)
            # $B612
            address = 0xB612
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B618
            address = 0xB618
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B636
            address = 0xB636
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B63C
            address = 0xB63C
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B654
            address = 0xB654
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # B630
            address = 0xB630
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

        elif tileset == 2:      # Castle 1 (e.g. Castle British, Shrines)
            # $B61E
            address = 0xB61E
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B64E
            address = 0xB64E
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B624
            address = 0xB624
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B642
            address = 0xB642
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

        elif tileset == 3:      # Castle 2 (e.g. Castle Exodus)
            # $B61E
            address = 0xB61E
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B65A
            address = 0xB65A
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B64E
            address = 0xB64E
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

            # $B642
            address = 0xB642
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

        else:                   # Town / default
            # $B642
            address = 0xB642
            pattern_address = self.rom.read_word(0xA, address)
            tile_index = (self.rom.read_word(0xA, address + 2) - 0x1A40) >> 6
            tile_count = self.rom.read_word(0xA, address + 4) >> 6

            for t in range(tile_count):
                addresses[tile_index] = pattern_address
                pattern_address = pattern_address + 64
                tile_index = tile_index + 1

        # Now we have a full list of pattern addresses, we can use it to create our images
        tile_index = 0
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

            # We will combine the four patterns in a single 16x16 image and then cache it
            tile = Image.new('P', (16, 16), 0)
            tile.putpalette(colours)

            # Top-left pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, a)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image, (0, 0))
            # Bottom-left pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, a + 0x10)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image, (0, 8))
            # Top-right pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, a + 0x20)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image, (8, 0))
            # Bottom-right pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, a + 0x30)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image, (8, 8))

            image = ImageTk.PhotoImage(tile)
            self.tiles.append(image)

            # Show this tile in the tile palette
            x = 8 + (16 * (tile_index % 8))
            y = 8 + (16 * (tile_index >> 3))
            self.app.addCanvasImage("ME_Canvas_Tiles", x, y, image)

            # Next tile
            tile_index = tile_index + 1

    # ------------------------------------------------------------------------------------------------------------------

    def _load_tile_patterns_hardcoded(self, map_palette: List[int]) -> None:

        # Cache the 16 tiles used in this map
        for tile_index in range(16):
            # Load map palettes

            # Get palette index for this tile from table in ROM at 0D:856D
            palette_index = self.rom.read_byte(0x0D, 0x856D + tile_index) * 4
            colours = []
            for c in range(palette_index, palette_index + 4):
                colour_index = map_palette[c]
                rgb = bytearray(self.palette_editor.get_colour(colour_index))
                colours.append(rgb[0])  # Red
                colours.append(rgb[1])  # Green
                colours.append(rgb[2])  # Blue

            # We will combine the four patterns in a single 16x16 image and then cache it
            tile = Image.new('P', (16, 16), 0)
            tile.putpalette(colours)

            actual_tile_index = tile_index

            # TODO Detect vanilla game and use hardcoded vanilla substitutions

            # Some maps use alternative tiles, like the Force Field used in castle maps
            if self.map_index == 0:  # ---[ Sosaria ]---

                if tile_index == 0x06:  # Alt. Grass 0 replaces Yellow Floor
                    actual_tile_index = 0x3E
                elif tile_index == 0x08:  # Serpent Top replaces Brick Wall
                    actual_tile_index = 0x40
                elif tile_index == 0x09:  # Rocks replace Table
                    actual_tile_index = 0x41
                elif tile_index == 0x0B:  # Alt. Grass 1 replaces Green Floor
                    actual_tile_index = 0x3F
                elif tile_index == 0x0C:  # Serpent Bottom replaces Top Wall
                    actual_tile_index = 0x9C

            elif self.map_index == 0x0F:  # ---[ Ambrosia ]---

                if tile_index == 0x0E:  # Shrine Icon replaces Dungeon Icon
                    actual_tile_index = 0x10
                elif tile_index == 0x0D:  # Flower replaces Castle Icon
                    actual_tile_index = 0x9D
                elif tile_index == 0x06:  # Alt. Grass 0 replaces Yellow Floor
                    actual_tile_index = 0x3E
                elif tile_index == 0x0B:  # Alt. Grass 1 replaces Green Floor
                    actual_tile_index = 0x3F
                elif tile_index == 0x09:  # Rocks replace Table
                    actual_tile_index = 0x41

            elif self.map_index == 0x06 or self.map_index >= 0x15:  # ---[ Castle British and Shrines ]---

                if tile_index == 0x04:  # Ankh replaces Mountains
                    actual_tile_index = 0x3D
                elif tile_index == 0x0E:  # Force Field replaces Dungeon Icon
                    actual_tile_index = 0x13
                elif tile_index == 0x0F:  # Alt. Grass 0 replaces Town Icon
                    actual_tile_index = 0x3E
                elif tile_index == 0x06:  # Alternative castle floor
                    actual_tile_index = -20

            elif self.map_index == 0x14:  # ---[ Castle Exodus ]---

                if tile_index == 0x0E:  # Force Field replaces Dungeon Icon
                    actual_tile_index = 0x13
                elif tile_index == 0x0D:  # Computer Terminal replaces Castle Icon
                    actual_tile_index = 0x42
                elif tile_index == 0x0F:  # Alt. Grass 0 replaces Town Icon
                    actual_tile_index = 0x3E
                elif tile_index == 0x06:  # Alternative castle floor
                    actual_tile_index = -20

            else:  # ---[ Default / Towns ]---
                if tile_index == 0x0F:  # Alt. Grass 0 replaces Town Icon
                    actual_tile_index = 0x3E

            # Top-left pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, 0x8A40 + (actual_tile_index * 64))))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image, (0, 0))
            # Bottom-left pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, 0x8A50 + (actual_tile_index * 64))))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image, (0, 8))
            # Top-right pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, 0x8A60 + (actual_tile_index * 64))))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image, (8, 0))
            # Bottom-right pattern
            pixels = bytes(bytearray(self.rom.read_pattern(0x0A, 0x8A70 + (actual_tile_index * 64))))
            image = Image.frombytes('P', (8, 8), pixels)
            image.putpalette(colours)
            tile.paste(image, (8, 8))

            image = ImageTk.PhotoImage(tile)
            self.tiles.append(image)

            # Show this tile in the tile palette
            x = 8 + (16 * (tile_index % 8))
            y = 8 + (16 * (tile_index >> 3))
            self.app.addCanvasImage("ME_Canvas_Tiles", x, y, image)

    # ------------------------------------------------------------------------------------------------------------------

    def load_npc_sprites(self) -> None:
        """
        Loads and caches all NPC sprites
        """
        self.npc_sprites.clear()
        self.npc_sprites = []

        for npc_index in range(0, 0x1F):
            address = 0xBA08 + npc_index
            value = self.rom.read_byte(0xC, address)
            self.npc_palette_indices.append(value)

        # Cache NPC Sprites
        for npc_index in range(0, 0x1F):
            # print(f"NPC {npc_index}")
            sprite = Image.new('RGBA', (16, 16), 0xC0C0C000)
            address = 0x8000 + (npc_index * 16 * 4 * 8)  # eight meta-sprites, each containing four 16-byte patterns

            # TODO Use single colour for vanilla game

            # Get the top and bottom palettes for this sprite
            top_colours = []
            bottom_colours = []

            # Top palette index
            palette_index = (self.npc_palette_indices[npc_index] >> 2) * 4
            # print(f"Top palette: {palette_index}")

            for c in range(palette_index, palette_index + 4):
                try:
                    colour_index = self.palette_editor.palettes[1][c]
                except IndexError:
                    self.error(f"Index out of range for palette[1]: {c}")
                    colour_index = 0
                rgb = bytearray(self.palette_editor.get_colour(colour_index))
                top_colours.append(rgb[0])
                top_colours.append(rgb[1])
                top_colours.append(rgb[2])

            # Bottom palette index
            palette_index = (self.npc_palette_indices[npc_index] & 0x03) * 4
            # print(f"Bottom palette: {palette_index}")

            for c in range(palette_index, palette_index + 4):
                try:
                    colour_index = self.palette_editor.palettes[1][c]
                except IndexError:
                    self.error(f"Index out of range for palette[1]: {c}")
                    colour_index = 0
                rgb = bytearray(self.palette_editor.get_colour(colour_index))
                bottom_colours.append(rgb[0])  # Red
                bottom_colours.append(rgb[1])  # Green
                bottom_colours.append(rgb[2])  # Blue

            # Top-Left pattern
            pixels = bytes(bytearray(self.rom.read_pattern(3, address)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.info['transparency'] = 0
            image.putpalette(top_colours)
            sprite.paste(image.convert('RGBA'), (0, 0))
            # Bottom-Left pattern
            pixels = bytes(bytearray(self.rom.read_pattern(3, address + 0x10)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.info['transparency'] = 0
            image.putpalette(bottom_colours)
            sprite.paste(image.convert('RGBA'), (0, 8))
            # Top-Right pattern
            pixels = bytes(bytearray(self.rom.read_pattern(3, address + 0x20)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.info['transparency'] = 0
            image.putpalette(top_colours)
            sprite.paste(image.convert('RGBA'), (8, 0))
            # Bottom-Right pattern
            pixels = bytes(bytearray(self.rom.read_pattern(3, address + 0x30)))
            image = Image.frombytes('P', (8, 8), pixels)
            image.info['transparency'] = 0
            image.putpalette(bottom_colours)
            sprite.paste(image.convert('RGBA'), (8, 8))

            photo_image = ImageTk.PhotoImage(sprite)
            self.npc_sprites.append(photo_image)

        # Default sprite selection
        self.selected_npc_graphics = 0

    # ------------------------------------------------------------------------------------------------------------------

    def read_map_tables(self) -> None:
        """
        Reads the maps data table from ROM.
        """
        # Clear previous data if any
        if len(self.map_table) > 0:
            self.map_table.clear()
            self.map_table = []

        address = 0xFEA0
        for count in range(self.max_maps()):
            data = MapTableEntry()
            # Bank number
            data.bank = self.rom.read_byte(0xF, address)
            address += 1
            # Map data pointer
            data.data_pointer = self.rom.read_word(0xF, address)
            address += 2
            # NPC table pointer
            data.npc_pointer = self.rom.read_word(0xF, address)
            address += 2
            # Entry Y
            data.entry_y = self.rom.read_byte(0xF, address)
            address += 1
            # Entry X
            data.entry_x = self.rom.read_byte(0xF, address)
            address += 1
            # Flags/ID
            data.flags = self.rom.read_byte(0xF, address)
            address += 1

            self.map_table.append(data)

        if self.rom.has_feature("map tilesets"):
            self.tileset_table = self.rom.read_bytes(0xF, 0xFB9F, 32)
        else:
            self.tileset_table = [0] * 32

    # ------------------------------------------------------------------------------------------------------------------

    def save_map_tables(self) -> None:
        """
        Saves map table data to the ROM buffer.
        """
        address = 0xFEA0
        for m in range(self.max_maps()):
            # Byte 0: bank number
            self.rom.write_byte(0xF, address, self.map_table[m].bank)
            address = address + 1
            # Bytes 1, 2: map data pointer
            self.rom.write_word(0xF, address, self.map_table[m].data_pointer)
            address = address + 2
            # Bytes 3, 4: NPC data pointer
            self.rom.write_word(0xF, address, self.map_table[m].npc_pointer)
            address = address + 2
            # Byte 5: party entry Y
            self.rom.write_byte(0xF, address, self.map_table[m].entry_y)
            address = address + 1
            # Byte 6: party entry X
            self.rom.write_byte(0xF, address, self.map_table[m].entry_x)
            address = address + 1
            # Byte 7: flags/ID
            self.rom.write_byte(0xF, address, self.map_table[m].flags)
            address = address + 1

        if self.rom.has_feature("map tilesets"):
            self.rom.write_bytes(0xF, 0xFB9F, self.tileset_table[:self.max_maps()])

    # ------------------------------------------------------------------------------------------------------------------

    def read_dungeon_data(self) -> None:
        """
        Reads Message / Mark / Fountain pointers and values
        and stores them in self.dungeon_data
        NOTE: This needs the map_table to be already populated!
        """
        # Discard previous data, if needed
        for d in self.dungeon_data:
            d.message_pointers.clear()
            d.messages.clear()

        self.dungeon_data.clear()

        # Allocate room for 11 dungeons
        for _ in range(11):
            self.dungeon_data.append(DungeonData(message_pointers=[], messages=[], fountain_ids=[], mark_ids=[]))

        # self.info("Reading dungeon data...")

        # Get base address of message pointers table from ROM, by reading the instruction that is by default:
        # 0D:AA87    LDA $AAF6,X
        base_message_pointer = self.rom.read_word(0xD, 0xAA88)

        # Sanity check: if the pointer seems to be outside the bank, use the default one
        if 0x8000 > base_message_pointer > 0xBFFF:
            log(3, f"{self.__class__.__name__}",
                f"Base Dungeon Message pointer 0x{base_message_pointer:04X} out of scope."
                f"Using default value.")
            base_message_pointer = 0xAAF6

        # Get base address of mark/fountain pointers table from ROM, by reading the instruction that is by default:
        # 0D:AD91   LDA $B95D,X
        base_mark_pointer = self.rom.read_word(0xD, 0xAD92)

        # Same sanity check for this
        if 0x8000 > base_mark_pointer > 0xBFFF:
            self.warning(f"Base Mark/Fountain pointer 0x{base_mark_pointer:04X} out of scope."
                         f"Using default value.")
            base_mark_pointer = 0xB95D

        # Loop through all the maps, loading data for those who have the dungeon flag set
        index = 0
        for entry in self.map_table:

            if self.is_dungeon(index):

                # Retrieve dungeon ID
                dungeon_id = entry.flags & 0x1F

                if dungeon_id > 11:
                    log(3, f"{self.__class__.__name__}",
                        f"Invalid dungeon ID: {dungeon_id}. Value must be between 0 and 11.")
                    continue

                # Get data address
                map_bank = entry.bank
                map_address = entry.data_pointer

                # Read map data (64*32 = 2KB)
                map_data = self.rom.read_bytes(map_bank, map_address, 2046)

                # Read Mark and Fountain pointers
                mark_pointer = self.rom.read_word(0xD, base_mark_pointer + (dungeon_id * 4))
                fountain_pointer = self.rom.read_word(0xD, base_mark_pointer + 2 + (dungeon_id * 4))

                # Now we know where to find mark and fountain IDs, but we don't know how many we have to read, because
                # there is no sequence terminator character or byte count stored anywhere; so we need to read the map
                # and read the values as we go

                # Uncompress map data if needed
                map_compression = self.bank_compression[map_bank]
                if map_compression == "RLE":
                    map_data = rle.decode(map_data)
                elif map_compression == "LZSS":
                    map_data = lzss.decode(map_data)

                # Read one byte for each mark/fountain found
                fountain_count = 0
                fountain_ids = []
                mark_count = 0
                mark_ids = []
                for tile_id in map_data:
                    if tile_id == 6:
                        mark_ids.append(self.rom.read_byte(0xD, mark_pointer + mark_count))
                        mark_count = mark_count + 1
                    elif tile_id == 7:
                        fountain_ids.append(self.rom.read_byte(0xD, fountain_pointer + fountain_count))
                        fountain_count = fountain_count + 1

                # Now read the messages, these luckily have a terminator character
                message_pointers = []
                messages = []
                address = base_message_pointer + (dungeon_id * 16)  # 2 bytes x level x dungeon
                for _ in range(0, 8):
                    pointer = self.rom.read_word(0xD, address)
                    message_pointers.append(pointer)

                    # Read and cache decoded text
                    message = ""

                    # Also make sure the pointer is valid
                    if 0xBFFF > pointer > 0x8000:
                        message = read_text(self.rom, 0xD, pointer)

                    messages.append(message)

                    # Move to next message pointer
                    address = address + 2

                # Store data for this dungeon
                self.dungeon_data[dungeon_id] = DungeonData(message_pointers, messages, mark_ids, fountain_ids,
                                                            mark_pointer, fountain_pointer)

            # Advance to next map
            index = index + 1

        # Fill dungeon data that remained empty
        for d in self.dungeon_data:
            while len(d.messages) < 8:
                d.messages.append("")
            while len(d.message_pointers) < 8:
                d.message_pointers.append(0xBFFF)

    # ------------------------------------------------------------------------------------------------------------------

    def load_npc_data(self) -> None:
        """
        Loads NPC data for the currently loaded map and puts the NPC images on the canvas
        """
        bank = self.map_table[self.map_index].bank
        address = self.map_table[self.map_index].npc_pointer

        # Clear previous data
        self.npc_data.clear()
        self.npc_data = []

        # Remove previous NPC images
        for npc in self.canvas_npc_images:
            self.canvas_map.delete(npc)
        self.canvas_npc_images.clear()

        # We will use this to create a selectable OptionBox containing a list of NPCs
        npc_list = []

        # If either the bank number or the address is out of range, then we are creating an empty map
        if bank > 0xE or address > 0xBFFF:
            self.info(f"Creating empty NPC table for map {self.map_index}.")
            self.app.changeOptionBox("NPCE_Option_NPC_List", ["No NPCs found on this map"])
            return

        # Keep reading until 0xFF is found or 32 NPCs have been loaded
        for i in range(32):
            npc = NPCData()
            npc.sprite_id = self.rom.read_byte(bank, address)
            if npc.sprite_id == 0xFF:
                break
            address = address + 1
            npc.dialogue_id = self.rom.read_byte(bank, address)
            address = address + 1
            npc.starting_x = self.rom.read_byte(bank, address)
            address = address + 1
            npc.starting_y = self.rom.read_byte(bank, address)
            address = address + 1
            self.npc_data.append(npc)

            # Draw this NPC on the map
            canvas_x = (npc.starting_x << 4) + 8
            canvas_y = (npc.starting_y << 4) + 8
            npc_sprite = self.npc_sprites[npc.sprite_id & 0x7F]
            self.canvas_npc_images.append(self.app.addCanvasImage("ME_Canvas_Map", canvas_x, canvas_y, npc_sprite))

            # Add this NPC to the list widget
            npc_list.append(f"{i:02d}: G[0x{npc.sprite_id:02X}] D[0x{npc.dialogue_id:02X}] ({npc.starting_x},"
                            f"{npc.starting_y})")

        # Create empty images for missing NPCs; this is to avoid creating them later if a new NPC is made, otherwise
        # its sprite will be drawn on top of map icons (entrances, Moongates etc)
        npc_count = len(self.npc_data)
        for i in range(npc_count, 32):
            npc_sprite = self.app.addCanvasImage("ME_Canvas_Map", 255, 255, self.npc_sprites[0])
            self.canvas_map.itemconfigure(npc_sprite, state="hidden")
            self.canvas_npc_images.append(npc_sprite)

        # Update the widgets
        self.app.clearOptionBox("NPCE_Option_NPC_List")
        if len(npc_list) < 1:
            self.app.changeOptionBox("NPCE_Option_NPC_List", ["No NPCs found on this map"])
        else:
            self.app.changeOptionBox("NPCE_Option_NPC_List", npc_list)

    # ------------------------------------------------------------------------------------------------------------------

    def load_entrances(self) -> None:
        """
        Reads the table of entrance coordinates to other maps and shows them on the map canvas
        This only works for maps 0x0 and 0xF
        """
        # Clear previous entries
        for e in self.canvas_icon_entrances:
            self.canvas_map.delete(e)
        self.canvas_icon_entrances.clear()
        self.entrances.clear()

        self.app.clearListBox("EE_List_Entrances", callFunction=False)
        self.app.clearEntry("EE_Entrance_X", callFunction=False, setFocus=False)
        self.app.clearEntry("EE_Entrance_Y", callFunction=False, setFocus=False)

        # Remove previous starting position icon
        if self.canvas_icon_start > -1:
            self.canvas_map.delete(self.canvas_icon_start)
            self.canvas_icon_start = -1

        # Add an icon for the starting point on this map
        starting_x = self.map_table[self.map_index].entry_x
        starting_y = self.map_table[self.map_index].entry_y
        image = ImageTk.PhotoImage(Image.open("res/icon-start.gif"))
        self.canvas_icon_start = self.app.addCanvasImage("ME_Canvas_Map",
                                                         (starting_x << 4) + 8, (starting_y << 4) + 8, image)

        # Process entrances from Sosaria
        if self.map_index == 0x0:
            # Pre-load the entrance icon
            image = ImageTk.PhotoImage(Image.open("res/icon-entrance.gif"))

            # Read the address of the table from ROM, default in vanilla game:
            # C42F    LDA $FF70,Y
            # v1.09+:
            # C42F    LDA $FB50,Y
            address = self.rom.read_word(0xF, 0xC430)

            # Enable the widget containing the list of entrance nodes
            self.app.enableListBox("EE_List_Entrances")

            # The first continent always has 0x15 (21) entrances, the first one being an entrance to itself,
            # which is ignored
            for e in range(21):
                entrance = Point2D()
                entrance.x = self.rom.read_byte(0xF, address)
                entrance.y = self.rom.read_byte(0xF, address + 1)
                self.entrances.append(entrance)
                address = address + 2
                # Create an icon for this entrance
                image_id = self.app.addCanvasImage("ME_Canvas_Map",
                                                   (entrance.x << 4) + 8, (entrance.y << 4) + 8,
                                                   image)
                self.canvas_icon_entrances.append(image_id)
                # Only show entrance if coordinates are valid
                if entrance.x > 63 or entrance.y > 63:
                    self.canvas_map.itemconfigure(image_id, state="hidden")

                # Update widget with the list of entrances
                self.app.addListItem("EE_List_Entrances", f"0x{e:02X} -> {entrance.x:02d}, {entrance.y:02d}",
                                     select=False)

        # Process entrances from Ambrosia
        elif self.map_index == 0xF:
            # Pre-load the entrance icon
            image = ImageTk.PhotoImage(Image.open("res/icon-entrance.gif"))

            # Read the address of the table from ROM, default in vanilla game is:
            # C46A    LDA $C489,Y
            # v1.09+:
            # C46A    LDA $FB7A,Y
            # This also tells us how many extra entrances are allowed from the second continent
            address = self.rom.read_word(0xF, 0xC46B)

            # The second continent allows up to 11 entrances in v1.09+, otherwise 7
            if address == 0xC489:
                max_entrances = 7
            else:
                max_entrances = 11

            # Enable the widget containing the list of entrance nodes
            self.app.enableListBox("EE_List_Entrances")

            for e in range(max_entrances):
                entrance = Point2D()
                entrance.x = self.rom.read_byte(0xF, address)
                entrance.y = self.rom.read_byte(0xF, address + 1)
                self.entrances.append(entrance)
                address = address + 2
                # Create an icon for this entrance
                image_id = self.app.addCanvasImage("ME_Canvas_Map",
                                                   (entrance.x << 4) + 8, (entrance.y << 4) + 8,
                                                   image)
                self.canvas_icon_entrances.append(image_id)
                # Only show the icon if coordinates are valid
                if entrance.x > 63 or entrance.y > 63:
                    self.canvas_map.itemconfigure(image_id, state="hidden")

                # Update widget with the list of entrances
                self.app.addListItem("EE_List_Entrances",
                                     f"0x{e + 0x15:02X} -> {entrance.x:02d}, {entrance.y:02d}", select=False)

        # Enable the entrance editing widgets if there are any
        if len(self.entrances) > 0:
            # self.app.selectListItemAtPos("EE_List_Entrances", 0, callFunction=True)
            self.app.enableButton("EE_Button_Entrance_Set")
            self.app.enableButton("EE_Button_Entrance_Remove")
            self.app.enableEntry("EE_Entrance_X")
            self.app.enableEntry("EE_Entrance_Y")
        else:
            self.app.disableListBox("EE_List_Entrances")
            self.app.disableButton("EE_Button_Entrance_Set")
            self.app.disableButton("EE_Button_Entrance_Remove")
            self.app.disableEntry("EE_Entrance_X")
            self.app.disableEntry("EE_Entrance_Y")

    # ------------------------------------------------------------------------------------------------------------------

    def load_moongates(self) -> None:
        """
        Reads data from ROM concerning Moongate coordinates, moon phases and replacement tile ID, including
        those used for the town of Dawn
        """
        # Clear previous entries
        for m in self.canvas_icon_moongates:
            self.canvas_map.delete(m)
        if self.canvas_icon_dawn > -1:
            self.canvas_map.delete(self.canvas_icon_dawn)

        self.canvas_icon_moongates.clear()
        self.canvas_icon_dawn = -1

        self.app.clearListBox("EE_List_Moongates", callFunction=False)
        self.app.clearEntry("EE_Moongate_X", callFunction=False, setFocus=False)
        self.app.clearEntry("EE_Moongate_Y", callFunction=False, setFocus=False)

        self.app.clearCanvas("EE_Canvas_Moon_Phase")
        self.app.clearCanvas("EE_Canvas_Moongate_Tile")
        self.app.clearCanvas("EE_Canvas_Dawn_Tile")

        # Read the condition for the moongates and Dawn to be displayed, the default code is:
        # Bank $0B
        # B200    LDA $A8
        # B202    CMP #$0C
        check = self.rom.read_byte(0xB, 0xB201)
        value = self.rom.read_byte(0xB, 0xB203)

        if check == 0xA8:
            # Only activate Moongates on Continent maps
            self.app.disableOptionBox("EE_Option_Moongates_Map")
            if self.is_continent():
                moongates_active = True
            else:
                moongates_active = False

        elif value == self.map_index:
            self.app.enableOptionBox("EE_Option_Moongates_Map")
            moongates_active = True

        else:
            self.app.enableOptionBox("EE_Option_Moongates_Map")
            moongates_active = False

        if moongates_active:
            # Show Moongate icons and activate widgets
            self.app.enableListBox("EE_List_Moongates")
            self.app.enableButton("EE_Button_Moongate_Set")
            self.app.enableButton("EE_Button_Moongate_Remove")
            self.app.enableEntry("EE_Moongate_X")
            self.app.enableEntry("EE_Moongate_Y")
            self.app.enableOptionBox("EE_Option_Moongate_Tile")

            # Pre-load Moongate icon
            image = ImageTk.PhotoImage(Image.open("res/icon-moongate.gif"))

            # Read Moongate coordinates from ROM
            address = 0xC4D2
            for e in range(8):
                x = self.rom.read_byte(0xF, address)
                y = self.rom.read_byte(0xF, address + 1)
                address = address + 2

                self.moongates.append(Point2D(x, y))

                # Add this entry to the widget
                self.app.addListItem("EE_List_Moongates", f"{e} ({x:02d}, {y:02d})", select=False)

                # Show this Moongate's icon on the map
                canvas_image = self.app.addCanvasImage("ME_Canvas_Map", (x << 4) + 8, (y << 4) + 8, image)
                self.canvas_icon_moongates.append(canvas_image)

            # Read Moongate "replacement" tile IDs from ROM
            self.moongate_replacements.clear()
            address = 0xB2C7
            for e in range(8):
                tile_id = self.rom.read_byte(0xB, address) & 0x0F
                address = address + 1
                self.moongate_replacements.append(tile_id)

            # Read Dawn's coordinates (bank $0B)
            # B211    LDA #$26
            # B213    STA $30
            # B215    LDA #$36
            # B217    STA $2E
            x = self.rom.read_byte(0xB, 0xB212)
            y = self.rom.read_byte(0xB, 0xB216)
            self.moongates.append(Point2D(x, y))
            self.app.addListItem("EE_List_Moongates", f"Dawn: ({x:02d}, {y:02d})", select=False)

            # Show Dawn's icon on the map
            image = ImageTk.PhotoImage(Image.open("res/icon-dawn.gif"))
            self.canvas_icon_dawn = self.app.addCanvasImage("ME_Canvas_Map", (x << 4) + 8, (y << 4) + 8, image)

            # Read Dawn's entrance and replacement tiles (bank $0B)
            # B225    LDA #$8F
            # B22A    LDA #$82
            self.dawn_tile = self.rom.read_byte(0xB, 0xB226) & 0xF
            self.app.addCanvasImage("EE_Canvas_Dawn_Tile", 8, 8, self.tiles[self.dawn_tile])
            self.app.setOptionBox("EE_Option_Dawn_Tile", index=self.dawn_tile, callFunction=False)

            tile_id = self.rom.read_byte(0xB, 0xB22B) & 0x0F
            self.moongate_replacements.append(tile_id)

        else:
            # Disable Moongate widgets
            self.app.disableListBox("EE_List_Moongates")
            self.app.disableButton("EE_Button_Moongate_Set")
            self.app.disableButton("EE_Button_Moongate_Remove")
            self.app.disableEntry("EE_Moongate_X")
            self.app.disableEntry("EE_Moongate_Y")
            self.app.disableOptionBox("EE_Option_Moongate_Tile")

    # ------------------------------------------------------------------------------------------------------------------

    def select_tool(self, tool: str) -> None:
        """
        Selects a new tool to use when clicking on the map

        Parameters
        ----------
        tool: str
            Can be: draw, fill, clear, info, move_entrance, move_moongate, move_npc
        """
        if tool == "clear":
            choice = self.app.yesNoBox("Clear Map", "The map will be cleared. This operation cannot be undone.\n"
                                                    "Do you want to proceed?", "Map_Editor")
            if choice is True:
                # Clear the map

                # TODO Clear undo/redo history
                self._modified_tiles = 0

                if self.is_dungeon():
                    # Only clear the current dungeon level
                    # Put walls around the level first
                    for x in range(0, 16):
                        self._change_tile(x, 0, 0x00, False)
                    for y in range(1, 16):
                        self._change_tile(0, y, 0x00, False)

                    # Then make everything else a regular floor
                    for y in range(1, 16):
                        for x in range(1, 16):
                            self._change_tile(x, y, 0x0D, False)

                else:
                    # Clear the whole area
                    clear_npcs = self.app.yesNoBox("Clear Map", "Do you also want to remove all NPCs?", "Map_Editor")

                    self.app.setLabel("Progress_Label", "Clearing map, please wait...")
                    self.app.showSubWindow("Map_Progress")
                    root = self.canvas_map.winfo_toplevel()
                    root.update()
                    progress = 0.0
                    self.app.setMeter("ME_Progress_Meter", value=progress)
                    for y in range(64):
                        progress = progress + 1.55
                        for x in range(64):
                            self._change_tile(x, y, 0x00, False)
                        self.app.setMeter("ME_Progress_Meter", value=progress)
                        root.update()
                    # Hide progress window and re-focus map editor windows
                    self.app.hideSubWindow("Map_Progress")
                    self.app.showSubWindow("Entrance_Editor")
                    self.app.showSubWindow("NPC_Editor")
                    self.app.showSubWindow("Map_Editor")

                    if clear_npcs:
                        self.npc_data.clear()

                        for i in range(32):
                            # Hide the sprite
                            self.canvas_map.itemconfigure(self.canvas_npc_images[i], state="hidden")

                        # Empty widget with NPC list
                        self.app.changeOptionBox("NPCE_Option_NPC_List", ["No NPCs found on this map"])

                # Back to the drawing tool after clearing
                tool = "draw"

            else:
                # Action cancelled
                return

        _SELECTED = colour.PALE_TEAL
        _INACTIVE = colour.MEDIUM_GREY

        if tool == "draw":
            self.tool = tool
            self.app.setCanvasCursor("ME_Canvas_Map", "pencil")
            self.app.setButtonBg("ME_Button_Draw", _SELECTED)
            self.app.setButtonBg("ME_Button_Fill", _INACTIVE)
            self.app.setButtonBg("ME_Button_Info", _INACTIVE)
            self.app.setButtonBg("ME_Button_Clear", _INACTIVE)
            self.app.setLabel("ME_Selected_Tile_Position", "")

        elif tool == "fill":
            self.tool = tool
            self.app.setCanvasCursor("ME_Canvas_Map", "target")
            self.app.setButtonBg("ME_Button_Draw", _INACTIVE)
            self.app.setButtonBg("ME_Button_Fill", _SELECTED)
            self.app.setButtonBg("ME_Button_Info", _INACTIVE)
            self.app.setButtonBg("ME_Button_Clear", _INACTIVE)
            self.app.setLabel("ME_Selected_Tile_Position", "")

        elif tool == "info":
            self.tool = tool
            self.app.setCanvasCursor("ME_Canvas_Map", "question_arrow")
            self.app.setButtonBg("ME_Button_Draw", _INACTIVE)
            self.app.setButtonBg("ME_Button_Fill", _INACTIVE)
            self.app.setButtonBg("ME_Button_Info", _SELECTED)
            self.app.setButtonBg("ME_Button_Clear", _INACTIVE)
            self.app.setLabel("ME_Selected_Tile_Position", "")

        elif tool == "move_entrance":
            self.tool = tool
            self.app.setCanvasCursor("ME_Canvas_Map", "cross")
            self.app.setButtonBg("ME_Button_Draw", _INACTIVE)
            self.app.setButtonBg("ME_Button_Fill", _INACTIVE)
            self.app.setButtonBg("ME_Button_Info", _INACTIVE)
            self.app.setButtonBg("ME_Button_Clear", _INACTIVE)

        elif tool == "move_moongate":
            self.tool = tool
            self.app.setCanvasCursor("ME_Canvas_Map", "cross")
            self.app.setButtonBg("ME_Button_Draw", _INACTIVE)
            self.app.setButtonBg("ME_Button_Fill", _INACTIVE)
            self.app.setButtonBg("ME_Button_Info", _INACTIVE)
            self.app.setButtonBg("ME_Button_Clear", _INACTIVE)

        elif tool == "move_npc":
            self.tool = tool
            self.app.setCanvasCursor("ME_Canvas_Map", "man")
            self.app.setButtonBg("ME_Button_Draw", _INACTIVE)
            self.app.setButtonBg("ME_Button_Fill", _INACTIVE)
            self.app.setButtonBg("ME_Button_Info", _INACTIVE)
            self.app.setButtonBg("ME_Button_Clear", _INACTIVE)

        else:
            self.warning(f"Unimplemented tool: '{tool}'")

    # ----------------------------------------------------------------------------------------------------------------------

    def show_window(self) -> None:
        try:
            self.app.getFrameWidget("ME_Frame_Buttons")
        except ItemLookupError:
            self.create_widgets()

        self._undo_redo.clear()
        self._undo_actions = []
        self._redo_actions = []
        self._update_undo_buttons()

        self.app.showSubWindow("Map_Editor", hide=False)

        sw = self.app.openSubWindow("Map_Editor")
        sw.bind("<Control-z>", self._undo, add='')
        sw.bind("<Control-y>", self._redo, add='')

    # ----------------------------------------------------------------------------------------------------------------------

    def close_windows(self) -> bool:
        """
        Handles a request to close the map editor sub-window

        Returns
        -------
        bool
            Always returns true
        """
        # TODO Ask to save changes (if any)

        self._undo_redo.clear()
        self._undo_actions = []
        self._redo_actions = []
        self.canvas_map = tkinter.Canvas()

        self.app.hideSubWindow("NPC_Editor", useStopFunction=False)
        self.app.emptySubWindow("NPC_Editor")
        self.app.hideSubWindow("Entrance_Editor", useStopFunction=False)
        self.app.emptySubWindow("Entrance_Editor")
        self.app.hideSubWindow("Map_Editor", useStopFunction=False)
        self.app.emptySubWindow("Map_Editor")
        return True

    # ------------------------------------------------------------------------------------------------------------------

    def open_map(self, map_index: int, force_compression: str = "") -> None:
        """
        Opens the map at the given index in the map data table

        Parameters
        ----------
        map_index: int
            Index of the map to open (0 to 25)
        force_compression: str
            If specified, forces a decompression algorithm to be used instead of that assigned to the ROM bank
            where this map is found. Can be "none", "LZSS" or "RLE".
        """
        self.map_index = map_index
        map_data = self.map_table[map_index]
        if force_compression != "":
            compression = force_compression
        else:
            if map_data.bank <= 0xF:
                compression = self.bank_compression[map_data.bank]
            else:
                compression = "none"

        if self.is_dungeon() is False:
            self._load_map(map_data.bank, map_data.data_pointer, compression)
        else:
            self._load_dungeon(map_data.bank, map_data.data_pointer, compression)

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

    # ----------------------------------------------------------------------------------------------------------------------

    def update_map_table(self, map_data: MapTableEntry) -> None:
        """
        Updates the widgets in the Map Editor Tab

        Parameters
        ----------
        map_data: MapTableEntry
            Data to show
        """
        self.app.setEntry("MapInfo_Bank", f"0x{map_data.bank:02X}", False)
        self.app.setEntry("MapInfo_DataPtr", f"0x{map_data.data_pointer:04X}", False)

        # Get index of selected map

        try:
            map_index = self._get_selection_index("MapInfo_Select")
        except IndexError:
            value = self.app.getOptionBox("MapInfo_Select")
            log(3, "EDITOR", f"Error getting map index from: '{value}'.")
            map_index = 0

        # Basic info

        # In v1.09+, the map type depends on its flags entirely

        if self.max_maps() > 26:

            if map_index == 0:  # Map 0 is hardcoded
                map_type = 0

            # Dungeon flag
            elif map_data.flags & 0x80 != 0:
                map_type = 4

            # Continent flag
            elif map_data.flags & 0x20 != 0:
                # No Guards
                if map_data.flags & 0x40 != 0:
                    map_type = 0
                # With Guards
                else:
                    map_type = 1

            # Town / Castle
            else:
                # No Guards
                if map_data.flags & 0x40 != 0:
                    map_type = 2
                # With Guards
                else:
                    map_type = 3

        # Otherwise, it's a mix of dungeon flag and map index
        else:

            if map_data.flags & 0x80 != 0:  # Dungeons
                map_type = 4

            elif map_index == 0:  # Sosaria
                map_type = 0

            elif map_index == 6:  # Castle British
                map_type = 3

            elif map_index == 15:  # Ambrosia
                map_type = 2

            elif map_index == 20:  # Castle Death
                map_type = 2

            else:  # Towns / default
                map_type = 3

        self.app.setOptionBox("MapInfo_Basic_Type", map_type)

        if 0 <= map_data.bank <= 0xF:
            self.app.setOptionBox("MapInfo_Basic_Bank", map_data.bank)
        else:
            # Defaults based on type: dungeons on bank 2, anything else bank 0
            if map_data.flags & 0x80 != 0:
                self.app.setOptionBox("MapInfo_Basic_Bank", 2)
            else:
                self.app.setOptionBox("MapInfo_Basic_Bank", 0)

        map_id = map_data.flags & 0x1F
        self.app.setSpinBox("MapInfo_Basic_ID", map_id, callFunction=False)

        # Advanced info

        # For dungeon maps, the low byte is actually the facing direction
        # ...but only for version 1.09+, so we need to detect that based on the entry table address
        if self.max_maps() > 26:
            if self.is_dungeon(self.map_index):
                self.app.setLabel("MapInfo_h2", "Facing dir.:")
            else:
                self.app.setLabel("MapInfo_h2", "NPC Table:")
        self.app.setEntry("MapInfo_NPCPtr", f"0x{map_data.npc_pointer:04X}", False)

        self.app.setEntry("MapInfo_EntryX", f"{map_data.entry_x}", False)
        self.app.setEntry("MapInfo_EntryY", f"{map_data.entry_y}", False)
        self.app.setEntry("MapInfo_Flags", f"0x{map_data.flags:02X}", False)

        if self.rom.has_feature("map tilesets") is True:
            self.app.enableOptionBox("MapInfo_Tileset")
            self.app.setOptionBox("MapInfo_Tileset", self.tileset_table[map_index], callFunction=False)
        else:
            self.app.disableOptionBox("MapInfo_Tileset")

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

    def _map_button1_down(self, event: any) -> None:
        """
        Called when the user clicks on the map canvas.

        Parameters
        ----------
        event
            Mouse click event instance
        """
        tile_x = event.x >> 4
        tile_y = event.y >> 4

        # Save coordinates for future editing
        self._last_tile(tile_x, tile_y)

        if self.tool == "draw":
            old_tile_id = self.get_tile_id(tile_x, tile_y)

            # self._change_tile(tile_x, tile_y, self.selected_tile_id, False)
            self._undo_redo(self._change_tile, (tile_x, tile_y, self.selected_tile_id, False),
                            (tile_x, tile_y, old_tile_id, False), text="Draw")
            self._modified_tiles += 1

        elif self.tool == "fill":
            self.flood_fill(tile_x, tile_y)
            self.app.setCanvasCursor("ME_Canvas_Map", "target")     # Change mouse cursor back from "wait"

        elif self.tool == "info":
            # log(4, "EDITOR", f"Tile {tile_x}, {tile_y}")

            # Get the ID of the tile at the mouse click coordinates
            tile_id = self.get_tile_id(tile_x, tile_y)

            # Display info about this tile
            self.tile_info(tile_id, tile_x, tile_y)

            self.selected_tile_id = tile_id
            self.app.setLabel("ME_Selected_Tile_Position", f"[{tile_x}, {tile_y}]")

            if self.is_dungeon() is False:
                # Find an NPC at this coordinates and show it in NPC editor
                npc_index = self.find_npc(tile_x, tile_y)
                if npc_index > -1:
                    # log(4, "EDITOR", f"Found NPC #{npc_index}")
                    self.npc_index = npc_index
                    self.npc_info(npc_index)
                    self.app.setOptionBox("NPCE_Option_NPC_List", npc_index)
                    self.app.showLabelFrame("NPCE_Frame_Info")
                    # app.setButton("NPCE_Button_Create_Apply", "Apply Changes")

        elif self.tool == "move_entrance":
            self.select_tool("draw")
            if self.selected_entrance < 0 or len(self.app.getAllListItems("EE_List_Entrances")) < 1:
                return

            self.change_entrance(self.selected_entrance, tile_x, tile_y)

        elif self.tool == "move_moongate":
            self.select_tool("draw")
            if self.selected_moongate < 0 or len(self.app.getAllListItems("EE_List_Moongates")) < 1:
                return

            self.change_moongate(self.selected_moongate, tile_x, tile_y)

        elif self.tool == "move_npc":
            self.move_npc(tile_x, tile_y)
            # Select draw tool after we're done moving
            self.select_tool("draw")

    # ----------------------------------------------------------------------------------------------------------------------

    def _map_button1_up(self, _event=None) -> None:
        if self.tool != "draw":
            return

        # Display last tile position
        self.app.setLabel("ME_Selected_Tile_Position", f"[{self._last_tile.x}, {self._last_tile.y}]")

        self._undo_actions.append(self._modified_tiles)
        self._redo_actions = []
        self._modified_tiles = 0
        self._update_undo_buttons()

    # ----------------------------------------------------------------------------------------------------------------------

    def _map_button1_drag(self, event) -> None:
        if self.tool != "draw":
            return

        tile_x = event.x >> 4
        tile_y = event.y >> 4

        if self._last_tile.x == tile_x and self._last_tile.y == tile_y:
            return

        # Save coordinates for future editing
        self._last_tile(tile_x, tile_y)

        old_tile_id = self.get_tile_id(tile_x, tile_y)

        # self._change_tile(tile_x, tile_y, self.selected_tile_id, False)
        self._undo_redo(self._change_tile, (tile_x, tile_y, self.selected_tile_id, False),
                        (tile_x, tile_y, old_tile_id, False), text="Draw")
        self._modified_tiles += 1

    # ----------------------------------------------------------------------------------------------------------------------

    def map_input(self, widget: str) -> None:
        """
        Generic button callback for the Map Editor sub-window and its sub-windows

        Parameters
        ----------
        widget: str
            Name of the Button widget being pressed

        """
        if widget == "ME_Button_Draw":
            self.select_tool("draw")

        elif widget == "ME_Button_Fill":
            self.select_tool("fill")

        elif widget == "ME_Button_Clear":
            self.select_tool("clear")

        elif widget == "ME_Button_Info":
            self.select_tool("info")

        elif widget == "MapEditor_Discard":
            self.close_windows()

        elif widget == "MapEditor_Save":
            if self.settings.get("sync npc sprites"):
                sync = True
            else:
                sync = False
            self.save_map(sync)

            # Reload enemy sprites if sync sprite options is selected
            if sync:
                self.enemy_editor.read_enemy_data(self.text_editor)

            self.app.hideSubWindow("Entrance_Editor")
            self.app.hideSubWindow("NPC_Editor")
            self.app.hideSubWindow("Map_Editor")
            # Addresses may have changed due to reallocation, so refresh display
            self.update_map_table(self.map_table[self.map_index])

        elif widget == "MapEditor_Import":
            # Browse for a file to import
            file_name = self.app.openBox("Import Map Data...", self.settings.get("last map import path"),
                                         [("4-bit packed", "*.bin"), ("LZSS Compressed", "*.lzss"),
                                          ("RLE Encoded", "*.rle")],
                                         asFile=False, parent="Map_Editor", multiple=False)
            if file_name != "":
                self.import_map(file_name)
                directory = os.path.dirname(file_name)
                self.settings.set("last map import path", directory)

        elif widget == "MapEditor_Export":
            # Ask for a file name
            file_name = self.app.saveBox("Export Map Data...", None, self.settings.get("last map export path"), ".bin",
                                         [("4-bit packed", "*.bin"), ("LZSS Compressed", "*.lzss"),
                                          ("RLE Encoded", "*.rle")],
                                         parent="Map_Editor")
            if file_name != "":
                self.export_map(file_name)
                directory = os.path.dirname(file_name)
                self.settings.set("last map export path", directory)

        elif widget == "ME_Button_Undo":
            self._undo()

        elif widget == "ME_Button_Redo":
            self._redo()

        elif widget == "ME_Option_Map_Colours":
            # Do nothing if ROM doesn't support custom map colours
            if self.rom.has_feature("custom map colours") is False:
                return

            # Read value
            try:
                colour_value = int(self.app.getOptionBox("ME_Option_Map_Colours"), 16)
            except ValueError:
                return
            # Reload tiles using the new colour
            self.load_tiles(map_colour=colour_value)
            # Redraw the map
            self.redraw_map()

        elif widget == "NPCE_Option_NPC_List":
            try:
                # Move the map to the specified NPC's position
                npc_index = int(self.app.getOptionBox("NPCE_Option_NPC_List")[:2])
                x = self.npc_data[npc_index].starting_x
                y = self.npc_data[npc_index].starting_y
                if (0 <= x <= 63) and (0 <= y <= 63):
                    self.jump_to(x, y)

                # Populate the info frame with the selected character's data
                npc_index = int(self.app.getOptionBox("NPCE_Option_NPC_List")[:2])
                self.npc_index = npc_index
                self.npc_info(npc_index)
                self.app.showLabelFrame("NPCE_Frame_Info")

            except ValueError:
                pass

        elif widget == "NPCE_Entry_Dialogue_ID":
            # Get Dialogue/Function ID
            value = self.app.getEntry("NPCE_Entry_Dialogue_ID")
            try:
                dialogue_id = int(value, 16)
            except ValueError:
                # app.errorBox("Apply NPC Changes", f"ERROR: Invalid Dialogue/Function ID '{value}'.\n"
                #                                  "Please enter a numeric value in hexadecimal format (e.g.: 0x1B).",
                #             parent="NPC_Editor")
                return

            self.set_npc_dialogue(dialogue_id)

        elif widget == "NPCE_Create":
            # This will create a new NPC with default attributes
            self.npc_info(-1)
            self.app.showLabelFrame("NPCE_Frame_Info")
            # app.setButton("NPCE_Button_Create_Apply", "Create NPC")

        elif widget == "NPCE_Button_Position":
            self.select_tool("move_npc")

        elif widget == "NPCE_Button_Edit_Dialogue":
            string_id = self.app.getEntry("NPCE_Entry_Dialogue_ID")
            try:
                value = int(string_id, 16)
                if 0 <= value <= 0xE5:
                    self.text_editor.show_advanced_window(value, "Dialogue")
                elif 0xF0 <= value <= 0xFF:
                    self.text_editor.show_special_window(value, self.location_names)
                else:
                    self.app.warningBox("Edit Dialogue", f"{string_id} is not a valid Dialogue ID.",
                                        parent="NPC_Editor")
            except ValueError:
                self.app.warningBox("Edit Dialogue", f"{string_id} is not a valid Dialogue ID.", parent="NPC_Editor")

        else:
            self.warning(f"Unimplemented Map Editor button: {widget}")

    # ------------------------------------------------------------------------------------------------------------------

    def create_widgets(self) -> None:

        with self.app.subWindow("Map_Editor"):

            # noinspection PyArgumentList
            self.app.setStopFunction(self.close_windows)

            # Buttons
            with self.app.frame("ME_Frame_Buttons", row=0, column=0, padding=[4, 0], sticky='NEW', stretch='ROW'):
                self.app.button("MapEditor_Save", name="Save Changes", value=self.map_input, image="res/floppy.gif",
                                tooltip="Apply Changes", row=0, column=0)
                self.app.button("MapEditor_Import", name="Import", value=self.map_input, image="res/import.gif",
                                tooltip="Import from File", row=0, column=1)
                self.app.button("MapEditor_Export", name="Export", value=self.map_input, image="res/export.gif",
                                tooltip="Export to File", row=0, column=2)
                self.app.button("MapEditor_Discard", name="Discard Changes", value=self.map_input,
                                image="res/close.gif",
                                tooltip="Close and Discard Changes", row=0, column=3)

                self.app.button("ME_Button_Undo", self.map_input, image="res/undo.gif", sticky="E",
                                tooltip="Nothing to Undo", row=0, column=5)
                self.app.button("ME_Button_Redo", self.map_input, image="res/redo.gif", sticky="E",
                                tooltip="Nothing to Redo", row=0, column=6)

            # Tile picker / toolbox
            with self.app.frame("ME_Frame_Tile_Picker", row=1, column=0, padding=[4, 0], stretch='COLUMN', sticky='EW'):
                self.app.button("ME_Button_Draw", self.map_input, name="Draw", image="res/pencil.gif",
                                tooltip="Draw", height=32, row=0, column=0)
                self.app.button("ME_Button_Fill", self.map_input, name="Fill", image="res/bucket.gif",
                                tooltip="Flood Fill", height=32, row=0, column=1)
                self.app.button("ME_Button_Clear", self.map_input, name="Clear", image="res/eraser.gif",
                                tooltip="Clear Map", height=32, row=0, column=2)
                self.app.button("ME_Button_Info", self.map_input, name="Info", image="res/zoom.gif",
                                tooltip="Tile Info", height=32, row=0, column=3)
                self.app.canvas("ME_Canvas_Tiles", row=0, column=4, width=128, height=32, stretch='NONE', map=None,
                                bg="black").bind("<Button-1>", self.map_pick_tile, add='')
                self.app.setCanvasCursor("ME_Canvas_Tiles", "hand2")

            # Tile info frame
            with self.app.labelFrame("Tile Info", padding=[1, 1], row=2, column=0, stretch='BOTH', sticky='EW'):
                self.app.canvas("ME_Canvas_Selected_Tile", row=0, column=0, width=16, height=16, stretch='NONE',
                                map=None, bg=colour.PALE_NAVY)
                self.app.label("ME_Selected_Tile_Name", "", row=0, column=1)
                self.app.label("ME_Selected_Tile_Properties", "", row=0, column=2)
                self.app.label("ME_Selected_Tile_Position", "", row=0, column=3)

                # Special tile info
                with self.app.frame("ME_Frame_Special_Tile", row=0, column=4, padding=[4, 1]):
                    self.app.label("ME_Special_Tile_Name", "Special", row=0, column=0, font=10)
                    self.app.optionBox("ME_Special_Tile_Value", ["", "", "", ""], row=0, column=1, width=10,
                                       change=self.select_dungeon_special_type, font=9)

            # Colours and special options
            with self.app.frame("ME_Frame_Map_Options", row=3, column=0, padding=[4, 4], stretch='ROW', sticky='EW'):
                # Column 0
                self.app.label("Map-specific colours:", row=0, column=0, sticky='E')
                # Column 1
                values: List[str] = []
                for i in range(9):
                    values.append(f"0x{i:02X}")
                self.app.optionBox("ME_Option_Map_Colours", values, row=0, column=1, width=4, sticky='W',
                                   change=self.map_input)
                del values
                # Column 2
                self.app.canvas("ME_Canvas_Map_Colours", width=35, height=18, row=0, column=2, stretch='NONE',
                                map=None, bg=colour.BLACK)

            # Map Canvas
            with self.app.scrollPane("ME_Scroll_Pane", row=4, column=0, stretch='BOTH', padding=[0, 0], sticky='NEWS'):
                # Map Canvas
                self.app.canvas("ME_Canvas_Map", row=0, column=0, width=1024, height=1024, map=None,
                                bg="black")

                # Dungeon tools
                with self.app.frame("ME_Frame_Dungeon_Tools", row=0, column=1, padding=[8, 0], sticky='SEWN',
                                    stretch='COLUMN', bg=colour.PALE_ORANGE):
                    # Dungeon tools Row #0
                    self.app.label("ME_Label_Dungeon_Level", "Floor:", row=0, column=0)
                    # Dungeon tools Row #1
                    self.app.optionBox("ME_Option_Dungeon_Level",
                                       [" 1 ", " 2 ", " 3 ", " 4 ", " 5 ", " 6 ", " 7 ", " 8 "],
                                       change=self.select_dungeon_level, row=1, column=0, stretch='NONE', sticky='NEW')
                    # Dungeon tools Row #2
                    self.app.label("ME_Label_Dungeon_Message", "Message Sign:", row=2, column=0, font=9)
                    # Dungeon tools Row #3
                    self.app.textArea("ME_Text_Dungeon_Message", "", row=3, column=0, sticky='WE', height=5,
                                      scroll=True,
                                      width=12, change=self.change_dungeon_message).setFont(size=9)
                    # Dungeon tools Row #4
                    self.app.label("ME_Label_Marks_Count", "Marks: 0", row=4, column=0, width=10,
                                   stretch='NONE', sticky='NEW', font=9)
                    # Dungeon tools Row #5
                    self.app.label("ME_Label_Fountains_Count", "Fountains: 0", row=5, column=0, width=10,
                                   stretch='NONE', sticky='NEW', font=9)
                    # Dungeon tools Row #6
                    self.app.checkBox("ME_Auto_Ladders", text="Auto-Ladder", value=True, row=6, column=0,
                                      tooltip="Automatically create corresponding ladder on the connecting floor",
                                      font=9)

            # Progress Sub-Sub-Window ----------------------------------------------------------------------------------
            with self.app.subWindow("Map_Progress", title="Redraw Map", modal=True, size=[300, 100], padding=[4, 4],
                                    bg=colour.PALE_LIME):
                # noinspection PyArgumentList
                self.app.setStopFunction(no_stop)

                self.app.label("Progress_Label", "Please wait...", row=0, column=0, font=16)
                self.app.meter("ME_Progress_Meter", value=0, stretch="BOTH", sticky="WE",
                               row=1, column=0, fill=colour.MEDIUM_BLUE)

            # Entrance / Moongate Editor Sub-Sub-Window ----------------------------------------------------------------
            with self.app.subWindow("Entrance_Editor", "Entrances / Moongates", size=[256, 440], modal=False,
                                    resizable=False, bg=colour.PALE_OLIVE):
                # noinspection PyArgumentList
                self.app.setStopFunction(self.close_windows)

                # Entrances frame
                with self.app.labelFrame("EE_Frame_Entrances", name="Entrances", row=0, column=0, stretch="ROW",
                                         sticky='NEW'):
                    # Column 0
                    self.app.listBox("EE_List_Entrances", list(range(22)), change=self.entrance_input, row=0,
                                     column=0, width=16, font=10)

                    # Column 1
                    with self.app.frame("EE_Frame_Entrance_Tools", padding=[1, 1], row=0, column=1):
                        # Row 0
                        self.app.button("EE_Button_Entrance_Set", name="Move", image="res/target.gif", row=0, column=0,
                                        value=self.entrance_input, tooltip="Pick new coordinates from the map")
                        self.app.button("EE_Button_Entrance_Remove", name="Delete", image="res/eraser.gif",
                                        value=self.entrance_input,
                                        tooltip="Clear this entrance (moves it off map)",
                                        row=0, column=1)
                        # Row 1
                        self.app.label("EE_Label_h2", "X:", row=1, column=0, font=9)
                        self.app.label("EE_Label_h3", "Y:", row=1, column=1, font=9)
                        # Row 2
                        self.app.entry("EE_Entrance_X", value=255, change=self.entrance_input, width=4,
                                       row=2, column=0, font=9)
                        self.app.entry("EE_Entrance_Y", value=255, change=self.entrance_input, width=4,
                                       row=2, column=1, font=9)
                        # Row 3
                        self.app.label("EE_Label_h4", "Map:", row=3, column=0, font=9)
                        self.app.label("EE_Entrance_Map", "0x00", width=4, row=3, column=1, font=9)

                # Moongates frame
                with self.app.labelFrame("EE_Frame_Moongates", name="Moongates", row=1, column=0, stretch='BOTH',
                                         expand='BOTH', sticky='SEWN'):
                    # Column 0
                    with self.app.frame("EE_Frame_Moongate_List", row=0, column=0):
                        # Row 0
                        self.app.listBox("EE_List_Moongates", list(range(9)), change=self.entrance_input,
                                         colspan=2, width=10, height=6, row=0, column=0, font=10)
                        # Row 1
                        self.app.label("EE_Label_h10", "Dawn tile:", stretch='BOTH', sticky='NEWS', row=1, column=0,
                                       font=9)
                        self.app.canvas("EE_Canvas_Dawn_Tile", width=16, height=16, bg=colour.BLACK, map=None,
                                        stretch='BOTH', sticky='W', row=1, column=1)
                        # Row 2
                        tiles_list: List[str] = []
                        for i in range(16):
                            tiles_list.append(f"0x{i:02X}")
                        self.app.optionBox("EE_Option_Dawn_Tile", tiles_list, change=self.entrance_input,
                                           colspan=2, sticky='EW', row=2, column=0, font=9)
                        # Row 3
                        self.app.label("EE_Label_h9", "Active on:", row=3, column=0, colspan=2, font=9)
                        # Row 4
                        self.app.optionBox("EE_List_Moongates_Options", ["Continent maps", "A specific map"],
                                           change=self.entrance_input,
                                           row=4, column=0, colspan=2, sticky='EW', font=9)
                        # Row 5
                        self.app.optionBox("EE_Option_Moongates_Map", self.location_names, sticky='EW',
                                           row=5, column=0, colspan=2, font=9)

                    # Column 1
                    with self.app.frame("EE_Frame_Moongate_Tools", padding=[1, 1], row=0, column=1):
                        # Row 0
                        self.app.button("EE_Button_Moongate_Set", name="Move", image="res/target.gif", row=0, column=0,
                                        value=self.entrance_input, tooltip="Pick new coordinates from the map")
                        self.app.button("EE_Button_Moongate_Remove", name="Delete", image="res/eraser.gif", row=0,
                                        column=1,
                                        value=self.entrance_input,
                                        tooltip="Clear this Moongate (moves it off map)")
                        # Row 1
                        self.app.label("EE_Label_Moongate_X", "X:", row=1, column=0, font=9)
                        self.app.label("EE_Label_Moongate_Y", "Y:", row=1, column=1, font=9)
                        # Row 2
                        self.app.entry("EE_Moongate_X", value=255, width=4, row=2, column=0,
                                       change=self.entrance_input, font=9)
                        self.app.entry("EE_Moongate_Y", value=255, width=4, row=2, column=1,
                                       change=self.entrance_input, font=9)
                        # Row 3
                        self.app.label("EE_Label_h7", "Moon Phase:", sticky='EW', row=3, column=0, colspan=2, font=9)
                        # Row 4
                        self.app.canvas("EE_Canvas_Moon_Phase", width=16, height=16, bg=colour.BLACK, map=None,
                                        stretch='BOTH', sticky='N', row=4, column=0, colspan=2)
                        # Row 5
                        self.app.label("EE_Label_h8", "'Ground':", sticky='EW', row=5, column=0, colspan=2, font=9)
                        # Row 6
                        self.app.canvas("EE_Canvas_Moongate_Tile", width=16, height=16, bg=colour.BLACK, map=None,
                                        stretch='BOTH', sticky='N', row=6, column=0, colspan=2)
                        # Row 7
                        self.app.optionBox("EE_Option_Moongate_Tile", tiles_list, row=7, column=0, colspan=2,
                                           height=1, change=self.entrance_input, sticky='N', font=9)

            # NPC Editor Sub-Sub-Window --------------------------------------------------------------------------------
            with self.app.subWindow("NPC_Editor", "NPC Editor", size=[360, 300], modal=False, resizable=False):
                # noinspection PyArgumentList
                self.app.setStopFunction(self.close_windows)

                # NPC Actions
                with self.app.frame("NPCE_Frame_Top", row=0, column=0, stretch='COLUMN', sticky='NEW', padding=[4, 0]):
                    self.app.button("NPCE_Create", self.map_input, name=" Create a New NPC ",
                                    row=0, column=0, font=9)
                    self.app.label("NPCE_Label", "Or select an existing one from the list below",
                                   row=1, column=0, font=9)

                # NPC Selection
                with self.app.frame("NPCE_Frame_Middle", row=1, column=0, stretch='COLUMN', sticky='NEW',
                                    padding=[4, 4]):
                    self.app.optionBox("NPCE_Option_NPC_List", ["No NPCs on this map"], change=self.map_input,
                                       row=0, column=0, width=28, font=9)
                    self.app.button("NPCE_Delete", self.map_input, name="Delete", image="res/eraser.gif",
                                    tooltip="Delete NPC", row=0, column=1, font=9)

                # NPC Info
                with self.app.labelFrame("NPCE_Frame_Info", name="NPC Info", row=2, column=0, stretch='BOTH',
                                         sticky='NEWS', padding=[4, 4]):
                    with self.app.frame("NPCE_Frame_Info_Top", row=0, column=0, padding=[4, 0]):
                        # NPC Graphics
                        self.app.label("NPCE_Sprite_ID", "GFX Index: ", row=0, column=0, font=10)
                        options = []
                        for i in range(0x1F):
                            options.append(f"0x{i:02X}")
                        self.app.optionBox("NPCE_Option_Graphics", options, change=self.npc_select_graphics, row=0,
                                           column=1,
                                           font=9)
                        self.app.canvas("NPCE_Canvas_New_Sprite", row=0, column=2, width=16, height=16, stretch='NONE',
                                        map=None, bg=colour.MEDIUM_GREY)
                        self.app.checkBox("NPCE_Check_Static", text="Static", change=self.npc_select_graphics, row=0,
                                          column=3,
                                          font=9)

                    with self.app.frame("NPCE_Frame_Info_Palettes", row=1, column=0, padding=[4, 0]):
                        # 1
                        self.app.label("NPCE_Label_Palette_1", "Palette 1:", row=0, column=0, font=9)
                        self.app.optionBox("NPCE_Palette_1", ["0", "1", "2", "3"], change=self.npc_select_graphics,
                                           row=0, column=1, font=9)
                        # 2
                        self.app.label("NPCE_Label_Palette_2", "Palette 2:", row=0, column=2, font=9)
                        self.app.optionBox("NPCE_Palette_2", ["0", "1", "2", "3"], change=self.npc_select_graphics,
                                           row=0, column=3, font=9)

                    with self.app.frame("NPCE_Frame_Info_Bottom", row=2, column=0, padding=[4, 0]):
                        # NPC Properties Row 0
                        self.app.label("NPCE_Dialogue_ID", "Dialogue/Function:", row=0, column=0, colspan=2, font=9)
                        self.app.label("NPCE_Starting_Position", "Starting Pos: 0, 0", row=0, column=2, font=9)
                        # NPC Properties Row 1
                        self.app.entry("NPCE_Entry_Dialogue_ID", "0x00", change=self.map_input, case="upper",
                                       row=1, column=0, font=9)
                        self.app.button("NPCE_Button_Edit_Dialogue", value=self.map_input, image="res/edit-dlg.gif",
                                        tooltip="Edit Dialogue Text", row=1, column=1, font=9)
                        self.app.button("NPCE_Button_Position", self.map_input, name="Set Position", row=1, column=2,
                                        font=9)

        # Bind events
        self.canvas_map = self.app.getCanvas("ME_Canvas_Map")
        self.canvas_map.bind("<ButtonPress-1>", self._map_button1_down, add='')
        self.canvas_map.bind("<B1-Motion>", self._map_button1_drag, add='')
        self.canvas_map.bind("<ButtonRelease-1>", self._map_button1_up, add='')

    # ------------------------------------------------------------------------------------------------------------------

    def _load_dungeon(self, bank: int, address: int, compression: str = "") -> None:
        """
        Loads and displays a dungeon map from ROM

        Parameters
        ----------
        bank: int
            Number of the ROM bank where this map's data resides
        address: int
            Address in ROM of map data
        compression: str
            Can be "none", "LZSS" or "RLE". If not specified, use the default compression for that bank
        """
        # Clear map
        self.map.clear()

        # Set default tool
        self.select_tool("draw")

        # Show level 1 by default after loading
        self.dungeon_level = 0

        # Resize canvas to show one dungeon level at once (16 x 16 x 16 = 256 x 256)
        self.app.setCanvasWidth("ME_Canvas_Map", 256)
        self.app.setCanvasHeight("ME_Canvas_Map", 256)

        # If the address is out of range, create an empty dungeon
        if 0x8000 > address or address > 0xBFFF:
            data = bytearray()
            for _ in range(2048):
                data.append(0x0D)
        else:
            data = self.rom.read_bytes(bank, address, 2048)

        if compression == "" and (0 <= bank <= 0xF):
            compression = self.bank_compression[bank]

        if compression == "none" or 0x8000 > address or address > 0xBFFF:
            self.map = data
            self.show_map()

        elif compression == "RLE":

            self.info(f"Opening dungeon map @{bank:X}:{address:04X} (RLE compressed)...")
            uncompressed = rle.decode(data)
            for i in range(2048):
                value = uncompressed[i]
                self.map.append(value)

            self.show_map()

        elif compression == "LZSS":

            self.info(f"Opening dungeon map @{bank:X}:{address:04X} (LZSS compressed)...")
            uncompressed = lzss.decode(data)
            for i in range(2048):
                value = uncompressed[i]
                self.map.append(value)

            self.show_map()

        else:

            log(3, f"{self.__class__.__name__}",
                f"Unsupported compression type: '{compression}' for map @{bank:X}:{address:04X}!")

            for _ in range(2048):
                self.map.append(0xD)

            self.show_map()

    # ------------------------------------------------------------------------------------------------------------------

    def _load_map(self, bank: int, address: int, compression: str) -> None:
        """
        Loads and displays a (non dungeon) map from ROM

        Parameters
        ----------
        bank: int
            Number of the ROM bank where this map's data resides
        address: int
            Address in ROM of the map data
        compression: str
            Can be "none", "LZSS" or "RLE"
        """
        # Clear map
        self.map.clear()

        # Set default tool
        self.select_tool("draw")

        # Resize canvas (64 x 64 x 16 = 1024 x 1024)
        self.app.setCanvasWidth("ME_Canvas_Map", 1024)
        self.app.setCanvasHeight("ME_Canvas_Map", 1024)

        # If the bank or address is out of range, we create an empty map
        if bank > 0xE or 0x8000 > address or address > 0xBFFF:
            self.info(f"Creating new empty map...")
            for _ in range(64 * 64):
                self.map.append(0)

        elif compression == "none":
            # self.info(f"Opening map @{bank:X}:{address:04X} (uncompressed)...")
            for y in range(64):
                for x in range(32):
                    # Each byte represents two tiles
                    value = self.rom.read_byte(bank, address)
                    address = address + 1
                    # Separate and store the two values
                    self.map.append(value >> 4)
                    self.map.append(value & 0x0F)
            self.show_map()

        elif compression == "RLE":
            # self.info(f"Opening map @{bank:X}:{address:04X} (RLE compressed)...")
            data = self.rom.read_bytes(bank, address, 2048)
            uncompressed = rle.decode(data)
            offset = 0
            for y in range(64):
                for x in range(32):
                    # Each byte represents two tiles
                    value = uncompressed[offset]
                    offset = offset + 1
                    # Separate and store the two values
                    self.map.append(value >> 4)
                    self.map.append(value & 0x0F)
            self.show_map()

        elif compression == "LZSS":

            # self.info(f"Opening map @{bank:X}:{address:04X} (LZSS compressed)...")
            data = self.rom.read_bytes(bank, address, 2048)
            uncompressed = lzss.decode(data)
            offset = 0
            for y in range(64):
                for x in range(32):
                    # Each byte represents two tiles
                    value = uncompressed[offset]
                    offset = offset + 1
                    # Separate and store the two values
                    self.map.append(value >> 4)
                    self.map.append(value & 0x0F)
            self.show_map()

        else:

            log(3, f"{self.__class__.__name__}",
                f"Unimplemented compression method '{compression}' for non-dungeon map.")

    # ------------------------------------------------------------------------------------------------------------------

    def import_map(self, file_name: str) -> bool:
        """
        Imports map data from a binary file

        Parameters
        ----------
        file_name: str
            Full path of the file to open. Compression type will be chosen depending on file extension.

        Returns
        -------
        bool
            True if import was successful, False otherwise
        """
        file = None

        # Determine compression type depending on file name
        try:
            position = file_name.index('.')
            extension = file_name[position:]
        except ValueError:
            extension = ".bin"

        if extension.lower() == ".lzss":
            compression = "LZSS"

        elif extension.lower() == ".rle":
            compression = "RLE"

        else:
            compression = "none"

        try:
            file = open(file_name, "rb")

            buffer = file.read()

            if compression == "LZSS":
                unpacked = lzss.decode(buffer)
            elif compression == "RLE":
                unpacked = rle.decode(bytearray(buffer))
            else:
                unpacked = bytearray(buffer)

            new_map = bytearray()

            try:
                if self.is_dungeon():
                    fountains = 0
                    marks = 0
                    dungeon_id = self.get_map_id()

                    # Copy map data as it is
                    for i in range(64 * 32):
                        # Count fountains and marks
                        if unpacked[i] == 6:
                            marks = marks + 1
                        elif unpacked[i] == 7:
                            fountains = fountains + 1

                        new_map.append(int(unpacked[i]))

                    # Update fountains/marks count
                    difference = marks - len(self.dungeon_data[dungeon_id].mark_ids)

                    if difference > 0:
                        # There are  more marks than before: expand list
                        for _ in range(difference):
                            self.dungeon_data[dungeon_id].mark_ids.append(0)

                    elif difference < 0:
                        # There are less marks than before: shrink list
                        self.dungeon_data[dungeon_id].mark_ids = self.dungeon_data[dungeon_id].mark_ids[0:difference]

                    # Same thing with fountains
                    difference = fountains - len(self.dungeon_data[dungeon_id].fountain_ids)

                    if difference > 0:
                        # More fountains than before: expand list
                        for _ in range(difference):
                            self.dungeon_data[dungeon_id].fountain_ids.append(0)

                    elif difference < 0:
                        # Less fountains than before: shrink list
                        self.dungeon_data[dungeon_id].fountain_ids = \
                            self.dungeon_data[dungeon_id].fountain_ids[0:difference]

                else:
                    # Non-dungeon maps use 4-bit packing
                    for t in unpacked:
                        new_map.append(t >> 4)
                        new_map.append(t & 0x0F)

            except IndexError as error:
                self.error(f"Bad map data in file '{file_name}': {error}.")
                file.close()
                return False

            # Done
            file.close()

            # Clear map
            self.map.clear()
            self.map = new_map

            self.show_map()

            if self.is_dungeon():
                # Refresh marks and fountains count if dungeon
                self.show_marks_count()
                self.show_fountains_count()

            else:
                # Show NPCs and entrances if not a dungeon
                self.load_npc_data()
                self.load_entrances()
                self.load_moongates()

            return True

        except OSError as error:
            self.error(f"System error importing '{file_name}': {error}.")

            if file is not None:
                file.close()

            return False

    # ------------------------------------------------------------------------------------------------------------------

    def export_map(self, file_name: str) -> bool:
        """
        Exports map data to a binary file

        Parameters
        ----------
        file_name: str
            A string containing the desired file name. The extension will determine the export format.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        # Pack map data first using 4-bit packing (this is the format used internally by the game)
        packed_data = bytearray()

        # Only use 4-bit packing for non-dungeon maps
        if self.is_dungeon() is False:
            for i in range(0, 64 * 64, 2):
                left = self.map[i]
                right = self.map[i + 1]
                packed_data.append((left << 4) | right)

        else:
            packed_data = bytearray(self.map)

        # Decide format depending on file extension
        try:
            position = file_name.index('.')
            extension = file_name[position:]
        except ValueError:
            extension = ".bin"

        if extension.lower() == ".lzss":
            packed_data = lzss.encode(packed_data)

        elif extension.lower() == ".rle":
            packed_data = rle.encode(packed_data)

        file = open(file_name, "wb")
        if file is not None:
            file.write(packed_data)
            file.close()
            return True
        else:
            return False

    # ------------------------------------------------------------------------------------------------------------------

    def jump_to(self, x: int, y: int) -> None:
        """
        Scrolls the view to show the tile at the given coordinates

        Parameters
        ----------
        x: int
            Horizontal coordinates of the tile to jump to
        y: int
            Vertical coordinates of the tile to jump to
        """
        if self.is_dungeon():
            return

        # self.info(f"Jump to {x}, {y}.")

        pane = self.app.getScrollPaneWidget("ME_Scroll_Pane")
        delta_x = (x - 12)
        delta_y = (y - 8)
        offset_x = +1 if delta_x > 0 else 0
        offset_y = +1 if delta_y > 0 else 0
        pane.canvas.xview_moveto(float(delta_x + offset_x) / 64)
        pane.canvas.yview_moveto(float(delta_y + offset_y) / 64)

    # ------------------------------------------------------------------------------------------------------------------

    def show_map(self) -> None:
        """
        Use cached tiles to display the currently loaded map
        """

        # self.info("Drawing map on canvas...")
        self.app.clearCanvas("ME_Canvas_Map")
        self.canvas_map_images.clear()

        self.canvas_icon_dawn = -1
        self.canvas_icon_entrances.clear()
        self.canvas_icon_start = -1
        self.canvas_icon_moongates.clear()

        if self.is_dungeon():
            # Get offset of map data for the current level
            level_offset = self.dungeon_level << 8
            dungeon_index = self.get_map_id()

            for y in range(16):
                for x in range(16):
                    # Calculate offset of this tile for this level
                    offset = level_offset + x + (y << 4)
                    tile_id = self.map[offset]
                    tile_image = self.tiles[tile_id]

                    # Calculate drawing position on canvas
                    canvas_x = (x << 4) + 8
                    canvas_y = (y << 4) + 8

                    # "Paste" cached tile image on canvas
                    pasted_image = self.app.addCanvasImage("ME_Canvas_Map", canvas_x, canvas_y, tile_image)
                    self.canvas_map_images.append(pasted_image)

            # If this is a new map, it will have no messages
            missing_messages = 8 - len(self.dungeon_data[dungeon_index].messages)
            if missing_messages > 0:
                for m in range(0, missing_messages):
                    self.dungeon_data[dungeon_index].messages.append("")

            # Also show message sign for the current level
            text = self.dungeon_data[dungeon_index].messages[self.dungeon_level]
            self.app.clearTextArea("ME_Text_Dungeon_Message", callFunction=False)
            self.app.setTextArea("ME_Text_Dungeon_Message", text, callFunction=False)
            self.app.setOptionBox("ME_Option_Dungeon_Level", index=self.dungeon_level, callFunction=False)
            # ...and other dungeon info
            self.show_marks_count()
            self.show_fountains_count()

        else:
            # Show progress
            self.app.setLabel("Progress_Label", "Loading map, please wait...")
            self.app.showSubWindow("Map_Progress")
            root = self.canvas_map.winfo_toplevel()
            root.update()
            progress = 0.0
            self.app.setMeter("ME_Progress_Meter", value=progress)

            index = 0
            for y in range(64):
                progress = progress + 1.55
                for x in range(64):
                    # Each value should be between 0 and 0x0F
                    tile_id = self.map[index]
                    tile_image = self.tiles[tile_id]
                    # Calculate the centre coordinates of this tile in the canvas
                    canvas_x = (x << 4) + 8
                    canvas_y = (y << 4) + 8
                    # "Paste" the cached tile on the canvas
                    pasted_image = self.app.addCanvasImage("ME_Canvas_Map", canvas_x, canvas_y, tile_image)
                    self.canvas_map_images.append(pasted_image)
                    # Move to the next tile
                    index = index + 1
                self.app.setMeter("ME_Progress_Meter", value=progress)
                root.update()

            # Hide progress window
            self.app.hideSubWindow("Map_Progress", useStopFunction=False)
            self.app.showSubWindow("Entrance_Editor")
            self.app.showSubWindow("NPC_Editor")
            self.app.showSubWindow("Map_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def _set_party_entry(self, x: int, y: int, facing: int = 0) -> None:
        """
        Sets/changes the coordinates at which the party will be placed when entering this map from a continent

        Parameters
        ----------
        x: int
            Horizontal coordinate in map or in dungeon level 1
        y: int
            Vertical coordinate in map or in dungeon level 1
        facing: int
            Facing direction (0 to 3) when entering dungeon (optional, ignored if map is not a dungeon)
        """
        self.map_table[self.map_index].entry_x = x
        self.map_table[self.map_index].entry_y = y

        if self.is_dungeon():
            self.map_table[self.map_index].npc_pointer = facing

    # ------------------------------------------------------------------------------------------------------------------

    def flood_fill(self, x: int, y: int) -> None:
        """
        Exactly what you would expect.

        Parameters
        ----------
        x: int
            Starting point of the fill, X coordinate
        y: int
            Starting point of the fill, Y coordinate
        """
        old_tile_id = self.get_tile_id(x, y)

        if old_tile_id == self.selected_tile_id:
            # Nothing to do
            return

        if self.is_dungeon() is False:
            self._map_flood_fill(x, y, self.selected_tile_id, old_tile_id)
            self._redo_actions = []
            self._undo_actions.append(self._modified_tiles)
            self._modified_tiles = 0
            self._update_undo_buttons()

        else:
            # Don't fill dungeons with special tiles, to avoid problems with pointers
            if self.selected_tile_id != 0 and self.selected_tile_id != 0xD and self.selected_tile_id != 0xF:
                self.info(f"Cannot fill dungeon with tile #${self.selected_tile_id:X}.")
                self.app.soundError()
                return

            # If the old ID is a special tile, behave like the "draw" tool
            if old_tile_id != 0 and old_tile_id != 0xD and old_tile_id != 0xF:
                # self._change_tile(x, y, self.selected_tile_id)
                self._undo_redo(self._change_tile, (x, y, self.selected_tile_id),
                                (x, y, old_tile_id), text="Draw")
                self._redo_actions = []
                self._undo_actions.append(1)
                self._modified_tiles = 0
                self._update_undo_buttons()
            else:
                self._dungeon_flood_fill(x, y, self.selected_tile_id, old_tile_id)
                self._redo_actions = []
                self._undo_actions.append(self._modified_tiles)
                self._modified_tiles = 0
                self._update_undo_buttons()

    # ------------------------------------------------------------------------------------------------------------------

    def _map_flood_fill(self, x: int, y: int, new_tile_id: int, old_tile_id: int) -> None:
        """
        Does what it says on the tin.

        Parameters
        ----------
        x: int
            Starting point of the fill, X coordinate
        y: int
            Starting point of the fill, Y coordinate
        new_tile_id: int
            The ID of the tile that will fill the area
        old_tile_id: int
            ID of the tile(s) that will be replaced
        """
        self.app.setCanvasCursor("ME_Canvas_Map", "watch")

        queue = list()

        # self._change_tile(x, y, new_tile_id)
        self._undo_redo(self._change_tile, (x, y, new_tile_id), (x, y, old_tile_id), text="Flood fill")
        self._modified_tiles += 1

        queue.append((x, y))

        while len(queue) > 0:
            # root.update()

            node = queue.pop()

            node_x = node[0] - 1
            node_y = node[1]
            if node_x >= 0 and self.get_tile_id(node_x, node_y) == old_tile_id:
                # self._change_tile(node_x, node_y, new_tile_id)
                self._undo_redo(self._change_tile, (node_x, node_y, new_tile_id),
                                (node_x, node_y, old_tile_id), text="Flood fill")
                self._modified_tiles += 1
                queue.append((node_x, node_y))

            node_x = node[0] + 1
            node_y = node[1]
            if node_x <= 63 and self.get_tile_id(node_x, node_y) == old_tile_id:
                # self._change_tile(node_x, node_y, new_tile_id)
                self._undo_redo(self._change_tile, (node_x, node_y, new_tile_id),
                                (node_x, node_y, old_tile_id), text="Flood fill")
                self._modified_tiles += 1
                queue.append((node_x, node_y))

            node_x = node[0]
            node_y = node[1] - 1
            if node_y >= 0 and self.get_tile_id(node_x, node_y) == old_tile_id:
                # self._change_tile(node_x, node_y, new_tile_id)
                self._undo_redo(self._change_tile, (node_x, node_y, new_tile_id),
                                (node_x, node_y, old_tile_id), text="Flood fill")
                self._modified_tiles += 1
                queue.append((node_x, node_y))

            node_x = node[0]
            node_y = node[1] + 1
            if node_y <= 63 and self.get_tile_id(node_x, node_y) == old_tile_id:
                # self._change_tile(node_x, node_y, new_tile_id)
                self._undo_redo(self._change_tile, (node_x, node_y, new_tile_id),
                                (node_x, node_y, old_tile_id), text="Flood fill")
                self._modified_tiles += 1
                queue.append((node_x, node_y))

    # ------------------------------------------------------------------------------------------------------------------

    def _dungeon_flood_fill(self, x: int, y: int, new_tile_id: int, old_tile_id: int) -> None:
        """
        Specialised version of the Flood Fill, for dungeon maps.

        Parameters
        ----------
        x: int
            Starting point of the fill, X coordinate
        y: int
            Starting point of the fill, Y coordinate
        new_tile_id: int
            ID of the tile that will fill the area. Should only be a wall or flood.
        old_tile_id: int
            ID of the tile(s) that will be replaced. Should only be a wall or floor.
        """
        self.app.setCanvasCursor("ME_Canvas_Map", "watch")

        queue = list()

        # self._change_tile(x, y, new_tile_id)
        self._undo_redo(self._change_tile, (x, y, new_tile_id), (x, y, old_tile_id), text="Flood fill")
        self._modified_tiles += 1

        queue.append((x, y))

        while len(queue) > 0:
            node = queue.pop()

            node_x = node[0] - 1
            node_y = node[1]
            if node_x >= 0 and self.get_tile_id(node_x, node_y) == old_tile_id:
                # self._change_tile(node_x, node_y, new_tile_id)
                self._undo_redo(self._change_tile, (node_x, node_y, new_tile_id),
                                (node_x, node_y, old_tile_id), text="Flood fill")
                self._modified_tiles += 1
                queue.append((node_x, node_y))

            node_x = node[0] + 1
            node_y = node[1]
            if node_x <= 15 and self.get_tile_id(node_x, node_y) == old_tile_id:
                # self._change_tile(node_x, node_y, new_tile_id)
                self._undo_redo(self._change_tile, (node_x, node_y, new_tile_id),
                                (node_x, node_y, old_tile_id), text="Flood fill")
                self._modified_tiles += 1
                queue.append((node_x, node_y))

            node_x = node[0]
            node_y = node[1] - 1
            if node_y >= 0 and self.get_tile_id(node_x, node_y) == old_tile_id:
                # self._change_tile(node_x, node_y, new_tile_id)
                self._undo_redo(self._change_tile, (node_x, node_y, new_tile_id),
                                (node_x, node_y, old_tile_id), text="Flood fill")
                self._modified_tiles += 1
                queue.append((node_x, node_y))

            node_x = node[0]
            node_y = node[1] + 1
            if node_y <= 15 and self.get_tile_id(node_x, node_y) == old_tile_id:
                # self._change_tile(node_x, node_y, new_tile_id)
                self._undo_redo(self._change_tile, (node_x, node_y, new_tile_id),
                                (node_x, node_y, old_tile_id), text="Flood fill")
                self._modified_tiles += 1
                queue.append((node_x, node_y))

    # ------------------------------------------------------------------------------------------------------------------

    def _change_tile(self, x: int, y: int, tile_id: int, show_info: bool = True) -> None:
        """
        Changes the tile at the specified coordinates to the a new ID

        Parameters
        ----------
        x: int
            Horizontal coordinate of tile to change
        y: int
            Vertical coordinate of tile to change
        tile_id: int
            New ID to assign to this tile (0x0 to 0xF)
        show_info: bool
            If True, update the info widgets with this tile's data
        """
        # If drawing a special tile, show special tile info
        if self.is_dungeon():
            map_index = x + (16 * y) + (self.dungeon_level << 8)
            canvas_index = x + (16 * y)

            dungeon_id = self.get_map_id()

            # If replacing a fountain with something else, remove it from the fountains list
            if self.map[map_index] == 7 and tile_id != 7:
                # Get the index of the old fountain
                fountain_index = self.get_fountain_index(x, y)
                # Remove it from the list
                self.dungeon_data[dungeon_id].fountain_ids.pop(fountain_index)

            # If replacing a mark with something else, remove it from the marks list
            elif self.map[map_index] == 6 and tile_id != 6:
                # Get the index of the mark being removed
                mark_index = self.get_mark_index(x, y)
                # Remove it from the list
                self.dungeon_data[dungeon_id].mark_ids.pop(mark_index)

            if 3 <= tile_id <= 5:  # Placing a ladder
                # If the "Auto-Ladder" option is enabled, create the corresponding ladder(s)
                if self.app.getCheckBox("ME_Auto_Ladders"):
                    if tile_id == 3 or tile_id == 5:
                        # Ladder up: create ladder down in level above, if not already at top level
                        if self.dungeon_level > 0:
                            # Make sure there is room for a ladder on the other side
                            old_tile = self.map[map_index - 256]
                            if old_tile == 6 or old_tile == 7:
                                self.app.warningBox("Auto-Ladder", f"Could not automatically place a ladder:\n"
                                                                   f"the space corresponding to this ladder in the "
                                                                   f"floor above is occupied by either a Mark or a "
                                                                   f"Fountain.\nCoordinates: {x}, {y}.")
                            elif 3 <= old_tile <= 5:
                                self.info(f"Auto-Ladder: ladder already present in level "
                                          f"{self.dungeon_level - 1} ({x}, {y}).")

                            else:
                                self.map[map_index - 256] = 4
                        else:
                            # Automatically set entry point if creating a ladder up from level 0
                            # TODO For v1.09+, try to guess facing direction by looking for walls around the ladder
                            self._set_party_entry(x, y, 0)

                    if tile_id == 4 or tile_id == 5:
                        # Ladder down: create ladder up in level below
                        if self.app.getCheckBox("ME_Auto_Ladders"):
                            if self.dungeon_level > 6:
                                self.app.warningBox("Auto-Ladder", "Can't place a ladder going down: "
                                                                   "this is the lowest level of the dungeon!")
                                return

                            # Make sure there is room for a ladder in the corresponding tile below
                            old_tile = self.map[map_index + 256]
                            if old_tile == 6 or old_tile == 7:
                                self.app.warningBox("Auto-Ladder", f"Could not automatically place a ladder:\n"
                                                                   f"the space corresponding to this ladder in the "
                                                                   f"floor below is occupied by either a Mark or a "
                                                                   f"Fountain.\nCoordinates: {x}, {y}.")
                            elif 3 <= old_tile <= 5:
                                self.info(f"Auto-Ladder: ladder already present in level "
                                          f"{self.dungeon_level + 1} ({x}, {y}).")
                            else:
                                self.map[map_index + 256] = 3

                # Hide special tile info
                self.app.hideFrame("ME_Frame_Special_Tile")

            elif tile_id == 0x07:  # Placing a new Fountain tile
                # Check how many fountains were before this one
                fountain_index = self.get_fountain_index(x, y)

                if fountain_index >= 148:
                    self.app.warningBox("Edit Map", "You have reached the maximum number of Fountain tiles!",
                                        parent="Map_Editor")
                    return

                # If a fountain was already there, just show the fountain ID and allow to change it
                if self.map[map_index] == 7:
                    if fountain_index < 0:
                        self.warning("Wrong fountain count for this map!")
                        fountain_id = 0
                    else:
                        fountain_id = self.dungeon_data[dungeon_id].fountain_ids[fountain_index]
                        # self.info(f"Found fountain type {fountain_id} at {x}, {y}.")

                # If this is a new fountain, insert it in the list after the previous one
                else:
                    fountain_id = 0
                    self.dungeon_data[dungeon_id].fountain_ids.insert(fountain_index, fountain_id)
                    # self.info(f"Inserting new fountain, index {fountain_index} at {x}, {y}.")

                # Update the label with the fountains count
                self.show_fountains_count()

                if show_info:
                    # Populate special tile info with fountain IDs
                    self.show_fountain_info(fountain_id)
                    # Show the special tile info frame
                    self.app.showFrame("ME_Frame_Special_Tile")

            elif tile_id == 0x06:  # Placing a new Mark tile
                # Check how many marks were before this one
                mark_index = self.get_mark_index(x, y)

                if mark_index >= 31:
                    self.app.warningBox("Edit Map", "You have reached the maximum number of Mark ties!",
                                        parent="Map_Editor")

                # If a Mark was already there, show the Mark ID and allow to change it
                if self.map[map_index] == 6:
                    if mark_index < 0:
                        self.warning("Wrong Mark count for this map!")
                        mark_id = 0
                    else:
                        mark_id = self.dungeon_data[dungeon_id].mark_ids[mark_index]
                        # self.info(f"Found Mark type {mark_id} at {x}, {y}.")

                # If this is a new Mark, insert it in the list after the previous one
                else:
                    mark_id = 0
                    self.dungeon_data[dungeon_id].mark_ids.insert(mark_index, mark_id)
                    # self.info(f"Inserting new Mark, index {mark_index} at {x}, {y}.")

                # Update label with mark count
                self.show_marks_count()

                if show_info:
                    # Populate special tile info with mark IDs
                    self.show_mark_info(mark_id)
                    # Show special tile info frame
                    self.app.showFrame("ME_Frame_Special_Tile")

        # Otherwise, simply hide special tile info frame
        else:
            map_index = x + (y << 6)
            canvas_index = map_index

            # self.app.hideFrame("ME_Frame_Special_Tile")

        # self.info(f"Editing cached image #{self.canvas_images[index]}.")
        # Update cached map data
        self.map[map_index] = tile_id
        # Update canvas image
        self.canvas_map.itemconfig(self.canvas_map_images[canvas_index], image=self.tiles[tile_id])

    # ------------------------------------------------------------------------------------------------------------------

    def _update_undo_buttons(self) -> None:
        if len(self._undo_actions) < 1:
            self.app.disableButton("ME_Button_Undo")
            self.app.setButtonTooltip("ME_Button_Undo", "Nothing to Undo")
        else:
            self.app.enableButton("ME_Button_Undo")
            self.app.setButtonTooltip("ME_Button_Undo", "Undo: " + self._undo_redo.get_undo_text())

        if len(self._redo_actions) < 1:
            self.app.disableButton("ME_Button_Redo")
            self.app.setButtonTooltip("ME_Button_Redo", "Nothing to Redo")
        else:
            self.app.enableButton("ME_Button_Redo")
            self.app.setButtonTooltip("ME_Button_Undo", "Undo: " + self._undo_redo.get_redo_text())

    # ------------------------------------------------------------------------------------------------------------------

    def redraw_map(self) -> None:
        """
        Exactly what you would expect.
        """
        first = 0
        last = 64 * 64
        canvas_index = 0

        if self.is_dungeon():
            # Each dungeon level is 256 bytes long
            first = 256 * self.dungeon_level
            last = first + 256

        for i in range(first, last):
            tile_id = self.map[i]
            self.canvas_map.itemconfig(self.canvas_map_images[canvas_index], image=self.tiles[tile_id])
            canvas_index = canvas_index + 1

    # ------------------------------------------------------------------------------------------------------------------

    def tile_info(self, tile_id: int, x: int = -1, y: int = -1) -> None:
        """
        Displays information about the selected tile for a non-dungeon map

        Parameters
        ----------
        tile_id: int
            ID of the tile
        x: int
            X coordinate in the current dungeon floor (optional)
        y: int
            Y coordinate in the current dungeon floor (optional)
        """

        if self.is_dungeon():
            self._dungeon_tile_info(tile_id, x, y)
            return

        # TODO Use substitution tables instead of hard-coding everything
        if tile_id == 0x0:
            name = "Grass 0"
            info = "Normal"

        elif tile_id == 0x1:
            name = "Brush"
            info = "Moderate Slowdown"

        elif tile_id == 0x2:
            name = "Trees"
            info = "Heavy Slowdown, Blocks View"

        elif tile_id == 0x3:
            name = "Water"
            info = "Water"

        elif tile_id == 0x4:
            if self.map_index == 0x06 or self.map_index > 0x14:
                name = "Ankh"
            else:
                name = "Mountains"
            info = "Impassible, Blocks View"

        elif tile_id == 0x5:
            if self.map_index == 0x00:
                name = "Door (Unused)"
            else:
                name = "Door"
            info = "Impassible, Blocks View"

        elif tile_id == 0x06:
            if self.map_index == 0x00 or self.map_index == 0x0F:
                name = "Grass 2"
            else:
                name = "Floor 0"
            info = "Normal"

        elif tile_id == 0x07:
            name = "Lava"
            info = "Deadly"

        elif tile_id == 0x08:
            if self.map_index == 0x00:
                name = "Serpent 0"
            else:
                name = "Wall"
            info = "Impassible, Blocks View"

        elif tile_id == 0x09:
            if self.map_index == 0x00 or self.map_index == 0x0F:
                name = "Rocks"
            else:
                name = "Table"
            info = "Impassible, Counter"

        elif tile_id == 0xA:
            name = "Chest"
            info = "Normal"

        elif tile_id == 0xB:
            if self.map_index == 0x00 or self.map_index == 0x0F:
                name = "Grass 1"
            else:
                name = "Floor 1"
            info = "Normal"

        elif tile_id == 0xC:
            if self.map_index == 0x00:
                name = "Serpent 1"
            else:
                name = "Wall Top"
            info = "Impassible, Blocks View"

        elif tile_id == 0xD:
            info = "Entrance"
            if self.map_index == 0x14:
                name = "Exodus"
            elif self.map_index == 0x0F:
                name = "Flower"
                info = "Special"
            else:
                name = "Castle"

        elif tile_id == 0xE:
            if self.map_index == 0x06 or self.map_index >= 0x14:
                name = "Force Field"
                info = "Deadly"
            elif self.map_index == 0x0F:
                name = "Shrine"
                info = "Entrance"
            else:
                name = "Dungeon"
                info = "Entrance"

        elif tile_id == 0xF:
            if self.map_index == 0x00 or self.map_index == 0x0F:
                name = "Town"
                info = "Entrance"
            else:
                name = "Grass 1"
                info = "Normal"

        else:
            name = "Unknown"
            info = "No Info"

        self.app.setLabel("ME_Selected_Tile_Name", name)
        self.app.clearCanvas("ME_Canvas_Selected_Tile")
        self.app.addCanvasImage("ME_Canvas_Selected_Tile", 8, 8, self.tiles[tile_id])
        self.app.setLabel("ME_Selected_Tile_Properties", f"({info})")

    # ------------------------------------------------------------------------------------------------------------------

    def _dungeon_tile_info(self, tile_id, x: int = -1, y: int = -1):
        names = [
            "Wall", "Door", "Hidden Door", "Stairs Up", "Stairs Down", "Stairs Up & Down", "Mark", "Fountain",
            "Message Sign", "Wind", "Gremlins", "Treasure Chest", "Trap", "Regular Floor", "Time Lord", "Safe Floor"
        ]
        info = ["Impassable", "Normal", "Looks like a wall", "Can 'Climb'", "Can 'Climb'", "Can 'Climb'", "Special",
                "Special", "Special", "Causes Darkness", "Steal Food", "Can 'Get'", "Trap", "Normal", "Special",
                "No Encounters"]

        try:
            self.app.setLabel("ME_Selected_Tile_Name", names[tile_id])
            self.app.clearCanvas("ME_Canvas_Selected_Tile")
            self.app.addCanvasImage("ME_Canvas_Selected_Tile", 8, 8, self.tiles[tile_id])
            self.app.setLabel("ME_Selected_Tile_Properties", f"({info[tile_id]})")
        except IndexError as error:
            self.error(f"_dungeon_tile_info: {error}.")

        # If coordinates are specified, show additional info
        if x > 0 and y > 0:
            # Transform X, Y, Level info map data offset
            # (Not needed, use the tile_id parameter instead)
            # offset = x + (y * 16) + (self.dungeon_level * 256)
            # tile_id = self.map[offset]

            # Get dungeon ID
            dungeon_id = self.get_map_id()

            # Fountain tile info
            if tile_id == 7:
                # Get fountain index
                special_index = self.get_fountain_index(x, y)
                special_type = self.dungeon_data[dungeon_id].fountain_ids[special_index]
                self.show_fountain_info(special_type)

            # Mark tile info
            elif tile_id == 6:
                # Get mark index
                special_index = self.get_mark_index(x, y)
                special_type = self.dungeon_data[dungeon_id].mark_ids[special_index]
                self.show_mark_info(special_type)

            # If not a fountain or mark, hide special tile info
            else:
                self.app.hideFrame("ME_Frame_Special_Tile")

    # ------------------------------------------------------------------------------------------------------------------

    def set_npc_dialogue(self, dialogue_id: int, npc_index: int = -1) -> None:
        """
        Sets the dialogue/function ID of an NPC

        Parameters
        ----------
        dialogue_id: int
            Index of the dialogue or function to call when the player uses the TALK command with this NPC
        npc_index: int
            Index of the NPC being modified; if not provided use the currently selected NPC
        """
        if npc_index < 0:
            npc_index = self.npc_index

        self.npc_data[npc_index].dialogue_id = dialogue_id

    # ------------------------------------------------------------------------------------------------------------------

    def select_npc_graphics(self, selection: int) -> None:
        """
        A new NPC graphics index has been selected

        Parameters
        ----------
        selection: int
            Index of the new sprite, including the "static" flag (bit 7)
        """
        self.selected_npc_graphics = selection
        self.app.clearCanvas("NPCE_Canvas_New_Sprite")
        self.app.addCanvasImage("NPCE_Canvas_New_Sprite", 8, 8, self.npc_sprites[selection & 0x7F])

        # Update canvas image
        self.canvas_map.itemconfig(self.canvas_npc_images[self.npc_index], image=self.npc_sprites[selection & 0x7F])

        # Update data table
        self.npc_data[self.npc_index].sprite_id = selection

        # Update Option Box item
        npc = self.npc_data[self.npc_index]
        new_text = f"{self.npc_index:02d}: G[0x{npc.sprite_id:02X}] D[0x{npc.dialogue_id:02X}] ({npc.starting_x}," \
                   f" {npc.starting_y})"
        box = self.app.getOptionBoxWidget("NPCE_Option_NPC_List")
        box.options[self.npc_index] = new_text

    # ------------------------------------------------------------------------------------------------------------------

    def change_npc_palettes(self, palette_top: int, palette_bottom: int = 0, **kwargs) -> None:
        """
        Changes the palette indices for an NPC sprite

        Optional Parameters:\n
        - sprite_id: int (if not specified, use the sprite ID of the currently selected NPC)
        """
        # Get the index of the sprite that is going to be modified
        sprite_id = kwargs.get("sprite_id", self.npc_data[self.npc_index].sprite_id) & 0x7F
        # Set the new value(s)
        if self.rom.has_feature("2-colour sprites"):
            self.npc_palette_indices[sprite_id] = (palette_top << 2) | (palette_bottom & 0x3)
        else:
            # Only use the top value in the vanilla game
            self.npc_palette_indices[sprite_id] = palette_top

        # Reload this sprite using the new colours
        sprite = Image.new('RGBA', (16, 16), 0xC0C0C000)
        address = 0x8000 + (sprite_id * 16 * 4 * 8)  # eight meta-sprites, each containing four 16-byte patterns

        # TODO Use single colour for vanilla game

        # Get the top and bottom palettes for this sprite
        top_colours = []
        bottom_colours = []

        # Top palette index
        palette_index = (palette_top >> 2) * 4
        # print(f"Top palette: {palette_index}")

        for c in range(palette_index, palette_index + 4):
            try:
                colour_index = self.palette_editor.palettes[1][c]
            except IndexError:
                self.error(f"Index out of range for palette[1]: {c}")
                colour_index = 0
            rgb = bytearray(self.palette_editor.get_colour(colour_index))
            top_colours.append(rgb[0])
            top_colours.append(rgb[1])
            top_colours.append(rgb[2])

        # Bottom palette index
        palette_index = (palette_bottom & 0x03) * 4
        # print(f"Bottom palette: {palette_index}")

        for c in range(palette_index, palette_index + 4):
            try:
                colour_index = self.palette_editor.palettes[1][c]
            except IndexError:
                self.error(f"Index out of range for palette[1]: {c}")
                colour_index = 0
            rgb = bytearray(self.palette_editor.get_colour(colour_index))
            bottom_colours.append(rgb[0])  # Red
            bottom_colours.append(rgb[1])  # Green
            bottom_colours.append(rgb[2])  # Blue

        # Top-Left pattern
        pixels = bytes(bytearray(self.rom.read_pattern(3, address)))
        image = Image.frombytes('P', (8, 8), pixels)
        image.info['transparency'] = 0
        image.putpalette(top_colours)
        sprite.paste(image.convert('RGBA'), (0, 0))
        # Bottom-Left pattern
        pixels = bytes(bytearray(self.rom.read_pattern(3, address + 0x10)))
        image = Image.frombytes('P', (8, 8), pixels)
        image.info['transparency'] = 0
        image.putpalette(bottom_colours)
        sprite.paste(image.convert('RGBA'), (0, 8))
        # Top-Right pattern
        pixels = bytes(bytearray(self.rom.read_pattern(3, address + 0x20)))
        image = Image.frombytes('P', (8, 8), pixels)
        image.info['transparency'] = 0
        image.putpalette(top_colours)
        sprite.paste(image.convert('RGBA'), (8, 0))
        # Bottom-Right pattern
        pixels = bytes(bytearray(self.rom.read_pattern(3, address + 0x30)))
        image = Image.frombytes('P', (8, 8), pixels)
        image.info['transparency'] = 0
        image.putpalette(bottom_colours)
        sprite.paste(image.convert('RGBA'), (8, 8))

        photo_image = ImageTk.PhotoImage(sprite)
        self.npc_sprites[sprite_id] = photo_image

        # Update the canvas widget with the new sprite
        self.app.clearCanvas("NPCE_Canvas_New_Sprite")
        self.app.addCanvasImage("NPCE_Canvas_New_Sprite", 8, 8, photo_image)

    # ------------------------------------------------------------------------------------------------------------------

    def find_npc(self, npc_x: int, npc_y: int) -> int:
        """
        Finds the NPC at the given map coordinates

        Parameters
        ----------
        npc_x: int
            X coordinate
        npc_y: int
            Y coordinate

        Returns
        -------
        int
            Index of the NPC at these coordinates (from this map's NPC data table), or -1 if none
        """
        for i in range(0, len(self.npc_data)):
            entry = self.npc_data[i]
            if entry.starting_x == npc_x and entry.starting_y == npc_y:
                return i

        return -1  # Not found

    # ------------------------------------------------------------------------------------------------------------------

    def _create_npc(self) -> (NPCData, int):
        """
        Creates a new NPC and adds it to the map

        Returns
        -------
        (NPCData, int)
            A tuple (NPCData, int) containing the instance of the newly created NPC and its index in the npc_data table
        """
        # Determine the index of the new NPC
        npc_index = len(self.npc_data)

        # Check if the map is already full
        if npc_index >= 32:
            self.app.errorBox("Create NPC", "Cannot create NPC: this map is already full!", parent="Map_Editor")
            raise IndexError

        # Create a default NPC
        npc = NPCData(0, 0, 0, 0)
        self.npc_data.append(npc)

        # Add an image for this NPC onto the map canvas
        self.canvas_map.itemconfigure(self.canvas_npc_images[npc_index], state="normal")
        self.canvas_map.coords(self.canvas_npc_images[npc_index], (npc.starting_x << 4) + 8, (npc.starting_y << 4) + 8)

        # Update widgets
        npc_list = self.app.getOptionBoxWidget("NPCE_Option_NPC_List").options
        npc_list.append(f"{npc_index:02d}: G[0x{npc.sprite_id:02X}] D[0x{npc.dialogue_id:02X}] ({npc.starting_x},"
                        f"{npc.starting_y})")
        self.app.changeOptionBox("NPCE_Option_NPC_List", options=npc_list, index=npc_index, callFunction=False)

        return npc, npc_index

    # ------------------------------------------------------------------------------------------------------------------

    def move_npc(self, x: int, y: int, npc_index: int = -1) -> None:
        """
        Moves the starting position of an NPC to the specified map coordinates

        Parameters
        ----------
        x: int
            X coordinate (0 to 63, anything else makes the NPC inactive)
        y: int
            Y coordinate (0 to 63, anything else makes the NPC inactive)
        npc_index: int
            Index of the NPC to modify; if not provided, use the currently selected NPC
        """
        if npc_index < 0:
            npc_index = self.npc_index

        self.npc_data[npc_index].starting_x = x
        self.npc_data[npc_index].starting_y = y

        # Move the NPC image on the map
        self.canvas_map.coords(self.canvas_npc_images[npc_index], (x << 4) + 8, (y << 4) + 8)

        # Update the label showing the position
        self.app.setLabel("NPCE_Starting_Position", f"Starting Pos: {x}, {y}")

    # ------------------------------------------------------------------------------------------------------------------

    def npc_info(self, npc_index: int) -> None:
        """
        Display info for an NPC in the NPC Editor window

        Parameters
        ----------
        npc_index: int
            Index of the NPC whose info will be displayed, from this map's NPC data table
        """
        if npc_index >= len(self.npc_data):
            self.warning(f"Invalid NPC Index: {npc_index}!")
            return
        elif npc_index < 0:
            try:
                npc, npc_index = self._create_npc()
            except IndexError:
                return
        else:
            npc = self.npc_data[npc_index]

        # Select this NPC for editing
        self.npc_index = npc_index

        # Static sprite option
        if npc.sprite_id & 0x80 > 0:
            self.app.setCheckBox("NPCE_Check_Static", ticked=True, callFunction=False)
        else:
            self.app.setCheckBox("NPCE_Check_Static", ticked=False, callFunction=False)

        # Sprite Index
        self.app.setOptionBox("NPCE_Option_Graphics", npc.sprite_id & 0x7F, callFunction=True)

        # Palettes
        if self.rom.has_feature("2-colour sprites"):
            top = self.npc_palette_indices[npc.sprite_id & 0x7F] >> 2
            bottom = self.npc_palette_indices[npc.sprite_id & 0x7F] & 0x3
            self.app.setOptionBox("NPCE_Palette_1", index=top, callFunction=False)
            self.app.setOptionBox("NPCE_Palette_2", index=bottom, callFunction=False)
            self.app.enableOptionBox("NPCE_Palette_2")
        else:
            self.app.setOptionBox("NPCE_Palette_1", index=self.npc_palette_indices[npc_index], callFunction=False)
            self.app.setOptionBox("NPCE_Palette_2", index=0, callFunction=False)
            self.app.disableOptionBox("NPCE_Palette_2")

        # Starting position
        self.app.setLabel("NPCE_Starting_Position", f"Starting Pos: {npc.starting_x}, {npc.starting_y}")
        # Dialogue / Function ID
        self.app.setEntry("NPCE_Entry_Dialogue_ID", f"0x{npc.dialogue_id:02X}", callFunction=False)

    # ------------------------------------------------------------------------------------------------------------------

    def moongate_info(self, moongate_index: int) -> None:
        """
        Displays info about a Moongate / Dawn in the Entrance Editor window

        Parameters
        ----------
        moongate_index: int
            Index of this Moongate in the list (0 to 8, last entry is Dawn)
        """
        if moongate_index < 0 or moongate_index > 8:
            self.warning(f"Invalid Moongate index: {moongate_index}!")
            return

        # Clear previous Moon Phase image
        self.app.clearCanvas("EE_Canvas_Moon_Phase")
        self.app.clearCanvas("EE_Canvas_Moongate_Tile")

        # Coordinates
        self.app.setEntry("EE_Moongate_X", f"{self.moongates[moongate_index].x:02d}", callFunction=False)
        self.app.setEntry("EE_Moongate_Y", f"{self.moongates[moongate_index].y:02d}", callFunction=False)

        if moongate_index < 8:  # Dawn needs no moon phase, just a replacement tile
            # Moon phase
            palette = self.palette_editor.palettes[0]
            colours = self.palette_editor.get_colours(palette[4:8])

            moon_image = Image.new('P', (16, 16), 0)
            moon_image.putpalette(colours)

            address = 0x8E80 + (16 * moongate_index)
            pattern = bytes(bytearray(self.rom.read_pattern(0xA, address)))

            # Upscale the pattern x2
            scaled = bytearray()
            in_offset = 0
            for y in range(8):

                # Copy this line
                for x in range(8):
                    value = pattern[in_offset + x]
                    # Duplicate this pixel
                    scaled.append(value)
                    scaled.append(value)

                # Copy the same line again
                for x in range(8):
                    value = pattern[in_offset + x]
                    # Duplicate this pixel
                    scaled.append(value)
                    scaled.append(value)

                # Move to next input line
                in_offset = in_offset + 8

            image = Image.frombytes('P', (16, 16), bytes(scaled))
            moon_image.paste(image, (0, 0))

            # Convert image to something we can put on a Canvas Widget, and cache it
            image = ImageTk.PhotoImage(moon_image)
            self.app.addCanvasImage("EE_Canvas_Moon_Phase", 8, 8, image)

        # Replacement tile
        self.app.addCanvasImage("EE_Canvas_Moongate_Tile", 8, 8,
                                self.tiles[self.moongate_replacements[moongate_index]])

        self.app.setOptionBox("EE_Option_Moongate_Tile", self.moongate_replacements[moongate_index], callFunction=False)

    # ------------------------------------------------------------------------------------------------------------------

    def entrance_info(self, entrance_index: int) -> None:
        """
        Displays info about a location entrance in the Entrance Editor window

        Parameters
        ----------
        entrance_index: int
            Index of this entrance in the current map's list
        """
        if entrance_index < 0 or entrance_index > len(self.entrances):
            self.warning(f"Invalid entrance index: {entrance_index}!")
            return

        entrance = self.entrances[entrance_index]

        # Coordinates
        self.app.setEntry("EE_Entrance_X", entrance.x, callFunction=False)
        self.app.setEntry("EE_Entrance_Y", entrance.y, callFunction=False)

        # Destination
        if self.map_index == 0xF:
            destination = entrance_index + 0x15
        else:
            destination = entrance_index

        self.app.setLabel("EE_Entrance_Map", f"0x{destination:02X}")

    # ------------------------------------------------------------------------------------------------------------------

    def change_moongate(self, moongate_index: int, new_x: int = -1, new_y: int = -1,
                        new_replacement_tile: int = -1, new_dawn_tile: int = -1) -> None:
        """
        Sets new coordinates, replacement tile, or Dawn's tile for a Moongate

        Parameters
        ----------
        moongate_index: int
            Index of the Moongate to modify; 8 = Dawn
        new_x: int
            New X coordinate; 255 to disable the gate, -1 to leave unchanged
        new_y: int
            New Y coordinate; 255 to disable the gate, -1 to leave unchanged
        new_replacement_tile: int
            ID of the tile that replaces the Moongate as it disappears; 0 to 15 or -1 to leave unchanged
        new_dawn_tile: int
            ID of the tile that appears on Dawn's coordinates; 0 to 15 or -1 to leave unchanged
        """
        if moongate_index < 0 or moongate_index > len(self.moongates):
            self.warning(f"Invalid Moongate index: {moongate_index}.")
            return

        if new_x > -1:
            self.moongates[moongate_index].x = new_x

        if new_y > -1:
            self.moongates[moongate_index].y = new_y

        if new_replacement_tile > -1:
            self.moongate_replacements[moongate_index] = new_replacement_tile & 0xF

        if new_dawn_tile > -1 and moongate_index == 8:
            self.dawn_tile = new_dawn_tile & 0xF

        # Update the icon on the map if coordinates changed
        if new_x > -1 or new_y > -1:
            icon = self.canvas_icon_moongates[moongate_index] if moongate_index < 8 else self.canvas_icon_dawn

            position = self.moongates[moongate_index]
            if position.x > 63 or position.y > 63:
                # Moongate disabled: hide icon
                self.canvas_map.itemconfigure(icon, state="hidden")

            else:
                # Moongate moved, update icon coordinates
                self.canvas_map.coords(icon, (position.x << 4) + 8, (position.y << 4) + 8)
                self.canvas_map.itemconfigure(icon, state="normal")

            # Update the item in the list box
            name = f"{moongate_index}" if moongate_index < 8 else "Dawn"
            self.app.setListItemAtPos("EE_List_Moongates", moongate_index,
                                      f"{name} ({position.x:02d}, {position.y:02d})")

        # Update replacement tile image if changed
        if new_replacement_tile > -1:
            # Remove old image
            self.app.clearCanvas("EE_Canvas_Moongate_Tile")
            # Create a new one
            self.app.addCanvasImage("EE_Canvas_Moongate_Tile", 8, 8, self.tiles[new_replacement_tile])

        # Update Dawn tile image if changed
        if new_dawn_tile > -1 and moongate_index == 8:
            self.app.clearCanvas("EE_Canvas_Dawn_Tile")
            self.app.addCanvasImage("EE_Canvas_Dawn_Tile", 8, 8, self.tiles[self.dawn_tile])

    # ------------------------------------------------------------------------------------------------------------------

    def change_entrance(self, entrance_index: int, new_x: int = 255, new_y: int = 255) -> None:
        """
        Moves the specified entrance to new coordinates

        Parameters
        ----------
        entrance_index: int
            Index of the entrance to modify
        new_x: int
            New horizontal coordinate; anything over 63 deactivates the entrance
        new_y: int
            New vertical coordinate; anything over 63 deactivates the entrance
        """
        if entrance_index < 0 or entrance_index > len(self.entrances):
            self.app.errorBox("Edit Entrance", f"Could not change entrance #{entrance_index}: index out of range.")
            return

        self.entrances[entrance_index].x = new_x
        self.entrances[entrance_index].y = new_y

        # Move the entrance icon on the map
        self.canvas_map.coords(self.canvas_icon_entrances[entrance_index], (new_x << 4) + 8, (new_y << 4) + 8)

        # Hide or un-hide the icon as needed after moving it
        if new_x > 63 or new_y > 63:
            self.canvas_map.itemconfigure(self.canvas_icon_entrances[entrance_index], state="hidden")
        else:
            self.canvas_map.itemconfigure(self.canvas_icon_entrances[entrance_index], state="normal")

        # Update the widget with the list of entrances
        if self.map_index == 0xF:
            destination = entrance_index + 0x15
        else:
            destination = entrance_index

        self.app.setListItemAtPos("EE_List_Entrances", entrance_index,
                                  f"0x{destination:02X} -> {new_x:02}, {new_y:02}")

    # ------------------------------------------------------------------------------------------------------------------

    def is_dungeon(self, map_index: int = -1) -> bool:
        """Use this to check if a map is a dungeon, using the most significant bit of flag/ID field

        Parameters
        ----------
        map_index: int
            Index of the map in the data table. If not specified, uses the currently loaded map.

        Returns
        -------
        bool
            True if the map is a dungeon, False otherwise
        """
        if map_index < 0:
            map_index = self.map_index

        if map_index < 0:
            self.warning("is_dungeon(): No map loaded.")
            return False

        map_data = self.map_table[map_index]
        if map_data.flags == 0xFF:
            return False

        if map_data.flags >> 7 == 1:
            return True

        return False

    # ------------------------------------------------------------------------------------------------------------------

    def is_continent(self, map_index: int = -1) -> bool:
        """
        Reads the map's flags to check whether this map is a Continent
        Note that map 0 is hardcoded as a continent regardless of its flags

        Parameters
        ----------
        map_index: int
            Index of the map to check; if not provided, check the currently loaded map

        Returns
        -------
        bool
            True if map is a continent, otherwise False
        """
        if map_index < 0:
            map_index = self.map_index

        if map_index == 0:
            return True

        if self.map_table[map_index].flags & 0x20:
            return True

        return False

    # ------------------------------------------------------------------------------------------------------------------

    def is_guarded(self, map_index: int = -1) -> bool:
        """
        Reads the map's fags to check whether this map has guards, i.e. the player will make guard NPCs spawn by
        opening a chest or attacking a friendly NPC

        Parameters
        ----------
        map_index: int
            If provided, index of the map to check; otherwise, use the currently loaded map

        Returns
        -------
        bool
            True if the map has guards, False otherwise
        """
        if self.map_table[map_index].flags & 0x40:
            return False

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def get_tile_id(self, x: int, y: int, level: int = -1) -> int:
        """

        Parameters
        ----------
        x: int
            Horizontal coordinate within the current map
        y: int
            Vertical coordinate within the current map
        level: int
            Dungeon level; if not provided use currently displayed level

        Returns
        -------
        int
            The ID of the tile found at the given coordinates (0x00 to 0x0F)
        """
        if self.is_dungeon():
            if 0 < level < 8:
                dungeon_level = level
            else:
                dungeon_level = self.dungeon_level

            offset = dungeon_level << 8
            tile_id = self.map[offset + x + (y << 4)]
        else:
            tile_id = self.map[x + (y << 6)]

        return tile_id

    # ------------------------------------------------------------------------------------------------------------------

    def get_fountain_index(self, x: int, y: int) -> int:
        """Get the index of the fountain that is at the given coordinates in the current dungeon map

        Parameters
        ----------
        x: int
            X coordinate in the current dungeon map/level
        y: int
            Y coordinate int he current dungeon map/level

        Returns
        -------
        int
            The index of the fountain at these coordinates, i.e. the number of fountains found *before* this one
        """
        # Transform x, y and level values to an offset in the map data
        offset = x + (y * 16) + (self.dungeon_level * 256)

        # Loop through map data counting the fountains until we reach the current offset
        count = -1
        for i in range(0, offset):
            if self.map[i] == 0x07:
                count = count + 1

        return count + 1

    # ------------------------------------------------------------------------------------------------------------------

    def get_mark_index(self, x: int, y: int) -> int:
        """
        Get the index of the mark that is at the given coordinates in the current dungeon map

        Parameters
        ----------
        x: int
            X coordinate in the current map/level
        y: int
            Y coordinate in the current map/level

        Returns
        -------
        int
            The index of the mark at the given coordinates, i.e. the number of marks found *before* this one
        """
        # Transform x, y and level values to an offset in the map data
        offset = x + (y * 16) + (self.dungeon_level * 256)

        # Loop through map data counting the fountains until we reach the current offset
        count = -1
        for i in range(0, offset):
            if self.map[i] == 0x06:
                count = count + 1

        return count + 1

    # ------------------------------------------------------------------------------------------------------------------

    def show_marks_count(self) -> None:
        dungeon_id = self.get_map_id()
        value = len(self.dungeon_data[dungeon_id].mark_ids)

        self.app.setLabel("ME_Label_Marks_Count", f"Marks: {value}")

    # ------------------------------------------------------------------------------------------------------------------

    def show_fountains_count(self) -> None:
        dungeon_id = self.get_map_id()
        value = len(self.dungeon_data[dungeon_id].fountain_ids)

        self.app.setLabel("ME_Label_Fountains_Count", f"Fountains: {value}")

    # ------------------------------------------------------------------------------------------------------------------

    def show_fountain_info(self, fountain_id) -> None:
        fountain_values = ["0: HEAL", "1: CURE", "2: HURT", "3: POISON"]
        self.app.changeOptionBox("ME_Special_Tile_Value", options=fountain_values)
        self.app.setOptionBox("ME_Special_Tile_Value", fountain_id, value=False, callFunction=False)
        self.app.setLabel("ME_Special_Tile_Name", "Fountain type:")

        self.app.showFrame("ME_Frame_Special_Tile")

    # ------------------------------------------------------------------------------------------------------------------

    def show_mark_info(self, mark_id) -> None:
        # Get the names from ROM
        mark_names = read_text(self.rom, 0xC, 0xA608).splitlines(False)
        if len(mark_names) != 4:
            mark_values = ["0: KINGS", "1: FIRE", "2: FORCE", "3: SNAKE"]
        else:
            mark_values = [f"0: {mark_names[3]}", f"0: {mark_names[1]}", f"0: {mark_names[0]}", f"0: {mark_names[2]}"]

        self.app.changeOptionBox("ME_Special_Tile_Value", options=mark_values)
        self.app.setOptionBox("ME_Special_Tile_Value", mark_id, value=False, callFunction=False)
        self.app.setLabel("ME_Special_Tile_Name", "Mark type:")

        self.app.showFrame("ME_Frame_Special_Tile")

    # ------------------------------------------------------------------------------------------------------------------

    def change_mark_type(self, x: int, y: int, new_id: int) -> None:
        """
        Changes the Mark at the given coordinates to a new type

        Parameters
        ----------
        x: int
            Horizontal coordinate between 0 and 15
        y: int
            Vertical coordinate between 0 and 15

        new_id: int
            New type ID for this mark, between 0 and 3
        """
        index = self.get_mark_index(x, y)
        dungeon_id: int = self.get_map_id()
        if index >= len(self.dungeon_data[dungeon_id].mark_ids):
            self.warning(f"Invalid Mark index: {index} at {x}, {y}!")
            self.app.errorBox("ERROR", f"Invalid Mark index: {index} at {x}, {y}!", parent="Map_Editor")
        else:
            self.dungeon_data[dungeon_id].mark_ids[index] = new_id

    # ------------------------------------------------------------------------------------------------------------------

    def change_fountain_type(self, x: int, y: int, new_id: int) -> None:
        """
        Changes the Fountain at the given coordinates to a new type

        Parameters
        ----------
        x: int
            Horizontal coordinate between 0 and 15
        y: int
            Vertical coordinate between 0 and 15

        new_id: int
            New type ID for this fountain, between 0 and 3
        """
        index = self.get_fountain_index(x, y)
        dungeon_id: int = self.get_map_id()
        if index >= len(self.dungeon_data[dungeon_id].fountain_ids):
            self.warning(f"Invalid Mark index: {index} at {x}, {y}!")
            self.app.errorBox("ERROR", f"Invalid Fountain index: {index} at {x}, {y}!", parent="Map_Editor")
        else:
            self.dungeon_data[dungeon_id].fountain_ids[index] = new_id

    # ------------------------------------------------------------------------------------------------------------------

    def change_message(self, level: int = -1, message: str = "") -> None:
        """
        Changes the text of a Message Sign for the current dungeon

        Parameters
        ----------
        level: int
            Dungeon level whose message will be changed. If not provided, the level currently being edited will be used
        message: str
            A text string to be assigned to this message
        """
        if level < 0:
            level = self.dungeon_level

        dungeon_id = self.get_map_id()

        # Ignore pointer as it will be reallocated when saving the map
        self.dungeon_data[dungeon_id].messages[level] = message.upper()

    # ------------------------------------------------------------------------------------------------------------------

    def get_map_id(self) -> int:
        """

        Returns
        -------
        int
            The ID of the current map, stripped of the dungeon/continent/guard flags
        """
        # Use 0x3F if pre-v1.09
        if self.rom.has_feature("extra map flags"):
            mask = 0x1F
        else:
            mask = 0x3F
        return self.map_table[self.map_index].flags & mask

    # ------------------------------------------------------------------------------------------------------------------

    def max_maps(self) -> int:
        """
        Tries to detect support of more than 26 maps, based on the address of the location entry coordinates as read
        by the instruction:
        C42F    LDA $FF70,Y
        If the value is $FF70, then up to 26 maps are supported, otherwise we assume it's 32

        Returns
        -------
        int
            The maximum number of maps allowed by this version of the ROM
        """
        if self.rom.read_word(0xF, 0xC430) == 0xFF70:
            return 26

        return 32

    # ------------------------------------------------------------------------------------------------------------------

    def update_moongate_condition(self) -> None:
        """
        Updates the conditional check performed to enable Moongates on the map
        Also shows/hides moongates for the currently opened map accordingly
        """
        # Moongate conditions
        self.info("Saving Moongate conditional check code...")
        # Bank $0B
        # B200    LDA $A8	; <-- Change to lda $70 ($A5 $70) to load map index instead
        # B202    CMP #$0C	; <-- Change 0B:B203 to the index of the map where Moongates and Dawn should be enabled
        check = self.app.getOptionBox("EE_List_Moongates_Options")
        # value = int(self.app.getOptionBox("EE_Option_Moongates_Map")[:4], 16)
        value = self._get_selection_index("EE_Option_Moongates_Map")

        if check[0] == 'C':
            self.rom.write_byte(0xB, 0xB201, 0xA8)
            self.rom.write_byte(0xB, 0xB203, 0x0C)
        else:
            self.rom.write_byte(0xB, 0xB201, 0x70)
            self.rom.write_byte(0xB, 0xB203, value)

        self.load_moongates()

    # ------------------------------------------------------------------------------------------------------------------

    @dataclass(init=True, repr=False)
    class ProcessedEntry:
        """
        Helper class used to recreate the map data table
        """
        old_address: int = 0
        new_address: int = 0

    # ------------------------------------------------------------------------------------------------------------------

    def save_map(self, sync_npc_sprites: bool = True) -> bool:
        """
        Saves changes to the currently loaded map.
        This will recreate the map data table and re-organise the data in the bank where this map is stored.

        Parameters
        ----------
        sync_npc_sprites: bool
            If True, also update the colours used for NPC sprites in battle scenes to be the same used on the map

        Returns
        -------
        bool
            True if changes were successfully saved, False otherwise
        """
        self.info("Saving map changes...")

        # Create a new map table
        new_table: List[MapTableEntry] = []

        # For convenience, store the current map's entry in a local variable
        current_map = self.map_table[self.map_index]

        # Create a helper list
        processed_maps: List[MapEditor.ProcessedEntry] = []
        processed_npcs: List[MapEditor.ProcessedEntry] = []

        # The first available address will depend on bank number and then size/address of the previous one
        first_map_address = 0x8000
        first_npc_address = 0xB800

        if self.bank_compression[current_map.bank] == "LZSS":
            first_map_address = 0x8140
            first_npc_address = 0xB100
        elif self.bank_compression[current_map.bank] == "RLE":
            first_map_address = 0x8050
            first_npc_address = 0xBB00

        else:
            # The vanilla game stores maps at the beginning of the bank, except for bank 6
            if current_map.bank == 2:
                first_map_address = 0x8000
                first_npc_address = 0xBB00
            elif current_map.bank == 6:
                first_map_address = 0x9000
                first_npc_address = 0x9800

        # Since we will be reading map and NPC data from ROM, we can't at the same time write to it
        # So, we'll store maps and NPC data in a buffer
        map_buffer: List[bytearray] = []
        npc_buffer: List[bytearray] = []

        # Go through the current map data table
        for entry in self.map_table:

            if entry.bank != current_map.bank:
                # Different bank: just copy this to the new table
                new_table.append(entry)

            else:

                data_done = False
                npc_done = False

                # Don't process NPC data for dungeons, instead we'll just keep the value, which is used as a starting
                # facing direction in v1.09+
                if entry.flags & 0x80 != 0:
                    npc_done = True

                # Check the processed list for matching Map Data addresses
                for processed in processed_maps:

                    # If this entry's data address had already been processed, then we don't need to reallocate it
                    if data_done is False and processed.old_address == entry.data_pointer:
                        entry.data_pointer = processed.new_address
                        data_done = True

                # Same with the NPC pointer
                for processed in processed_npcs:

                    if npc_done is False and processed.old_address == entry.npc_pointer:
                        entry.npc_pointer = processed.new_address
                        npc_done = True

                # If we found no matches, re-compress the map and store it again
                map_data = bytearray()
                if data_done is False:

                    # If this was the current map's address, use the loaded map data
                    if entry.data_pointer == current_map.data_pointer:

                        if entry.flags & 0x80 != 0:
                            map_data = bytearray(self.map)
                        else:
                            # Use 4-bit packing for non-dungeon maps
                            for i in range(0, 64 * 64, 2):
                                left = self.map[i]
                                right = self.map[i + 1]
                                map_data.append((left << 4) | (right & 0x0F))

                    # Otherwise read it from ROM, un-compress and re-compress
                    else:
                        # Ignore values out of bound
                        if 0 <= entry.bank <= 0xE:
                            # Load raw bytes
                            log(4, f"{self.__class__.__name__}",
                                f"Re-allocating map from {entry.bank:X}:{entry.data_pointer:04X}...")
                            map_data = self.rom.read_bytes(entry.bank, entry.data_pointer, 2048)

                            # Decompress if needed
                            if self.bank_compression[entry.bank] == "LZSS":
                                map_data = lzss.decode(map_data)
                                # We don't have an "end of data" marker, so just discard anything over 2 KB
                                map_data = map_data[0:2048]
                            elif self.bank_compression[entry.bank] == "RLE":
                                map_data = rle.decode(map_data)

                        else:
                            map_data = None

                    # Store this data at the first available address
                    if map_data is not None:

                        # Re-compress if needed
                        if self.bank_compression[entry.bank] == "LZSS":
                            map_data = lzss.encode(map_data).tobytes(order="A")
                        elif self.bank_compression[entry.bank] == "RLE":
                            map_data = rle.encode(map_data)

                        # Add this entry to the processed maps list
                        processed_maps.append(MapEditor.ProcessedEntry(old_address=entry.data_pointer,
                                                                       new_address=first_map_address))

                        # Update pointer for this entry
                        entry.data_pointer = first_map_address
                        # Advance data pointer
                        first_map_address = first_map_address + len(map_data)

                # Check if we also need to re-write the NPC table
                npc_data = bytearray()
                if npc_done is False:

                    # If this is the current map's NPC data address, use the cached data
                    if entry.npc_pointer == current_map.npc_pointer:
                        for npc in self.npc_data:
                            npc_data.append(npc.sprite_id)
                            npc_data.append(npc.dialogue_id)
                            npc_data.append(npc.starting_x)
                            npc_data.append(npc.starting_y)

                        # We need to fill any empty space with 0xFF
                        size = 256 - len(npc_data)
                        for _ in range(0, size):
                            npc_data.append(0xFF)

                    # Otherwise load it from ROM
                    else:
                        npc_data = self.rom.read_bytes(entry.bank, entry.npc_pointer, 256)

                    # Store this entry in the processed list
                    processed_npcs.append(MapEditor.ProcessedEntry(old_address=entry.npc_pointer,
                                                                   new_address=first_npc_address))
                    # Update this entry's pointer
                    entry.npc_pointer = first_npc_address
                    # Advance NPC address pointer
                    first_npc_address = first_npc_address + 256

                # Ready to store the modified entry
                new_table.append(entry)
                # Save data
                # TODO Check that it does not extend over the reserved area in ROM
                npc_buffer.append(npc_data)
                # Save compressed data
                # TODO Check here that it does not go over the allowed area in ROM
                map_buffer.append(map_data)

        # Store the new table in ROM
        address = 0xFEA0
        i = 0  # This will be the index for entries that are on the current bank
        for m in new_table:
            self.rom.write_byte(0xF, address, m.bank)
            address = address + 1
            self.rom.write_word(0xF, address, m.data_pointer)
            address = address + 2
            self.rom.write_word(0xF, address, m.npc_pointer)
            address = address + 2
            self.rom.write_byte(0xF, address, m.entry_y)
            address = address + 1
            self.rom.write_byte(0xF, address, m.entry_x)
            address = address + 1
            self.rom.write_byte(0xF, address, m.flags)
            address = address + 1
            # Write map and NPC data if they belong to the current maps' bank
            if m.bank == current_map.bank:
                if len(map_buffer[i]) > 0 and 0x8000 < m.data_pointer < 0xC000:
                    self.rom.write_bytes(m.bank, m.data_pointer, map_buffer[i])
                if len(npc_buffer[i]) > 0 and 0x8000 < m.npc_pointer < 0xC000:
                    self.rom.write_bytes(m.bank, m.npc_pointer, npc_buffer[i])
                i = i + 1

        # Update the currently cached table
        self.map_table = new_table

        # If we were editing a dungeon map, also reallocate and save messages, marks and fountains
        if self.is_dungeon():
            self.info("Saving dungeon data...")

            # Get base address of message pointers table from ROM, by reading the instruction that is by default:
            # 0D:AA87    LDA $AAF6,X
            base_message_pointer = self.rom.read_word(0xD, 0xAA88)

            # Sanity check: if the pointer seems to be outside the bank, use the default one
            if 0x8000 > base_message_pointer > 0xBFFF:
                log(3, f"{self.__class__.__name__}",
                    f"Base Dungeon Message pointer 0x{base_message_pointer:04X} out of scope."
                    f"Using default value.")
                base_message_pointer = 0xAAF6

            # Get base address of mark/fountain pointers table from ROM, by reading the instruction that is by default:
            # 0D:AD91   LDA $B95D,X
            base_mark_pointer = self.rom.read_word(0xD, 0xAD92)

            # Same sanity check for this
            if 0x8000 > base_mark_pointer > 0xBFFF:
                log(3, f"{self.__class__.__name__}",
                    f"Base Mark/Fountain pointer 0x{base_mark_pointer:04X} out of scope."
                    f"Using default value.")
                base_mark_pointer = 0xB95D

            # First available address for each type of data
            marks_address = self.rom.read_word(0xD, base_mark_pointer)
            fountains_address = self.rom.read_word(0xD, base_mark_pointer + 2)

            # We allocate two separate areas for uncompressed text, to make room for more data
            messages_0 = 0xB635
            messages_0_end = 0xB917
            # The second area is only available in v1.09+
            messages_1 = 0
            messages_1_end = 0
            if base_message_pointer != 0xAAF6:
                messages_1 = 0xAAF6
                messages_1_end = 0xAB65

            for d in range(0, len(self.dungeon_data)):
                # Save marks pointer
                address = base_mark_pointer + (4 * d)
                self.rom.write_word(0xD, address, marks_address)
                self.dungeon_data[d].mark_pointer = address

                # Save mark IDs
                for mark in self.dungeon_data[d].mark_ids:
                    self.rom.write_byte(0xD, marks_address, mark)
                    marks_address = marks_address + 1
                    if marks_address > 0xB9A7:
                        self.app.errorBox("Save Map", "ERROR: Too many Marks!", parent="Map_Editor")
                        break

                # Save fountains pointer
                address = base_mark_pointer + 2 + (4 * d)
                self.rom.write_word(0xD, address, fountains_address)
                self.dungeon_data[d].fountain_pointer = address

                # Save fountain IDs
                for fountain in self.dungeon_data[d].fountain_ids:
                    self.rom.write_byte(0xD, fountains_address, fountain)
                    fountains_address = fountains_address + 1
                    if fountains_address > 0x893D:
                        self.app.errorBox("Save Map", "ERROR: Too many fountains!", parent="Map_Editor")
                        break

                # Save messages
                if d < len(self.dungeon_data):
                    for m in range(len(self.dungeon_data[d].messages)):
                        current_message = self.dungeon_data[d].messages[m]

                        # This will be set to True if an identical message was already found in ROM
                        match = False

                        # Check if this message is a duplicate by comparing it to previous dungeons' messages
                        if d > 0:
                            for previous_dungeon in range(0, d - 1):
                                if match:
                                    break

                                # Loop through each of the previous dungeon's messages
                                for p in range(len(self.dungeon_data[previous_dungeon].messages)):
                                    previous_message = self.dungeon_data[previous_dungeon].messages[p]

                                    if current_message == previous_message:
                                        # Match: update pointer, don't write message
                                        self.dungeon_data[d].message_pointers[m] = \
                                            self.dungeon_data[previous_dungeon].message_pointers[p]
                                        match = True
                                        break

                        # Allocate memory for this text if needed
                        if match is False:
                            # Encode string
                            data = ascii_to_exodus(current_message)
                            # Add terminator character if needed
                            if len(data) < 1 or data[-1] != 0xFF:
                                data.append(0xFF)

                            # Check if it fits in the first message area
                            size = len(data)
                            if messages_0 + size > messages_0_end:
                                # Won't fit: try the second area if available
                                if messages_1 > 0x8000:
                                    if messages_1 + size > messages_1_end:
                                        log(2, f"{self.__class__.__name__}",
                                            f"Message '{current_message}' from dungeon #{d} won't fit in ROM!")
                                        # Show a popup message and ask to continue/abort
                                        if self.app.yesNoBox("Saving Dungeon Messages",
                                                             f"ERROR: Message '{current_message}' from dungeon "
                                                             f"#{d} won't fit in ROM!\nDo you want to continue?",
                                                             parent="Map_Editor"):
                                            continue
                                        else:
                                            return False
                                    else:
                                        # Save area 1 pointer
                                        self.dungeon_data[d].message_pointers[m] = messages_1
                                        messages_1 = messages_1 + size
                                else:
                                    log(2, f"{self.__class__.__name__}",
                                        f"Message '{current_message}' from dungeon #{d} won't fit in ROM!")
                                    if self.app.yesNoBox("Saving Dungeon Messages",
                                                         f"ERROR: Message '{current_message}' from dungeon "
                                                         f"#{d} won't fit in ROM!\nDo you want to continue?",
                                                         parent="Map_Editor"):
                                        continue
                                    else:
                                        return False
                            else:
                                # Save area 0 pointer
                                self.dungeon_data[d].message_pointers[m] = messages_0
                                messages_0 = messages_0 + size

                            # Save text
                            self.rom.write_bytes(0xD, self.dungeon_data[d].message_pointers[m], data)

                        # Save pointer
                        address = base_message_pointer + (2 * m) + (16 * d)
                        self.rom.write_word(0xD, address, self.dungeon_data[d].message_pointers[m])

            # Custom dungeon colours only if the ROM supports them
            if self.rom.has_feature("custom map colours"):
                self.info("Saving custom map colours...")
                address = self.rom.read_word(0xB, 0x86AF) + self.get_map_id()
                self.rom.write_byte(0xB, address, self.map_colour)
                address = self.rom.read_word(0xD, 0xBDD2) + self.get_map_id()
                self.rom.write_byte(0xD, address, self.map_colour)
            else:
                self.info("Custom map colours not supported by this ROM.")

        else:
            # Custom map colours only if the ROM supports them
            if self.rom.has_feature("custom map colours"):
                self.info("Saving custom map colours...")
                address = self.rom.read_word(0xF, 0xEE03) + self.map_index
                self.rom.write_byte(0xF, address, self.map_colour)
            else:
                self.info("Custom map colours not supported by this ROM.")

        # Save Entrances and Moongates if enabled on this map
        # Entrances
        if self.map_index == 0 or self.map_index == 0xF:
            self.info("Saving map entrance data...")

            # Entrances from Sosaria
            if self.map_index == 0:
                # Get the address of the entrance coordinates table
                # Default / vanilla game:
                # C42F    LDA $FF70,Y
                # v1.09+:
                # C42F    LDA $FB50,Y
                address = self.rom.read_word(0xF, 0xC430)

            # Entrances from Ambrosia
            else:
                # C46A    LDA $C489,Y
                # v1.09+:
                # C46A    LDA $FB7A,Y
                # This also tells us how many extra entrances are allowed from the second continent
                address = self.rom.read_word(0xF, 0xC46B)

            # Store entrance coordinates
            for e in self.entrances:
                self.rom.write_byte(0xF, address, e.x)
                self.rom.write_byte(0xF, address + 1, e.y)
                address = address + 2

        # Moongates
        if len(self.moongates) > 0:
            self.info("Saving Moongate data...")

            # Store Moongate coordinates and replacement tile ids
            address_1 = 0xC4D2
            address_2 = 0xB2CF
            address_3 = 0xB2C7

            for g in range(8):
                self.rom.write_byte(0xF, address_1, self.moongates[g].x)
                self.rom.write_byte(0xF, address_1 + 1, self.moongates[g].y)
                self.rom.write_byte(0xB, address_2, self.moongates[g].x)
                self.rom.write_byte(0xB, address_2 + 1, self.moongates[g].y)
                address_1 = address_1 + 2
                address_2 = address_2 + 2

                self.rom.write_byte(0xB, address_3, self.moongate_replacements[g] | 0x80)
                address_3 = address_3 + 1

            # Store Dawn coordinates
            self.rom.write_byte(0xB, 0xB212, self.moongates[8].x)
            self.rom.write_byte(0xB, 0xB216, self.moongates[8].y)

            # Store Dawn tile id
            self.rom.write_byte(0xB, 0xB226, self.dawn_tile | 0x80)

            # Store Dawn replacement tile id
            self.rom.write_byte(0xB, 0xB22B, self.moongate_replacements[8] | 0x80)

        # Save NPC palette indices
        self.rom.write_bytes(0xF, 0xCED2, bytes(self.npc_palette_indices[:23]))

        # If requested, keep the same colours for battle sprites
        if sync_npc_sprites:
            self.rom.write_bytes(0xC, 0xBA08, bytes(self.npc_palette_indices[:23]))

        self.info("All done!")
        return True

    # ------------------------------------------------------------------------------------------------------------------

    def map_pick_tile(self, event: any) -> None:
        """
        Called when the user clicks on the tile picker canvas

        Parameters
        ----------
        event
            Mouse click event instance
        """
        tile_index = (event.x >> 4) + ((event.y >> 4) << 3)

        if tile_index < 0 or tile_index > 0xF:
            return

        # print(f"Picked tiled ID: 0x{tile_index:02X}")
        self.selected_tile_id = tile_index
        self.tile_info(tile_index)
        self.app.setLabel("ME_Selected_Tile_Position", "")

        # Hide the "special" field for now
        self.app.hideFrame("ME_Frame_Special_Tile")

        # If the current tool is neither "draw" nor "fill", switch to drawing mode
        if self.tool != "draw" and self.tool != "fill":
            self.select_tool("draw")

    # ------------------------------------------------------------------------------------------------------------------

    def npc_select_graphics(self, option_box: str) -> None:
        """
        An item has been selected from the NPC Sprite Option Box in the NPC Editor sub-window

        Parameters
        ----------
        option_box: str
            Name of the widget generating the event, could be either the option box or the "static" checkbox
        """
        if option_box == "NPCE_Option_Graphics" or option_box == "NPCE_Option_Graphics":
            selection = int(self.app.getOptionBox("NPCE_Option_Graphics"), base=16)
            if self.app.getCheckBox("NPCE_Check_Static"):
                selection = selection | 0x80
            self.select_npc_graphics(selection)

        elif option_box == "NPCE_Palette_1" or option_box == "NPCE_Palette_2":
            top = int(self.app.getOptionBox("NPCE_Palette_1"))
            if self.rom.has_feature("2-colour sprites"):
                bottom = int(self.app.getOptionBox("NPCE_Palette_2"))
            else:
                bottom = 0
            self.change_npc_palettes(top, bottom)

    # ------------------------------------------------------------------------------------------------------------------

    def entrance_input(self, widget: str) -> None:
        """
        Callback function for presses/changes on widgets in the Entrance Editor sub-sub-window

        Parameters
        ----------
        widget: str
            Name of the widget that generated the event
        """

        _SELECTED = "#DFDFDF"
        _UNSELECTED = "#FFFFFF"

        # Click on Entrance Move Button
        if widget == "EE_Button_Entrance_Set":
            if self.selected_entrance > -1:
                self.select_tool("move_entrance")

        # Click on Entrance Remove Button
        elif widget == "EE_Button_Entrance_Remove":
            if self.selected_entrance < 0 or len(self.app.getAllListItems("EE_List_Entrances")) < 1:
                return

            self.change_entrance(self.selected_entrance, 0xFF, 0xFF)

        # Selected item from Entrances ListBox
        elif widget == "EE_List_Entrances":
            value = self.app.getListBoxPos(widget)
            if len(value):
                # If clicking on the already selected item, just jump to it on the map
                if value[0] == self.selected_entrance:
                    point = self.entrances[value[0]]
                    self.jump_to(point.x, point.y)

                else:
                    # We change the background of the item as it will be deselected when clicking outside the list
                    items: list = self.app.getAllListItems(widget)
                    for pos in range(len(items)):
                        if pos == value[0]:
                            self.app.setListItemAtPosBg(widget, pos, _SELECTED)
                            self.selected_entrance = pos
                        else:
                            self.app.setListItemAtPosBg(widget, pos, _UNSELECTED)

                    # Update the widgets to show info about this entrance
                    self.entrance_info(value[0])

        # Input new value in Entrance X / Y Entry Widget
        elif widget == "EE_Entrance_X" or widget == "EE_Entrance_Y":
            if self.selected_entrance < 0 or len(self.app.getAllListItems("EE_List_Entrances")) < 1:
                return

            try:
                new_x = int(self.app.getEntry("EE_Entrance_X"))
                new_y = int(self.app.getEntry("EE_Entrance_Y"))
                self.change_entrance(self.selected_entrance, new_x, new_y)

            except ValueError:
                pass

        # Selected new condition for Moongates to show up
        elif widget == "EE_List_Moongates_Options":
            value = self.app.getOptionBox("EE_List_Moongates_Options")
            if value[0] == 'C':  # Continent maps only
                self.app.disableOptionBox("EE_Option_Moongates_Map")

            else:  # A specific map
                self.app.enableOptionBox("EE_Option_Moongates_Map")
                # Select the current map by default
                self.app.setOptionBox("EE_Option_Moongates_Map", index=self.map_index, callFunction=False)

            # This will save the changes to the ROM buffer, and show/hide the Moongates accordingly
            self.update_moongate_condition()

        # Selected item from Moongates ListBox
        elif widget == "EE_List_Moongates":
            value = self.app.getListBoxPos(widget)
            if len(value):
                # If clicking on the already selected item, just jump to it on the map
                if value[0] == self.selected_moongate:
                    point = self.moongates[value[0]]
                    self.jump_to(point.x, point.y)

                else:
                    items: list = self.app.getAllListItems(widget)
                    for pos in range(len(items)):
                        if pos == value[0]:
                            self.app.setListItemAtPosBg(widget, pos, _SELECTED)
                            self.selected_moongate = pos
                            self.moongate_info(pos)
                        else:
                            self.app.setListItemAtPosBg(widget, pos, _UNSELECTED)

        # Mouse click on move Moongate button
        elif widget == "EE_Button_Moongate_Set":
            if 0 <= self.selected_moongate <= 8:
                self.select_tool("move_moongate")

        # Mouse click on remove Moongate button
        elif widget == "EE_Button_Moongate_Remove":
            if self.selected_moongate < 0 or len(self.app.getAllListItems("EE_List_Moongates")) < 1:
                pass
            else:
                self.change_moongate(self.selected_moongate, 0xFF, 0xFF)

        # Entered a new value for Moongate X
        elif widget == "EE_Moongate_X" or widget == "EE_Moongate_Y":
            if 0 <= self.selected_moongate <= 8:
                try:
                    new_x = int(self.app.getEntry("EE_Moongate_X"))
                    new_y = int(self.app.getEntry("EE_Moongate_Y"))
                    self.change_moongate(self.selected_moongate, new_x=new_x, new_y=new_y)
                except ValueError:
                    # Invalid input: restore previous value
                    # app.setEntry(widget, f"{map_editor.moongates[selected_moongate].x}", callFunction=False)
                    pass

        # Selected a new tile for Dawn
        elif widget == "EE_Option_Dawn_Tile":
            new_tile_id = int(self.app.getOptionBox(widget), 16)
            self.change_moongate(8, new_dawn_tile=new_tile_id)

        # Selected a new Moongate/Dawn replacement tile
        elif widget == "EE_Option_Moongate_Tile":
            if 0 <= self.selected_moongate <= 8:
                new_tile_id = int(self.app.getOptionBox(widget), 16)
                self.change_moongate(self.selected_moongate, new_replacement_tile=new_tile_id)

        else:
            self.warning(f"Unimplemented callback for widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def select_dungeon_special_type(self, widget) -> None:
        """
        User selected either a new Mark or Fountain type for the currently selected dungeon tile

        Parameters
        ----------
        widget
            The OptionBox where the event occurred
        """
        tile_x, tile_y = self._last_tile.x, self._last_tile.y

        try:
            special_id = int(self.app.getOptionBox(widget)[0])
        except ValueError as error:
            log(2, "EDITOR", f"Could not read special type ID from '{self.app.getOptionBox(widget)}': {error}")
            return

        # First, check if the current tile is a special one, and then change it depending on which one it is
        tile_id = self.get_tile_id(tile_x, tile_y)

        if tile_id == 6:  # Mark
            self.change_mark_type(tile_x, tile_y, special_id)
        elif tile_id == 7:  # Fountain
            self.change_fountain_type(tile_x, tile_y, special_id)
        else:  # Not a special tile!
            self.app.errorBox("ERROR", f"Could not find special tile at {tile_x}, {tile_y}!\nID = 0x{tile_id:02X}.",
                              parent="Map_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def select_dungeon_level(self, sel: str) -> None:
        """
        Called when the user clicks on the dungeon level Option Box widget

        Parameters
        ----------
        sel: str
            Title of the Option Box widget
        """
        try:
            level = int(self.app.getOptionBox(sel)) - 1
        except ValueError:
            level = 0

        self.dungeon_level = level
        self.show_map()

    # ------------------------------------------------------------------------------------------------------------------

    def change_dungeon_message(self, widget) -> None:
        """
        User typed something in the dungeon message.

        Parameters
        ----------
        widget
            The TextArea widget where the event occurred
        """
        self.change_message(message=self.app.getTextArea(widget))
