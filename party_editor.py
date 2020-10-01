__author__ = "Fox Cunning"

from typing import List

from PIL import Image, ImageTk

from appJar import gui
from debug import log
from palette_editor import PaletteEditor
from rom import ROM
from text_editor import TextEditor, exodus_to_ascii, ascii_to_exodus


class PartyEditor:
    def __init__(self, app: gui, rom: ROM, text_editor: TextEditor, palette_editor: PaletteEditor):
        self.app: gui = app
        self.rom: ROM = rom
        self.text_editor: TextEditor = text_editor
        self.palette_editor: PaletteEditor = palette_editor
        self.current_window: str = ""

        # We store values that can be modified and written back to ROM within this class
        self.race_names: List[str] = []
        self.profession_names: List[str] = []
        self.attribute_names: List[str] = ["", "", "", ""]
        self.weapon_names: List[str] = []
        self.armour_names: List[str] = []

        # Number of selectable races for character creation
        self.selectable_races: int = 5

        self.best_weapon: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.best_armour: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

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
        # MAx starting attribute values for each race
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
        # Colours for Status Screen / Character Creation Menu
        self.colour_indices: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        # Colours for map/battle sprites
        self.sprite_colours: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        # Number of selectable professions (11 by default)
        self.selectable_professions: int = 11

        # Currently selected race/profession/weapon/spell etc. (depending on current window)
        self.selected_index: int = -1

    # --- PartyEditor.show_races_window() ---

    def show_window(self, window_name: str):
        self.app.emptySubWindow("Party_Editor")

        if window_name == "Races":
            self._create_races_window()

        elif window_name == "Professions":
            self._create_professions_window()

        else:
            return

        self.current_window = window_name
        self.selected_index = -1

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

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(320, 280)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", row=0, column=0, padding=[4, 0], colspan=2,
                                sticky='NEW', stretch='ROW'):
                self.app.button("PE_Apply", name="Apply", value=self._races_input, image="res/floppy.gif",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                tooltip="Discard Changes and Close Window", row=0, column=1)

            with self.app.frame("PE_Frame_Races", row=1, column=0, stretch="BOTH", sticky="NEWS", padding=[4, 2],
                                bg="#F0F0D0"):
                # Row 0
                self.app.label("PE_Label_r0", "Selectable Races:", row=0, column=0)
                self.app.spinBox("PE_Spin_Races", list(range(5, 0, -1)), width=3, row=0, column=1,
                                 change=self._races_input)
                self.app.setSpinBox("PE_Spin_Races", self.selectable_races)

                # Row 1
                self.app.label("PE_Label_r1", "Edit Race:", row=1, column=0)
                self.app.optionBox("PE_Option_Race", race_names, row=1, column=1, change=self._races_input)

                # Row 2
                self.app.label("PE_Label_r2", "Max Attribute Values:", row=2, column=0, colspan=2)

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
                                      row=0, column=0, colspan=3)
                    # Row 1, Col 0
                    self.app.label("PE_Label_Race_Gender", "Gender Chr.:", row=1, column=0)
                    # Row 1, Col 1
                    self.app.entry("PE_Gender_Character", "0x00", width=4, fg="#000000", font=9,
                                   change=self._races_input, row=1, column=1)
                    # Row 1, Col 2
                    self.app.canvas("PE_Canvas_Gender", width=16, height=16, bg="#000000", map=None, sticky="W",
                                    row=1, column=2)

            with self.app.frame("PE_Frame_Race_Names", row=1, column=1, padding=[4, 2]):
                self.app.label("PE_Label_Race_Names", value="Race Names:", row=0, column=0)
                self.app.textArea("PE_Race_Names", value=race_text, change=self._races_input, row=1, column=0,
                                  width=12, height=9, fg="#000000")
                self.app.button("PE_Update_Race_Names", name="Update", value=self._races_input,
                                row=2, column=0)

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

        # Read number of selectable professions
        # We use the routine at 0C:8D76 which creates the race/profession menu for character creation
        # This value is the 0-based index of the last possible selection, so we add 1
        self.selectable_professions = self.rom.read_byte(0xC, 0x8ECB) + 1

        with self.app.subWindow("Party_Editor"):
            self.app.setSize(440, 420)

            # Buttons
            with self.app.frame("PE_Frame_Buttons", row=0, column=0, padding=[4, 2], sticky="NEW", stretch="BOTH"):
                self.app.button("PE_Apply", name="Apply", value=self._professions_input, image="res/floppy.gif",
                                sticky="NE",
                                tooltip="Apply Changes and Close Window", row=0, column=0)
                self.app.button("PE_Cancel", name="Cancel", value=self._generic_input, image="res/close.gif",
                                sticky="NW",
                                tooltip="Discard Changes and Close Window", row=0, column=1)
                # Left Column
                with self.app.frame("PE_Frame_Left", row=1, column=0, stretch="BOTH", sticky="NEWS", padding=[4, 2],
                                    colspan=2, bg="#C0D0F0"):
                    # --- Profession selection ---

                    # Row 0 Col 0
                    self.app.label("PE_Label_Professions", "Selectable Prof.:", row=0, column=0)
                    # Row 0 Col 1
                    self.app.spinBox("PE_Spin_Professions", list(range(11, 0, -1)),
                                     change=self._professions_input, width=3, row=0, column=1)
                    self.app.setSpinBox("PE_Spin_Professions", self.selectable_professions)
                    # Row 1 Col 0, 1
                    self.app.optionBox("PE_Option_Profession", professions_list, change=self._professions_input,
                                       row=1, column=0, colspan=2)

                    # --- Status / Character creation graphics and map / battle sprite ---

                    # Row 2 Col 0, 1
                    with self.app.frame("PE_Frame_Graphics", row=2, column=0, colspan=2):
                        # Row 0 Col 0
                        self.app.canvas("PE_Canvas_Profession", Map=None, width=48, height=48, bg="#000000",
                                        sticky="W", row=0, column=0)
                        # Row 0 Col 1
                        self.app.canvas("PE_Canvas_Sprite", Map=None, width=32, height=32, bg="#C0C0C0",
                                        sticky="W", row=0, column=1)
                        # Row 1 Col 0
                        self.app.label("PE_Label_Colours", "Colours:", row=1, column=0)
                        # Row 1 Col 1
                        self.app.label("PE_Label_Palettes", "Palettes:", row=1, column=1)
                        # Row 2 Col 0
                        self.app.optionBox("PE_Profession_Colours", colours_list, change=self._professions_input,
                                           sticky="NW", row=2, column=0)
                        # Row 2 Col 1
                        self.app.optionBox("PE_Sprite_Palette_Top", list(range(0, 4)), change=self._professions_input,
                                           sticky="NW", row=2, column=1)
                        # Row 3 Col 1
                        self.app.optionBox("PE_Sprite_Palette_Bottom", list(range(0, 4)),
                                           change=self._professions_input, sticky="NW", row=3, column=1)

                    # --- Equipment ---

                    # Row 3 Col 0, 1
                    with self.app.frame("PE_Frame_Gear", padding=[4, 2], row=3, column=0, colspan=2):
                        # Row 0
                        self.app.label("PE_Label_Best_Weapon", "Best Weapon:", row=0, column=0)
                        self.app.optionBox("PE_Option_Weapon", self.weapon_names, change=self._professions_input,
                                           width=10, row=0, column=1)
                        # Row 1
                        self.app.label("PE_Label_Best_Armour", "Best Armour:", row=1, column=0)
                        self.app.optionBox("PE_Option_Armour", self.armour_names, change=self._professions_input,
                                           width=10, row=1, column=1)

                    # --- Gender ---

                    # Row 4 Col 0, 1
                    with self.app.frame("PE_Frame_Gender", padding=[4, 2], row=4, column=0, colspan=2):
                        # Row 0, Col 0, 1, 2
                        self.app.checkBox("PE_Check_Gender", text="Gender based on Profession",
                                          value=self.gender_by_profession, change=self._professions_input,
                                          row=0, column=0, colspan=3)
                        # Row 1, Col 0
                        self.app.label("PE_Label_Gender", "Gender Chr.:", row=1, column=0)
                        # Row 1, Col 1
                        self.app.entry("PE_Gender_Character", "0x00", width=4, fg="#000000", font=9,
                                       change=self._professions_input, row=1, column=1)
                        # Row 1, Col 2
                        self.app.canvas("PE_Canvas_Gender", width=16, height=16, bg="#000000", map=None, sticky="W",
                                        row=1, column=2)

            # Right Column
            with self.app.frame("PE_Frame_Right", row=0, column=1, stretch="BOTH", sticky="NEW", padding=[4, 2],
                                bg="#C0F0D0"):
                self.app.label("PE_Label_Names", "Profession Names:", sticky="NEW", row=0, column=0)
                self.app.textArea("PE_Profession_Names", value=profession_names, width=10, height=11, font=9,
                                  change=self._professions_input,
                                  sticky="NEW", fg="#000000", scroll=True, row=1, column=0)
                self.app.button("PE_Update_Profession_Names", value=self._professions_input, name="Update",
                                sticky="NEW", row=2, column=0)

            # --- Primary Attributes ---

            # Row 5, Col 0, 1
            with self.app.frame("PE_Frame_Primary_Attributes", padding=[4, 2], row=1, column=0, expand="BOTH",
                                stretch="ROW", sticky="NEW", bg="#C0D0F0"):
                # Row 0, Col 0, 1
                self.app.label("PE_Label_Primary_Attributes", "Primary Attributes:", sticky="EW",
                               row=0, column=0, colspan=2)
                # Row 1, Col 0
                self.app.optionBox("PE_Primary_0", self.attribute_names, change=self._professions_input,
                                   row=1, column=0)
                # Row 1, Col 1
                self.app.optionBox("PE_Primary_1", self.attribute_names, change=self._professions_input,
                                   row=1, column=1)

            with self.app.frame("PE_Frame_HP", row=1, column=1, stretch="ROW", sticky="NEW", padding=[4, 4],
                                expand="BOTH", bg="#C0D0F0"):
                # Row 0
                self.app.label("PE_Label_HP", "HP gain:", row=0, column=0, colspan=4)
                # Row 1
                self.app.entry("PE_HP_Base", 0, width=3, fg="#000000", font=9, change=self._professions_input,
                               row=1, column=0)
                self.app.label("PE_Label_Plus", "+ (", row=1, column=1)
                self.app.entry("PE_HP_Bonus", 0, width=3, fg="#000000", font=9, change=self._professions_input,
                               row=1, column=2)
                self.app.label("PE_Label_Per_Level", "x level)", row=1, column=3)

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

    # --- PartyEditor.close_window() ---

    def close_window(self) -> bool:
        """
        Closes the editor window

        Returns
        -------
        bool
            True if the window was closed, False otherwise (e.g. user cancelled)
        """
        # TODO Ask to confirm
        self.current_window = ""
        self.app.hideSubWindow("Party_Editor", False)
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
            self.gender_by_profession = self.app.getCheckBox(widget)

        else:
            log(3, f"{self}", f"Unimplemented widget callback from '{widget}'.")

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
                self.close_window()

        elif widget == "PE_Gender_By_Race":
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
                self.app.textArea(widget, fg="#CF0000")
            else:
                self.app.textArea(widget, fg="#000000")

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

        elif widget == "PE_Gender_Character":
            try:
                text: str = self.app.getEntry(widget)
                value: int = int(text, 16)
                if 0 < value < 256:
                    self._display_gender(value)
                    self.gender_char[self.selected_index] = value

            except ValueError:
                return

        else:
            log(3, f"{self}", f"Unimplemented widget callback from '{widget}'.")

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
            except ValueError:
                if value == '':
                    pass
                else:
                    log(3, f"{self}", f"Invalid value '{value}' for professions count.")

        elif widget == "PE_Profession_Names":
            # Make sure the total length including newlines and string terminator is not over 59
            names = self.app.getTextArea(widget)
            if (len(names) + 1) > 59:
                self.app.textArea(widget, fg="#CF0000")
            else:
                self.app.textArea(widget, fg="#000000")

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

        elif widget == "PE_Profession_Colours":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                self.colour_indices[self.selected_index] = box.options.index(value)
                # Update canvas
                self._load_profession_graphics()

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

                # Update sprite
                self._load_profession_sprite()

        elif widget == "PE_Primary_0":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                primary_0 = box.options.index(value)

                self.primary_attributes[self.selected_index][0] = primary_0

        elif widget == "PE_Primary_1":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                primary_1 = box.options.index(value)

                self.primary_attributes[self.selected_index][1] = primary_1

        elif widget == "PE_Option_Weapon":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                weapon = box.options.index(value)

                self.best_weapon[self.selected_index] = weapon

        elif widget == "PE_Option_Armour":
            if self.selected_index >= 0:
                value = self.app.getOptionBox(widget)
                box = self.app.getOptionBoxWidget(widget)
                armour = box.options.index(value)

                self.best_weapon[self.selected_index] = armour

        elif widget == "PE_HP_Base":
            value = self.app.getEntry(widget)
            try:
                self.hp_base = int(value, 10)
            except ValueError:
                pass

        elif widget == "PE_HP_Bonus":
            if self.selected_index >= 0:
                value = self.app.getEntry(widget)
                try:
                    self.hp_bonus[self.selected_index] = int(value, 10)
                except ValueError:
                    pass

        elif widget == "PE_Apply":
            if self.save_professions() is not False:
                self.close_window()

        else:
            log(3, f"{self}", f"Unimplemented widget callback: '{widget}'.")

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

    # --- PartyEditor._read_weapon_armour_names() ---

    def _read_weapon_armour_names(self) -> None:
        """
        Reads and decodes weapon/armour names from ROM, caching them as ASCII strings for editing
        """
        # Read and decode weapon/armour names for "best weapon/armour" stats
        self.weapon_names: List[str] = [""]
        self.armour_names: List[str] = [""]

        # The actual weapon/armour names come first in ROM, the default HAND/SKIN strings follow
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
            if count < 15:
                self.weapon_names.append(ascii_string.strip(" "))
            elif count == 22:
                self.weapon_names[0] = ascii_string.strip(" ")
            elif count == 23:
                self.armour_names[0] = ascii_string.strip(" ")
            else:
                self.armour_names.append(ascii_string.strip(" "))

            count = count + 1

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
            log(2, f"{self}", f"Invalid colour index #{colour_index} for profession graphics!")
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

    # --- PartyEditor._load_profession_sprite() ---

    def _load_profession_sprite(self) -> None:
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

    # --- PartyEditor.race_info() ---

    def race_info(self) -> None:
        """
        Show info for the currently selected race
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

    # --- PartyEditor.profession_info() ---

    def profession_info(self) -> None:
        """
        Shows info for the currently selected profession
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
        self._load_profession_sprite()

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
        self.app.clearEntry("PE_HP_Base", callFunction=False)
        self.app.clearEntry("PE_HP_Bonus", callFunction=False)
        self.app.setEntry("PE_HP_Base", self.hp_base, callFunction=False)
        self.app.setEntry("PE_HP_Bonus", self.hp_bonus[self.selected_index], callFunction=False)

        # Best weapon/armour
        self.app.setOptionBox("PE_Option_Weapon", self.best_weapon[self.selected_index], callFunction=False)
        self.app.setOptionBox("PE_Option_Armour", self.best_armour[self.selected_index], callFunction=False)

    # --- PartyEditor._display_gender() ---

    def _display_gender(self, character_index: int) -> None:
        """
        Reads gender pattern from ROM and displays it as an image on the gender canvas

        Parameters
        ----------
        character_index: int
            Index of the character to load from character memory
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
        Saves profession names used for the Status screen into the ROM buffer

        Returns
        -------
        bool
            True if the operation completed successfully, False otherwise
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
        Saves race names to ROM buffer

        Returns
        -------
        bool
            True if operation completed successfully, False otherwise
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
        Saves attribute names (by default "STR", "INT", "DEX", "WIS") to the ROM buffer

        Returns
        -------
        bool
            True if the operation completed successfully, False otherwise
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
        Applies changes to rom buffer, doesn't save to file
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

    # --- PartyEditor._save_profession_data() ---

    def _save_profession_data(self) -> None:
        """
        Applies changes to rom buffer, doesn't save to file
        """
        # Starting HP values and bonus HP per level
        for p in range(len(self.hp_bonus)):
            self.rom.write_byte(0xC, 0xBFE4 + p, self.hp_bonus[p] + self.hp_base)
            self.rom.write_byte(0xD, 0x889F + p, self.hp_bonus[p])

        # Base HP
        self.rom.write_byte(0xD, 0x8872, self.hp_base)

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

        for i in range(11):
            # 2 bytes per entry: multiply index x2 (or shift 1 bit left)
            address = 0x97D6 + (i << 1)

            primary_0 = self.primary_attributes[i][0] + 7
            primary_1 = self.primary_attributes[i][1] + 7

            self.rom.write_byte(0xC, address, primary_0)
            self.rom.write_byte(0xC, address + 1, primary_1)

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

        # Save HP gain data
        if self.rom.has_feature("enhanced party"):
            self.rom.write_byte(0xD, 0x8872, self.hp_base)

            for i in range(11):
                self.rom.write_byte(0xD, 0x889F + i, self.hp_bonus[i])

        else:
            self.rom.write_byte(0xD, 0x8870, self.hp_base)
            self.rom.write_byte(0xD, 0x8866, self.hp_bonus[0])

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
            self.rom.write_byte(0xC, 0x8ECA, self.selectable_professions - 1)

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
            self.rom.write_byte(0xC, 0x8ECA, self.selectable_professions - 1)

            # Number of professions in the right column
            self.rom.write_byte(0xC, 0x8DEE, self.selectable_professions - 6)

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
