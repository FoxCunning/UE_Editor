"""
An extensive editor for the NES version of Ultima III: Exodus and its Remastered Hack by Fox Cunning
"""
__version__ = "0.01"

__author__ = "Fox Cunning"
__copyright__ = "Copyright ©2020, Fox Cunning"
__credits__ = ["Fox Cunning"]

__license__ = "Apache 2.0"

__maintainer__ = "Fox Cunning"
__email__ = ""
__status__ = "Development"

import ast
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import TextIO, List

from appJar import gui
from debug import log
from enemy_editor import EnemyEditor
from map_editor import MapEditor, MapTableEntry
from palette_editor import PaletteEditor
from party_editor import PartyEditor
from rom import ROM, feature_names
from text_editor import TextEditor


# --- Editor Settings class ---

@dataclass(init=True, repr=False)
class EditorSettings:
    """
    A fairly generic class for keeping track of settings, loading/saving etc.
    """
    settings_file: str = "settings.conf"
    _keys = {"last rom path": "",
             "make backups": True,
             "emulator": "",
             "emulator parameters": "%f",
             "last map import path": "",
             "last map export path": "",
             "editor fonts": "Consolas",
             "sync npc sprites": True
             }

    # --- EditorSettings.load() ---

    def load(self) -> bool:
        """
        Loads settings from file.
           If the file does not exist, save() is called to create one with the default values.

        Returns
        -------
        bool
            True if settings have been successfully loaded. False otherwise.
        """
        # Get execution path
        path: str = os.path.realpath(__file__)
        try:
            last = path.rindex('\\')
        except ValueError:
            try:
                last = path.rindex('/')
            except ValueError:
                # Does not look like a directory name
                return False
        path = path[:last + 1]
        path = path + self.settings_file
        try:
            file = open(path, "rt")
        except OSError:
            log(3, "EDITOR", "Could not load settings from file. Creating one.")
            return self.save()

        # Read and parse lines
        line = file.readline()
        while line != "":
            self._parse_line(line)  # Parse last line
            line = file.readline()  # Get next line

        file.close()
        return True

    # --- EditorSettings.save() ---

    def save(self) -> bool:
        """
        Saves current settings to file

        Returns
        -------
        bool
            True if settings were successfully saved. False otherwise.
        """
        # Get execution path
        path: str = os.path.realpath(__file__)
        try:
            last = path.rindex('\\')
        except ValueError:
            try:
                last = path.rindex('/')
            except ValueError:
                # Does not look like a directory name
                return False
        path = path[:last + 1]

        path = path + self.settings_file

        try:
            file = open(path, "wt")
        except OSError:
            log(3, "EDITOR", "Could not save settings to file. Make sure you have write access to the editor's folder.")
            return False

        for key in self._keys:
            setting_string = f"{key} = {self._keys[key]}\n"
            file.write(setting_string)

        file.close()
        return True

    # --- EditorSettings._parse_line() ---

    def _parse_line(self, line: str) -> None:
        """
        Parses one line of text from the settings file

        Parameters
        ----------
        line: str
            Line of text to parse
        """
        # Strip leading and trailing whitespaces
        line = line.strip()

        # Skip lines that were just a newline
        if len(line) < 1:
            return

        # Get the part of the line before the '='
        try:
            index = line.index('=')
        except ValueError:
            # '=' not found
            log(2, "EDITOR", f"Error parsing setting '{line}'.")
            return

        key = line[:index].strip()
        value = line[index + 1:].strip()

        try:
            # Some settings should not be treated as strings
            if key == "make backups":
                if value.lower() == "true" or value == "1" or value.lower() == "yes":
                    value = True
                else:
                    value = False
            elif key == "sync npc sprites":
                if value.lower() == "true" or value == "1" or value.lower() == "yes":
                    value = True
                else:
                    value = False

            # Assign the value read from file
            self._keys[key] = value
        except KeyError:
            log(2, "EDITOR", f"Invalid setting '{key}' in line '{line}'.")

        return

    # --- EditorSettings.get() ---

    def get(self, key: str) -> any:
        """
        Retrieves the value of a setting

        Parameters
        ----------
        key: str
            Name of the setting, e.g. "last rom path"

        Returns
        -------
        any
            The current value for that setting, or None if the key was not valid
        """
        try:
            value = self._keys[key]
        except KeyError:
            log(3, "EDITOR", f"Setting '{key}' not found.")
            return None

        return value

    # --- EditorSettings.set() ---

    def set(self, key: str, value: str) -> None:
        """
        Changes the value of the given setting

        Parameters
        ----------
        key: str
            The name of the setting to change
        value: str
            The desired new value as a string
        """
        self._parse_line(f"{key} = {value}")


# --- Global variables ---

settings = EditorSettings()

rom = ROM()

emulator_pid: subprocess.Popen

# Index of the selected map from the drop-down option box
selected_map: int = -1

# Index of the selected entrance / moongate from the listbox in the Entrance Editor sub-sub-window
selected_entrance: int = -1
selected_moongate: int = -1

# Compression method for the selected map
map_compression: str = "none"

# Sub-window handlers
map_editor: MapEditor
text_editor: TextEditor
palette_editor: PaletteEditor
enemy_editor: EnemyEditor
party_editor: PartyEditor

# These will be save when clicking on the map
last_tile = {
    "x": 0,
    "y": 0
}


# --- get_option_index() ---

def get_option_index(widget: str, value: str) -> int:
    """
    Retrieves the index of the desired item from an OptionBox

    Parameters
    ----------
    widget: str
        Name of the OptionBox widget
    value: str
        Value of the item whose index is to be retrieved

    Returns
    -------
    int
        The index of the item; rises ValueError if not found
    """
    box = app.getOptionBoxWidget(widget)
    return box.options.index(value)


# --- edit_map() ---

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

    app.showSubWindow("Map_Editor", hide=False)
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
    else:
        map_editor.load_npc_data()
        # Move the map editor and the NPC editor relatively to the main window
        main_location = app.getLocation()
        app.setSubWindowLocation("Map_Editor", main_location[0] - 256, main_location[1])
        app.setSubWindowLocation("NPC_Editor", main_location[0] + 258, main_location[1])
        app.setSubWindowLocation("Entrance_Editor", main_location[0] - 514, main_location[1])

        app.hideFrame("ME_Frame_Dungeon_Tools")

        app.hideLabelFrame("NPCE_Frame_Info")
        app.showSubWindow("NPC_Editor", hide=False)

        app.showSubWindow("Entrance_Editor", hide=False)

        # Show entrances and Moongates
        map_editor.load_entrances()
        map_editor.load_moongates()


# --- select_dungeon_level() ---

def select_dungeon_level(sel: str) -> None:
    """
    Called when the user clicks on the dungeon level Option Box widget

    Parameters
    ----------
    sel: str
        Title of the Option Box widget
    """
    try:
        level = int(app.getOptionBox(sel)) - 1
    except ValueError:
        level = 0

    map_editor.dungeon_level = level
    map_editor.show_map()


# --- change_dungeon_message() ---

def change_dungeon_message(widget) -> None:
    """
    User typed something in the dungeon message

    Parameters
    ----------
    widget
        The TextArea widget where the event occurred
    """
    map_editor.change_message(message=app.getTextArea(widget))


# --- select_dungeon_special_type() ---

def select_dungeon_special_type(widget) -> None:
    """
    User selected either a new Mark or Fountain type for the currently selected dungeon tile

    Parameters
    ----------
    widget
        The OptionBox where the event occurred
    """
    tile_x = last_tile["x"]
    tile_y = last_tile["y"]

    try:
        special_id = int(app.getOptionBox(widget)[0])
    except ValueError as error:
        log(2, "EDITOR", f"Could not read special type ID from '{app.getOptionBox(widget)}': {error}")
        return

    # First, check if the current tile is a special one, and then change it depending on which one it is
    tile_id = map_editor.get_tile_id(tile_x, tile_y)

    if tile_id == 6:  # Mark
        map_editor.change_mark_type(tile_x, tile_y, special_id)
    elif tile_id == 7:  # Fountain
        map_editor.change_fountain_type(tile_x, tile_y, special_id)
    else:  # Not a special tile!
        app.errorBox("ERROR", f"Could not find special tile at {tile_x}, {tile_y}!\nID = 0x{tile_id:02X}.",
                     parent="Map_Editor")


# --- no_stop() ---

def no_stop() -> bool:
    """
    Used for sub-windows that should only be closed programmatically

    Returns
    -------
    bool
        False
    """
    return False


# --- map_editor_stop() ---

def map_editor_stop() -> bool:
    """
    Handles a request to close the map editor sub-window

    Returns
    -------
    bool
        Always returns true
    """
    # TODO Ask to save changes (if any)
    app.hideSubWindow("NPC_Editor")
    app.hideSubWindow("Map_Editor", useStopFunction=False)
    app.hideSubWindow("Entrance_Editor", useStopFunction=False)
    return True


# --- map_editor_input() ---

def map_editor_input(widget: str) -> None:
    """
    Generic button callback for the Map Editor sub-window and its sub-windows

    Parameters
    ----------
    widget: str
        Name of the Button widget being pressed

    """
    if widget == "ME_Button_Draw":
        map_editor.select_tool("draw")

    elif widget == "ME_Button_Fill":
        map_editor.select_tool("fill")

    elif widget == "ME_Button_Clear":
        map_editor.select_tool("clear")

    elif widget == "ME_Button_Info":
        map_editor.select_tool("info")

    elif widget == "MapEditor_Save":
        if settings.get("sync npc sprites"):
            sync = True
        else:
            sync = False
        map_editor.save_map(sync)

        # Reload enemy sprites if sync sprite options is selected
        if sync:
            enemy_editor.read_enemy_data(text_editor)

        app.hideSubWindow("Entrance_Editor")
        app.hideSubWindow("NPC_Editor")
        app.hideSubWindow("Map_Editor")
        # Addresses may have changed due to reallocation, so refresh display
        update_map_table(map_editor.map_table[selected_map])

    elif widget == "MapEditor_Import":
        # Browse for a file to import
        file_name = app.openBox("Import Map Data...", settings.get("last map import path"),
                                [("4-bit packed", "*.bin"), ("LZSS Compressed", "*.lzss"), ("RLE Encoded", "*.rle")],
                                asFile=False, parent="Map_Editor", multiple=False)
        if file_name != "":
            map_editor.import_map(file_name)
            directory = os.path.dirname(file_name)
            settings.set("last map import path", directory)

    elif widget == "MapEditor_Export":
        # Ask for a file name
        file_name = app.saveBox("Export Map Data...", None, settings.get("last map export path"), ".bin",
                                [("4-bit packed", "*.bin"), ("LZSS Compressed", "*.lzss"), ("RLE Encoded", "*.rle")],
                                parent="Map_Editor")
        if file_name != "":
            map_editor.export_map(file_name)
            directory = os.path.dirname(file_name)
            settings.set("last map export path", directory)

    elif widget == "ME_Option_Map_Colours":
        # Do nothing if ROM doesn't support custom map colours
        if rom.has_feature("custom map colours") is False:
            return

        # Read value
        try:
            colour = int(app.getOptionBox("ME_Option_Map_Colours"), 16)
        except ValueError:
            return
        # Reload tiles using the new colour
        map_editor.load_tiles(map_colour=colour)
        # Redraw the map
        map_editor.redraw_map()

    elif widget == "NPCE_Option_NPC_List":
        try:
            # Move the map to the specified NPC's position
            npc_index = int(app.getOptionBox("NPCE_Option_NPC_List")[:2])
            x = map_editor.npc_data[npc_index].starting_x
            y = map_editor.npc_data[npc_index].starting_y
            if (0 <= x <= 63) and (0 <= y <= 63):
                map_editor.jump_to(x, y)

            # Populate the info frame with the selected character's data
            npc_index = int(app.getOptionBox("NPCE_Option_NPC_List")[:2])
            map_editor.npc_index = npc_index
            map_editor.npc_info(npc_index)
            app.showLabelFrame("NPCE_Frame_Info")

        except ValueError:
            pass

    elif widget == "NPCE_Entry_Dialogue_ID":
        # Get Dialogue/Function ID
        value = app.getEntry("NPCE_Entry_Dialogue_ID")
        try:
            dialogue_id = int(value, 16)
        except ValueError:
            # app.errorBox("Apply NPC Changes", f"ERROR: Invalid Dialogue/Function ID '{value}'.\n"
            #                                  "Please enter a numeric value in hexadecimal format (e.g.: 0x1B).",
            #             parent="NPC_Editor")
            return

        map_editor.set_npc_dialogue(dialogue_id)

    elif widget == "NPCE_Create":
        # This will create a new NPC with default attributes
        map_editor.npc_info(-1)
        app.showLabelFrame("NPCE_Frame_Info")
        # app.setButton("NPCE_Button_Create_Apply", "Create NPC")

    elif widget == "NPCE_Button_Position":
        map_editor.select_tool("move_npc")

    elif widget == "NPCE_Button_Edit_Dialogue":
        string_id = app.getEntry("NPCE_Entry_Dialogue_ID")
        try:
            value = int(string_id, 16)
            if 0 <= value <= 0xE6:
                text_editor.show_window(value, "Dialogue")
            else:
                app.warningBox("Edit Dialogue", f"{string_id} is not a valid Dialogue ID.", parent="NPC_Editor")
        except ValueError:
            app.warningBox("Edit Dialogue", f"{string_id} is not a valid Dialogue ID.", parent="NPC_Editor")

    else:
        log(3, "EDITOR", f"Unimplemented Map Editor button: {widget}")


# --- map_editor_pick_tile() ---

def map_editor_pick_tile(event: any) -> None:
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
    map_editor.selected_tile_id = tile_index
    map_editor.tile_info(tile_index)
    app.setLabel("ME_Selected_Tile_Position", "")

    # Hide the "special" field for now
    app.hideFrame("ME_Frame_Special_Tile")

    # If the current tool is neither "draw" nor "fill", switch to drawing mode
    if map_editor.tool != "draw" and map_editor.tool != "fill":
        map_editor.select_tool("draw")


# --- map_editor_edit_tile() ---

def map_editor_edit_tile(event: any) -> None:
    """
    Called when the user clicks on the map canvas

    Parameters
    ----------
    event
        Mouse click event instance
    """
    tile_x = event.x >> 4
    tile_y = event.y >> 4

    # Save coordinates for future editing
    last_tile["x"] = tile_x
    last_tile["y"] = tile_y

    if map_editor.tool == "draw":
        map_editor.change_tile(tile_x, tile_y, map_editor.selected_tile_id, True)
        # Also display tile position
        app.setLabel("ME_Selected_Tile_Position", f"[{tile_x}, {tile_y}]")

    elif map_editor.tool == "fill":
        map_editor.flood_fill(tile_x, tile_y)

    elif map_editor.tool == "info":
        log(4, "EDITOR", f"Tile {tile_x}, {tile_y}")

        # Get the ID of the tile at the mouse click coordinates
        tile_id = map_editor.get_tile_id(tile_x, tile_y)

        # Display info about this tile
        map_editor.tile_info(tile_id, tile_x, tile_y)

        map_editor.selected_tile_id = tile_id
        app.setLabel("ME_Selected_Tile_Position", f"[{tile_x}, {tile_y}]")

        if map_editor.is_dungeon() is False:
            # Find an NPC at this coordinates and show it in NPC editor
            npc_index = map_editor.find_npc(tile_x, tile_y)
            if npc_index > -1:
                # log(4, "EDITOR", f"Found NPC #{npc_index}")
                map_editor.npc_index = npc_index
                map_editor.npc_info(npc_index)
                app.setOptionBox("NPCE_Option_NPC_List", npc_index)
                app.showLabelFrame("NPCE_Frame_Info")
                # app.setButton("NPCE_Button_Create_Apply", "Apply Changes")

    elif map_editor.tool == "move_entrance":
        map_editor.select_tool("draw")
        if selected_entrance < 0 or len(app.getAllListItems("EE_List_Entrances")) < 1:
            return

        map_editor.change_entrance(selected_entrance, tile_x, tile_y)

    elif map_editor.tool == "move_moongate":
        map_editor.select_tool("draw")
        if selected_moongate < 0 or len(app.getAllListItems("EE_List_Moongates")) < 1:
            return

        map_editor.change_moongate(selected_moongate, tile_x, tile_y)

    elif map_editor.tool == "move_npc":
        map_editor.move_npc(tile_x, tile_y)
        # Select draw tool after we're done moving
        map_editor.select_tool("draw")


# --- npc_select_graphics() ---

def npc_select_graphics(option_box: str) -> None:
    """
    An item has been selected from the NPC Sprite Option Box in the NPC Editor sub-window

    Parameters
    ----------
    option_box: str
        Name of the widget generating the event, could be either the option box or the "static" checkbox
    """
    if option_box == "NPCE_Option_Graphics" or option_box == "NPCE_Option_Graphics":
        selection = int(app.getOptionBox("NPCE_Option_Graphics"), base=16)
        if app.getCheckBox("NPCE_Check_Static"):
            selection = selection | 0x80
        map_editor.select_npc_graphics(selection)

    elif option_box == "NPCE_Palette_1" or option_box == "NPCE_Palette_2":
        top = int(app.getOptionBox("NPCE_Palette_1"))
        if rom.has_feature("2-colour sprites"):
            bottom = int(app.getOptionBox("NPCE_Palette_2"))
        else:
            bottom = 0
        map_editor.change_npc_palettes(top, bottom)


# --- entrance_editor_press() ---

def entrance_editor_press(widget: str) -> None:
    """
    Callback function for presses/changes on widgets in the Entrance Editor sub-sub-window

    Parameters
    ----------
    widget: str
        Name of the widget that generated the event
    """
    global selected_entrance
    global selected_moongate

    _SELECTED = "#DFDFDF"
    _UNSELECTED = "#FFFFFF"

    # Click on Entrance Move Button
    if widget == "EE_Button_Entrance_Set":
        if selected_entrance > -1:
            map_editor.select_tool("move_entrance")

    # Click on Entrance Remove Button
    elif widget == "EE_Button_Entrance_Remove":
        if selected_entrance < 0 or len(app.getAllListItems("EE_List_Entrances")) < 1:
            return

        map_editor.change_entrance(selected_entrance, 0xFF, 0xFF)

    # Selected item from Entrances ListBox
    elif widget == "EE_List_Entrances":
        value = app.getListBoxPos(widget)
        if len(value):
            # If clicking on the already selected item, just jump to it on the map
            if value[0] == selected_entrance:
                point = map_editor.entrances[value[0]]
                map_editor.jump_to(point.x, point.y)

            else:
                # We change the background of the item as it will be deselected when clicking outside the list
                items: list = app.getAllListItems(widget)
                for pos in range(len(items)):
                    if pos == value[0]:
                        app.setListItemAtPosBg(widget, pos, _SELECTED)
                        selected_entrance = pos
                    else:
                        app.setListItemAtPosBg(widget, pos, _UNSELECTED)

                # Update the widgets to show info about this entrance
                map_editor.entrance_info(value[0])

    # Input new value in Entrance X / Y Entry Widget
    elif widget == "EE_Entrance_X" or widget == "EE_Entrance_Y":
        if selected_entrance < 0 or len(app.getAllListItems("EE_List_Entrances")) < 1:
            return

        try:
            new_x = int(app.getEntry("EE_Entrance_X"))
            new_y = int(app.getEntry("EE_Entrance_Y"))
            map_editor.change_entrance(selected_entrance, new_x, new_y)

        except ValueError:
            pass

    # Selected new condition for Moongates to show up
    elif widget == "EE_List_Moongates_Options":
        value = app.getOptionBox("EE_List_Moongates_Options")
        if value[0] == 'C':  # Continent maps only
            app.disableOptionBox("EE_Option_Moongates_Map")

        else:  # A specific map
            app.enableOptionBox("EE_Option_Moongates_Map")
            # Select the current map by default
            app.setOptionBox("EE_Option_Moongates_Map", index=map_editor.map_index, callFunction=False)

        # This will save the changes to the ROM buffer, and show/hide the Moongates accordingly
        map_editor.update_moongate_condition()

    # Selected item from Moongates ListBox
    elif widget == "EE_List_Moongates":
        value = app.getListBoxPos(widget)
        if len(value):
            # If clicking on the already selected item, just jump to it on the map
            if value[0] == selected_moongate:
                point = map_editor.moongates[value[0]]
                map_editor.jump_to(point.x, point.y)

            else:
                items: list = app.getAllListItems(widget)
                for pos in range(len(items)):
                    if pos == value[0]:
                        app.setListItemAtPosBg(widget, pos, _SELECTED)
                        selected_moongate = pos
                        map_editor.moongate_info(pos)
                    else:
                        app.setListItemAtPosBg(widget, pos, _UNSELECTED)

    # Mouse click on move Moongate button
    elif widget == "EE_Button_Moongate_Set":
        if 0 <= selected_moongate <= 8:
            map_editor.select_tool("move_moongate")

    # Mouse click on remove Moongate button
    elif widget == "EE_Button_Moongate_Remove":
        if selected_moongate < 0 or len(app.getAllListItems("EE_List_Moongates")) < 1:
            pass
        else:
            map_editor.change_moongate(selected_moongate, 0xFF, 0xFF)

    # Entered a new value for Moongate X
    elif widget == "EE_Moongate_X" or widget == "EE_Moongate_Y":
        if 0 <= selected_moongate <= 8:
            try:
                new_x = int(app.getEntry("EE_Moongate_X"))
                new_y = int(app.getEntry("EE_Moongate_Y"))
                map_editor.change_moongate(selected_moongate, new_x=new_x, new_y=new_y)
            except ValueError:
                # Invalid input: restore previous value
                # app.setEntry(widget, f"{map_editor.moongates[selected_moongate].x}", callFunction=False)
                pass

    # Selected a new tile for Dawn
    elif widget == "EE_Option_Dawn_Tile":
        new_tile_id = int(app.getOptionBox(widget), 16)
        map_editor.change_moongate(8, new_dawn_tile=new_tile_id)

    # Selected a new Moongate/Dawn replacement tile
    elif widget == "EE_Option_Moongate_Tile":
        if 0 <= selected_moongate <= 8:
            new_tile_id = int(app.getOptionBox(widget), 16)
            map_editor.change_moongate(selected_moongate, new_replacement_tile=new_tile_id)

    else:
        log(3, "ENTRANCE EDITOR", f"Unimplemented callback for widget '{widget}'.")


# --- encounter_input() ---

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


# --- enemy_editor_input() ---

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
            app.entry("ET_Sprite_Address", fg="#7F0000")
            return

        try:
            address = int(text, 16)
            if address < 0x8000 or address > 0xBFFF:
                # Out of range
                app.entry("ET_Sprite_Address", fg="#7F0000")
                return

            # Valid input: change address and reload sprite
            app.entry("ET_Sprite_Address", fg="#007F00")
            enemy_editor.change_sprite(sprite_address=address)

        except ValueError:
            # Not a valid hex value
            app.entry("ET_Sprite_Address", fg="#7F0000")
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


# --- select_palette() ---

def select_palette(sel: str) -> None:
    """
    An item has been selected from the palettes Option Box in the Palette Editor tab

    Parameters
    ----------
    sel: str
        Name of the Option Box widget
    """
    log(4, "EDITOR", f"Selected palette: {app.getOptionBox(sel)}")
    palette_set = app.getOptionBox(sel)
    palette_editor.choose_palette_set(palette_set)


# --- cycle_palette_sets() ---

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


# --- edit_colour() ---

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


# --- pick_colour() ---

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


# --- edit_text() ---

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

    text_editor.show_window(string_index, string_type)


# --- close_rom() ---

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
    for feature in range(9):
        app.hideCheckBox(f"Feature_{feature}")
    # Close all sub-windows
    app.hideAllSubWindows(False)
    # Deactivate all tabs
    app.setTabbedFrameDisabledTab("TabbedFrame", "Map", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Party", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Enemies", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Text", True)
    app.setTabbedFrameDisabledTab("TabbedFrame", "Palettes", True)
    app.setStatusbar("ROM file closed.", field=0)
    app.setTitle("UE Editor")


# --- save_rom() ---

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

    if rom.save(file_name) is True:
        file_name = os.path.basename(file_name)
        app.setStatusbar(f"Saved as '{file_name}'.")
    else:
        app.setStatusbar("Save operation failed.")
        app.errorBox("Export ROM", f"ERROR: Could not save to '{file_name}'.")


# --- open_rom() ---

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

    app.setStatusbar(f"Opening ROM file '{file_name}'", field=0)
    val = rom.open(file_name)
    if val != "OK":
        app.setStatusbar(val)
        app.errorBox("ERROR", val)
    else:
        app.setStatusbar(f"ROM file opened: '{file_name}'", field=0)
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

        # Create Editor instances
        palette_editor = PaletteEditor(rom, app)
        # Load palettes
        palette_editor.load_palettes()

        map_colours = []  # Portrait map_colours
        for c in range(4, 8):
            colour_index: int = palette_editor.palettes[0][c]
            colour = bytearray(palette_editor.get_colour(colour_index))
            map_colours.append(colour[0])  # Red
            map_colours.append(colour[1])  # Green
            map_colours.append(colour[2])  # Blue
        map_editor = MapEditor(rom, app, palette_editor)

        # This automatically loads text pointer tables and caches dialogue and special strings
        text_editor = TextEditor(rom, map_colours, app)

        # Read tables
        selected_map = 0
        update_map_table(map_editor.map_table[selected_map])
        map_compression = "LZSS"
        app.setOptionBox("Map_Compression", 1)

        update_text_table(app.getOptionBox("Text_Type"))

        # Read map location names from file
        # TODO Use different list instead of default one if name matches ROM file
        location_names: List[str] = []
        try:
            locations_file: TextIO = open("location_names.txt", "r")
            location_names = locations_file.readlines()
            locations_file.close()
        except IOError as error:
            log(3, "EDITOR", f"Error reading location names: {error}.")

        # Update map list for the correct maximum number of maps
        maps = []
        for m in range(0, map_editor.max_maps()):
            name = "(No Name)"
            if m < len(location_names):
                name = location_names[m].rstrip("\n\r\a")
                if len(name) > 16:  # Truncate names that are too long to be displayed correctly
                    name = name[:15] + '-'
            maps.append(f"0x{m:02X} {name}")
        app.changeOptionBox("MapInfo_Select", maps)
        app.clearOptionBox("MapInfo_Select", callFunction=True)

        # Use the same list with names for the Moongate map selection
        app.changeOptionBox("EE_Option_Moongates_Map", maps)
        app.clearOptionBox("EE_Option_Moongates_Map", callFunction=False)

        # Enemy data
        enemy_editor = EnemyEditor(app, rom, palette_editor)
        enemy_editor.read_encounters_table()
        enemy_editor.read_enemy_data(text_editor)

        app.hideFrame("ET_Frame_Enemy")
        app.hideFrame("ET_Frame_Encounter")

        # Party editor
        party_editor = PartyEditor(app, rom, text_editor, palette_editor)

        # Activate tabs
        app.setTabbedFrameDisabledTab("TabbedFrame", "Map", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Party", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Enemies", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Text", False)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Palettes", False)

        # Add file name to the window's title
        app.setTitle(f"UE Editor - {os.path.basename(file_name)}")


# --- update_map_table() ---

def update_map_table(map_data: MapTableEntry) -> None:
    """
    Updates the widgets in the Map Editor Tab

    Parameters
    ----------
    map_data: MapTableEntry
        Data to show
    """
    app.setEntry("MapInfo_Bank", f"0x{map_data.bank:02X}", False)
    app.setEntry("MapInfo_DataPtr", f"0x{map_data.data_pointer:04X}", False)

    # Get index of selected map

    try:
        map_index = int(app.getOptionBox("MapInfo_Select")[:4], base=16)
    except IndexError:
        value = app.getOptionBox("MapInfo_Select")
        log(3, "EDITOR", f"Error getting map index from: '{value}'.")
        map_index = 0

    # Basic info

    # In v1.09+, the map type depends on its flags entirely

    if map_editor.max_maps() > 26:

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

    app.setOptionBox("MapInfo_Basic_Type", map_type)

    if 0 <= map_data.bank <= 0xF:
        app.setOptionBox("MapInfo_Basic_Bank", map_data.bank)
    else:
        # Defaults based on type: dungeons on bank 2, anything else bank 0
        if map_data.flags & 0x80 != 0:
            app.setOptionBox("MapInfo_Basic_Bank", 2)
        else:
            app.setOptionBox("MapInfo_Basic_Bank", 0)

    map_id = map_data.flags & 0x1F
    app.setSpinBox("MapInfo_Basic_ID", map_id, callFunction=False)

    # Advanced info

    # For dungeon maps, the low byte is actually the facing direction
    # ...but only for version 1.09+, so we need to detect that based on the entry table address
    if map_editor.max_maps() > 26:
        if map_editor.is_dungeon(selected_map):
            app.setLabel("MapInfo_h2", "Facing dir.:")
        else:
            app.setLabel("MapInfo_h2", "NPC Table:")
    app.setEntry("MapInfo_NPCPtr", f"0x{map_data.npc_pointer:04X}", False)

    app.setEntry("MapInfo_EntryX", f"{map_data.entry_x}", False)
    app.setEntry("MapInfo_EntryY", f"{map_data.entry_y}", False)
    app.setEntry("MapInfo_Flags", f"0x{map_data.flags:02X}", False)


# --- select_map() ---

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

    selected_map = int(app.getOptionBox(sel)[:4], 16)
    log(4, "EDITOR", f"Selected map# {selected_map}")

    map_data = map_editor.map_table[selected_map]

    # Display data for the selected map
    update_map_table(map_data)

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


# --- select_compression() ---

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


# --- text_editor_stop() ---

def text_editor_stop() -> bool:
    """
    Callback: request to close the Text Editor sub-window

    Returns
    -------
    bool
        True if the window has been closed, False if the action has been cancelled
    """
    if text_editor.hide_window() is False:
        # Re-focus Text Editor sub-window
        app.showSubWindow("Text_Editor")
        return False

    # Reload currently selected string if the text tab is active
    if app.getTabbedFrameSelectedTab("TabbedFrame") == "Text":
        app.selectListItemAtPos("Text_Id", text_editor.index, callFunction=True)

    return True


# --- text_editor_press() ---

def text_editor_press(widget: str) -> None:
    """
    Button press callback for the Text Editor sub-window

    Parameters
    ----------
    widget: str
        Name of the Button widget being pressed
    """
    if widget == "Text_Apply":
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
        if text_editor.index >= 0:
            app.selectListItemAtPos("Text_Id", text_editor.index, callFunction=True)

    elif widget == "TE_Button_Close":
        text_editor.hide_window(False)

        # Reload currently selected string if the text tab is active
        if app.getTabbedFrameSelectedTab("TabbedFrame") == "Text":
            app.selectListItemAtPos("Text_Id", text_editor.index, callFunction=True)

    elif widget == "TE_Button_Reload_Text":
        # Get address from input widget
        address_string = ""
        try:
            address_string = app.getEntry("TE_Entry_Address")
            new_address = int(address_string, 16)

            if text_editor.type == "Dialogue" or text_editor.type == "Special":
                # Try to unpack the string at the new address
                new_string = text_editor.unpack_text(rom, new_address)

                # TODO Add code for NPC and Enemy Names
            else:
                new_string = ""

            # Update the output widget with the new text
            app.clearTextArea("TE_Text")
            app.setTextArea("TE_Text", new_string)

            # Set the new text and address variables in the Text Editor
            text_editor.text = new_string
            text_editor.address = new_address
            text_editor.changed = True
        except ValueError:
            app.errorBox("ERROR", f"Invalid address '{address_string}'.\n"
                                  "Please only enter numbers, in hexadecimal format.",
                         "Text_Editor")

    elif widget == "TE_Button_Accept":
        # Get new text and address
        new_text: str = app.getTextArea("TE_Text")
        if text_editor.type == "Dialogue" or text_editor.type == "Special":
            try:
                new_name: int = ast.literal_eval(app.getOptionBox("TE_Option_Name")[:6])
                new_portrait = int(app.getOptionBox("TE_Option_Portrait")[:2])
            except SyntaxError:
                value = app.getOptionBox("TE_Option_Name")[:6]
                log(3, "TEXT EDITOR", f"Could not convert value from '{value}'.")
                new_name = -1
                new_portrait = -1
        else:
            new_portrait = -1
            new_name = -1
        try:
            new_address = int(app.getEntry("TE_Entry_Address"), 16)
        except ValueError:
            value = app.getEntry('TE_Entry_Address')
            app.errorBox("Invalid Value", f"The address specified ('{value}') is not valid.\n"
                                          "Please only use hexadecimal numbers in the format '0x1234'.", "Text_Editor")
            return

        # TODO Update address in the items list

        text_editor.modify_text(new_text, new_address, new_portrait, new_name)
        # Hide window
        app.hideSubWindow("Text_Editor", useStopFunction=False)

        # Save changes to ROM
        text_editor_press("Text_Apply")
        # Refresh current string if the text tab is active
        # if app.getTabbedFrameSelectedTab("TabbedFrame") == "Text":
        #    app.selectListItemAtPos("Text_Id", text_editor.index, callFunction=True)

    else:
        print(f"Unimplemented Text Editor button: {widget}")


# --- select_text_type() ---

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


# --- update_text_table() ---

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

    elif text_type == "Choose Type":
        pass

    else:
        log(3, "EDITOR", f"update_text_table: Unimplemented text type '{text_type}'.")

    app.clearListBox("Text_Id")
    app.updateListBox("Text_Id", strings_list)


# --- save_text() ---

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
        text_type = app.getListBox("Text_Type")

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


# --- select_text_id() ---

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


# --- select_portrait() ---

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


# --- party_editor_press() ---

def party_editor_press(button: str) -> bool:
    if button == "PT_Button_Races":
        party_editor.show_window("Races")

    elif button == "PT_Button_Professions":
        party_editor.show_window("Professions")

    elif button == "PT_Button_Pre-Made":
        party_editor.show_window("Pre-Made")

    else:
        log(3, "PARTY_EDITOR", f"Unimplemented button '{button}'.")

    return True


# --- party_editor_stop() ---
def party_editor_stop() -> bool:
    return party_editor.close_window()


# --- press() ---

# noinspection PyArgumentList
def press(widget: str) -> bool:
    """
    Generic button press callback for the main window

    Parameters
    ----------
    widget: str
        Name of the Button widget
    """
    global emulator_pid

    if widget == "Open ROM":
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

    elif widget == "Save ROM":
        # Check if a file is currently open
        if rom.path is None or len(rom.path) < 1:
            app.warningBox("Save ROM", "You need to open a ROM file first.")
            return True

        save_rom(rom.path)

    elif widget == "Save ROM As...":
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

    elif widget == "Close ROM":
        close_rom()

    elif widget == "About":
        app.infoBox("About", f"Ultima: Exodus Editor\nVersion {__version__}.")

    elif widget == "Exit":
        # TODO Ask to save changes if any
        close_rom()
        app.stop()

    elif widget == "Start Emulator":
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
                app.setStatusbar("Emulator process started")

        else:
            app.setStatusbar("Emulator launch failed!")
            app.warningBox("Launch Emulator", f"Invalid emulator path '{path}'.\n"
                                              "Please go to Settings and choose the correct path.")

    elif widget == "Map_Edit":
        edit_map()

    elif widget == "MapInfo_Advanced_Option":
        value = app.getRadioButton(widget)
        if value == "Basic":
            app.showFrame("MapInfo_Frame_Basic")
            app.hideFrame("MapInfo_Frame_Advanced")
        else:
            app.hideFrame("MapInfo_Frame_Basic")
            app.showFrame("MapInfo_Frame_Advanced")

    elif widget == "MapInfo_Basic_Bank":
        # Update bank number in Advanced view
        value = int(app.getOptionBox(widget))
        app.setEntry("MapInfo_Bank", f"0x{value:02X}")

    elif widget == "MapInfo_Basic_Type" or widget == "MapInfo_Basic_ID":
        # Update flags/ID in Advanced view
        try:
            flags = int(app.getOptionBox("MapInfo_Basic_Type")[0])
            id_value = int(app.getSpinBox("MapInfo_Basic_ID"))
            value = flags << 4 | id_value
            app.setEntry("MapInfo_Flags", f"0x{value:02X}")
        except ValueError:
            pass

    else:
        log(3, "EDITOR", f"Unimplemented button: {widget}")
        return False

    return True


# --- editor_stop() ---

def editor_stop() -> bool:
    # TODO Ask for confirmation if there are unsaved changes
    # Save settings
    settings.save()
    return True


# --- MAIN ---

if __name__ == "__main__":

    # Try to load editor settings
    settings.load()

    # --- GUI Elements ---

    with gui("UE Editor", "492x344", bg='#FFFFF0', resizable=False) as app:
        print(app.SHOW_VERSION())
        # noinspection PyArgumentList
        app.setIcon(image="res/app-icon.ico")
        # noinspection PyArgumentList
        app.setStopFunction(editor_stop)
        app.setFont(family=settings.get("editor fonts"), underline=False, size=12)

        #       ##### Toolbar #####

        tools = ["Open ROM", "Close ROM", "Save ROM", "Save ROM As...", "Start Emulator", "Settings", "About", "Exit"]
        app.addToolbar(tools, press, True)
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
            with app.labelFrame("ROM Info", padding=[2, 0], row=0, column=0, stretch='BOTH', sticky='NEWS'):
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
                for f in range(9):
                    app.checkBox(f"Feature_{f}", name=feature_names[f], value=False, row=f, column=0, font=9)
                    app.disableCheckBox(f"Feature_{f}")
                    app.hideCheckBox(f"Feature_{f}")

        # MAP Tab ------------------------------------------------------------------------------------------------------
        with app.tab("Map", padding=[4, 0]):

            maps_list = list()
            for i in range(0, 0x1A):
                maps_list.append(f"0x{i:02X}")

            with app.frame("Map_TopFrame", row=0, column=0, sticky='NEW', stretch='BOTH', bg="#DFCFCF"):
                app.label("MapInfo_SelectLabel", value="Map:", row=0, column=0, sticky='E')
                app.optionBox("MapInfo_Select", maps_list, change=select_map, sticky='WE', width=20,
                              stretch='ROW', row=0, column=1, font=11)
                app.radioButton("MapInfo_Advanced_Option", "Basic", change=press, row=0, column=2, sticky="E")
                app.radioButton("MapInfo_Advanced_Option", "Advanced", change=press, row=0, column=3, sticky="W")

            with app.frame("Map_MidFrame", row=1, column=0, sticky='NEW', stretch='BOTH', bg="#CFCFDF"):

                # Basic info
                with app.frame("MapInfo_Frame_Basic", row=0, column=0, padding=[8, 0], stretch='BOTH'):
                    app.label("MapInfo_Basic_h0", "Map type: ", sticky='E', row=0, column=0, colspan=2)
                    app.optionBox("MapInfo_Basic_Type", ["6: Continent (No Guards)", "2: Continent (w/Guards)",
                                                         "4: Town / Castle (No Guards)", "0: Town / Castle (w/Guards)",
                                                         "8: Dungeon"], width=26, sticky='W', row=0, column=2,
                                  colspan=2, change=press, font=11)

                    app.label("MapInfo_Basic_h1", "Bank: ", sticky='E', row=1, column=0)
                    banks_list = []
                    for i in range(0, 16):
                        banks_list.append(f"{i}")
                    app.optionBox("MapInfo_Basic_Bank", banks_list, sticky='W', row=1, column=1,
                                  change=press)
                    del banks_list

                    app.label("MapInfo_Basic_h2", "ID: ", sticky='E', row=1, column=2)
                    app.spinBox("MapInfo_Basic_ID", list(range(31, -1, -1)), change=press, row=1, column=3)

                # Advanced info
                with app.frame("MapInfo_Frame_Advanced", row=1, column=0, padding=[8, 0], stretch='BOTH'):
                    app.label("MapInfo_h0", value="Bank Number", row=0, column=0, sticky='NEW', stretch='ROW')
                    app.label("MapInfo_h1", value="Data Address", row=0, column=1, sticky='NEW', stretch='ROW')
                    app.label("MapInfo_h2", value="NPC Table", row=0, column=2, sticky='NEW', stretch='ROW')

                    # Map bank number
                    app.entry("MapInfo_Bank", row=1, column=0, stretch='ROW', sticky='NEW', width=12)
                    # Map data address
                    app.entry("MapInfo_DataPtr", row=1, column=1, stretch='ROW', sticky='NEW', width=12)
                    # NPC table address / starting facing position in a dungeon (v1.09+)
                    app.entry("MapInfo_NPCPtr", row=1, column=2, stretch='ROW', sticky='NEW', width=12)
                    app.label("MapInfo_h3", value="Party Entry X, Y", row=2, sticky='NEW', column=0, colspan=2,
                              stretch='ROW')
                    app.label("MapInfo_h4", value="Flags/ID", row=2, column=2, sticky='NEW', stretch='ROW')
                    # Party entry coordinates
                    app.entry("MapInfo_EntryX", row=3, column=0, stretch='ROW', sticky='NEW', width=12)
                    app.entry("MapInfo_EntryY", row=3, column=1, stretch='ROW', sticky='NEW', width=12)
                    # Flags / ID
                    app.entry("MapInfo_Flags", row=3, column=2, stretch='ROW', sticky='NEW', width=12)

            # Show "Basic" info by default
            app.setRadioButton("MapInfo_Advanced_Option", "Basic", callFunction=False)
            app.hideFrame("MapInfo_Frame_Advanced")

            with app.frame("Map_BtmFrame", row=4, column=0, sticky='NEWS', stretch='BOTH', padding=[4, 8],
                           bg="#CFDFCF"):
                app.button("Map_Apply", name="Apply Changes", value=press, sticky='NEW', row=0, column=0)
                app.button("Map_Edit", name="Edit Map", value=press, sticky='NEW', row=0, column=1)
                app.label("MapInfo_SelectCompression", "Compression:", sticky='NEW', row=0, column=2)
                app.optionBox("Map_Compression", ["none", "LZSS", "RLE"], change=select_compression, sticky='NEW',
                              callFunction=True, row=0, column=3)

        # PARTY Tab ----------------------------------------------------------------------------------------------------
        with app.tab("Party"):
            # Row 0
            app.button("PT_Button_Races", name="Races", value=party_editor_press, sticky='NEWS', row=0, column=0)
            app.button("PT_Button_Professions", name="Professions", value=party_editor_press,  sticky='NEWS',
                       row=0, column=1)
            # Row 1
            app.button("PT_Button_Pre-Made", name="Pre-Made\nCharacters", value=party_editor_press,  sticky='NEWS',
                       row=1, column=0)
            app.button("PT_Button_Items", name="Items", value=party_editor_press,  sticky='NEWS', row=1, column=1)
            # Row 2
            app.button("PT_Button_Magic", name="Magic", value=party_editor_press,  sticky='NEWS', row=2, column=0)
            app.button("PT_Button_Special", name="Special\nAbilities", value=party_editor_press, sticky='NEWS',
                       row=2, column=1)

        # ENEMIES Tab --------------------------------------------------------------------------------------------------
        with app.tab("Enemies", padding=[0, 0]):
            # Left
            with app.frame("ET_Frame_Left", bg="#F0F7F7", stretch='BOTH', sticky='NWS', row=0, column=0):
                app.optionBox("ET_Option_Enemies", ["- Select an Enemy -", "0x00"], row=0, column=0,
                              width=22, change=enemy_editor_input, stretch='ROW', sticky='EW')

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
            with app.frame("ET_Frame_Enemy", bg="#F7F7F0", stretch='BOTH', sticky='NEWS', row=0, column=1):
                # Row 0
                app.label("ET_Label_h1", "Gfx Addr.:", sticky='NEW', row=0, column=0)
                app.checkBox("ET_Big_Sprite", name="4x4 Sprite", change=enemy_editor_input, row=0, column=1)
                # Row 1 - sprite
                app.entry("ET_Sprite_Address", value="0x0000", change=enemy_editor_input, width=5, fg="#007F00",
                          row=1, column=0)
                app.canvas("ET_Canvas_Sprite", map=None, width=32, height=32, sticky='NEW', bg="#CFCFCF",
                           row=1, column=1)
                # Row 2 - HP
                app.label("ET_Label_HP", "Base HP:", sticky='NEW', row=2, column=0)
                app.entry("ET_Base_HP", "0", change=enemy_editor_input, sticky='NEW', row=2, width=4, column=1)
                # Row 3 - XP
                app.label("ET_Label_XP", "Base XP:", sticky='NEW', row=3, column=0)
                app.entry("ET_Base_XP", "0", change=enemy_editor_input, sticky='NEW', width=4, row=3, column=1)
                # Rows 4, 5, 6 - colours
                # Colour selection, for vanilla game
                colours: List[str] = []
                for i in range(0x40):
                    colours.append(f"0x{i:02X}")
                app.label("ET_Label_Colour_1", "Colour 1", sticky='NEW', row=4, column=0)
                app.optionBox("ET_Colour_1", colours, change=enemy_editor_input, sticky='NEW', width=4,
                              row=4, column=1)
                app.label("ET_Label_Colour_2", "Colour 2", sticky='NEW', row=5, column=0)
                app.optionBox("ET_Colour_2", colours, change=enemy_editor_input, sticky='NEW', width=4,
                              row=5, column=1)
                app.label("ET_Label_Colour_3", "Colour 3", sticky='NEW', row=6, column=0)
                app.optionBox("ET_Colour_3", colours, change=enemy_editor_input, sticky='NEW', width=4,
                              row=6, column=1)
                # Palette selection, for hacked game
                app.optionBox("ET_Palette_1", ["00", "01", "02", "03"], change=enemy_editor_input,
                              sticky='NEW', width=4, row=4, column=1)
                app.optionBox("ET_Palette_2", ["00", "01", "02", "03"], change=enemy_editor_input,
                              sticky='NEW', width=4, row=5, column=1)
                # Row 7 - abilities
                app.label("ET_Label_Ability", "Ability:", sticky='NEW', row=7, column=0)
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
            with app.frame("ET_Frame_Encounter", bg="#F0F0F7", stretch='BOTH', sticky='NEWS', row=0, column=2):
                app.label("ET_Label_Level", "Level/Type", row=0, column=0)
                app.label("ET_Label_h3", "Encounters Table #0", row=1, column=0)
                with app.frame("ET_Frame_Encounters_List", sticky='NEW', padding=[4, 4], row=2, column=0):
                    app.entry("ET_Encounter_0", "0x00", change=encounter_input, width=4, row=0, column=1)
                    app.entry("ET_Encounter_1", "0x00", change=encounter_input, width=4, row=0, column=2)
                    app.entry("ET_Encounter_2", "0x00", change=encounter_input, width=4, row=0, column=3)
                    app.entry("ET_Encounter_3", "0x00", change=encounter_input, width=4, row=0, column=4)
                    app.entry("ET_Encounter_4", "0x00", change=encounter_input, width=4, row=1, column=1)
                    app.entry("ET_Encounter_5", "0x00", change=encounter_input, width=4, row=1, column=2)
                    app.entry("ET_Encounter_6", "0x00", change=encounter_input, width=4, row=1, column=3)
                    app.entry("ET_Encounter_7", "0x00", change=encounter_input, width=4, row=1, column=4)
                with app.labelFrame("ET_Frame_Special", name="Special", sticky='NEW', padding=[2, 2], row=3, column=0):
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
            with app.frame("TextEditor_Left", row=0, column=0, padding=[2, 2], inPadding=[0, 0],
                           sticky='NW', bg="#AFBFAF"):
                app.label("TextEditor_Type", "Text Preview:", row=0, column=0, sticky='NW', stretch='NONE', font=10)
                app.textArea("Text_Preview", row=1, column=0, colspan=2, sticky='NEW', stretch='ROW', scroll=True,
                             end=False, height=10, rowspan=2).setFont(family="Consolas", size=11)
                app.button("Text_Apply", name="Apply Changes", value=text_editor_press, row=3, column=0,
                           sticky='NW', stretch='NONE')
                app.button("Text_More", name="More Actions", value=edit_text, row=3, column=1, sticky='NW',
                           stretch='NONE')

            with app.frame("TextEditor_Right", row=0, column=1, sticky='NE', padding=[2, 2], bg="#BFBFAF"):
                app.optionBox("Text_Type", ["Choose Type", "Dialogue", "Special", "NPC Names", "Enemy Names",
                                            "Menus / Intro"],
                              change=select_text_type, row=0, column=4, sticky='NW', colspan=2, stretch='NONE',
                              bg="#CFCFBF")
                app.listBox("Text_Id", value=[], change=select_text_id, row=1, column=4, sticky='NE',
                            stretch='NONE', bg="#EFEFEF")

        # PALETTES Tab -------------------------------------------------------------------------------------------------
        with app.tab("Palettes", padding=[4, 2]):

            with app.frame("PE_Frame_List", row=0, column=0, padding=[2, 0], bg="#EFDFDF"):
                app.label("PE_Label_Select", "Select a palette set:", row=0, column=0)
                app.optionBox("PE_List_Palettes", ["Intro / Credits", "Title", "Status Screen", "Flashing",
                                                   "End Sequence", "Map Default", "Ambrosia", "Dungeon",
                                                   "Continent View"],
                              change=select_palette, row=0, column=1)

            with app.frame("PE_Frame_Palettes", row=1, column=0, padding=[0, 2], stretch='BOTH', sticky='NEWS',
                           bg="#DFEFDF"):
                app.button("PE_Palette_Prev", name=" << Prev ", row=0, column=0, stretch='NONE',
                           command=lambda: cycle_palette_sets(0))
                app.label("PE_Label_0", "Palette 0:", row=0, column=1, stretch='COLUMN')
                app.button("PE_Palette_Next", name=" Next >> ", row=0, column=2, stretch='NONE',
                           command=lambda: cycle_palette_sets(1))

            with app.frame("PE_Frame_Sub_Palette", row=2, column=0, padding=[8, 0], stretch='COLUMN', sticky='NEWS',
                           bg="#DFEFDF"):
                app.canvas("PE_Canvas_Palette_0", row=0, column=0, width=65, height=17, stretch='NONE', map=None,
                           bg="#000000").bind(
                    "<Button-1>", lambda event: edit_colour(event, 0), add="+")
                app.canvas("PE_Canvas_Palette_1", row=0, column=1, width=65, height=17, stretch='NONE', map=None,
                           bg="#000000").bind(
                    "<Button-1>", lambda event: edit_colour(event, 1), add="+")
                app.canvas("PE_Canvas_Palette_2", row=0, column=2, width=65, height=17, stretch='NONE', map=None,
                           bg="#000000").bind(
                    "<Button-1>", lambda event: edit_colour(event, 2), add="+")
                app.canvas("PE_Canvas_Palette_3", row=0, column=3, width=65, height=17, stretch='NONE', map=None,
                           bg="#000000").bind(
                    "<Button-1>", lambda event: edit_colour(event, 3), add="+")
                app.setCanvasCursor("PE_Canvas_Palette_0", "pencil")
                app.setCanvasCursor("PE_Canvas_Palette_1", "pencil")
                app.setCanvasCursor("PE_Canvas_Palette_2", "pencil")
                app.setCanvasCursor("PE_Canvas_Palette_3", "pencil")

            with app.frame("PE_Frame_Full", row=3, column=0, colspan=2, padding=[2, 0], stretch='BOTH', bg="#DFEFEF"):
                # Full NES palette
                app.canvas("PE_Canvas_Full", row=0, column=0, width=257, height=65, stretch='NONE', map=None,
                           bg="#000000",
                           sticky='EW').bind("<Button-1>", pick_colour, add="+")
                app.setCanvasCursor("PE_Canvas_Full", "hand1")

        # SFX / MUSIC Tab ----------------------------------------------------------------------------------------------
        with app.tab("SFX/Music", padding=[4, 2]):
            app.button("SFX", row=0, column=0)
            app.button("Music", row=1, column=0)

        #       ##### End of tab definitions #####
        app.stopTabbedFrame()

        # Deactivate tabs until ROM is loaded
        app.setTabbedFrameDisabledTab("TabbedFrame", "Map", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Party", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Enemies", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Text", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "Palettes", True)
        app.setTabbedFrameDisabledTab("TabbedFrame", "SFX/Music", True)

        # Status bar
        app.statusFont = 9
        app.addStatusbar(fields=1)
        app.setStatusbar("Open a ROM file to begin...", field=0)

        #       ##### Sub-Windows #####

        # Party Editor Sub-Window --------------------------------------------------------------------------------------
        with app.subWindow("Party_Editor", title="Party Editor", size=[360, 240], modal=False, resizable=False,
                           padding=0, inPadding=0, guiPadding=0, bg="#C0C0B0"):
            # noinspection PyArgumentList
            app.setStopFunction(party_editor_stop)

            app.label("PE_Label_p0", "")

        # Map Editor Sub-Window ----------------------------------------------------------------------------------------
        with app.subWindow("Map_Editor", "Map Editor", size=[512, 480], modal=False, resizable=False, padding=0,
                           inPadding=0, guiPadding=0, bg="#A0A0A0"):

            # noinspection PyArgumentList
            app.setStopFunction(map_editor_stop)

            # Buttons
            with app.frame("ME_Frame_Buttons", row=0, column=0, padding=[4, 0], sticky='NEW', stretch='ROW'):

                app.button("MapEditor_Import", name="Import", value=map_editor_input, image="res/import.gif",
                           tooltip="Import from File", row=0, column=0)
                app.button("MapEditor_Export", name="Export", value=map_editor_input, image="res/export.gif",
                           tooltip="Export to File", row=0, column=1)
                app.button("MapEditor_Save", name="Save Changes", value=map_editor_input, image="res/floppy.gif",
                           tooltip="Close and Apply Changes", row=0, column=2)
                app.button("MapEditor_Discard", name="Discard Changes", value=map_editor_stop, image="res/close.gif",
                           tooltip="Close and Discard Changes", row=0, column=3)

            # Tile picker / toolbox
            with app.frame("ME_Frame_Tile_Picker", row=1, column=0, padding=[4, 0], stretch='COLUMN', sticky='EW',
                           bg="#3F3F3F"):

                app.button("ME_Button_Draw", map_editor_input, name="Draw", image="res/pencil.gif",
                           tooltip="Draw", height=32, row=0, column=0)
                app.button("ME_Button_Fill", map_editor_input, name="Fill", image="res/bucket.gif",
                           tooltip="Flood Fill", height=32, row=0, column=1)
                app.button("ME_Button_Clear", map_editor_input, name="Clear", image="res/eraser.gif",
                           tooltip="Clear Map", height=32, row=0, column=2)
                app.button("ME_Button_Info", map_editor_input, name="Info", image="res/zoom.gif",
                           tooltip="Tile Info", height=32, row=0, column=3)
                app.canvas("ME_Canvas_Tiles", row=0, column=4, width=128, height=32, stretch='NONE', map=None,
                           bg="black").bind("<Button-1>", map_editor_pick_tile, add="+")
                app.setCanvasCursor("ME_Canvas_Tiles", "hand2")

            # Tile info frame
            with app.labelFrame("Tile Info", row=2, column=0, bg="#7F7F8F", stretch='BOTH', sticky='EW'):
                app.canvas("ME_Canvas_Selected_Tile", row=0, column=0, width=16, height=16, stretch='NONE', map=None,
                           bg="#7F7F8F")
                app.label("ME_Selected_Tile_Name", "", row=0, column=1)
                app.label("ME_Selected_Tile_Properties", "", row=0, column=2)
                app.label("ME_Selected_Tile_Position", "", row=0, column=3)

                # Special tile info
                with app.frame("ME_Frame_Special_Tile", row=0, column=4, padding=[8, 0]):
                    app.label("ME_Special_Tile_Name", "Special", row=0, column=0)
                    app.optionBox("ME_Special_Tile_Value", ["", "", "", ""], row=0, column=1, width=10,
                                  change=select_dungeon_special_type)

            # Colours and special options
            with app.frame("ME_Frame_Map_Options", row=3, column=0, padding=[4, 4], stretch='ROW', sticky='EW'):
                # Column 0
                app.label("Map-specific colours:", row=0, column=0, sticky='E')
                # Column 1
                values: List[str] = []
                for i in range(9):
                    values.append(f"0x{i:02X}")
                app.optionBox("ME_Option_Map_Colours", values, row=0, column=1, width=4, sticky='W',
                              change=map_editor_input)
                del values
                # Column 2
                app.canvas("ME_Canvas_Map_Colours", width=35, height=18, row=0, column=2, stretch='NONE',
                           map=None, bg="#000000")

            # Map Canvas
            with app.scrollPane("ME_Scroll_Pane", row=4, column=0, stretch='BOTH', padding=[0, 0], sticky='NEWS'):
                # Map Canvas
                app.canvas("ME_Canvas_Map", row=0, column=0, width=1024, height=1024, map=None,
                           bg="black").bind("<Button-1>", map_editor_edit_tile, add="+")

                # Dungeon tools
                with app.frame("ME_Frame_Dungeon_Tools", row=0, column=1, padding=[8, 0], sticky='SEWN',
                               stretch='COLUMN', bg="#9F9F7F"):
                    # Dungeon tools Row #0
                    app.label("ME_Label_Dungeon_Level", "Floor:", row=0, column=0)
                    # Dungeon tools Row #1
                    app.optionBox("ME_Option_Dungeon_Level", [" 1 ", " 2 ", " 3 ", " 4 ", " 5 ", " 6 ", " 7 ", " 8 "],
                                  change=select_dungeon_level, row=1, column=0, stretch='NONE', sticky='NEW')
                    # Dungeon tools Row #2
                    app.label("ME_Label_Dungeon_Message", "Message Sign:", row=2, column=0, font=9)
                    # Dungeon tools Row #3
                    app.textArea("ME_Text_Dungeon_Message", "", row=3, column=0, sticky='WE', height=5, scroll=True,
                                 width=12, change=change_dungeon_message).setFont(size=9)
                    # Dungeon tools Row #4
                    app.label("ME_Label_Marks_Count", "Marks: 0", row=4, column=0, width=10,
                              stretch='NONE', sticky='NEW', font=9)
                    # Dungeon tools Row #5
                    app.label("ME_Label_Fountains_Count", "Fountains: 0", row=5, column=0, width=10,
                              stretch='NONE', sticky='NEW', font=9)
                    # Dungeon tools Row #6
                    app.checkBox("ME_Auto_Ladders", text="Auto-Ladder", value=True, row=6, column=0,
                                 tooltip="Automatically create corresponding ladder on the connecting floor",
                                 font=9)

            # Progress Sub-Sub-Window ----------------------------------------------------------------------------------
            with app.subWindow("Map_Progress", title="Redraw Map", modal=True, size=[300, 100], padding=[4, 4],
                               bg="#F0E0C0"):
                # noinspection PyArgumentList
                app.setStopFunction(no_stop)

                app.label("Progress_Label", "Please wait...", row=0, column=0, stretch='ROW', sticky='WE',
                          font=16)
                app.meter("ME_Progress_Meter", value=0, row=1, column=0, stretch='BOTH', sticky='WE', fill="#9090F0")

            # Entrance / Moongate Editor Sub-Sub-Window ----------------------------------------------------------------
            with app.subWindow("Entrance_Editor", "Entrances / Moongates", size=[256, 440], modal=False,
                               resizable=False, bg="#DFD7D0"):
                # noinspection PyArgumentList
                app.setStopFunction(map_editor_stop)

                # Entrances frame
                with app.labelFrame("EE_Frame_Entrances", name="Entrances", row=0, column=0, stretch='ROW',
                                    sticky='NEW'):
                    # Column 0
                    app.listBox("EE_List_Entrances", list(range(22)), change=entrance_editor_press, row=0, column=0,
                                width=16, font=10)

                    # Column 1
                    with app.frame("EE_Frame_Entrance_Tools", padding=[1, 1], row=0, column=1):
                        # Row 0
                        app.button("EE_Button_Entrance_Set", name="Move", image="res/target.gif", row=0, column=0,
                                   value=entrance_editor_press, tooltip="Pick new coordinates from the map")
                        app.button("EE_Button_Entrance_Remove", name="Delete", image="res/eraser.gif", row=0, column=1,
                                   value=entrance_editor_press, tooltip="Clear this entrance (moves it off map)")
                        # Row 1
                        app.label("EE_Label_h2", "X:", row=1, column=0, font=9)
                        app.label("EE_Label_h3", "Y:", row=1, column=1, font=9)
                        # Row 2
                        app.entry("EE_Entrance_X", value=255, width=4, row=2, column=0, change=entrance_editor_press,
                                  font=9)
                        app.entry("EE_Entrance_Y", value=255, width=4, row=2, column=1, change=entrance_editor_press,
                                  font=9)
                        # Row 3
                        app.label("EE_Label_h4", "Map:", row=3, column=0, font=9)
                        app.label("EE_Entrance_Map", "0x00", width=4, row=3, column=1, font=9)

                # Moongates frame
                with app.labelFrame("EE_Frame_Moongates", name="Moongates", row=1, column=0, stretch='BOTH',
                                    expand='BOTH', sticky='SEWN'):
                    # Column 0
                    with app.frame("EE_Frame_Moongate_List", row=0, column=0):
                        # Row 0
                        app.listBox("EE_List_Moongates", list(range(9)), change=entrance_editor_press, row=0, column=0,
                                    colspan=2, width=10, height=6, font=10)
                        # Row 1
                        app.label("EE_Label_h10", "Dawn tile:", stretch='BOTH', sticky='NEWS', row=1, column=0, font=9)
                        app.canvas("EE_Canvas_Dawn_Tile", width=16, height=16, bg="#000000", map=None,
                                   stretch='BOTH', sticky='W', row=1, column=1)
                        # Row 2
                        app.optionBox("EE_Option_Dawn_Tile", tiles_list, change=entrance_editor_press, row=2, column=0,
                                      colspan=2, sticky='EW', font=9)
                        # Row 3
                        app.label("EE_Label_h9", "Active on:", row=3, column=0, colspan=2, font=9)
                        # Row 4
                        app.optionBox("EE_List_Moongates_Options", ["Continent maps", "A specific map"],
                                      change=entrance_editor_press,
                                      row=4, column=0, colspan=2, sticky='EW', font=9)
                        # Row 5
                        app.optionBox("EE_Option_Moongates_Map", maps_list, row=5, column=0, colspan=2,
                                      sticky='EW', change=entrance_editor_press, font=9)

                    # Column 1
                    with app.frame("EE_Frame_Moongate_Tools", padding=[1, 1], row=0, column=1):
                        # Row 0
                        app.button("EE_Button_Moongate_Set", name="Move", image="res/target.gif", row=0, column=0,
                                   value=entrance_editor_press, tooltip="Pick new coordinates from the map")
                        app.button("EE_Button_Moongate_Remove", name="Delete", image="res/eraser.gif", row=0, column=1,
                                   value=entrance_editor_press, tooltip="Clear this Moongate (moves it off map)")
                        # Row 1
                        app.label("EE_Label_Moongate_X", "X:", row=1, column=0, font=9)
                        app.label("EE_Label_Moongate_Y", "Y:", row=1, column=1, font=9)
                        # Row 2
                        app.entry("EE_Moongate_X", value=255, width=4, row=2, column=0,
                                  change=entrance_editor_press, font=9)
                        app.entry("EE_Moongate_Y", value=255, width=4, row=2, column=1,
                                  change=entrance_editor_press, font=9)
                        # Row 3
                        app.label("EE_Label_h7", "Moon Phase:", sticky='EW', row=3, column=0, colspan=2, font=9)
                        # Row 4
                        app.canvas("EE_Canvas_Moon_Phase", width=16, height=16, bg="#000000", map=None,
                                   stretch='BOTH', sticky='N', row=4, column=0, colspan=2)
                        # Row 5
                        app.label("EE_Label_h8", "'Ground':", sticky='EW', row=5, column=0, colspan=2, font=9)
                        # Row 6
                        app.canvas("EE_Canvas_Moongate_Tile", width=16, height=16, bg="#000000", map=None,
                                   stretch='BOTH', sticky='N', row=6, column=0, colspan=2)
                        # Row 7
                        app.optionBox("EE_Option_Moongate_Tile", tiles_list, row=7, column=0, colspan=2,
                                      height=1, change=entrance_editor_press, sticky='N', font=9)

            # NPC Editor Sub-Sub-Window --------------------------------------------------------------------------------
            with app.subWindow("NPC_Editor", "NPC Editor", size=[360, 300], modal=False, resizable=False):
                # noinspection PyArgumentList
                app.setStopFunction(map_editor_stop)

                # NPC Actions
                with app.frame("NPCE_Frame_Top", row=0, column=0, stretch='COLUMN', sticky='NEW', padding=[4, 0]):
                    app.button("NPCE_Create", map_editor_input, name=" Create a New NPC ", row=0, column=0, font=9)
                    app.label("NPCE_Label", "Or select an existing one from the list below", row=1, column=0, font=9)

                # NPC Selection
                with app.frame("NPCE_Frame_Middle", row=1, column=0, stretch='COLUMN', sticky='NEW',
                               padding=[4, 4]):
                    app.optionBox("NPCE_Option_NPC_List", ["No NPCs on this map"], change=map_editor_input,
                                  row=0, column=0, width=28, font=9)
                    app.button("NPCE_Delete", map_editor_input, name="Delete", image="res/eraser.gif",
                               tooltip="Delete NPC", row=0, column=1, font=9)

                # NPC Info
                with app.labelFrame("NPCE_Frame_Info", name="NPC Info", row=2, column=0, stretch='BOTH',
                                    sticky='NEWS', padding=[4, 4]):
                    with app.frame("NPCE_Frame_Info_Top", row=0, column=0, padding=[4, 0]):
                        # NPC Graphics
                        app.label("NPCE_Sprite_ID", "GFX Index: ", row=0, column=0, font=10)
                        options = []
                        for i in range(0x1F):
                            options.append(f"0x{i:02X}")
                        app.optionBox("NPCE_Option_Graphics", options, change=npc_select_graphics, row=0, column=1,
                                      font=9)
                        app.canvas("NPCE_Canvas_New_Sprite", row=0, column=2, width=16, height=16, stretch='NONE',
                                   map=None, bg='#C0C0C0')
                        app.checkBox("NPCE_Check_Static", text="Static", change=npc_select_graphics, row=0, column=3,
                                     font=9)

                    with app.frame("NPCE_Frame_Info_Palettes", row=1, column=0, padding=[4, 0]):
                        # 1
                        app.label("NPCE_Label_Palette_1", "Palette 1:", row=0, column=0, font=9)
                        app.optionBox("NPCE_Palette_1", ["0", "1", "2", "3"], change=npc_select_graphics,
                                      row=0, column=1, font=9)
                        # 2
                        app.label("NPCE_Label_Palette_2", "Palette 2:", row=0, column=2, font=9)
                        app.optionBox("NPCE_Palette_2", ["0", "1", "2", "3"], change=npc_select_graphics,
                                      row=0, column=3, font=9)

                    with app.frame("NPCE_Frame_Info_Bottom", row=2, column=0, padding=[4, 0]):
                        # NPC Properties Row 0
                        app.label("NPCE_Dialogue_ID", "Dialogue/Function:", row=0, column=0, colspan=2, font=9)
                        app.label("NPCE_Starting_Position", "Starting Pos: 0, 0", row=0, column=2, font=9)
                        # NPC Properties Row 1
                        app.entry("NPCE_Entry_Dialogue_ID", "0x00", change=map_editor_input, case="upper",
                                  row=1, column=0, font=9)
                        app.button("NPCE_Button_Edit_Dialogue", value=map_editor_input, image="res/edit-dlg.gif",
                                   tooltip="Edit Dialogue Text", row=1, column=1, font=9)
                        app.button("NPCE_Button_Position", map_editor_input, name="Set Position", row=1, column=2,
                                   font=9)

        # Text Editor Sub-Window ---------------------------------------------------------------------------------------
        with app.subWindow("Text_Editor", "Text Editor", size=[400, 360], modal=False, resizable=False):
            # noinspection PyArgumentList
            app.setStopFunction(text_editor_stop)

            # Buttons
            with app.frame("TE_Frame_Top", row=0, colspan=2, sticky='NEW', stretch='ROW', padding=[8, 2]):
                app.button("TE_Button_Accept", text_editor_press, name="Accept and Close", image="res/floppy.gif",
                           tooltip="Apply Changes and Close", row=0, column=0, sticky='W')
                app.button("TE_Button_Close", text_editor_press, name=" Cancel ", image="res/close.gif",
                           tooltip="Discard Changes and Close", row=0, column=2, sticky='E')

            # Text
            with app.frame("TE_Frame_Left", row=1, column=0, bg="#FFCFCF", sticky='NEW', stretch='COLUMN',
                           padding=[2, 2]):
                app.label("TE_Label_Text", "Unpacked string:", row=0, column=0)
                app.textArea("TE_Text", "", width=22, stretch='BOTH', sticky='NEWS', scroll=True,
                             row=1, column=0).setFont(family="Consolas", size=12)

            # Address
            with app.frame("TE_Frame_Right", row=1, column=1, bg="#CFCFFF",
                           padding=[2, 2]):
                app.label("TE_Label_Type", "(Text type)")
                app.label("TE_Label_Address", "Address:")
                app.entry("TE_Entry_Address", "", case="upper")
                app.button("TE_Button_Reload_Text", value=text_editor_press, name="Reload Text")

            # Dialogue name and portrait
            with app.frame("TE_Frame_Bottom", row=2, colspan=2, sticky='SEW', stretch='COLUMN',
                           padding=[2, 2]):
                with app.labelFrame("Dialogue Properties", 0, 0, padding=[4, 4]):
                    with app.frame("TE_Frame_Dialogue_Left", row=0, column=0, bg="#FFFFFF", sticky='NEW',
                                   stretch='COLUMN'):
                        app.label("TE_Label_Name", "NPC Name: ", row=0, column=0)
                        app.optionBox("TE_Option_Name", ["(0xFF) No Name"], row=0, column=1, width=20)
                        app.label("TE_Label_Portrait", "Portrait: ", row=1, column=0)
                        portrait_options = ["No Portrait"]
                        for p in range(0x22):
                            portrait_options.append(f"{p:02d}")
                        app.optionBox("TE_Option_Portrait", portrait_options, change=select_portrait, row=1, column=1)

                    with app.frame("TE_Frame_Dialogue_Right", row=0, column=1, bg="#CFCFCF", sticky='NEW',
                                   stretch='COLUMN'):
                        app.canvas("TE_Canvas_Portrait", width=40, height=48, bg='#000000', map=None, sticky='NEW',
                                   stretch='NONE')

    del maps_list
    del portrait_options
    del options
    del tiles_list
