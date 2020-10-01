__author__ = "Fox Cunning"

from dataclasses import dataclass, field
from typing import List

from PIL import Image, ImageTk

from appJar import gui
from debug import log
from palette_editor import PaletteEditor
from rom import ROM
from text_editor import TextEditor


@dataclass(init=True, repr=False)
class Enemy:
    sprite_address: int = 0
    big_sprite: bool = False
    abilities: int = 0
    base_health: int = 0
    base_experience: int = 0
    colours: bytearray = field(default_factory=bytearray)


class EnemyEditor:

    def __init__(self, app: gui, rom: ROM, palette_editor: PaletteEditor):
        self.app: gui = app
        self.rom: ROM = rom
        self.palette_editor: PaletteEditor = palette_editor

        self.encounters: List[bytearray] = []
        self.enemies: List[Enemy] = []

        # Index of the currently selected enemy/encounter
        self.enemy_index: int = -1
        self.encounter_index: int = -1

        self.special_encounters_map: int = 0x14
        self.special_encounters_tile: int = 0x0A

    # --- EnemyEditor.read_encounters_table() ---

    def read_encounters_table(self) -> None:
        # Clear previously cached table
        for e in self.encounters:
            e.clear()
        self.encounters.clear()

        # Read data from ROM
        address = 0xB300

        items = []
        for e in range(9):
            entry = self.rom.read_bytes(0x4, address, 8)
            self.encounters.append(entry)
            text = f"{e:02}:"
            for i in range(8):
                text = text + f" {entry[i]:02X}"
            items.append(text)
            address = address + 8

        self.app.clearListBox("ET_List_Encounters", callFunction=False)
        self.app.updateListBox("ET_List_Encounters", items, select=False, callFunction=False)

        # Read special encounters (by default in Castle Exodus) data
        self.special_encounters_map = self.rom.read_byte(0xF, 0xC40A)

        if self.rom.has_feature("special encounter"):
            self.special_encounters_tile = self.rom.read_byte(0x0, 0xAFEB) & 0x0F

    # --- EnemyEditor.read_enemy_data() ---

    def read_enemy_data(self, text_editor: TextEditor) -> None:
        """
        Reads and caches all enemy data from ROM
        """
        # Clear previous entries first
        self.enemies.clear()

        # A list of items for the editor's widget
        items: List[str] = ["- Select an Enemy -"]

        # Read enemy data from ROM, bank 04
        address = 0xB400
        for e in range(0x1E):
            enemy = Enemy()

            data = self.rom.read_bytes(0x4, address, 8)

            enemy.sprite_address = (data[1] << 8) | (data[0] & 0xFF)
            enemy.big_sprite = False if (data[2] & 0x80) == 0 else True
            enemy.abilities = data[2] & 0x7F
            enemy.base_health = data[3]
            enemy.base_experience = data[4]
            enemy.colours = bytearray([data[5], data[6], data[7]])

            self.enemies.append(enemy)

            # Get enemy's name to display on the option box widget
            name = text_editor.enemy_names[e]

            items.append(f"0x{e:02X} {name}")

            address = address + 8

        # Read Townspeople data following that
        address = 0xB500
        for e in range(0x1F):
            enemy = Enemy()

            # NPC Sprites are taken from bank 03
            enemy.sprite_address = 0x8000 + (0x200 * e)

            enemy.big_sprite = False
            enemy.abilities = 0
            enemy.base_health = self.rom.read_byte(0x4, address)
            enemy.base_experience = self.rom.read_byte(0x4, address + 1)

            enemy.colours = bytearray([0, 0, 0])
            # enemy.colours.append(self.rom.read_byte(0xC, 0xBA08 + e)) no, that is for non-battle sprites
            enemy.colours[0] = self.rom.read_byte(0xF, 0xCED2 + e)

            self.enemies.append(enemy)

            # Get enemy's name to display on the option box widget
            try:
                name = text_editor.enemy_names[e + 0x1E]
            except IndexError:
                name = 'UNDEFINED'

            items.append(f"0x{(e + 0x1E):02X} {name}")

            address = address + 2

        self.app.clearOptionBox("ET_Option_Enemies", callFunction=False)
        self.app.changeOptionBox("ET_Option_Enemies", options=items, callFunction=False)

    # --- EnemyEditor.encounter_info() ---

    def encounter_info(self, **kwargs) -> None:
        """
        Shows the list of enemies for an encounter table.

        Optional Parameters:\n
        - encounter_index: int
        """
        encounter_index = kwargs.get("encounter_index", self.encounter_index)
        self.encounter_index = encounter_index

        if encounter_index < 0:
            # No selection
            return

        # Display encounter type/level
        description = ["Level 1+",
                       "Level 3+",
                       "Level 5+",
                       "Level 5+ (Sea)",
                       "Level 7+",
                       "Level 9+",
                       "Level 9+ (Sea)",
                       "Level 5+ (Ship)",
                       "Special Encounter"]

        self.app.setLabel("ET_Label_Level", description[encounter_index])

        # Data entries

        encounter = self.encounters[encounter_index]

        for e in range(8):
            self.app.setEntry(f"ET_Encounter_{e}", f"0x{encounter[e]:02X}", callFunction=False)

        self.app.setLabel("ET_Label_h3", f"Encounter Table #{encounter_index}")

        # Special encounter data
        if encounter_index == 8:
            self.app.clearOptionBox("ET_Special_Map", callFunction=False)
            self.app.changeOptionBox("ET_Special_Map", options=self.app.getOptionBoxWidget("MapInfo_Select").options,
                                     index=self.special_encounters_map, callFunction=False)
            self.app.enableOptionBox("ET_Special_Map")

            if self.rom.has_feature("special encounter"):
                self.app.enableOptionBox("ET_Special_Tile")
                self.app.setOptionBox("ET_Special_Tile", self.special_encounters_tile, callFunction=False)
        else:
            self.app.disableOptionBox("ET_Special_Map")
            self.app.disableOptionBox("ET_Special_Tile")

    # --- EnemyEditor.enemy_info() ---

    def enemy_info(self, **kwargs) -> None:
        """
        Shows details of the selected enemy

        Optional Parameters:\n
        - enemy_index: int
        """
        enemy_index = kwargs.get("enemy_index", self.enemy_index)

        self.enemy_index = enemy_index

        if enemy_index < 0:
            # No selection
            return

        try:
            enemy = self.enemies[enemy_index]
        except IndexError:
            log(3, f"{self}", f"Invalid enemy ID: {enemy_index}!")
            return

        # Clear previous entries
        self.app.clearEntry("ET_Sprite_Address", callFunction=False)
        self.app.clearEntry("ET_Base_HP", callFunction=False)
        self.app.clearEntry("ET_Base_XP", callFunction=False)

        # This will also call the function that loads and displays the sprites
        self.app.setEntry("ET_Sprite_Address", f"0x{enemy.sprite_address:04X}", callFunction=True)

        self.app.setEntry("ET_Base_HP", f"{enemy.base_health}", callFunction=False)
        self.app.setEntry("ET_Base_XP", f"{enemy.base_experience}", callFunction=False)

        if enemy_index != 0x23:
            self.app.enableEntry("ET_Sprite_Address")
            self.app.showLabel("ET_Label_Colour_1")
            self.app.showLabel("ET_Label_Colour_2")
            self.app.hideLabelFrame("ET_Frame_Floor")

        # The "FLOOR" special encounter has no sprite
        if enemy_index == 0x23:
            self.app.hideLabel("ET_Label_Colour_1")
            self.app.hideLabel("ET_Label_Colour_2")
            self.app.hideLabel("ET_Label_Colour_3")
            self.app.showLabelFrame("ET_Frame_Floor")

            self.app.disableEntry("ET_Sprite_Address")
            self.app.hideOptionBox("ET_Palette_1")
            self.app.hideOptionBox("ET_Palette_2")
            self.app.hideOptionBox("ET_Colour_1")
            self.app.hideOptionBox("ET_Colour_2")
            self.app.hideOptionBox("ET_Colour_3")

        # Colour selection

        elif self.rom.has_feature("2-colour sprites"):
            palette_1 = (enemy.colours[0] >> 2) & 0x3
            palette_2 = enemy.colours[0] & 0x3

            # TODO Change the backgrounds to sprite colours
            self.app.setOptionBox("ET_Palette_1", palette_1, callFunction=False)
            self.app.showOptionBox("ET_Palette_1")

            self.app.setOptionBox("ET_Palette_2", palette_2, callFunction=False)
            self.app.showOptionBox("ET_Palette_2")
            self.app.enableOptionBox("ET_Palette_2")

            self.app.hideOptionBox("ET_Colour_1")
            self.app.hideOptionBox("ET_Colour_2")
            self.app.hideLabel("ET_Label_Colour_3")
            self.app.hideOptionBox("ET_Colour_3")

            self.app.setCheckBox("ET_Big_Sprite", enemy.big_sprite, callFunction=False)
            self.app.enableCheckBox("ET_Big_Sprite")

        elif enemy_index < 0x1E:
            # Vanilla game, monsters
            self.app.setOptionBox("ET_Colour_1", index=enemy.colours[0], callFunction=False)
            colour = list(self.palette_editor.get_colour(enemy.colours[0]))
            self.app.optionBox("ET_Colour_1", bg=f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}")
            self.app.showOptionBox("ET_Colour_1")

            self.app.setOptionBox("ET_Colour_2", index=enemy.colours[1], callFunction=False)
            colour = list(self.palette_editor.get_colour(enemy.colours[1]))
            self.app.optionBox("ET_Colour_2", bg=f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}")
            self.app.showOptionBox("ET_Colour_2")

            self.app.setOptionBox("ET_Colour_3", index=enemy.colours[2], callFunction=False)
            colour = list(self.palette_editor.get_colour(enemy.colours[2]))
            self.app.optionBox("ET_Colour_3", bg=f"#{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}")
            self.app.showOptionBox("ET_Colour_3")
            self.app.showLabel("ET_Label_Colour_3")

            self.app.hideOptionBox("ET_Palette_1")
            self.app.hideOptionBox("ET_Palette_2")

        else:
            # Vanilla game, townspeople
            # TODO Change the backgrounds to sprite colours
            self.app.setOptionBox("ET_Palette_1", enemy.colours[0], callFunction=False)
            self.app.showOptionBox("ET_Palette_1")

            self.app.showOptionBox("ET_Palette_2")
            self.app.disableOptionBox("ET_Palette_2")

            self.app.hideOptionBox("ET_Colour_1")
            self.app.hideOptionBox("ET_Colour_2")
            self.app.hideLabel("ET_Label_Colour_3")
            self.app.hideOptionBox("ET_Colour_3")

        # 2x2 / 4x4 sprite checkbox
        if enemy_index < 0x1E:
            self.app.setCheckBox("ET_Big_Sprite", enemy.big_sprite, callFunction=False)
            self.app.enableCheckBox("ET_Big_Sprite")
        else:
            self.app.setCheckBox("ET_Big_Sprite", False, callFunction=False)
            self.app.disableCheckBox("ET_Big_Sprite")
            
        # Load and display battle sprite
        self._load_sprite()

        # Display special abilities

        self.app.setOptionBox("ET_Ability", enemy.abilities, callFunction=False)

    # --- EnemyEditor.change_sprite() ---

    def change_sprite(self, **kwargs) -> None:
        """
        Sets a new address for an enemy

        Optional parameters:\n
        - sprite_address: int
        - big_sprite: bool
        - colours: bytearray
        - enemy_index: int
        """
        enemy_index = kwargs.get("enemy_index", self.enemy_index)

        if enemy_index < 0:
            # No selection
            return

        big_sprite = kwargs.get("big_sprite", self.enemies[enemy_index].big_sprite)
        sprite_address = kwargs.get("sprite_address", self.enemies[enemy_index].sprite_address)
        colours = kwargs.get("colours", self.enemies[enemy_index].colours)

        self.enemies[enemy_index].big_sprite = big_sprite
        self.enemies[enemy_index].sprite_address = sprite_address
        self.enemies[enemy_index].colours = colours
        self._load_sprite()

    # --- EnemyEditor.change_stats() ---

    def change_stats(self, **kwargs) -> None:
        """
        Changes the base HP / XP of an enemy

        Optional parameters:\n
        - enemy_index: int\n
        - base_hp: int\n
        - base_xp: int\n
        - ability: int
        """
        enemy_index = kwargs.get("enemy_index", self.enemy_index)

        if enemy_index < 0:
            return

        base_hp = kwargs.get("base_hp", None)
        base_xp = kwargs.get("base_xp", None)
        ability = kwargs.get("ability", None)

        if base_hp is not None:
            self.enemies[enemy_index].base_health = base_hp

        if base_xp is not None:
            self.enemies[enemy_index].base_experience = base_xp

        if ability is not None:
            self.enemies[enemy_index].abilities = ability

    # --- EnemyEditor.change_encounter() ---

    def change_encounter(self, entry_index: int, encounter_id: int, **kwargs) -> None:
        """
        Changes an entry in an encounter table.
        Optional Parameters:\n
        - encounter_index: int

        Parameters
        ----------
        entry_index: int
        encounter_id: int
        """
        encounter_index = kwargs.get("encounter_index", self.encounter_index)

        try:
            encounter = self.encounters[encounter_index]
            encounter[entry_index] = encounter_id

        except IndexError:
            self.app.errorBox("Edit Encounter", f"Invalid selection:\nEntry: #{entry_index}\n"
                                                f"Encounter ID: {encounter_id}\nTable: #{encounter_index}")
            return

        # Update list widget
        items = []
        for e in range(9):
            entry = self.encounters[e]
            text = f"{e:02}:"
            for i in range(8):
                text = text + f" {entry[i]:02X}"
            items.append(text)

        self.app.clearListBox("ET_List_Encounters", callFunction=False)
        self.app.updateListBox("ET_List_Encounters", items, select=False, callFunction=False)

    # --- EnemyEditor._load_sprite() ---

    def _load_sprite(self, **kwargs) -> None:
        """
        Reads sprite data from ROM for the currently selected enemy, and displays the sprite on the Canvas widget

        Optional Parameters:\n
        - sprite_address: int
        """
        if self.enemy_index < 0:
            # No enemy selected
            return

        # Clear previous sprite
        self.app.clearCanvas("ET_Canvas_Sprite")

        enemy = self.enemies[self.enemy_index]
        bank = 4 if self.enemy_index < 0x1E else 3

        sprite_address = kwargs.get("sprite_address", enemy.sprite_address)

        # The "FLOOR" special encounter has no sprite (data is taken from RAM, all zeroes)
        if self.enemy_index == 0x23:
            return

        if self.rom.has_feature("2-colour sprites"):
            # 2 palettes, one for the top sprites, one for the bottom
            top_colours: List[int] = []
            bottom_colours: List[int] = []

            # Top palette

            palette_index = (enemy.colours[0] >> 2) << 2

            for c in range(palette_index, palette_index + 4):
                try:
                    colour_index = self.palette_editor.palettes[1][c]
                except IndexError:
                    log(2, f"{self}", f"Index out of range for palette[1]: {c}")
                    colour_index = 0
                colour = bytearray(self.palette_editor.get_colour(colour_index))
                top_colours.append(colour[0])
                top_colours.append(colour[1])
                top_colours.append(colour[2])

            # Bottom palette

            palette_index = (enemy.colours[0] & 0x3) << 2

            for c in range(palette_index, palette_index + 4):
                try:
                    colour_index = self.palette_editor.palettes[1][c]
                except IndexError:
                    log(2, f"{self}", f"Index out of range for palette[1]: {c}")
                    colour_index = 0
                colour = bytearray(self.palette_editor.get_colour(colour_index))
                bottom_colours.append(colour[0])  # Red
                bottom_colours.append(colour[1])  # Green
                bottom_colours.append(colour[2])  # Blue

        else:
            # Single palette for vanilla game
            top_colours: List[int] = [0x0F, 0x0F, 0x0F]
            for c in range(3):
                colour = list(self.palette_editor.get_colour(enemy.colours[0]))
                top_colours.append(colour[0])
                top_colours.append(colour[1])
                top_colours.append(colour[2])
            bottom_colours = top_colours

        if enemy.big_sprite:
            # 32x32 meta-sprite
            sprite = Image.new('RGBA', (32, 32), 0xC0C0C0)

            # Top-Left
            sprite.paste(self.rom.read_sprite(bank, sprite_address, top_colours).convert('RGBA'), (0, 0))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x10, top_colours).convert('RGBA'), (0, 8))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x20, top_colours).convert('RGBA'), (8, 0))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x30, top_colours).convert('RGBA'), (8, 8))

            sprite_address = sprite_address + 0x80

            # Bottom-Left
            sprite.paste(self.rom.read_sprite(bank, sprite_address, bottom_colours).convert('RGBA'), (0, 16))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x10, bottom_colours).convert('RGBA'), (0, 24))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x20, bottom_colours).convert('RGBA'), (8, 16))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x30, bottom_colours).convert('RGBA'), (8, 24))

            sprite_address = sprite_address + 0x80

            # Top-Right
            sprite.paste(self.rom.read_sprite(bank, sprite_address, top_colours).convert('RGBA'), (16, 0))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x10, top_colours).convert('RGBA'), (16, 8))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x20, top_colours).convert('RGBA'), (24, 0))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x30, top_colours).convert('RGBA'), (24, 8))

            sprite_address = sprite_address + 0x80

            # Bottom-Right
            sprite.paste(self.rom.read_sprite(bank, sprite_address, bottom_colours).convert('RGBA'), (16, 16))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x10, bottom_colours).convert('RGBA'), (16, 24))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x20, bottom_colours).convert('RGBA'), (24, 16))
            sprite.paste(self.rom.read_sprite(bank, sprite_address + 0x30, bottom_colours).convert('RGBA'), (24, 24))

            self.app.addCanvasImage("ET_Canvas_Sprite", 16, 16, ImageTk.PhotoImage(sprite))

        else:
            # 16x16 meta-sprite
            sprite = Image.new('RGBA', (16, 16), 0xC0C0C0)

            # Top-Left pattern
            image = self.rom.read_sprite(bank, sprite_address, top_colours)
            sprite.paste(image.convert('RGBA'), (0, 0))

            # Bottom-Left pattern
            image = self.rom.read_sprite(bank, sprite_address + 0x10, bottom_colours)
            sprite.paste(image.convert('RGBA'), (0, 8))

            # Top-Right pattern
            image = self.rom.read_sprite(bank, sprite_address + 0x20, top_colours)
            sprite.paste(image.convert('RGBA'), (8, 0))

            # Bottom-Right pattern
            image = self.rom.read_sprite(bank, sprite_address + 0x30, bottom_colours)
            sprite.paste(image.convert('RGBA'), (8, 8))

            self.app.addCanvasImage("ET_Canvas_Sprite", 16, 16, ImageTk.PhotoImage(sprite))

    # --- EnemyEditor.update_names() ---

    def update_names(self, text_editor: TextEditor) -> None:
        """
        Updates the names shown in the list of enemies.

        Parameters
        ----------
        text_editor: TextEditor
        """
        # A list of items for the editor's widget
        items: List[str] = ["- Select an Enemy -"]

        # Monsters
        for e in range(0x1F):
            name = text_editor.enemy_names[e]
            items.append(f"0x{e:02X} {name}")

        # Townspeople
        for e in range(0x1E):
            try:
                name = text_editor.enemy_names[e + 0x1E]
            except IndexError:
                name = 'UNDEFINED'

            items.append(f"0x{(e + 0x1E):02X} {name}")

        self.app.clearOptionBox("ET_Option_Enemies", callFunction=False)
        self.app.changeOptionBox("ET_Option_Enemies", options=items, callFunction=False)

    # --- EnemyEditor.save() ---

    def save(self, sync_npc_sprites: bool = False) -> None:
        """
        Saves changes to enemies and enemy tables to ROM
        """
        # Save enemy data

        monsters_address = 0xB400
        npcs_address = 0xB500
        for e in range(len(self.enemies)):
            enemy = self.enemies[e]

            if e < 0x1E:
                # Monsters
                self.rom.write_word(0x4, monsters_address, enemy.sprite_address)
                value = enemy.abilities
                if enemy.big_sprite:
                    value = value | 0x80
                self.rom.write_byte(0x4, monsters_address + 2, value)
                self.rom.write_byte(0x4, monsters_address + 3, enemy.base_health)
                self.rom.write_byte(0x4, monsters_address + 4, enemy.base_experience)
                self.rom.write_bytes(0x4, monsters_address + 5, enemy.colours)

                monsters_address = monsters_address + 8

            else:
                # Townspeople
                self.rom.write_byte(0x3, npcs_address, enemy.base_health)
                self.rom.write_byte(0x3, npcs_address + 1, enemy.base_experience)
                npcs_address = npcs_address + 2

                # Save NPC battle colours
                offset = e - 0x1E
                self.rom.write_byte(0xF, 0xCED2 + offset, enemy.colours[0])

                # If requested, keep the same colours for map sprites
                if sync_npc_sprites:
                    self.rom.write_byte(0xC, 0xBA08 + offset, enemy.colours[0])

        # Save encounter tables

        address = 0xB300
        for encounter in self.encounters:
            for e in range(8):
                self.rom.write_byte(0x4, address, encounter[e])
                address = address + 1

        # Save special encounter (Castle Exodus' Chest) data

        self.rom.write_byte(0xF, 0xC40A, self.special_encounters_map)

        if self.rom.has_feature("special encounter"):
            self.rom.write_byte(0x0, 0xAFEB, self.special_encounters_tile)

        self.app.setStatusbar("Enemy/Encounter data saved.")
