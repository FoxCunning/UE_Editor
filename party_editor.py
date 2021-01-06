__author__ = "Fox Cunning"

import configparser
import glob
import os
import colour
from dataclasses import dataclass, field
from typing import List

from PIL import Image, ImageTk

from appJar import gui
from debug import log
from map_editor import MapEditor
from palette_editor import PaletteEditor
from rom import ROM
from routines import Routine, AttributeCheck, Parameter
from text_editor import TextEditor, exodus_to_ascii, ascii_to_exodus


# noinspection SpellCheckingInspection
class PartyEditor:
    # --- PartyEditor.PreMade class ---
    @dataclass(init=True, repr=False)
    class PreMade:
        """
        A helper class used to store data used for pre-made characters.
        """
        name: str = ""
        race: int = 0
        profession: int = 0
        attributes: list = field(default_factory=list)

    def __init__(self, app: gui, rom: ROM, text_editor: TextEditor, palette_editor: PaletteEditor,
                 map_editor: MapEditor):
        self.app: gui = app
        self.rom: ROM = rom
        self.text_editor: TextEditor = text_editor
        self.map_editor: MapEditor = map_editor
        self.palette_editor: PaletteEditor = palette_editor
        self.current_window: str = ""

        # We store values that can be modified and written back to ROM within this class
        self.race_names: List[str] = []
        self.profession_names: List[str] = []
        self.attribute_names: List[str] = ["STR", "DEX", "INT", "WIS"]
        self.weapon_names: List[str] = []
        self.armour_names: List[str] = []
        self.mark_names: List[str] = ["FORCE", "FIRE", "SNAKE", "KING"]
        self.spell_names_0: List[str] = []  # Cleric spells
        self.spell_names_1: List[str] = []  # Wizard spells
        self.attribute_checks: List[AttributeCheck] = []
        # Spells (0-31) and common routines (32-...)
        # Or Tools (0-9)
        self.routines: List[Routine] = []
        # List of spell definition file names
        self.routine_definitions: List[str] = []

        # Number of selectable races for character creation
        self.selectable_races: int = 5

        # Weapon type table at $D189 (16 entries, 1 byte per entry)
        self.weapon_type: bytearray = bytearray()

        self.best_weapon: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.best_armour: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

        self.thief_bonus: bytearray = bytearray()

        self.hp_base: int = 75
        self.hp_bonus: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        # Gender will be determined either by Profession or by Race
        self.gender_by_profession: bool = True
        self.gender_char: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.primary_attributes = [[0, 0],
                                   [0, 0],
                                   [0, 0],
                                   [0, 0],
                                   [0, 0],
                                   [0, 0],
                                   [0, 0],
                                   [0, 0],
                                   [0, 0],
                                   [0, 0],
                                   [0, 0]]
        # Max starting attribute values for each race
        self.start_attributes = [[25, 25, 25, 25],
                                 [25, 25, 25, 25],
                                 [25, 25, 25, 25],
                                 [25, 25, 25, 25],
                                 [25, 25, 25, 25]]
        # Max value of attributes for each race
        self.max_attributes = [[75, 75, 75, 75],
                               [75, 75, 75, 75],
                               [75, 75, 75, 75],
                               [75, 75, 75, 75],
                               [75, 75, 75, 75]]
        # Max MP assignment for each profession
        # Default: 0 = WIS, 1 = INT, 2 = WIS/2, 3 = INT/2, 4 = MAX(INT/2, WIS/2), 5 = MIN(INT/2, WIS/2), 6 = Zero
        # Remastered:   0 = WIS, 1 = INT, 2 = WIS/2, 3 = INT/2, 4 = WIS*3/4, 5 = (INT+WIS)/2, 6 = INT*3/4,
        #               7 = (INT+WIS)/4, 8 = (Fixed Value)
        self.max_mp: bytearray = bytearray([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        # Two bit flags per profession, determining which spells they can cast (none/clr/wiz/both)
        self.caster_flags: bytearray = bytearray([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        # Colours for Status Screen / Character Creation Menu
        self.colour_indices: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        # Colours for map/battle sprites
        self.sprite_colours: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        # Number of selectable professions (11 by default)
        self.selectable_professions: int = 11

        # ID of races/professions used in the character creation menus
        self.menu_string_id: int = 0

        # An array containing pre-made character data
        self.pre_made: List[PartyEditor.PreMade] = []

        # Currently selected race/profession/weapon/spell etc. (depending on current window)
        self.selected_index: int = -1

        # Should we ignore warnings or show a messagebox?
        self._ignore_warnings: bool = False

        # Set to True every time there is a change that needs to be saved
        self._unsaved_changes: bool = False

    # --- PartyEditor.error() ---

    def error(self, message: str):
        log(2, f"{self.__class__.__name__}", message)

    # --- PartyEditor.warning() ---

    def warning(self, message: str):
        log(3, f"{self.__class__.__name__}", message)

    # --- PartyEditor.info() ---

    def info(self, message: str):
        log(4, f"{self.__class__.__name__}", message)

    # --- PartyEditor.show_races_window() ---

    def show_window(self, window_name: str) -> None:
        """
        Shows a sub-window for a specific editor.

        Parameters
        ----------
        window_name: str
            Valid options: "Races", "Professions", "Pre-Made", "Special Abilities", "Magic", "Weapons", "Commands".
        """
        # self.app.emptySubWindow("Party_Editor") Now performed after closing the window
        self.selected_index = -1

        self._unsaved_changes = False

        if window_name == "Races":
            self._create_races_window()

        elif window_name == "Professions":
            self._create_professions_window()

        elif window_name == "Pre-Made":
            if self.rom.has_feature("enhanced party") is False:
                self.app.errorBox("Party Editor", "The pre-made character editor is only available on the Remastered " +
                                  "version of the ROM.")
                return

            else:
                self._create_pre_made_window()

        elif window_name == "Special Abilities":
            self._create_special_window()

        elif window_name == "Magic":
            self._create_magic_window()

        elif window_name == "Items":
            self._create_items_window()

        elif window_name == "Weapons":
            self._create_weapons_window()

        else:
            self.warning(f"Unimplemented: {window_name}.")
            return

        self.current_window = window_name

        self.app.showSubWindow("Party_Editor")

    # --- PartyEditor._create_races_window() ---

    def _create_races_window(self) -> None:
        # Build a list of race names, reading them from ROM
        # We'll read the uncompressed text used for the Status screen, by default at 0C:A564
        race_names: List[str] = ["- Race -"]

        self._read_race_names()
        race_names = race_names + self.race_names

        race_text = ""
        for r in self.race_names:
            race_text = race_text + r + "\n"

        # Read attribute names
        self._read_attribute_names()

        # Check whether gender depends on race or profession, default code in bank 0xD:
        # A637    LDY #$06                 ;Read character's Profession
        # A639    LDA ($99),Y
        # A63B    TAY
        # A63C    LDA $A727,Y              ;Get Gender letter tile index
        # A63F    STA $0580,X
        if self.rom.read_byte(0xD, 0xA638) == 0x6:
            self.gender_by_profession = True
        else:
            self.gender_by_profession = False

        # Read gender data
        for i in range(11):
            self.gender_char[i] = self.rom.read_byte(0xD, 0xA727 + i)

        if self.rom.has_feature("enhanced party"):
            # Read max starting attributes
            # Table at 0C:BFD0
            address = 0xBFD0
            for r in range(5):
                for i in range(4):
                    self.start_attributes[r][i] = self.rom.read_byte(0xC, address)
                    address = address + 1
        else:
            for r in range(5):
                for i in range(4):
                    self.start_attributes[r][i] = 25

        # Read max attribute values
        # Table at 0D:9780, values are in the order: INT, WIS, STR, DEX for some reason
        address = 0x9780
        for r in range(5):
            self.max_attributes[r][0] = self.rom.read_byte(0xD, address + 2)
            self.max_attributes[r][1] = self.rom.read_byte(0xD, address + 3)
            self.max_attributes[r][2] = self.rom.read_byte(0xD, address)
            self.max_attributes[r][3] = self.rom.read_byte(0xD, address + 1)
            address = address + 4

        # Number of selectable races
        # We use the routine at 0C:8D76 which creates the menu
        # Add 1 because that is the index of the last possible selection (0-based)
        self.selectable_races = self.rom.read_byte(0xC, 0x8EAD) + 1

        # Read string ID from ROM, bank 0xC
        # 8DB8    LDA #$0A
        # 8DBA    STA $30
        # 8DBC    JSR DrawTextForPreGameMenu
        self.menu_string_id = self.rom.read_byte(0xC, 0x8DB9)

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(340, 288)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", row=0, column=0, padding=[4, 0], colspan=2,
                                sticky="NEW", stretch="ROW"):
                self.app.button("PE_Apply", name="Apply", value=self._races_input, image="res/floppy.gif",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                tooltip="Discard Changes and Close Window", row=0, column=1)
                self.app.button("PE_Update_Race_Names", name="Reload", value=self._races_input, image="res/reload.gif",
                                tooltip="Update Race Names", row=0, column=3, sticky="E")

            with self.app.frame("PE_Frame_Races", row=1, column=0, stretch="BOTH", sticky="NEWS", padding=[4, 2],
                                bg=colour.PALE_BLUE):
                # Row 0
                self.app.label("PE_Label_r0", "Selectable Races:", row=0, column=0, font=10)
                self.app.spinBox("PE_Spin_Races", list(range(5, 0, -1)), width=3, row=0, column=1,
                                 change=self._races_input, font=10)
                self.app.setSpinBox("PE_Spin_Races", self.selectable_races, callFunction=False)

                # Row 1
                self.app.label("PE_Label_r1", "Edit Race:", row=1, column=0, font=10)
                self.app.optionBox("PE_Option_Race", race_names, row=1, column=1, change=self._races_input, font=10)

                # Row 2
                self.app.label("PE_Label_r2", "Max Attribute Values:", row=2, column=0, colspan=2, font=10)

                # Row 3
                with self.app.frame("PE_Frame_Max_Attributes", row=3, column=0, colspan=2, padding=[8, 2]):
                    # Row 0 - Names
                    self.app.entry("PE_Attribute_Name_0", self.attribute_names[0], width=4, row=0, column=0)
                    self.app.entry("PE_Attribute_Name_1", self.attribute_names[1], width=4, row=0, column=1)
                    self.app.entry("PE_Attribute_Name_2", self.attribute_names[2], width=4, row=0, column=2)
                    self.app.entry("PE_Attribute_Name_3", self.attribute_names[3], width=4, row=0, column=3)
                    # Row 1 - Max Start Values
                    self.app.entry("PE_Start_Attribute_0", 0, change=self._races_input, width=4, row=1, column=0)
                    self.app.entry("PE_Start_Attribute_1", 0, change=self._races_input, width=4, row=1, column=1)
                    self.app.entry("PE_Start_Attribute_2", 0, change=self._races_input, width=4, row=1, column=2)
                    self.app.entry("PE_Start_Attribute_3", 0, change=self._races_input, width=4, row=1, column=3)
                    # Row 2 - Max Total Value
                    self.app.entry("PE_Max_Attribute_0", 0, change=self._races_input, width=4, row=2, column=0)
                    self.app.entry("PE_Max_Attribute_1", 0, change=self._races_input, width=4, row=2, column=1)
                    self.app.entry("PE_Max_Attribute_2", 0, change=self._races_input, width=4, row=2, column=2)
                    self.app.entry("PE_Max_Attribute_3", 0, change=self._races_input, width=4, row=2, column=3)

                # Row 4
                with self.app.frame("PE_Frame_Gender_By_Race", row=4, column=0, colspan=2, padding=[8, 4]):
                    # Row 0, Col 0-2
                    self.app.checkBox("PE_Gender_By_Race", text="Gender based on Race",
                                      value=not self.gender_by_profession, change=self._races_input,
                                      row=0, column=0, colspan=3, font=10)
                    # Row 1, Col 0
                    self.app.label("PE_Label_Race_Gender", "Gender Chr.:", row=1, column=0, font=10)
                    # Row 1, Col 1
                    self.app.entry("PE_Gender_Character", "0x00", width=4, fg=colour.BLACK, font=10,
                                   change=self._races_input, row=1, column=1)
                    # Row 1, Col 2
                    self.app.canvas("PE_Canvas_Gender", width=16, height=16, bg=colour.BLACK, map=None, sticky="W",
                                    row=1, column=2)

            # Right Column
            with self.app.frame("PE_Frame_Race_Names", row=1, column=1, padding=[4, 2]):
                self.app.label("PE_Label_Race_Names", value="Race Names:", row=0, column=0, font=10)
                self.app.textArea("PE_Race_Names", value=race_text, change=self._races_input, row=1, column=0,
                                  width=12, height=7, fg=colour.BLACK, font=10)

                # Race names list string index and edit button
                with self.app.frame("PE_Frame_Menu_String", row=3, column=0, sticky="NEW", padding=[4, 2],
                                    bg=colour.PALE_TEAL):
                    self.app.button("PE_Edit_Menu_String", value=self._races_input, name="Edit Text",
                                    image="res/edit-dlg-small.gif", sticky="NW", width=16, height=16, row=0, column=0)
                    self.app.label("PE_Menu_String_Label", value="ID:", sticky="NEWS", row=0, column=1, font=10)
                    self.app.entry("PE_Menu_String_Id", value=f"0x{self.menu_string_id:02X}",
                                   change=self._races_input,
                                   width=5, sticky="NES", row=0, column=2, font=10)

        # Disable gender character widgets if gender depends on profession
        if self.gender_by_profession:
            self.app.disableEntry("PE_Gender_Character")
        else:
            self.app.enableEntry("PE_Gender_Character")

        # Disable max starting attribute per race if ROM does not support that
        if self.rom.has_feature("enhanced party"):
            for i in range(4):
                self.app.enableEntry(f"PE_Start_Attribute_{i}")
        else:
            for i in range(4):
                self.app.disableEntry(f"PE_Start_Attribute_{i}")

    # --- PartyEditor._create_professions_window() ---

    def _create_professions_window(self) -> None:
        # Read profession names from ROM
        # We'll read the uncompressed text used for the Status screen, by default at 0C:A581
        professions_list: List[str] = ["- Profession -"]
        profession_names: str = ""

        # Read and decode attribute names
        self._read_attribute_names()

        # Read profession names from ROM
        self._read_profession_names()
        # List for option box
        professions_list = professions_list + self.profession_names
        # String for text area
        for p in self.profession_names:
            profession_names = profession_names + p + '\n'
        profession_names = profession_names.strip('\n')

        self._read_weapon_armour_names()

        # Read caster flags from ROM:
        self.caster_flags = self.rom.read_bytes(0xF, 0xD455, 11)

        # Check whether gender depends on race or profession, default code in bank 0xD:
        # A637    LDY #$06                 ;Read character's Profession
        # A639    LDA ($99),Y
        # A63B    TAY
        # A63C    LDA $A727,Y              ;Get Gender letter tile index
        # A63F    STA $0580,X
        if self.rom.read_byte(0xD, 0xA638) == 0x6:
            self.gender_by_profession = True
        else:
            self.gender_by_profession = False

        # Primary Attributes for each profession
        for i in range(11):
            # 2 bytes per entry: multiply index x2 (or shift 1 bit left)
            address = 0x97D6 + (i << 1)
            primary_0 = self.rom.read_byte(0xD, address) - 7
            primary_1 = self.rom.read_byte(0xD, address + 1) - 7
            self.primary_attributes[i] = [primary_0, primary_1]

        # Colours for profession graphics
        colours_list = [0, 1, 2, 3]
        if self.rom.has_feature("new profession gfx"):
            colours_list.append(4)
            colours_list.append(5)
            colours_list.append(6)

        for i in range(11):
            # BG Profession Graphics colours
            self.colour_indices[i] = self.rom.read_byte(0xC, 0x9736 + i)
            # Sprite colours
            self.sprite_colours[i] = self.rom.read_byte(0xF, 0xEF5A + i)

        # Read best armour/weapons
        for i in range(11):
            # We use the table used for the equip screen, but when saving we will also copy it to the "shop" table
            self.best_weapon[i] = self.rom.read_byte(0xC, 0xA23B + i)
            self.best_armour[i] = self.rom.read_byte(0xC, 0xA246 + i)

        # Read gender data
        for i in range(11):
            self.gender_char[i] = self.rom.read_byte(0xD, 0xA727 + i)

        # Read HP gain data
        if self.rom.has_feature("enhanced party"):
            self.hp_base = self.rom.read_byte(0xD, 0x8872)
            for i in range(11):
                self.hp_bonus[i] = self.rom.read_byte(0xD, 0x889F + i)

        else:
            self.hp_base = self.rom.read_byte(0xD, 0x8870)
            bonus = self.rom.read_byte(0xD, 0x8866)
            for i in range(11):
                self.hp_bonus[i] = bonus

        # MP options
        _int = self.attribute_names[2]
        _wis = self.attribute_names[3]
        if self.rom.has_feature("enhanced party"):
            mp_options = [_wis, f"{_wis} / 2", f"{_wis} x 3 / 4", _int, f"{_int} / 2", f"{_int} x 3 / 4",
                          f"({_wis} + {_int}) / 2", f"({_wis} + {_int}) / 4", "Fixed Value", ]
        else:
            mp_options = [_wis, _int, f"{_wis} / 2", f"{_int} / 2", f"MAX({_wis} / 2, {_int} / 2)",
                          f"MIN({_wis} / 2, {_int} / 2)", "Fixed Value"]

        # Read "thieving" bonus table
        self.thief_bonus = self.rom.read_bytes(0xF, 0xDEAA, 11)

        # Read number of selectable professions
        # We use the routine at 0C:8D76 which creates the race/profession menu for character creation
        # This value is the 0-based index of the last possible selection, so we add 1
        self.selectable_professions = self.rom.read_byte(0xC, 0x8ECB) + 1

        # Read string ID from ROM, bank 0xC
        # 8F41    LDA #$0D
        # 8F43    STA $30
        # 8F45    JSR DrawTextForPreGameMenu
        self.menu_string_id = self.rom.read_byte(0xC, 0x8F42)

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(600, 460)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", row=0, column=0, colspan=3,
                                padding=[4, 2], sticky="NEW", stretch="BOTH"):
                self.app.button("PE_Apply", name="Apply", value=self._professions_input, image="res/floppy.gif",
                                sticky="NE",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                sticky="NW",
                                tooltip="Discard Changes and Close Window", row=0, column=1)
                self.app.button("PE_Update_Profession_Names", name="Reload", value=self._professions_input,
                                image="res/reload.gif", tooltip="Update Profession Names", row=0, column=3, sticky="E")

            # Left Column
            with self.app.frame("PE_Frame_Left", row=1, column=0, stretch="COLUMN", sticky="NEW", padding=[4, 2],
                                bg=colour.PALE_BLUE):
                # --- Profession selection ---

                # Row 0 Col 0
                self.app.label("PE_Label_Professions", "Selectable Professions:", sticky="E",
                               row=0, column=0, font=10)
                # Row 0 Col 1
                self.app.spinBox("PE_Spin_Professions", list(range(11, 0, -1)),
                                 change=self._professions_input, width=3, sticky="W", row=0, column=1, font=10)
                self.app.setSpinBox("PE_Spin_Professions", self.selectable_professions, callFunction=False)
                # Row 1 Col 0, 1
                self.app.optionBox("PE_Option_Profession", professions_list, change=self._professions_input,
                                   row=1, column=0, colspan=2, font=10)

                with self.app.frame("PE_Sub_Left", row=2, column=0):
                    # --- Status / Character creation graphics and map / battle sprite ---

                    # Row 2 Col 0, 1
                    with self.app.frame("PE_Frame_Graphics", row=0, column=0, colspan=2):
                        # Row 0 Col 0
                        self.app.canvas("PE_Canvas_Profession", Map=None, width=48, height=48, bg=colour.BLACK,
                                        sticky="W", row=0, column=0)
                        # Row 0 Col 1
                        self.app.canvas("PE_Canvas_Sprite", Map=None, width=32, height=32, bg=colour.MEDIUM_GREY,
                                        sticky="W", row=0, column=1)
                        # Row 1 Col 0
                        self.app.label("PE_Label_Colours", "Colours:", row=1, column=0, font=10)
                        # Row 1 Col 1
                        self.app.label("PE_Label_Palettes", "Palettes:", row=1, column=1, font=10)
                        # Row 2 Col 0
                        self.app.optionBox("PE_Profession_Colours", colours_list, change=self._professions_input,
                                           sticky="NW", row=2, column=0, font=10)
                        # Row 2 Col 1
                        self.app.optionBox("PE_Sprite_Palette_Top", list(range(0, 4)),
                                           change=self._professions_input,
                                           sticky="NW", row=2, column=1, font=10)
                        # Row 3 Col 1
                        self.app.optionBox("PE_Sprite_Palette_Bottom", list(range(0, 4)),
                                           change=self._professions_input, sticky="NW", row=3, column=1, font=10)

                    # --- Equipment ---

                    # Row 3 Col 0, 1
                    with self.app.frame("PE_Frame_Gear", padding=[4, 2], row=1, column=0, colspan=2):
                        # Row 0
                        self.app.label("PE_Label_Best_Weapon", "Best Weapon:", row=0, column=0, font=10)
                        self.app.optionBox("PE_Option_Weapon", self.weapon_names, change=self._professions_input,
                                           width=10, row=0, column=1, font=10)
                        # Row 1
                        self.app.label("PE_Label_Best_Armour", "Best Armour:", row=1, column=0, font=10)
                        self.app.optionBox("PE_Option_Armour", self.armour_names, change=self._professions_input,
                                           width=10, row=1, column=1, font=10)

                    # --- Gender ---

                    # Row 4 Col 0, 1
                    with self.app.frame("PE_Frame_Gender", padding=[4, 2], row=2, column=0, colspan=2):
                        # Row 0, Col 0, 1, 2
                        self.app.checkBox("PE_Check_Gender", text="Gender based on Profession",
                                          value=self.gender_by_profession, change=self._professions_input,
                                          row=0, column=0, colspan=3, font=10)
                        # Row 1, Col 0
                        self.app.label("PE_Label_Gender", "Gender Chr.:", row=1, column=0, font=10)
                        # Row 1, Col 1
                        self.app.entry("PE_Gender_Character", "0x00", width=4, fg=colour.BLACK, font=9,
                                       change=self._professions_input, row=1, column=1)
                        # Row 1, Col 2
                        self.app.canvas("PE_Canvas_Gender", width=16, height=16, bg=colour.BLACK,
                                        map=None, sticky="W", row=1, column=2)

                    # --- Max MP ---

                    with self.app.frame("PE_Frame_MP", padding=[4, 2], row=3, column=0, colspan=2):
                        # Max MP / Fixed Value
                        self.app.label("PE_Label_MP", "Max MP:", sticky="NE", row=0, column=0, font=11)
                        self.app.optionBox("PE_Option_MP", mp_options, sticky="NW", row=0, column=1, font=10)
                        self.app.label("PE_Label_Fixed_MP", "Fixed Value:", sticky="NE", row=1, column=0, font=11)
                        self.app.entry("PE_Fixed_MP", "0", width=4, sticky="NW", row=1, column=1, font=10)
                        # Custom code / override
                        self.app.label("PE_Label_Custom", "This ROM uses custom code for Max MP.",
                                       row=2, column=0, colspan=2, font=11, fg=colour.MEDIUM_RED)
                        self.app.checkBox("PE_Overwrite_MP", name="Overwrite custom code",
                                          change=self._professions_input,
                                          row=3, column=0, colspan=2, font=10)

            # Middle Column
            with self.app.frame("PE_Sub_Right", row=1, column=1, padding=[4, 2], sticky="NEW", stretch="COLUMN",
                                bg=colour.PALE_NAVY):
                # --- Primary Attributes ---

                # Col 0, 1
                with self.app.frame("PE_Frame_Primary_Attributes", padding=[4, 2], row=0, column=0,
                                    stretch="ROW", sticky="NEW"):
                    # Row 0, Col 0, 1
                    self.app.label("PE_Label_Primary_Attributes", "Primary Attributes:", sticky="SEW",
                                   row=0, column=0, colspan=2, font=11)
                    # Row 1, Col 0
                    self.app.optionBox("PE_Primary_0", self.attribute_names, change=self._professions_input,
                                       row=1, column=0, sticky="NEW", font=10)
                    # Row 1, Col 1
                    self.app.optionBox("PE_Primary_1", self.attribute_names, change=self._professions_input,
                                       row=1, column=1, sticky="NEW", font=10)

                # --- HP Gain ---

                with self.app.frame("PE_Frame_HP", row=1, column=0, stretch="ROW", sticky="NEW",
                                    padding=[4, 4]):
                    # Row 0
                    self.app.label("PE_Label_HP", "HP gain:", row=0, column=0, colspan=4, sticky="SEW", font=10)
                    # Row 1
                    self.app.entry("PE_HP_Base", 0, width=3, fg=colour.BLACK, font=10,
                                   change=self._professions_input,
                                   row=1, column=0, sticky="NEW")
                    self.app.label("PE_Label_Plus", "+ (", row=1, column=1, font=10)
                    self.app.entry("PE_HP_Bonus", 0, width=3, fg=colour.BLACK, font=10,
                                   change=self._professions_input,
                                   row=1, column=2, sticky="NEW")
                    self.app.label("PE_Label_Per_Level", "x level)", row=1, column=3, sticky="NEW", font=10)

                # --- Caster Flags ---

                with self.app.frame("PE_Frame_Caster", row=2, column=0, stretch="BOTH", sticky="NEWS"):
                    self.app.label("PE_Label_Caster", "Caster Flags:", sticky="SEW", row=0, column=0, font=11)
                    self.app.checkBox("PE_Check_Caster_0", False, name="Spell List 1", sticky="NEW",
                                      change=self._professions_input, row=1, column=0, font=10)
                    self.app.checkBox("PE_Check_Caster_1", False, name="Spell List 2", sticky="NEW",
                                      change=self._professions_input, row=2, column=0, font=10)

                # --- Thieving Bonus ---

                with self.app.frame("PE_Frame_Thieving", row=3, column=0, stretch="BOTH", sticky="NEWS"):
                    self.app.label("PE_Label_Thieving_0", "Thieving Bonus:", sticky="SE", row=0, column=0, font=11)
                    self.app.entry("PE_Thieving_Bonus", "0", change=self._professions_input, fg=colour.BLACK,
                                   tooltip="This value should be between 0 and 156.",
                                   width=5, sticky="SW", row=0, column=1, font=10)
                    self.app.label("PE_Label_Thieving_1", "Success Chance:", sticky="SEW",
                                   tooltip="The chance to successfully avoid a trap or steal a chest without alerting" +
                                   " the guards.\nThe minimum value is for a DEX of 0, the maximum is for a DEX of 99.",
                                   row=1, column=0, colspan=2, font=11)
                    self.app.label("PE_Thieving_Chance", "", sticky="SEW", row=2, column=0, colspan=2, font=11)

            # Right Column
            with self.app.frame("PE_Frame_Right", row=1, column=2, stretch="COLUMN", sticky="NEW", padding=[4, 2],
                                bg=colour.PALE_VIOLET):
                self.app.label("PE_Label_Names", "Profession Names:", sticky="NEW", row=0, column=0, font=10)
                self.app.textArea("PE_Profession_Names", value=profession_names, width=11, height=11, font=10,
                                  change=self._professions_input,
                                  sticky="NEW", fg=colour.BLACK, scroll=True, row=1, column=0).clearModifiedFlag()

                # Professions list string index and edit button
                with self.app.frame("PE_Frame_Menu_String", row=2, column=0, sticky="NEW", padding=[4, 2],
                                    bg=colour.PALE_BLUE):
                    self.app.button("PE_Edit_Menu_String", value=self._professions_input, name="Edit Text", font=10,
                                    image="res/edit-dlg.gif", sticky="NW", width=32, height=32, row=0, column=0)
                    self.app.label("PE_Menu_String_Label", value="ID:", sticky="NEWS", row=0, column=1, font=10)
                    self.app.entry("PE_Menu_String_Id", value=f"0x{self.menu_string_id:02X}",
                                   change=self._professions_input,
                                   width=5, sticky="NES", row=0, column=2, font=10)

        # Read Max MP values
        if self._read_max_mp():
            self.app.hideLabel("PE_Label_Custom")
            self.app.setCheckBox("PE_Overwrite_MP", True, callFunction=False)
            self.app.hideCheckBox("PE_Overwrite_MP")

        else:
            self.app.showLabel("PE_Label_Custom")
            self.app.showCheckBox("PE_Overwrite_MP")
            self.app.setCheckBox("PE_Overwrite_MP", False, callFunction=False)
            self.app.disableEntry("PE_Fixed_MP")
            self.app.changeOptionBox("PE_Option_MP",
                                     [_wis, _int, f"{_wis} / 2", f"{_int} / 2", f"MAX({_wis} / 2, {_int} / 2)",
                                      f"MIN({_wis} / 2, {_int} / 2)", "Fixed Value"], callFunction=False)
            self.app.disableOptionBox("PE_Option_MP")

        # Disable inputs until a selection is made
        self.selected_index = -1
        self.app.disableOptionBox("PE_Profession_Colours")
        self.app.disableOptionBox("PE_Sprite_Palette_Top")
        self.app.disableOptionBox("PE_Sprite_Palette_Bottom")
        self.app.disableOptionBox("PE_Option_Weapon")
        self.app.disableOptionBox("PE_Option_Armour")
        self.app.disableOptionBox("PE_Primary_0")
        self.app.disableOptionBox("PE_Primary_1")
        self.app.disableEntry("PE_Gender_Character")

    # --- PartyEditor._create_pre_made_window() ---

    def _create_pre_made_window(self) -> None:
        """
        Creates a window and widgets for editing the pre-made characters.
        This is only for the Remastered version of the ROM.
        """
        # We need to read some text from ROM: attribute names, professions and races.
        # These will be displayed but not altered here.

        professions_list: List[str] = ["- Profession -"]
        race_names: List[str] = ["- Race -"]

        # Read and decode attribute names
        self._read_attribute_names()

        # Read profession names from ROM
        self._read_profession_names()
        # List for option box
        professions_list = professions_list + self.profession_names

        # Read race names from ROM
        self._read_race_names()
        # List for option box
        race_names = race_names + self.race_names

        # Read attribute names from ROM
        self._read_attribute_names()

        # Read pre-made characters from ROM
        self._read_pre_made()

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(400, 250)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", row=0, column=0, padding=[4, 0], sticky="NEW", stretch="ROW"):
                self.app.button("PE_Apply", name="Apply", value=self._pre_made_input, image="res/floppy.gif",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                tooltip="Discard Changes and Close Window", row=0, column=1)

            # Selector
            with self.app.frame("PE_Frame_Top", row=1, column=0, padding=[4, 2], stretch="ROW"):
                self.app.label("PE_Label_Character", "Pre-made character slot:", row=0, column=0, sticky="NEW")
                self.app.optionbox("PE_Character_Index",
                                   value=["0", "1", "2", "-", "3", "4", "5", "-", "6", "7", "8", "-", "9", "10", "11"],
                                   row=0, column=1, sticky="NEW", change=self._pre_made_input)

            # Character data
            with self.app.frame("PE_Frame_Data", row=2, column=0, padding=[4, 2], sticky="NEW", stretch="ROW"):
                # Row 0 - Name
                self.app.label("PE_Label_Name", "Name:", row=0, column=0, sticky='NE',
                               change=self._pre_made_input)
                self.app.entry("PE_Character_Name", "", width=10, row=0, column=1, sticky="NW",
                               change=self._pre_made_input)
                # Row 1 - Race and profession
                self.app.optionbox("PE_Race", race_names, row=1, column=0, sticky="NW",
                                   change=self._pre_made_input)
                self.app.optionbox("PE_Profession", professions_list, row=1, column=1, sticky="NW",
                                   change=self._pre_made_input)

            # Character attributes
            with self.app.frame("PE_Frame_Attributes", row=3, column=0, padding=[2, 2], sticky="NEW", stretch="ROW"):
                for r in range(4):
                    self.app.label(f"PE_Label_Attribute_{r}", self.attribute_names[r], row=0, column=(r * 2),
                                   sticky="NW")
                    self.app.entry(f"PE_Attribute_{r}", "", width=5, row=0, column=(r * 2) + 1, sticky="NW",
                                   change=self._pre_made_input)

            # Total attribute points
            with self.app.frame("PE_Frame_Total_Points", row=4, column=0, padding=[2, 2], sticky="NEWS", stretch="ROW"):
                self.app.label("PE_Label_Total", "Total attribute points:", row=0, column=0, sticky='NE')
                self.app.label("PE_Total_Points", "0", row=0, column=1, sticky="NW")

        # Display the first pre-made character
        self.app.setOptionBox("PE_Character_Index", 0, callFunction=True)

    # --- PartyEditor._create_magic_window() ---

    def _create_magic_window(self) -> None:
        """
        Creates a window and widgets for editing magic spells
        """
        # Read spell names
        custom = self._read_spell_names()

        # Read info that we will need for the UI (this module will not change any of this):
        self.caster_flags = self.rom.read_bytes(0xF, 0xD455, 11)
        self._read_profession_names()
        self._read_attribute_names()

        # Find spell definition files
        definitions_list = self._read_definitions()

        # Find spell string IDs
        spell_strings: List[int] = [5, 3]
        # List 1 (Cleric):
        # D378  $A9 $05        LDA #$05
        # D37A  $8D $D4 $03    STA $03D4
        # D37D  $20 $15 $D4    JSR SpellMenu
        bytecode = self.rom.read_bytes(0xF, 0xD378, 2)
        if bytecode[0] == 0xA9:
            spell_strings[0] = bytecode[1]
        else:
            custom = True
        # List 2 (Wizard):
        # D3AA  $A9 $03        LDA #$03
        # D3AC  $8D $D4 $03    STA $03D4
        # D3AF  $20 $15 $D4    JSR SpellMenu
        bytecode = self.rom.read_bytes(0xF, 0xD3AA, 2)
        if bytecode[0] == 0xA9:
            spell_strings[1] = bytecode[1]
        else:
            custom = True

        # Get map names
        map_options: List[str] = [] + self.map_editor.location_names
        if len(map_options) < 1:
            for m in range(self.map_editor.max_maps()):
                map_options.append(f"MAP #{m:02}")

        # TODO Read mark names from ROM

        # Read other spell data
        definition = 0
        if len(self.routine_definitions) > 0:
            # If any definition filename matches the currently loaded ROM filename, then use that one
            rom_name = os.path.basename(self.rom.path).rsplit('.')[0].lower()
            for d in range(len(self.routine_definitions)):
                definition_name = os.path.basename(self.routine_definitions[d]).rsplit('.')[0].lower()
                if definition_name == rom_name:
                    definition = d
                    break
            mp_increment = self._read_spell_data(self.routine_definitions[definition])
        else:
            mp_increment = self._read_spell_data()

        spell_flags_list = ["Nowhere", "Battle Only", "Town, Continent, Dungeon", "Continent Only", "Dungeon Only",
                            "Continent and Dungeon", "Battle and Continent", "Battle and Dungeon",
                            "Battle, Continent, Dungeon", "Everywhere"]

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(480, 580)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", padding=[4, 0], row=0, column=0, stretch="BOTH", sticky="NEWS"):
                self.app.button("PE_Apply", name="Apply", value=self._magic_input, image="res/floppy.gif",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                tooltip="Discard Changes and Close Window", row=0, column=1)
                self.app.button("PE_Reload", name="Reload", value=self._magic_input, image="res/reload.gif",
                                tooltip="Update Spell Names", row=0, column=3, sticky="E")

            # Spell list
            with self.app.frame("PE_Frame_Top", padding=[2, 2], row=1, column=0, stretch="BOTH", sticky="NEW"):
                with self.app.frame("PE_Frame_Top_Left", padding=[2, 2], row=0, column=0, bg=colour.PALE_NAVY):
                    self.app.optionBox("PE_Spell_List", ["Spell List 1", "Spell List 2", "Common Routines"],
                                       change=self._magic_input, row=0, column=0, sticky="NEW", font=10)
                    self.app.label("PE_Label_Magic_Professions", "Available to:", row=1, column=0, sticky="NW", font=11)
                    self.app.message("PE_Magic_Professions", "(None)", width=400, row=2, column=0, sticky="EW", font=10)

                with self.app.frame("PE_Frame_Top_Right", padding=[4, 2], row=0, column=1, bg=colour.PALE_VIOLET):
                    # List 1 string ID
                    self.app.label("PE_Label_Spell_Names_1", "List 1 Names String:",
                                   row=0, column=0, sticky="NEW", font=11)
                    self.app.entry("PE_Spell_String_ID_1", f"0x{spell_strings[0]:02X}", change=self._magic_input,
                                   fg=colour.BLACK, width=5, row=0, column=1, sticky="NW", font=10)
                    self.app.button("PE_Button_Spell_String_1_1", image="res/edit-dlg-small.gif", width=16, height=16,
                                    value=self._magic_input, row=0, column=2)
                    self.app.button("PE_Button_Spell_String_1_2", image="res/edit-dlg-small.gif", width=16, height=16,
                                    value=self._magic_input, row=0, column=3)
                    # List 2 string ID
                    self.app.label("PE_Label_Spell_Names_2", "List 2 Names String:",
                                   row=1, column=0, sticky="NEW", font=11)
                    self.app.entry("PE_Spell_String_ID_2", f"0x{spell_strings[1]:02X}", change=self._magic_input,
                                   fg=colour.BLACK, width=5, row=1, column=1, sticky="NW", font=10)
                    self.app.button("PE_Button_Spell_String_2_1", image="res/edit-dlg-small.gif", width=16, height=16,
                                    value=self._magic_input, row=1, column=2)
                    self.app.button("PE_Button_Spell_String_2_2", image="res/edit-dlg-small.gif", width=16, height=16,
                                    value=self._magic_input, row=1, column=3)
                    # Message for custom menus
                    self.app.message("PE_Message_Custom_Menus", "This ROM uses a custom routine for spell  menus.",
                                     fg=colour.MEDIUM_RED, sticky="NEWS", width=220,
                                     row=2, column=0, colspan=3, font=11)

            # MP cost routine
            with self.app.frame("PE_Frame_Middle", padding=[2, 2], row=3, column=0, stretch="BOTH", sticky="NEW",
                                bg=colour.PALE_BLUE):
                with self.app.frame("PE_Frame_Mid_Left", padding=[2, 2], row=0, column=0, sticky="NWS"):
                    self.app.radioButton("PE_Radio_MP", "Incremental MP Cost", change=self._magic_input,
                                         row=0, column=0, font=11)
                    self.app.entry("PE_Incremental_MP", "4", change=self._magic_input, fg=colour.BLACK, width=4,
                                   row=0, column=1, font=10)
                    self.app.radioButton("PE_Radio_MP", "Uneven MP Cost", change=self._magic_input,
                                         row=0, column=2, font=11)

                with self.app.frame("PE_Frame_Mid_Right", row=0, column=1, sticky="NES"):
                    self.app.message("PE_Message_Custom_MP", "This ROM uses custom code for the spell menu.", width=200,
                                     row=0, column=0, sticky="NEWS", font=10, fg=colour.MEDIUM_RED)

            # Spell editor
            with self.app.frame("PE_Frame_Bottom", padding=[2, 2], row=4, column=0, stretch="BOTH", sticky="NEWS",
                                bg=colour.PALE_NAVY):
                # Spell definitions file
                self.app.label("PE_Label_Definitions", "Spell definitions file:", sticky="NSE", font=10,
                               row=0, column=0)
                self.app.optionBox("PE_Spell_Definitions", definitions_list, change=self._magic_input,
                                   row=0, column=1, sticky="NEWS", font=10)

                self.app.label("PE_Label_Select_Spell", "Edit Spell:", font=11,
                               row=1, column=0, sticky="NE")
                self.app.optionBox("PE_Option_Spell", self.spell_names_0, change=self._magic_input,
                                   font=10, row=1, column=1, sticky="NEW")

                self.app.label("PE_Label_Spell_Flags", "Casting Flags:", sticky="NE", row=2, column=0, font=11)
                self.app.optionBox("PE_Spell_Flags", spell_flags_list, change=self._magic_input,
                                   sticky="NEW", row=2, column=1, font=10)

                # Specific usability flags (same used for "tools")
                with self.app.frame("PE_Specific_Flags", padding=[2, 2], row=3, column=0, colspan=2, sticky="NEW",
                                    bg=colour.PALE_LIME):
                    self.app.label("PE_Label_Specific", "Specific usability flags:", font=11,
                                   sticky="NEW", row=0, column=0, colspan=4)
                    # Left
                    self.app.checkBox("PE_Flag_0x01", name="Battle (anywhere)", change=self._magic_input, font=10,
                                      sticky="NEW", row=1, column=0, colspan=2)
                    self.app.checkBox("PE_Flag_0x04", name="Map:", change=self._magic_input, font=10,
                                      sticky="NEW", row=2, column=0)
                    self.app.optionBox("PE_Map_Flag_0x04", map_options, change=self._magic_input, font=10, width=16,
                                       tooltip="This will apply to ALL items/spells using this flag.",
                                       sticky="NW", row=2, column=1)
                    self.app.checkBox("PE_Flag_0x10", name="Map:", change=self._magic_input, font=10,
                                      sticky="NEW", row=3, column=0)
                    self.app.optionBox("PE_Map_Flag_0x10", map_options, change=self._magic_input, font=10, width=16,
                                       tooltip="This will apply to ALL items/spells using this flag.",
                                       sticky="NW", row=3, column=1)
                    self.app.checkBox("PE_Flag_0x40", name="Continents (embarked)", change=self._magic_input,
                                      font=10, sticky="NEW", row=4, column=0, colspan=2)
                    # Right
                    self.app.checkBox("PE_Flag_0x02", name="Map:", change=self._magic_input, font=10,
                                      sticky="NEW", row=1, column=2)
                    self.app.optionBox("PE_Map_Flag_0x02", map_options, change=self._magic_input, font=10, width=16,
                                       tooltip="This will apply to ALL items/spells using this flag.",
                                       sticky="NW", row=1, column=3)
                    self.app.checkBox("PE_Flag_0x08", name="Dungeons", change=self._magic_input, font=10,
                                      sticky="NEW", row=2, column=2, colspan=2)
                    self.app.checkBox("PE_Flag_0x20", name="Towns and Shrines", change=self._magic_input, font=10,
                                      sticky="NEW", row=3, column=2, colspan=2)
                    self.app.checkBox("PE_Flag_0x80", name="Continents (not embarked)", change=self._magic_input,
                                      font=10, sticky="NEW", row=4, column=2, colspan=2)

                with self.app.frame("PE_Bottom_Left", padding=[2, 2], row=4, column=0, sticky="NEW"):
                    self.app.label("PE_Label_Spell_Address", "Routine Address:", sticky="NE",
                                   row=0, column=0, font=11)
                    self.app.entry("PE_Spell_Address", "0x0000", change=self._magic_input, width=8, sticky="NW",
                                   fg=colour.BLACK, row=0, column=1, font=10)

                with self.app.frame("PE_Bottom_Right", padding=[2, 2], row=4, column=1, sticky="NEW"):
                    self.app.label("PE_Label_MP_Display", "MP to display:", sticky="NE", row=0, column=0, font=11)
                    self.app.entry("PE_MP_Display", "0", change=self._magic_input, width=5, sticky="NW",
                                   fg=colour.BLACK, row=0, column=1, font=10)

                    self.app.label("PE_Label_MP_Cast", "MP to cast:", sticky="NE", row=1, column=0, font=11)
                    self.app.entry("PE_MP_Cast", "0", change=self._magic_input, width=5, sticky="NW",
                                   fg=colour.BLACK, row=1, column=1, font=10)

                    self.app.label("PE_Spell_Custom", "This spell is using a custom routine", fg=colour.MEDIUM_RED,
                                   sticky="NW", row=1, column=1, font=11)
                    self.app.hideLabel("PE_Spell_Custom")

                # Spell parameters
                with self.app.labelFrame("PE_Frame_Parameters", name="Parameters", padding=[2, 2],
                                         bg=colour.MEDIUM_GREY, row=5, column=0, colspan=2, sticky="NEWS"):
                    pass

        # Spell list string IDs input widgets enable/disable
        if custom is False:
            self.app.enableEntry("PE_Spell_String_ID_1")
            self.app.enableButton("PE_Button_Spell_String_1_1")
            self.app.enableButton("PE_Button_Spell_String_1_2")
            self.app.enableEntry("PE_Spell_String_ID_2")
            self.app.enableButton("PE_Button_Spell_String_2_1")
            self.app.enableButton("PE_Button_Spell_String_2_2")
            self.app.hideMessage("PE_Message_Custom_Menus")

        else:
            self.app.disableEntry("PE_Spell_String_ID_1")
            self.app.disableButton("PE_Button_Spell_String_1_1")
            self.app.disableButton("PE_Button_Spell_String_1_2")
            self.app.disableEntry("PE_Spell_String_ID_2")
            self.app.disableButton("PE_Button_Spell_String_2_1")
            self.app.disableButton("PE_Button_Spell_String_2_2")
            self.app.showMessage("PE_Message_Custom_Menus")

        # MP system options
        if mp_increment > -1:
            self.app.setRadioButton("PE_Radio_MP", "Incremental MP Cost", callFunction=False)
            self.app.clearEntry("PE_Incremental_MP", callFunction=False, setFocus=False)
            self.app.setEntry("PE_Incremental_MP", f"{mp_increment}", callFunction=False)
            self.app.hideMessage("PE_Message_Custom_MP")
            self.app.disableEntry("PE_MP_Display")

        elif mp_increment == -1:
            self.app.setRadioButton("PE_Radio_MP", "Uneven MP Cost", callFunction=False)
            self.app.disableEntry("PE_Incremental_MP")
            self.app.hideMessage("PE_Message_Custom_MP")
            self.app.enableEntry("PE_MP_Display")

        else:
            self.app.disableRadioButton("PE_Radio_MP")
            self.app.disableEntry("PE_Incremental_MP")

        # Read map IDs for fine flags from this code (bank $0B):
        # TODO Check if code has been customised
        # AF24  $A5 $70        LDA _CurrentMapId
        # AF26  $C9 $14        CMP #$14                 ;Check if in Castle Death
        # AF2C  $C9 $0F        CMP #$0F                 ;Check if in Ambrosia
        # AF32  $C9 $06        CMP #$06                 ;Check if in Castle British
        value = self.rom.read_byte(0xB, 0xAF27)
        self.app.setOptionBox("PE_Map_Flag_0x02", index=value, callFunction=False)
        value = self.rom.read_byte(0xB, 0xAF2D)
        self.app.setOptionBox("PE_Map_Flag_0x04", index=value, callFunction=False)
        value = self.rom.read_byte(0xB, 0xAF33)
        self.app.setOptionBox("PE_Map_Flag_0x10", index=value, callFunction=False)

        # Default selections
        self.app.setOptionBox("PE_Spell_Definitions", definition, callFunction=False)
        self.app.setOptionBox("PE_Spell_List", 0, callFunction=True)

    # --- PartyEditor._create_special_window() ---

    def _create_special_window(self) -> None:
        """
        Creates a window and widgets for managing special abilities such as critical hit and extra MP regeneration.
        """
        # Read attribute names from ROM
        self._read_attribute_names()

        # Read profession names from ROM
        self._read_profession_names()
        # List for option box
        professions_list = self.profession_names + ["None"]

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(400, 492)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", padding=[4, 0], row=0, column=0, stretch="BOTH", sticky="NEWS"):
                self.app.button("PE_Apply", name="Apply", value=self._special_input, image="res/floppy.gif",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                tooltip="Discard Changes and Close Window", row=0, column=1)

            # Special 0
            with self.app.labelFrame("MP Regeneration", row=1, column=0, stretch="BOTH", sticky="NEWS",
                                     padding=[4, 0], bg=colour.PALE_TEAL):
                # Make sure the code we want to modify is actually there, to avoid issues with customised ROMs
                # Bank 0xD
                # 8713    LDA $2A
                # 8715    CMP #$08
                if self.rom.read_bytes(0xD, 0x8713, 3) == b'\xA5\x2A\xC9':

                    self.app.label("PE_Label_Profession_0", "Available to:", row=0, column=0, sticky='SEW', font=11)
                    self.app.optionBox("PE_Profession_0", professions_list, change=self._special_input,
                                       width=12, row=0, column=1, sticky='SEW', font=10)
                    # Description
                    self.app.label("PE_Description_0", "The selected profession will regenerate double the MP",
                                   fg=colour.DARK_BLUE,
                                   row=1, column=0, colspan=2, sticky='WE', stretch="ROW", font=10)
                    self.app.label("PE_Description_1", "when moving on the map, compared to other professions.",
                                   fg=colour.DARK_BLUE,
                                   row=2, column=0, colspan=2, sticky='WE', stretch="ROW", font=10)
                    # Initial value, read from ROM
                    value = self.rom.read_byte(0xD, 0x8716)
                    self.app.setOptionBox("PE_Profession_0", value, callFunction=False)

                else:
                    self.app.label("PE_Label_Unsupported_0", "The loaded ROM does not support this feature.",
                                   row=0, column=0, sticky="NEWS", stretch="ROW", font=11)

            # Special 1
            with self.app.labelFrame("Critical Hit", row=2, column=0, stretch="BOTH", sticky="NEWS",
                                     padding=[4, 0], bg=colour.PALE_BLUE):
                # Code to check (bank 0):
                # B0C4    LDA ($99),Y
                # B0C6    CMP #$03
                # and:
                # B0E0    LDA ($99),Y
                # B0E2    CLC
                if self.rom.read_bytes(0x0, 0xB0C4, 3) == b'\xB1\x99\xC9' \
                        and self.rom.read_bytes(0x0, 0xB0E0, 3) == b'\xB1\x99\x18':

                    self.app.label("PE_Label_Profession_1", "Available to:", row=0, column=0, sticky='SEW', font=11)
                    self.app.optionBox("PE_Profession_1", professions_list, change=self._special_input,
                                       width=12, row=0, column=1, sticky='SEW', font=10)
                    self.app.label("PE_Label_Damage_1", "Damage based on:", row=1, column=0, sticky='SEW', font=11)
                    self.app.optionBox("PE_Damage_1", self.attribute_names + ["Level", "Custom"],
                                       change=self._special_input, width=12,
                                       row=1, column=1, sticky='SEW', font=10)
                    # Custom index for damage
                    self.app.label("PE_Label_Custom_1", "Custom index:", row=2, column=0, sticky='SEW', font=11)
                    self.app.entry("PE_Custom_1", "", change=self._special_input, width=5,
                                   row=2, column=1, sticky='SEW', font=10)
                    # Description
                    self.app.label("PE_Description_2", "This profession will have a chance of scoring",
                                   fg=colour.DARK_BLUE,
                                   row=3, column=0, colspan=2, sticky='WE', stretch="ROW", font=10)
                    self.app.label("PE_Description_3", "critical hits (chance is based on character level).",
                                   fg=colour.DARK_BLUE,
                                   row=4, column=0, colspan=2, sticky='WE', stretch="ROW", font=10)
                    # Initial values, read from ROM
                    value = self.rom.read_byte(0x0, 0xB0C7)
                    self.app.setOptionBox("PE_Profession_1", value, callFunction=False)
                    value = self.rom.read_byte(0x0, 0xB0DF)
                    self.app.setEntry("PE_Custom_1", f"0x{value:02X}", callFunction=False)
                    self.app.disableEntry("PE_Custom_1")
                    if 7 <= value <= 10:
                        # Attribute-based (first attribute index = 7)
                        value = value - 7
                    elif value == 0x33:
                        # Level-based
                        value = 4
                    else:
                        # Allow custom entry
                        value = 5
                        self.app.enableEntry("PE_Custom_1")
                    self.app.setOptionBox("PE_Damage_1", value, callFunction=False)

                else:
                    self.app.label("PE_Label_Unsupported_1", "The loaded ROM does not support this feature.",
                                   row=0, column=0, sticky="NEWS", stretch="ROW", font=11)

            # Special 2
            with self.app.labelFrame("Extra Damage", row=3, column=0, stretch="BOTH", sticky="NEWS",
                                     padding=[4, 0], bg=colour.PALE_NAVY):
                # Code to check (bank 0):
                # B0E8    CMP #$05  ; #$05 = Barbarian
                # B0EA    BNE $B0F9
                # and:
                # B0EC    LDY #$33  ; #$33 = Level
                # B0EE    LDA ($99),Y
                if self.rom.read_byte(0x0, 0xB0E8) == 0xC9 and self.rom.read_byte(0x0, 0xB0EC) == 0xA0 \
                        and self.rom.read_word(0x0, 0xB0EA) == 0x0DD0 and self.rom.read_word(0x0, 0xB0EE) == 0x99B1:
                    self.app.label("PE_Label_Profession_2", "Available to:", row=0, column=0, sticky='SEW', font=11)
                    self.app.optionBox("PE_Profession_2", professions_list, change=self._special_input,
                                       width=12, row=0, column=1, sticky='SEW', font=10)
                    self.app.label("PE_Label_Damage_2", "Damage based on:", row=1, column=0, sticky='SEW', font=11)
                    self.app.optionBox("PE_Damage_2", self.attribute_names + ["Level", "Weapon", "Custom"],
                                       change=self._special_input,
                                       width=12, row=1, column=1, sticky='SEW', font=10)
                    # Custom index for damage
                    self.app.label("PE_Label_Custom_2", "Custom index:", row=2, column=0, sticky='SEW', font=11)
                    self.app.entry("PE_Custom_2", "", change=self._special_input, width=5,
                                   row=2, column=1, sticky='SEW', font=10)
                    # Damage Adjustment
                    self.app.label("PE_Label_Adjustment_2", "Extra Damage adjustment:",
                                   row=3, column=0, colspan=2, sticky='SEW', font=11)
                    self.app.optionBox("PE_Adjustment_2", ["None", "Subtract", "Add", "x2", "x4", "/2", "/4"],
                                       change=self._special_input,
                                       row=4, column=0, sticky='SEW', font=10)
                    self.app.entry("PE_Adjustment_3", "", change=self._special_input, width=5,
                                   row=4, column=1, sticky='SEW', font=11)
                    # Description
                    self.app.label("PE_Description_4", "This profession will always deal additional",
                                   fg=colour.DARK_BLUE,
                                   row=5, column=0, colspan=2, sticky='WE', stretch="ROW", font=10)
                    self.app.label("PE_Description_5", "damage when hitting an enemy in combat.",
                                   fg=colour.DARK_BLUE,
                                   row=6, column=0, colspan=2, sticky='WE', stretch="ROW", font=10)

                    # Initial values, read from ROM
                    value = self.rom.read_byte(0x0, 0xB0E9)
                    self.app.setOptionBox("PE_Profession_2", value, callFunction=False)
                    value = self.rom.read_byte(0x0, 0xB0ED)
                    self.app.setEntry("PE_Custom_2", f"0x{value:02X}", callFunction=False)
                    self.app.disableEntry("PE_Custom_2")
                    if 7 <= value <= 10:
                        # Attribute-based (first attribute index = 7)
                        value = value - 7
                    elif value == 0x33:
                        # Level-based
                        value = 4
                    elif value == 0x34:
                        # Weapon-based
                        value = 5
                    else:
                        # Allow custom entry
                        value = 6
                        self.app.enableEntry("PE_Custom_2")
                    self.app.setOptionBox("PE_Damage_2", value, callFunction=False)

                    # Read damage adjustment
                    # Default: -1 => $38, $E9, $01
                    # B0F0    SEC
                    # B0F1    SBC #$01
                    value = self.rom.read_bytes(0x0, 0xB0F0, 3)
                    if value[1] == 0xE9:
                        # SBC = Subtract
                        self.app.setOptionBox("PE_Adjustment_2", 1, callFunction=False)
                        self.app.enableEntry("PE_Adjustment_3")
                        self.app.setEntry("PE_Adjustment_3", f"{value[2]}", callFunction=False)

                    elif value[1] == 0x65:
                        # ADC = Add
                        self.app.setOptionBox("PE_Adjustment_2", 1, callFunction=False)
                        self.app.enableEntry("PE_Adjustment_3")
                        self.app.setEntry("PE_Adjustment_3", f"{value[2]}", callFunction=False)

                    elif value[0] == 0x0A:
                        # ASL = Multiply
                        self.app.disableEntry("PE_Adjustment_3")

                        if value[1] == 0x0A:
                            # x4
                            self.app.setOptionBox("PE_Adjustment_2", 4, callFunction=False)
                        else:
                            # x2
                            self.app.setOptionBox("PE_Adjustment_2", 3, callFunction=False)

                    elif value[0] == 0x4A:
                        # LSR = Divide
                        self.app.disableEntry("PE_Adjustment_3")

                        if value[1] == 0x4A:
                            # /4
                            self.app.setOptionBox("PE_Adjustment_2", 6, callFunction=False)
                        else:
                            # /2
                            self.app.setOptionBox("PE_Adjustment_2", 5, callFunction=False)

                    else:
                        # Possibly NOP
                        self.app.disableEntry("PE_Adjustment_3")
                        self.app.setOptionBox("PE_Adjustment_2", 0, callFunction=False)

                else:
                    self.app.label("PE_Label_Unsupported_2", "The loaded ROM does not support this feature.",
                                   row=0, column=0, sticky="NEWS", stretch="ROW", font=11)

    # --- PartyEditor._create_weapons_window() ---

    def _create_weapons_window(self) -> None:
        """
        Creates a sub-window and widgets for editing weapons and armour properties
        """
        self._read_weapon_armour_names()

        # Weapon type table (0 = melee, 1 = ranged)
        self.weapon_type = self.rom.read_bytes(0xF, 0xD189, 16)

        # Throwing weapon ID
        # D112  $A0 $34        LDY #$34
        # D114  $B1 $99        LDA ($99),Y
        # D116  $C9 $01        CMP #$01     ; Daggers can be thrown
        throwing_weapon = self.rom.read_byte(0xF, 0xD117)
        if throwing_weapon > 15:
            self.app.warningBox("Reading Weapon Data",
                                f"WARNING: Invalid ID for throwing weapon ({throwing_weapon}).\nMust be 0-15.",
                                "Party_Editor")
            throwing_weapon = 1

        # Armour damage avoidance:
        # CBD3  $A0 $35        LDY #$35
        # CBD5  $B1 $99        LDA ($99),Y
        # CBD7  $18            CLC
        # CBD8  $69 $0A        ADC #$0A
        # CBDA  $20 $4E $E6    JSR RNG
        # CBDD  $C9 $08        CMP #$08
        # CBDF  $90 $03        BCC MeleeDamage
        armour_add = self.rom.read_byte(0xF, 0xCBD9)
        armour_check = self.rom.read_byte(0xF, 0xCBDE)

        # One special map can be set to only accept specific weapon(s):
        # BattleAttack:
        # D0B3  $A5 $70        LDA _CurrentMapId
        # D0B5  $C9 $14        CMP #$14                 ; Map $14 = Castle Exodus
        # D0B7  $D0 $12        BNE $D0CB
        # D0B9  $A0 $34        LDY #$34                 ; Read current weapon...
        # D0BB  $B1 $99        LDA ($99),Y
        # D0BD  $C9 $0F        CMP #$0F                 ; Only Mystic Weapons work in this map
        # D0BF  $F0 $0A        BEQ $D0CB
        # D0C1  $A9 $F5        LDA #$F5                 ; "CAN`T USE IT."
        # D0C3  $85 $30        STA $30
        # D0C5  $20 $27 $D2    JSR $D227                ; Battle Info Text
        # D0C8  $4C $D0 $CA    JMP __EndBattleTurn
        special_map = self.rom.read_byte(0xF, 0xD0B6)
        special_weapon = self.rom.read_byte(0xF, 0xD0BE)
        special_condition = self.rom.read_byte(0xF, 0xD0BF)
        special_dialogue = self.rom.read_byte(0xF, 0xD0C2)

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(520, 360)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", padding=[4, 2], row=0, column=0, colspan=2,
                                stretch="BOTH", sticky="NEWS"):
                self.app.button("PE_Apply", name="Apply", value=self._weapons_input, image="res/floppy.gif",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                tooltip="Discard Changes and Close Window", row=0, column=1)

            # Weapons
            with self.app.labelFrame("Weapons", padding=[2, 2], row=1, column=0, bg=colour.PALE_VIOLET):
                with self.app.frame("PW_Frame_Weapons_Selection", padding=[2, 2], row=0, column=0):
                    self.app.label("PE_Label_Throwing_Weapon", "Throwing Weapon:", row=0, column=0, font=11)
                    self.app.optionBox("PE_Option_Throwing_Weapon", self.weapon_names, change=self._weapons_input,
                                       width=16, row=0, column=1, font=10)
                    self.app.setOptionBox("PE_Option_Throwing_Weapon", index=throwing_weapon, callFunction=False)

                    self.app.label("PE_Label_Weapon", "Edit weapon:", row=1, column=0, font=11)
                    self.app.optionBox("PE_Option_Weapon", self.weapon_names, change=self._weapons_input,
                                       width=16, row=1, column=1, font=10)

                with self.app.frame("PE_Frame_Weapon_Data", padding=[2, 2], row=1, column=0):
                    self.app.label("PE_Label_Weapon_Name", "Name:", stretch="COLUMN", sticky="WE",
                                   row=0, column=0, font=11)
                    self.app.entry("PE_Weapon_Name", "", submit=self._update_weapon_names, width=16, sticky="WE",
                                   row=0, column=1, font=10)
                    self.app.button("PE_Update_Weapon_Names", value=self._update_weapon_names, sticky="W",
                                    tooltip="Update names list",
                                    image="res/reload-small.gif", width=16, height=16, row=0, column=2)

                    self.app.checkBox("PE_Weapon_Ranged", False, name="Ranged", change=self._weapons_input,
                                      row=1, column=0, font=11)
                    self.app.label("PE_Label_Weapon_Damage", "Base Damage = 0", row=1, column=1, colspan=2, font=11)

            # Armour
            with self.app.labelFrame("Armour", padding=[2, 2], row=2, column=0, bg=colour.PALE_RED):
                with self.app.frame("PW_Frame_Armour_Selection", padding=[2, 2], row=0, column=0):
                    self.app.label("PE_Label_Armour", "Edit armour:", row=1, column=0, font=11)
                    self.app.optionBox("PE_Option_Armour", self.armour_names, change=self._weapons_input,
                                       width=16, row=1, column=1, font=10)

                with self.app.frame("PE_Frame_Armour_Data", padding=[2, 2], row=1, column=0):
                    self.app.label("PE_Label_Armour_Name", "Name:", row=0, column=0, font=11)
                    self.app.entry("PE_Armour_Name", "", submit=self._update_armour_names, width=16, sticky="W",
                                   row=0, column=1, font=10)
                    self.app.button("PE_Update_Armour_Names", value=self._update_armour_names, sticky="W",
                                    tooltip="Update names list",
                                    image="res/reload-small.gif", width=16, height=16, row=0, column=2)

                with self.app.frame("PE_Frame_Armour_Parry", padding=[2, 2], row=2, column=0):
                    self.app.label("PE_Label_Armour_Parry_0", "Parry Chance: %", sticky="WE",
                                   row=0, column=0, colspan=4, font=11)

                    self.app.label("PE_Label_Armour_Parry_1", "RANDOM(0 to ID + ", row=1, column=0, font=11)
                    self.app.entry("PE_Armour_Parry_Add", f"{armour_add}", change=self._weapons_input, width=5,
                                   row=1, column=1, font=10)
                    self.app.label("PE_Label_Armour_Parry_2", ") >= ", row=1, column=2, font=11)
                    self.app.entry("PE_Armour_Parry_Check", f"{armour_check}", change=self._weapons_input, width=5,
                                   row=1, column=3, font=10)

            # Special
            with self.app.labelFrame("Special", padding=[2, 2], row=1, column=1, rowspan=2,
                                     bg=colour.PALE_BROWN):
                self.app.label("PE_Label_Special_0", "On this map:", row=0, column=0, colspan=3, font=11)
                self.app.optionBox("PE_Special_Map", self.map_editor.location_names,
                                   index=special_map, colspan=3, sticky="EW",
                                   row=1, column=0, font=10)
                self.app.label("PE_Label_Special_1", "Limit possible weapons to:", row=2, column=0, colspan=3, font=11)
                self.app.optionBox("PE_Special_Condition",
                                   ["Exactly", "Anything except", "At least (including)", "Up to (excluding)"],
                                   colspan=3, sticky="EW",
                                   row=3, column=0, font=10)
                self.app.optionBox("PE_Special_Weapon", self.weapon_names,
                                   colspan=3, sticky="EW",
                                   row=4, column=0, font=10)
                self.app.label("PE_Label_Special_2", "Failure dialogue:", row=5, column=0, font=11)
                self.app.entry("PE_Special_Dialogue", f"0x{special_dialogue:02X}", fg=colour.BLACK, width=5,
                               change=self._weapons_input,
                               row=5, column=1, font=10)
                self.app.button("PE_Button_Special_Dialogue", self._weapons_input, image="res/edit-dlg-small.gif",
                                width=16, height=16, row=5, column=2)

        self.app.setOptionBox("PE_Special_Map", index=special_map, callFunction=False)
        self.app.setOptionBox("PE_Special_Weapon", index=special_weapon, callFunction=False)
        # Special condition
        selection = -1
        if special_condition == 0xF0:           # BEQ
            selection = 0
        elif special_condition == 0xD0:         # BNE
            selection = 1
        elif (special_condition == 0xB0         # BCS
              or special_condition == 0x10):    # BPL
            selection = 2
        elif (special_condition == 0x90         # BCC
              or special_condition == 0x30):    # BMI
            selection = 3

        if selection >= 0:
            self.app.setOptionBox("PE_Special_Condition", index=selection, callFunction=False)
        else:
            self.app.changeOptionBox("PE_Special_Condition", ["- CUSTOM CODE -"])
            self.app.disableEntry("PE_Special_Dialogue")
            self.app.disableButton("PE_Button_Special_Dialogue")
            self.app.disableOptionBox("PE_Special_Map")
            self.app.disableOptionBox("PE_Special_Weapon")
            self.app.disableOptionBox("PE_Special_Condition")

        # Default selection
        self.app.setOptionBox("PE_Option_Weapon", 0, callFunction=True)
        self.app.setOptionBox("PE_Option_Armour", 0, callFunction=True)

    # --- PartyEditor._create_items_window() ---

    def _create_items_window(self) -> None:
        """
        Creates a sub-window and widgets for editing "tools" (usable items)
        """
        self.routines.clear()

        # Read item names from the ROM buffer
        tools_list = self._read_item_names()
        if len(tools_list) < 1:
            self.app.warningBox("Parsing Routines", "WARNING: Item names not found (bank $0D, address $9B08).",
                                "Party_Editor")
            tools_list = ["- None -"]

        # TODO Read mark names from the ROM buffer

        # Get map names
        map_options: List[str] = [] + self.map_editor.location_names
        if len(map_options) < 1:
            for m in range(self.map_editor.max_maps()):
                map_options.append(f"MAP #{m:02}")

        # Read routine definitions
        definitions_list = self._read_definitions()

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(400, 408)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", padding=[4, 0], row=0, column=0, stretch="BOTH", sticky="NEWS"):
                self.app.button("PE_Apply", name="Apply", value=self._items_input, image="res/floppy.gif",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                tooltip="Discard Changes and Close Window", row=0, column=1)

            # Definitions file
            with self.app.frame("PE_Frame_Definitions", padding=[2, 0], row=1, column=0, bg=colour.PALE_TEAL):
                self.app.label("PE_Label_Definitions", "Definitions file:", sticky="E", row=0, column=0, font=11)
                self.app.optionBox("PE_Definitions", definitions_list, change=self._items_input,
                                   width=25, row=0, column=1, font=10)

            # Item selection
            with self.app.frame("PE_Frame_Selection", padding=[2, 2], row=2, column=0, bg=colour.PALE_GREEN):
                # Option
                self.app.label("PE_Label_Item", "Edit item:", sticky="E", row=0, column=0, font=11)
                self.app.optionBox("PE_Option_Item", tools_list, change=self._items_input, sticky="W",
                                   width=16, row=0, column=1, colspan=2, font=10)
                # Name
                self.app.label("PE_Label_Name", "Item name:", sticky="E", row=1, column=0, font=11)
                self.app.entry("PE_Item_Name", "", change=self._items_input, submit=self._update_item_names,
                               sticky="W", width=16, row=1, column=1, font=10)
                self.app.button("PE_Update_Names", self._update_item_names, image="res/reload-small.gif", sticky="W",
                                tooltip="Update list.",
                                width=16, height=16, row=1, column=2)
                # Consumption
                self.app.label("PE_Label_Consumption", "Consumption on use:", sticky="E", row=2, column=0, font=11)
                self.app.entry("PE_Item_Consumption", "", change=self._items_input, width=5, sticky="W",
                               tooltip="A positive value means items will be added on use.\n" +
                                       "Zero means item is not consumed on use.",
                               row=2, column=1, colspan=2, font=10)
                # Address
                self.app.label("PE_Label_Address", "Address:", sticky="E", row=3, column=0, font=11)
                self.app.entry("PE_Item_Address", "", change=self._items_input, submit=self._update_item_parameters,
                               sticky="W", width=16, row=3, column=1, font=10)
                self.app.button("PE_Update_Parameters", self._update_item_parameters, image="res/reload-small.gif",
                                tooltip="Re-read parameters from ROM.",
                                sticky="W", width=16, height=16, row=3, column=2)

            # Specific usability flags (same used for spells)
            with self.app.frame("PE_Specific_Flags", padding=[2, 2], row=3, column=0, sticky="NEW",
                                bg=colour.PALE_OLIVE):
                self.app.label("PE_Label_Specific", "Specific usability flags:", font=11,
                               sticky="NEW", row=0, column=0, colspan=4)
                # Left
                self.app.checkBox("PE_Flag_0x01", name="Battle (anywhere)", change=self._items_input, font=10,
                                  sticky="NEW", row=1, column=0, colspan=2)
                self.app.checkBox("PE_Flag_0x04", name="Map:", change=self._items_input, font=10,
                                  sticky="NEW", row=2, column=0)
                self.app.optionBox("PE_Map_Flag_0x04", map_options, change=self._items_input, font=10, width=16,
                                   tooltip="This will apply to ALL items/spells using this flag.",
                                   sticky="NW", row=2, column=1)
                self.app.checkBox("PE_Flag_0x10", name="Map:", change=self._items_input, font=10,
                                  sticky="NEW", row=3, column=0)
                self.app.optionBox("PE_Map_Flag_0x10", map_options, change=self._items_input, font=10, width=16,
                                   tooltip="This will apply to ALL items/spells using this flag.",
                                   sticky="NW", row=3, column=1)
                self.app.checkBox("PE_Flag_0x40", name="Continents (embarked)", change=self._items_input,
                                  font=10, sticky="NEW", row=4, column=0, colspan=2)
                # Right
                self.app.checkBox("PE_Flag_0x02", name="Map:", change=self._items_input, font=10,
                                  sticky="NEW", row=1, column=2)
                self.app.optionBox("PE_Map_Flag_0x02", map_options, change=self._items_input, font=10, width=16,
                                   tooltip="This will apply to ALL items/spells using this flag.",
                                   sticky="NW", row=1, column=3)
                self.app.checkBox("PE_Flag_0x08", name="Dungeons", change=self._items_input, font=10,
                                  sticky="NEW", row=2, column=2, colspan=2)
                self.app.checkBox("PE_Flag_0x20", name="Towns and Shrines", change=self._items_input, font=10,
                                  sticky="NEW", row=3, column=2, colspan=2)
                self.app.checkBox("PE_Flag_0x80", name="Continents (not embarked)", change=self._items_input,
                                  font=10, sticky="NEW", row=4, column=2, colspan=2)

            # Routine parameters
            with self.app.labelFrame("PE_Frame_Parameters", name="Parameters", padding=[2, 2], row=4, column=0,
                                     bg=colour.PALE_LIME):
                self.app.label("PE_Label_Parameters", "")

        # Read map IDs for fine flags from this code (bank $0B):
        # TODO Check if code has been customised
        # AF24  $A5 $70        LDA _CurrentMapId
        # AF26  $C9 $14        CMP #$14                 ;Check if in Castle Death
        # AF2C  $C9 $0F        CMP #$0F                 ;Check if in Ambrosia
        # AF32  $C9 $06        CMP #$06                 ;Check if in Castle British
        value = self.rom.read_byte(0xB, 0xAF27)
        self.app.setOptionBox("PE_Map_Flag_0x02", index=value, callFunction=False)
        value = self.rom.read_byte(0xB, 0xAF2D)
        self.app.setOptionBox("PE_Map_Flag_0x04", index=value, callFunction=False)
        value = self.rom.read_byte(0xB, 0xAF33)
        self.app.setOptionBox("PE_Map_Flag_0x10", index=value, callFunction=False)

        # Select the definition files that matches the current ROM, if there is one
        definition = 0
        if len(self.routine_definitions) > 0:
            # If any definition filename matches the currently loaded ROM filename, then use that one
            rom_name = os.path.basename(self.rom.path).rsplit('.')[0].lower()
            for d in range(len(self.routine_definitions)):
                definition_name = os.path.basename(self.routine_definitions[d]).rsplit('.')[0].lower()
                if definition_name == rom_name:
                    definition = d
                    break
        self.app.setOptionBox("PE_Definitions", definition, callFunction=False)

        # Parse the selected definition file
        self._read_item_data(self.routine_definitions[definition])

        # Select the first item and show info
        self.app.setOptionBox("PE_Option_Item", 0, callFunction=True)

    # --- PartyEditor.close_window() ---

    def close_window(self) -> bool:
        """
        Closes the editor window

        Returns
        -------
        bool
            True if the window was closed, False otherwise (e.g. user cancelled)
        """
        # Ask to confirm if changes were made
        if self._unsaved_changes is True:
            if self.app.yesNoBox("Confirm Close", "There are unsaved changes. Are you sure you want to quit?",
                                 "Party_Editor") is False:
                return False

        self.app.hideSubWindow("Party_Editor", False)
        self.app.emptySubWindow("Party_Editor")

        # Cleanup
        if self.current_window == "Races":
            self.race_names.clear()
            self.attribute_names.clear()

        elif self.current_window == "Professions":
            self.profession_names.clear()
            self.attribute_names.clear()
            self.weapon_names.clear()
            self.armour_names.clear()

        elif self.current_window == "Special Abilities":
            self.profession_names.clear()
            self.attribute_names.clear()

        elif self.current_window == "Pre-Made":
            self.pre_made.clear()

        elif self.current_window == "Magic":
            self.routines.clear()
            self.routine_definitions.clear()
            self.spell_names_0.clear()
            self.spell_names_1.clear()
            self.attribute_checks.clear()
            self.attribute_names.clear()

        elif self.current_window == "Items":
            self.routine_definitions.clear()

        self.current_window = ""
        self._unsaved_changes = False

        return True

    # --- PartyEditor.generic_input() ---

    def _generic_input(self, widget: str) -> None:
        """
        Processes UI input from a widget shared across different parts of the editor

        Parameters
        ----------
        widget: str
            Name of the widget that generated the input
        """
        if widget == "PE_Cancel":
            self.close_window()

        elif widget == "PE_Check_Gender":
            self._unsaved_changes = True
            self.gender_by_profession = self.app.getCheckBox(widget)

        else:
            self.warning(f"Unimplemented widget callback from '{widget}'.")

    # --- PartyEditor._selected_routine_id() ---

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

    # --- PartyEditor._selected_spell_id() ---

    def _selected_routine_id(self) -> int:
        """

        Returns
        -------
        int:
            The index of the currently selected routine
        """
        if self.current_window == "Magic":
            routine_id = self._get_selection_index("PE_Option_Spell")
            if self.selected_index == 0:
                routine_id = routine_id + 16
        else:
            routine_id = self.selected_index

        return routine_id

    # --- PartyEditor._magic_input() ---

    def _magic_input(self, widget: str) -> None:
        """
        Processes UI input from a widget that is part of the Magic Editor sub-window

        Parameters
        ----------
        widget: str
            Name of the widget generating the input
        """
        if widget == "PE_Apply":
            if self.save_magic_data() is True:
                self.app.setStatusbar("Spell Data saved.")
                self._unsaved_changes = False
                self.close_window()
            else:
                self.app.setStatusbar("Error(s) encountered.")

        elif widget == "PE_Reload":
            self._read_spell_names()
            self._magic_input("PE_Spell_List")

        elif widget == "PE_Spell_List":
            # A new spell list has been selected
            self.selected_index = self._get_selection_index(widget)

            # Show which professions have access to this list
            message = ""
            if self.selected_index < 2:  # Don't show this list for common routines
                for p in range(len(self.caster_flags)):
                    if self.caster_flags[p] == 3 or self.caster_flags[p] == self.selected_index + 1:
                        if message != "":
                            message = message + ", "
                        message = message + self.profession_names[p]
                if len(message) < 1:
                    message = "(None)"
            self.app.clearMessage("PE_Magic_Professions")
            self.app.setMessage("PE_Magic_Professions", message)

            # Populate the spell option box with names from this list if needed
            self.app.clearOptionBox("PE_Option_Spell", callFunction=False)
            if self.selected_index == 0:
                names_list = self.spell_names_0
                selection = 0
            elif self.selected_index == 1:
                names_list = self.spell_names_1
                selection = 16
            else:  # Common routines
                names_list: List[str] = []
                for c in self.routines[32:]:
                    names_list.append(c.name)
                if len(names_list) < 1:
                    names_list.append("- No Common Routines Defined -")
                selection = 32
            self.app.changeOptionBox("PE_Option_Spell", names_list, index=0, callFunction=False)

            # Display info for the first spell in this list
            self.magic_info(selection)

        elif widget == "PE_Radio_MP":
            value = self.app.getRadioButton(widget)
            self._unsaved_changes = True
            if value[:1] == 'I':  # Incremental
                self.app.disableEntry("PE_MP_Display")
            else:
                self.app.enableEntry("PE_MP_Display")

        elif widget == "PE_Option_Spell":
            # A spell has been selected
            spell_id = self._selected_routine_id()
            # Adjust value for common routines
            if self._get_selection_index("PE_Spell_List") == 2:
                spell_id = spell_id + 32
            # Update widgets for the current selection
            self.magic_info(spell_id)

        elif widget == "PE_Incremental_MP":
            try:
                value = int(self.app.getEntry(widget), 10)
                if 0 < value < 255:
                    self.app.entry(widget, fg=colour.BLACK)
                    self._unsaved_changes = True
                else:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)
            except ValueError:
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget == "PE_MP_Display":
            # Changing the value of MP needed to make a spell available
            self._unsaved_changes = True
            spell_id = self._selected_routine_id()
            if spell_id < 32:
                try:
                    value = int(self.app.getEntry(widget), 10)
                    self.routines[spell_id].mp_display = value
                    self.app.entry(widget, fg=colour.BLACK)
                except ValueError:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget == "PE_MP_Cast":
            # Changing the value of MP deduced after casting a spell
            self._unsaved_changes = True
            spell_id = self._selected_routine_id()
            if spell_id < 32:
                try:
                    value = int(self.app.getEntry(widget), 10)
                    self.routines[spell_id].mp_cast = value
                    self.app.entry(widget, fg=colour.BLACK)
                except ValueError:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget == "PE_Spell_Address":
            self._unsaved_changes = True
            spell_id = self._selected_routine_id()
            try:
                value = int(self.app.getEntry(widget), 16)
                if 0x8000 <= value <= 0xFFFF:
                    self.routines[spell_id].address = value
                    self.app.entry(widget, fg=colour.BLACK)
                else:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)
            except ValueError:
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget == "PE_Spell_Flags":
            self._unsaved_changes = True
            spell_id = self._selected_routine_id()
            # Get selection index
            value = self.app.getOptionBox(widget)
            box = self.app.getOptionBoxWidget(widget)
            selection = box.options.index(value)
            # 0: Nowhere 1: Battle Only 2: Town, Continent, Dungeon 3: Continent Only 4: Dungeon Only
            # 5: Continent and Dungeon 6: Battle and Continent 7: Battle and Dungeon
            # 8: Battle, Continent, Dungeon 9: Everywhere
            if selection == 0:
                self.routines[spell_id].flags = 0x0
            elif selection == 1:
                self.routines[spell_id].flags = 0x2
            elif selection == 2:
                self.routines[spell_id].flags = 0x8
            elif selection == 3:
                self.routines[spell_id].flags = 0x4
            elif selection == 4:
                self.routines[spell_id].flags = 0x1
            elif selection == 5:
                self.routines[spell_id].flags = 0x5
            elif selection == 6:
                self.routines[spell_id].flags = 0x6
            elif selection == 7:
                self.routines[spell_id].flags = 0x3
            elif selection == 8:
                self.routines[spell_id].flags = 0x7
            elif selection == 9:
                self.routines[spell_id].flags = 0xF

        elif widget[:8] == "PE_Flag_":
            self._unsaved_changes = True
            # Calculate fine flags
            flag = 1
            value = 0
            for w in range(8):
                if self.app.getCheckBox(f"PE_Flag_0x{flag:02X}") is True:
                    value = value | flag
                flag = flag << 1
            # Save new value for fine flags
            spell_id = self._selected_routine_id()
            self.routines[spell_id].fine_flags = value

        elif widget[:12] == "PE_Map_Flag_":
            # Nothing to do here, this will be read when saving to ROM buffer
            pass

        elif widget == "PE_Spell_Definitions":
            spell_id = self._selected_routine_id()
            # Get selection index
            value = self.app.getOptionBox(widget)
            box = self.app.getOptionBoxWidget(widget)
            selection = box.options.index(value)
            # Get file name
            definitions = self.routine_definitions[selection]
            # Re-read spell data
            self._read_spell_data(definitions)
            # Show info for the currently selected spell again
            self.magic_info(spell_id)

        elif widget[:19] == "PE_Spell_String_ID_":
            try:
                value = int(self.app.getEntry(widget), 16)
                if 0 <= value <= 255:
                    self.app.entry(widget, fg=colour.BLACK)
                    self._unsaved_changes = True
                else:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)
            except ValueError:
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget[:23] == "PE_Button_Spell_String_":
            try:
                list_id = int(widget[-3:-2], 10)
                string_id = int(self.app.getEntry(f"PE_Spell_String_ID_{list_id}"), 16)
                if int(widget[-1:], 10) == 2:
                    string_id = string_id + 1
                # Open this string in the Eext Editor
                self.text_editor.show_window(string_id, "Special")
            except ValueError as e:
                self.warning(f"Error processing input from widget: '{widget}': {e}.")

        else:
            self.warning(f"Unimplemented Magic Editor widget input: '{widget}'.")

    # --- PartyEditor._parameter_input() ---

    def _parameter_input(self, widget: str) -> None:
        """
        Handles input from a routine "Parameters" frame
        """
        if widget[:8] == "PE_Bool_":
            # Changing a boolean spell parameter
            self._unsaved_changes = True
            routine_id = self._selected_routine_id()
            # Get parameter index
            parameter_id = int(widget[-2:], 10)
            # Set value
            value = 1 if self.app.getCheckBox(widget) is True else 0
            self.routines[routine_id].parameters[parameter_id].value = value

        elif widget[:16] == "PE_Attribute_Id_":
            self._unsaved_changes = True
            # Get index of currently selected routine or spell
            routine_id = self._selected_routine_id()

            # Set option box according to this value
            try:
                # Get parameter index
                parameter_id = int(widget[-2:], 10)

                value = int(self.app.getEntry(widget), 16)
                self.app.entry(widget, fg=colour.BLACK)
                if 6 < value < 0xB:
                    self.app.setOptionBox(f"PE_Attribute_List_Parameter_{parameter_id:02}", index=value - 7,
                                          callFunction=False)
                elif value == 0x33:
                    self.app.setOptionBox(f"PE_Attribute_List_Parameter_{parameter_id:02}", index=4,
                                          callFunction=False)
                else:
                    self.app.setOptionBox(f"PE_Attribute_List_Parameter_{parameter_id:02}", index=5,
                                          callFunction=False)

                # Set the value for this spell's parameter
                self.routines[routine_id].parameters[parameter_id].value = value

            except ValueError:
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget[:18] == "PE_Attribute_List_":
            self._unsaved_changes = True
            routine_id = self._selected_routine_id()

            # Get selection index
            value = self.app.getOptionBox(widget)
            box = self.app.getOptionBoxWidget(widget)
            selection = box.options.index(value)

            parameter_id = int(widget[-2:], 10)

            # Set value according to this selection
            self.app.clearEntry(f"PE_Attribute_Id_Parameter_{parameter_id:02}", callFunction=False)
            if 0 <= selection <= 3:
                value = selection + 7
            elif selection == 4:
                value = 0x33
            else:
                value = 0
            # Assign and show value
            self.routines[routine_id].parameters[parameter_id].value = value
            self.app.setEntry(f"PE_Attribute_Id_Parameter_{parameter_id:02}", f"0x{value:02X}", callFunction=False)

        elif widget[:7] == "PE_Hex_":
            try:
                parameter_id = int(widget[-2:], 10)
                routine_id = self._selected_routine_id()
                value = int(self.app.getEntry(widget), 16)
                self.routines[routine_id].parameters[parameter_id].value = value
                self.app.entry(widget, fg=colour.BLACK)
                self._unsaved_changes = True
            except ValueError as e:
                self.warning(f"Error processing input from widget: '{widget}': {e}.")
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget[:11] == "PE_Decimal_":
            try:
                parameter_id = int(widget[-2:], 10)
                routine_id = self._selected_routine_id()
                value = int(self.app.getEntry(widget), 10)
                self.routines[routine_id].parameters[parameter_id].value = value
                self.app.entry(widget, fg=colour.BLACK)
                self._unsaved_changes = True
            except ValueError as e:
                self.warning(f"Error processing input from widget: '{widget}': {e}.")
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget[:8] == "PE_Mark_":
            parameter_id = int(widget[-2:], 10)
            routine_id = self._selected_routine_id()

            # Get dictionary of values
            selection = self.app.getOptionBox(widget)
            # Each value represents one bit
            bit = 1
            value = 0
            for d in selection:
                if selection.get(d) is True:
                    value = value | bit
                bit = bit << 1
            self.routines[routine_id].parameters[parameter_id].value = value

        elif widget[:9] == "PE_Check_":
            parameter_id = int(widget[-2:], 10)
            routine_id = self._selected_routine_id()

            # Get selection index
            value = self.app.getOptionBox(widget)
            box = self.app.getOptionBoxWidget(widget)
            selection = box.options.index(value)

            # The value is the address of the check indexed by the selection
            if selection < len(self.attribute_checks):
                self.routines[routine_id].parameters[parameter_id].value = self.attribute_checks[selection].address
                self._unsaved_changes = True
            else:
                self.warning(f"Error processing input from widget: '{widget}': {selection} is not a valid check.")

        elif widget[:17] == "PE_String_Button_":
            routine_id = self._selected_routine_id()
            try:
                parameter_id = int(widget[-2:], 10)
                string_id = self.routines[routine_id].parameters[parameter_id].value
                # int(self.app.getEntry(f"PE_String_Id_Parameter_{parameter_id:02}"), 16)
                if 0 <= string_id <= 255:
                    self.text_editor.show_window(string_id, "Special")
            except ValueError:
                pass

        elif widget[:13] == "PE_String_Id_":
            try:
                parameter_id = int(widget[-2:], 10)
                routine_id = self._selected_routine_id()
                value = int(self.app.getEntry(widget), 16)
                if 0 <= value <= 255:
                    self.routines[routine_id].parameters[parameter_id].value = value
                    self.app.entry(widget, fg=colour.BLACK)
                    self._unsaved_changes = True
                else:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)
            except ValueError as e:
                self.warning(f"Error processing input from widget: '{widget}': {e}.")
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget[:7] == "PE_Map_":
            try:
                parameter_id = int(widget[-2:], 10)
                routine_id = self._selected_routine_id()
                value = self._get_selection_index(widget)
                self.routines[routine_id].parameters[parameter_id] = value
            except ValueError as e:
                self.warning(f"Error processing input from widget: '{widget}': {e}.")
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget[:7] == "PE_NPC_":
            try:
                parameter_id = int(widget[-2:], 10)
                routine_id = self._selected_routine_id()
                value = self._get_selection_index(widget)
                self.routines[routine_id].parameters[parameter_id] = value
                self._show_npc_sprite(value, f"PE_NPC_Sprite_{parameter_id:02}")
            except ValueError as e:
                self.warning(f"Error processing input from widget: '{widget}': {e}.")
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        else:
            self.warning(f"Unimplemented Parameter Editor widget input: '{widget}'.")

    # --- PartyEditor._races_input() ---

    def _races_input(self, widget: str) -> None:
        """
        Processes UI input from a widget that is part of the Races Editor sub-window

        Parameters
        ----------
        widget: str
            Name of the widget generating the input
        """
        if widget == "PE_Option_Race":
            value = self.app.getOptionBox(widget)
            box = self.app.getOptionBoxWidget(widget)
            # Subtract 1 since the first value is not selectable
            self.selected_index = box.options.index(value) - 1
            # Update widgets for the current selection
            self.race_info()

        elif widget == "PE_Apply":
            if self.save_races() is not False:
                self.app.setStatusbar("Race data saved.")
                self._unsaved_changes = False
                self.close_window()

        elif widget == "PE_Gender_By_Race":
            self._unsaved_changes = True
            self.gender_by_profession = not self.app.getCheckBox("PE_Gender_By_Race")

            if self.gender_by_profession:
                self.app.disableEntry("PE_Gender_Character")
            else:
                self.app.enableEntry("PE_Gender_Character")

        elif widget == "PE_Race_Names":
            # Make sure the text is not larger than 28 characters
            value: str = self.app.getTextArea(widget)
            if len(value) > 28:
                # Make text red to warn user
                self.app.textArea(widget, fg=colour.MEDIUM_RED)
            else:
                self.app.textArea(widget, fg=colour.BLACK)
                self._unsaved_changes = True

        elif widget == "PE_Update_Race_Names":
            # Make sure it's all uppercase (just for consistency)
            value: str = self.app.getTextArea("PE_Race_Names").upper()
            self.app.clearTextArea("PE_Race_Names", callFunction=False)
            self.app.textArea("PE_Race_Names", value=value)
            # Parse text, reading race names that are separated by newlines
            self.race_names = value.splitlines(False)

            # Make sure there are exactly 5 races, and each is at least one character long
            if len(self.race_names) > 5:
                self.race_names = self.race_names[:5]
            else:
                while len(self.race_names) < 5:
                    self.race_names.append(" ")
            for i in range(5):
                if len(self.race_names[i]) < 1:
                    self.race_names[i] = " "

            # Rebuild the option box
            race_list: List[str] = ["- Race -"]
            race_list = race_list + self.race_names
            self.app.changeOptionBox("PE_Option_Race", race_list, None, False)

        elif widget == "PE_Spin_Races":
            self.selectable_races = int(self.app.getSpinBox("PE_Spin_Races"), 10)
            self._unsaved_changes = True

        elif widget == "PE_Gender_Character":
            try:
                text: str = self.app.getEntry(widget)
                value: int = int(text, 16)
                if 0 < value < 256:
                    self._display_gender(value)
                    self.gender_char[self.selected_index] = value
                    self._unsaved_changes = True

            except ValueError:
                return

        elif widget == "PE_Menu_String_Id":
            value = self.app.getEntry(widget)
            try:
                self.menu_string_id = int(value, 16)
                self._unsaved_changes = True
            except ValueError:
                pass

        elif widget == "PE_Edit_Menu_String":
            self._unsaved_changes = True
            # Update the displayed string ID, in case the box contained an invalid value
            self._update_menu_string_entry()
            # Now we can show the "advanced" text editor
            self.text_editor.show_window(self.menu_string_id, "Menus / Intro")

        else:
            self.warning(f"Unimplemented widget callback from '{widget}'.")

    # --- PartyEditor._professions_input() ---

    def _professions_input(self, widget: str) -> None:
        """
        Processes UI input from a widget part of the Professions Editor sub-window

        Parameters
        ----------
        widget: str
            Name of the widget generating the input
        """
        if widget == "PE_Option_Profession":
            # Get selection index
            value = self.app.getOptionBox(widget)
            box = self.app.getOptionBoxWidget(widget)
            # Subtract 1 since the first value is not selectable
            self.selected_index = box.options.index(value) - 1
            # Update widgets
            self.profession_info()

        elif widget == "PE_Spin_Professions":
            value = self.app.getSpinBox("PE_Spin_Professions")
            try:
                self.selectable_professions = int(value, 10)
                self._unsaved_changes = True
            except ValueError:
                if value == '':
                    pass
                else:
                    self.warning(f"Invalid value '{value}' for professions count.")

        elif widget == "PE_Profession_Names":
            # Make sure the total length including newlines and string terminator is not over 59
            names = self.app.getTextArea(widget)
            if (len(names) + 1) > 59:
                self.app.textArea(widget, fg=colour.MEDIUM_RED)
            else:
                self.app.textArea(widget, fg=colour.BLACK)

        elif widget == "PE_Update_Profession_Names":
            # Make sure it's all uppercase (just for consistency)
            value: str = self.app.getTextArea("PE_Profession_Names").upper()
            self.app.clearTextArea("PE_Profession_Names", callFunction=False)
            self.app.textArea("PE_Profession_Names", value=value)
            # Parse text, reading profession names that are separated by newlines
            self.profession_names = value.splitlines(False)

            # Make sure there are exactly 11 professions, and each is at least one character long
            if len(self.profession_names) > 11:
                self.profession_names = self.profession_names[:11]
            else:
                while len(self.profession_names) < 11:
                    self.profession_names.append(" ")
            for i in range(11):
                if len(self.profession_names[i]) < 1:
                    self.profession_names[i] = " "

            # Rebuild the option box
            professions_list: List[str] = ["- Profession -"]
            professions_list = professions_list + self.profession_names
            self.app.changeOptionBox("PE_Option_Profession", professions_list, None, False)

        elif widget == "PE_Check_Gender":
            self.gender_by_profession = self.app.getCheckBox("PE_Check_Gender")
            self._unsaved_changes = True

        elif widget == "PE_Profession_Colours":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                self.colour_indices[self.selected_index] = box.options.index(value)
                # Update canvas
                self._load_profession_graphics()
                self._unsaved_changes = True

        elif widget == "PE_Sprite_Palette_Top" or widget == "PE_Sprite_Palette_Bottom":
            if self.selected_index >= 0:
                # Read both values
                value = self.app.getOptionBox("PE_Sprite_Palette_Top")
                box = self.app.getOptionBoxWidget("PE_Sprite_Palette_Top")
                top_value = box.options.index(value)

                value = self.app.getOptionBox("PE_Sprite_Palette_Bottom")
                box = self.app.getOptionBoxWidget("PE_Sprite_Palette_Bottom")
                bottom_value = box.options.index(value)

                # If only using one colour, we don't need to set the flag bit
                if top_value == bottom_value or (self.rom.has_feature("2-colour sprites") is False):
                    self.sprite_colours[self.selected_index] = top_value

                # Set the MSB for two-colour sprites, then use bits 0-1 for bottom and 2-3 for top
                else:
                    self.sprite_colours[self.selected_index] = 0x80 | ((top_value << 2) | bottom_value)

                self._unsaved_changes = True

                # Update sprite
                self._show_profession_sprite()

        elif widget == "PE_Primary_0":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                primary_0 = box.options.index(value)

                self.primary_attributes[self.selected_index][0] = primary_0

                self._unsaved_changes = True

        elif widget == "PE_Primary_1":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                primary_1 = box.options.index(value)

                self.primary_attributes[self.selected_index][1] = primary_1

                self._unsaved_changes = True

        elif widget == "PE_Option_Weapon":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                weapon = box.options.index(value)

                self.best_weapon[self.selected_index] = weapon

                self._unsaved_changes = True

        elif widget == "PE_Option_Armour":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                armour = box.options.index(value)

                self.best_weapon[self.selected_index] = armour

                self._unsaved_changes = True

        elif widget == "PE_HP_Base":
            value = self.app.getEntry(widget)
            try:
                self.hp_base = int(value, 10)
                self._unsaved_changes = True
            except ValueError:
                pass

        elif widget == "PE_HP_Bonus":
            if self.selected_index >= 0:
                value = self.app.getEntry(widget)
                try:
                    self.hp_bonus[self.selected_index] = int(value, 10)
                    self._unsaved_changes = True
                except ValueError:
                    pass

        elif widget == "PE_Thieving_Bonus":
            if self.selected_index >= 0:
                value = self.app.getEntry(widget)
                try:
                    bonus = int(value, 10)
                    if 156 >= bonus >= 0:
                        self.thief_bonus[self.selected_index] = bonus
                        self.app.entry(widget, fg=colour.BLACK)
                        self._unsaved_changes = True
                        self._thieving_chance(bonus)
                    else:
                        self.app.entry(widget, fg=colour.MEDIUM_RED)
                except ValueError:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget == "PE_Apply":
            if self.save_professions() is not False:
                self.app.setStatusbar("Profession data saved.")
                self._unsaved_changes = False
                self.close_window()

        elif widget == "PE_Menu_String_Id":
            value = self.app.getEntry(widget)
            try:
                self.menu_string_id = int(value, 16)
                self._unsaved_changes = True
            except ValueError:
                pass

        elif widget == "PE_Edit_Menu_String":
            # Update the displayed string ID, in case the box contained an invalid value
            self._update_menu_string_entry()
            # Now we can show the "advanced" text editor
            self.text_editor.show_window(self.menu_string_id, "Menus / Intro")

        elif widget == "PE_Check_Caster_0":
            if self.selected_index >= 0:
                self._unsaved_changes = True
                self.caster_flags[self.selected_index] = self.caster_flags[self.selected_index] | 1

        elif widget == "PE_Check_Caster_1":
            if self.selected_index >= 0:
                self._unsaved_changes = True
                self.caster_flags[self.selected_index] = self.caster_flags[self.selected_index] | 2

        elif widget == "PE_Overwrite_MP":
            self._unsaved_changes = True
            if self.app.getCheckBox(widget) is True:
                self.app.enableOptionBox("PE_Option_MP")
                self.app.enableEntry("PE_Fixed_MP")
            else:
                self.app.disableOptionBox("PE_Option_MP")
                self.app.disableEntry("PE_Fixed_MP")

        else:
            self.warning(f"Unimplemented widget callback: '{widget}'.")

    def _pre_made_input(self, widget: str) -> None:
        """
        Processes UI input from a widget part of the Professions Editor sub-window

        Parameters
        ----------
        widget: str
            Name of the widget generating the input
        """
        if widget == "PE_Apply":
            if self.save_pre_made() is not False:
                self.app.setStatusbar("Pre-made character data saved.")
                self._unsaved_changes = False
                self.close_window()

        elif widget == "PE_Character_Name":
            name = self.app.getEntry(widget)
            # Ignore empty names
            if len(name) < 1:
                return
            # Truncate string if needed
            self.pre_made[self.selected_index].name = name[:5].upper()
            self._unsaved_changes = True

        elif widget[:12] == "PE_Attribute":
            # Get the index of the attribute we are editing
            try:
                index = int(widget[-1:], 10)
                # Read the value from this widget
                value = int(self.app.getEntry(widget), 10)
                # Assign this value to the selected attribute
                self.pre_made[self.selected_index].attributes[index] = value

                # Calculate and show new total points
                total = 0
                for a in range(4):
                    total = total + self.pre_made[self.selected_index].attributes[a]
                self.app.label("PE_Total_Points", f"{total}")

                self._unsaved_changes = True

            except ValueError:
                return

            except IndexError:
                return

        elif widget == "PE_Character_Index":
            value = self.app.getOptionBox(widget)
            try:
                index = int(value, 10)
                if 0 <= index <= 11:
                    # Show name
                    self.selected_index = index
                    self.app.setEntry("PE_Character_Name", self.pre_made[index].name, callFunction=False)

                    # Show race, profession (+1 because option 0 is not part of the selectable items)
                    # TODO Check that index is within selectable options, set to default if not
                    self.app.setOptionBox("PE_Race", self.pre_made[index].race + 1, callFunction=False)
                    self.app.setOptionBox("PE_Profession", self.pre_made[index].profession + 1, callFunction=False)

                    # Show attributes, also calculate total
                    total = 0
                    for a in range(4):
                        self.app.clearEntry(f"PE_Attribute_{a}", callFunction=False)
                        self.app.setEntry(f"PE_Attribute_{a}", f"{self.pre_made[index].attributes[a]}",
                                          callFunction=False)
                        total = total + self.pre_made[index].attributes[a]

                    # Show total attribute points
                    self.app.label("PE_Total_Points", f"{total}")

                    self._unsaved_changes = True

            except ValueError:
                return

        else:
            self.warning(f"Unimplemented input from widget: {widget}.")

    # --- PartyEditor._special_input() ---

    def _special_input(self, widget: str) -> None:
        """
        Handles input events from widgets in the Special Abilities window

        Parameters
        ----------
        widget: str
            Name of the widget that is generating the event
        """
        if widget == "PE_Apply":
            if self.save_special_abilities() is not False:
                self.app.setStatusbar("Special Abilities saved.")
                self._unsaved_changes = False
                self.close_window()

        elif widget[:14] == "PE_Profession_":
            # Maybe perform sanity checks, not needed in the current implementation
            pass

        elif widget == "PE_Damage_1":
            # Get the index of the new selection
            box = self.app.getOptionBoxWidget(widget)
            value = box.options.index(self.app.getOptionBox(widget))

            # Set the custom value to the correct index for this selection
            self.app.disableEntry("PE_Custom_1")
            if 0 <= value <= 3:
                # Attribute-based
                value = value + 0x7
            elif value == 4:
                # Level-based
                value = 0x33
            else:
                # Allow custom entry
                try:
                    value = int(self.app.getEntry("PE_Custom_1"), 16)
                    self._unsaved_changes = True
                except ValueError:
                    value = 0x7
                self.app.enableEntry("PE_Custom_1")

            self.app.setEntry("PE_Custom_1", f"0x{value:02X}", callFunction=False)

        elif widget == "PE_Damage_2":
            # Get the index of the new selection
            box = self.app.getOptionBoxWidget(widget)
            value = box.options.index(self.app.getOptionBox(widget))

            # Set the custom value to the correct index for this selection
            self.app.disableEntry("PE_Custom_2")
            if 0 <= value <= 3:
                # Attribute-based
                value = value + 0x7
            elif value == 4:
                # Level-based
                value = 0x33
            elif value == 5:
                # Weapon-based
                value = 0x34
            else:
                # Allow custom entry
                try:
                    value = int(self.app.getEntry("PE_Custom_2"), 16)
                    self._unsaved_changes = True
                except ValueError:
                    value = 0x7
                self.app.enableEntry("PE_Custom_2")

            self.app.setEntry("PE_Custom_2", f"0x{value:02X}", callFunction=False)

        elif widget == "PE_Custom_1" or widget == "PE_Custom_2" or widget == "PE_Adjustment_3":
            # Sanity checks on value could be performed here. For now they are done when trying to apply changes.
            pass

        elif widget == "PE_Adjustment_2":
            # Get selection index
            box = self.app.getOptionBoxWidget(widget)
            value = box.options.index(self.app.getOptionBox(widget))
            self._unsaved_changes = True
            # Only enable input from adjustment value if needed
            if value == 1 or value == 2:
                self.app.enableEntry("PE_Adjustment_3")
            else:
                self.app.disableEntry("PE_Adjustment_3")

        else:
            self.warning(f"Unimplemented Special Editor input for widget: {widget}.")

    # --- PartyEditor._weapons_input() ---

    def _weapons_input(self, widget: str) -> None:
        """
        Processes input for widgets specific to the "Weapons" sub-window.

        Parameters
        ----------
        widget: str
            Name of the widget generating the event.
        """
        if widget == "PE_Apply":
            if self.save_weapon_armour_data() is True:
                self.app.setStatusbar("Weapon/Armour Data saved.")
                self._unsaved_changes = False
                self.close_window()
            else:
                self.app.setStatusbar("Error(s) encountered.")

        elif widget == "PE_Option_Weapon":
            value = self._get_selection_index(widget)
            self.weapon_info(value)

        elif widget == "PE_Option_Armour":
            value = self._get_selection_index(widget)
            self.armour_info(value)

        elif widget == "PE_Option_Throwing_Weapon":
            value = self._get_selection_index(widget)
            # Check that it's a melee weapon
            if self.weapon_type[value] != 0:
                if self.app.yesNoBox("Throwing Weapon",
                                     "For this to work, the weapon needs to be set to 'Melee' type.\n" +
                                     f"Do you want to change {self.weapon_names[value]}'s type to Melee?",
                                     "Party_Editor") is True:
                    self.weapon_type[value] = 0
                    if self._get_selection_index("PE_Option_Weapon") == value:
                        self.weapon_info(value)

        elif widget == "PE_Weapon_Ranged":
            value = self._get_selection_index("PE_Option_Weapon")
            self.weapon_type[value] = 1 if self.app.getCheckBox(widget) is True else 0
            # TODO If changing a weapon type to ranged, make sure this isn't the throwing weapon

        elif widget[:16] == "PE_Armour_Parry_":
            try:
                value = int(self.app.getEntry(widget), 10)
                if 255 >= value >= 0:
                    self.app.entry(widget, fg=colour.BLACK)
                    self.armour_info(self._get_selection_index("PE_Option_Armour"))
                else:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)
            except ValueError:
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget == "PE_Special_Dialogue":
            try:
                value = int(self.app.getEntry(widget), 16)
                if value > 0xFF:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)
                else:
                    self.app.entry(widget, fg=colour.BLACK)
            except ValueError:
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget == "PE_Button_Special_Dialogue":
            try:
                value = int(self.app.getEntry("PE_Special_Dialogue"), 16)
                if value <= 0xFF:
                    self.text_editor.show_window(value, "Special")
            except ValueError:
                self.app.warningBox("Special", f"Invalid string ID: '{self.app.getEntry('PE_Special_Dialogue')}'.")

        else:
            self.warning(f"Unimplemented Weapons/Armour Editor input for widget: {widget}.")

    # --- PartyEditor._items_input() ---

    def _items_input(self, widget: str) -> None:
        """
        Processes input for widgets specific to the "Items" sub-window.

        Parameters
        ----------
        widget: str
            Name of the widget generating the event.
        """
        if widget == "PE_Apply":
            if self.save_item_data() is True:
                self.app.setStatusbar("Item Data saved.")
                self._unsaved_changes = False
                self.close_window()
            else:
                self.app.setStatusbar("Error(s) encountered.")

        elif widget == "PE_Option_Item":
            self.selected_index = self._get_selection_index(widget)
            self.item_info(self.selected_index)

        elif widget == "PE_Definitions":
            value = self._get_selection_index(widget)
            self._read_item_data(self.routine_definitions[value])
            self.item_info(self.selected_index)

        elif widget == "PE_Item_Name":
            name = self.app.getEntry(widget)
            if len(name) > 12:
                name = name[:12]
                self.app.clearEntry(widget, callFunction=False, setFocus=False)
            self.routines[self.selected_index].name = name
            self._unsaved_changes = True

        elif widget == "PE_Item_Consumption":
            try:
                value = int(self.app.getEntry(widget), 10)
                self.routines[self.selected_index].mp_cast = value
                self.app.entry(widget, fg=colour.BLACK)
            except ValueError:
                self.app.entry(widget, fg=colour.MEDIUM_RED)
                return

        elif widget == "PE_Item_Address":
            try:
                value = int(self.app.getEntry(widget), 16)
                if 0xFFFF >= value >= 0x8000:
                    self.routines[self.selected_index].address = value
                    self._unsaved_changes = True
                    self.app.entry(widget, fg=colour.BLACK)
                else:
                    self.app.entry(widget, fg=colour.MEDIUM_RED)
            except ValueError:
                self.app.entry(widget, fg=colour.MEDIUM_RED)

        elif widget[:8] == "PE_Flag_":
            self._unsaved_changes = True
            # Re-calculate fine flags
            flag = 1
            value = 0
            for w in range(8):
                if self.app.getCheckBox(f"PE_Flag_0x{flag:02X}") is True:
                    value = value | flag
                flag = flag << 1
            # Save new value for fine flags
            self.routines[self.selected_index].fine_flags = value

        else:
            self.warning(f"Unimplemented Item Editor input for widget: {widget}.")

    # --- PartyEditor._update_weapon_names() ---

    def _update_weapon_names(self) -> None:
        """
        Sets the name of the currently selected weapon and then updates the list for the Option Box widget.
        """
        selection = self._get_selection_index("PE_Option_Weapon")
        name = self.app.getEntry("PE_Weapon_Name")
        max_length = 12 if selection == 0 else 9
        if len(name) > 0:
            self.weapon_names[selection] = name[:max_length].upper()
            self.app.changeOptionBox("PE_Option_Weapon", options=self.weapon_names, index=selection, callFunction=False)
            self._unsaved_changes = True

    # --- PartyEditor._update_armour_names() ---

    def _update_armour_names(self) -> None:
        """
        Sets the name of the currently selected armour and then updates the list for the Option Box widget.
        """
        selection = self._get_selection_index("PE_Option_Armour")
        name = self.app.getEntry("PE_Armour_Name")
        max_length = 12 if selection == 0 else 9
        if len(name) > 0:
            self.armour_names[selection] = name[:max_length].upper()
            self.app.changeOptionBox("PE_Option_Armour", options=self.armour_names, index=selection, callFunction=False)
            self._unsaved_changes = True

    # --- PartyEditor._update_item_names() ---

    def _update_item_names(self) -> None:
        names_list: List[str] = []
        for i in self.routines:
            names_list.append(i.name)
        self.app.changeOptionBox("PE_Option_Item", names_list, index=self.selected_index, callFunction=False)

    # --- PartyEditor._update_item_parameters() ---

    def _update_item_parameters(self) -> None:
        i = self.selected_index

        definition = self._get_selection_index("PE_Definitions")

        parser = configparser.ConfigParser()
        parser.read(self.routine_definitions[definition])

        if parser.has_section(f"TOOL_{i}"):
            values = self._decode_routine(i, self.routines[i].address, "TOOL", parser)
            if values["Custom"] is False:
                self.routines[i].custom_code = False
                self.routines[i].notes = values["Notes"]
                self.routines[i].parameters = values["Parameters"]

            else:
                self.routines[i].custom_code = True

        self.item_info(self.selected_index)

    # --- PartyEditor._read_race_names() ---

    def _read_race_names(self) -> None:
        """
        Reads uncompressed text used to show race names in the Status screen from ROM, and caches it as ASCII strings
        """
        # Clear previous values
        self.race_names.clear()

        # Read pointer
        address = self.rom.read_word(0xC, 0x0A435)

        for r in range(5):
            data = bytearray()

            # Read strings byte by byte: they are separated by 0xFD
            character = self.rom.read_byte(0xC, address)
            address = address + 1

            while character != 0xFD and character != 0xFF:
                data.append(character)
                character = self.rom.read_byte(0xC, address)
                address = address + 1

            # Convert string to ASCII and add to list
            self.race_names.append(exodus_to_ascii(data))

    # --- PartyEditor._read_profession_names() ---

    def _read_profession_names(self) -> None:
        """
        Reads uncompressed text used to show profession names in the Status screen from ROM, and caches it as a list
        of ASCII strings
        """
        # Clear previous values
        self.profession_names.clear()

        # Read profession names pointer
        address = self.rom.read_word(0xC, 0x0A439)

        for r in range(11):
            data = bytearray()

            # Read strings byte by byte: they are separated by 0xFD
            character = self.rom.read_byte(0xC, address)
            address = address + 1

            while character != 0xFD and character != 0xFF:
                data.append(character)
                character = self.rom.read_byte(0xC, address)
                address = address + 1

            # Convert string to ASCII and add to list
            ascii_string = exodus_to_ascii(data)
            self.profession_names.append(ascii_string)
            # profession_names = profession_names + '\n' + ascii_string

    # --- PartyEditor._read_item_names() ---

    def _read_item_names(self) -> List[str]:
        """
        Reads the names of the items used for the "TOOLS" menu into the PartyEditor routines (these will be appended
        to the bottom of the routines list if not empty)

        Returns
        -------
        List[str]:
            A list of strings containing the names only.
        """
        names: List[str] = []

        # Read 81 bytes from bank $0D, this is where the names are stored
        values = self.rom.read_bytes(0xD, 0x9B09, 81)

        # Each should be at least 8 bytes long (padded with spaces) to a maximum of 10 bytes, and followed by 0xFD
        # The last name is followed by 0xFF
        converted = exodus_to_ascii(values).split('\n')

        for i in range(len(converted)):
            if converted[i][0] == '~':
                break
            stripped = converted[i].rstrip()
            self.routines.append(Routine(name=stripped))
            names.append(stripped)

        return names

    # --- PartyEditor._read_definitions() ---

    def _read_definitions(self) -> List[str]:
        """
        Finds and reads definition files (.def), populates PartyEditor's routine_definitions

        Returns
        -------
        List[str]:
            A list of strings containing the version info of each definitions, useful for creating option boxes.
        """
        # Find spell definition files
        self.routine_definitions.clear()
        definitions = glob.glob("*.def")
        definitions_list: List[str] = []

        # Get spell definition files info
        for d in definitions:
            parser = configparser.ConfigParser()
            try:
                parser.read(d)
                if parser.has_section("INFO"):
                    definitions_list.append(parser["INFO"].get("VERSION", d))
                    self.routine_definitions.append(d)
            except configparser.DuplicateOptionError as error:
                self.app.errorBox("Definition Parser", f"ERROR parsing routine definitions file: {error}.",
                                  "Party_Editor")
            del parser

        if len(definitions_list) < 1:
            self.app.errorBox("Spell Editor", "ERROR: Could not find any spell definitions.\n" +
                              "Make sure at least one spells_xxx.ini file is present in the editor's directory.",
                              "Party_Editor")
            definitions_list.append("- No Spell Definitions Found -")

        return definitions_list

    # --- PartyEditor._read_spell_data() ---

    def _read_spell_data(self, config_file: str = "Ultima - Exodus Remastered.def") -> int:
        """
        Reads data for each spell from ROM.

        Returns
        -------
        int:
            -2 if the ROM is using custom code (e.g. spell tables and/or menu calls can't be found).<br/>
            -1 if the ROM uses "uneven MP" code.<br/>
            If the ROM uses the standard "incremental MP" code, the value of the increment will be returned (0-255).
        """
        # Show progress
        self.app.setLabel("PE_Progress_Label", "Decoding spell data...")
        progress = 0.0
        self.app.setMeter("PE_Progress_Meter", progress)
        self.app.showSubWindow("PE_Progress")

        root = self.app.topLevel
        root.update()

        # Clear local spell data first
        self.routines.clear()

        # Read table
        # This will be set to True if the code doesn't match what we're looking for
        custom_code = False

        # Get spell table address
        address = self.rom.read_word(0xF, 0xD3BD)

        if custom_code is True:
            # Everything is custom, we can't even find the table
            for s in range(32):
                self.routines.append(Routine())
            self.app.hideSubWindow("PE_Progress")
            return -2

        # First, try to determine whether this ROM uses the "incremental" MP system, or the "uneven cost" one
        # Normally, this code is present:
        # D441    LDY #$2F
        # D443    LDA ($99),Y
        # D445    LDY #$00
        # D447    INY
        # D448    SEC
        # D449    SBC #$05  ; <-- Incremental cost
        # D44B    BCS $D447
        # D44D    CPY #$10
        # D44F    BCC $D453
        # D451    LDY #$10
        # D453    TYA
        # D454    RTS

        progress = progress + 5.0
        self.app.setMeter("PE_Progress_Meter", progress)
        root.update()

        bytecode = self.rom.read_bytes(0xF, 0xD448, 3)
        if bytecode[0] == 0x38 and bytecode[1] == 0xE9:  # $38 = SEC, $E9 = SBC d
            self.info("Incremental MP subroutine detected.")
            incremental_mp = bytecode[2]

        else:
            self.info("Detecting uneven MP subroutine...")
            incremental_mp = -1
            # No "incremental MP" code was found, try to detect "uneven MP" code
            # First, this call is JSR $D415 for incremental MP and JSR $D419 for uneven
            bytecode = self.rom.read_bytes(0xF, 0xD37D, 3)

            if bytecode[0] != 0x20:  # $20 = JSR d
                # Unrecognised code
                incremental_mp = -2
                self.warning(f"Unrecognised bytecode {bytecode} at 0F:D37D.")

            else:
                if bytecode[1] == 0x19:
                    # This points to the custom routine that builds the "cleric" spells list
                    # Make sure that is so, we expect:
                    # LDX #$40
                    # LDY #$2F
                    bytecode = self.rom.read_bytes(0xF, 0xD419, 4)
                    if bytecode != b'\xA2\x40\xA0\x2F':
                        # Unrecognised code
                        incremental_mp = -2
                        self.warning(f"Unrecognised bytecode {bytecode} at 0F:D419.")

        progress = progress + 5.0
        self.app.setMeter("PE_Progress_Meter", progress)
        root.update()

        # Keep track of previous spell's MP cost for incremental values
        mp_cost = 0

        self.app.setStatusbar("Decoding spell data...")

        parser = configparser.ConfigParser()
        parser.read(config_file)

        # Read spell data from the table
        self._ignore_warnings = False
        for s in range(32):
            # Keep track of previous spell's MP cost for incremental values
            if incremental_mp > -1:
                if s == 0 or s == 16:
                    mp_cost = 0
                else:
                    mp_cost = mp_cost + incremental_mp

            spell = Routine()
            spell.flags = self.rom.read_byte(0xF, address)
            spell.fine_flags = self.rom.read_byte(0xB, 0xAF47 + s)

            # The MP value from the table is not used unless we inject our "uneven MP" code
            if incremental_mp > -1:
                spell.mp_display = mp_cost
            else:
                spell.mp_display = self.rom.read_byte(0xF, address + 1)

            spell.address = self.rom.read_word(0xF, address + 2)

            # Read routine and try to find MP to cast + parameters
            values = self._decode_routine(s, spell.address, "SPELL", parser)

            progress = progress + 5.0
            self.app.setMeter("PE_Progress_Meter", progress)
            root.update()

            spell.notes = values["Notes"]
            if values["Custom"] is True:
                spell.custom_code = True
            else:
                spell.custom_code = False
                spell.mp_cast = values["MP"]
                spell.mp_address = values["MP Address"]
                spell.parameters = values["Parameters"]

            # Store data
            self.routines.append(spell)

            # Each entry is 4 bytes long, move to the next one
            address = address + 4

        # Read attribute check definitions
        # Expect a maximum of 8 checks
        self.attribute_checks.clear()
        for c in range(8):
            if parser.has_section(f"CHECK_{c}") is False:
                break
            name = parser[f"CHECK_{c}"].get("NAME", f"Check#{c}")
            address = parser[f"CHECK_{c}"].get("ADDRESS", "0")
            try:
                value = int(address, 16)
                if value < 0x8000 or value > 0xFFFF:
                    self.warning(f"Invalid address for Check '{name}' (0x{value:0x4}).")
                    continue
            except ValueError:
                self.warning(f"Invalid address for Check '{name}' ({address}).")
                continue

            progress = progress + 5.0
            self.app.setMeter("PE_Progress_Meter", progress)
            root.update()

            check = AttributeCheck()
            check.name = name
            check.address = value
            self.attribute_checks.append(check)

        # Read common code used by various spells (single-hit missiles, multi-hit magic...)
        for s in range(16):
            if parser.has_section(f"COMMON_{s}") is False:
                break
            spell = Routine()
            values = self._decode_routine(s, 0, "COMMON", parser)

            progress = progress + 5.0
            self.app.setMeter("PE_Progress_Meter", progress)
            root.update()

            spell.notes = values["Notes"]
            spell.name = values["Name"]
            # Only show parameters if code is not customised
            if values["Custom"] is True:
                spell.custom_code = True
            else:
                spell.custom_code = False
                # These don't have an MP cost, so we use the MP Address value as the routine address
                spell.address = values["MP Address"]
                spell.parameters = values["Parameters"]
            self.routines.append(spell)

        self.app.setStatusbar("Spell data decoded.")

        self._ignore_warnings = True

        # Hide progress
        self.app.hideSubWindow("PE_Progress")

        return incremental_mp

    # --- PartyEditor._read_item_data() ---

    def _read_item_data(self, config_file: str = "Ultima - Exodus Remastered.def") -> int:
        """
        Reads routine parameters for the items in the "TOOLS" menu.

        Parameters
        ----------
        config_file: str
            Name of the file containing routine definitions.

        Returns
        -------
        int:
            Number of item routine definitions found.
        """
        count: int = 0

        # Read addresses, item consumption values and usability flags from tables in ROM
        for i in range(len(self.routines)):
            self.routines[i].address = self.rom.read_word(0xF, 0xDBB1 + (i * 2))
            self.routines[i].mp_cast = int.from_bytes([self.rom.read_byte(0xF, 0xDBC3 + i)], 'little', signed=True)
            self.routines[i].fine_flags = self.rom.read_byte(0xB, 0xAF67 + i)

        # Parse definitions
        parser = configparser.ConfigParser()
        parser.read(config_file)

        for i in range(len(self.routines)):
            if parser.has_section(f"TOOL_{i}"):
                values = self._decode_routine(i, self.routines[i].address, "TOOL", parser)
                if values["Custom"] is False:
                    self.routines[i].custom_code = False
                    self.routines[i].notes = values["Notes"]
                    self.routines[i].parameters = values["Parameters"]

                else:
                    self.routines[i].custom_code = True

                count = count + 1
            else:
                break

        return count

    # --- PartyEditor._decode_routine() ---

    def _decode_routine(self, routine_id: int, address: int, routine_type: str,
                        parser: configparser.ConfigParser) -> dict:
        """
        Tries to decode a spell's routine to extract its parameters.

        Parameters
        ----------
        routine_id: int
            The index of the routine, so we know what to look for and where.

        address: int
            The base address of the routine, so we can also work with relocated (but unchanged) code.
            Common routines take their address from the definitions file instead.

        routine_type: str
            Base name of the section we want to read: "SPELL", "COMMON", "TOOL", "COMMAND", "SPECIAL".

        parser: ConfigParser
            A reference to the configuration parser containing the routine definitions.

        Returns
        -------
        dict:
            An a dictionary: {"Custom": bool, "Name": str, "MP": int, "MP Address": int, "Notes": str,
            "parameters": List[Spell.Parameter]}.
        """
        decoded = {
            "Custom": False,
            "Name": "",
            "MP": 0,
            "MP Address": 0,
            "Notes": "",
            "Parameters": []
        }

        if parser.has_section(f"{routine_type}_{routine_id}") is False:
            decoded["Custom"] = True
            self.warning(f"WARNING: Section [{routine_type}_{routine_id}] not found.")
            return decoded
        section = parser[f"{routine_type}_{routine_id}"]
        decoded["Name"] = section.get("NAME", "(Unnamed Routine)")

        # Get actual MP cost
        if routine_type == "SPELL":
            offset = section.get("MP", "zero")
            if offset == "zero":
                decoded["MP"] = 0
                decoded["MP Address"] = 0
            else:
                try:
                    mp_address = address + int(offset, 16)
                    decoded["MP"] = self.rom.read_byte(0xF, mp_address)
                    decoded["MP Address"] = mp_address
                except ValueError:
                    self.app.warningBox(f"Decode {routine_type}",
                                        f"WARNING: Definition file contains invalid MP offset: " +
                                        f"'{offset}' for spell #{routine_id}.", "Party_Editor")
                    decoded["Custom"] = True
                    return decoded

        elif routine_type == "COMMON":
            # Common routines use the MP Address field as the routine's address
            try:
                decoded["MP Address"] = int(section.get("ADDRESS", "0"), 16)
                address = decoded["MP Address"]
            except ValueError:
                address = 0
            if address == 0:
                self.app.errorBox(f"Decode {routine_type} Routine",
                                  f"ERROR: Routine #{routine_id} has invalid or no address", "Party_Editor")
                return decoded

        # Read notes, if any
        decoded["Notes"] = section.get("NOTES", "").replace("\\n", "\n")

        # Read parameters (allow a maximum of 16)
        parameters: List[Parameter] = []
        for p in range(16):
            # Description
            try:
                description = section.get(f"DESCRIPTION_{p}", "none")
            except configparser.InterpolationSyntaxError as e:
                self.app.warningBox(f"Decode {routine_type}",
                                    f"Error parsing description #{p} for {routine_type} #{routine_id}:" +
                                    f"\n'{e.message}'.", "Party_Editor")
                description = "(SYNTAX ERROR IN DESCRIPTION)"

            if description == "none":
                # Found last parameter
                break

            parameter = Parameter()
            parameter.description = description

            # Type, if any
            value = section.get(f"TYPE_{p}", "DECIMAL")
            if value[0] == 'D':
                parameter.type = Parameter.TYPE_DECIMAL
            elif value[0] == 'H':
                parameter.type = Parameter.TYPE_HEX
            elif value[0] == 'P':
                parameter.type = Parameter.TYPE_POINTER
            elif value[0] == 'S':
                parameter.type = Parameter.TYPE_STRING
            elif value[0] == 'A':
                parameter.type = Parameter.TYPE_ATTRIBUTE
            elif value[0] == 'B':
                parameter.type = Parameter.TYPE_BOOL
            elif value[0] == 'C':
                parameter.type = Parameter.TYPE_CHECK
            elif value[0] == 'L':
                parameter.type = Parameter.TYPE_LOCATION
            elif value[0] == 'M':
                parameter.type = Parameter.TYPE_MARK
            else:
                self.warning(f"Invalid type '{value}' for parameter #{p} in {routine_type} #{routine_id}.\n" +
                             "Using defaults.")
                parameter.type = Parameter.TYPE_DECIMAL

            # Pointer, if any
            value = section.get(f"POINTER_{p}", "none")
            if value != "none":
                try:
                    pointer_offset = int(value, 16)
                    pointer = self.rom.read_word(0xF, address + pointer_offset)
                    if pointer < 0x8000 or pointer > 0xFFFF:
                        if self._ignore_warnings is False:
                            if self.app.okBox(f"Decode {routine_type}",
                                              f"WARNING: {routine_type} #{routine_id} has invalid pointer '{value}' " +
                                              f"for parameter #{p}.\n\nClick 'Cancel' to ignore further warnings.",
                                              "Party_Editor") is False:
                                self._ignore_warnings = True
                        continue

                except ValueError:
                    self.app.warningBox(f"Decode {routine_type}",
                                        f"WARNING: {routine_type} #{routine_id} has invalid pointer '{value}' " +
                                        f"for parameter #{p}.",
                                        "Party_Editor")
                    continue
            else:
                pointer = 0

            # Offset
            value = section.get(f"OFFSET_{p}")
            if value is None:
                self.app.warningBox(f"Decode {routine_type}",
                                    f"WARNING: {routine_type} #{routine_id} has no offset for parameter #{p}.",
                                    "Party_Editor")
                continue

            try:
                offset = int(value, 16)

            except ValueError:
                self.app.warningBox(f"Decode {routine_type}",
                                    f"WARNING: {routine_type} #{routine_id} has invalid offset '{value}' " +
                                    f"for parameter #{p}.", "Party_Editor")
                continue

            # If a pointer was specified, calculate the offset based on that
            if pointer > 0:
                parameter_address = pointer + offset

            # Otherwise, use the spell address
            else:
                parameter_address = address + offset

            parameter.address = parameter_address

            # Figure out which bank contains this parameter
            bank = 0xF if parameter.address >= 0xC000 else 0

            # We need to know if the parameter is a Word or Byte, and we read the op code for that
            code = self.rom.read_byte(bank, parameter.address - 1)
            if code == 0x20 or code == 0x4C or code == 0xAD or code == 0xBD:
                # Read Word
                parameter.value = self.rom.read_word(bank, parameter.address)
                # These must be 8-bit values
                if (parameter.type == parameter.TYPE_LOCATION or parameter.type == parameter.TYPE_ATTRIBUTE or
                        parameter.type == parameter.TYPE_STRING or parameter.type == parameter.TYPE_BOOL or
                        parameter.type == parameter.TYPE_MARK or parameter.type == parameter.TYPE_NPC):
                    if self._ignore_warnings is False:
                        if self.app.okBox("Decode Routine",
                                          f"WARNING: {routine_type} #{routine_id}'s Parameter #{p} must be an 8-bit " +
                                          "value, but is preceeded by 16-bit parameter instruction.\n\n" +
                                          "Click 'Cancel' to ignore further warnings.", "Party_Editor") is False:
                            self._ignore_warnings = True
            else:
                # Read Byte
                parameter.value = self.rom.read_byte(bank, parameter.address)
                # Pointers and Checks must be 16-bit
                if parameter.type == parameter.TYPE_POINTER or parameter.type == parameter.TYPE_CHECK:
                    if self._ignore_warnings is False:
                        if self.app.okBox("Decode Routine",
                                          f"WARNING: Spell #{routine_id}'s Parameter #{p} must be a 16-bit value, " +
                                          "but is preceeded by 8-bit parameter instruction.\n\n" +
                                          "Click 'Cancel' to ignore further warnings.",
                                          "Party_Editor") is False:
                            self._ignore_warnings = True

            parameters.append(parameter)

        decoded["Custom"] = False
        decoded["Parameters"] = parameters

        return decoded

    # --- PartyEditor._read_spell_names() ---

    def _read_spell_names(self) -> bool:
        """
        Reads compressed text used to create the spell menus, and caches it as a list of ASCII strings.

        Returns
        -------
        bool
            True if strings have been found, False otherwise (usually means the ROM uses custom code).
        """
        # This will be set to True if the code for spell menus is not recognised
        custom_menu_code = False

        # Find the ID of the string used for the first menu (default: 3)
        # D3AA  $A9 $03        LDA #$03
        # D3AC  $8D $D4 $03    STA $03D4
        # D3AF  $20 $15 $D4    JSR SpellMenu

        bytecode = self.rom.read_bytes(0xF, 0xD3AA, 5)

        if bytecode[0] != 0xA9 or bytecode[2:5] != b'\x8D\xD4\x03':
            self.warning("This ROM seems to use custom code for the Wizard spell menu. Using default string IDs.")
            custom_menu_code = True
            menu_id = 3

        else:
            menu_id = bytecode[1]

        strings = self.text_editor.special_text[menu_id]

        # Clear previous entries
        self.spell_names_1.clear()

        # Add each line as a separate string, remove terminator character
        for s in strings.splitlines(False):
            self.spell_names_1.append(s.replace('~', '', 1))

        if custom_menu_code is False:
            # We must have exactly 8 spells at this point
            while len(self.spell_names_1) < 8:
                self.spell_names_1.append(" ")
            if len(self.spell_names_1) > 8:
                self.spell_names_1 = self.spell_names_1[:8]

        # The second part is always the ID of the first part + 1
        # E5DD  $AD $D4 $03    LDA $03D4
        # E5E0  $18            CLC
        # E5E1  $69 $01        ADC #$01
        # E5E3  $85 $30        STA $30
        # E5E5  $4C $2B $E5    JMP $E52B

        strings = self.text_editor.special_text[menu_id + 1]
        for s in strings.splitlines(False):
            self.spell_names_1.append(s.strip('~'))

        if custom_menu_code is False:
            # We must have exactly 16 spells now
            while len(self.spell_names_1) < 16:
                self.spell_names_1.append(" ")
            if len(self.spell_names_1) > 16:
                self.spell_names_1 = self.spell_names_1[:16]

        # Second menu (cleric spells)
        # D378  $A9 $05        LDA #$05
        # D37A  $8D $D4 $03    STA $03D4
        # D37D  $20 $15 $D4    JSR SpellMenu

        bytecode = self.rom.read_bytes(0xF, 0xD378, 5)

        if bytecode[0] != 0xA9 or bytecode[2:5] != b'\x8D\xD4\x03':
            # Default string ID = 5
            menu_id = 5
            if custom_menu_code is False:  # This check is to avoid giving the same warning twice
                self.warning("This ROM seems to use custom code for the Cleric spell menu. Using default string IDs.")
                custom_menu_code = True

        else:
            menu_id = bytecode[1]

        self.spell_names_0.clear()

        strings = self.text_editor.special_text[menu_id]
        for s in strings.splitlines(False):
            self.spell_names_0.append(s.strip('~'))

        if custom_menu_code is False:
            # Make sure we have exactly 8 spells at this point
            while len(self.spell_names_0) < 8:
                self.spell_names_0.append(" ")
            if len(self.spell_names_0) > 8:
                self.spell_names_0 = self.spell_names_0[:8]

        # Second part
        strings = self.text_editor.special_text[menu_id + 1]
        for s in strings.splitlines(False):
            self.spell_names_0.append(s.strip('~'))

        if custom_menu_code is False:
            # And now we should have 16
            while len(self.spell_names_0) < 16:
                self.spell_names_0.append(" ")
            if len(self.spell_names_0) > 16:
                self.spell_names_0 = self.spell_names_0[:16]

        return custom_menu_code

    # --- PartyEditor._update_menu_string_entry() ---

    def _update_menu_string_entry(self) -> None:
        """
        Re-writes the currently stored value for the menu string Id in its entry widget.
        Since the internal variable is only updated when the entry is valid, the displayed value may not match what
        is saved if the user inputs invalid values.
        Calling this before storing a new value in ROM, or before showing the text editor may be useful.
        """
        self.app.clearEntry("PE_Menu_String_Id", callFunction=False)
        self.app.setEntry("PE_Menu_String_Id", f"0x{self.menu_string_id:02X}", callFunction=False)

    # --- PartyEditor._read_attribute_names() ---

    def _read_attribute_names(self) -> None:
        """
        Reads attribute names from ROM, from the uncompressed string used to create the main Status screen
        """
        self.attribute_names: List[str] = ["", "", "", ""]

        address = 0xA515
        # Skip spaces and newlines to find attribute names
        value = self.rom.read_byte(0xC, address)
        address = address + 1
        for i in range(4):
            while value == 0x00 or value == 0xFD:
                value = self.rom.read_byte(0xC, address)
                address = address + 1
            # Start copying the name until space, newline or string terminator is found
            data = bytearray()
            while value != 0x00 and value < 0xFD:
                data.append(value)
                value = self.rom.read_byte(0xC, address)
                address = address + 1
            # Convert data to ASCII
            self.attribute_names[i] = exodus_to_ascii(data)

    # --- PartyEditor._read_max_mp() ---

    def _read_max_mp(self) -> bool:
        """
        Interprets the code that assigns Max MP values for each profession.

        Returns
        -------
        bool
            True if code is valid. False if customised / not supported / not recognised.
        """
        if self.rom.has_feature("enhanced party") is False:
            # Support for vanilla game
            values = self.rom.read_bytes(0xD, 0x8854, 11)
            for p in range(11):
                if values[p] > 6:
                    # Custom code
                    return False
                self.max_mp[p] = values[p]

            value = self.rom.read_byte(0xD, 0x881D)
            self.app.clearEntry("PE_Fixed_MP", callFunction=False, setFocus=False)
            self.app.setEntry("PE_Fixed_MP", f"{value}", callFunction=False)
            return True

        address = 0x881C
        end_address = 0x885E  # We have exactly 4 bytes to spare in the Remastered ROM

        # Read first byte of code
        value = self.rom.read_byte(0xD, address)
        address = address + 1
        # We expect $A9 = LDA instruction
        if value != 0xA9:
            return False

        # Get fixed value MP (0 by default)
        value = self.rom.read_byte(0xD, address)
        address = address + 1
        self.app.clearEntry("PE_Fixed_MP", callFunction=False, setFocus=False)
        self.app.setEntry("PE_Fixed_MP", f"{value}", callFunction=False)

        # We now expect one or more STA for professions that use fixed value Max MP, followed by LDY #$06
        while address < end_address:
            # Read next instructions
            value = self.rom.read_byte(0xD, address)
            address = address + 1

            if value == 0x85:  # STA zp
                # Read parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1
                # Validate parameter
                if 0x31 <= value <= 0x3B:
                    # Calculate profession index for this value
                    value = value - 0x31
                    self.max_mp[value] = 8  # 8: MAX MP = Fixed Value
                    # self.info(f"{self.profession_names[value]} MAX MP = Fixed Value.")

                else:
                    self.error("Unexpected parameter for STA instruction found while " +
                               f"reading Max MP data: 0x{value:02X}.")
                    return False

            elif value == 0xA0:  # LDY d
                break

            else:  # Unexpected instructions
                self.error(f"Unexpected op code ${value:02X} in Max MP routine @0D:{address - 1:04X}.")
                return False

        # Check that we have the correct bytecode for reading the character's Wisdom
        bytecode = self.rom.read_bytes(0xD, address, 3)
        address = address + 3
        if bytecode != b'\x0A\xB1\x99':
            self.error(f"Unexpected op code ${value:02X} in Max MP routine " +
                       f"@0D:{address - 1:04X}. Expected $85 or $46.")
            return False

        # Now we look for a sequence of STA zp followed by LSR zp (WIS/2), ASL + ADC + ROR + LSR (WIS*3),
        # or DEY (used to switch to INT calculations)
        while address < end_address:
            # Read next instruction
            value = self.rom.read_byte(0xD, address)
            address = address + 1

            if value == 0x85:  # STA zp (Max MP = WIS)
                # Read STA parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1
                # Validate STA parameter
                if 0x31 <= value <= 0x3B:
                    # Calculate profession index for this value
                    value = value - 0x31
                    self.max_mp[value] = 0  # 0: MAX MP = WIS
                    # self.info(f"{self.profession_names[value]} MAX MP = {self.attribute_names[3]}.")

                else:
                    self.error("Unexpected parameter for STA instruction found while " +
                               f"reading Max MP data: 0x{value:02X}.")
                    return False

            elif value == 0x46:  # LSR zp (Max MP = WIS/2)
                # Read parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1
                # Validate parameter
                if 0x31 <= value <= 0x3B:
                    # Calculate profession index
                    value = value - 0x31
                    self.max_mp[value] = 1  # 1: MAX MP = WIS / 2
                    # self.info(f"{self.profession_names[value]} MAX MP = {self.attribute_names[3]}/2.")

            elif value == 0x0A:  # ASL
                break

        # Read next instruction, we are expecting ADC zp
        value = self.rom.read_byte(0xD, address)
        address = address + 2  # Ignore parameter

        if value != 0x65:  # ADC zp
            self.error(f"Unexpected op code encountered @0D:{address - 2:04X}.")
            return False

        # Check rest of bytecode
        bytecode = self.rom.read_bytes(0xD, address, 2)
        address = address + 2
        # Also make it work on the older, bugged ROM (the save function will fix it anyway)
        if (bytecode[0] != 0x6A and bytecode[0] != 0x4A) or bytecode[1] != 0x4A:
            self.error(f"Unexpected bytecode encountered @0D:{address - 2:04X}.")
            return False

        # Now we expect a series of STA zp, followed by DEY
        while address < end_address:
            # Read next opcode
            value = self.rom.read_byte(0xD, address)
            address = address + 1

            if value == 0x85:  # STA zp
                # Read parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1
                # Validate parameter
                if 0x31 <= value <= 0x3B:
                    value = value - 0x31
                    self.max_mp[value] = 2  # 2: MAX MP = WIS*3/4
                    # self.info(f"{self.profession_names[value]} MAX MP = {self.attribute_names[3]}*3/4.")
                else:
                    self.error("Unexpected parameter for STA instruction found while " +
                               f"reading Max MP data: 0x{value:02X} @0D:{address - 1:04X}.")
                    return False

            elif value == 0x88:  # DEY
                break

        # Now look for LDA($99),Y
        bytecode = self.rom.read_bytes(0xD, address, 2)
        address = address + 2

        if bytecode != b'\xB1\x99':
            self.error(f"Unexpected bytecode encountered @0D:{address - 2:04X}.")
            return False

        # As usual, a sequence of STA zp should follow, then LSR and finally ASL
        while address < end_address:
            value = self.rom.read_byte(0xD, address)
            address = address + 1

            if value == 0x85:  # $85 = STA zp
                # Get and check parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1

                if 0x31 <= value <= 0x3B:
                    value = value - 0x31
                    self.max_mp[value] = 3  # 3: MAX MP = INT
                    # self.info(f"{self.profession_names[value]} MAX MP = {self.attribute_names[2]}.")

                else:
                    self.error("Unexpected parameter for STA instruction found while " +
                               f"reading Max MP data: 0x{value:02X} @0D:{address - 1:04X}.")
                    return False

            elif value == 0x46:  # $46 = LSR
                # Get and check parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1

                if 0x31 <= value <= 0x3B:
                    value = value - 0x31
                    self.max_mp[value] = 4  # 4: MAX MP = INT/2
                    # self.info(f"{self.profession_names[value]} MAX MP = {self.attribute_names[2]}/2.")

                else:
                    self.error("Unexpected parameter for STA instruction found while " +
                               f"reading Max MP data: 0x{value:02X} @0D:{address - 1:04X}.")
                    return False

            elif value == 0x0A:  # $0A = ASL
                break

            else:
                self.error(f"Unexpected op code ${value:02X} in Max MP routine " +
                           f"@0D:{address - 1:04X}. Expected $85 or $46.")
                return False

        # An ASL instruction was already found, ADC zp should follow
        bytecode = self.rom.read_bytes(0xD, address, 4)
        address = address + 4

        if bytecode[0] != 0x65:
            self.error(f"Unexpected op code ${value:02X} in Max MP routine " +
                       f"@0D:{address - 5:04X}. Expected $65.")
            return False

        # Ignore parameter and check the rest, allowing for the older bugged ROM (the save routine will fix it)
        if (bytecode[2] != 0x6A and bytecode[2] != 0x4A) or bytecode[3] != 0x4A:
            self.error(f"Unexpected bytecode '0x{bytecode[2]:02X} " +
                       f"0x{bytecode[3]:02X}' encountered @0D:{address - 2:04X}.")
            return False

        # There should now be a sequence of STA zp, followed by LDA zp at the end
        while address < end_address:
            # Read instruction
            value = self.rom.read_byte(0xD, address)
            address = address + 1

            if value == 0x85:  # $85 = STA zp
                # Check and adjust parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1
                if 0x31 <= value <= 0x3B:
                    value = value - 0x31
                    self.max_mp[value] = 5  # 5: MAX MP = INT*3/4
                    # self.info(f"{self.profession_names[value]} MAX MP = {self.attribute_names[2]}*3/4.")

                else:
                    self.error("Unexpected parameter for STA instruction found while " +
                               f"reading Max MP data: 0x{value:02X} @0D:{address - 1:04X}.")
                    return False

            elif value == 0xA5:  # $A5 = LDA zp
                # Skip the parameter
                address = address + 1
                break

        # CLC, ADC zp, LSR should follow
        bytecode = self.rom.read_bytes(0xD, address, 4)
        address = address + 4
        if bytecode[0] != 0x18 or bytecode[1] != 0x65 or bytecode[3] != 0x4A:
            self.error(f"Unexpected bytecode encountered @0D:{address - 4:04X}.")
            return False

        # Sequence of STA zp, ending with LSR
        while address < end_address:
            # Read next op code
            value = self.rom.read_byte(0xD, address)
            address = address + 1

            if value == 0x85:  # $85 = STA zp
                # Validate and adjust parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1
                if 0x31 <= value <= 0x3B:
                    value = value - 0x31
                    self.max_mp[value] = 6  # 6: MAX MP = (INT+WIS)/2
                    # self.info(f"{self.profession_names[value]} MAX MP = ({self.attribute_names[2]} + " +
                    #          f"{self.attribute_names[3]})/2.")

            elif value == 0x4A:  # $4A = LSR
                break

            else:
                self.error(f"Unexpected op code ${value:02X} in Max MP routine " +
                           f"@0D:{address - 1:04X}. Expected $85 or $65.")
                return False

        # Last sequence of STA zp, ends with LDY #$06
        while address < end_address:
            # Read next instruction
            value = self.rom.read_byte(0xD, address)
            address = address + 1

            if value == 0x85:  # $85 = STA zp
                # Validate and adjust parameter
                value = self.rom.read_byte(0xD, address)
                address = address + 1
                if 0x31 <= value <= 0x3B:
                    value = value - 0x31
                    self.max_mp[value] = 7  # 7: MAX MP = (INT+WIS) / 4
                    # self.info(f"{self.profession_names[value]} MAX MP = ({self.attribute_names[2]} + " +
                    #          f"{self.attribute_names[3]})/4.")

                else:
                    self.error("Unexpected parameter for STA instruction found while " +
                               f"reading Max MP data: 0x{value:02X} @0D:{address - 1:04X}.")
                    return False

            elif value == 0xA0:  # $A0 = LDY d
                # Skip parameter
                # address = address + 1
                # break
                return True

            else:
                self.error(f"Unexpected op code ${value:02X} in Max MP routine " +
                           f"@0D:{address - 1:04X}. Expected $85 or $A0.")
                return False

        # All done
        return True

    # --- PartyEditor._read_weapon_armour_names() ---

    def _read_weapon_armour_names(self) -> None:
        """
        Reads and decodes weapon/armour names from ROM, caching them as ASCII strings for editing.
        These are the strings used in the STATUS screen.
        """
        # Read and decode weapon/armour names
        # We start both with one empty entry which will be populated later...
        self.weapon_names: List[str] = [""]
        self.armour_names: List[str] = [""]

        # ...this is because the actual weapon/armour names come first in ROM, the default HAND/SKIN strings come last
        address = 0xBB01
        count = 0
        while address < 0xBBF7:
            data = bytearray()

            # Read first character
            character = self.rom.read_byte(0xC, address)
            address = address + 1

            # Keep reading until newline or terminator character is found
            while character != 0xFD and character != 0xFF:
                data.append(character)
                character = self.rom.read_byte(0xC, address)
                address = address + 1

            if character == 0xFF:
                continue

            # Convert to ASCII
            ascii_string = exodus_to_ascii(data)
            if count < 15:  # Weapons 1 - 15
                self.weapon_names.append(ascii_string.strip(" "))
            elif count == 22:  # Weapon 0 ("HAND")
                self.weapon_names[0] = ascii_string.strip(" ")
            elif count == 23:  # Wrmour 0 ("SKIN")
                self.armour_names[0] = ascii_string.strip(" ")
            else:  # Armour 1 - 15
                self.armour_names.append(ascii_string.strip(" "))

            count = count + 1

    # --- PartyEditor._read_pre_made() ---

    def _read_pre_made(self) -> bool:
        """
        Reads all pre-made character data from ROM into the pre_made array.
        Overwrites any previous contents of the array.

        Returns
        -------
        bool:
            True if data was written to the ROM buffer successfully.
            At the moment this can never fail, but this value could be useful in future implementations.
        """
        self.pre_made = []

        # From bank 0xC
        address = 0xA941

        for p in range(12):
            pre_made = PartyEditor.PreMade()

            # Read name (5 bytes)
            name = self.rom.read_bytes(0xC, address, 5)
            pre_made.name = exodus_to_ascii(name)
            address = address + 5

            # Read race
            pre_made.race = self.rom.read_byte(0xC, address)
            address = address + 1

            # Read profession
            pre_made.profession = self.rom.read_byte(0xC, address)
            address = address + 1

            # Read attributes
            for a in range(4):
                pre_made.attributes.append(self.rom.read_byte(0xC, address))
                address = address + 1

            # Skip 5 extra bytes that are always 00 01 00 00 00
            address = address + 5

            self.pre_made.append(pre_made)

        return True

    # --- PartyEditor.load_profession_graphics() ---

    def _load_profession_graphics(self) -> None:
        """
        Reads the profession graphics used in character creation and Status screen for the currently selected
        profession, and displays it on the canvas widget
        """
        if self.selected_index < 0:
            return

        # Clear previous image
        self.app.clearCanvas("PE_Canvas_Profession")

        # Read palette data
        colour_index = self.colour_indices[self.selected_index]

        if colour_index > 6:
            self.error(f"Invalid colour index #{colour_index} for profession graphics!")
            return

        # Show colour index in the corresponding widget
        self.app.setOptionBox("PE_Profession_Colours", index=colour_index, callFunction=False)

        # For 48x48 graphics, this is simply the palette index
        # For 32x32 graphics, this corresponds to the values:
        # 0 = BG Palette 0 (blue)
        # 1 = BG Palette 2 (red)
        # 2 = Top is BG Palette 2, Bottom is BG palette 0
        # 3 = BG Palette 3 (grey)
        # 4 = BG Palette 1 (orange)
        # 5 = Top is BG Palette 0, Bottom is BG Palette 1
        # 6 = Top is BG Palette 1, Bottom is BG Palette 0
        palette_dictionary = [[0, 0],
                              [2, 2],
                              [2, 0],
                              [3, 3],
                              [1, 1],
                              [0, 1],
                              [1, 0]]

        # 32x32 pixels, 4x4 patterns
        if self.rom.has_feature("new profession gfx"):
            # Create an empty 32x32 image
            graphics = Image.new('RGB', (32, 32), 0)

            # Get sub-palette indices
            top_palette = palette_dictionary[colour_index][0]
            bottom_palette = palette_dictionary[colour_index][1]

            # Get RGB values
            top_colours = self.palette_editor.sub_palette(34, top_palette)
            bottom_colours = self.palette_editor.sub_palette(34, bottom_palette)

            # Address to the first pattern for this profession's graphics
            # Patterns are stored in consecutive lines, top to bottom, left to right
            address = 0x9600 + (0x100 * self.selected_index)

            # Process 4x4 patterns
            for y in range(4):
                for x in range(4):
                    # Read next pattern
                    pixels = bytes(self.rom.read_pattern(0x7, address))
                    address = address + 0x10

                    # Convert to PIL.Image
                    image = Image.frombytes('P', (8, 8), pixels)

                    # Assign palette
                    if y < 2:
                        image.putpalette(top_colours)
                    else:
                        image.putpalette(bottom_colours)

                    # Paste into full image
                    graphics.paste(image.convert('RGB'), (x << 3, y << 3))

            # Put graphics on the canvas
            self.app.addCanvasImage("PE_Canvas_Profession", 24, 24, ImageTk.PhotoImage(graphics))

        # 48x48 pixels, 6x6 patterns
        else:
            # Create an empty 48x48 image
            graphics = Image.new('P', (48, 48), 0)

            # Retrieve RGB values for this graphics
            colours = self.palette_editor.sub_palette(34, colour_index)

            graphics.putpalette(colours)

            # Address to the first pattern for this profession's graphics
            # Patterns are stored in consecutive lines, top to bottom, left to right
            address = 0x9600 + (0x240 * self.selected_index)

            # Process 6x6 patterns
            for y in range(6):
                for x in range(6):
                    # Raw pixel data
                    pixels = bytes(self.rom.read_pattern(0x7, address))
                    address = address + 0x10

                    # Convert to PIL.Image
                    image = Image.frombytes('P', (8, 8), pixels)

                    # Assign colours
                    image.putpalette(colours)

                    # Paste into larger image
                    graphics.paste(image, (x << 3, y << 3))

            # Put the graphics on the canvas
            self.app.addCanvasImage("PE_Canvas_Profession", 24, 24, ImageTk.PhotoImage(graphics))

    # --- PartyEditor._show_profession_sprite() ---

    def _show_profession_sprite(self) -> None:
        """
        Loads and displays the map/combat sprite for the currently selected profession
        """
        if self.selected_index < 0:
            return

        # Clear previous image
        self.app.clearCanvas("PE_Canvas_Sprite")

        # Get address of the first pattern for this profession's sprite
        address = 0x8000 + (0x200 * self.selected_index)

        # Create an up-scaled image with transparency that will contain all the patterns
        sprite = Image.new('RGBA', (32, 32), 0)

        # Get this profession's sprite colours
        value = self.sprite_colours[self.selected_index]
        if self.rom.has_feature("2-colour sprites"):
            if (value & 0x80) != 0:
                top_colours = self.palette_editor.sub_palette(1, (value >> 2) & 0x3)
                bottom_colours = self.palette_editor.sub_palette(1, value & 0x3)
                # Update input widgets
                self.app.setOptionBox("PE_Sprite_Palette_Top", index=((value >> 2) & 0x3), callFunction=False)
                self.app.setOptionBox("PE_Sprite_Palette_Bottom", index=(value & 0x3), callFunction=False)
            else:
                top_colours = self.palette_editor.sub_palette(1, value)
                bottom_colours = top_colours
                # Update input widgets
                self.app.setOptionBox("PE_Sprite_Palette_Top", index=value, callFunction=False)
                self.app.setOptionBox("PE_Sprite_Palette_Bottom", index=value, callFunction=False)
        else:
            top_colours = self.palette_editor.sub_palette(1, value)
            bottom_colours = top_colours
            # Update input widgets
            self.app.setOptionBox("PE_Sprite_Palette_Top", index=value, callFunction=False)
            self.app.disableOptionBox("PE_Sprite_Palette_Bottom")

        # Load 2x2 patterns, they are stored in the order: top-left, bottom-left, top-right, bottom-right
        for x in range(2):
            for y in range(2):
                colours = top_colours if y == 0 else bottom_colours
                image = self.rom.read_sprite(0x7, address, list(colours))
                address = address + 0x10
                sprite.paste(image.convert('RGBA').resize((16, 16), Image.NONE), (x << 4, y << 4))

        # Put the image on the canvas
        self.app.addCanvasImage("PE_Canvas_Sprite", 16, 16, ImageTk.PhotoImage(sprite))

    # --- PartyEditor._show_npc_sprite() ---

    def _show_npc_sprite(self, npc_id: int, canvas: str) -> None:
        """
        Loads and shows the sprite used for an NPC/enemy on town/overworld maps.

        Parameters
        ----------
        npc_id: int
            Index of the NPC whose sprite we want to show (0x0-0x1E)

        canvas: str
            Name of the canvas widget where the sprite will be shown
        """
        self.app.clearCanvas(canvas)

        # Get address of the first pattern for this profession's sprite
        address = 0x8000 + (0x200 * npc_id)

        # Create an up-scaled image with transparency that will contain all the patterns
        sprite = Image.new('RGBA', (32, 32), 0)

        # Get colours
        palette_value = self.rom.read_byte(0xC, 0xBA08 + npc_id)

        if self.rom.has_feature("2-colour sprites"):
            top_colours = self.palette_editor.sub_palette(1, (palette_value >> 2) & 0x3)
            bottom_colours = self.palette_editor.sub_palette(1, palette_value & 0x3)

        else:
            top_colours = self.palette_editor.sub_palette(1, palette_value)
            bottom_colours = top_colours

        # Load 2x2 patterns, they are stored in the order: top-left, bottom-left, top-right, bottom-right
        for x in range(2):
            for y in range(2):
                colours = top_colours if y == 0 else bottom_colours
                image = self.rom.read_sprite(0x7, address, list(colours))
                address = address + 0x10
                sprite.paste(image.convert('RGBA').resize((16, 16), Image.NONE), (x << 4, y << 4))

        # Put the image on the canvas
        self.app.addCanvasImage(canvas, 8, 8, ImageTk.PhotoImage(sprite))

    # --- PartyEditor.magic_info() ---

    def magic_info(self, spell_id: int) -> None:
        """
        Show info for the currently selected spell

        Parameters
        ----------
        spell_id: int
            Index of the spell whose info is going to be shown. Spell list index is self.selected_index.
        """
        # Don't show MP and flags widgets for common routines
        if self.selected_index > 1 or spell_id > 31:
            routine_address = self.routines[spell_id].address
            self.app.clearEntry("PE_Spell_Address", callFunction=False, setFocus=False)
            self.app.setEntry("PE_Spell_Address", f"0x{routine_address:04X}", callFunction=False)

            self.app.disableEntry("PE_Spell_Address")
            self.app.disableEntry("PE_MP_Display")
            self.app.disableEntry("PE_MP_Cast")
            self.app.disableOptionBox("PE_Spell_Flags")

            flag = 1
            for w in range(8):
                self.app.disableCheckBox(f"PE_Flag_0x{flag:02X}")
                flag = flag << 1
            self.app.disableOptionBox("PE_Map_Flag_0x02")
            self.app.disableOptionBox("PE_Map_Flag_0x04")
            self.app.disableOptionBox("PE_Map_Flag_0x10")

        else:
            mp_to_show = self.routines[spell_id].mp_display
            mp_to_cast = self.routines[spell_id].mp_cast
            routine_address = self.routines[spell_id].address

            # ["Nowhere", "Battle Only", "Town, Continent, Dungeon", "Continent Only", "Dungeon Only",
            #  "Continent and Dungeon", "Battle and Continent", "Battle and Dungeon",
            #  "Battle, Continent, Dungeon", "Everywhere"]
            flags = self.routines[spell_id].flags
            self.app.clearEntry("PE_Spell_Address", callFunction=False, setFocus=False)
            self.app.setEntry("PE_Spell_Address", f"0x{routine_address:04X}", callFunction=False)
            self.app.enableEntry("PE_Spell_Address")

            # Same with fine flags
            flag = 1
            for w in range(8):
                self.app.enableCheckBox(f"PE_Flag_0x{flag:02X}")
                flag = flag << 1
            self.app.enableOptionBox("PE_Map_Flag_0x02")
            self.app.enableOptionBox("PE_Map_Flag_0x04")
            self.app.enableOptionBox("PE_Map_Flag_0x10")

            self.app.clearEntry("PE_MP_Display", callFunction=False, setFocus=False)
            self.app.setEntry("PE_MP_Display", f"{mp_to_show}", callFunction=False)
            # Only enable this if using "Uneven" MP cost routine
            if self.app.getRadioButton("PE_Radio_MP")[:1] == 'U':
                self.app.enableEntry("PE_MP_Display")

            # Certain spells do not allow altering their MP cost, e.g. the first spell in each list always has
            # zero cost, while other spells jump into a different spell's routine and use that spell's MP cost instead
            if self.routines[spell_id].mp_address < 0xC000:
                self.app.disableEntry("PE_MP_Cast")
            else:
                self.app.enableEntry("PE_MP_Cast")
                self.app.clearEntry("PE_MP_Cast", callFunction=False, setFocus=False)
                self.app.setEntry("PE_MP_Cast", f"{mp_to_cast}", callFunction=False)

            # Decode flags and set corresponding option
            value = 9  # Default: Everywhere
            if flags == 0:
                value = 0  # Nowhere
            elif flags == 1:
                value = 4  # Dungeon Only
            elif flags == 2:
                value = 1  # Battle Only
            elif flags == 3:
                value = 7  # Dungeon and Battle
            elif flags == 4:
                value = 3  # Continent Only
            elif flags == 5:
                value = 5  # Continent and Dungeon
            elif flags == 6:
                value = 6  # Battle and Continent
            elif flags == 7:
                value = 8  # Battle, Continent and Dungeon
            elif flags == 8 or flags == 9 or flags == 12 or flags == 13:
                value = 2  # Town, Continent and Dungeon

            self.app.setOptionBox("PE_Spell_Flags", value, callFunction=False)
            self.app.enableOptionBox("PE_Spell_Flags")

            # Also show "fine" flags
            flag = 1
            for w in range(8):
                if self.routines[spell_id].fine_flags & flag != 0:
                    self.app.setCheckBox(f"PE_Flag_0x{flag:02X}", ticked=True, callFunction=False)
                else:
                    self.app.setCheckBox(f"PE_Flag_0x{flag:02X}", ticked=False, callFunction=False)
                flag = flag << 1

        self.app.emptyLabelFrame("PE_Frame_Parameters")

        # Resize the window depending on how many parameter options we need to display
        with self.app.subWindow("Party_Editor"):
            self.app.setSize(480, 580 + (30 * len(self.routines[spell_id].parameters)))

        self._create_parameter_widgets(self.routines[spell_id].notes, self.routines[spell_id].parameters,
                                       self._parameter_input)

    # --- PartyEditor.weapon_info() ---

    def weapon_info(self, weapon_id: int) -> None:
        """
        Displays weapon name, type (melee/ranged) and base damage.

        Parameters
        ----------
        weapon_id: int
            Index of the weapon (0 to 15).
        """
        # Name
        self.app.clearEntry("PE_Weapon_Name", callFunction=False, setFocus=False)
        self.app.setEntry("PE_Weapon_Name", self.weapon_names[weapon_id], callFunction=False)

        # Type
        self.app.setCheckBox("PE_Weapon_Ranged", ticked=True if self.weapon_type[weapon_id] != 0 else False,
                             callFunction=False)

        # Damage
        damage = (weapon_id >> 1) + weapon_id
        self.app.setLabel("PE_Label_Weapon_Damage", f"Base Damage = {damage}")

    # --- PartyEditor.armour_info() ---

    def armour_info(self, armour_id: int) -> None:
        """
        Displays armour name and parry chance.

        Parameters
        ----------
        armour_id: int
            Index of the armour (0 to 7).
        """
        self.app.clearEntry("PE_Armour_Name", callFunction=False, setFocus=False)
        self.app.setEntry("PE_Armour_Name", self.armour_names[armour_id], callFunction=False)

        self.app.setLabel("PE_Label_Armour_Parry_1", f"RANDOM(0 to {armour_id} + ")

        try:
            armour_max = int(self.app.getEntry("PE_Armour_Parry_Add"), 10) + armour_id
            armour_check = int(self.app.getEntry("PE_Armour_Parry_Check"), 10)

        except ValueError:
            self.app.setLabel("PE_Label_Armour_Parry_0", "Parry Chance:")
            return

        # *=$CBC3
        #   LDY #$35
        #   LDA ($99),Y
        #   CLC
        #   ADC #$0A    ; Parry "Add"
        #   JSR RNG
        #   CMP #$08    ; Parry "Check"
        #   BCC $CBE4
        #   JMP $CD62
        # 8 >= RANDOM(0 to armour + 10)? hit : not hit

        try:
            armour_chance = int((armour_max - armour_check) / armour_max * 100)
        except ZeroDivisionError:
            armour_chance = 0

        if armour_chance < 0:
            armour_chance = 0

        self.app.setLabel("PE_Label_Armour_Parry_0", f"Parry Chance: {armour_chance}%")

    # --- PartyEditor.item_info() ---

    def item_info(self, item_id: int) -> None:
        """
        Shows names/notes/parameter info for the requested item.

        Parameters
        ----------
        item_id: int
            Index of the item in the PartyEditor.routines list.
        """
        self.app.clearEntry("PE_Item_Consumption", callFunction=False)
        self.app.setEntry("PE_Item_Consumption", f"{self.routines[item_id].mp_cast}", callFunction=False)

        self.app.clearEntry("PE_Item_Address", callFunction=False)
        self.app.setEntry("PE_Item_Address", f"0x{self.routines[item_id].address:04X}", callFunction=False)

        self.app.clearEntry("PE_Item_Name", callFunction=False, setFocus=True)
        self.app.setEntry("PE_Item_Name", self.routines[item_id].name, callFunction=False)

        # Usability flags
        flag = 1
        for w in range(8):
            if self.routines[item_id].fine_flags & flag != 0:
                self.app.setCheckBox(f"PE_Flag_0x{flag:02X}", ticked=True, callFunction=False)
            else:
                self.app.setCheckBox(f"PE_Flag_0x{flag:02X}", ticked=False, callFunction=False)
            flag = flag << 1

        # Remove previous widgets
        self.app.emptyLabelFrame("PE_Frame_Parameters")

        # Resize the window depending on how many parameter options we need to display
        with self.app.subWindow("Party_Editor"):
            self.app.setSize(480, 408 + (30 * len(self.routines[item_id].parameters)))

        self._create_parameter_widgets(self.routines[item_id].notes, self.routines[item_id].parameters,
                                       self._parameter_input)

    # --- PartyEditor._create_parameter_widgets() ---

    def _create_parameter_widgets(self, notes: str, parameters: List, change_function: any,
                                  frame: str = "PE_Frame_Parameters") -> None:
        """
        Creates widgets for a routine's parameters and shows the appropriate values.

        Parameters
        ----------
        notes: str
            Notes field read from definition file.

        parameters: List
            A list of parameters for this routine.

        frame: str
            Name of the Frame widget that will contain the parameter widgets.
        """
        # Build a list of options for attribute checks, one for maps, and one for attribute names
        check_options: List[str] = []
        for c in self.attribute_checks:
            check_options.append(c.name)
        if len(check_options) < 1:
            check_options.append("- No Checks Defined -")

        map_options: List[str] = [] + self.map_editor.location_names
        if len(map_options) < 1:
            for m in range(self.map_editor.max_maps()):
                map_options.append(f"MAP #{m:02}")

        npc_options: List[str] = []
        for n in range(0x1F):
            npc_options.append(f"0x{n:02X}")

        attribute_options: List[str] = [] + self.attribute_names
        attribute_options.append("Level")
        attribute_options.append("(Custom)")

        with self.app.labelFrame(frame):
            # Show spell notes, if any
            self.app.message("PE_Routine_Notes", notes, width=400,
                             row=0, column=0, colspan=3, sticky="NEWS", fg=colour.MEDIUM_RED, font=11)

            # Add parameter widgets
            for p in range(len(parameters)):
                parameter = parameters[p]
                self.app.label(f"PE_Label_Parameter_{p:02}", parameter.description,
                               sticky="NE", row=1 + p, column=0, font=11)

                if parameter.type == parameter.TYPE_DECIMAL:
                    self.app.entry(f"PE_Decimal_Parameter_{p:02}", f"{parameter.value}", change=change_function,
                                   sticky="NW", width=8, row=1 + p, column=1, colspan=2, font=10)

                elif parameter.type == parameter.TYPE_HEX:
                    self.app.entry(f"PE_Hex_Parameter_{p:02}", f"0x{parameter.value:02X}", change=change_function,
                                   sticky="NW", width=5, row=1 + p, column=1, colspan=2, font=10)

                elif parameter.type == parameter.TYPE_POINTER:
                    self.app.entry(f"PE_Pointer_Parameter_{p:02}", f"{parameter.value:04X}", change=change_function,
                                   sticky="NW", width=8, row=1 + p, column=1, colspan=2, font=10)

                elif parameter.type == parameter.TYPE_STRING:
                    self.app.entry(f"PE_String_Id_Parameter_{p:02}", f"0x{parameter.value:02X}",
                                   change=change_function,
                                   sticky="NW", width=8, row=1 + p, column=1, font=10)
                    self.app.button(f"PE_String_Button_Parameter_{p:02}", image="res/edit-dlg-small.gif",
                                    value=change_function, sticky="NW", width=16, height=16, row=1 + p, column=2)

                elif parameter.type == parameter.TYPE_LOCATION:
                    self.app.optionBox(f"PE_Map_Parameter_{p:02}", map_options, change=change_function,
                                       width=24, sticky="NW", row=1 + p, column=1, colspan=2, font=10)
                    self.app.setOptionBox(f"PE_Map_Parameter_{p:02}", index=parameter.value, callFunction=False)

                elif parameter.type == parameter.TYPE_POINTER:
                    self.app.entry(f"PE_Pointer_Parameter_{p:02}", f"0x{parameter.value:04X}", change=change_function,
                                   sticky="NW", width=8, row=1 + p, column=1, colspan=2, font=10)

                elif parameter.type == parameter.TYPE_BOOL:
                    self.app.checkBox(f"PE_Bool_Parameter_{p:02}", name="", change=change_function, sticky="NW",
                                      row=1 + p, column=1, colspan=2)
                    self.app.setCheckBox(f"PE_Bool_Parameter_{p:02}", ticked=True if parameter.value != 0 else False,
                                         callFunction=False)

                elif parameter.type == parameter.TYPE_ATTRIBUTE:
                    self.app.entry(f"PE_Attribute_Id_Parameter_{p:02}", f"0x{parameter.value:02X}",
                                   change=change_function, sticky="NW", width=8, row=1 + p, column=1, font=10)
                    self.app.optionBox(f"PE_Attribute_List_Parameter_{p:02}", attribute_options,
                                       change=change_function,
                                       width=12, sticky="NW", row=1 + p, column=2, font=9)
                    # Select the appropriate option from the list
                    change_function(f"PE_Attribute_Id_Parameter_{p:02}")

                elif parameter.type == parameter.TYPE_MARK:
                    self.app.optionBox(f"MARKS Param {p:02}", self.mark_names, kind="ticks",
                                       change=change_function,
                                       width=14, sticky="NEW", row=1 + p, column=1, colspan=2, font=9)
                    bit = 1
                    for b in range(4):
                        if (parameter.value & bit) != 0:
                            self.app.setOptionBox(f"MARKS Param {p:02}", self.mark_names[b],
                                                  value=True, callFunction=False)
                        else:
                            self.app.setOptionBox(f"MARKS Param {p:02}", self.mark_names[b],
                                                  value=False, callFunction=False)
                        bit = bit << 1

                elif parameter.type == parameter.TYPE_CHECK:
                    # Find out which check this is
                    check_id = -1
                    for c in range(len(self.attribute_checks)):
                        if parameter.value == self.attribute_checks[c].address:
                            check_id = c
                            break
                    if check_id == -1:
                        self.warning(f"Unrecognised Check address '0x{parameter.value:04X}' for parameter #{p}.")
                        check_id = 0

                    self.app.optionBox(f"PE_Check_Parameter_{p:02}", check_options, change=change_function,
                                       sticky="NW", width=20, row=1 + p, column=1, colspan=2, font=10)
                    self.app.setOptionBox(f"PE_Check_Parameter_{p:02}", index=check_id, callFunction=False)

                elif parameter.type == parameter.TYPE_NPC:
                    self.app.optionBox(f"PE_NPC_Parameter_{p:02}", npc_options, change=change_function,
                                       width=24, sticky="NW", row=1 + p, column=1, colspan=2, font=10)
                    self.app.setOptionBox(f"PE_NPC_Parameter_{p:02}", index=parameter.value, callFunction=False)
                    self.app.canvas(f"PE_NPC_Sprite_{p:02}", sticky="NW", width=16, height=16, bg=colour.MEDIUM_GREY,
                                    row=1 + p, column=2)

                    if 0 <= parameter.value <= 0x1E:
                        self._show_npc_sprite(parameter.value, f"PE_NPC_Sprite_{p:02}")

                else:
                    self.warning(f"Unknown type: '{parameter.type}' for parameter #{p}.")
                    self.app.entry(f"PE_Hex_Parameter_{p:02}", f"0x{parameter.value:02X}", change=change_function,
                                   sticky="NW", width=8, row=1 + p, column=1, colspan=2, font=10)

    # --- PartyEditor.race_info() ---

    def race_info(self) -> None:
        """
        Shows info for the currently selected race.
        """
        if self.selected_index < 0:
            return

        # Gender widgets
        # Read gender character for this race
        gender = self.gender_char[self.selected_index]
        self.app.setEntry("PE_Gender_Character", f"0x{gender:02X}", callFunction=False)
        self._display_gender(gender)

        # Max starting / total attributes
        starting_values = self.start_attributes[self.selected_index]
        max_values = self.max_attributes[self.selected_index]
        for i in range(4):
            self.app.setEntry(f"PE_Start_Attribute_{i}", starting_values[i], callFunction=False)
            self.app.setEntry(f"PE_Max_Attribute_{i}", max_values[i], callFunction=False)

    # --- PartyEditor._thieving_chance() ---

    def _thieving_chance(self, bonus) -> None:
        """
        Calculates the min and max success chances and updates the thieving bonus widgets accordingly.
        """
        self.app.clearEntry("PE_Thieving_Bonus", callFunction=False, setFocus=False)
        self.app.setEntry("PE_Thieving_Bonus", f"{bonus}", callFunction=False)
        # Calculate success chance
        if bonus < 256:
            min_chance = bonus / 255 * 100
        else:
            min_chance = 100
        if (bonus + 99) < 256:
            max_chance = (bonus + 99) / 255 * 100
        else:
            max_chance = 100
        self.app.setLabel("PE_Thieving_Chance", f"{min_chance:.2f}% to {max_chance:.2f}%")

    # --- PartyEditor.profession_info() ---

    def profession_info(self) -> None:
        """
        Shows info for the currently selected profession.
        """
        if self.selected_index < 0:
            return

        # Enable input widgets
        self.app.enableOptionBox("PE_Profession_Colours")
        self.app.enableOptionBox("PE_Sprite_Palette_Top")
        self.app.enableOptionBox("PE_Sprite_Palette_Bottom")
        self.app.enableOptionBox("PE_Option_Weapon")
        self.app.enableOptionBox("PE_Option_Armour")

        # Show profession graphics
        self._load_profession_graphics()

        # Show on-map sprite as well
        self._show_profession_sprite()

        # Gender widgets
        if self.app.getCheckBox("PE_Check_Gender"):
            self.app.enableEntry("PE_Gender_Character")
            # Read gender character for this profession
            gender = self.gender_char[self.selected_index]
            self.app.setEntry("PE_Gender_Character", f"0x{gender:02X}", callFunction=False)
            self._display_gender(gender)

        else:
            self.app.clearCanvas("PE_Canvas_Gender")
            self.app.disableEntry("PE_Gender_Character")

        # Primary Attributes
        if self.rom.has_feature("enhanced party"):
            # The table contains offsets to the attribute value in the party data in RAM; STR is 0x7
            primary_0 = self.primary_attributes[self.selected_index][0]
            primary_1 = self.primary_attributes[self.selected_index][1]

            self.app.setOptionBox("PE_Primary_0", index=primary_0, callFunction=False)
            self.app.setOptionBox("PE_Primary_1", index=primary_1, callFunction=False)

            self.app.enableOptionBox("PE_Primary_0")
            self.app.enableOptionBox("PE_Primary_1")
        else:
            self.app.disableOptionBox("PE_Primary_0")
            self.app.disableOptionBox("PE_Primary_1")

        # HP Gain
        self.app.clearEntry("PE_HP_Base", callFunction=False, setFocus=False)
        self.app.clearEntry("PE_HP_Bonus", callFunction=False, setFocus=False)
        self.app.setEntry("PE_HP_Base", self.hp_base, callFunction=False)
        self.app.setEntry("PE_HP_Bonus", self.hp_bonus[self.selected_index], callFunction=False)

        # Thieving bonus
        bonus = self.thief_bonus[self.selected_index]
        self._thieving_chance(bonus)

        # Best weapon/armour
        self.app.setOptionBox("PE_Option_Weapon", self.best_weapon[self.selected_index], callFunction=False)
        self.app.setOptionBox("PE_Option_Armour", self.best_armour[self.selected_index], callFunction=False)

        # Caster flags
        self.app.setCheckBox("PE_Check_Caster_0", True if self.caster_flags[self.selected_index] & 1 else False,
                             callFunction=False)
        self.app.setCheckBox("PE_Check_Caster_1", True if self.caster_flags[self.selected_index] & 2 else False,
                             callFunction=False)

        # Max MP
        self.app.setOptionBox("PE_Option_MP", self.max_mp[self.selected_index], callFunction=False)

    # --- PartyEditor._display_gender() ---

    def _display_gender(self, character_index: int) -> None:
        """
        Reads gender pattern from ROM and displays it as an image on the gender canvas.

        Parameters
        ----------
        character_index: int
            Index of the character to load from character memory.
        """
        # We will upscale the pattern 2x, so we need a bigger image
        image_2x = Image.new('P', (16, 16), 0)

        # Read pattern from ROM
        address = 0x8000 + (character_index << 4)
        pixels = bytes(self.rom.read_pattern(0xA, address))
        image_1x = Image.frombytes('P', (8, 8), pixels)

        # Use the default palette
        colours = self.palette_editor.sub_palette(0, 1)

        image_2x.putpalette(colours)
        image_1x.putpalette(colours)

        # Scale image and paste it into the bigger one
        image_2x.paste(image_1x.resize((16, 16), Image.NONE))

        # Put this image in the canvas
        self.app.clearCanvas("PE_Canvas_Gender")
        self.app.addCanvasImage("PE_Canvas_Gender", 8, 8, ImageTk.PhotoImage(image_2x))

    # --- PartyEditor._save_profession_names() ---

    def _save_profession_names(self) -> bool:
        """
        Saves profession names used for the Status screen into the ROM buffer.

        Returns
        -------
        bool
            True if the operation completed successfully, False otherwise.
        """
        # Read profession names pointer
        address = self.rom.read_word(0xC, 0x0A439)
        new_data = bytearray()

        for n in range(11):
            name = self.profession_names[n]
            encoded = ascii_to_exodus(name)
            if n < 11:
                encoded.append(0xFD)
            else:
                encoded.append(0xFF)
            new_data = new_data + encoded

        # Make sure the new strings are not too long
        if len(new_data) > 0x3B:
            self.app.errorBox("Profession Editor", f"ERROR: Profession names are too log ({len(new_data)}/59).\n"
                                                   f"Please use shorter names and try again.",
                              "Party_Editor")
            return False

        self.rom.write_bytes(0xC, address, new_data)

        return True

    # --- PartyEditor._save_race_names() ---

    def _save_race_names(self) -> bool:
        """
        Saves race names to ROM buffer.

        Returns
        -------
        bool
            True if operation completed successfully, False otherwise.
        """

        # Read pointer
        address = self.rom.read_word(0xC, 0x0A435)

        # Put all names together in a single string, separating them with newlines and adding a terminator character
        text = ""
        for n in self.race_names:
            text = text + n + '\n'
        # Note that the last name is also followed by a newline
        text = text + '~'

        # Make sure there are no more than 29 bytes
        if len(text) > 29:
            return False

        # Convert to nametable indices
        data = ascii_to_exodus(text)

        # Save to ROM buffer
        self.rom.write_bytes(0xC, address, data)

        return True

    # --- PartyEditor._save_attribute_names() ---

    def _save_attribute_names(self) -> bool:
        """
        Saves attribute names (by default "STR", "INT", "DEX", "WIS") to the ROM buffer.

        Returns
        -------
        bool
            True if the operation completed successfully, False otherwise.
        """

        # First, we make sure each name has exactly 4 digits: we crop or add spaces if needed
        attributes: List[str] = []
        for a in self.attribute_names:
            name = a[:4]
            while len(name) < 4:
                name = name + ' '
            attributes.append(name)

        # Save names with newlines for Status screen
        address = 0xA53B
        for a in range(4):
            exodus_string = ascii_to_exodus(attributes[a])
            # Add a newline
            exodus_string.append(0xFD)
            self.rom.write_bytes(0xC, address, exodus_string)
            address = address + len(exodus_string)

        # Get pointer to attribute names for character creation screen
        address = self.rom.read_word(0xC, 0xA68B) + 6
        for a in range(4):
            # We centre each name by moving it to the left or right depending on how long the string is
            name = attributes[a].rstrip(' ')
            if len(name) > 3:
                final_address = address - 1
            elif len(name) < 3:
                final_address = address + 1
            else:
                final_address = address

            exodus_string = ascii_to_exodus(name)
            self.rom.write_bytes(0xC, final_address, exodus_string)
            address = address + 5

        # Add a string termination character
        self.rom.write_byte(0xC, address - 2, 0xFF)

        return True

    # --- PartyEditor._save_race_data() ---

    def _save_race_data(self) -> None:
        """
        Applies changes to rom buffer, doesn't save to file.
        """
        # Gender by profession / race (index in character record)
        # A637    LDY #$06                 ;Read character's Profession (#$05 = Race instead)
        # A639    LDA ($99),Y
        # A63B    TAY
        # A63C    LDA $A727,Y              ;Get Gender letter tile index (1 byte per profession - or race)
        # A63F    STA $0580,X
        if self.gender_by_profession:
            self.rom.write_byte(0xD, 0xA638, 0x6)
        else:
            self.rom.write_byte(0xD, 0xA638, 0x5)

            # Save gender characters
            for i in range(5):
                self.rom.write_byte(0xD, 0xA727 + i, self.gender_char[i])

        # Save number of selectable races
        # Modify the routine at 0C:8D76 which creates the menu

        # Frame height
        self.rom.write_byte(0xC, 0x8DA2, (self.selectable_races * 2) + 2)

        # Index of last selectable race
        self.rom.write_byte(0xC, 0x8EAD, self.selectable_races - 1)

        # # Max starting attributes for each race
        if self.rom.has_feature("enhanced party"):
            # Table at 0C:BFD0
            address = 0xBFD0
            for r in range(5):
                for i in range(4):
                    self.rom.write_byte(0xC, address, self.start_attributes[r][i])
                    address = address + 1

        # Max attribute values per race
        # Table at 0D:9780, values are in the order: INT, WIS, STR, DEX for some reason
        address = 0x9780
        for r in range(5):
            self.rom.write_byte(0xD, address + 2, self.max_attributes[r][0])
            self.rom.write_byte(0xD, address + 3, self.max_attributes[r][1])
            self.rom.write_byte(0xD, address, self.max_attributes[r][2])
            self.rom.write_byte(0xD, address + 1, self.max_attributes[r][3])
            address = address + 4

        # Save string ID from ROM, bank 0xC
        # 8DB8    LDA #$0A
        # 8DBA    STA $30
        # 8DBC    JSR DrawTextForPreGameMenu
        self.rom.write_byte(0xC, 0x8DB9, self.menu_string_id)
        # Update string ID widget, in case it contained invalid data
        self._update_menu_string_entry()

    # --- PartyEditor._save_max_mp() ---

    def _save_max_mp(self) -> bool:
        """
        Creates the routine that assigns max MP to each profession.
        For the vanilla game, it populates the corresponding table instead.

        Returns
        -------
        bool:
            True if saved successfully. False on fail (e.g. not enough space for the routine or invalid data).
        """
        # Detect vanilla game
        vanilla = True

        bytecode = self.rom.read_bytes(0xD, 0x8854, 11)
        for p in bytecode:
            if p > 0xA:
                vanilla = False
                break

        # --- Vanilla game code ---

        if vanilla:
            # Save fixed value
            try:
                value = int(self.app.getEntry("PE_Fixed_MP"), 10)
            except ValueError:
                self.warning(f"Invalid entry for Fixed MP Value.")
                value = 0
                self.app.clearEntry("PE_Fixed_MP", callFunction=False, setFocus=False)
                self.app.setEntry("PE_Fixed_MP", "0", callFunction=False)

            self.rom.write_byte(0xD, 0x881D, value)

            # Save table of values
            self.rom.write_bytes(0xD, 0x8854, self.max_mp)
            return True

        # --- Remastered version code ---

        # We will create the new bytecode here, then commit it to the ROM buffer after checking that it fits
        bytecode = bytearray()
        max_size = 0x885F - 0x881C

        # Write fixed value
        try:
            value = int(self.app.getEntry("PE_Fixed_MP"), 10)
        except ValueError:
            value = 0
            self.warning("Invalid Fixed MP entry.")
            self.app.clearEntry("PE_Fixed_MP", callFunction=False, setFocus=False)
            self.app.setEntry("PE_Fixed_MP", "0", callFunction=False)

        bytecode.append(0xA9)
        bytecode.append(value)

        # Create a list of STA zp for each character that has Max MP = Fixed Value
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 8:
                value = p + 0x31
                bytecode.append(0x85)  # STA zp
                bytecode.append(value)

        # Add code to read the Wisdom attribute
        # LDY #$0A
        bytecode.append(0xA0)
        bytecode.append(0x0A)
        # LDA ($99),Y
        bytecode.append(0xB1)
        bytecode.append(0x99)

        # List of STA zp for characters with Max MP = WIS or Max MP = WIS/2
        wisdom_address = 0  # ZP address where WIS value is saved
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 0 or self.max_mp[p] == 1:
                value = p + 0x31
                bytecode.append(0x85)  # STA zp
                bytecode.append(value)

                # Save it for later
                if self.max_mp[p] == 0:
                    wisdom_address = value

        # If no characters have Max MP = WIS, then WIS is not saved anywhere, which would be a problem since we need it
        # to calculate WIS*3/4 and WIS+INT later.
        # So we save it to a new location in that case.
        if wisdom_address == 0:
            wisdom_address = 0x3C
            # STA wisdom_address
            bytecode.append(0x85)
            bytecode.append(wisdom_address)

        # Create one LSR instruction for each character using WIS/2
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 1:
                value = p + 0x31
                bytecode.append(0x46)  # LSR zp
                bytecode.append(value)

        # Now we need the previously stored WIS value to calculate WIS*3/4
        bytecode.append(0x0A)
        # ADC wisdom_address
        bytecode.append(0x65)
        bytecode.append(wisdom_address)
        # ROR
        bytecode.append(0x6A)
        # LSR
        bytecode.append(0x4A)

        # Finally store it on the location of each profession using WIS*3/4
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 2:
                value = p + 0x31
                bytecode.append(0x85)  # STA zp
                bytecode.append(value)

        # Now read INT
        # DEY
        bytecode.append(0x88)
        # LDA ($99),Y
        bytecode.append(0xB1)
        bytecode.append(0x99)

        # Store this for each profession that uses MAX MP = INT or INT/2
        # We will also need it later to calculate INT*3/4 and INT+WIS
        int_address = 0
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 3 or self.max_mp[p] == 4:
                value = p + 0x31
                bytecode.append(0x85)
                bytecode.append(value)

                # Save this for later
                if self.max_mp[p] == 3:
                    int_address = value

        # If no professions were using INT, then we save it to another location
        if int_address == 0:
            int_address = 0x3D
            # STA int_address
            bytecode.append(0x85)
            bytecode.append(int_address)

        # Right shift one bit for each class using INT/2
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 4:
                value = p + 0x31
                bytecode.append(0x46)  # LSR zp
                bytecode.append(value)

        # Create the code that calculates INT*3/4 using the previously stored value at int_address
        # ASL
        bytecode.append(0x0A)
        # ADC int_address
        bytecode.append(0x65)
        bytecode.append(int_address)
        # ROR
        bytecode.append(0x6A)
        # LSR
        bytecode.append(0x4A)

        # Store INT*3/4 for each profession using it
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 5:
                value = p + 0x31
                bytecode.append(0x85)  # STA zp
                bytecode.append(value)

        # Calculate (INT+WIS)/2 using previously saved values
        # LDA wisdom_address
        bytecode.append(0xA5)
        bytecode.append(wisdom_address)
        # CLC
        bytecode.append(0x18)
        # ADC int_address
        bytecode.append(0x65)
        bytecode.append(int_address)
        # LSR
        bytecode.append(0x4A)

        # Store this for professions using (INT+WIS)/2
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 6:
                value = p + 0x31
                bytecode.append(0x85)  # STA zp
                bytecode.append(value)

        # Divide again to obtain (INT+WIS)/4
        bytecode.append(0x4A)

        # Store this for professions using (INT+WIS)/4
        for p in range(len(self.max_mp)):
            if self.max_mp[p] == 7:
                value = p + 0x31
                bytecode.append(0x85)  # STA zp
                bytecode.append(value)

        # Assign value to current character, using profession to index the table we just created
        # LDY #$06
        bytecode.append(0xA0)
        bytecode.append(0x06)
        # LAX($99),Y
        bytecode.append(0xB3)
        bytecode.append(0x99)
        # LDA $31,X
        bytecode.append(0xB5)
        bytecode.append(0x31)
        # LDY #$38
        bytecode.append(0xA0)
        bytecode.append(0x38)
        # STA ($99),Y
        bytecode.append(0x91)
        bytecode.append(0x99)

        # All done, RTS
        bytecode.append(0x60)

        # Size check
        if len(bytecode) > max_size:
            self.error(f"Bytecode for MAX MP routine is too large ({len(bytecode)} bytes).")
            return False

        # Save to ROM
        self.rom.write_bytes(0xD, 0x881C, bytecode)

        return True

    # --- PartyEditor._save_profession_data() ---

    def _save_profession_data(self) -> None:
        """
        Applies changes to rom buffer, doesn't save to file.
        """
        if self.rom.has_feature("enhanced party"):  # Remastered ROM

            # Starting HP values and bonus HP per level
            for p in range(len(self.hp_bonus)):
                self.rom.write_byte(0xC, 0xBFE4 + p, self.hp_bonus[p] + self.hp_base)
                self.rom.write_byte(0xD, 0x889F + p, self.hp_bonus[p])

            # Base HP
            self.rom.write_byte(0xD, 0x8872, self.hp_base)

        else:  # Vanilla game ROM
            # Starting HP values and bonus HP per level
            self.rom.write_byte(0xD, 0x8866, self.hp_bonus[0])

            # Base HP
            self.rom.write_byte(0xD, 0x8870, self.hp_base)

        # Gender by profession / race (index in character record)
        # A637    LDY #$06                 ;Read character's Profession (#$05 = Race instead)
        # A639    LDA ($99),Y
        # A63B    TAY
        # A63C    LDA $A727,Y              ;Get Gender letter tile index (1 byte per profession - or race)
        # A63F    STA $0580,X
        if self.gender_by_profession:
            self.rom.write_byte(0xD, 0xA638, 0x6)

            # Save gender characters
            for i in range(11):
                self.rom.write_byte(0xD, 0xA727 + i, self.gender_char[i])

        else:
            self.rom.write_byte(0xD, 0xA638, 0x5)

        # Primary attribute(s) per profession
        if self.rom.has_feature("enhanced party"):
            for i in range(11):
                # 2 bytes per entry: multiply index x2 (or shift 1 bit left)
                address = 0x97D6 + (i << 1)

                primary_0 = self.primary_attributes[i][0] + 7
                primary_1 = self.primary_attributes[i][1] + 7

                self.rom.write_byte(0xD, address, primary_0)
                self.rom.write_byte(0xD, address + 1, primary_1)

                # Also there is a table with cursor position that indicates these attributes
                # during character creation
                address = 0x937A + (i << 1)

                primary_0 = self.primary_attributes[i][0] * 5
                primary_1 = self.primary_attributes[i][1] * 5

                self.rom.write_byte(0xC, address, 0xED + primary_0)
                self.rom.write_byte(0xC, address + 1, 0xED + primary_1)

        # Profession graphics colours
        for i in range(11):
            # BG Profession Graphics colours
            self.rom.write_byte(0xC, 0x9736 + i, self.colour_indices[i])

            # Sprite colours
            self.rom.write_byte(0xF, 0xEF5A + 1, self.sprite_colours[i])

        # Save best armour/weapons
        for i in range(11):
            # We used the table used for the equip screen, but when saving we will also copy it to the "shop" table
            self.rom.write_byte(0xC, 0xA23B + i, self.best_weapon[i])
            self.rom.write_byte(0xD, 0x942C + i, self.best_weapon[i])

            self.rom.write_byte(0xC, 0xA246 + i, self.best_armour[i])
            self.rom.write_byte(0xD, 0x97BD + i, self.best_armour[i])

        # Save thief bonus table
        self.rom.write_bytes(0xF, 0xDEAA, self.thief_bonus[:11])

        # Save number of selectable professions
        # Modify the routine at 0C:8D76 which creates the menu

        # Reduce the frame size if less than 7 profession
        if self.selectable_professions < 7:
            # Width
            self.rom.write_byte(0xC, 0x8F27, 13)
            # Height
            self.rom.write_byte(0xC, 0x8F2B, (self.selectable_professions * 2) + 2)

            # Index of last profession on the left column
            self.rom.write_byte(0xC, 0x8EC7, self.selectable_professions - 1)
            # Index of last selectable profession
            self.rom.write_byte(0xC, 0x8ECB, self.selectable_professions - 1)

            # Number of professions in the right column
            self.rom.write_byte(0xC, 0x8DEE, 0)

        else:
            # Default width
            self.rom.write_byte(0xC, 0x8F27, 18)
            # Default height
            self.rom.write_byte(0xC, 0x8F2B, 14)

            # Index of last profession on the left column
            self.rom.write_byte(0xC, 0x8EC7, 5)
            # Index of last selectable profession
            self.rom.write_byte(0xC, 0x8ECB, self.selectable_professions - 1)

            # Number of professions in the right column
            self.rom.write_byte(0xC, 0x8DEE, self.selectable_professions - 6)

        # Save menu string Id to ROM, bank 0xC
        # 8F41    LDA #$0D    ; <- string ID
        # 8F43    STA $30
        # 8F45    JSR DrawTextForPreGameMenu
        self.rom.write_byte(0xC, 0x8F42, self.menu_string_id)

        # Save caster flags
        self.rom.write_bytes(0xF, 0xD455, self.caster_flags)

        # Save max MP data
        # Don't overwrite custom code unless option checked
        if self.app.getCheckBox("PE_Overwrite_MP"):
            if self._save_max_mp() is False:
                self.app.errorBox("ERROR", "Error saving Max MP data.", parent="Party_Editor")
            else:
                self.info("MAX MP data saved.")

        # Update the entry box, in case it contained an invalid value (the variable is only updated if entry is valid)
        self._update_menu_string_entry()

    # --- PartyEditor.save_weapon_armour_data() ---

    def save_weapon_armour_data(self) -> bool:
        """
        Saves weapon/armour names and data to the ROM buffer.

        Returns
        -------
        bool
            True if everything was saved successfully. False if errors occurred, e.g. not enough space in ROM to save
            name strings.
        """
        success = True

        # Save weapon names
        name_data = bytearray()
        for i in range(1, 16):
            name = ascii_to_exodus(self.weapon_names[i][:9])

            # Except for the first one (i.e.: hand/skin), all names must be 9 bytes long,
            # padded with zeroes and followed by 0xFD
            while len(name) < 9:
                name.append(0)
            name.append(0xFD)
            name_data = name_data + name

        for i in range(1, 8):
            name = ascii_to_exodus(self.armour_names[i][:9])

            # Except for the first one (i.e.: hand/skin), all names must be 9 bytes long,
            # padded with zeroes and followed by 0xFD
            while len(name) < 9:
                name.append(0)
            name.append(0xFD)
            name_data = name_data + name

        # There is a termination character 0xFF before the strings for no weapon/no armour
        name_data.append(0xFF)

        # No weapon (e.g. "HAND")
        name = ascii_to_exodus(self.weapon_names[0][:12])
        name.append(0xFD)
        name_data = name_data + name

        # No armour (e.g. "SKIN")
        name = ascii_to_exodus(self.armour_names[0][:12])
        name.append(0xFD)
        name_data = name_data + name
        # Note: there is no termination character here

        # Make sure this fits in ROM
        if len(name_data) > 247:
            if self.app.yesNoBox("Saving Weapons/Armour Data",
                                 "WARNING: Weapon/Armour names won't fit in ROM.\nTruncate strings and continue?",
                                 "Party_Editor") is True:
                success = False
                name_data = name_data[:246]
                name_data.append(0xFD)
            else:
                return False

        self.rom.write_bytes(0xC, 0xBB01, name_data)

        # Save throwing weapon ID
        # Throwing weapon ID
        # D112  $A0 $34        LDY #$34
        # D114  $B1 $99        LDA ($99),Y
        # D116  $C9 $01        CMP #$01     ; Daggers can be thrown
        value = self._get_selection_index("PE_Option_Throwing_Weapon")
        # Warn if this weapon is ranged
        if self.weapon_type[value] != 0:
            if self.app.yesNoBox("Saving Weapons/Armour Data",
                                 "WARNING: The selected throwing weapon has the RANGED flag enable.\n" +
                                 f"Do you want to clear this flag for '{self.weapon_names[value]}'?",
                                 "Party_Editor") is True:
                self.weapon_type[value] = 0
                if self._get_selection_index("PE_Option_Weapon") == value:
                    self.weapon_info(value)
        self.rom.write_byte(0xF, 0xD117, value)

        # Save weapon type table
        self.rom.write_bytes(0xF, 0xD189, self.weapon_type[:16])

        # Save armour parry "add" and "check" values
        # CBD3  $A0 $35        LDY #$35
        # CBD5  $B1 $99        LDA ($99),Y
        # CBD7  $18            CLC
        # CBD8  $69 $0A        ADC #$0A         ; "Add"
        # CBDA  $20 $4E $E6    JSR RNG
        # CBDD  $C9 $08        CMP #$08         ; "Check"
        # CBDF  $90 $03        BCC MeleeDamage
        armour_add = 10
        try:
            armour_add = int(self.app.getEntry("PE_Armour_Parry_Add"), 10)
        except ValueError:
            if self.app.warningBox("Saving Weapons/Armour Data",
                                   "WARNING: Invalid value for armour parry 'ADD' value.\n" +
                                   "Continue using the default value (10)?",
                                   "Party_Editor") is True:
                success = False
                self.app.clearEntry("PE_Armour_Parry_Add", callFunction=False)
                self.app.setEntry("PE_Armour_Parry_Add", "10")
            else:
                return False

        self.rom.write_byte(0xF, 0xCBD9, armour_add)

        armour_check = 8
        try:
            armour_check = int(self.app.getEntry("PE_Armour_Parry_Check"), 10)
        except ValueError:
            if self.app.warningBox("Saving Weapons/Armour Data",
                                   "WARNING: Invalid value for armour parry 'ADD' value.\n" +
                                   "Continue using the default value (8)?",
                                   "Party_Editor") is True:
                success = False
                self.app.clearEntry("PE_Armour_Parry_Check", callFunction=False)
                self.app.setEntry("PE_Armour_Parry_Check", "8")
            else:
                return False

        self.rom.write_byte(0xF, 0xCBDE, armour_check)

        # One special map can be set to only accept specific weapon(s):
        #         # BattleAttack:
        #         # D0B3  $A5 $70        LDA _CurrentMapId
        #         # D0B5  $C9 $14        CMP #$14                 ; Map $14 = Castle Exodus
        #         # D0B7  $D0 $12        BNE $D0CB
        #         # D0B9  $A0 $34        LDY #$34                 ; Read current weapon...
        #         # D0BB  $B1 $99        LDA ($99),Y
        #         # D0BD  $C9 $0F        CMP #$0F                 ; Only Mystic Weapons work in this map
        #         # D0BF  $F0 $0A        BEQ $D0CB
        #         # D0C1  $A9 $F5        LDA #$F5                 ; "CAN`T USE IT."
        #         # D0C3  $85 $30        STA $30
        #         # D0C5  $20 $27 $D2    JSR $D227                ; Battle Info Text
        #         # D0C8  $4C $D0 $CA    JMP __EndBattleTurn
        special_map = self._get_selection_index("PE_Special_Map")
        special_weapon = self._get_selection_index("PE_Special_Weapon")
        try:
            special_dialogue = int(self.app.getEntry("PE_Special_Dialogue"), 16)
        except ValueError:
            special_dialogue = 0xF5     # Default value
            self.app.clearEntry("PE_Special_Dialogue", callFunction=False, setFocus=False)
            self.app.entry("PE_Special_Dialogue", "0xF5", fg=colour.BLACK)
        special_condition = self.app.getOptionBox("PE_Special_Condition")

        # Only do this if no custom code was detected
        if special_condition[0] != '-':
            self.rom.write_byte(0xF, 0xD0B6, special_map)
            self.rom.write_byte(0xF, 0xD0BE, special_weapon)
            self.rom.write_byte(0xF, 0xD0C2, special_dialogue)

            selection = self._get_selection_index("PE_Special_Condition")
            if selection == 1:      # Anything but the specified weapon
                value = 0xD0    # BNE
            elif selection == 2:    # Specified weapon or better
                value = 0xB0    # BCS
            elif selection == 3:    # Up to and excluding the specified weapon
                value = 0x90    # BCC
            else:                   # Default: exactly and only the specified weapon
                value = 0xF0  # BEQ
            self.rom.write_byte(0xF, 0xD0BD, value)

        return success

    # --- PartyEditor.save_item_data() ---

    def save_item_data(self) -> bool:
        """
        Apply changes to ROM buffer.

        Returns
        -------
        bool
            True if everything was successfully saved, False if any of the data was not valid or strings would not fit
            in allocated ROM space.
        """
        success = True

        # Save item names in ROM at 0xD:0x9B09, 81 bytes max including terminator characters
        # Each name is padded to a minimum of 7 characters, maximum 10, and terminated by 0xFD
        # The last name is also followed by 0xFF
        data = bytearray()

        for i in range(len(self.routines)):
            # Convert to indices
            name = ascii_to_exodus(self.routines[i].name)
            # Add padding if needed
            while len(name) < 7:
                name.append(0)
            # Add termination character
            name.append(0xFD)

            data = data + name

        data.append(0xFF)

        if len(data) > 81:
            success = False
            if self.app.yesNoBox("Save Item Data", "ERROR: Not enough space to save item names.\n\n" +
                                                   "Do you want to ignore this error and continue?",
                                 "Party_Editor") is True:
                data = data[:79]
                data.append(0xFD)
                data.append(0xFF)
            else:
                return False

        self.rom.write_bytes(0xD, 0x9B09, data)

        # Save usability flags at 0B:AF67
        for i in range(len(self.routines)):
            if i > 8:
                success = False
                if self.app.yesNoBox("Save Item Data", "ERROR: Too many items defined.\n\n" +
                                                       "Do you want to ignore this error and continue?\n" +
                                                       "Note that only the first 9 items will be saved in any case.",
                                     "Party_Editor") is True:
                    break
                else:
                    return False

            self.rom.write_byte(0xB, 0xAF67 + i, self.routines[i].fine_flags)

        # Save item consumption table at $DBC3
        for i in range(len(self.routines)):
            if i > 8:
                success = False
                if self.app.yesNoBox("Save Item Data", "ERROR: Too many items defined.\n\n" +
                                                       "Do you want to ignore this error and continue?\n" +
                                                       "Note that only the first 9 items will be saved in any case.",
                                     "Party_Editor") is True:
                    break
                else:
                    return False

            value = int.to_bytes(self.routines[i].mp_cast, 1, "little", signed=True)
            self.rom.write_byte(0xF, 0xDBC3 + i, value[0])

        # Save routine pointers table at $DBB1
        for i in range(len(self.routines)):
            if i > 8:
                success = False
                if self.app.yesNoBox("Save Item Data", "ERROR: Too many items defined.\n\n" +
                                                       "Do you want to ignore this error and continue?\n" +
                                                       "Note that only the first 9 items will be saved in any case.",
                                     "Party_Editor") is True:
                    break
                else:
                    return False

            self.rom.write_word(0xF, 0xDBB1 + (2 * i), self.routines[i].address)

        # Save routine parameters
        self._ignore_warnings = False
        for i in range(len(self.routines)):
            for p in self.routines[i].parameters:
                # 16-bit parameter types
                if p.type == Parameter.TYPE_POINTER or \
                        p.type == Parameter.TYPE_CHECK:
                    if p.address >= 0xC000:
                        self.rom.write_word(0xF, p.address, p.value)
                    elif p.address >= 0x8000:
                        self.rom.write_word(0x0, p.address, p.value)
                        if p.address >= 0xBF10:  # A few subroutines must also be mirrored in bank 6
                            self.rom.write_word(0x6, p.address, p.value)
                    else:
                        success = False

                        if self._ignore_warnings is False:
                            if self.app.okBox("Save Item Data",
                                              f"ERROR: Invalid address 0x{p.address:04X} for Parameter " +
                                              f"'{p.description}' in Item#{i}." +
                                              "\n\nClick 'Cancel' to ignore further warnings.",
                                              "Party_Editor") is False:
                                self._ignore_warnings = True

                # Everything else is 8-bit
                else:
                    if p.value > 255:
                        if self._ignore_warnings is False:
                            if self.app.okBox("Save Item Data",
                                              f"ERROR: Item#{i} invalid data for parameter: " +
                                              f"'{p.description}': expecting 8-bit value, got {p.value} instead." +
                                              "\n\nClick 'Cancel' to ignore further warnings.",
                                              "Party_Editor") is False:
                                self._ignore_warnings = True
                        success = False
                    else:
                        if p.address >= 0xC000:
                            self.rom.write_byte(0xF, p.address, p.value)
                        elif p.address >= 0x8000:
                            self.rom.write_byte(0x0, p.address, p.value)
                            if p.address >= 0xBF10:
                                self.rom.write_byte(0x6, p.address, p.value)
                        else:
                            success = False

                            if self._ignore_warnings is False:
                                if self.app.okBox("Save Item Data",
                                                  f"ERROR: Invalid address 0x{p.address:04X} for Parameter " +
                                                  f"'{p.description}' in Item#{i}." +
                                                  "\n\nClick 'Cancel' to ignore further warnings.",
                                                  "Party_Editor") is False:
                                    self._ignore_warnings = True

        return success

    # --- PartyEditor.save_magic_data() ---

    def save_magic_data(self) -> bool:
        """
        Apply changes to ROM buffer.

        Returns
        -------
        bool
            True if everything was successfully saved, False if any of the data was not valid.
        """
        success = True
        self._ignore_warnings = False

        # Save spell data table
        if len(self.routines) < 32:
            self.app.warningBox("Save Spell Data", "ERROR: Expecting at least 32 spells, found only " +
                                f"{len(self.routines)} instead.", "Party_Editor")
            success = False
        else:
            # Prepare table
            data = bytearray()
            for s in range(32):
                data.append(self.routines[s].flags)
                data.append(self.routines[s].mp_display)
                data.append(self.routines[s].address & 0x00FF)
                data.append((self.routines[s].address & 0xFF00) >> 8)

            # Write table
            self.rom.write_bytes(0xF, 0xD460, data)

        # Save spell menu routine (progressive/uneven MP)
        if self.app.getRadioButton("PE_Radio_MP")[:2] == 'I':
            # Incremental MP cost
            data = bytearray(b'\x20\x41\xD4\xA2\x00\xC9\x09\x90\x03\xAA\xA9\x08\x85\x9C\x86\x9D'
                             b'\xA9\x0A\x8D\xD0\x03\xA9\x06\x8D\xD1\x03\xA9\x0A\x8D\xD2\x03\xA5'
                             b'\x9C\x18\x69\x01\x0A\x8D\xD3\x03\x4C\xFF\xE4\x60\xA0\x2F\xB1\x99'
                             b'\xA0\x00\xC8\x38\xE9\x04\xB0\xFA\xC0\x10\x90\x02\xA0\x10\x98\x60')
            # MP cost is hardcoded here:
            # D449  $E9 $04     SBC  #$04
            try:
                value = int(self.app.getEntry("PE_Incremental_MP"))
            except ValueError:
                value = 4
                success = False
                self.app.warningBox("Save Spell Data", "WARNING: Invalid value for incremental MP cost.\n" +
                                    "The default value '4' will be used.")
                self.app.clearEntry("PE_Incremental_MP", callFunction=False, setFocus=False)
                self.app.setEntry("PE_Incremental_MP", "4", callFunction=False)

            data[53] = value
            address = 0xD415

        else:
            # Uneven MP cost
            data = b'\xA2\x00\xF0\x02\xA2\x40\xA0\x2F\xB1\x99\xA0\x00\xDD\x61\xD4\x90\x09\xE8\xE8\xE8\xE8\xC8\xC0\x10' \
                   b'\xD0\xF2\x98\xA2\x00\xC9\x09\x90\x03\xAA\xA9\x08\x85\x9C\x86\x9D\xA9\x0A\x8D\xD0\x03\x8D\xD2\x03' \
                   b'\xA9\x06\x8D\xD1\x03\xA7\x9C\xE8\x8A\x0A\x8D\xD3\x03\x4C\xFF\xE4'
            address = 0xD419

        # Save the new table
        self.rom.write_bytes(0xF, 0xD415, data)
        # Set the address of this call:
        # D37E:  JSR ClericSpellMenu    ; $D415 incremental, $D419 uneven
        self.rom.write_word(0xF, 0xD37E, address)

        # "Fine flags" table in bank $0B
        for s in range(32):
            self.rom.write_byte(0xB, 0xAF47 + s, self.routines[s].fine_flags)

        # Save hardcoded map IDs used by some fine flags:
        # TODO Check if code has been customised (e.g. read opcodes)
        # AF24  $A5 $70        LDA _CurrentMapId
        # AF26  $C9 $14        CMP #$14                 ;Check if in Castle Death
        # AF2C  $C9 $0F        CMP #$0F                 ;Check if in Ambrosia
        # AF32  $C9 $06        CMP #$06                 ;Check if in Castle British
        value = self._get_selection_index("PE_Map_Flags_0x02")
        self.rom.write_byte(0xB, 0xAF27, value)
        value = self._get_selection_index("PE_Map_Flags_0x04")
        self.rom.write_byte(0xB, 0xAF2D, value)
        value = self._get_selection_index("PE_Map_Flags_0x10")
        self.rom.write_byte(0xB, 0xAF33, value)

        # Save MP cost and parameter values for each spell
        for s in range(len(self.routines)):
            if s < 32:
                # MP Cost
                address = self.routines[s].mp_address
                if address >= 0xC000:
                    self.rom.write_byte(0xF, address, self.routines[s].mp_cast)
                elif address >= 0x8000:
                    self.rom.write_byte(0x0, address, self.routines[s].mp_cast)
                    self.rom.write_byte(0x6, address, self.routines[s].mp_cast)
                elif address == 0:
                    # This spell does not consume any MP
                    pass
                else:
                    success = False

                    if self._ignore_warnings is False:
                        if self.app.okBox("Save Spell Data",
                                          f"ERROR: Invalid address 0x{address:04X} for MP cost for Spell#{s}." +
                                          "\n\nClick 'Cancel' to ignore further warnings.",
                                          "Party_Editor") is False:
                            self._ignore_warnings = True

                # Parameters
                for p in self.routines[s].parameters:
                    # 16-bit parameter types
                    if p.type == Parameter.TYPE_POINTER or \
                            p.type == Parameter.TYPE_CHECK:
                        if p.address >= 0xC000:
                            self.rom.write_word(0xF, p.address, p.value)
                        elif p.address >= 0x8000:
                            self.rom.write_word(0x0, p.address, p.value)
                            if p.address >= 0xBF10:  # A few subroutines must also be mirrored in bank 6
                                self.rom.write_word(0x6, p.address, p.value)
                        else:
                            success = False

                            if self._ignore_warnings is False:
                                if self.app.okBox("Save Spell Data",
                                                  f"ERROR: Invalid address 0x{p.address:04X} for Parameter " +
                                                  f"'{p.description}' in Spell#{s}." +
                                                  "\n\nClick 'Cancel' to ignore further warnings.",
                                                  "Party_Editor") is False:
                                    self._ignore_warnings = True

                    # Everything else is 8-bit
                    else:
                        if p.value > 255:
                            if self._ignore_warnings is False:
                                if self.app.okBox("Save Spell Data",
                                                  f"ERROR: Spell#{s} invalid data for parameter: " +
                                                  f"'{p.description}': expecting 8-bit value, got {p.value} instead." +
                                                  "\n\nClick 'Cancel' to ignore further warnings.",
                                                  "Party_Editor") is False:
                                    self._ignore_warnings = True
                            success = False
                        else:
                            if p.address >= 0xC000:
                                self.rom.write_byte(0xF, p.address, p.value)
                            elif p.address >= 0x8000:
                                self.rom.write_byte(0x0, p.address, p.value)
                                if p.address >= 0xBF10:
                                    self.rom.write_byte(0x6, p.address, p.value)
                            else:
                                success = False

                                if self._ignore_warnings is False:
                                    if self.app.okBox("Save Spell Data",
                                                      f"ERROR: Invalid address 0x{p.address:04X} for Parameter " +
                                                      f"'{p.description}' in Spell#{s}." +
                                                      "\n\nClick 'Cancel' to ignore further warnings.",
                                                      "Party_Editor") is False:
                                        self._ignore_warnings = True

        self._ignore_warnings = False

        return success

    # --- PartyEditor.save_special_abilities() ---

    def save_special_abilities(self) -> bool:
        """
        Applies changes to ROM buffer.

        Returns
        -------
        bool
            True if changes successfully applied. False if any of the data was not valid.
        """
        # Sanity checks on entry field values
        try:
            custom_1 = int(self.app.getEntry("PE_Custom_1"), 16)
        except ValueError:
            self.app.errorBox("Error applying changes",
                              f"Value for custom index on Special Ability 1 is not valid.\n"
                              f"Please enter a hexadecimal value in the format '0x1A'.",
                              "Party_Editor")
            return False

        try:
            custom_2 = int(self.app.getEntry("PE_Custom_2"), 16)
        except ValueError:
            self.app.errorBox("Error applying changes",
                              f"Value for custom index on Special Ability 2 is not valid.\n"
                              f"Please enter a hexadecimal value in the format '0x1A'.",
                              "Party_Editor")
            return False

        adjustment_3 = 0
        box = self.app.getOptionBoxWidget("PE_Adjustment_2")
        value = box.options.index(self.app.getOptionBox("PE_Adjustment_2"))
        # Only enable input from adjustment value if needed
        if value == 1 or value == 2:
            self.app.enableEntry("PE_Adjustment_3")
            try:
                # Only check this value if needed
                adjustment_3 = int(self.app.getEntry("PE_Adjustment_3"), 10)
            except ValueError:
                self.app.errorBox("Error applying changes",
                                  f"Damage Adjustment value for Special Ability 2 is not valid.\n"
                                  f"Please enter a decimal numeric value between 0 and 255.",
                                  "Party_Editor")
                return False

        if custom_1 > 255:
            custom_1 = 255
            self.app.clearEntry("PE_Custom_1", callFunction=False, setFocus=False)
            self.app.setEntry("PE_Custom_1", f"0x{custom_1:02X}", callFunction=False)

        if custom_2 > 255:
            custom_2 = 255
            self.app.clearEntry("PE_Custom_2", callFunction=False, setFocus=False)
            self.app.setEntry("PE_Custom_2", f"0x{custom_2:02X}", callFunction=False)

        if adjustment_3 > 255:
            adjustment_3 = 255
            self.app.clearEntry("PE_Adjustment_3", callFunction=False, setFocus=False)
            self.app.setEntry("PE_Adjustment_3", f"0x{adjustment_3:02X}", callFunction=False)

        # Save code and values to ROM buffer

        # Ability 0: Double MP regeneration
        box = self.app.getOptionBoxWidget("PE_Profession_0")
        value = box.options.index(self.app.getOptionBox("PE_Profession_0"))
        # Bank 0xD
        # 8713    LDA $2A
        # 8715    CMP #$08  ; <-- Profession
        self.rom.write_byte(0xD, 0x8716, value)

        # Ability 1: Critical hit

        box = self.app.getOptionBoxWidget("PE_Profession_1")
        value = box.options.index(self.app.getOptionBox("PE_Profession_1"))
        # Bank 0
        # B0C4    LDA ($99),Y
        # B0C6    CMP #$03  ; <-- Profession
        self.rom.write_byte(0x0, 0xB0C7, value)

        # Critical hit damage value
        # Bank 0
        # B0DE    LDY #$08  ; <-- #$08 = Dexterity
        # B0E0    LDA ($99),Y
        # B0E2    CLC
        # B0E3    ADC $51
        box = self.app.getOptionBoxWidget("PE_Damage_1")
        value = box.options.index(self.app.getOptionBox("PE_Damage_1"))
        if 0 <= value <= 3:
            # First ability index = 7
            value = value + 7
        else:
            value = custom_1

        self.rom.write_byte(0x0, 0xB0DF, value)

        # Ability 2: Extra damage

        box = self.app.getOptionBoxWidget("PE_Profession_2")
        value = box.options.index(self.app.getOptionBox("PE_Profession_2"))
        # Bank 0
        # B0E8    CMP #$05  ; <-- Profession
        # B0EA    BNE $B0F9
        self.rom.write_byte(0x0, 0xB0E9, value)

        # Extra damage base value
        # Bank 0
        # B0EC    LDY #$33  ; #$33 = Level
        # B0EE    LDA ($99),Y
        box = self.app.getOptionBoxWidget("PE_Damage_2")
        value = box.options.index(self.app.getOptionBox("PE_Damage_2"))
        if 0 <= value <= 3:
            # First ability index = 7
            value = value + 7
        elif value == 4:
            # Level index
            value = 0x33
        elif value == 5:
            # Weapon index
            value = 0x34
        else:
            # Custom index
            value = custom_2
        self.rom.write_byte(0x0, 0xB0ED, value)

        # Extra damage adjustment
        # Bank 0
        # B0F0    SEC       ; Default / base code
        # B0F1    SBC #$01  ; = subtract 1
        # Default bytecode: $38 $E9 $01
        byte_code = bytearray([0x38, 0xE9, 0x01])
        box = self.app.getOptionBoxWidget("PE_Adjustment_2")
        value = box.options.index(self.app.getOptionBox("PE_Adjustment_2"))
        if value == 0:
            # No adjustment
            # JMP B0F3
            byte_code = bytearray([0x4C, 0xF3, 0xB0])

        elif value == 1:
            # Subtract
            # SEC
            # SBC #_adjustment
            byte_code = bytearray([0x38, 0xE9, adjustment_3])

        elif value == 2:
            # Add
            # CLC
            # ADC #_adjustment
            byte_code = bytearray([0x18, 0x69, adjustment_3])

        elif value == 3:
            # x 2
            # ASL
            # SKB #_adjustment  ; Value is ignored, but at least we save it in case we want to change the condition only
            byte_code = bytearray([0x0A, 0x80, adjustment_3])

        elif value == 4:
            # x 4
            # ASL
            # ASL
            # NOP
            byte_code = bytearray([0x0A, 0x0A, 0xEA])

        elif value == 5:
            # / 2
            # LSR
            # SKB #_adjustment
            byte_code = bytearray([0x4A, 0x80, adjustment_3])

        elif value == 6:
            # / 4
            # LSR
            # LSR
            # NOP
            byte_code = bytearray([0x4A, 0x4A, 0xEA])

        self.rom.write_bytes(0x0, 0xB0F0, byte_code)

        return True

    # --- PartyEditor.save_pre_made() ---

    def save_pre_made(self) -> None:
        # Bank 0xC
        address = 0xA941

        for p in range(12):
            pre_made = self.pre_made[p]

            # Write name (5 bytes)

            # Truncate the name if too long first
            if len(pre_made.name) > 5:
                pre_made.name = pre_made.name[:5]

            name = ascii_to_exodus(pre_made.name)

            # Add zeroes if shorter than 5 bytes
            if len(name) < 5:
                for _ in range(5 - len(name)):
                    name.append(0)

            self.rom.write_bytes(0xC, address, name)
            address = address + 5

            # Write race ID
            self.rom.write_byte(0xC, address, pre_made.race)
            address = address + 1

            # Write profession ID
            self.rom.write_byte(0xC, address, pre_made.profession)
            address = address + 1

            # Write attributes
            for a in range(4):
                self.rom.write_byte(0xC, address, pre_made.attributes[a])
                address = address + 1

            # Last 5 bytes that are always 00 01 00 00 00
            self.rom.write_bytes(0xC, address, bytearray([0, 1, 0, 0, 0]))
            address = address + 5

    # --- PartyEditor.save_professions() ---

    def save_professions(self) -> bool:
        """
        Saves professions data to the ROM buffer
        """
        if self._save_profession_names() is False:
            self.app.errorBox("Profession Editor", "Error saving profession names!", parent="Profession_Editor")
            return False

        if self._save_profession_data() is False:
            self.app.errorBox("Profession Editor", "Error saving profession data!", parent="Profession_Editor")
            return False

        return True

    # --- PartyEditor.save_races() ---

    def save_races(self) -> bool:
        """
        Saves race and attribute data to the ROM buffer
        Returns
        """
        if self._save_race_names() is False:
            self.app.errorBox("Race Editor", "Error saving race names!\nPlease try using shorter names.",
                              parent="Race Editor")
            return False

        if self._save_attribute_names() is False:
            self.app.errorBox("Race Editor", "Error saving attribute names!", parent="Race Editor")
            return False

        self._save_race_data()

        return True
