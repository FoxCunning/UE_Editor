__author__ = "Fox Cunning"

from typing import List

from appJar import gui
from debug import log
from rom import ROM


class PaletteEditor:
    """
    Palette Editor

    Attributes
    ----------
    rom: ROM
        Instance of the ROM handler
    app: gui
        Main AppJar gui instance
    """

    def __init__(self, rom: ROM, app: gui):
        self.app = app
        self.rom = rom
        self._colours: list = [[124, 124, 124],
                               [0, 0, 252],
                               [0, 0, 188],
                               [68, 40, 188],
                               [148, 0, 132],
                               [168, 0, 32],
                               [168, 16, 0],
                               [136, 20, 0],
                               [80, 48, 0],
                               [0, 120, 0],
                               [0, 104, 0],
                               [0, 88, 0],
                               [0, 64, 88],
                               [0, 0, 0],
                               [0, 0, 0],
                               [0, 0, 0],
                               [188, 188, 188],
                               [0, 120, 248],
                               [0, 88, 248],
                               [104, 68, 252],
                               [216, 0, 204],
                               [228, 0, 88],
                               [248, 56, 0],
                               [228, 92, 16],
                               [172, 124, 0],
                               [0, 184, 0],
                               [0, 168, 0],
                               [0, 168, 68],
                               [0, 136, 136],
                               [0, 0, 0],
                               [0, 0, 0],
                               [0, 0, 0],
                               [248, 248, 248],
                               [60, 188, 252],
                               [104, 136, 252],
                               [152, 120, 248],
                               [248, 120, 248],
                               [248, 88, 152],
                               [248, 120, 88],
                               [252, 160, 68],
                               [248, 184, 0],
                               [184, 248, 24],
                               [88, 216, 84],
                               [88, 248, 152],
                               [0, 232, 216],
                               [120, 120, 120],
                               [0, 0, 0],
                               [0, 0, 0],
                               [252, 252, 252],
                               [164, 228, 252],
                               [184, 184, 248],
                               [216, 184, 248],
                               [248, 184, 248],
                               [248, 164, 192],
                               [240, 208, 176],
                               [252, 224, 168],
                               [248, 216, 120],
                               [216, 248, 120],
                               [184, 248, 184],
                               [184, 248, 216],
                               [0, 252, 252],
                               [248, 216, 248],
                               [0, 0, 0],
                               [0, 0, 0]]

        # TODO Read colours from file

        self.palettes = []

        # Currently displayed palette set, or -1 for none
        self.selected_palette_set = -1
        # Currently selected palette for editing, or -1 for none
        self.selected_palette = -1
        # Currently selected colour for editing, or -1 for none
        self.selected_colour = -1

    # --- PaletteEditor.get_colour() ---

    def get_colour(self, index: int) -> list:
        """
        Get a colour from the NES palette

        Parameters
        ----------
        index: int
            Colour index (0x00 to 0x3F)

        Returns
        -------
        list
            An array in the form [red, green, blue] for the requested NES colour index (0x00 to 0x3F)
        """
        colour: list = [0, 0, 0]
        if 0 <= index < len(self._colours):
            colour = self._colours[index]
            # return colour
        return colour

    # --- PaletteEditor.get_colours() ---

    def get_colours(self, values: List[int]) -> bytearray:
        """
        Get a list of RGB values for the required colour indices taken from the NES palette

        Parameters
        ----------
        values: List[int]
            List of indices from the NES palette (0x00 to 0x3F)

        Returns
        -------
        bytearray
            A series of RGB values as a bytearray
        """
        colours = bytearray()

        for c in values:
            colour = bytes(self.get_colour(c))
            colours.append(colour[0])
            colours.append(colour[1])
            colours.append(colour[2])

        return colours

    # --- PaletteEditor.sub_palette() ---

    def sub_palette(self, palette_index: int, sub_palette_index: int) -> bytearray:
        """
        Retrieves RGB values for four colours in one of the four sub-palettes in the specified palette

        Parameters
        ----------
        palette_index: int
        sub_palette_index: int

        Returns
        -------
        bytearray
            Four 8-bit R, G, B values in a bytearray
        """
        first = sub_palette_index * 4
        last = first + 4
        return self.get_colours(self.palettes[palette_index][first:last])

    # --- PaletteEditor._read_palette() ---

    def _read_palette(self, bank: int, address: int) -> list:
        """
        Read 4x4 colours (4 tile palettes of 4 colours each) from ROM

        Parameters
        ----------
        bank: int
            ROM bank number
        address: int
            Address in ROM

        Returns
        -------
        list
            Colours in the palette at bank:address as a list of values
        """
        temp_colours = []
        for _ in range(16):
            temp_colours.append(self.rom.read_byte(bank, address))
            address = address + 1

        return temp_colours

    # --- PaletteEditor.load_palettes() ---

    def load_palettes(self) -> None:
        """
        Load all palettes from ROM and update the Palettes frame accordingly
        """
        # log(4, "PALETTE EDITOR", "Loading palettes from ROM...")

        # Populate the full NES palette canvas
        self.app.clearCanvas("PE_Canvas_Full")
        canvas = self.app.getCanvas("PE_Canvas_Full")

        for i in range(0x40):
            cell_x = (i % 0x10) << 4
            cell_y = (i >> 4) << 4

            colour = self._colours[i]
            colour_string = f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}"

            # print(f"Adding colour[{i:02X}]: {colour_string} at {cell_x}, {cell_y}")
            canvas.create_rectangle(cell_x, cell_y, cell_x + 16, cell_y + 16, fill=colour_string, outline="#000000",
                                    width=1)
            if i == 0x2D or i == 0x3D:
                text_colour = "red"
            elif cell_x > 192 or cell_y < 32:
                text_colour = "white"
            else:
                text_colour = "black"
            canvas.create_text(cell_x + 8, cell_y + 8, text=f"{i:02X}", fill=text_colour)

        # Read palettes from ROM

        # palettes[0] = Map Default, background
        # Base map palette --> palettes[0]
        # Read 4x4 colours (4 tile palettes of 4 colours each)
        self.palettes.append(self._read_palette(0xF, 0xFE3E))

        # palettes[1] = Map Default, sprites
        self.palettes.append(self._read_palette(0xF, 0xFE4E))

        # palettes[2] = Ambrosia, background
        self.palettes.append(self._read_palette(0xF, 0xFE5E))

        # palettes[3] = Ambrosia, sprites
        self.palettes.append(self._read_palette(0xF, 0xFE6E))

        # palettes[4] to palettes[8] = Intro / Credits
        address = 0xBA8D
        for _ in range(5):
            self.palettes.append(self._read_palette(0xE, address))
            address = address + 0x10

        # palettes[9] to palettes[13] Title (Fade 0-2, Final, Sprites)
        address = 0xBADD
        for _ in range(5):
            self.palettes.append(self._read_palette(0xE, address))
            address = address + 0x10

        # palettes[14] to palettes[29] = Dungeon palettes (note that the hack doesn't use the default dungeon palettes)
        # 8 palettes for various light conditions
        address = 0xB46B
        for _ in range(8):
            self.palettes.append(self._read_palette(0xB, address))
            address = address + 0x10
        # Time Lord BG
        self.palettes.append(self._read_palette(0xB, 0xB3DC))
        # Time Lord sprites
        self.palettes.append(self._read_palette(0xB, 0xB3EC))
        # Marks BG
        self.palettes.append(self._read_palette(0xB, 0xAF70))
        # Marks sprites
        self.palettes.append(self._read_palette(0xB, 0xAF80))
        # Fountains BG
        self.palettes.append(self._read_palette(0xB, 0xB35E))
        # Fountains sprites
        self.palettes.append(self._read_palette(0xB, 0xB36E))
        # Map view, unused in recent hack versions
        self.palettes.append(self._read_palette(0xD, 0xBD4B))
        # Map view sprites
        self.palettes.append(self._read_palette(0xD, 0xBD5B))

        # palettes[30] and palettes[31] = colours used to flash the screen (e.g. when casting spells)
        self.palettes.append(self._read_palette(0xF, 0xFE7E))   # BG
        self.palettes.append(self._read_palette(0xF, 0xFE8E))   # Sprites

        # palettes[32] and palettes[33] = "end sequence" palettes, used after activating Exodus's altar
        self.palettes.append(self._read_palette(0xB, 0x9244))   # BG
        self.palettes.append(self._read_palette(0xB, 0x9254))   # Sprites

        # palettes[34] and palettes[35] = Status screen
        self.palettes.append(self._read_palette(0xC, 0x9752))   # BG
        self.palettes.append(self._read_palette(0xC, 0x9762))   # Sprites

        # palettes[36] and palettes[37] = Continent map view
        self.palettes.append(self._read_palette(0xF, 0xFFD0))   # BG
        self.palettes.append(self._read_palette(0xF, 0xFFE0))   # Sprites

        # palettes[38] and palettes[39] = Cutscene
        self.palettes.append(self._read_palette(0xC, 0x835F))   # BG
        self.palettes.append(self._read_palette(0xC, 0x836F))   # Sprites

        # Select Intro palettes by default
        self.app.setOptionBox("PE_List_Palettes", 0)

    # --- PaletteEditor.show_palette_set() ---

    def show_palette_set(self, palette_index: int) -> None:
        """
        Shows a palette for editing

        Parameters
        ----------
        palette_index: int
            Palette index:
            0       Map Default (background),
            1       Map Default (sprites),
            2       Ambrosia (background),
            3       Ambrosia (sprites),
            4       Intro (Dark),
            5       Intro (Fading 1),
            6       Intro (Fading 2),
            7       Intro (Fading 3),
            8       Intro (Text),
            9-13    Title
            14-29   Dungeon
            30-31   Flashing
            32-33   End Sequence
            34-35   Status
            36-37   Menu
        """
        palette = self.palettes[palette_index]

        palette_names = ["Map Backgrounds",
                         "Map Sprites",
                         "Ambrosia Backgrounds",
                         "Ambrosia Sprites",
                         "Start (Dark)",
                         "Start (Fading 1)",
                         "Start (Fading 2)",
                         "Start (Fading 3)",
                         "Start (Text)",
                         "Title Screen, Fade 0",
                         "Title Screen, Fade 1",
                         "Title Screen, Fade 2",
                         "Title Screen, Final",
                         "Title Screen, Sprites",
                         "Dungeon BG, fully lit",
                         "Dungeon Sprites, fully lit",
                         "Dungeon BG, *unused*",
                         "Dungeon Sprites, *unused*",
                         "Dungeon BG, darkness",
                         "Dungeon Sprites, darkness",
                         "Dungeon BG, medium light",
                         "Dungeon Sprites, medium light",
                         "Time Lord BG",
                         "Time Lord Sprites",
                         "Marks BG",
                         "Marks Sprites",
                         "Fountains BG",
                         "Fountains Sprites",
                         "Dungeon Map View BG",
                         "Dungeon Map View Sprites",
                         "Flashing Effect BG",
                         "Flashing Effect Sprites",
                         "End Sequence BG",
                         "End Sequence Sprites",
                         "Menu / Status Screen BG",
                         "Menu / Status Screen Sprites",
                         "Continent Map View BG",
                         "Continent Map View Sprites",
                         "Cutscene BG",
                         "Cutscene Sprites"]

        # TODO Notify of unused dungeon palettes for recent hack versions

        self.app.setLabel("PE_Label_0", text=palette_names[palette_index])
        self.selected_palette_set = palette_index

        # Clear canvases
        for i in range(4):
            self.app.clearCanvas(f"PE_Canvas_Palette_{i}")

        # Add colour boxes, 4 per palette, with 4 palettes in each set
        for i in range(4):
            canvas = self.app.getCanvas("PE_Canvas_Palette_0")
            colour = bytes(self.get_colour(palette[i]))
            colour_string = f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}"
            x = i * 16
            canvas.create_rectangle(x, 0, x + 16, 16, fill=colour_string, outline="#000000", width=1)
            if palette[i] < 0x20 or 0x2D <= palette[i] <= 0x2F or palette[i] == 0x3E or palette[i] == 0x3F:
                text_colour = "#FFFFFF"
            else:
                text_colour = "#000000"
            canvas.create_text(x + 8, 8, text=f"{palette[i]:02X}", fill=text_colour)
            # print(f"*DEBUG* Adding colour {colour_string} at {x}, 0.")

        for i in range(4):
            colour_index = i + 4
            canvas = self.app.getCanvas("PE_Canvas_Palette_1")
            colour = bytes(self.get_colour(palette[colour_index]))
            colour_string = f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}"
            x = i * 16
            canvas.create_rectangle(x, 0, x + 16, 16, fill=colour_string, outline="#000000", width=1)
            if palette[colour_index] < 0x20 or 0x2D <= palette[colour_index] <= 0x2F or palette[colour_index] == 0x3E \
                    or palette[colour_index] == 0x3F:
                text_colour = "#FFFFFF"
            else:
                text_colour = "#000000"
            canvas.create_text(x + 8, 8, text=f"{palette[colour_index]:02X}", fill=text_colour)
            # print(f"*DEBUG* Adding colour {colour_string} at {x}, 0.")

        for i in range(4):
            colour_index = i + 8
            canvas = self.app.getCanvas("PE_Canvas_Palette_2")
            colour = bytes(self.get_colour(palette[colour_index]))
            colour_string = f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}"
            x = i * 16
            canvas.create_rectangle(x, 0, x + 16, 16, fill=colour_string, outline="#000000", width=1)
            if palette[colour_index] < 0x20 or 0x2D <= palette[colour_index] <= 0x2F or palette[colour_index] == 0x3E \
                    or palette[colour_index] == 0x3F:
                text_colour = "#FFFFFF"
            else:
                text_colour = "#000000"
            canvas.create_text(x + 8, 8, text=f"{palette[colour_index]:02X}", fill=text_colour)

        for i in range(4):
            colour_index = i + 12
            canvas = self.app.getCanvas("PE_Canvas_Palette_3")
            colour = bytes(self.get_colour(palette[colour_index]))
            colour_string = f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}"
            x = i * 16
            canvas.create_rectangle(x, 0, x + 16, 16, fill=colour_string, outline="#000000", width=1)
            if palette[colour_index] < 0x20 or 0x2D <= palette[colour_index] <= 0x2F or palette[colour_index] == 0x3E \
                    or palette[colour_index] == 0x3F:
                text_colour = "#FFFFFF"
            else:
                text_colour = "#000000"
            canvas.create_text(x + 8, 8, text=f"{palette[colour_index]:02X}", fill=text_colour)

    # --- PaletteEditor.choose_palette_set() ---

    def choose_palette_set(self, palette_set: str) -> None:
        """
        Select a palette set to edit, and show the first palette in this set.

        Parameters
        ----------
        palette_set: str
            One of: "Intro / Credits", "Title", "Status Screen", "Flashing", "End Sequence", "Map Default",
            "Ambrosia", "Dungeon", "Continent View"
        """
        if palette_set == "Start / Credits":
            self.show_palette_set(4)
        elif palette_set == "Map Default":
            self.show_palette_set(0)
        elif palette_set == "Ambrosia":
            self.show_palette_set(2)
        elif palette_set == "Title":
            self.show_palette_set(9)
        elif palette_set == "Dungeon":
            self.show_palette_set(14)
        elif palette_set == "Flashing":
            self.show_palette_set(30)
        elif palette_set == "End Sequence":
            self.show_palette_set(32)
        elif palette_set == "Status Screen":
            self.show_palette_set(34)
        elif palette_set == "Continent View":
            self.show_palette_set(36)
        elif palette_set == "Cutscene":
            self.show_palette_set(38)
        else:
            log(3, "PALETTE EDITOR", f"Invalid palette set '{palette_set}' selected!")

    # --- PaletteEditor.edit_colour() ---

    def edit_colour(self, palette_index: int, colour_index: int) -> None:
        """
        User clicked on a palette to pick a colour to change

        Parameters
        ----------
        palette_index: int
            One of the 4 palettes in the currently displayed set (0 to 3)
        colour_index: int
            One of the 4 colours in the above mentioned palette (0 to 3)
        """
        if self.selected_colour != -1:
            # Copy previously selected colour
            # Get value of previously selected colour
            palette = self.palettes[self.selected_palette_set]
            new_colour = colour_index + (palette_index * 4)
            self.change_colour(palette[new_colour])
            return

        # print(f"*DEBUG* Editing Palette {palette_index}, colour {colour_index}")

        canvas = self.app.getCanvas(f"PE_Canvas_Palette_{palette_index}")
        # print("*DEBUG* Canvas children: ", canvas.find_all())

        # Highlight selected colour
        canvas_text = canvas.find_all()[(colour_index << 1) + 1]  # (colour_index + 1) << 1
        # print(f"*DEBUG* Canvas Text item {canvas_text}")
        canvas.itemconfig(canvas_text, fill="#FF0000")

        self.selected_colour = colour_index
        self.selected_palette = palette_index
        # old_colour = self.selected_colour + (self.selected_palette * 4)
        # print(f"*DEBUG* Editing colour {old_colour:02X}")

    # --- PaletteEditor.change_colour() ---

    def change_colour(self, new_colour: int) -> None:
        """
        Replaces a colour in a palette with another one

        Parameters
        ----------
        new_colour: int
        """
        if self.selected_colour == -1:
            # No colour selected, this shouldn't happen
            log(3, "PALETTE EDITOR", "Requested to change colour without a selection.")
            return

        # print(f"*DEBUG* Assigning {new_colour:02X} to colour {self.selected_colour} in palette {
        # self.selected_palette}")
        palette = self.palettes[self.selected_palette_set]
        palette[self.selected_colour + (self.selected_palette * 4)] = new_colour

        self.selected_colour = -1

        # Refresh view
        self.show_palette_set(self.selected_palette_set)

    # --- PaletteEditor.next_palette() ---

    def next_palette(self) -> None:
        """
        Shows the next palette in the current set
        """
        last_palettes = [1, 3, 8, 13, 29, 31, 33, 35, 37, 39]
        # Make sure we have not reached the last palette in the current set
        try:
            last_palettes.index(self.selected_palette_set)
            return
        except ValueError:
            self.show_palette_set(self.selected_palette_set + 1)

    # --- PaletteEditor.previous_palette() ---

    def previous_palette(self) -> None:
        """
        Shows the previous palette in the current set
        """
        last_palettes = [0, 2, 4, 9, 14, 30, 32, 34, 36, 38]
        # Make sure we have not reached the last palette in the current set
        try:
            last_palettes.index(self.selected_palette_set)
            return
        except ValueError:
            self.show_palette_set(self.selected_palette_set - 1)

    # --- PaletteEditor.save_palettes() ---

    def save_palettes(self):
        """
        Writes palette data to ROM
        """
        # palettes[0] = Map Default, background
        # Base map palette --> palettes[0]
        self.rom.write_bytes(0xF, 0xFE3E, bytes(self.palettes[0]))

        # palettes[1] = Map Default, sprites
        self.rom.write_bytes(0xF, 0xFE4E, bytes(self.palettes[1]))

        # palettes[2] = Ambrosia, background
        self.rom.write_bytes(0xF, 0xFE5E, bytes(self.palettes[2]))

        # palettes[3] = Ambrosia, sprites
        self.rom.write_bytes(0xF, 0xFE6E, bytes(self.palettes[3]))

        # palettes[4] to palettes[8] = Intro / Credits
        address = 0xBA8D
        for p in range(5):
            self.rom.write_bytes(0xE, address, bytes(self.palettes[4 + p]))
            address = address + 0x10

        # palettes[9] to palettes[13] Title (Fade 0-2, Final, Sprites)
        address = 0xBADD
        for p in range(5):
            self.rom.write_bytes(0xE, address, bytes(self.palettes[9 + p]))
            address = address + 0x10

        # palettes[14] to palettes[29] = Dungeon palettes (note that the hack doesn't use the default dungeon palettes)
        # 8 palettes for various light conditions
        address = 0xB46B
        for p in range(8):
            self.rom.write_bytes(0xB, address, bytes(self.palettes[14 + p]))
            address = address + 0x10
        # Time Lord BG
        self.rom.write_bytes(0xB, 0xB3DC, bytes(self.palettes[22]))
        # Time Lord sprites
        self.rom.write_bytes(0xB, 0xB3EC, bytes(self.palettes[23]))
        # Marks BG
        self.rom.write_bytes(0xB, 0xAF70, bytes(self.palettes[24]))
        # Marks sprites
        self.rom.write_bytes(0xB, 0xAF80, bytes(self.palettes[25]))
        # Fountains BG
        self.rom.write_bytes(0xB, 0xB35E, bytes(self.palettes[26]))
        # Fountains sprites
        self.rom.write_bytes(0xB, 0xB36E, bytes(self.palettes[27]))
        # Dungeon Map view BG, unused in recent hack versions
        self.rom.write_bytes(0xD, 0xBD4B, bytes(self.palettes[28]))
        # Dungeon Map view sprites
        self.rom.write_bytes(0xD, 0xBD5B, bytes(self.palettes[29]))

        # palettes[30] and palettes[31] = colours used to flash the screen (e.g. when casting spells)
        self.rom.write_bytes(0xF, 0xFE7E, bytes(self.palettes[30]))
        self.rom.write_bytes(0xF, 0xFE8E, bytes(self.palettes[31]))

        # palettes[32] and palettes[33] = "end sequence" palettes, used after activating Exodus's altar
        self.rom.write_bytes(0xB, 0x9244, bytes(self.palettes[32]))
        self.rom.write_bytes(0xB, 0x9254, bytes(self.palettes[33]))

        # palettes[34] and palettes[35] = Status screen
        self.rom.write_bytes(0xC, 0x9752, bytes(self.palettes[34]))
        self.rom.write_bytes(0xC, 0x9762, bytes(self.palettes[35]))

        # palettes[36] and palettes[37] = Continent Map View
        self.rom.write_bytes(0xF, 0xFFD0, bytes(self.palettes[36]))
        self.rom.write_bytes(0xF, 0xFFE0, bytes(self.palettes[37]))

        # palettes[38] and palette[39] = Cutscene (Lord British)
        self.rom.write_bytes(0xC, 0x835F, bytes(self.palettes[38]))
        self.rom.write_bytes(0xC, 0x836F, bytes(self.palettes[39]))
