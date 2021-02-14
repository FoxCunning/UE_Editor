"""
An extensive editor for the NES version of Ultima III: Exodus and its Remastered Hack by Fox Cunning
"""
__version__ = "Pre-Alpha 0.2"

__author__ = "Fox Cunning"
__copyright__ = "Copyright ©2020-2021 Fox Cunning"
__credits__ = ["Fox Cunning"]

__license__ = "Apache 2.0"

__maintainer__ = "Fox Cunning"
__email__ = "fox.cunning@mail.co.uk"
__status__ = "Pre-Release"

import ast
import os
import shlex
import subprocess
import sys

import pyo

import colour

from typing import List

from APU.APU import APU
from appJar import gui
from battlefield_editor import BattlefieldEditor
from editor_settings import EditorSettings
from cutscene_editor import CutsceneEditor
from debug import log
from end_game_editor import EndGameEditor
from enemy_editor import EnemyEditor
from map_editor import MapEditor
from palette_editor import PaletteEditor
from party_editor import PartyEditor
from rom import ROM, feature_names
from music_editor import MusicEditor
from sfx_editor import SFXEditor
from text_editor import TextEditor, read_text

# ----------------------------------------------------------------------------------------------------------------------

settings = EditorSettings()

rom = ROM()

emulator_pid: subprocess.Popen

# Index of the selected map from the drop-down option box
selected_map: int = -1

# Compression method for the selected map
map_compression: str = "none"

# Sub-window handlers
map_editor: MapEditor
text_editor: TextEditor
palette_editor: PaletteEditor
enemy_editor: EnemyEditor
party_editor: PartyEditor
end_game_editor: EndGameEditor
cutscene_editor: CutsceneEditor
music_editor: MusicEditor
battlefield_editor: BattlefieldEditor
sfx_editor: SFXEditor


# ----------------------------------------------------------------------------------------------------------------------

def get_option_index(widget: str, value: str = "") -> int:
    """
    Retrieves the index of the desired item from an OptionBox

    Parameters
    ----------
    widget: str
        Name of the OptionBox widget
    value: str
        Value of the item whose index is to be retrieved, if empty use the currently selected value

    Returns
    -------
    int
        The index of the item; rises ValueError if not found
    """
    if value == "":
        value = app.getOptionBox(widget)

    box = app.getOptionBoxWidget(widget)
    return box.options.index(value)


# ----------------------------------------------------------------------------------------------------------------------

def edit_map() -> None:
    """
    Called when the user clicks on the map canvas in the map editor sub-window
    """
    global selected_map
    global map_compression

    # Apply changes to map info before opening this map
    map_editor.map_table[selected_map].bank = int(app.getEntry("MapInfo_Bank"), 16)
    map_editor.map_table[selected_map].data_pointer = int(app.getEntry("MapInfo_DataPtr"), 16)
    map_editor.map_table[selected_map].npc_pointer = int(app.getEntry("MapInfo_NPCPtr"), 16)
    map_editor.map_table[selected_map].entry_y = int(app.getEntry("MapInfo_EntryY"))
    map_editor.map_table[selected_map].entry_x = int(app.getEntry("MapInfo_EntryX"))
    map_editor.map_table[selected_map].flags = int(app.getEntry("MapInfo_Flags"), 16)

    map_editor.show_window()
    if map_editor.is_dungeon() is False:
        map_editor.load_npc_sprites()  # Reload NPC sprites to refresh palettes
    map_editor.load_tiles(selected_map)

    # TODO Force compression if checked
    map_editor.open_map(selected_map)

    # Hide the special tile info for now
    app.hideFrame("ME_Frame_Special_Tile")

    # Only show the Entrance and NPC editor for non-dungeon maps
    if map_editor.is_dungeon():
        app.hideSubWindow("NPC_Editor")
        app.showFrame("ME_Frame_Dungeon_Tools")
        # Move the scrollbars to the top and left
        pane = app.getScrollPaneWidget("ME_Scroll_Pane")
        pane.hscrollbar.set(0.1, 0.9)
        pane.vscrollbar.set(0.1, 0.9)
        pane.canvas.xview_moveto(0)
        pane.canvas.yview_moveto(0)
        pane.canvas.configure(width=448)
    else:
        map_editor.load_npc_data()
        # Move the map editor and the NPC editor relatively to the main window
        main_location = app.getLocation()
        app.setSubWindowLocation("Map_Editor", main_location[0], main_location[1])
        app.setSubWindowLocation("NPC_Editor", main_location[0] + 514, main_location[1])
        app.setSubWindowLocation("Entrance_Editor", main_location[0] - 258, main_location[1])

        app.hideFrame("ME_Frame_Dungeon_Tools")

        app.hideLabelFrame("NPCE_Frame_Info")
        app.showSubWindow("NPC_Editor", hide=False)

        app.showSubWindow("Entrance_Editor", hide=False)

        # Show entrances and Moongates
        map_editor.load_entrances()
        map_editor.load_moongates()

        app.getScrollPaneWidget("ME_Scroll_Pane").canvas.configure(width=508)


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


# ----------------------------------------------------------------------------------------------------------------------

def encounter_input(widget: str) -> None:
    """
    Callback for input on the Enemies Tab's widgets pertaining to Encounter Tables

    Parameters
    ----------
    widget: str
        Name of the widget generating the event
    """
    if widget[:-1] == "ET_Encounter_":
        # Get encounter index
        try:
            index = int(widget[-1])
            value = int(app.getEntry(widget), 16)
            enemy_editor.change_encounter(index, value)

        except ValueError:
            return


# ----------------------------------------------------------------------------------------------------------------------

def enemy_editor_input(widget: str) -> None:
    """
    Callback for input on the Enemies Tab's widgets

    Parameters
    ----------
    widget: str
        Name of the widget that has generated the call
    """
    if widget == "ET_Option_Enemies":
        try:
            index = int(app.getOptionBox("ET_Option_Enemies")[:4], 16)
            # Ask the Enemy Editor to populate the info widgets
            enemy_editor.enemy_info(enemy_index=index)

            # Show the Enemy detail, hide the Encounter info
            app.hideFrame("ET_Frame_Encounter")
            app.showFrame("ET_Frame_Enemy")

        except ValueError:
            log(3, "ENEMY EDITOR", f"Invalid enemy selection: {app.getOptionBox(widget)[:4]}")

    elif widget == "ET_Base_HP":
        try:
            value = int(app.getEntry("ET_Base_HP"))
            enemy_editor.change_stats(base_hp=value)
        except ValueError:
            return

    elif widget == "ET_Base_XP":
        try:
            value = int(app.getEntry("ET_Base_XP"))
            enemy_editor.change_stats(base_xp=value)
        except ValueError:
            return

    elif widget == "ET_Ability":
        try:
            value = get_option_index("ET_Ability", app.getOptionBox("ET_Ability"))
            enemy_editor.change_stats(ability=value)
        except ValueError:
            log(3, "ENEMY EDITOR", "Invalid selection for enemy ability!")
            return

    elif widget == "ET_Big_Sprite":
        value = app.getCheckBox("ET_Big_Sprite")
        enemy_editor.change_sprite(big_sprite=value)

    elif widget == "ET_Palette_1" or widget == "ET_Palette_2":
        try:
            value_1 = int(app.getOptionBox("ET_Palette_1"))
            value_2 = int(app.getOptionBox("ET_Palette_2"))
            enemy_editor.change_sprite(colours=[value_1 << 2 | value_2, 0xFF, 0xFF])

        except ValueError:
            log(3, "ENEMY EDITOR", "Invalid values for palettes!")
            return

    elif widget == "ET_Colour_1" or widget == "ET_Colour_2" or widget == "ET_Colour_3":
        try:
            value_1 = int(app.getOptionBox("ET_Colour_1"))
            value_2 = int(app.getOptionBox("ET_Colour_2"))
            value_3 = int(app.getOptionBox("ET_Colour_3"))
            enemy_editor.change_sprite(colours=[value_1, value_2, value_3])

        except ValueError:
            log(3, "ENEMY EDITOR", "Invalid values for colours!")
            return

    elif widget == "ET_Sprite_Address":
        # Check if valid input
        text = app.getEntry("ET_Sprite_Address")

        if len(text) != 6:
            # Not enough digits: mark as invalid
            app.entry("ET_Sprite_Address", fg=colour.DARK_RED)
            return

        try:
            address = int(text, 16)
            if address < 0x8000 or address > 0xBFFF:
                # Out of range
                app.entry("ET_Sprite_Address", fg=colour.DARK_RED)
                return

            # Valid input: change address and reload sprite
            app.entry("ET_Sprite_Address", fg=colour.DARK_GREEN)
            enemy_editor.change_sprite(sprite_address=address)

        except ValueError:
            # Not a valid hex value
            app.entry("ET_Sprite_Address", fg=colour.DARK_RED)
            return

    elif widget == "ET_List_Encounters":
        # Get the index of the selected encounter table
        value = app.getListBoxPos("ET_List_Encounters")
        if value:
            enemy_editor.encounter_info(encounter_index=value[0])
            app.hideFrame("ET_Frame_Enemy")
            app.showFrame("ET_Frame_Encounter")

    elif widget == "ET_Button_Apply":
        enemy_editor.save()

        # Reload NPC sprite data if palette sync option is selected
        if settings.get("sync npc sprites"):
            map_editor.load_npc_sprites()

    else:
        log(3, "ENEMY EDITOR", f"Unimplemented input from: '{widget}'.")


# ----------------------------------------------------------------------------------------------------------------------

def select_palette(sel: str) -> None:
    """
    An item has been selected from the palettes Option Box in the Palette Editor tab

    Parameters
    ----------
    sel: str
        Name of the Option Box widget
    """
    # log(4, "EDITOR", f"Selected palette: {app.getOptionBox(sel)}")
    palette_set = app.getOptionBox(sel)
    palette_editor.choose_palette_set(palette_set)


# ----------------------------------------------------------------------------------------------------------------------

def cycle_palette_sets(direction: int) -> None:
    """
    Shows different palette sets

    Parameters
    ----------
    direction: int
        0 = Previous palette, 1 = Next
    """
    if direction == 0:  # Previous
        palette_editor.previous_palette()
    else:  # Next
        palette_editor.next_palette()


# ----------------------------------------------------------------------------------------------------------------------

def edit_colour(event: any, palette_index: int) -> None:
    """
    User clicked on a palette's colour with the intention of changing it

    Parameters
    ----------
    event
         Mouse click event instance
    palette_index: int
        Index of the palette being modified
    """
    colour_index = event.x >> 4
    palette_editor.edit_colour(palette_index, colour_index)


# ----------------------------------------------------------------------------------------------------------------------

def pick_colour(event: any) -> None:
    """
    User clicked on the NES palette to choose a new colour

    Parameters
    ----------
    event
        Mouse click event instance
    """
    colour_index = (event.x >> 4) + ((event.y >> 4) << 4)
    # print(f"*DEBUG* Picked colour {colour_index:02X}")
    palette_editor.change_colour(colour_index)


# ----------------------------------------------------------------------------------------------------------------------

def edit_text() -> None:
    """
    User clicked on the "More Actions" button in the Text Editor Tab
    """
    # Retrieve selection value
    if text_editor.index < 0:
        return

    # If valid selection, get the index
    string_index = text_editor.index
    # Get string type
    string_type = app.getOptionBox("Text_Type")

    text_editor.show_advanced_window(string_index, string_type)


# ----------------------------------------------------------------------------------------------------------------------

# noinspection PyArgumentList
def close_rom() -> None:
    """
    Closes the ROM file and releases all its resources
    """
    global rom
    rom.close()
    # Clear ROM Info labels
    app.setLabel("RomInfo_0", "Open a ROM file to begin...")
    app.showLabel("RomInfo_0")
    for idx in range(1, 9):
        app.setLabel(f"RomInfo_{idx}", "")
    # Hide features list
    for feature in range(11):
        app.hideCheckBox(f"Feature_{feature}")
    # Close all sub-windows
    app.hideAllSubWindows(False)
    # Deactivate all tabs
    app.setTabbedFrameDisabledTab("TabbedFrame", "Map", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Misc", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Enemies", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Text", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Palettes", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Screens", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "\u266B", True)
    app.setStatusbar("ROM file closed.", field=0)
    app.setTitle("UE Editor")


# ----------------------------------------------------------------------------------------------------------------------

def save_rom(file_name: str) -> None:
    """
    Saves the current ROM data to file

    Parameters
    ----------
    file_name: str
        Full path of the file name to save to
    """
    # Write any unsaved changes to the buffer before saving the file
    palette_editor.save_palettes()

    if file_name == rom.path and settings.get("make backups"):
        index = file_name.rfind('.')
        if index > -1:
            backup_name = file_name[:index] + ".bak"
        else:
            backup_name = file_name + ".bak"
        rom.save(backup_name)

    if rom.save(file_name) is True:
        file_name = os.path.basename(file_name)
        app.setStatusbar(f"Saved as '{file_name}'.")
    else:
        app.setStatusbar("Save operation failed.")
        app.errorBox("Export ROM", f"ERROR: Could not save to '{file_name}'.")


# ----------------------------------------------------------------------------------------------------------------------

# noinspection PyArgumentList
def open_rom(file_name: str) -> None:
    """
    Opens an Ultima: Exodus ROM file

    Parameters
    ----------
    file_name: str
        Name of the file containing the ROM
    """
    global rom
    global selected_map
    global map_compression
    global text_editor
    global palette_editor
    global map_editor
    global enemy_editor
    global party_editor
    global cutscene_editor
    global music_editor
    global battlefield_editor
    global sfx_editor
    global end_game_editor

    app.setStatusbar(f"Opening ROM file '{file_name}'", field=0)
    val = rom.open(file_name)
    if val != "OK":
        app.setStatusbar(val)
        app.errorBox("ERROR", val)
    else:
        app.showSubWindow("PE_Progress")
        app.setLabel("PE_Progress_Label", "Loading...")
        app.setMeter("PE_Progress_Meter", 0)
        app.topLevel.update()

        # Process header
        h = bytearray(rom.header())
        s = ""
        for c in h[0:3]:
            s += chr(c)
        if s != "NES":
            app.errorBox("ERROR", "Wrong header. This does not look like a valid ROM file!")
            close_rom()
            return
        # app.setLabel("RomInfo_0", "ROM Info:")
        app.hideLabel("RomInfo_0")
        n = h[4] * 16
        app.setLabel("RomInfo_1", f" PRG ROM: {n}KB")
        n = h[5] * 8
        app.setLabel("RomInfo_2", f" CHR ROM: {n}KB")
        n = (h[6] >> 4) | (h[7] & 0xF0)
        app.setLabel("RomInfo_3", f" Mapper: {n}")
        n = h[6] & 0x01
        s = "Vertical"
        if n == 0:
            s = "Horizontal"
        app.setLabel("RomInfo_4", f" Mirroring: {s}")
        n = h[6] & 0x02
        s = "Present"
        if n == 0:
            s = "Not present"
        app.setLabel("RomInfo_5", f" Battery Backed SRAM: {s}")
        n = h[6] & 0x04
        s = "Not Present"
        if n != 0:
            rom.trainer_size = 512
            s = "Present"
        app.setLabel("RomInfo_6", f" Trainer: {s}")
        n = h[9] & 0x01
        s = "NTSC"
        if n != 0:
            s = "PAL"
        app.setLabel("RomInfo_7", f" TV System: {s}")
        s = ""
        for c in h[11:16]:
            s += chr(c)
        app.setLabel("RomInfo_8", f" Extra Data: {s}")

        # Show ROM features
        for feature in range(9):
            app.setCheckBox(f"Feature_{feature}", ticked=rom.has_feature(feature_names[feature]), callFunction=False)
            app.showCheckBox(f"Feature_{feature}")

        app.setMeter("PE_Progress_Meter", 10)
        app.topLevel.update()

        # Create Editor instances
        palette_editor = PaletteEditor(rom, app)
        # Load palettes
        palette_editor.load_palettes()

        app.setMeter("PE_Progress_Meter", 20)
        app.topLevel.update()

        map_colours = []  # Portrait map_colours
        for c in range(4, 8):
            colour_index: int = palette_editor.palettes[0][c]
            colour_value = bytearray(palette_editor.get_colour(colour_index))
            map_colours.append(colour_value[0])  # Red
            map_colours.append(colour_value[1])  # Green
            map_colours.append(colour_value[2])  # Blue

        # This automatically loads text pointer tables and caches dialogue and special strings
        text_editor = TextEditor(rom, map_colours, palette_editor.sub_palette(0, 1), app, settings)

        app.setMeter("PE_Progress_Meter", 30)
        app.topLevel.update()

        # Enemy editor
        enemy_editor = EnemyEditor(app, rom, palette_editor)
        enemy_editor.read_encounters_table()
        enemy_editor.read_enemy_data(text_editor)

        app.setMeter("PE_Progress_Meter", 40)
        app.topLevel.update()

        # Map editor
        map_editor = MapEditor(rom, app, palette_editor, text_editor, enemy_editor, settings)

        # Read tables
        selected_map = 0
        map_editor.update_map_table(map_editor.map_table[selected_map])
        map_compression = "LZSS"
        app.setOptionBox("Map_Compression", 1)

        update_text_table(app.getOptionBox("Text_Type"))

        app.setMeter("PE_Progress_Meter", 50)
        app.topLevel.update()

        # Read map location names from file
        # Update map list for the correct maximum number of maps
        maps = []
        for m in range(0, map_editor.max_maps()):
            name = "(No Name)"
            if m < len(map_editor.location_names):
                name = map_editor.location_names[m].rstrip("\n\r\a")
                if len(name) > 16:  # Truncate names that are too long to be displayed correctly
                    name = name[:15] + '-'
            maps.append(f"0x{m:02X} {name}")
        app.changeOptionBox("MapInfo_Select", maps)
        app.clearOptionBox("MapInfo_Select", callFunction=True)

        app.hideFrame("ET_Frame_Enemy")
        app.hideFrame("ET_Frame_Encounter")

        app.setMeter("PE_Progress_Meter", 60)
        app.topLevel.update()

        app.setStatusbar("Booting sound server...")
        if sys.platform == "win32":
            sound_server: pyo.Server = pyo.Server(sr=settings.get("sample rate"), duplex=0, nchnls=1,
                                                  winhost=settings.get("audio host"), buffersize=1024).boot()
        else:
            sound_server: pyo.Server = pyo.Server(sr=settings.get("sample rate"), duplex=0, nchnls=1,
                                                  buffersize=1024).boot()
        sound_server.setAmp(0.5)

        apu = APU()

        # Music editor
        music_editor = MusicEditor(app, rom, settings, apu, sound_server)
        music_editor.read_track_titles()

        # Try to detect envelope bug
        data = rom.read_bytes(0x8, 0x8248, 3)
        if data[0] == 0x18:  # Bug detected
            if settings.get("fix envelope bug"):
                app.setCheckBox("ST_Fix_Envelope_Bug", ticked=True, callFunction=False)
            else:
                app.setCheckBox("ST_Fix_Envelope_Bug", ticked=False, callFunction=False)
        elif data[0] == 0xEA:  # Fix already present
            app.setCheckBox("ST_Fix_Envelope_Bug", ticked=True, callFunction=False)
        else:  # Custom / unrecognised music driver code
            app.disableCheckBox("ST_Fix_Envelope_Bug")

        app.setStatusbar("Creating interfaces...")
        app.setMeter("PE_Progress_Meter", 70)
        app.topLevel.update()

        # Sound effect editor
        sfx_editor = SFXEditor(app, settings, rom, apu, sound_server)
        names = sfx_editor.read_sfx_names()
        app.changeOptionBox("ST_Option_SFX", [f"0x{n:02X} {names[n]}" for n in range(52)])
        app.setOptionBox("ST_Option_SFX", 0)

        # Battlefield map editor
        battlefield_editor = BattlefieldEditor(app, rom, palette_editor)
        app.changeOptionBox("Battlefield_Option_Map", battlefield_editor.get_map_names(), 0, callFunction=False)
        music_list = music_editor.track_titles[0] + music_editor.track_titles[1]
        app.changeOptionBox("Battlefield_Option_Music", music_list, 0, callFunction=False)

        battlefield_editor.read_tab_data()

        # Default selection
        app.setOptionBox("Battlefield_Option_Map", 0, callFunction=True)
        app.setOptionBox("ST_Music_Bank", 0, callFunction=True)

        app.setMeter("PE_Progress_Meter", 80)
        app.topLevel.update()

        # Party editor
        party_editor = PartyEditor(app, rom, text_editor, palette_editor, map_editor)

        # End game editor
        end_game_editor = EndGameEditor(app, settings, rom, palette_editor)

        app.setMeter("PE_Progress_Meter", 90)
        app.topLevel.update()

        # Cutscene data
        for scene in range(8):
            read_cutscene_data(scene)

        # Cutscene editor
        cutscene_editor = CutsceneEditor(app, rom, palette_editor)

        # Cutscene selection
        screens = ["Lord British", "Time Lord", "Title"]
        marks = read_text(rom, 0xC, 0xA608).splitlines(False)
        if len(marks) != 4:
            screens = screens + ["KING", "FIRE", "FORCE", "SNAKE"]
        else:
            screens = screens + [marks[3], marks[1], marks[0], marks[2]]

        screens.append("Fountain")
        app.changeOptionBox("CE_Option_Cutscene", screens, 0, callFunction=False)

        app.setMeter("PE_Progress_Meter", 100)

        # Activate tabs
        app.setTabbedFrameDisabledTab("TabbedFrame", "Map", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Misc", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Enemies", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Text", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Palettes", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Screens", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "\u266B", False)

        # Add file name to the window's title
        app.setTitle(f"UE Editor - {os.path.basename(file_name)}")

        app.hideSubWindow("PE_Progress")
        app.setStatusbar(f"ROM file opened: '{file_name}'", field=0)


# ----------------------------------------------------------------------------------------------------------------------

def save_cutscene_data(scene: int) -> None:
    # Lord British
    if scene == 0:

        # Party facing direction
        if app.getOptionBoxWidget("CE_Param_0_00").cget("state") != 'disabled':
            value = get_option_index("CE_Param_0_00", app.getOptionBox("CE_Param_0_00"))
            rom.write_byte(0xC, 0x812F, value)

        # Show party sprite 1-4
        address = [0x828D, 0x829C, 0x82AB, 0x82BA]
        for param in range(4):
            widget = f"CE_Param_0_0{param + 1}"
            if app.getCheckBoxWidget(widget).cget("state") != "disabled":
                if app.getCheckBox(widget) is True:
                    rom.write_bytes(0xC, address[param], bytes([0x20, 0xBE, 0x82]))  # JSR $82BE
                else:
                    rom.write_bytes(0xC, address[param], bytes([0xEA, 0xEA, 0xEA]))  # 3x NOP

        # Sprite 1-4 Movement Offset X
        address = [0x8282, 0x8291, 0x82A0, 0x82AF]
        for param in range(4):
            widget = f"CE_Param_0_0{param + 5}"
            if app.getEntryWidget(widget).cget("state") != "disabled":
                try:
                    signed_value = int(app.getEntry(widget), 10)
                    byte_value = signed_value.to_bytes(1, "little", signed=True)
                    rom.write_byte(0xC, address[param], byte_value[0])
                except ValueError:
                    app.warningBox("Save Cutscene Data",
                                   f"WARNING: Invalid entry for Sprite {param + 1} Movement Offset X.")

        # Horizontal movement delay 1-4
        address = [0x8288, 0x8297, 0x82A6, 0x82B5]
        for param in range(4):
            widget = f"CE_Param_0_{(param + 9):02d}"
            if app.getEntryWidget(widget).cget("state") != "disabled":
                try:
                    value = int(app.getEntry(widget), 10)
                    rom.write_byte(0xC, address[param], value)
                except ValueError:
                    app.warningBox("Save Cutscene Data",
                                   f"WARNING: Invalid entry for Sprite {param + 1} Horizontal Movement Delay.")

        # Global movement
        # Options: None, Up, Down, Left, Right
        if app.getOptionBoxWidget("CE_Param_0_13").cget("state") != "disabled":
            option = get_option_index("CE_Param_0_13", app.getOptionBox("CE_Param_0_13"))
            data = bytearray()
            if option == 0:  # No movement:
                data = [0xEA, 0xEA]  # NOP, NOP
            elif option == 1:  # Up:
                data = [0xCE, 0x18]  # DEC $18
            elif option == 2:  # Down:
                data = [0xE6, 0x18]  # INC $18
            elif option == 3:  # Left
                data = [0xCE, 0x19]  # DEC $19
            elif option == 4:  # Right
                data = [0xE6, 0x19]  # INC $19

            if len(data) > 0:
                rom.write_bytes(0xC, 0x82CE, data)

        # Starting X, Y
        address = [0x82BF, 0x82C3]
        for param in range(2):
            widget = f"CE_Param_0_{param + 14}"
            if app.getEntryWidget(widget).cget("state") != "disabled":
                try:
                    value = int(app.getEntry(widget), 10)
                    rom.write_byte(0xC, address[param], value)
                except ValueError:
                    app.warningBox("Save Cutscene Data", "WARNING: Invalid entry for Starting X/Y.\n" +
                                   "Please enter a decimal value between 0 and 255.")

        # Target position check and value
        if app.getOptionBoxWidget("CE_Param_0_16").cget("state") != "disabled":
            option = get_option_index("CE_Param_0_16", app.getOptionBox("CE_Param_0_16"))
            # Options: "X =", "Y =", "X >=", "Y >=", "X <", "Y <"
            data = [[0x19, 0xC9, 0x50, 0xD0],  # BNE
                    [0x18, 0xC9, 0x50, 0xD0],
                    [0x19, 0xC9, 0x50, 0xB0],  # BCS
                    [0x18, 0xC9, 0x50, 0xB0],
                    [0x19, 0xC9, 0x50, 0x90],  # BCC
                    [0x18, 0xC9, 0x50, 0x90]]
            code = bytearray(data[option])
            try:
                value = int(app.getEntry("CE_Param_0_17"), 10)
                code[2] = value
                rom.write_bytes(0xC, 0x82E0, code)
            except ValueError:
                app.warningBox("Save Cutscene Data", "WARNING: Invalid entry for Target Position.\n" +
                               "Please enter a decimal value between 0 and 255.")

        # Dialogue IDs
        address = [0x8242, 0x826A]
        for param in range(2):
            widget = f"CE_Param_0_{param + 18}"
            if app.getEntryWidget(widget).cget("state") != "disabled":
                try:
                    value = int(app.getEntry(widget), 16)
                    rom.write_byte(0xC, address[param], value)
                except ValueError:
                    app.warningBox("Save Cutscene Data", "WARNING: Invalid Dialogue ID entry.\n" +
                                   "Please enter a hexadecimal value between 0x00 and 0xFF")

        # Dialogue position and size
        if app.getEntryWidget("CE_Param_0_20").cget("state") != "disabled":
            try:
                x = int(app.getEntry("CE_Param_0_20"), 10)
                y = int(app.getEntry("CE_Param_0_21"), 10)
                w = int(app.getEntry("CE_Param_0_22"), 10)
                h = int(app.getEntry("CE_Param_0_23"), 10)
                rom.write_byte(0xC, 0x8249, x)
                rom.write_byte(0xC, 0x822F, x - 2)
                rom.write_byte(0xC, 0x824D, y)
                rom.write_byte(0xC, 0x8233, y - 2)
                rom.write_byte(0xC, 0x8251, w)
                rom.write_byte(0xC, 0x8237, w + 4)
                rom.write_byte(0xC, 0x8255, h)
                rom.write_byte(0xC, 0x823B, h + 4)
            except ValueError:
                app.warningBox("Save Cutscene Data", "WARNING: Invalid entry for Dialogue Size/Position.\n",
                               "Please enter decimal values between 2 and 251.")

    # Title Screen
    elif scene == 2:
        # Music ID
        if app.getOptionBoxWidget("CE_Param_2_00").cget("state") != "disabled":
            data = get_option_index("CE_Param_2_00", app.getOptionBox("CE_Param_2_00"))
            rom.write_byte(0xE, 0xB8F7, data | 0x80)

        # Text position and size
        addresses = [0xB908, 0xB90C, 0xB910, 0xB914]
        for param in range(4):
            widget = f"CE_Param_2_0{param + 1}"

            if app.getEntryWidget(widget).cget("state") != "disabled":
                try:
                    data = int(app.getEntry(widget), 10)
                    rom.write_byte(0xE, addresses[param], data)
                except ValueError:
                    app.errorBox("Screen Editor", f"Invalid entry for text size/position: '{app.getEntry(widget)}'.\n" +
                                 "Please enter a value between 0 and 255.")

    # Marks / Fountain
    elif 3 <= scene <= 7:
        addresses = [0xAD4E, 0xAD4F, 0xAD50, 0xAD51, 0xAC3E]

        widget = f"CE_Param_{scene}_00"
        if app.getEntryWidget(widget).cget("state") != "disabled":
            try:
                data = int(app.getEntry(widget), 10)
                rom.write_byte(0xD, addresses[scene - 3], data)
            except ValueError:
                app.errorBox("Screen Editor", f"Invalid entry for text ID: '{app.getEntry(widget)}'.\n" +
                             "Please enter a value between 0 and 255.")

    app.setStatusbar("Data saved successfully.")


# ----------------------------------------------------------------------------------------------------------------------

def read_cutscene_data(scene: int) -> None:
    if scene == 0:  # Lord British game start

        # Party facing direction
        data = rom.read_bytes(0xC, 0x812E, 2)
        # Check for custom code
        if data[0] != 0xA9 or data[1] > 4:
            app.disableOptionBox("CE_Param_0_00")
        else:
            app.enableOptionBox("CE_Param_0_00")
            app.setOptionBox("CE_Param_0_00", data[1], callFunction=False)

        # Show party sprites
        addresses = [0x828D, 0x829C, 0x82AB, 0x82BA]
        for param in range(4):
            widget = f"CE_Param_0_0{param + 1}"
            data = rom.read_bytes(0xC, addresses[param], 3)
            if data == b'\x20\xBE\x82':
                app.enableCheckBox(widget)
                app.setCheckBox(widget, True, callFunction=False)
            elif data[0] == 0xEA:
                app.enableCheckBox(widget)
                app.setCheckBox(widget, False, callFunction=False)

        # Sprite movement offset X
        addresses = [0x8281, 0x8290, 0x829F, 0x82AE]
        for param in range(4):
            widget = f"CE_Param_0_{(param + 5):02}"
            data = rom.read_bytes(0xC, addresses[param], 2)
            if data[0] != 0xA9:
                app.disableEntry(widget)
            else:
                app.enableEntry(widget)
                app.clearEntry(widget, callFunction=False, setFocus=False)
                value = int.from_bytes([data[1]], "little", signed=True)
                app.setEntry(widget, f"{value}", callFunction=False)

        # Sprite movement delay
        addresses = [0x8287, 0x8296, 0x82A5, 0x82B4]
        for param in range(4):
            widget = f"CE_Param_0_{(param + 9):02}"
            data = rom.read_bytes(0xC, addresses[param], 2)
            if data[0] != 0xA9:
                app.disableEntry(widget)
            else:
                app.enableEntry(widget)
                app.clearEntry(widget, callFunction=False, setFocus=False)
                app.setEntry(widget, f"{data[1]}", callFunction=False)

        # Global movement
        data = rom.read_bytes(0xC, 0x82CE, 2)
        option = -1
        if data[0] == 0xE6:  # INC
            if data[1] == 0x18:
                option = 2  # Down
            elif data[1] == 0x19:
                option = 4  # Right
            else:
                option = 0  # None
        elif data[0] == 0xC6:  # DEC
            if data[1] == 0x18:
                option = 1  # Up
            elif data[1] == 0x19:
                option = 3  # Left
            else:
                option = 0  # None
        if option == -1:
            app.disableOptionBox("CE_Param_0_13")
        else:
            app.enableOptionBox("CE_Param_0_13")
            app.setOptionBox("CE_Param_0_13", option, callFunction=False)

        # Starting X
        data = rom.read_bytes(0xC, 0x82BE, 2)
        if data[0] != 0xA9:
            app.disableEntry("CE_Param_0_14")
        else:
            app.enableEntry("CE_Param_0_14")
            app.clearEntry("CE_Param_0_14", callFunction=False, setFocus=False)
            app.setEntry("CE_Param_0_14", f"{data[1]}", callFunction=False)

        # Starting Y
        data = rom.read_bytes(0xC, 0x82C2, 2)
        if data[0] != 0xA9:
            app.disableEntry("CE_Param_0_15")
        else:
            app.enableEntry("CE_Param_0_15")
            app.clearEntry("CE_Param_0_15", callFunction=False, setFocus=False)
            app.setEntry("CE_Param_0_15", f"{data[1]}", callFunction=False)

        # Target position
        data = rom.read_bytes(0xC, 0x82E0, 4)
        option = -1  # Options: "X =", "Y =", "X >=", "Y >=", "X <", "Y <"
        if data[3] == 0xD0:  # BNE
            if data[0] == 0x19:
                option = 0
            elif data[0] == 0x18:
                option = 1
        elif data[3] == 0xB0:  # BCS
            if data[0] == 0x19:
                option = 2
            elif data[0] == 0x18:
                option = 3
        elif data[3] == 0x90:  # BCC
            if data[0] == 0x19:
                option = 4
            elif data[0] == 0x18:
                option = 5

        if option == -1:
            app.disableOptionBox("CE_Param_0_16")
            app.disableEntry("CE_Param_0_17")
        else:
            app.enableOptionBox("CE_Param_0_16")
            app.enableEntry("CE_Param_0_17")
            app.setOptionBox("CE_Param_0_16", option, callFunction=False)
            app.clearEntry("CE_Param_0_17", callFunction=False, setFocus=False)
            app.setEntry("CE_Param_0_17", f"{data[2]}", callFunction=False)

        # First Dialogue ID
        data = rom.read_bytes(0xC, 0x8241, 2)
        if data[0] != 0xA9:
            app.disableEntry("CE_Param_0_18")
        else:
            app.enableEntry("CE_Param_0_18")
            app.clearEntry("CE_Param_0_18", callFunction=False, setFocus=False)
            app.setEntry("CE_Param_0_18", f"0x{data[1]:02X}", callFunction=False)

        # Last Dialogue ID
        data = rom.read_bytes(0xC, 0x8269, 2)
        if data[0] != 0xC9:
            app.disableEntry("CE_Param_0_19")
        else:
            app.enableEntry("CE_Param_0_19")
            app.clearEntry("CE_Param_0_19", callFunction=False, setFocus=False)
            app.setEntry("CE_Param_0_19", f"0x{data[1]:02X}", callFunction=False)

        # Dialogue position and size
        addresses = [0x8248, 0x824C, 0x8250, 0x8254]
        for param in range(4):
            widget = f"CE_Param_0_{(param + 20):02}"
            data = rom.read_bytes(0xC, addresses[param], 2)
            if data[0] != 0xA9:
                app.disableEntry(widget)
            else:
                app.enableEntry(widget)
                app.clearEntry(widget, callFunction=False, setFocus=False)
                app.setEntry(widget, f"{data[1]}", callFunction=False)

    elif scene == 1:  # Time Lord

        # Dialogue ID
        data = rom.read_bytes(0xD, 0xACDA, 2)
        if data[0] != 0xA9:
            app.disableEntry("CE_Param_1_00")
        else:
            app.enableEntry("CE_Param_1_00")
            app.clearEntry("CE_Param_1_00", callFunction=False, setFocus=False)
            app.setEntry("CE_Param_1_00", f"0x{data[1]:02X}", callFunction=False)

    elif scene == 2:  # Title Screen

        # Music ID
        data = rom.read_bytes(0xE, 0xB8F6, 2)
        if data[0] != 0xA9:
            app.disableOptionBox("CE_Param_2_00")
        else:
            app.enableOptionBox("CE_Param_2_00")
            app.changeOptionBox("CE_Param_2_00", music_editor.track_titles[0] + music_editor.track_titles[1],
                                callFunction=False)
            app.setOptionBox("CE_Param_2_00", data[1] & 0x7F, callFunction=False)

        addresses = [0xB907, 0xB90B, 0xB90F, 0xB913]
        for param in range(4):
            widget = f"CE_Param_2_0{param + 1}"
            data = rom.read_bytes(0xE, addresses[param], 2)
            if data[0] != 0xA9:
                app.disableEntry(widget)
            else:
                app.enableEntry(widget)
                app.clearEntry(widget, callFunction=False, setFocus=False)
                app.setEntry(widget, f"{data[1]}", callFunction=False)

    elif 3 <= scene <= 6:  # Marks
        address = 0xAD4E
        for param in range(4):
            widget = f"CE_Param_{param + 3}_00"
            value = rom.read_byte(0xD, address + param)
            app.clearEntry(widget, callFunction=False, setFocus=False)
            app.setEntry(widget, f"0x{value:02X}", callFunction=False)

    elif scene == 7:  # Fountain
        data = rom.read_bytes(0xD, 0xAC3D, 2)

        if data[0] != 0xA9:
            app.disableEntry("CE_Param_7_00")
        else:
            app.enableEntry("CE_Param_7_00")
            app.clearEntry("CE_Param_7_00", callFunction=False, setFocus=False)
            app.setEntry("CE_Param_7_00", f"0x{data[1]:02X}", callFunction=False)

    else:
        log(2, "EDITOR", f"Invalid cutscene index: {scene}.")


# ----------------------------------------------------------------------------------------------------------------------

def select_map(sel: str) -> None:
    """
    An item has been selected from the Option Box in the Map Editor Tab

    Parameters
    ----------
    sel: str
        Name of the Option Box widget
    """
    global selected_map
    global map_compression

    selected_map = get_option_index(sel, app.getOptionBox(sel))  # int(app.getOptionBox(sel)[:4], 16)
    # log(4, "EDITOR", f"Selected map# {selected_map}")

    map_data = map_editor.map_table[selected_map]

    # Display data for the selected map
    map_editor.update_map_table(map_data)

    # Choose a default compression based on bank number
    if map_data.bank <= 0xF:
        map_compression = map_editor.bank_compression[map_data.bank]
    else:
        map_compression = "none"

    if map_compression == "LZSS":
        app.setOptionBox("Map_Compression", 1)
    elif map_compression == "RLE":
        app.setOptionBox("Map_Compression", 2)
    else:
        app.setOptionBox("Map_Compression", 0)


# ----------------------------------------------------------------------------------------------------------------------

def select_compression(sel: str) -> None:
    """
    An item has been selected from the compression method Option Box in the Map Editor Tab

    Parameters
    ----------
    sel: str
        Name of the Option Box widget
    """
    global map_compression
    map_compression = app.getOptionBox(sel)
    # print("Selected compression: {0}".format(map_compression))


# ----------------------------------------------------------------------------------------------------------------------

def text_editor_stop() -> bool:
    """
    Callback: request to close the Text Editor sub-window

    Returns
    -------
    bool
        True if the window has been closed, False if the action has been cancelled
    """
    if text_editor.close_advanced_window() is False:
        # Re-focus Text Editor sub-window
        app.showSubWindow("Text_Editor")
        return False

    # Reload currently selected string if the text tab is active
    if app.getTabbedFrameSelectedTab("TabbedFrame") == "Text":
        app.selectListItemAtPos("Text_Id", text_editor.index, callFunction=True)

    return True


# ----------------------------------------------------------------------------------------------------------------------

def text_editor_input(widget: str) -> None:
    """
    Button main_input callback for the Text Editor sub-window

    Parameters
    ----------
    widget: str
        Name of the Button widget being pressed
    """
    if widget == "Text_Apply":  # --------------------------------------------------------------------------------------
        # Used to re-select the active text
        selected_index = text_editor.index

        # Get the currently selected text type
        if text_editor.type == "Dialogue" or text_editor.type == "Special":
            # Rebuild pointer tables
            text_editor.rebuild_pointers()

            # Reload strings
            text_editor.uncompress_all_string()

        elif text_editor.type == "NPC Names":
            text_editor.modify_text(app.getTextArea("Text_Preview"), 0)
            text_editor.save_npc_names()

        elif text_editor.type == "Enemy Names":
            text_editor.modify_text(app.getTextArea("Text_Preview"), 0)
            text_editor.save_enemy_names()
            enemy_editor.update_names(text_editor)

        elif text_editor.type == "Menus / Intro":
            text_editor.modify_text(app.getTextArea("Text_Preview"), 0)

            # Rebuild pointers
            text_editor.save_menu_text()

            # Reload strings
            text_editor.read_menu_text()

        elif text_editor.type == "":
            # Nothing selected
            pass

        else:
            log(3, "TEXT EDITOR", f"Invalid text type: {text_editor.type}")

        # Reload currently selected string
        select_text_type("Text_Type")
        if selected_index >= 0:
            app.selectListItemAtPos("Text_Id", selected_index, callFunction=True)

    elif widget == "TE_Button_Close":   # ------------------------------------------------------------------------------
        text_editor.close_advanced_window(False)

        # Reload currently selected string if the text tab is active
        if app.getTabbedFrameSelectedTab("TabbedFrame") == "Text":
            app.selectListItemAtPos("Text_Id", text_editor.index, callFunction=True)

    elif widget == "TE_Button_Customise":   # --------------------------------------------------------------------------
        text_editor.show_customise_window()
        app.getTextAreaWidget("TE_Text").focus_set()
        text_editor.draw_text_preview(True)

    elif widget == "TE_Button_Reload_Text":     # ----------------------------------------------------------------------
        # Get address from input widget
        address_string = ""
        try:
            address_string = app.getEntry("TE_Entry_Address")
            new_address = int(address_string, 16)

            if text_editor.type == "Dialogue" or text_editor.type == "Special":
                # Try to unpack the string at the new address
                new_string = text_editor.unpack_text(rom, new_address)

            else:
                new_string = ""

            # Update the output widget with the new text
            app.clearTextArea("TE_Text")
            app.setTextArea("TE_Text", new_string)
            TextEditor.highlight_keywords(app.getTextAreaWidget("TE_Text"))
            text_editor.draw_text_preview(False)

            # Set the new text and address variables in the Text Editor
            text_editor.text = new_string
            text_editor.address = new_address
            text_editor.changed = True
        except ValueError:
            app.errorBox("ERROR", f"Invalid address '{address_string}'.\n"
                                  "Please only enter numbers, in hexadecimal format.",
                         "Text_Editor")

    elif widget == "TE_Button_Accept":  # ------------------------------------------------------------------------------
        text_id = text_editor.index

        # Get new text and address
        new_text: str = app.getTextArea("TE_Text")
        if text_editor.type == "Dialogue" or text_editor.type == "Special":
            try:
                new_name: int = ast.literal_eval(app.getOptionBox("TE_Option_Name")[:6])
            except SyntaxError:
                value = app.getOptionBox("TE_Option_Name")[:6]
                log(3, "TEXT EDITOR", f"Could not convert value from '{value}'.")
                new_name = -1

            value = app.getOptionBox("TE_Option_Portrait")
            try:
                if value[:2] != "No":
                    new_portrait = int(value[:2], 10)
                else:
                    new_portrait = -1
            except ValueError:
                log(3, "TEXT EDITOR", f"Could not convert value from '{value}'.")
                new_portrait = -1

        else:
            new_portrait = -1
            new_name = -1
        try:
            new_address = int(app.getEntry("TE_Entry_Address"), 16)
        except ValueError:
            value = app.getEntry("TE_Entry_Address")
            app.errorBox("Invalid Value", f"The address specified ('{value}') is not valid.\n"
                                          "Please only use hexadecimal numbers in the format '0x1234'.", "Text_Editor")
            return

        text_editor.modify_text(new_text, new_address, new_portrait, new_name)
        # Update address in the items list
        app.setListItemAtPos("Text_Id", text_id, f"0x{text_id:02X} @0x{new_address:04X}")

        # Hide window
        app.hideSubWindow("Text_Editor", useStopFunction=False)

        # Save changes to ROM
        text_editor_input("Text_Apply")

    elif widget == "TE_Option_Name":    # ------------------------------------------------------------------------------
        text_editor.draw_text_preview(True)

    elif widget == "TE_Preview_Mode":   # ------------------------------------------------------------------------------
        text_editor.draw_text_preview(True)

    elif widget == "TE_Conversation_Advance":   # ----------------------------------------------------------------------
        text_editor.text_line += 5
        lines = app.getTextArea("TE_Text").splitlines()
        if len(lines) <= text_editor.text_line:
            text_editor.text_line = 0
        text_editor.draw_text_preview(False)

    else:   # ----------------------------------------------------------------------------------------------------------
        print(f"Unimplemented Text Editor button: {widget}")


# ----------------------------------------------------------------------------------------------------------------------

def select_text_type(sel: str) -> None:
    """
    Creates a preview of the selected text once an item has been
    chosen from the Text_Id listbox

    Parameters
    ----------
    sel: str
        Name of the Option Box widget
    """
    # Save changes to previously selected string, if any
    save_text(text_editor.index, app.getTextArea("Text_Preview"), text_editor.type)

    app.clearTextArea("Text_Preview")

    t = app.getOptionBox(sel)
    # print(f"Selected text type: {t}")
    if t == "Choose Type":
        text_editor.type = ""
        text_editor.index = -1
        return

    update_text_table(t)

    text_editor.type = t

    # Deselect previous string
    text_editor.index = -1


# ----------------------------------------------------------------------------------------------------------------------

def update_text_table(text_type: str) -> None:
    """
    Fills the Text_Id listbox with items for the specified text type

    Parameters
    ----------
    text_type: str
        "Dialogue" / "Special" / "NPC Names" / "Enemy Names"
    """
    strings_list: List[str] = []

    if text_type == "Dialogue":
        index = 0
        for entry in text_editor.dialogue_text_pointers:
            strings_list.append(f"0x{index:02X} @0x{entry:04X}")
            index = index + 1

    elif text_type == "Special":
        index = 0
        for entry in text_editor.special_text_pointers:
            strings_list.append(f"0x{index:02X} @0x{entry:04X}")
            index = index + 1

    elif text_type == "NPC Names":
        for entry in text_editor.npc_names:
            strings_list.append(entry)

    elif text_type == "Enemy Names":
        for entry in text_editor.enemy_names:
            strings_list.append(entry)

    elif text_type == "Menus / Intro":
        index = 0
        for entry in text_editor.menu_text_pointers:
            strings_list.append(f"0x{index:02X} @0x{entry:04X}")
            index = index + 1

    else:
        pass

    app.clearListBox("Text_Id")
    app.updateListBox("Text_Id", strings_list)


# ----------------------------------------------------------------------------------------------------------------------

def save_text(text_id: int, text_string: str, text_type: str) -> None:
    """
    Saves the previously selected text

    Parameters
    ----------
    text_id: int
        Index of the text in the pointers table
    text_string: str
        A string containing the text to be saved
    text_type: str
        The type of text: Special, Dialogue, NPC Names, Enemy Names
    """
    if text_id < 0:
        # No selection
        return

    if text_type == "":
        text_type = app.getOptionBox("Text_Type")

    if text_type == "Special":
        text_editor.special_text[text_id] = text_string

    elif text_type == "Dialogue":
        text_editor.dialogue_text[text_id] = text_string

    elif text_type == "NPC Names":
        text_editor.npc_names[text_id] = text_string

    elif text_type == "Enemy Names":
        text_editor.enemy_names[text_id] = text_string

    elif text_type == "Menus / Intro":
        text_editor.menu_text[text_id] = text_string

    elif text_type == "Choose Type":
        pass

    else:
        log(3, "EDITOR", f"Unexpected text type '{text_type}'.")
        return


# ----------------------------------------------------------------------------------------------------------------------

def select_text_id(sel: str) -> None:
    """
    An item has been selected from the Text ID Option Box in the Text Editor Tab

    Parameters
    ----------
    sel: str
        Name of the Option Box widget
    """
    # Get string type
    string_type = app.getOptionBox("Text_Type")

    # Retrieve selection value
    t = app.getListBox(sel)
    if len(t) == 0:
        return

    # Save previous text changes if any
    save_text(text_editor.index, app.getTextArea("Text_Preview").upper(), string_type)

    # If valid selection, get the index
    index = app.getListBoxPos(sel)

    text_editor.index = index[0]

    # Show text preview
    if string_type == "Dialogue":
        string = text_editor.dialogue_text[index[0]]

    elif string_type == "Special":
        string = text_editor.special_text[index[0]]

    elif string_type == "NPC Names":
        string = text_editor.npc_names[index[0]]

    elif string_type == "Enemy Names":
        string = text_editor.enemy_names[index[0]]

    elif string_type == "Menus / Intro":
        string = text_editor.menu_text[index[0]]

    else:
        return

    # Use the cached unpacked strings from the global variable instead of unpacking the string now
    app.clearTextArea("Text_Preview")
    app.setTextArea("Text_Preview", string)
    app.setLabel("TextEditor_Type", f"String #{index[0]}:")


# ----------------------------------------------------------------------------------------------------------------------

def select_portrait(sel: str) -> None:
    """
    An item has been selected from the Portrait ID Option Box in the Text Editor sub-window

    Parameters
    ----------
    sel: str
        Name of the Option Box widget
    """
    global rom
    portrait = app.getOptionBox(sel)
    if portrait == "No Portrait":
        index = 0xFF
    else:
        index = int(portrait[:2])
    text_editor.load_portrait(index)


# ----------------------------------------------------------------------------------------------------------------------

def cutscene_input(widget: str) -> None:
    global cutscene_editor

    if widget == "CE_Option_Cutscene":
        scene = get_option_index(widget, app.getOptionBox(widget))
        try:
            app.selectFrame("Screens", scene, callFunction=True)
        except IndexError:
            log(3, "SCREEN_EDITOR", f"Invalid screen selection: {scene}.")

    elif widget == "CE_Save_Parameters":
        scene_id = get_option_index("CE_Option_Cutscene", app.getOptionBox("CE_Option_Cutscene"))
        save_cutscene_data(scene_id)

    # TODO "CE_Reload_Parameters"

    elif widget == "CE_Cutscene_Save":
        if cutscene_editor.save_nametable() is True and cutscene_editor.save_attributes() is True:
            cutscene_editor.close_window()

    elif widget == "CE_Cutscene_Export":
        # Ask for a file name
        file_name = app.saveBox("Export Cutscene...", None, settings.get("last map export path"), ".bin",
                                [("Raw PPU Data", "*.bin"), ("All Files", "*.*")],
                                parent="Cutscene_Editor")
        if file_name != "":
            cutscene_editor.export_to_file(file_name)
            directory = os.path.dirname(file_name)
            settings.set("last map import path", directory)

    elif widget == "CE_Cutscene_Import":
        # Browse for a file to import
        file_name = app.openBox("Import Cutscene...", settings.get("last map import path"),
                                [("Raw PPU Data", "*.bin"), ("All Files", "*.*")],
                                asFile=False, parent="Cutscene_Editor", multiple=False)
        if file_name != "":
            cutscene_editor.import_from_file(file_name)
            directory = os.path.dirname(file_name)
            settings.set("last map import path", directory)

    elif widget == "CE_Cutscene_Close":
        cutscene_editor.close_window()

    elif widget == "CE_Cutscene_1x1":
        cutscene_editor.set_selection_size(0)

    elif widget == "CE_Cutscene_2x2":
        cutscene_editor.set_selection_size(1)

    elif widget == "CE_Edit_Graphics":
        scene_id = get_option_index("CE_Option_Cutscene", app.getOptionBox("CE_Option_Cutscene"))

        dungeon_attributes = bytearray([0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55,
                                        0x99, 0xAA, 0xAA, 0xAA, 0xAA, 0x55, 0x55, 0x55,
                                        0x99, 0xAA, 0xFA, 0xBA, 0xAA, 0x55, 0x55, 0x55,
                                        0x99, 0xAA, 0xFF, 0xBB, 0xAA, 0x55, 0x55, 0x55,
                                        0x99, 0xAA, 0xAA, 0xAA, 0xAA, 0x55, 0x55, 0x55,
                                        0x59, 0x5A, 0x5A, 0x5A, 0x5A, 0x55, 0x55, 0x55,
                                        0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55,
                                        0x05, 0x05, 0x05, 0x05, 0x05, 0x05, 0x05, 0x05])

        # Lord British
        if scene_id == 0:
            cutscene_editor.load_palette(38)
            cutscene_editor.load_patterns(0xA, 0x8000, 0xA4, 0x00)
            cutscene_editor.load_patterns(0x7, 0xA100, 20, 0x0A)
            cutscene_editor.load_patterns(0xC, 0xAF01, 84, 0xA4)
            cutscene_editor.load_patterns(0xA, 0x8F80, 8, 0xF8)
            cutscene_editor.show_window(0xC, 0x9B1B, 0x9EEB, 32, 30)

        # Time Lord
        elif scene_id == 1:
            cutscene_editor.load_palette(22)
            cutscene_editor.load_patterns(0xA, 0x8000, 0xA4, 0x00)
            cutscene_editor.load_patterns(0xA, 0x9B00, 58, 0xA4)
            cutscene_editor.load_patterns(0xA, 0x9FD0, 4, 0xF0)
            cutscene_editor.load_patterns(0xA, 0x9500, 12, 0xF4)
            cutscene_editor.show_window(0xD, 0xA500, -1, 16, 16, 3, 5, dungeon_attributes)

        # Title Screen
        elif scene_id == 2:
            cutscene_editor.load_palette(12)
            cutscene_editor.load_patterns(0xE, 0x8000, 128, 0x00)
            cutscene_editor.load_patterns(0xA, 0x8800, 128, 0x80)
            cutscene_editor.show_window(0xE, 0x8800, 0x8BC0, 32, 30)

        # Marks / Fountain
        elif 3 <= scene_id <= 7:
            addresses = [0xA200, 0xA300, 0xA100, 0xA000, 0xA400]
            cutscene_editor.load_palette(26 if scene_id == 7 else 14)
            cutscene_editor.load_patterns(0xA, 0x8000, 0xA4, 0x00)
            cutscene_editor.load_patterns(0xA, 0x9600, 58, 0xA4)
            cutscene_editor.load_patterns(0xA, 0x9FD0, 4, 0xF0)
            cutscene_editor.load_patterns(0xA, 0x9500, 12, 0xF4)
            cutscene_editor.show_window(0xD, addresses[scene_id - 3], -1, 16, 16, 3, 5, dungeon_attributes)

        else:
            log(3, "CUTSCENE_EDITOR", f"Unimplemented cutscene #{scene_id}")

    else:
        log(3, "CUTSCENE_EDITOR", f"Unimplemented input from widget '{widget}'.")


# ----------------------------------------------------------------------------------------------------------------------

def misc_editor_input(button: str) -> bool:
    if button == "PT_Button_Races":
        party_editor.show_window("Races")

    elif button == "PT_Button_Professions":
        party_editor.show_window("Professions")

    elif button == "PT_Button_Pre-Made":
        party_editor.show_window("Pre-Made")

    elif button == "PT_Button_Special":
        party_editor.show_window("Special Abilities")

    elif button == "PT_Button_Magic":
        party_editor.show_window("Magic")

    elif button == "PT_Button_Items":
        party_editor.show_window("Items")

    elif button == "PT_Button_Weapons":
        party_editor.show_window("Weapons")

    elif button == "PT_Button_Commands":
        party_editor.show_window("Commands")

    elif button == "PT_Button_Credits":
        end_game_editor.show_credits_window()

    elif button == "PT_Button_Ending":
        end_game_editor.show_end_game_window()

    else:
        log(3, "PARTY_EDITOR", f"Unimplemented button '{button}'.")

    return True


# ----------------------------------------------------------------------------------------------------------------------

def cutscene_editor_stop() -> bool:
    return cutscene_editor.close_window()


# ----------------------------------------------------------------------------------------------------------------------

def party_editor_stop() -> bool:
    return party_editor.close_window()


# ----------------------------------------------------------------------------------------------------------------------

def instrument_editor_stop() -> bool:
    return music_editor.close_instrument_editor()


# ----------------------------------------------------------------------------------------------------------------------

def track_editor_stop() -> bool:
    return music_editor.close_track_editor()


# ----------------------------------------------------------------------------------------------------------------------

def sound_tab_input(widget: str) -> None:
    if widget == "ST_Music_Bank":
        value = get_option_index(widget)
        if value == 0:  # Bank 8
            bank = 8

        else:  # Bank 9
            bank = 9

        app.setButton("ST_Import_Instruments", text=f"Import from bank {9 - value}")

        # Show how many tracks and instruments are in this bank
        if bank == 8:
            tracks_list = music_editor.track_titles[0]
            instruments = 50
            # TODO Read value from ROM or stored variable
            app.setSpinBox("ST_Tracks_Count", 10, callFunction=False)
            app.enableSpinBox("ST_Tracks_Count")
        else:
            tracks_list = music_editor.track_titles[1]
            instruments = 13
            app.setSpinBox("ST_Tracks_Count", 4, callFunction=False)
            app.disableSpinBox("ST_Tracks_Count")

        app.setLabel("ST_Label_Instruments", f"Instruments in this bank: {instruments}")
        app.changeOptionBox("ST_Option_Music", tracks_list, 0, callFunction=False)

    elif widget == "ST_Edit_Instruments":
        bank = 8 + get_option_index("ST_Music_Bank")
        music_editor.show_instrument_editor(bank)

    elif widget == "ST_Edit_Music":
        bank = 8 + get_option_index("ST_Music_Bank")
        track = get_option_index("ST_Option_Music")
        music_editor.show_track_editor(bank, track)

    elif widget == "ST_Edit_SFX":
        sfx_id = get_option_index("ST_Option_SFX", app.getOptionBox("ST_Option_SFX"))
        sfx_editor.show_window(sfx_id)

    elif widget == "ST_Option_SFX":
        sfx_id = get_option_index("ST_Option_SFX", app.getOptionBox("ST_Option_SFX"))
        channel, address, flag, size = sfx_editor.get_sfx_info(sfx_id)
        channel_names = ["Pulse 0", "Pulse 1", "Triangle", "Noise"]

        app.setLabel("ST_Label_Info", f"Channel: {channel_names[channel]}, Volume Only: {'Yes' if flag else 'No'}, " +
                     f"Size: {size} [Address: $09:{address:04X}]")

    else:
        log(3, "MUSIC EDITOR", f"Unimplemented callback for widget '{widget}'.")


# ----------------------------------------------------------------------------------------------------------------------

# noinspection PyArgumentList
def main_input(widget: str) -> bool:
    """
    Generic button main_input callback for the main window

    Parameters
    ----------
    widget: str
        Name of the Button widget
    """
    global emulator_pid

    if widget == "Open ROM":    # --------------------------------------------------------------------------------------
        # If a ROM is already open, close it first
        # TODO Ask to save changes if any
        if rom.path is None or len(rom.path) < 1:
            close_rom()

        # Browse for a ROM file
        file_name = app.openBox("Open ROM file...", settings.get("last rom path"),
                                [("NES ROM files", "*.nes"), ("Binary data", "*.bin"), ("All files", "*.*")],
                                asFile=False)
        if file_name != '':
            open_rom(file_name)
            directory = os.path.dirname(file_name)
            settings.set("last rom path", directory)

    elif widget == "Save ROM":      # ----------------------------------------------------------------------------------
        # Check if a file is currently open
        if rom.path is None or len(rom.path) < 1:
            app.warningBox("Save ROM", "You need to open a ROM file first.")
            return True

        save_rom(rom.path)

    elif widget == "Save ROM As...":    # ------------------------------------------------------------------------------
        # Check if a file is currently open
        if rom.path is None or len(rom.path) < 1:
            app.warningBox("Save ROM As...", "You need to open a ROM file first.")
            return True

        file_name = app.saveBox("Save ROM file as...", None, settings.get("last rom path"), ".nes",
                                [("NES ROM files", "*.nes"), ("Binary data", "*.bin"), ("All files", "*.*")],
                                asFile=False)
        if file_name != '':
            save_rom(file_name)
            directory = os.path.dirname(file_name)
            settings.set("last rom path", directory)

            # Update ROM path
            rom.path = file_name

            # Add file name to the window's title
            app.setTitle(f"UE Editor - {os.path.basename(file_name)}")

    elif widget == "Close ROM":     # ----------------------------------------------------------------------------------
        close_rom()

    elif widget == "Settings":  # --------------------------------------------------------------------------------------
        settings.show_settings_window(app)

    elif widget == "About":     # --------------------------------------------------------------------------------------
        app.infoBox("About", f"Ultima: Exodus Editor\nVersion {__version__}.")

    elif widget == "Exit":      # --------------------------------------------------------------------------------------
        # TODO Ask to save changes if any
        close_rom()
        app.stop()

    elif widget == "Start Emulator":    # ------------------------------------------------------------------------------
        # Check if we have a ROM file open
        if rom.path is None or len(rom.path) < 1:
            app.errorBox("Launch Emulator", "You need to open a ROM file first!")
            return True

        # Get the emulator's path from settings
        path = str(settings.get("emulator"))
        if path == "":
            app.warningBox("Launch Emulator", f"Emulator path not set.\n"
                                              "Please go to Settings and choose an emulator executable.")
        elif os.path.exists(path):
            # Check if emulator already running
            try:
                if emulator_pid.poll() is None:
                    app.warningBox("Launch Emulator", "The Emulator process is already running.\n"
                                                      "Please close the previous instance before opening a new one.")
                    return True
            except NameError:
                pass

            # TODO Ask to save changes if needed

            app.setStatusbar("Launching emulator...")

            # Get emulator's command line parameters
            params = str(settings.get("emulator parameters"))
            # Replace '%f' with the ROM file name
            params = params.replace('%f', f'"{rom.path}"')
            # Try to launch the application
            command = shlex.split(path + " " + params)
            emulator_pid = subprocess.Popen(command)

            # Check if the emulator actually started
            if emulator_pid.poll() is not None:
                app.setStatusbar("Emulator launch failed!")
                app.errorBox("Launch Emulator", f"Could not start Emulator process.\nCommand line: '{path} {params}'")
            else:
                app.setStatusbar("Emulator process started.")

        else:
            app.setStatusbar("Emulator launch failed!")
            app.warningBox("Launch Emulator", f"Invalid emulator path '{path}'.\n"
                                              "Please go to Settings and choose the correct path.")

    elif widget == "ME_Option_Map_Type":    # --------------------------------------------------------------------------
        map_type = get_option_index(widget, app.getOptionBox(widget))
        app.selectFrame("Map_Types", map_type, callFunction=True)

    elif widget == "Map_Apply":     # ----------------------------------------------------------------------------------
        map_editor.save_map_tables()
        app.soundWarning()
        app.setStatusbar("Map tables saved.")

    elif widget == "Map_Edit":  # --------------------------------------------------------------------------------------
        edit_map()

    elif widget == "MapInfo_Advanced_Option":   # ----------------------------------------------------------------------
        value = app.getRadioButton(widget)
        if value == "Basic":
            app.showFrame("MapInfo_Frame_Basic")
            app.hideFrame("MapInfo_Frame_Advanced")
        else:
            app.hideFrame("MapInfo_Frame_Basic")
            app.showFrame("MapInfo_Frame_Advanced")

    elif widget == "MapInfo_Basic_Bank":    # --------------------------------------------------------------------------
        # Update bank number in Advanced view
        value = int(app.getOptionBox(widget))
        app.setEntry("MapInfo_Bank", f"0x{value:02X}")

    elif widget == "MapInfo_Basic_Type" or widget == "MapInfo_Basic_ID":    # ------------------------------------------
        # Update flags/ID in Advanced view
        try:
            flags = int(app.getOptionBox("MapInfo_Basic_Type")[0])
            id_value = int(app.getSpinBox("MapInfo_Basic_ID"))
            value = flags << 4 | id_value
            app.setEntry("MapInfo_Flags", f"0x{value:02X}")
        except ValueError:
            pass

    elif widget == "MapInfo_Tileset":   # ------------------------------------------------------------------------------
        set_index = get_option_index(widget, app.getOptionBox(widget))
        map_index = get_option_index("MapInfo_Select", app.getOptionBox("MapInfo_Select"))
        map_editor.tileset_table[map_index] = set_index

    elif widget == "Battlefield_Apply":     # --------------------------------------------------------------------------
        battlefield_editor.save_tab_data()
        app.soundWarning()
        app.setStatusbar("Battlefield data saved.")

    elif widget == "Battlefield_Option_Map":    # ----------------------------------------------------------------------
        # Show the address of the selected map
        map_index = get_option_index(widget, app.getOptionBox(widget))
        address = battlefield_editor.get_map_address(map_index)
        app.clearEntry("Battlefield_Map_Address", callFunction=False, setFocus=False)
        app.setEntry("Battlefield_Map_Address", f"0x{address:04X}", callFunction=False)

    elif widget == "Battlefield_Edit":      # --------------------------------------------------------------------------
        # TODO Ask to save changes first? If cancelled, re-read selected map address
        map_index = get_option_index("Battlefield_Option_Map", app.getOptionBox("Battlefield_Option_Map"))
        battlefield_editor.show_window(map_index)

    elif widget == "Battlefield_Map_Address":   # ----------------------------------------------------------------------
        try:
            value = int(app.getEntry(widget), 16)
            if 0x8000 <= value <= 0xBFFF:
                map_index = get_option_index("Battlefield_Option_Map", app.getOptionBox("Battlefield_Option_Map"))
                app.entry(widget, fg=colour.BLACK)
                battlefield_editor.set_map_address(value, map_index)
            else:
                app.entry(widget, fg=colour.MEDIUM_RED)
        except ValueError:
            app.entry(widget, fg=colour.MEDIUM_RED)

    else:   # ----------------------------------------------------------------------------------------------------------
        log(3, "EDITOR", f"Unimplemented button: {widget}")
        return False

    return True


# ----------------------------------------------------------------------------------------------------------------------

def editor_stop() -> bool:
    # TODO Ask for confirmation if there are unsaved changes
    # Save settings
    settings.save()
    return True


# ----------------------------------------------------------------------------------------------------------------------

if __name__ == "__main__":

    # Try to load editor settings
    settings.load()

    # --- GUI Elements ---

    with gui("UE Editor", "492x344", bg=colour.WHITE, resizable=False) as app:
        print(app.SHOW_VERSION())
        # noinspection PyArgumentList
        app.setIcon(image="res/app-icon.ico")
        # noinspection PyArgumentList
        app.setStopFunction(editor_stop)
        f = settings.get("editor fonts")
        if f == "":
            f = "Consolas"
        app.setFont(family=f, underline=False, size=12)

        #       ##### Toolbar #####

        tools = ["Open ROM", "Close ROM", "Save ROM", "Save ROM As...", "Start Emulator", "Settings", "About", "Exit"]
        app.addToolbar(tools, main_input, True)
        app.setToolbarImage("Open ROM", "res/folder_open.gif")
        app.setToolbarImage("Close ROM", "res/cart_close.gif")
        app.setToolbarImage("Save ROM", "res/cart_save.gif")
        app.setToolbarImage("Save ROM As...", "res/cart_export.gif")
        app.setToolbarImage("Start Emulator", "res/controller.gif")
        app.setToolbarImage("Settings", "res/settings.gif")
        app.setToolbarImage("About", "res/info.gif")
        app.setToolbarImage("Exit", "res/exit.gif")
        app.setToolbarBg("#F0F0F0")

        #       ##### Tabs #####

        app.startTabbedFrame("TabbedFrame")

        # ROM Tab ------------------------------------------------------------------------------------------------------
        with app.tab("ROM"):
            with app.labelFrame("ROM Info", padding=[2, 0], row=0, column=0, stretch='BOTH', sticky='NEWS',
                                bg=colour.WHITE):
                app.label("RomInfo_0", value="Open a ROM file to begin...", row=0)
                app.label("RomInfo_1", value="", row=1, sticky='W')  # PRG ROM Size
                app.label("RomInfo_2", value="", row=2, sticky='W')  # CHR ROM Size
                app.label("RomInfo_3", value="", row=3, sticky='W')  # Mapper
                app.label("RomInfo_4", value="", row=4, sticky='W')  # Mirroring
                app.label("RomInfo_5", value="", row=5, sticky='W')  # Battery
                app.label("RomInfo_6", value="", row=6, sticky='W')  # Trainer
                app.label("RomInfo_7", value="", row=7, sticky='W')  # TV System
                app.label("RomInfo_8", value="", row=8, sticky='W')  # Extra Data

            with app.labelFrame("Features", row=0, column=1, stretch='BOTH', sticky='NEWS'):
                for f in range(11):
                    app.checkBox(f"Feature_{f}", name=feature_names[f], value=False, row=f, column=0, font=8,
                                 fg=colour.DARK_BLUE)
                    app.disableCheckBox(f"Feature_{f}")
                    app.hideCheckBox(f"Feature_{f}")

        # MAP Tab ------------------------------------------------------------------------------------------------------
        with app.tab("Map", padding=[4, 2]):

            app.optionBox("ME_Option_Map_Type", ["World and Dungeon Maps", "Battlefield Maps"], sticky="NEW",
                          tooltip="Select the type of map you want to edit", change=main_input,
                          stretch="COLUMN", row=0, column=0, font=11)

            with app.frameStack("Map_Types", inPadding=[4, 4], start=0, sticky="NEWS", stretch="BOTH", row=1, column=0):

                with app.frame("Map_Frame_0", padding=[4, 2], inPadding=[4, 4], sticky="NEWS", stretch="BOTH",
                               row=0, column=0):
                    maps_list = list()
                    for i in range(0, 0x1A):
                        maps_list.append(f"0x{i:02X}")

                    with app.frame("Map_TopFrame", row=0, column=0, sticky="NEW", stretch='BOTH', bg=colour.PALE_BROWN):
                        app.label("MapInfo_SelectLabel", value="Map:", row=0, column=0, sticky='E')
                        app.optionBox("MapInfo_Select", maps_list, change=select_map, sticky='WE', width=20,
                                      stretch="ROW", row=0, column=1, font=11)
                        app.radioButton("MapInfo_Advanced_Option", "Basic", change=main_input, sticky="E",
                                        row=0, column=2)
                        app.radioButton("MapInfo_Advanced_Option", "Advanced", change=main_input, sticky="W",
                                        row=0, column=3)

                    with app.frame("Map_MidFrame", row=1, column=0, sticky="NEW", stretch='BOTH', bg=colour.PALE_OLIVE):

                        # Basic info
                        with app.frame("MapInfo_Frame_Basic", row=0, column=0, padding=[8, 4], stretch='BOTH'):
                            app.label("MapInfo_Basic_h0", "Map type: ", sticky='E', row=0, column=0, colspan=2)
                            app.optionBox("MapInfo_Basic_Type", ["6: Continent (No Guards)", "2: Continent (w/Guards)",
                                                                 "4: Town / Castle (No Guards)",
                                                                 "0: Town / Castle (w/Guards)", "8: Dungeon"],
                                          width=26, sticky='W', row=0, column=2, colspan=2, change=main_input, font=11)

                            app.label("MapInfo_Basic_h1", "Bank: ", sticky='E', row=1, column=0)
                            banks_list = []
                            for i in range(0, 16):
                                banks_list.append(f"{i}")
                            app.optionBox("MapInfo_Basic_Bank", banks_list, sticky='W', row=1, column=1,
                                          change=main_input)
                            del banks_list

                            app.label("MapInfo_Basic_h2", "ID: ", sticky='E', row=1, column=2)
                            app.spinBox("MapInfo_Basic_ID", list(range(31, -1, -1)), change=main_input,
                                        width=4, sticky='W', row=1, column=3)

                        # Advanced info
                        with app.frame("MapInfo_Frame_Advanced", row=1, column=0, padding=[4, 1], stretch='BOTH'):
                            app.label("MapInfo_h0", "Bank Number", row=0, column=0, sticky="NEW", stretch="ROW")
                            app.label("MapInfo_h1", "Data Address", row=0, column=1, sticky="NEW", stretch="ROW")
                            app.label("MapInfo_h2", "NPC Table", row=0, column=2, sticky="NEW", stretch="ROW")

                            # Map bank number
                            app.entry("MapInfo_Bank", row=1, column=0, stretch="ROW", sticky="NEW", width=8)
                            # Map data address
                            app.entry("MapInfo_DataPtr", row=1, column=1, stretch="ROW", sticky="NEW", width=8)
                            # NPC table address / starting facing position in a dungeon (v1.09+)
                            app.entry("MapInfo_NPCPtr", row=1, column=2, stretch="ROW", sticky="NEW", width=8)
                            app.label("MapInfo_h3", "Party Entry X, Y", stretch="ROW", sticky="NEW",
                                      row=2, column=0, colspan=2)
                            app.label("MapInfo_h4", "Flags/ID", row=2, column=2, sticky="NEW", stretch="ROW")
                            app.label("MapInfo_h5", "Tile Set", row=2, column=3, sticky="NEW", stretch="COLUMN")
                            # Party entry coordinates
                            app.entry("MapInfo_EntryX", row=3, column=0, stretch="ROW", sticky="NEW", width=8)
                            app.entry("MapInfo_EntryY", row=3, column=1, stretch="ROW", sticky="NEW", width=8)
                            # Flags / ID
                            app.entry("MapInfo_Flags", row=3, column=2, stretch="ROW", sticky="NEW", width=8)
                            # Tileset
                            tilesets_list: List[str] = ["Continent 1", "Continent 2", "Castle 1", "Castle 2", "Town"]
                            app.optionBox("MapInfo_Tileset", tilesets_list, change=main_input,
                                          row=3, column=3, sticky="NEW", stretch="COLUMN", width=9, font=10)
                            del tilesets_list

                    # Show "Basic" info by default
                    app.setRadioButton("MapInfo_Advanced_Option", "Basic", callFunction=False)
                    app.hideFrame("MapInfo_Frame_Advanced")

                    with app.frame("Map_BtmFrame", row=4, column=0, sticky='NEWS', stretch='BOTH', padding=[4, 2],
                                   bg=colour.PALE_LIME):
                        app.button("Map_Apply", image="res/floppy.gif", value=main_input, width=32, height=32,
                                   tooltip="Save the changes to the values in this tab",
                                   bg=colour.PALE_TEAL, sticky="NEW", row=0, column=0)
                        app.button("Map_Edit", image="res/brush.gif", value=main_input, width=128, height=32,
                                   tooltip="Edit the selected map",
                                   bg=colour.PALE_TEAL, sticky="NEW", row=0, column=1)
                        app.label("MapInfo_SelectCompression", "Compression:", sticky="NEW", row=0, column=2)
                        app.optionBox("Map_Compression", ["none", "LZSS", "RLE"], change=select_compression,
                                      sticky="NEW", callFunction=True, row=0, column=3)

                with app.frame("Map_Frame_1", padding=[4, 2], inPadding=[4, 4], sticky="NEWS", stretch="BOTH",
                               row=0, column=0):
                    with app.frame("Battlefield_Top_Frame", inPadding=[4, 4], padding=[4, 0], bg=colour.PALE_BLUE,
                                   sticky="NEWS", stretch="BOTH", row=0, column=0):
                        battlefields = ["(Unused)", "Grass", "Brush", "Forest", "North: Water, South: Land",
                                        "North: Ship, South: Land", "Stone Floor 1", "City / Dungeon",
                                        "Ship in the Sea", "Naval Battle", "North: Land, South: Ship"]
                        app.label("Battlefield_Label_Map", "Map:", sticky="E", row=0, column=0, font=11)
                        app.optionBox("Battlefield_Option_Map", battlefields, change=main_input,
                                      sticky="W", row=0, column=1, font=10)

                    with app.frame("Battlefield_Middle_Frame", inPadding=[4, 4], padding=[4, 1], bg=colour.PALE_BLUE,
                                   sticky="NEWS", stretch="BOTH", row=1, column=0):
                        app.label("Battlefield_Label_Address", "Address: ", sticky="E", row=0, column=0, font=11)
                        app.entry("Battlefield_Map_Address", "", change=main_input, fg=colour.BLACK, sticky="W",
                                  width=8, row=0, column=1, font=10)

                    with app.frame("Battlefield_Bottom_Frame", inPadding=[4, 4], padding=[4, 2], bg=colour.PALE_BROWN,
                                   sticky="NEWS", stretch="BOTH", row=2, column=0):
                        app.label("Battlefield_Label_Music", "Battle Music (all maps):", sticky="E",
                                  row=0, column=0, font=11)
                        app.optionBox("Battlefield_Option_Music", ["- None -"], sticky="W", width=24,
                                      row=0, column=1, font=10)

                    with app.frame("Battlefield_Buttons_Frame", row=3, column=0, sticky="NWS",
                                   padding=[4, 4], bg=colour.PALE_LIME):
                        app.button("Battlefield_Apply", image="res/floppy.gif", value=main_input, width=32, height=32,
                                   tooltip="Save all changes to the values for this map",
                                   bg=colour.PALE_TEAL, sticky="E", row=0, column=0)
                        app.button("Battlefield_Reload", image="res/reload.gif", value=main_input, width=32, height=32,
                                   tooltip="Reload all values from ROM buffer",
                                   bg=colour.PALE_TEAL, sticky="W", row=0, column=1)
                        app.button("Battlefield_Edit", image="res/brush.gif", value=main_input, width=128, height=32,
                                   tooltip="Edit the selected map",
                                   bg=colour.PALE_TEAL, sticky="W", row=0, column=2)

        # MISC Tab ----------------------------------------------------------------------------------------------------
        with app.tab("Misc"):
            # Row 0
            app.button("PT_Button_Races", name="Races", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_BLUE, row=0, column=0, font=10)
            app.button("PT_Button_Professions", name="Professions", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_BROWN, row=0, column=1, font=10)
            # Row 1
            app.button("PT_Button_Pre-Made", name="Pre-Made Characters", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_OLIVE, row=1, column=0, font=9)
            app.button("PT_Button_Items", name="Items", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_TEAL, row=1, column=1, font=10)
            # Row 2
            app.button("PT_Button_Magic", name="Magic", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_ORANGE, row=2, column=0, font=10)
            app.button("PT_Button_Special", name="Special Abilities", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_VIOLET, row=2, column=1, font=10)
            # Row 3
            app.button("PT_Button_Weapons", name="Weapons/Armour", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_MAGENTA, row=3, column=0, font=10)
            app.button("PT_Button_Commands", name="Commands", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_LIME, row=3, column=1, font=10)
            # Row 4
            app.button("PT_Button_Credits", name="Game Credits Screen", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_NAVY, row=4, column=0, font=10)
            app.button("PT_Button_Ending", name="Game Ending", value=misc_editor_input, sticky='NEWS',
                       bg=colour.PALE_PINK, row=4, column=1, font=10)

        # ENEMIES Tab --------------------------------------------------------------------------------------------------
        with app.tab("Enemies", padding=[0, 0]):
            # Left
            with app.frame("ET_Frame_Left", bg=colour.PALE_RED, stretch='BOTH', sticky='NWS', row=0, column=0):
                app.optionBox("ET_Option_Enemies", ["- Select an Enemy -", "0x00"], row=0, column=0,
                              width=22, change=enemy_editor_input, stretch="ROW", sticky='EW')

                with app.frame("ET_Frame_Encounters", row=1, column=0):
                    app.label("ET_Label_h0", "Encounters:", row=0, column=0)
                    app.listBox("ET_List_Encounters", [""], row=1, column=0, height=7, change=enemy_editor_input,
                                stretch='COLUMN', sticky='NEWS')

                with app.frame("ET_Frame_Buttons", padding=[2, 2], row=2, column=0):
                    app.button("ET_Button_Apply", enemy_editor_input, name="Apply Changes", sticky='EW',
                               row=0, column=0)
                    app.button("ET_Button_Reload", enemy_editor_input, name="Cancel/Reload", sticky='EW',
                               row=0, column=1)

            # Right - Enemy
            with app.frame("ET_Frame_Enemy", bg=colour.PALE_TEAL, stretch='BOTH', sticky='NEWS', row=0, column=1):
                # Row 0
                app.label("ET_Label_h1", "Gfx Addr.:", sticky="NEW", row=0, column=0)
                app.checkBox("ET_Big_Sprite", name="4x4 Sprite", change=enemy_editor_input, row=0, column=1)
                # Row 1 - sprite
                app.entry("ET_Sprite_Address", value="0x0000", change=enemy_editor_input, width=5, fg=colour.DARK_OLIVE,
                          row=1, column=0)
                app.canvas("ET_Canvas_Sprite", map=None, width=32, height=32, sticky="NEW", bg=colour.MEDIUM_GREY,
                           row=1, column=1)
                # Row 2 - HP
                app.label("ET_Label_HP", "Base HP:", sticky="NEW", row=2, column=0)
                app.entry("ET_Base_HP", "0", change=enemy_editor_input, sticky="NEW", row=2, width=4, column=1)
                # Row 3 - XP
                app.label("ET_Label_XP", "Base XP:", sticky="NEW", row=3, column=0)
                app.entry("ET_Base_XP", "0", change=enemy_editor_input, sticky="NEW", width=4, row=3, column=1)
                # Rows 4, 5, 6 - colours
                # Colour selection, for vanilla game
                colours: List[str] = []
                for i in range(0x40):
                    colours.append(f"0x{i:02X}")
                app.label("ET_Label_Colour_1", "Colour 1", sticky="NEW", row=4, column=0)
                app.optionBox("ET_Colour_1", colours, change=enemy_editor_input, sticky="NEW", width=4,
                              row=4, column=1)
                app.label("ET_Label_Colour_2", "Colour 2", sticky="NEW", row=5, column=0)
                app.optionBox("ET_Colour_2", colours, change=enemy_editor_input, sticky="NEW", width=4,
                              row=5, column=1)
                app.label("ET_Label_Colour_3", "Colour 3", sticky="NEW", row=6, column=0)
                app.optionBox("ET_Colour_3", colours, change=enemy_editor_input, sticky="NEW", width=4,
                              row=6, column=1)
                # Palette selection, for hacked game
                app.optionBox("ET_Palette_1", ["00", "01", "02", "03"], change=enemy_editor_input,
                              sticky="NEW", width=4, row=4, column=1)
                app.optionBox("ET_Palette_2", ["00", "01", "02", "03"], change=enemy_editor_input,
                              sticky="NEW", width=4, row=5, column=1)
                # Row 7 - abilities
                app.label("ET_Label_Ability", "Ability:", sticky="NEW", row=7, column=0)
                app.optionBox("ET_Ability", ["None", "Steal", "Poison Atk", "Fireball", "Magic Poison"], width=5,
                              change=enemy_editor_input, row=7, column=1)
                del colours

                # Special "FLOOR" encounter
                with app.labelFrame("ET_Frame_Floor", name="Special Encounter", row=8, column=0, colspan=2):
                    app.label("ET_Label_Special_f0", "Map 0x14 coordinates:", row=0, column=0, colspan=4)
                    app.label("ET_Label_Special_f1", "X:", row=1, column=0)
                    app.entry("ET_Special_X", "0", change=enemy_editor_input, width=4, row=1, column=1)
                    app.label("ET_Label_Special_f2", "Y:", row=1, column=2)
                    app.entry("ET_Special_Y", "0", change=enemy_editor_input, width=4, row=1, column=2)

            # Right - Encounter
            with app.frame("ET_Frame_Encounter", bg=colour.PALE_TEAL, stretch='BOTH', sticky='NEWS', row=0, column=2):
                app.label("ET_Label_Level", "Level/Type", row=0, column=0)
                app.label("ET_Label_h3", "Encounters Table #0", row=1, column=0)
                with app.frame("ET_Frame_Encounters_List", sticky="NEW", padding=[4, 4], row=2, column=0):
                    app.entry("ET_Encounter_0", "0x00", change=encounter_input, width=4, row=0, column=1)
                    app.entry("ET_Encounter_1", "0x00", change=encounter_input, width=4, row=0, column=2)
                    app.entry("ET_Encounter_2", "0x00", change=encounter_input, width=4, row=0, column=3)
                    app.entry("ET_Encounter_3", "0x00", change=encounter_input, width=4, row=0, column=4)
                    app.entry("ET_Encounter_4", "0x00", change=encounter_input, width=4, row=1, column=1)
                    app.entry("ET_Encounter_5", "0x00", change=encounter_input, width=4, row=1, column=2)
                    app.entry("ET_Encounter_6", "0x00", change=encounter_input, width=4, row=1, column=3)
                    app.entry("ET_Encounter_7", "0x00", change=encounter_input, width=4, row=1, column=4)
                with app.labelFrame("ET_Frame_Special", name="Special", sticky="NEW", padding=[2, 2], row=3, column=0):
                    tiles_list: List[str] = []
                    for i in range(16):
                        tiles_list.append(f"0x{i:02X}")

                    app.label("ET_Special_l0", "Only on map:", row=0, column=0, colspan=2)
                    app.optionBox("ET_Special_Map", maps_list, width=18, change=encounter_input,
                                  row=1, column=0, colspan=2)
                    app.label("ET_Special_l1", "Tile:", row=2, column=0)
                    app.optionBox("ET_Special_Tile", tiles_list, change=encounter_input, row=2, column=1)

        # TEXT Tab -----------------------------------------------------------------------------------------------------
        with app.tab("Text", padding=[0, 0]):
            with app.frame("TextEditor_Left", row=0, column=0, padding=[4, 2], inPadding=[0, 0],
                           sticky='NW', bg=colour.PALE_OLIVE):
                app.label("TextEditor_Type", "Text Preview:", row=0, column=0, sticky="NW", stretch="NONE", font=10)
                app.textArea("Text_Preview", row=1, column=0, sticky="NEW", stretch="BOTH", scroll=True,
                             end=False, height=10, rowspan=2).setFont(family="Consolas", size=11)

                with app.frame("TextEditor_Buttons", padding=[4, 2], row=3, column=0):
                    app.button("Text_Apply", image="res/floppy.gif", value=text_editor_input, sticky="NEW", height=32,
                               row=0, column=0)
                    app.button("Text_More", image="res/edit-dlg.gif", value=edit_text, sticky="NEW", height=32,
                               row=0, column=1)

            with app.frame("TextEditor_Right", row=0, column=1, sticky="NEW", padding=[4, 2], bg=colour.PALE_BROWN):
                app.optionBox("Text_Type", ["- Choose Type -", "Dialogue", "Special", "NPC Names", "Enemy Names",
                                            "Menus / Intro"],
                              change=select_text_type, row=0, column=4, sticky="NEW", colspan=2, stretch="BOTH",
                              bg=colour.PALE_ORANGE)
                app.listBox("Text_Id", value=[], change=select_text_id, row=1, column=4, sticky="NEW",
                            group=True, multi=False, bg=colour.WHITE)

        # PALETTES Tab -------------------------------------------------------------------------------------------------
        with app.tab("Palettes", padding=[4, 2]):

            with app.frame("PE_Frame_List", row=0, column=0, padding=[2, 0], bg=colour.PALE_MAGENTA):
                app.label("PE_Label_Select", "Select a palette set:", row=0, column=0)
                app.optionBox("PE_List_Palettes", ["Start / Credits", "Title", "Status Screen", "Flashing",
                                                   "End Sequence", "Map Default", "Ambrosia", "Dungeon",
                                                   "Continent View", "Cutscene"],
                              change=select_palette, row=0, column=1)

            with app.frame("PE_Frame_Palettes", row=1, column=0, padding=[0, 2], stretch='BOTH', sticky='NEWS',
                           bg=colour.PALE_RED):
                app.button("PE_Palette_Prev", name=" << Prev ", row=0, column=0, stretch='NONE',
                           command=lambda: cycle_palette_sets(0))
                app.label("PE_Label_0", "Palette 0:", row=0, column=1, stretch='COLUMN')
                app.button("PE_Palette_Next", name=" Next >> ", row=0, column=2, stretch='NONE',
                           command=lambda: cycle_palette_sets(1))

            with app.frame("PE_Frame_Sub_Palette", row=2, column=0, padding=[8, 0], stretch='COLUMN', sticky='NEWS',
                           bg=colour.PALE_PINK):
                app.canvas("PE_Canvas_Palette_0", row=0, column=0, width=65, height=17, stretch='NONE', map=None,
                           bg=colour.BLACK).bind(
                    "<Button-1>", lambda event: edit_colour(event, 0), add="+")
                app.canvas("PE_Canvas_Palette_1", row=0, column=1, width=65, height=17, stretch='NONE', map=None,
                           bg=colour.BLACK).bind(
                    "<Button-1>", lambda event: edit_colour(event, 1), add="+")
                app.canvas("PE_Canvas_Palette_2", row=0, column=2, width=65, height=17, stretch='NONE', map=None,
                           bg=colour.BLACK).bind(
                    "<Button-1>", lambda event: edit_colour(event, 2), add="+")
                app.canvas("PE_Canvas_Palette_3", row=0, column=3, width=65, height=17, stretch='NONE', map=None,
                           bg=colour.BLACK).bind(
                    "<Button-1>", lambda event: edit_colour(event, 3), add="+")
                app.setCanvasCursor("PE_Canvas_Palette_0", "pencil")
                app.setCanvasCursor("PE_Canvas_Palette_1", "pencil")
                app.setCanvasCursor("PE_Canvas_Palette_2", "pencil")
                app.setCanvasCursor("PE_Canvas_Palette_3", "pencil")

            with app.frame("PE_Frame_Full", row=3, column=0, colspan=2, padding=[2, 0], stretch='BOTH',
                           bg=colour.PALE_ORANGE):
                # Full NES palette
                app.canvas("PE_Canvas_Full", row=0, column=0, width=257, height=65, stretch='NONE', map=None,
                           bg=colour.BLACK,
                           sticky='EW').bind("<Button-1>", pick_colour, add="+")
                app.setCanvasCursor("PE_Canvas_Full", "hand1")

        # SCREENS Tab ------------------------------------------------------------------------------------------------
        with app.tab("Screens", padding=[4, 2]):
            with app.frame("CE_Selection", row=0, column=0, sticky="NEW"):
                app.label("CE_Label_Selection", "Edit scene", sticky="NE", row=0, column=0, font=11)
                app.optionBox("CE_Option_Cutscene", ["Lord British", "Time Lord", "Title"], change=cutscene_input,
                              sticky="NW", row=0, column=1, font=10)

            with app.frameStack("Screens", start=0, sticky="NW", row=1, column=0, colspan=3):
                # Cutscene 0 parameters
                with app.frame("CE_Frame_Cutscene_0", bg=colour.PALE_NAVY):
                    with app.scrollPane("CE_Pane_Parameters_0", padding=[4, 1],
                                        row=0, column=0, disabled="horizontal", sticky="NEW"):
                        app.label("CE_Label_0_00", "Party sprites facing", sticky="E", colspan=2,
                                  row=1, column=0, font=11)
                        app.optionBox("CE_Param_0_00", ["None", "East", "West", "North", "South"],
                                      change=cutscene_input,
                                      sticky="W", width=10, colspan=2, row=1, column=2, font=10)

                        app.label("CE_Label_0_01", "Show party sprite 1", sticky="WE",
                                  row=2, column=0, font=11)
                        app.checkBox("CE_Param_0_01", True, name="", change=cutscene_input, sticky="W",
                                     row=2, column=1)
                        app.label("CE_Label_0_02", "Show party sprite 2", sticky="WE",
                                  row=3, column=0, font=11)
                        app.checkBox("CE_Param_0_02", True, name="", change=cutscene_input, sticky="W",
                                     row=3, column=1)
                        app.label("CE_Label_0_03", "Show party sprite 3", sticky="WE",
                                  row=4, column=0, font=11)
                        app.checkBox("CE_Param_0_03", True, name="", change=cutscene_input, sticky="W",
                                     row=4, column=1)
                        app.label("CE_Label_0_04", "Show party sprite 4", sticky="WE",
                                  row=5, column=0, font=11)
                        app.checkBox("CE_Param_0_04", True, name="", change=cutscene_input, sticky="W",
                                     row=5, column=1)

                        app.label("CE_Label_0_05", "Movement offset (X)", sticky="WE",
                                  row=2, column=2, font=11)
                        app.entry("CE_Param_0_05", "-1", change=cutscene_input, sticky="W", width=3,
                                  row=2, column=3, font=10)
                        app.label("CE_Label_0_06", "Movement offset (X)", sticky="WE",
                                  row=3, column=2, font=11)
                        app.entry("CE_Param_0_06", "-1", change=cutscene_input, sticky="W", width=3,
                                  row=3, column=3, font=10)
                        app.label("CE_Label_0_07", "Movement offset (X)", sticky="WE",
                                  row=4, column=2, font=11)
                        app.entry("CE_Param_0_07", "1", change=cutscene_input, sticky="W", width=3,
                                  row=4, column=3, font=10)
                        app.label("CE_Label_0_08", "Movement offset (X)", sticky="WE",
                                  row=5, column=2, font=11)
                        app.entry("CE_Param_0_08", "1", change=cutscene_input, sticky="W", width=3,
                                  row=5, column=3, font=10)

                        app.label("CE_Label_0_09", "Delay", sticky="WE",
                                  row=2, column=4, font=11)
                        app.entry("CE_Param_0_09", "1", change=cutscene_input, sticky="W", width=3,
                                  row=2, column=5, font=10)
                        app.label("CE_Label_0_10", "Delay", sticky="WE",
                                  row=3, column=4, font=11)
                        app.entry("CE_Param_0_10", "3", change=cutscene_input, sticky="W", width=3,
                                  row=3, column=5, font=10)
                        app.label("CE_Label_0_11", "Delay", sticky="WE",
                                  row=4, column=4, font=11)
                        app.entry("CE_Param_0_11", "3", change=cutscene_input, sticky="W", width=3,
                                  row=4, column=5, font=10)
                        app.label("CE_Label_0_12", "Delay", sticky="WE",
                                  row=5, column=4, font=11)
                        app.entry("CE_Param_0_12", "1", change=cutscene_input, sticky="W", width=3,
                                  row=5, column=5, font=10)

                        app.label("CE_Label_0_13", "Global movement", sticky="E", colspan=2,
                                  row=6, column=0, font=11)
                        app.optionBox("CE_Param_0_13", ["None", "Up", "Down", "Left", "Right"], change=cutscene_input,
                                      sticky="W", row=6, column=2, font=10)

                        app.label("CE_Label_0_14", "Starting X", sticky="E",
                                  row=7, column=0, font=11)
                        app.entry("CE_Param_0_14", "0", change=cutscene_input, sticky="W", width=3,
                                  row=7, column=1, font=10)
                        app.label("CE_Label_0_15", "Starting Y", sticky="E",
                                  row=7, column=2, font=11)
                        app.entry("CE_Param_0_15", "0", change=cutscene_input, sticky="W", width=3,
                                  row=7, column=3, font=10)

                        app.label("CE_Label_0_16", "Target position", sticky="E", colspan=2,
                                  row=8, column=0, font=11)
                        app.optionBox("CE_Param_0_16", ["X =", "Y =", "X >=", "Y >=", "X <", "Y <"],
                                      change=cutscene_input,
                                      row=8, column=2, sticky="WE", font=10)
                        app.entry("CE_Param_0_17", "0", change=cutscene_input, sticky="W", width=4,
                                  row=8, column=3, font=10)

                        app.label("CE_Label_0_18", "First dialogue ID", sticky="E",
                                  row=9, column=0, font=11)
                        app.entry("CE_Param_0_18", "32", change=cutscene_input, sticky="W", width=4,
                                  row=9, column=1, font=10)
                        app.label("CE_Label_0_19", "Last dialogue ID", sticky="E",
                                  row=9, column=2, font=11)
                        app.entry("CE_Param_0_19", "37", change=cutscene_input, sticky="W", width=4,
                                  row=9, column=3, font=10)

                        app.label("CE_Label_0_20", "Dialogue X", sticky="E",
                                  row=10, column=0, font=11)
                        app.entry("CE_Param_0_20", "0", change=cutscene_input, sticky="W", width=3,
                                  row=10, column=1, font=10)
                        app.label("CE_Label_0_21", "Dialogue Y", sticky="E",
                                  row=11, column=0, font=11)
                        app.entry("CE_Param_0_21", "0", change=cutscene_input, sticky="W", width=3,
                                  row=11, column=1, font=10)

                        app.label("CE_Label_0_22", "Dialogue Width", sticky="E",
                                  row=10, column=2, font=11)
                        app.entry("CE_Param_0_22", "0", change=cutscene_input, sticky="W", width=3,
                                  row=10, column=3, font=10)
                        app.label("CE_Label_0_23", "Dialogue Height", sticky="E",
                                  row=11, column=2, font=11)
                        app.entry("CE_Param_0_23", "0", change=cutscene_input, sticky="W", width=3,
                                  row=11, column=3, font=10)

                    # Resize scrollable pane
                    canvas = app.getScrollPaneWidget("CE_Pane_Parameters_0").canvas
                    canvas.configure(width=492 - 8, height=344 - 160)

                # Time Lord screen parameters
                with app.frame("CE_Frame_Cutscene_1", bg=colour.PALE_BLUE):
                    # Parameters
                    with app.frame("CE_Frame_Parameters_1", row=0, column=0, padding=[4, 1], sticky="NEW"):
                        app.label("CE_Label_1_00", "Dialogue ID", sticky="E", row=0, column=0, font=11)
                        app.entry("CE_Param_1_00", "", width=5, sticky="W", change=cutscene_input,
                                  row=0, column=1, font=10, fg=colour.BLACK)

                # Title screen parameters
                with app.frame("CE_Frame_Cutscene_2", bg=colour.PALE_VIOLET):
                    # Parameters
                    with app.frame("CE_Frame_Parameters_2", row=0, column=0, padding=[4, 1], sticky="NEW"):
                        app.label("CE_Label_2_00", "Music", sticky="E", row=0, column=0, font=11)
                        app.optionBox("CE_Param_2_00", ["- File not loaded -"], change=None, width=24,
                                      sticky="W", row=0, column=1, colspan=2, font=10, fg=colour.BLACK)

                        app.label("CE_Label_2_01", "Text Position (X)", row=1, column=0, sticky="NE")
                        app.entry("CE_Param_2_01", "", change=cutscene_input,
                                  sticky="NW", width=5, row=1, column=1, font=10, fg=colour.BLACK)

                        app.label("CE_Label_2_02", "Text Position (Y)", row=1, column=2, sticky="NE")
                        app.entry("CE_Param_2_02", "", change=cutscene_input,
                                  sticky="NW", width=5, row=1, column=3, font=10, fg=colour.BLACK)

                        app.label("CE_Label_2_03", "Line Length", row=2, column=0, sticky="NE")
                        app.entry("CE_Param_2_03", "", change=cutscene_input,
                                  sticky="NW", width=5, row=2, column=1, font=10, fg=colour.BLACK)

                        app.label("CE_Label_2_04", "Line Count", row=2, column=2, sticky="NE")
                        app.entry("CE_Param_2_04", "", change=cutscene_input,
                                  sticky="NW", width=5, row=2, column=3, font=10, fg=colour.BLACK)

                # Mark of Force screen parameters
                with app.frame("CE_Frame_Cutscene_3", bg=colour.PALE_GREEN):
                    # Parameters
                    with app.frame("CE_Frame_Parameters_3", row=0, column=0, padding=[4, 1], sticky="NEW"):
                        app.label("CE_Label_3_00", "Dialogue ID", sticky="E", row=0, column=0, font=11)
                        app.entry("CE_Param_3_00", "", width=5, sticky="W", change=cutscene_input,
                                  row=0, column=1, font=10, fg=colour.BLACK)

                # Mark of Fire screen parameters
                with app.frame("CE_Frame_Cutscene_4", bg=colour.PALE_OLIVE):
                    # Parameters
                    with app.frame("CE_Frame_Parameters_4", row=0, column=0, padding=[4, 1], sticky="NEW"):
                        app.label("CE_Label_4_00", "Dialogue ID", sticky="E", row=0, column=0, font=11)
                        app.entry("CE_Param_4_00", "", width=5, sticky="W", change=cutscene_input,
                                  row=0, column=1, font=10, fg=colour.BLACK)

                # Mark of Snake screen parameters
                with app.frame("CE_Frame_Cutscene_5", bg=colour.PALE_LIME):
                    # Parameters
                    with app.frame("CE_Frame_Parameters_5", row=0, column=0, padding=[4, 1], sticky="NEW"):
                        app.label("CE_Label_5_00", "Dialogue ID", sticky="E", row=0, column=0, font=11)
                        app.entry("CE_Param_5_00", "", width=5, sticky="W", change=cutscene_input,
                                  row=0, column=1, font=10, fg=colour.BLACK)

                # Mark of King screen parameters
                with app.frame("CE_Frame_Cutscene_6", bg=colour.PALE_TEAL):
                    # Parameters
                    with app.frame("CE_Frame_Parameters_6", row=0, column=0, padding=[4, 1], sticky="NEW"):
                        app.label("CE_Label_6_00", "Dialogue ID", sticky="E", row=0, column=0, font=11)
                        app.entry("CE_Param_6_00", "", width=5, sticky="W", change=cutscene_input,
                                  row=0, column=1, font=10, fg=colour.BLACK)

                # Fountain screen parameters
                with app.frame("CE_Frame_Cutscene_7", bg=colour.PALE_TEAL):
                    # Parameters
                    with app.frame("CE_Frame_Parameters_7", row=0, column=0, padding=[4, 1], sticky="NEW"):
                        app.label("CE_Label_7_00", "Dialogue ID", sticky="E", row=0, column=0, font=11)
                        app.entry("CE_Param_7_00", "", width=5, sticky="W", change=cutscene_input,
                                  row=0, column=1, font=10, fg=colour.BLACK)

            # Buttons
            with app.frame("CE_Frame_Buttons", padding=[4, 0], sticky="SEW", row=2, column=0):
                app.button("CE_Save_Parameters", cutscene_input, image="res/floppy.gif", sticky="E",
                           tooltip="Save Screen Parameters",
                           width=32, height=32, row=0, column=0)
                app.button("CE_Reload_Parameters", cutscene_input, image="res/reload.gif", sticky="W",
                           tooltip="Reload Parameters from ROM Buffer",
                           width=32, height=32, row=0, column=2)
                app.button("CE_Edit_Graphics", cutscene_input, image="res/brush.gif", sticky="WE",
                           tooltip="Edit Graphics",
                           width=128, height=32, row=0, column=3)

        # SFX / MUSIC Tab ----------------------------------------------------------------------------------------------
        with app.tab("\u266B", padding=[4, 2]):

            # --- Music Frame
            with app.labelFrame("ST_Frame_Music", name="Music", padding=[4, 2], sticky="NEW", bg=colour.PALE_ORANGE,
                                row=0, column=0):
                with app.frame("ST_Frame_Bank", padding=[4, 1], sticky="NEWS", row=0, column=0):
                    app.optionBox("ST_Music_Bank", ["Bank 8", "Bank 9"], change=sound_tab_input, width=12, sticky="W",
                                  row=0, column=0, font=10)
                    app.label("ST_Label_Tracks_Count", "Max tracks:", sticky="E", row=0, column=1, font=11)
                    app.spinBox("ST_Tracks_Count", list(range(11, 1, -1)), change=sound_tab_input, width=4,
                                sticky="W", row=0, column=2, font=10)
                    app.checkBox("ST_Fix_Envelope_Bug", name="Fix Envelope Bug", sticky="E",
                                 row=0, column=3, font=10)

                with app.frame("ST_Frame_Instruments", padding=[2, 1], sticky="NEWS", row=1, column=0):
                    app.label("ST_Label_Instruments", "Instruments in this bank: 0", sticky="WE",
                              row=0, column=0, font=11)
                    app.button("ST_Import_Instruments", sound_tab_input, text="Import from bank 9", sticky="E",
                               bg=colour.WHITE, row=0, column=1, font=10)

                    app.button("ST_Edit_Instruments", sound_tab_input, text="Edit Instruments", sticky="E",
                               bg=colour.WHITE, tooltip="Open the Instrument Editor",
                               width=12, row=0, column=2, font=10)

                with app.frame("ST_Frame_Music", padding=[2, 1], sticky="NEWS", row=2, column=0):
                    app.label("ST_Label_Tracks", "Music in this bank:", sticky="E", row=0, column=0, font=11)
                    app.optionBox("ST_Option_Music", ["- No Tracks -"], width=24, sticky="W", row=0, column=1, font=10)

                    app.button("ST_Edit_Music", sound_tab_input, text="Edit Track", sticky="E",
                               bg=colour.WHITE, tooltip="Open the Track Editor",
                               width=12, row=0, column=2, font=10)

            # --- SFX Frame
            with app.labelFrame("ST_Frame_SFX", name="Sound Effects", padding=[4, 2], sticky="SEW",
                                bg=colour.PALE_BROWN, row=1, column=0):
                app.optionBox("ST_Option_SFX", [f"0x{n:02X} (No Name)" for n in range(52)], width=32,
                              change=sound_tab_input, sticky="E", row=0, column=0, font=10)
                app.button("ST_Edit_SFX", sound_tab_input, text="Edit SFX", tooltip="Open the Sound Effect editor",
                           bg=colour.WHITE, sticky="W", row=0, column=1, font=10)
                app.label("ST_Label_Info", "Channel: ", sticky="WE", row=1, column=0, colspan=2, font=10)

        #       ##### End of tab definitions #####

        app.stopTabbedFrame()

        # Deactivate tabs until ROM is loaded
        app.setTabbedFrameDisabledTab("TabbedFrame", "Map", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Misc", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Enemies", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Text", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Palettes", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Screens", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "\u266B", True)

        # Status bar
        app.statusFont = 9
        app.addStatusbar(fields=1)
        app.setStatusbar("Open a ROM file to begin...", field=0)

        #       ##### Sub-Windows #####

        # Instrument Editor Sub-Window ---------------------------------------------------------------------------------
        with app.subWindow("Instrument_Editor", title="Ultima Exodus Instrument Editor", size=[900, 456],
                           padding=[2, 0], modal=False, resizable=False, inPadding=0, guiPadding=0,
                           bg=colour.DARK_ORANGE, fg=colour.WHITE, stopFunction=instrument_editor_stop):

            app.label("IE_Label_Temp", "...")

        # Track Editor Sub-Window --------------------------------------------------------------------------------------
        with app.subWindow("Track_Editor", title="Ultima Exodus Track Editor", size=[900, 720], padding=[2, 0],
                           modal=False, resizable=False, inPadding=0, guiPadding=0,
                           bg=colour.DARK_NAVY, fg=colour.WHITE, stopFunction=track_editor_stop):

            app.label("SE_Label_Temp", "...")

        # Screen Editor Sub-Window -------------------------------------------------------------------------------------
        with app.subWindow("Cutscene_Editor", title="Screen Editor", size=[800, 402], padding=[2, 0], modal=False,
                           resizable=False, inPadding=0, guiPadding=0, bg=colour.DARK_GREY,
                           stopFunction=cutscene_editor_stop):

            # Buttons
            with app.frame("CE_Cutscene_Buttons", row=0, column=0, padding=[2, 0]):
                app.button("CE_Cutscene_Save", cutscene_input, image="res/floppy.gif", sticky="W", width=32, height=32,
                           tooltip="Save Changes and close this window",
                           row=0, column=0)
                app.button("CE_Cutscene_Import", cutscene_input, image="res/import.gif", sticky="W", width=32,
                           tooltip="Import from File",
                           height=32, row=0, column=1)
                app.button("CE_Cutscene_Export", cutscene_input, image="res/export.gif", sticky="W", width=32,
                           tooltip="Export to File",
                           height=32, row=0, column=2)
                app.button("CE_Cutscene_Close", cutscene_input, image="res/close.gif", sticky="W", width=32, height=32,
                           tooltip="Discard Changes and close this window",
                           row=0, column=3)
                app.button("CE_Cutscene_1x1", cutscene_input, image="res/1x1.gif", sticky="E", width=32, height=32,
                           tooltip="Select/Edit 1 Tile/Pattern",
                           row=0, column=4, bg=colour.WHITE)
                app.button("CE_Cutscene_2x2", cutscene_input, image="res/2x2.gif", sticky="E", width=32, height=32,
                           tooltip="Select/Edit Groups of 2x2 Tiles/Patterns",
                           row=0, column=5, bg=colour.DARK_GREY)

            # Info
            app.label("CE_Info_Cutscene", "Info here...", fg=colour.WHITE, sticky="W", font=11, row=0, column=1)

            # Drawing area
            with app.scrollPane("CE_Pane_Cutscene", row=1, column=1, rowspan=5):
                app.canvas("CE_Canvas_Cutscene", row=0, column=0, width=512, height=480, bg=colour.MEDIUM_GREY)
                app.setCanvasCursor("CE_Canvas_Cutscene", "pencil")

            # Tiles
            app.canvas("CE_Canvas_Patterns", sticky="N", row=1, column=0, width=256, height=256, bg=colour.BLACK)
            app.setCanvasCursor("CE_Canvas_Patterns", "hand1")
            app.label("CE_Pattern_Info", "Pattern: 0x00", sticky="NW", row=2, column=0, font=9, fg=colour.BLACK)

            # Palette
            app.canvas("CE_Canvas_Palettes", row=3, column=0, width=256, height=18, bg=colour.MEDIUM_MAGENTA)
            app.setCanvasCursor("CE_Canvas_Palettes", "hand1")
            app.label("CE_Palette_Info", "Palette: 0", sticky="NW", row=4, column=0, font=9, fg=colour.BLACK)

        # Party Editor Sub-Window --------------------------------------------------------------------------------------
        with app.subWindow("Party_Editor", title="Party Editor", size=[360, 240], modal=False, resizable=False,
                           padding=0, inPadding=0, guiPadding=0, bg=colour.LIGHT_BLUE,
                           stopFunction=party_editor_stop):

            app.label("PE_Label_p0", "")

        # Progress Sub-Window ----------------------------------------------------------------------------------
        with app.subWindow("PE_Progress", title="Loading", modal=True, size=[300, 100], padding=[4, 4],
                           bg=colour.DARK_TEAL, fg=colour.WHITE, stopFunction=no_stop):

            app.label("PE_Progress_Label", "Please wait...", row=0, column=0, font=16)
            app.meter("PE_Progress_Meter", value=0, row=1, column=0, stretch="BOTH", sticky="WE",
                      fill=colour.MEDIUM_BLUE)

        # Map Editor Sub-Window ----------------------------------------------------------------------------------------
        with app.subWindow("Map_Editor", "Map Editor", size=[512, 480], modal=False, resizable=False, padding=0,
                           inPadding=0, guiPadding=0, bg=colour.WHITE):
            app.label("ME_Label_temp", "...")

        # Battlefield Editor Sub-Window --------------------------------------------------------------------------------
        with app.subWindow("Battlefield_Editor", "Battlefield Editor", size=[320, 612], modal=False, resizable=False,
                           padding=0, inPadding=0, guiPadding=0, bg=colour.PALE_BROWN):
            app.label("BE_Label_temp", "...")

        # Text Editor Sub-Window ---------------------------------------------------------------------------------------
        with app.subWindow("Text_Editor", "Ultima: Exodus - Text Editor", size=[428, 412], modal=False, resizable=False,
                           stopFunction=text_editor_stop, bg=colour.MEDIUM_GREY):
            # Buttons
            with app.frame("TE_Frame_Top", row=0, colspan=2, sticky="NEW", stretch="ROW", padding=[8, 2]):
                app.button("TE_Button_Accept", text_editor_input, image="res/floppy.gif",
                           tooltip="Apply Changes and Close", row=0, column=0, sticky="W")
                app.button("TE_Button_Close", text_editor_input, image="res/close.gif",
                           tooltip="Discard Changes and Close", row=0, column=1, sticky="W")
                app.button("TE_Button_Customise", text_editor_input, image="res/alphabet.gif",
                           tooltip="Customise Character Mapping", row=0, column=2, sticky="E")

            # Text
            with app.frame("TE_Frame_Left", row=1, column=0, bg=colour.DARK_GREY, sticky="NEW", stretch='COLUMN',
                           rowspan=2, padding=[2, 2]):
                app.label("TE_Label_Text", "Unpacked string:", row=0, column=0, fg=colour.WHITE)
                app.textArea("TE_Text", "", width=22, height=6, sticky="NEWS", scroll=True, bg=colour.WHITE,
                             row=1, column=0).setFont(family="monospace", size=9, weight="bold")

                app.canvas("TE_Preview", sticky="N", width=160, height=72, row=2, column=0, bg=colour.BLACK)

                with app.frame("TE_Preview_Controls", padding=[1, 1], row=3, column=0):
                    app.radioButton("TE_Preview_Mode", "Default", change=text_editor_input, font=9, sticky="NEW",
                                    row=0, column=0)
                    app.radioButton("TE_Preview_Mode", "Conversation", change=text_editor_input, font=9, sticky="NEW",
                                    row=0, column=1)
                    app.radioButton("TE_Preview_Mode", "Intro", change=text_editor_input, font=9, sticky="NEW",
                                    row=0, column=2)
                    app.button("TE_Conversation_Advance", text_editor_input, font=9, sticky="WE",
                               text="Advance Conversation \u2B06 / \u2B07", row=1, column=0, colspan=3)

            # Guide
            with app.frame("TE_Frame_TopRight", row=1, column=1, fg=colour.BLACK, padding=[2, 2]):
                app.message("TE_Message_Guide", "@ = Active character's name\n" +
                            "% = Enemy name (in battle)\n# = 16-bit numeric value\n" +
                            "& = Next string becomes new dialogue\n^ = Ask YES/NO after dialogue\n" +
                            "$ = Unlocks the 'PRAY' command\n* = Unlocks the 'BRIBE' command\n" +
                            "~ = String terminator", width=164, sticky="NEWS", font=9)

            # Address
            with app.frame("TE_Frame_Right", row=2, column=1, bg=colour.DARK_GREY, fg=colour.WHITE, padding=[2, 2]):
                app.label("TE_Label_Type", "(Text type)", row=0, column=0, colspan=2, font=11)
                app.entry("TE_Entry_Address", "", width=16, row=1, column=0, case="upper", font=11)
                app.button("TE_Button_Reload_Text", text_editor_input, image="res/reload-small.gif",
                           row=1, column=1, width=16, height=16)

            # Dialogue name and portrait
            with app.frame("TE_Frame_Bottom", row=3, colspan=2, sticky='SEW', stretch='COLUMN',
                           padding=[2, 2], bg=colour.WHITE):
                with app.labelFrame("Dialogue Properties", 0, 0, padding=[4, 4]):
                    with app.frame("TE_Frame_Dialogue_Left", row=0, column=0, sticky="NEW",
                                   stretch='COLUMN'):
                        app.label("TE_Label_Name", "NPC Name: ", row=0, column=0)
                        app.optionBox("TE_Option_Name", ["(0xFF) No Name"], change=text_editor_input,
                                      row=0, column=1, width=20)
                        app.label("TE_Label_Portrait", "Portrait: ", row=1, column=0)
                        portrait_options = ["No Portrait"]
                        for p in range(0x22):
                            portrait_options.append(f"{p:02d}")
                        app.optionBox("TE_Option_Portrait", portrait_options, change=select_portrait, row=1, column=1)

                    with app.frame("TE_Frame_Dialogue_Right", row=0, column=1, bg=colour.MEDIUM_GREY, sticky="NEW",
                                   stretch='COLUMN'):
                        app.canvas("TE_Canvas_Portrait", width=40, height=48, bg=colour.BLACK, map=None, sticky="NEW",
                                   stretch='NONE')

    del maps_list
    del portrait_options
    del tiles_list

    sys.setswitchinterval(0.05)
