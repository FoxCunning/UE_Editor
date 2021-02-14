__author__ = "Fox Cunning"

import configparser
import os
import tkinter
from typing import List, Union

from PIL import Image, ImageTk

import appJar
import colour
from appJar import gui
from debug import log
from editor_settings import EditorSettings
from rom import ROM

from routines import Routine, Parameter


# ----------------------------------------------------------------------------------------------------------------------
from tile_editor import TileEditor


def _convert_unpacked(byte: int) -> str:
    """Converts an unpacked text byte to the corresponding displayable ASCII character

    Parameters
    ----------
    byte
        A single byte containing the value to convert

    Returns
    -------
    str
        A single ASCII character representing the unpacked byte
    """
    if byte <= 25:
        return str(chr(byte + 65))

    if 32 <= byte <= 41:
        return str(chr(byte + 16))

    switcher = {
        0x1A: '!',
        0x1B: '?',
        0x1C: '.',
        0x1D: ',',
        0x1E: '-',
        0x1F: '"',
        0x2B: '-',
        0x2C: '`',
        0x2D: ' ',
        0x2E: ':',
        0x30: '@',  # Special: character name (address in $99, $9A)
        0x31: '%',  # Special: enemy name
        0x32: '#',  # Special: numeric value from $A0, $A1
        0x34: '&',  # Special: next string is new dialogue
        0x35: '^',  # Special: YES/NO question
        0x38: '$',  # Special: give the 'PRAY' command
        0x39: '*',  # Special: give the 'BRIBE' command
        0x3E: '\n',
        0x3F: '~'  # String terminator
    }

    return switcher.get(byte, '[?]')


# ----------------------------------------------------------------------------------------------------------------------

def _convert_packed(character: str) -> int:
    """Converts a string (representing a single ASCII character) to a 6-bit integer for bit-packing

    Parameters
    ----------
    character
        The ASCII character to convert

    Returns
    -------
    int
        The converted value as an integer
    """
    switcher = {
        '!': 0x1A,
        '?': 0x1B,
        '.': 0x1C,
        ',': 0x1D,
        '-': 0x1E,
        '"': 0x1F,
        '\'': 0x2C,
        '`': 0x2C,
        ' ': 0x2D,
        ':': 0x2E,
        '@': 0x30,  # Special: character name (address in $99, $9A)
        '%': 0x31,  # Special: enemy name
        '#': 0x32,  # Special: numeric value from $A0, $A1 (unsigned short)
        '&': 0x34,  # Special: next string is new dialogue
        '^': 0x35,  # Special: YES/NO question
        '$': 0x38,  # Special: give the 'PRAY' command
        '*': 0x39,  # Special: give the 'BRIBE' command
        '\n': 0x3E,
        '\r': 0x3E,
        '\a': 0x3E,
        '~': 0x3F  # String terminator
    }

    value = ord(character[0])
    if 65 <= value <= 90:  # A-Z
        return value - 65

    if 48 <= value <= 57:  # 0-9
        return value - 16

    return switcher.get(character[0], 0x1B)


# ----------------------------------------------------------------------------------------------------------------------

# Base dictionaries used for conversions

# Dictionary used to convert from Exodus to ASCII
_EXODUS_DICT = {
    0x00: ' ',
    0x01: '+',
    0x02: '-',
    0x03: ':',
    0x04: '\'',
    0x05: '"',
    0x09: '*',
    0x42: ',',
    0x43: '.',
    0x7C: '!',
    0x7D: '?',
    0x88: '©',
    0x89: '…',
    0xFD: '\n',
    0xFF: '~'
}

# Dictionary used to convert from ASCII to Exodus
_ASCII_DICT = {
    ' ': 0x00,
    '+': 0x01,
    '-': 0x02,
    ':': 0x03,
    '\'': 0x04,
    '"': 0x05,
    '*': 0x09,
    ',': 0x42,
    '.': 0x43,
    '!': 0x7C,
    '?': 0x7D,
    '©': 0x88,
    '…': 0x89,
    '\n': 0xFD,
    '\r': 0xFD,
    '\a': 0xFD,
    '~': 0xFF
}

# Customisable versions
_exodus_dict = _EXODUS_DICT.copy()
_ascii_dict = _ASCII_DICT.copy()


# ----------------------------------------------------------------------------------------------------------------------

def ascii_to_exodus(ascii_string: str) -> bytearray:
    """
    Converts an ASCII string to a string of bytes representing nametable value that can be displayed as text
    in the game

    Parameters
    ----------
    ascii_string: str
        The text to convert; escape sequences can be passed in the form '\\xNN' where NN is an 8-bit hexadecimal: these
        values will be written as they are, for example \\xA8 will produce 0xA8 as its output

    Returns
    -------
    bytearray
        A byte array containing the pattern indices that would be used to represent the given string
    """
    exodus_string = bytearray()
    ascii_string = ascii_string.upper()

    c = 0
    while c < len(ascii_string):

        value = ord(ascii_string[c])

        if 48 <= value <= 57:  # Numbers
            exodus_string.append(value + 8)

        elif 65 <= value <= 90:  # Letters
            exodus_string.append(value + 73)

        elif value == 92:  # '\xNN': beginning of escape sequence
            try:
                if ascii_string[c + 1] == 'X' or ascii_string[c + 1] == 'x':
                    c = c + 1
                    value = int(ascii_string[c + 1: c + 3], 16)
                    exodus_string.append(value)
                    c = c + 2
                else:
                    exodus_string.append(0x00)
            except IndexError as error:
                log(3, "TEXT EDITOR",
                    f"{error} while processing escape sequence in string '{ascii_string}'.")
                c = c + 1
                continue
            except ValueError as error:
                log(3, "TEXT EDITOR",
                    f"{error} while processing escape sequence in string '{ascii_string}'.")
                c = c + 1
                continue

        else:
            exodus_string.append(_ascii_dict.get(ascii_string[c], 0x00))

        c = c + 1

    return exodus_string


# ----------------------------------------------------------------------------------------------------------------------

def exodus_to_ascii(exodus_string: bytearray) -> str:
    """
    Converts a string stored as pattern IDs + special characters to an ASCII sting.
    Non-printable characters will be turned into escape sequences in the form '\\xNN' where NN is the original
    8-bit value

    Parameters
    ----------
    exodus_string: bytearray
        The string of bytes to convert

    Returns
    -------
    str
        The converted ASCII string
    """
    ascii_string = ""

    for char in exodus_string:
        if 0x8A <= char <= 0xA3:
            ascii_string = ascii_string + chr(char - 0x49)
        elif 0x38 <= char <= 0x41:
            ascii_string = ascii_string + chr(char - 0x08)
        else:
            value = _exodus_dict.get(char, '#')
            if value == '#':
                value = f"\\x{char:02X}"
            ascii_string = ascii_string + value

    return ascii_string


# ----------------------------------------------------------------------------------------------------------------------

def read_text(rom: ROM, bank: int, address: int) -> str:
    """
    Reads and decodes a string of text from ROM.

    Parameters
    ----------
    rom: ROM
        Instance of the ROM class containing the data
    bank: int
        Index of the bank where the text is stored
    address: int
        Address of the string of text in ROM

    Returns
    -------
    str
        An ASCII string representing the text at the given address
    """
    text = ""
    buffer = bytearray()
    value = rom.read_byte(bank, address)

    while value != 0xFF:
        buffer.append(value)
        address = address + 1
        value = rom.read_byte(bank, address)

    if len(buffer) > 0:
        text = exodus_to_ascii(buffer)

    return text


# ----------------------------------------------------------------------------------------------------------------------

def _empty_image(width: int, height: int) -> Image:
    colours = [0, 0, 0,
               255, 255, 255,
               255, 0, 0,
               0, 0, 255]
    pixels = []
    for _ in range(width * height):
        pixels.append(0)
    image_data = bytes(bytearray(pixels))
    image = Image.frombytes('P', (width, height), image_data)
    image.putpalette(colours)
    return image


# ----------------------------------------------------------------------------------------------------------------------

class TextEditor:

    def __init__(self, rom: ROM, colours: list, text_colours: bytearray, app: gui, settings: EditorSettings,
                 tile_editor: TileEditor):
        global _ascii_dict, _exodus_dict

        self.text: str = ""  # Text being edited (uncompressed)
        self.type: str = ""  # String type (determines where the pointer is)
        self.index: int = -1  # Index of the pointer to this string
        self.address: int = 0  # Address of compressed text in bank 05

        self.settings = settings

        self.special_index = -1  # Same, for special (e.g. shop) dialogues
        self._special_routine: Routine = Routine()
        self._special_unsaved_changes: bool = False
        # Full path of routine definitions file
        self._special_definitions: str = ""

        self._location_names: List[str] = ["- No Maps Names -"]

        self.unsaved_changes: bool = False  # Set this to True when the text has been modified

        self.npc_name_pointers: List[int] = [0]  # Pointer to NPC name for this dialogue
        self.npc_names: List[str] = []  # NPC name as read from ROM using the above pointer

        self.enemy_name_pointers: List[int] = []  # Pointers to enemy names
        self.enemy_names: List[str] = []  # Enemy name strings as read from ROM

        self.menu_text_pointers: List[int] = []
        self.menu_text: List[str] = []

        # Reference to the global ROM instance
        self.rom: ROM = rom

        self.tile_editor: TileEditor = tile_editor

        # Colours used to draw portrait previews
        self.colours: List[int] = colours

        # Compressed text pointer tables
        self.dialogue_text_pointers: List[int] = []  # Dialogue text, 0xE6 pointers at 05:9D90
        self.special_text_pointers: List[int] = []  # Special text, 0x100 pointers at 05:8000

        # Cached uncompressed text
        self.dialogue_text: List[str] = []
        self.special_text: List[str] = []

        self.app: gui = app

        # Cached images for preview
        self._chr_tiles: List[ImageTk.PhotoImage] = []

        self._text_colours: bytearray = text_colours

        # Start from this line when drawing the text preview
        self.text_line: int = 0

        # Canvas item IDs
        self._chr_items: List[int] = [0] * (20 * 9)
        self._preview_canvas: Union[any, tkinter.Canvas] = None
        self._charset_items: List[int] = [8] * 256
        self._charset_canvas: Union[any, tkinter.Canvas] = None
        self._charset_selection: int = 0

        # Selected character for custom mapping
        self._selected_char: int = 0

        # These will be used to read and customise character mappings before adding them to our dictionary
        self.custom_ascii = []
        self.custom_exodus = []

        # Read portrait descriptive names from file
        try:
            file = open("portraits.txt", "r")
            try:
                lines = file.readlines()
                entries = len(lines)
                options: List[str] = ["No Portrait"]
                for i in range(33):
                    if i < entries:
                        text = lines[i].rstrip("\n\r\a")
                        options.append(f"{i:02d} {text}")
                    else:
                        options.append(f"{i:02d}")
                self.app.changeOptionBox("TE_Option_Portrait", options, callFunction=False)

            except IOError as error:
                self.error(f"Error parsing portrait descriptions file: {error}.")

            file.close()

        except IOError:
            log(3, f"{self}", "Could not read portrait descriptions file.")

        # Load names table from ROM
        # Read strings from 0B:A700 byte by byte until 0xFF is encountered to get the base address of each string
        #   Repeat until 0xA7FF is reached
        end_of_string = False
        temp_name = bytearray()
        for address in range(0xA700, 0xA800):
            if end_of_string:
                self.npc_name_pointers.append(address & 0xFF)
                end_of_string = False
                temp_name = []
            value = rom.read_byte(0x0B, address)
            if value == 0xFF:
                end_of_string = True
                # Convert bytes to ASCII string and add it to npc_names
                self.npc_names.append(exodus_to_ascii(temp_name))
            else:
                temp_name.append(value)
        # This leaves us with an extra pointer (to an empty string) that we need to trim
        self.npc_name_pointers = self.npc_name_pointers[:-1]

        # Load enemy names from ROM
        # Read pointers from 05:BC80-BCF9 (these are 16-bit addresses)
        for address in range(0xBC80, 0xBCFA, 2):
            self.enemy_name_pointers.append(rom.read_word(0x5, address))

        # Use pointers to read strings
        for pointer in self.enemy_name_pointers:
            temp_name = bytearray()
            for a in range(32):
                # Read bytes until 0xFF is found
                value = rom.read_byte(0x5, pointer + a)
                if value == 0xFF:
                    self.enemy_names.append(exodus_to_ascii(temp_name))
                    break
                else:
                    temp_name.append(value)

        # Read custom character mappings. These are used for example to map accented letters to custom tiles.
        self.custom_ascii, self.custom_exodus = self._load_custom_mappings()
        # Turn them into dictionaries and build our new dictionaries by adding them to the default mappings
        d = dict(self.custom_ascii)
        _ascii_dict = {**_ASCII_DICT, **d}
        d = dict(self.custom_exodus)
        _exodus_dict = {**_EXODUS_DICT, ** d}

        # Read Menu/Intro pointers from ROM
        self.read_menu_text()

        # Read and uncompress dialogue / special strings
        self.uncompress_all_string()

    # ------------------------------------------------------------------------------------------------------------------

    def uncompress_all_string(self):
        """
        Unpacks and caches all the compressed strings from ROM
        """
        # Clear previous data if needed
        self.dialogue_text_pointers = []  # Dialogue text, 0xE6 pointers at 05:9D90
        self.special_text_pointers = []  # Special text, 0x100 pointers at 05:8000

        # Cached uncompressed text
        self.dialogue_text = []
        self.special_text = []

        # Read pointers to compressed text, and also uncompress the text and cache it
        for offset in range(0, 0x100):
            if offset < 0xE6:
                address = self.rom.read_word(5, 0x9D80 + (offset * 2))
                self.dialogue_text_pointers.append(address)
                self.dialogue_text.append(TextEditor.unpack_text(self.rom, address))

            address = self.rom.read_word(5, 0x8000 + (offset * 2))
            self.special_text_pointers.append(address)
            self.special_text.append(TextEditor.unpack_text(self.rom, address))

    # ------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def unpack_text(rom: ROM, address: int) -> str:
        """
        Unpacks text from bank 5 at the specified address.

        Parameters
        ----------
        rom: ROM
            Instance of the ROM class containing the data
        address: int
            Address of packed data in ROM Bank 05

        Returns
        -------
        str
            The unpacked ASCII string
        """
        buffer = [0, 0, 0]  # Input buffer
        temp = [0, 0, 0, 0]  # Temporary unpacked data storage
        output = ""  # Unpacked string that will be returned
        while address < 0xC000:
            # Get the next 3 bytes of packed data
            buffer[0] = rom.read_byte(5, address)
            buffer[1] = rom.read_byte(5, address + 1)
            buffer[2] = rom.read_byte(5, address + 2)
            address = address + 3

            # 1st byte
            temp[0] = (buffer[0] >> 2) & 0x3F
            if temp[0] == 0x3F:
                temp[1] = 0x2D
                temp[2] = 0x2D
                temp[3] = 0x2D
            else:
                temp[1] = (buffer[1] >> 4) | ((buffer[0] & 0x03) << 4)
                if temp[1] == 0x3F:
                    temp[2] = 0x2D
                    temp[3] = 0x2D
                else:
                    temp[2] = ((buffer[1] & 0x0F) << 2) | (buffer[2] >> 6)
                    if temp[2] == 0x3F:
                        temp[3] = 0x2D
                    else:
                        temp[3] = buffer[2] & 0x3F

            for i in range(0, 4):
                char = _convert_unpacked(temp[i])
                if char == '[?]':
                    log(3, "TEXT EDITOR", f"Unrecognised character: {temp[i]:02X}.\nAddress: 0x{address:04X}.\n"
                                          f"Partial output: '{output}'.")
                output = output + char
                if temp[i] == 0x3F:
                    return output

        return output

    # ------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def pack_text(text: str) -> bytearray:
        """
        Compresses the given ASCII string using 6-bit packing

        Parameters
        ----------
        text: str
            ASCII string to compress

        Returns
        -------
        bytearray
            A bytearray containing the compressed data
        """

        packed_data = bytearray()

        # Convert input string to uppercase, just in case (pun intended)
        text = text.upper()

        # Take four bytes per iteration and pack them into three bytes
        input_bytes = [0, 0, 0, 0]
        output_bytes = [0, 0, 0]
        length = len(text)
        for i in range(0, length, 4):
            # Move the next four characters into the input_bytes array, filling with 0xFF after end of string
            # (this is because we need exactly four bytes per iteration)
            for c in range(0, 4):
                if i + c < length:
                    input_bytes[c] = _convert_packed(text[i + c])
                else:
                    input_bytes[c] = 0x3F

            # Pack by discarding the two most significant bits and shifting twice to the left
            output_bytes[0] = 0xFF & ((input_bytes[0] << 2) | (input_bytes[1] >> 4))
            packed_data.append(output_bytes[0])
            # Check for end of string marker
            if input_bytes[0] == 0x3F:
                break

            output_bytes[1] = 0xFF & ((input_bytes[1] << 4) | (input_bytes[2] >> 2))
            packed_data.append(output_bytes[1])
            if input_bytes[1] == 0x3F:
                break

            output_bytes[2] = 0xFF & ((input_bytes[2] << 6) | (input_bytes[3]))
            packed_data.append(output_bytes[2])
            if input_bytes[2] == 0x3F or input_bytes[3] == 0x3F:
                break

        return packed_data

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

    def show_advanced_window(self, string_id: int, string_type: str) -> None:
        """
        Shows a window with advanced options to change the desired text and associated portrait/NPC name (if any)

        Parameters
        ----------
        string_id: int
            Index of the text to edit
        string_type: str
            The type of string to edit: "Dialogue", "Special", "NPC Names" or "Enemy Names" or "Menu / Intro"
        """
        self.index = string_id
        self.type = string_type

        self.unsaved_changes = False

        if string_type == "Dialogue":
            self.address = self.dialogue_text_pointers[string_id]
            self.text = self.dialogue_text[string_id]
            self.app.setRadioButton("TE_Preview_Mode", "Conversation", False)
        elif string_type == "Special":
            self.address = self.special_text_pointers[string_id]
            self.text = self.special_text[string_id]
            self.app.setRadioButton("TE_Preview_Mode", "Default", False)
        elif string_type == "NPC Names":
            self.address = self.npc_name_pointers[string_id]
            self.text = self.npc_names[string_id]
            self.app.setRadioButton("TE_Preview_Mode", "Default", False)
        elif string_type == "Enemy Names":
            self.address = self.enemy_name_pointers[string_id]
            self.text = self.enemy_names[string_id]
            self.app.setRadioButton("TE_Preview_Mode", "Default", False)
        elif string_type == "Menus / Intro":
            self.address = self.menu_text_pointers[string_id]
            self.text = self.menu_text[string_id]
            self.app.setRadioButton("TE_Preview_Mode", "Default", False)
        else:
            log(3, "TEXT EDITOR", f"Invalid string type '{string_type}'.")
            return

        text_widget = self.app.getTextAreaWidget("TE_Text")
        text_widget.bind("<KeyRelease>", lambda _e: TextEditor.highlight_keywords(text_widget))
        text_widget.bind("<KeyRelease>", lambda _e: self.draw_text_preview(False), add='+')

        self.app.clearTextArea("TE_Text", callFunction=False)
        self.app.setTextArea("TE_Text", self.text)
        TextEditor.highlight_keywords(text_widget)
        self.app.getTextAreaWidget("TE_Text").see("1.0")

        self.app.setLabel("TE_Label_Type", f"{string_type} Text")
        self.app.setEntry("TE_Entry_Address", f"0x{self.address:02X}")

        self._load_text_patterns()
        self._preview_canvas = self.app.getCanvasWidget("TE_Preview")
        self.draw_text_preview(True)

        if string_type == "Dialogue" or string_type == "Special":
            # Populate NPC names OptionBox
            names = ["(0xFF) No Name"]
            for i in range(len(self.npc_name_pointers)):
                names.append(f"(0x{self.npc_name_pointers[i]:02X}) {self.npc_names[i]}")
            # for name in self.npc_names:
            #    names.append(name)
            self.app.clearOptionBox("TE_Option_Name", callFunction=False)
            self.app.changeOptionBox("TE_Option_Name", names, callFunction=False)
            # Select "No Name" by default
            self.app.setOptionBox("TE_Option_Name", 0, callFunction=False)

            self.app.showFrame("TE_Frame_Bottom")
        else:
            # Hide dialogue frame and return
            self.app.hideFrame("TE_Frame_Bottom")
            self.app.showSubWindow("Text_Editor")
            # app.clearOptionBox("TE_Option_Name")
            # app.changeOptionBox("TE_Option_Name", ["- No Name -"])
            return

        # If this ROM does not support dialogue names=, disable that widget
        if self.rom.has_feature("portraits") is False:
            self.app.disableOptionBox("TE_Option_Name")

        elif string_type == "Dialogue" or string_type == "Special":
            self.app.enableOptionBox("TE_Option_Name")

            # Load NPC name for the selected dialogue
            #   Normal dialogues IDs in 0B:A600-A6FF
            #   Special dialogue IDs in 0B:9690-9865 (id - 0x56)
            #   Name strings in $A700-$A79F
            # Get name pointer from ROM
            if string_type == "Dialogue":
                address = 0xA600 + string_id
            elif string_type == "Special" and string_id >= 0x56:
                address = 0x9690 + string_id - 0x56
            else:
                address = 0

            if address > 0:
                pointer = self.rom.read_byte(0x0B, address)
                print(f"NPC Dialogue Name Pointer: 0x{pointer:02X} at 0B:{address:04X}")

                if pointer == 0xFF:  # No name
                    self.app.setOptionBox("TE_Option_Name", 0, callFunction=False)
                else:  # Find pointer in names OptionBox
                    for i in range(len(self.npc_name_pointers)):
                        if pointer == self.npc_name_pointers[i]:
                            self.app.setOptionBox("TE_Option_Name", i + 1, callFunction=False)
                            break
            else:
                self.app.setOptionBox("TE_Option_Name", 0, callFunction=False)

        # Default: no portrait
        portrait_index = 0xFF

        # If this ROM does not support dialogue names=, disable that widget
        if self.rom.has_feature("portraits") is False:
            self.app.disableOptionBox("TE_Option_Portrait")

        # Load portrait for selected dialogue/special
        elif string_type == "Dialogue":
            self.app.enableOptionBox("TE_Option_Portrait")

            # Get portrait index from 0B:94F0-95DF
            portrait_index = self.rom.read_byte(0x0B, 0x94F0 + string_id)
            # Option = index + 1 because option 0 is no portrait
            self.app.setOptionBox("TE_Option_Portrait", portrait_index + 1)
        elif string_type == "Special":
            self.app.enableOptionBox("TE_Option_Portrait")

            if string_id >= 0x56:
                # Get portrait index from 0B:95E0-968F ( + string_id - 0x56)
                portrait_index = self.rom.read_byte(0x0B, 0x95E0 + string_id - 0x56)
                if portrait_index < 0xFF:
                    self.app.setOptionBox("TE_Option_Portrait", portrait_index + 1)
                else:
                    self.app.setOptionBox("TE_Option_Portrait", 0)
            else:
                self.app.setOptionBox("TE_Option_Portrait", 0)
        else:
            self.app.setOptionBox("TE_Option_Portrait", 0)

        self.load_portrait(portrait_index)

        self.app.showSubWindow("Text_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    _DICTIONARY = {'@': colour.DARK_OLIVE,
                   '%': colour.DARK_BLUE,
                   '#': colour.DARK_BROWN,
                   '&': colour.DARK_ORANGE,
                   '$': colour.DARK_LIME,
                   '^': colour.DARK_TEAL,
                   '*': colour.DARK_MAGENTA,
                   '~': colour.DARK_RED}

    @staticmethod
    def highlight_keywords(widget: tkinter.Text) -> None:
        """
        Adapted from https://stackoverflow.com/questions/23120504/tkinter-text-widget-keyword-colouring
        """
        for key, clr in TextEditor._DICTIONARY.items():
            start_index = '1.0'
            while True:
                start_index = widget.search(key, start_index, tkinter.END)
                if start_index:
                    end_index = widget.index(f"{start_index}+{len(key)}c")
                    widget.tag_add(key, start_index, end_index)
                    widget.tag_config(key, foreground=clr, background=colour.PALE_GREEN)
                    start_index = end_index
                else:
                    break

    # ------------------------------------------------------------------------------------------------------------------

    def modify_text(self, new_text: str, new_address: int, new_portrait: int = -1, new_npc_name: int = -1) -> None:
        """
        Modifies the currently selected string.

        Parameters
        ----------
        new_text: int
            The new (uncompressed) text
        new_address: int
            A new address for this string, ignored if not dialogue/special
        new_portrait: int
            Index of the new portrait used for this dialogue.
            Ignored if -1, if type is neither Dialogue nor Special, or if the index of a special string is < 0x56.
        new_npc_name: int
            Index of the new name string for the NPC using this dialogue.
            Ignored if -1, if type is neither Dialogue nor Special, or if the index of a special string is < 0x56.
        """
        new_text = new_text.upper()

        if self.type == "Dialogue":
            self.dialogue_text[self.index] = new_text
            self.dialogue_text_pointers[self.index] = new_address

            if new_portrait >= 0:
                address = 0x94F0 + self.index
                self.rom.write_byte(0xB, address, new_portrait)

            if new_npc_name >= 0:
                address = 0xA600 + self.index
                self.rom.write_byte(0xB, address, new_npc_name)

        elif self.type == "Special":
            self.special_text[self.index] = new_text
            self.special_text_pointers[self.index] = new_address

            if self.index >= 0x56:
                if new_portrait >= 0:
                    address = 0x958A + self.index
                    self.rom.write_byte(0xB, address, new_portrait)
                if new_npc_name >= 0:
                    address = 0x963A + self.index
                    self.rom.write_byte(0xB, address, new_npc_name)

        elif self.type == "NPC Names":
            self.npc_names[self.index] = new_text

        elif self.type == "Enemy Names":
            self.enemy_names[self.index] = new_text
            # Also change names that share the same pointer
            address = self.enemy_name_pointers[self.index]
            for i in range(len(self.enemy_names)):
                if self.enemy_name_pointers[i] == address:
                    self.enemy_names[i] = new_text

        elif self.type == "Menus / Intro":
            # self.menu_text_pointers[self.index] = new_address
            self.menu_text[self.index] = new_text

        else:
            self.warning(f"Invalid string type for modify_text: '{self.type}'.")
            return

        self.app.clearTextArea("Text_Preview")
        self.app.setTextArea("Text_Preview", new_text)
        TextEditor.highlight_keywords(self.app.getTextAreaWidget("Text_Preview"))

    # ------------------------------------------------------------------------------------------------------------------

    def close_advanced_window(self, confirm_quit: bool = True) -> bool:
        """
        Close the advanced text editing window

        Parameters
        ----------
        confirm_quit: bool
            If True, ask for confirmation before closing

        Returns
        -------
        bool
            True if the window has been closed, False otherwise (e.g. user cancelled)
        """
        # Ask for confirmation if self.changed is True
        if confirm_quit is True and self.unsaved_changes is True:
            choice = self.app.questionBox("Confirm", "Unsaved changes will be lost. Continue?")
            if choice is False:
                return False

        self.app.hideSubWindow("Text_Editor", useStopFunction=False)

        # Purge image cache
        self._chr_tiles = []

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def draw_text_preview(self, redraw_frame: bool = False) -> None:
        mode = self.app.getRadioButton("TE_Preview_Mode")

        if mode == "Conversation":
            left = 4
            top = 2
            skip_rows = False
            frame = True
            last_row = 6
            last_col = 16
        elif mode == "Intro":
            left = 0
            top = 3
            skip_rows = True
            frame = False
            last_row = 7
            last_col = 19
        else:
            left = 0
            top = 0
            skip_rows = False
            frame = False
            last_row = 8
            last_col = 19

        # Get text as a list of lines
        lines = self.app.getTextArea("TE_Text").splitlines()

        # Clear items / draw frame first
        if redraw_frame:
            frame_col = left - 2
            frame_right = last_col + 1

            for y in range(9):
                for x in range(20):
                    item = x + (y * 20)
                    if frame:
                        if y == 0:
                            if frame_col < x < frame_right:
                                tile = 0x7F
                            elif x == frame_col:
                                tile = 0x7E
                            elif x == frame_right:
                                tile = 0x80
                            else:
                                tile = 0
                        elif y == last_row + 1:
                            if frame_col < x < frame_right:
                                tile = 0x84
                            elif x == frame_col:
                                tile = 0x83
                            elif x == frame_right:
                                tile = 0x85
                            else:
                                tile = 0
                        elif 0 < y < last_row + 1:
                            if x == frame_col:
                                tile = 0x81
                            elif x == frame_right:
                                tile = 0x82
                            else:
                                tile = 0
                        else:
                            tile = 0
                    else:
                        tile = 0

                    if self._chr_items[item] > 0:
                        self._preview_canvas.itemconfig(self._chr_items[item], image=self._chr_tiles[tile])
                    else:
                        self._preview_canvas.create_image(x * 8, y * 8, anchor="nw", image=self._chr_tiles[tile])

        # In "Conversation" mode, show the selected NPC name
        if redraw_frame and mode == "Conversation":
            name_id = self._get_selection_index("TE_Option_Name")
            if name_id > 0:
                name = ascii_to_exodus(self.npc_names[name_id - 1])

                x = left
                for c in name:
                    if self._chr_items[x] > 0:
                        self._preview_canvas.itemconfig(self._chr_items[x], image=self._chr_tiles[c])
                    else:
                        self._preview_canvas.create_image(x * 8, 0, anchor="nw", image=self._chr_tiles[c])
                    x += 1

        col = left
        row = top
        for text in lines[self.text_line:]:
            if row > last_row:
                break

            e = ascii_to_exodus(text)
            for c in e:
                if row > last_row:
                    break

                if col > last_col:
                    break

                if c == 0xFD:       # End of Line
                    row += 1
                    col = left
                    continue
                elif c == 0xFF:     # End of String
                    break

                item = col + (row * 20)
                if self._chr_items[item] > 0:
                    self._preview_canvas.itemconfig(self._chr_items[item], image=self._chr_tiles[c])
                else:
                    self._preview_canvas.create_image(col * 8, row * 8, anchor="nw", image=self._chr_tiles[c])

                col += 1

            # Clear the rest of the line
            while col < last_col + 1:
                item = col + (row * 20)
                if self._chr_items[item] > 0:
                    self._preview_canvas.itemconfig(self._chr_items[item], image=self._chr_tiles[0])
                else:
                    self._preview_canvas.create_image(col * 8, row * 8, anchor="nw", image=self._chr_tiles[0])
                col += 1

            row += 2 if skip_rows else 1
            col = left

        # Clear the remaining lines under the text, if needed
        while row < last_row + 1:
            col = left
            while col < last_col + 1:
                item = col + (row * 20)
                if self._chr_items[item] > 0:
                    self._preview_canvas.itemconfig(self._chr_items[item], image=self._chr_tiles[0])
                else:
                    self._preview_canvas.create_image(col * 8, row * 8, anchor="nw", image=self._chr_tiles[0])
                col += 1
            row += 1

    # ------------------------------------------------------------------------------------------------------------------

    def _load_text_patterns(self) -> None:
        """
        Reads pattern data used for the end credits and stores it in image instances that can be used on a canvas.
        """
        # The ending credits use the "map" palette 1
        colours = self._text_colours

        self._chr_tiles = []

        # First, load the default map patterns
        address = 0x8000
        for i in range(256):
            pixels = bytes(self.rom.read_pattern(0xA, address))
            address += 16  # Each pattern is 16 bytes long

            image_1x = Image.frombytes('P', (8, 8), pixels)

            image_1x.putpalette(colours)

            # Cache this image
            self._chr_tiles.append(ImageTk.PhotoImage(image_1x))

    # ------------------------------------------------------------------------------------------------------------------

    def load_portrait(self, index: int) -> None:
        self.app.clearCanvas("TE_Canvas_Portrait")

        if index == 0xFF:  # No portrait
            image = _empty_image(40, 48)
            self.app.addCanvasImage("TE_Canvas_Portrait", 20, 24, ImageTk.PhotoImage(image))
            return

        # Load portrait from ROM
        address = 0x8000 + (index * 0x1E0)

        for y in range(6):
            for x in range(5):
                byte_data = bytes(bytearray(self.rom.read_pattern(1, address)))
                image = Image.frombytes('P', (8, 8), byte_data)
                image.putpalette(self.colours)
                address = address + 16
                self.app.addCanvasImage("TE_Canvas_Portrait", 4 + (x * 8), 4 + (y * 8), ImageTk.PhotoImage(image))

    # ------------------------------------------------------------------------------------------------------------------

    class StringListItem:
        """
        A helper class used to rebuild string pointers

        Attributes
        ----------
        text: any
            Text, either in the form of compressed bytes, or a string of characters
        address: int
            The address of this string in ROM Bank 05
        done: bool, optional
            Set to True if this pointer has been already (re)allocated
        """
        text: any
        address: int = 0
        done: bool = False

        def __init__(self, text: any, address: int = 0):
            self.text = text
            self.address = address
            self.done = False

    # ------------------------------------------------------------------------------------------------------------------

    class StringMemoryInfo:
        """
        A helper class used to allocate memory for a compressed string

        Attributes
        ----------
        special_first: int
            The first available address for a special string
        special_end: int
            Boundary of the memory reserved to special strings
        normal_first: int
            The first available address for a normal string
        normal_end: int
            Boundary of the memory reserved to normal strings
        """

        def __init__(self):
            self.special_first: int = 0x8200
            self.special_end: int = 0x9B4F
            self.normal_first: int = 0x9F4C
            self.normal_end: int = 0xBBCF

        # --- TextEditor.StringMemoryInfo.allocate_memory() ---

        def allocate_memory(self, size: int, preference: str = "special") -> int:
            """
            Tries to allocate memory for a compressed string of bytes

            Parameters
            ----------
            size: int
                The size, in bytes, of the memory that we need to allocate
            preference: str, optional
                Preferred memory area, either "special" or "normal"

            Returns
            -------
            int
                The address of the allocated area, or 0 if out of memory
            """
            if preference == "normal":
                address = self._allocate_normal(size)
                if address == 0:
                    return self._allocate_special(size)
            else:
                address = self._allocate_special(size)
                if address == 0:
                    return self._allocate_normal(size)

            return address

        # --- TextEditor.StringMemoryInfo._allocate_special() ---

        def _allocate_special(self, size: int) -> int:
            """
            Finds an area in ROM where a special compressed string can be stored

            Parameters
            ----------
            size: int
                Size in bytes of the memory area required

            Returns
            -------
            int
                8-bit address of the allocated memory area
            """
            # Calculate potential end address
            end = self.special_first + size
            # Return 0 if out of bounds
            if end >= self.special_end:
                return 0

            # Otherwise update first available address and return allocated address
            address = self.special_first
            self.special_first = end

            return address

        # --- TextEditor.StringMemoryInfo._allocate_normal() ---

        def _allocate_normal(self, size: int) -> int:
            """
            Finds an area in ROM where a dialogue compressed string can be stored

            Parameters
            ----------
            size: int
                Size in bytes of the memory area required

            Returns
            -------
            int
                8-bit address of the allocated memory area
            """
            # Calculate potential end address
            end = self.normal_first + size
            # Return 0 if out of bounds
            if end >= self.normal_end:
                return 0

            # Otherwise update first available address and return allocated address
            address = self.normal_first
            self.normal_first = end

            return address

    # ------------------------------------------------------------------------------------------------------------------

    def rebuild_pointers(self) -> None:
        """
        Rebuilds the pointer tables for dialogues and special text
        """
        special_list = []
        dialogue_list = []

        memory = TextEditor.StringMemoryInfo()

        # Create two lists of strings to process
        for i in range(256):
            special_list.append(TextEditor.StringListItem(self.special_text[i], self.special_text_pointers[i]))
            if i < 0xE6:
                dialogue_list.append(TextEditor.StringListItem(self.dialogue_text[i], self.dialogue_text_pointers[i]))

        # Cycle through the lists of strings to process:
        # 1. Re-compress the text
        # 2. Change the pointer to the first available address, mark it as done
        # 3. Find other strings with the same pointer that are not "done" yet, and update them as well
        # 4. Write the new pointers and compressed data to ROM
        # 5. Fill the unused memory with 0xFF (optional, but good practice)

        for i in range(256):
            # If this item was already done, skip it
            if special_list[i].done is False:

                # 1.
                packed_bytes = TextEditor.pack_text(special_list[i].text)
                special_list[i].text = packed_bytes

                # 2.
                old_address = special_list[i].address
                new_address = memory.allocate_memory(len(packed_bytes), "special")

                if new_address == 0:
                    end_address = new_address + len(packed_bytes) - 1
                    self.app.errorBox("Out of boundaries",
                                      "ERROR: The compressed text does not fit into the reserved memory area.\n"
                                      "Please reduce the size of your text before trying again."
                                      f"Special string 0x{i:02X} (#{i})\n"
                                      f"Start address: 0x{new_address:04X}\nEnd address: 0x{end_address:04X}",
                                      "Text_Editor")
                    raise Exception(f"Address 0x{new_address:04X} is out of bounds.")

                special_list[i].address = new_address
                special_list[i].done = True

                # 3.
                for s in range(i + 1, 256):
                    if special_list[s].done is False and special_list[s].address == old_address:
                        special_list[s].address = new_address
                        special_list[s].text = packed_bytes
                        special_list[s].done = True
                    if s < 0xE6 and dialogue_list[s].done is False and dialogue_list[s].address == old_address:
                        dialogue_list[s].address = new_address
                        dialogue_list[s].text = packed_bytes
                        dialogue_list[s].done = True

        # We process dialogue strings in a separate loop, to have the addresses more or less consistent
        for i in range(0xE6):
            if dialogue_list[i].done is False:

                # 1.
                packed_bytes = TextEditor.pack_text(dialogue_list[i].text)
                dialogue_list[i].text = packed_bytes

                # 2.
                old_address = dialogue_list[i].address
                new_address = memory.allocate_memory(len(packed_bytes), "normal")
                if new_address == 0:
                    # Ask to expand the normal strings area (unsafe)
                    choice = self.app.yesNoBox("Out of bounds", "WARNING: The compressed text does not fit into the "
                                                                "reserved memory area.\n\n"
                                                                "Do you want to try expanding outside of this area?\n"
                                                                "Note that this operation is unsafe and may result in "
                                                                "corrupted text.")
                    if choice is False:
                        return

                    # Try expanding the memory area
                    memory.normal_end = 0xBC7F
                    new_address = memory.allocate_memory(len(packed_bytes), "normal")

                    # Check again
                    if new_address == 0:
                        end_address = new_address + len(packed_bytes) - 1
                        self.app.errorBox("Out of bounds",
                                          "ERROR: The compressed text does not fit into the reserved memory area.\n"
                                          "Please reduce the size of your text before trying again.\n\n"
                                          f"Dialogue string 0x{i:02X} (#{i})\n"
                                          f"Start address: 0x{new_address:04X}\nEnd address: 0x{end_address:04X}",
                                          "Text_Editor")
                        raise Exception(f"Address 0x{new_address:04X} is out of bounds.")

                dialogue_list[i].address = new_address
                dialogue_list[i].done = True

                # 3.
                for s in range(i + 1, 0xE6):
                    if dialogue_list[s].done is False and dialogue_list[s].address == old_address:
                        dialogue_list[s].address = new_address
                        dialogue_list[s].text = packed_bytes
                        dialogue_list[s].done = True
                    # No need to go through special strings as they are all done by now

        # 4.
        address = 0x8000  # Pointers
        for i in range(256):
            data_address = special_list[i].address
            self.rom.write_word(0x5, address, data_address)

            for byte in special_list[i].text:
                self.rom.write_byte(0x5, data_address, int(byte))
                data_address = data_address + 1

            # Move to the next pointer
            address = address + 2

        address = 0x9D80  # Pointers
        for i in range(0xE6):
            data_address = dialogue_list[i].address
            self.rom.write_word(0x5, address, data_address)

            for byte in dialogue_list[i].text:
                self.rom.write_byte(0x5, data_address, int(byte))
                data_address = data_address + 1

            # Move to the next pointer
            address = address + 2

        # 5. Fill remaining space with 0xFF

        for address in range(memory.special_first, memory.special_end + 1):
            # Write 0xFF
            self.rom.write_byte(0x5, address, 0xFF)

        for address in range(memory.normal_first, memory.normal_end + 1):
            self.rom.write_byte(0x5, address, 0xFF)

        # --- Uncompressed text ---

        # Rebuild Enemy Names pointers
        address_first = 0xBCFA
        address_end = 0xBE6F

        # Create the helper list
        names_list = []
        for i in range(len(self.enemy_name_pointers)):
            names_list.append(TextEditor.StringListItem(self.enemy_names[i], self.enemy_name_pointers[i]))

        # Cycle through items in the list
        for i in range(len(names_list)):
            if names_list[i].done is True:
                continue

            # Get ASCII text, for comparison
            ascii_text = names_list[i].text

            # Convert to U:E bytes
            exodus_text = ascii_to_exodus(ascii_text)
            exodus_text.append(0xFF)

            # Make sure it fits in memory
            if address_first + len(exodus_text) > address_end:
                self.app.errorBox("Out of bounds", f"'{ascii_text}' does not fit inside the memory area reserved "
                                                   " for Enemy Name strings.\nPlease shorten your text and try again.")
                return

            # Assign new pointer and text
            names_list[i].address = address_first
            names_list[i].text = exodus_text
            names_list[i].done = True

            # Check if any other items share the same text
            for c in range(i + 1, len(names_list)):
                if names_list[c].done is False and names_list[c].text == ascii_text:
                    names_list[c].text = exodus_text
                    names_list[c].address = address_first
                    names_list[c].done = True

            # Advance first available address
            address_first = address_first + len(exodus_text)

        # Save changes to ROM
        address_first = 0xBC80
        for i in range(len(names_list)):
            # Write 16-bit pointer
            address_text = names_list[i].address
            self.rom.write_word(0x5, address_first, address_text)
            address_first = address_first + 2

            # Write text
            for e in names_list[i].text:
                self.rom.write_byte(0x5, address_text, e)
                address_text = address_text + 1

        # Rebuild NPC Names pointers

        address_first = 0x00
        address_end = 0xFF

        # Helper list
        names_list = []

        # These pointers are the low byte of the full address; the high byte is always 0xA7
        for i in range(len(self.npc_name_pointers)):
            names_list.append(TextEditor.StringListItem(self.npc_names[i], self.npc_name_pointers[i]))

        for i in range(len(names_list)):
            # Get old address, so we can update the existing dialogue indices later
            old_address = names_list[i].address

            # Encode text and add string terminator
            exodus_text = ascii_to_exodus(names_list[i].text)
            exodus_text.append(0xFF)

            # Make sure the name fits in ROM
            if address_first + len(exodus_text) > address_end:
                self.app.errorBox("Out of bound", f"ERROR: The NPC name '{names_list[i].text}' does not fit "
                                                  "in the memory area reserved for these strings.\n"
                                                  "Please reduce the length of the name strings and try again.")
                return

            # Update entry
            names_list[i].address = address_first
            names_list[i].text = exodus_text
            names_list[i].done = True

            # Replace all instances of the old pointer to the new one
            for address in range(0x9690, 0x9740):
                value = self.rom.read_byte(0xB, address)
                if value == old_address:
                    self.rom.write_byte(0xB, address, address_first)

            # Update first available address
            address_first = address_first + len(exodus_text)

        self.app.setStatusbar("Text pointers successfully rebuilt")

    # ------------------------------------------------------------------------------------------------------------------

    def save_enemy_names(self) -> None:
        """
        Stores Enemy names shown in the battle screen in ROM and rebuilds their pointers table
        """
        # Create a new, empty list for the new pointers
        new_pointers: List[int] = []
        for _ in self.enemy_name_pointers:
            new_pointers.append(-1)

        first_address = 0xBCFA      # Pointer to the first name string
        end_address = 0xBE6F        # No names should go past this address
        name_data = bytearray()     # This will contain encoded name data

        index = 0
        for name in self.enemy_names:
            # 0. Skip if name had already been processed (e.g. points to a previously processed name)
            if new_pointers[index] > -1:
                index = index + 1
                continue

            # 1. Find room for this name in ROM (add one byte for string terminator)
            size = len(name) + 1
            if first_address + size > end_address:
                self.app.errorBox("Save Enemy Names", f"ERROR: '{name}' does not fit in ROM.\n"
                                  f"Please use shorter names and try again.",
                                  parent="Text_Editor")
                return

            # 2. Save new pointer
            new_pointers[index] = first_address

            # 3. Also update the pointer of any other names that match this one
            for n in range(index, len(self.enemy_names)):
                if self.enemy_names[n] == name:
                    new_pointers[n] = first_address

            # 4. Encode the string and prepare it for saving to ROM
            encoded = ascii_to_exodus(name)
            encoded.append(0xFF)
            name_data = name_data + encoded

            # 5. Advance index and pointer
            index = index + 1
            first_address = first_address + size

        # Save encoded text to ROM
        self.rom.write_bytes(0x5, 0xBCFA, name_data)

        # Save pointers
        address = 0xBC80
        for p in new_pointers:
            self.rom.write_word(0x5, address, p)
            address = address + 2

        # Update cached pointers
        self.enemy_name_pointers = new_pointers

    # ------------------------------------------------------------------------------------------------------------------

    def read_menu_text(self) -> None:
        # Read Menu/Intro pointers from ROM
        self.menu_text_pointers.clear()
        self.menu_text.clear()

        # Table at 0C:A675-A6C6 (82 bytes = 41 pointers)
        address = 0xA675
        for _ in range(41):
            self.menu_text_pointers.append(self.rom.read_word(0xC, address))
            address = address + 2

        # Use these pointers to read Menu / Intro strings, then convert them to ASCII
        for pointer in self.menu_text_pointers:
            data = bytearray()
            address = pointer
            value = self.rom.read_byte(0xC, address)
            address = address + 1
            while value != 0xFF:
                data.append(value)
                value = self.rom.read_byte(0xC, address)
                address = address + 1
            self.menu_text.append(exodus_to_ascii(data))

    # ------------------------------------------------------------------------------------------------------------------

    def save_menu_text(self) -> None:
        """
        Stores the uncompressed text used for the intro and pre-game menus to the ROM buffer, and
        rebuilds the pointers
        """

        # First usable address
        start_address = 0xA6C7
        # Last usable address
        end_address = 0xAEC1

        # The hacked ROM has some space reserved to pre-made character data, so it needs to use
        # our helper class
        string_memory = TextEditor.StringMemoryInfo()
        string_memory.normal_first = 0xA6C7
        string_memory.normal_end = 0xA940
        string_memory.special_first = 0xAA9A
        string_memory.special_end = 0xAEC1

        for i in range(41):
            # Convert text to nametable indices
            data: bytearray = ascii_to_exodus(self.menu_text[i])

            # Add string termination character if not present
            if len(data) == 0 or data[-1] != 0xFF:
                data.append(0xFF)

            size: int = len(data)

            if self.rom.has_feature("enhanced party"):
                if 0xF <= i <= 0x16:
                    # Ignore strings 0x0F-0x16 for the hacked game, since the pre-made characters are managed
                    # in a completely different way
                    continue
                else:
                    # See if the current string fits in the first area
                    address = string_memory.allocate_memory(size, "normal")
                    if address == 0:
                        self.app.errorBox("Text Editor", "ERROR: Could not allocate memory for Menu strings.\n" +
                                          "Please try reducing the size of these strings.",
                                          parent="Text_Editor")
                        return
                    self.rom.write_bytes(0xC, address, data)

                    # Update pointer
                    self.menu_text_pointers[i] = address

            else:
                # Find a space that can contain the current string
                # Calculate potential end address
                end = start_address + size
                # Out of bounds?
                if end >= end_address:
                    self.app.errorBox("Text Editor", "ERROR: Could not allocate memory for Menu strings.\n" +
                                      "Please try reducing the size of these strings.",
                                      parent="Text_Editor")
                    return

                # Otherwise save string and update first available address
                self.rom.write_bytes(0xC, start_address, data)
                # Update pointer
                self.menu_text_pointers[i] = start_address
                start_address = end

        # Save all pointers
        # Table at 0C:A675-A6C6 (82 bytes = 41 pointers)
        address = 0xA675
        for p in self.menu_text_pointers:
            self.rom.write_word(0xC, address, p)
            address = address + 2

    # ------------------------------------------------------------------------------------------------------------------

    def save_npc_names(self) -> None:
        """
        Stores NPC names shown during dialogue in ROM and rebuilds their pointers
        """
        # Create a new, empty list for the new pointers
        new_pointers: List[int] = []
        for _ in self.npc_name_pointers:
            new_pointers.append(-1)

        first_address = 0xA700  # This will be the pointer to the first name string
        end_address = 0xA7FF    # No names should go past this address
        name_data = bytearray()

        index = 0
        for name in self.npc_names:
            # 0. Skip this name if already processed (e.g. points to a previously processed name)
            if new_pointers[index] > -1:
                index = index + 1
                continue

            # 1. Find room for this name in ROM
            size = len(name) + 1
            if first_address + size > end_address:
                self.app.errorBox("Save NPC Names", f"ERROR: '{name}' does not fit in ROM.\n"
                                                    f"Please use shorter names and try again.",
                                  parent="Text_Editor")
                return

            # 2. Save the new pointer
            new_pointers[index] = first_address

            # 3. Also update the pointer of any other names that match this one
            for n in range(index, len(self.npc_names)):
                if self.npc_names[n] == name:
                    new_pointers[n] = first_address & 0xFF

            # 4. Encode the string and save it to ROM
            encoded = ascii_to_exodus(name)
            encoded.append(0xFF)
            name_data = name_data + encoded

            # 5. Advance index and pointer
            index = index + 1
            first_address = first_address + size

        # Save encoded text to ROM
        self.rom.write_bytes(0xB, 0xA700, name_data)

        # Update dialogue name pointers
        for i in range(256):
            address = 0xA600 + i
            # 1. Read pointer
            pointer = self.rom.read_byte(0xB, address)

            # 2. Find to which entry it corresponds in the old table
            if pointer != 0xFF:
                try:
                    index = self.npc_name_pointers.index(pointer)

                    # 3. Store the corresponding pointer from the new table
                    self.rom.write_byte(0xB, address, new_pointers[index])
                except ValueError:
                    log(3, f"{self}", f"Invalid NPC name pointer for dialogue 0x{i:02X} = 0x{pointer:02X}."
                                      f" Setting to default: no name.")
                    self.rom.write_byte(0xB, address, 0xFF)
                    continue

        # Update our pointers cache
        self.npc_name_pointers = new_pointers

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

    # ------------------------------------------------------------------------------------------------------------------

    def close_special_window(self) -> bool:
        # Ask confirmation if there are unsaved changes
        if self._special_unsaved_changes:
            if not self.app.yesNoBox("Special Dialogue Function Editor", "Are you sure you want to close this window?" +
                                     "\nAny unsaved changes will be lost.", "Special_Dialogue"):
                return False

        self.app.hideSubWindow("Special_Dialogue", useStopFunction=False)
        self.app.emptySubWindow("Special_Dialogue")
        self._special_unsaved_changes = False

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def show_special_window(self, dialogue_id: int, location_names: List[str]) -> None:
        try:
            self.app.openSubWindow("Special_Dialogue")
            window_exists = True
        except appJar.appjar.ItemLookupError:
            window_exists = False

        self._special_unsaved_changes = False
        self.special_index = dialogue_id - 0xF0
        address = self.rom.read_word(0xF, 0xC6CD + (self.special_index << 1))
        self._special_routine = Routine(address=address)

        self._location_names = location_names

        # Find and open definitions file
        rom_base = os.path.splitext(self.rom.path)[0]  # Dir + file name, no ext
        rom_file = os.path.basename(rom_base)     # File name, no dir, no ext

        if os.path.exists(rom_base + ".def"):
            # Found definitions file in ROM folder
            file_name = rom_base + ".def"
        elif os.path.exists(rom_file + ".def"):
            # Found definitions file in editor's folder
            file_name = rom_file + ".def"
        elif os.path.exists("Ultima - Exodus Remastered.def"):
            # Fallback definitions file
            file_name = "Ultima - Exodus Remastered.def"
            self.warning("No routine definitions file found. Using default definitions for Remastered version.")
        else:
            # No definitions found
            file_name = ""

        self._special_definitions = file_name

        if window_exists:
            # Empty existing sub-window
            self.app.emptySubWindow("Special_Dialogue")
            generator = self.app.subWindow("Special_Dialogue")
        else:
            # Create sub-window
            generator = self.app.subWindow("Special_Dialogue", title="Special Dialogue Function Editor",
                                           size=[480, 320], padding=[2, 2], resizable=False,
                                           bg=colour.DARK_OLIVE, fg=colour.WHITE, modal=False, blocking=False,
                                           stopFunction=self.close_special_window)

        # Create widgets
        with generator:
            with self.app.frame("SD_Frame_Info", 0, 0, sticky="NEW", padding=[4, 2]):
                self.app.button("SD_Button_Apply", self._special_input, image="res/floppy.gif", bg=colour.LIGHT_OLIVE,
                                tooltip="Save Changes", row=0, column=0, sticky="NW")
                self.app.button("SD_Button_Reload", self._special_input, image="res/reload.gif", bg=colour.LIGHT_OLIVE,
                                tooltip="Reload from ROM buffer", row=0, column=1, sticky="NW")
                self.app.button("SD_Button_Cancel", self._special_input, image="res/close.gif", bg=colour.LIGHT_OLIVE,
                                tooltip="Cancel Changes and Close", row=0, column=2, sticky="NW")

                self.app.label("SD_Label_Index", f"             Index: 0x{dialogue_id:02X}, Address:", row=0, column=3,
                               sticky="SE", font=11)
                self.app.entry("SD_Routine_Address", f"0x{address:04X}",
                               tooltip="Address in bank 08", submit=self._special_input,
                               bg=colour.DARK_GREEN, fg=colour.LIGHT_ORANGE,
                               width=8, row=0, column=4, sticky="SW", font=10)

            with self.app.scrollPane("SD_Pane_Parameters", 1, 0, sticky="NEWS", padding=[4, 2], bg=colour.DARK_GREEN):
                self._read_special_routine()

        self.app.showSubWindow("Special_Dialogue")

    # ------------------------------------------------------------------------------------------------------------------

    def _read_special_routine(self) -> None:
        if self._special_definitions == "":
            self.app.message("SD_Message_Error", "NO ROUTINE DEFINITIONS FOUND", sticky="NEWS",
                             fg=colour.PALE_RED, width=740, row=0, column=0, font=16)
        else:
            parser = configparser.ConfigParser()
            try:
                parser.read(self._special_definitions)

                section = parser[f"SPECIAL_{self.special_index}"]

                row = 0

                n = section.get("NOTES")
                if n is not None:
                    self.app.message(f"SD_Notes", n, width=740, sticky="NEW", row=row, column=0, colspan=3, font=11)
                    row += 1

                self._special_routine.bank = int(section.get("BANK", "0xD"), 16)

                for p in range(32):
                    description = section.get(f"DESCRIPTION_{p}")
                    if description is None:
                        break

                    # Description found: create new parameter
                    param = Parameter(description=description)

                    tooltip = section.get(f"TOOLTIP_{p}", f"Value for parameter {p}")

                    pointer = int(section.get(f"POINTER_{p}", "0xFFFF"), 16)
                    if pointer == 0xFFFF:
                        address = self._special_routine.address
                    else:
                        address = self.rom.read_word(self._special_routine.bank,
                                                     self._special_routine.address + pointer)

                    offsets = section.get(f"OFFSET_{p}", "0").split(',')
                    param.address = [(address + int(n, 16)) for n in offsets]

                    param.bank = 0xF if param.address[0] >= 0xC000 else self._special_routine.bank

                    param_type = section.get(f"TYPE_{p}", "H")[0]
                    param.type = Parameter.get_type(param_type)

                    if param_type == "T":
                        table_index = section.get(f"INDEX_TYPE_{p}", "D")[0]
                        param.table_index_type = Parameter.get_type(table_index)

                        value_type = section.get(f"VALUE_TYPE_{p}", "D")[0]
                        param.table_type = Parameter.get_type(value_type)

                        table_size = int(section.get(f"SIZE_{p}", "1"), 10)

                        param.table_address = self.rom.read_word(param.bank, param.address[0])

                        address = param.table_address
                        for v in range(table_size):
                            if param.table_type == Parameter.TYPE_WORD or param.table_type == Parameter.TYPE_CHECK:
                                param.table_values.append(self.rom.read_word(param.bank, address))
                                address += 2
                            else:
                                param.table_values.append(self.rom.read_byte(param.bank, address))
                                address += 1

                        copy_values = section.get(f"TABLE_COPY_{p}", "")
                        if copy_values != "":
                            param.table_copy = [self._special_routine.address + int(value, 16)
                                                for value in copy_values.split(',')]

                    # Read value
                    if param.type == Parameter.TYPE_POINTER or param_type == Parameter.TYPE_CHECK:
                        param.value = self.rom.read_word(param.bank, param.address[0])
                    elif param.type == Parameter.TYPE_TABLE:
                        pass
                    else:
                        param.value = self.rom.read_byte(param.bank, param.address[0])

                    # Add the newly created parameter to our routine instance
                    self._special_routine.parameters.append(param)

                    # Finally create the necessary widgets depending on its type
                    self.app.label(f"SD_Description_{p:02}", description, row=row, column=0, sticky="E", font=11)

                    if param.type == Parameter.TYPE_DECIMAL:
                        self.app.entry(f"SD_Value_{p:02}", f"{param.value}", tooltip=tooltip, sticky="W", width=6,
                                       change=self._special_input,
                                       bg=colour.MEDIUM_OLIVE, fg=colour.WHITE, row=row, column=1, colspan=2, font=10)

                    elif param.type == Parameter.TYPE_HEX:
                        self.app.entry(f"SD_Value_{p:02}", f"0x{param.value:02X}", tooltip=tooltip, sticky="W", width=6,
                                       change=self._special_input,

                                       bg=colour.MEDIUM_OLIVE, fg=colour.WHITE, row=row, column=1, colspan=2, font=10)

                    elif param.type == Parameter.TYPE_STRING:
                        self.app.entry(f"SD_Value_{p:02}", f"0x{param.value:02X}", tooltip=tooltip, sticky="W", width=6,
                                       change=self._special_input,
                                       bg=colour.MEDIUM_OLIVE, fg=colour.WHITE, row=row, column=1, font=10)
                        self.app.button(f"SD_Edit_String_{p:02}", self._special_input, image="res/edit-dlg-small.gif",
                                        sticky="W", width=16, height=16, tooltip="Edit this string", row=row, column=2)

                    elif param.type == Parameter.TYPE_MARK:
                        marks = read_text(self.rom, 0xC, 0xA608).splitlines(False)
                        self.app.optionBox(f"MARKS Param {p:02}", marks, kind="ticks",
                                           change=self._special_input,
                                           width=14, sticky="NEW", row=row, column=1, colspan=2, font=9)
                        bit = 1
                        for b in range(4):
                            if (param.value & bit) != 0:
                                self.app.setOptionBox(f"MARKS Param {p:02}", marks[b],
                                                      value=True, callFunction=False)
                            else:
                                self.app.setOptionBox(f"MARKS Param {p:02}", marks[b],
                                                      value=False, callFunction=False)
                            bit = bit << 1

                    elif param.type == Parameter.TYPE_TABLE:
                        # Table index
                        if param.table_index_type == Parameter.TYPE_LOCATION:
                            row += 1
                            self.app.optionBox(f"SD_Index_{p:02}", self._location_names[:len(param.table_values)],
                                               tooltip="Table index", change=self._special_input,
                                               sticky="WE", row=row, column=0, colspan=2, font=10)

                        elif param.table_index_type == Parameter.TYPE_DECIMAL:
                            indices = [f"{n}" for n in range(0, len(param.table_values))]
                            self.app.optionBox(f"SD_Index_{p:02}", indices, tooltip="Table index",
                                               change=self._special_input,
                                               width=5, sticky="W", row=row, column=1, font=10)

                        elif param.table_index_type == Parameter.TYPE_HEX:
                            indices = [f"0x{n:02X}" for n in range(0, len(param.table_values))]
                            self.app.optionBox(f"SD_Index_{p:02}", indices, tooltip="Table index",
                                               change=self._special_input,
                                               width=5, sticky="W", row=row, column=1, font=10)

                        else:
                            # Default index type: same as decimal
                            indices = [f"{n}" for n in range(0, len(param.table_values))]
                            self.app.optionBox(f"SD_Index_{p:02}", indices, tooltip="Table index",
                                               change=self._special_input,
                                               width=5, sticky="W", row=row, column=1, font=10)

                        # Table value
                        if param.table_type == Parameter.TYPE_WORD:
                            self.app.entry(f"SD_Table_Value_{p:02}", f"{param.table_values[0]}", tooltip=tooltip,
                                           bg=colour.MEDIUM_OLIVE, fg=colour.WHITE, change=self._special_input,
                                           width=6, sticky="W", row=row, column=2, font=10)
                        elif param.table_type == Parameter.TYPE_HEX:
                            self.app.entry(f"SD_Table_Value_{p:02}", f"0x{param.table_values[0]:02X}", tooltip=tooltip,
                                           bg=colour.MEDIUM_OLIVE, fg=colour.WHITE, change=self._special_input,
                                           width=6, sticky="W", row=row, column=2, font=10)
                        elif param.table_type == Parameter.TYPE_STRING:
                            self.app.entry(f"SD_Table_Value_{p:02}", f"0x{param.table_values[0]:02X}", tooltip=tooltip,
                                           bg=colour.MEDIUM_OLIVE, fg=colour.WHITE, change=self._special_input,
                                           width=6, sticky="W", row=row, column=2, font=10)
                            self.app.button(f"SD_Edit_Table_String_{p:02}", self._special_input,
                                            image="res/edit-dlg-small.gif", tooltip="Edit this string",
                                            width=16, height=16, sticky="W", row=row, column=3)
                        else:
                            # TODO Support other value types (LOCATION, BOOL, NPC...)
                            self.app.entry(f"SD_Table_Value_{p:02}", f"{param.table_values[0]}", tooltip=tooltip,
                                           bg=colour.MEDIUM_OLIVE, fg=colour.WHITE, change=self._special_input,
                                           width=6, sticky="W", row=row, column=2, font=10)

                    else:
                        self.app.label(f"SD_Unsupported_{p:02}", "Unsupported parameter type", sticky="W",
                                       fg=colour.PALE_RED, row=row, column=1, colspan=2, font=11)

                    # Move down one row for the next parameter
                    row += 1

            except configparser.ParsingError as error:
                self.app.message("SD_Message_Error", f"Error parsing '{self._special_definitions}':\n{error}",
                                 sticky="NEWS", width=740, fg=colour.PALE_RED, row=0, column=0, font=12)
            except TypeError as error:
                self.app.message("SD_Message_Error", f"Error parsing '{self._special_definitions}':\n{error}",
                                 sticky="NEWS", width=740, fg=colour.PALE_RED, row=0, column=0, font=12)
            except KeyError:
                self.app.message("SD_Message_Error", "No definitions found for this dialogue.", sticky="NEWS",
                                 fg=colour.PALE_RED, width=740, row=0, column=0, font=12)
            except ValueError or configparser.DuplicateOptionError or IndexError as error:
                self.app.message("SD_Message_Error", f"Error parsing '{self._special_definitions}':\n{error}",
                                 sticky="NEWS", width=740, fg=colour.PALE_RED, row=0, column=0, font=12)

    # ------------------------------------------------------------------------------------------------------------------

    def _save_special_routine(self) -> bool:
        """
        Returns
        -------
        bool
            True is successfully saved, False otherwise (e.g. address out of boundary)
        """
        for param in self._special_routine.parameters:

            for param_address in param.address:
                bank = param.bank if param_address < 0xC000 else 0xF

                if param.type == Parameter.TYPE_TABLE:
                    address = param.table_address
                    bank = 0xF if address >= 0xC000 else param.bank

                    for v in range(len(param.table_values)):

                        # 16-bit table value
                        if param.table_type == Parameter.TYPE_WORD:
                            self.rom.write_word(bank, address, param.table_values[v])
                            address += 2

                            if len(param.table_copy) > (v * 2):
                                # Low byte
                                c = v << 1
                                self.rom.write_byte(bank, param.table_copy[c], param.table_values[v] & 0x00FF)
                                # High byte
                                c += 1
                                self.rom.write_byte(bank, param.table_copy[c], param.table_values[v] >> 8)

                        # 8-bit table values
                        else:
                            self.rom.write_byte(bank, address, param.table_values[v])
                            address += 1

                            if len(param.table_copy) > v:
                                self.rom.write_byte(bank, param.table_copy[v], param.table_values[v])

                elif param.type == Parameter.TYPE_WORD or param.type == Parameter.TYPE_CHECK:
                    # 16-bit values
                    self.rom.write_word(bank, param_address, param.value)

                else:
                    # Everything else is an 8-bit value
                    self.rom.write_byte(bank, param_address, param.value)

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def _special_input(self, widget: str) -> None:
        if widget == "SD_Button_Apply":     # --------------------------------------------------------------------------
            if self._save_special_routine():
                self.app.setStatusbar(f"Special routine 0x{self.special_index:02X} saved.")
                self._special_unsaved_changes = False
                # Close window depending on settings
                if self.settings.get("close sub-window after saving"):
                    self.close_special_window()
            else:
                self.app.soundError()
                self.app.errorBox("Special Dialogue Editor", "Errors encountered while saving routine parameters.\n" +
                                  "Check offsets and table sizes in definitions file.", "Special_Editor")

        elif widget == "SD_Button_Reload":  # --------------------------------------------------------------------------
            with self.app.scrollPane("SD_Pane_Parameters"):
                self.app.emptyCurrentContainer()
                self._read_special_routine()
                self._special_unsaved_changes = False

        elif widget == "SD_Button_Cancel":  # --------------------------------------------------------------------------
            self.close_special_window()

        elif widget[:9] == "SD_Value_":     # --------------------------------------------------------------------------
            p = int(widget[-2:])
            param = self._special_routine.parameters[p]

            text = self.app.getEntry(widget)

            try:
                base = 16 if text[:2] == "0x" else 10
                value = int(text, base)
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget(widget).selection_range(0, "end")
                return

            # Make sure 8-bit values are 8-bit long
            if value > 0xFF:
                if param.type != Parameter.TYPE_WORD and param.type != Parameter.TYPE_CHECK:
                    self.app.soundError()
                    self.app.getEntryWidget(widget).selection_range(0, "end")
                    return

            # All good, assign value
            param.value = value
            self._special_unsaved_changes = True

        elif widget[:15] == "SD_Edit_String_":  # ----------------------------------------------------------------------
            p = int(widget[-2:])

            try:
                value = int(self.app.getEntry(f"SD_Value_{p:02}"), 16)
                self.show_advanced_window(value, "Special")
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget(f"SD_Value_{p:02}").selection_range(0, "end")

        elif widget[:21] == "SD_Edit_Table_String_":    # --------------------------------------------------------------
            p = int(widget[-2:])

            try:
                value = int(self.app.getEntry(f"SD_Table_Value_{p:02}"), 16)
                self.show_advanced_window(value, "Special")
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget(f"SD_Table_Value_{p:02}").selection_range(0, "end")

        elif widget[:12] == "MARKS Param ":     # ----------------------------------------------------------------------
            p = int(widget[-2:])
            param = self._special_routine.parameters[p]
            values = self.app.getOptionBox(widget)

            bit_mask = 0
            bit = 1

            for tick in values:
                if values.get(tick, False):
                    bit_mask |= bit

                bit = bit << 1

            param.value = bit_mask
            self._special_unsaved_changes = True

        elif widget[:9] == "SD_Index_":     # --------------------------------------------------------------------------
            p = int(widget[-2:])
            param = self._special_routine.parameters[p]

            selection = self._get_selection_index(widget)
            try:
                value = param.table_values[selection]
            except IndexError:
                self.app.errorBox("Special Dialogue Editor", f"Selection for parameter #{p} out of range.\n" +
                                  "Wrong list size in definition file?",
                                  "Special_Dialogue")
                return

            destination = f"SD_Table_Value_{p:02}"
            # The widget type where we write this value depends on the value type in the table
            if param.table_type == Parameter.TYPE_HEX or param.table_type == Parameter.TYPE_STRING:
                self.app.clearEntry(destination, callFunction=False, setFocus=True)
                self.app.setEntry(destination, f"0x{value:02X}", callFunction=False)
            elif param.table_type == Parameter.TYPE_LOCATION:
                self.app.setOptionBox(destination, value, callFunction=False)
            else:
                self.app.clearEntry(destination, callFunction=False, setFocus=True)
                self.app.setEntry(destination, f"{value}", callFunction=False)

        else:   # ------------------------------------------------------------------------------------------------------
            self.info(f"Unimplemented input from widget: '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def close_customise_window(self) -> None:
        self.app.hideSubWindow("Dictionary_Editor")
        self.app.emptySubWindow("Dictionary_Editor")
        self._charset_canvas = None
        self._charset_items = [0] * 256
        self._charset_selection = 0

    # ------------------------------------------------------------------------------------------------------------------

    def show_customise_window(self) -> None:
        # Check if window already exists
        try:
            self.app.getFrameWidget("TC_Frame_Buttons")
            self.app.showSubWindow("Dictionary_Editor")
            return

        except appJar.appjar.ItemLookupError:
            generator = self.app.subWindow("Dictionary_Editor", size=[380, 220], padding=[2, 2],
                                           title="Customise Character Mappings",
                                           resizable=False, modal=True, blocking=True,
                                           bg=colour.DARK_VIOLET, fg=colour.WHITE,
                                           stopFunction=self.close_customise_window)
        app = self.app

        with generator:

            with app.frame("TC_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0, colspan=3):

                app.button("TC_Apply", self._customise_input, image="res/floppy.gif", bg=colour.LIGHT_VIOLET,
                           row=0, column=1, sticky="W", tooltip="Save all changes")
                app.button("TC_Reload", self._customise_input, image="res/reload.gif", bg=colour.LIGHT_VIOLET,
                           row=0, column=2, sticky="W", tooltip="Reload from saved settings")
                app.button("TC_Close", self._customise_input, image="res/close.gif", bg=colour.LIGHT_VIOLET,
                           row=0, column=3, sticky="W", tooltip="Discard changes and close")

            with app.frame("TC_Frame_Parameters", padding=[4, 2], sticky="NEW", row=1, column=0):
                app.label("TC_Label_0", "Mappings:", sticky="WE", row=0, column=0, colspan=2)
                app.listBox("TC_List_Dictionary", [], multi=False, group=True, sticky="W", width=12, height=5,
                            row=1, column=0, colspan=2, font=10, change=self._customise_input)
                app.button("TC_Add_Entry", self._customise_input, image="res/mapping-new.gif", sticky="WE",
                           row=2, column=0, height=32, tooltip="New Mapping", bg=colour.PALE_VIOLET)
                app.button("TC_Del_Entry", self._customise_input, image="res/eraser.gif", sticky="WE",
                           row=2, column=1, height=32, tooltip="Remove Mapping", bg=colour.PALE_VIOLET)

            with app.frame("TC_Frame_Mapping", padding=[2, 2], sticky="NEW", row=1, column=1):
                app.label("TC_Label_1", "Edit Mapping", row=0, column=0, colspan=2, sticky="WE", font=11)

                app.label("TC_Label_2", "CHR:", row=1, column=0, font=11, sticky="E")
                app.entry("TC_Mapping_Chr", "", bg=colour.PALE_VIOLET, fg=colour.BLACK,
                          row=1, column=1, width=3, limit=1, font=10, sticky="W")
                app.label("TC_Label_3", "TID:", row=2, column=0, font=11, sticky="E")
                app.entry("TC_Mapping_Tile", "0x00", bg=colour.PALE_VIOLET, fg=colour.BLACK,
                          row=2, column=1, width=5, limit=4, font=10, sticky="W")

                app.button("TC_Edit_Tile", self._customise_input, image="res/pencil-small.gif", height=16,
                           row=4, column=0, sticky="WE", bg=colour.DARK_VIOLET)
                app.button("TC_Update_Entry", self._customise_input, image="res/check_green-small.gif", height=16,
                           row=4, column=1, sticky="WE", bg=colour.DARK_VIOLET)

            self._charset_canvas = app.canvas("TC_Canvas_Charset", width=128, height=128, bg=colour.BLACK,
                                              row=1, column=2)

        app.setCanvasCursor("TC_Canvas_Charset", "hand1")

        self._charset_canvas.bind("<ButtonRelease-1>", self._select_custom_tile, add='')

        # Show the whole charset
        if len(self._chr_tiles) == 0:
            self._load_text_patterns()

        for y in range(16):
            for x in range(16):
                c = x + (y << 4)
                self._charset_items[c] = self._charset_canvas.create_image(x * 8, y * 8,
                                                                           anchor="nw", image=self._chr_tiles[c])

        self._selected_char = 0
        self._charset_selection = self._charset_canvas.create_rectangle(0, 0, 8, 8, width=1, outline=colour.MEDIUM_RED)

        # We do everything with lists, then create dictionaries from them when saving

        self.custom_ascii, self.custom_exodus = self._load_custom_mappings()

        list_items = []
        for character, value in self.custom_ascii:
            list_items.append(f"'{character}' -> 0x{value:02X}")
        app.addListItems("TC_List_Dictionary", list_items, False)

        if len(list_items) > 0:
            app.selectListItemAtPos("TC_List_Dictionary", 0, True)

        app.showSubWindow("Dictionary_Editor")

    # ------------------------------------------------------------------------------------------------------------------

    def _customise_input(self, widget: str) -> None:
        global _ascii_dict, _exodus_dict

        if widget == "TC_Apply":    # ----------------------------------------------------------------------------------
            # First, check for duplicated items from the default mappings and remove them
            for i in range(len(self.custom_ascii)):     # The two lists must have the same size
                if _ASCII_DICT.get(self.custom_ascii[i]) is not None:
                    self.custom_ascii.pop(i)
                if _EXODUS_DICT.get(self.custom_exodus[i]) is not None:
                    self.custom_exodus.pop(i)

            # Note: no need to worry about duplicates withing the lists themselves as they will be automatically
            # ignored by dict()

            # Turn the lists into dictionaries and create the final dictionaries that we will use
            if len(self.custom_ascii) > 0 and len(self.custom_exodus) > 0:
                d = dict(self.custom_ascii)
                _ascii_dict = {**_ASCII_DICT, **d}
                d = dict(self.custom_exodus)
                _exodus_dict = {**_EXODUS_DICT, **d}

            # Save these in settings file too...

            # Re-create the whole section
            if self.settings.config.has_section("MAPPINGS"):
                self.settings.config.remove_section("MAPPINGS")
            self.settings.config.add_section("MAPPINGS")

            # Add items
            for c, v in self.custom_ascii:
                self.settings.config.set("MAPPINGS", f"{ord(c)}", f"0x{v:02X}")

            # All done
            if self.settings.get("close sub-window after saving"):
                self.close_customise_window()

        elif widget == "TC_Close":  # ----------------------------------------------------------------------------------
            self.close_customise_window()

        elif widget == "TC_Reload":     # ------------------------------------------------------------------------------
            self.custom_ascii, self.custom_exodus = self._load_custom_mappings()

            self.app.clearListBox("TC_List_Dictionary", False)

            list_items = []
            for character, value in self.custom_ascii:
                list_items.append(f"'{character}' -> 0x{value:02X}")
            self.app.addListItems("TC_List_Dictionary", list_items, False)

            if len(list_items) > 0:
                self.app.selectListItemAtPos("TC_List_Dictionary", 0, True)

        elif widget == "TC_List_Dictionary":    # ----------------------------------------------------------------------
            selection = self.app.getListBoxPos(widget)

            if len(selection) < 1:
                return

            char, value = self.custom_ascii[selection[0]]

            # Show and select ASCII/Unicode character
            self.app.clearEntry("TC_Mapping_Chr", callFunction=False, setFocus=True)
            self.app.setEntry("TC_Mapping_Chr", char, callFunction=False)
            self.app.getEntryWidget("TC_Mapping_Chr").selection_range(0, "end")

            # Show value of tile mapped to it
            self.app.clearEntry("TC_Mapping_Tile", callFunction=False, setFocus=False)
            self.app.setEntry("TC_Mapping_Tile", f"0x{value:02X}", callFunction=False)

            # Move the selection rectangle there
            x = (value % 16) << 3
            y = (value >> 4) << 3
            self._charset_canvas.coords(self._charset_selection, x, y, x + 8, y + 8)

        elif widget == "TC_Add_Entry":  # ------------------------------------------------------------------------------
            if len(self.custom_ascii) > 9:
                self.app.errorBox("Customise Mappings", "Cannot define more than 10 custom mappings.",
                                  "Dictionary_Editor")
                return

            # Use the first unused tile ID
            ascii_char = 'ÿ'
            tile_id = 0xFF

            # TODO Find an unused character/tile?

            self.custom_ascii.append((ascii_char, tile_id))
            self.custom_exodus.append((tile_id, ascii_char))

            self.app.addListItems("TC_List_Dictionary", [f"'{ascii_char}' -> 0x{tile_id:02X}"], select=True)

            self.app.clearEntry("TC_Mapping_Chr", callFunction=False, setFocus=True)
            self.app.setEntry("TC_Mapping_Chr", ascii_char, callFunction=False)
            self.app.getEntryWidget("TC_Mapping_Chr").selection_range(0, "end")

            self.app.clearEntry("TC_Mapping_Tile", callFunction=False, setFocus=False)
            self.app.setEntry("TC_Mapping_Tile", f"0x{tile_id:02X}", callFunction=False)

            x = (tile_id % 16) << 3
            y = (tile_id >> 4) << 3
            self._charset_canvas.coords(self._charset_selection, x, y, x + 8, y + 8)

        elif widget == "TC_Del_Entry":  # ------------------------------------------------------------------------------
            selection = self.app.getListBoxPos("TC_List_Dictionary")

            if len(selection) < 1:
                return

            del self.custom_ascii[selection[0]]
            del self.custom_exodus[selection[0]]
            self.app.removeListItemAtPos("TC_List_Dictionary", selection[0])

            # If there is at least one entry left, set a selection
            if len(self.custom_ascii) > 0:
                self.app.selectListItemAtPos("TC_List_Dictionary", 0, callFunction=True)

        elif widget == "TC_Edit_Tile":  # ------------------------------------------------------------------------------
            try:
                tile_id = int(self.app.getEntry("TC_Mapping_Tile"), 16)
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("TC_Mapping_Tile").selection_range(0, "end")
                return

            self.tile_editor.show(0xA, 0x8000 + (tile_id << 4), 0)

            # Refresh the tiles
            self._load_text_patterns()
            for y in range(16):
                for x in range(16):
                    c = x + (y << 4)
                    self._charset_canvas.itemconfigure(self._charset_items[c], image=self._chr_tiles[c])

            self.app.getEntryWidget("TC_Mapping_Chr").focus_set()

        elif widget == "TC_Update_Entry":   # --------------------------------------------------------------------------
            selection = self.app.getListBoxPos("TC_List_Dictionary")

            if len(selection) < 1:
                self.app.soundError()
                return

            index = selection[0]

            # New keys/values
            character = self.app.getEntry("TC_Mapping_Chr")
            try:
                tile_id = int(self.app.getEntry("TC_Mapping_Tile"), 16)
            except ValueError:
                self.app.soundError()
                self.app.getEntryWidget("TC_Mapping_Tile").selection_range(0, "end")
                return

            # Make sure these are valid entries
            if len(character) < 1:
                self.app.soundError()
                self.app.getEntryWidget("TC_Mapping_Chr").selection_range(0, "end")
                return

            # Replace the key that was previously at this index
            self.custom_ascii[index] = (character, tile_id)
            self.custom_exodus[index] = (tile_id, character)

            self.app.setListItemAtPos("TC_List_Dictionary", index, f"'{character}' -> 0x{tile_id:02X}")

        else:   # ------------------------------------------------------------------------------------------------------
            self.warning(f"Unimplemented input from Customisation widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _load_custom_mappings(self) -> (List, List):
        mappings_ascii = []
        mappings_exodus = []

        config = self.settings.config

        if config.has_section("MAPPINGS"):
            section = config["MAPPINGS"]

            # Keep count: we can only hold 10 custom mappings
            m = 0
            for character, value in section.items():
                # Values are in the form: ASCII/Unicode (int) = Tile ID (hex)
                # e.g.: 1064=0x8A
                try:
                    character = chr(int(character)).upper()
                except ValueError:
                    self.warning(f"Found invalid mapping for '{character}' in config file.")
                    continue

                try:
                    tile_id = int(value, 16)
                except ValueError:
                    self.warning(f"Found invalid mapping for tile ID '{value}' config file.")
                    continue

                # Make sure we have a valid ID
                if tile_id > 0xFF:
                    self.warning(f"Found invalid mapping with tile ID '{value}' in config file.")
                    continue

                # Also make sure it's not trying to replace a default one
                if _ASCII_DICT.get(character, -1) != -1:
                    self.warning(f"Cannot replace default value for character '{character}'.")
                    continue
                if _EXODUS_DICT.get(tile_id, -1) != -1:
                    self.warning(f"Cannot replace default value for tile ID '{value}'.")
                    continue

                mappings_ascii.append((character, tile_id))
                mappings_exodus.append((tile_id, character))

                m += 1
                if m > 9:
                    break

        return mappings_ascii, mappings_exodus

    # ------------------------------------------------------------------------------------------------------------------

    def _select_custom_tile(self, event: any) -> None:
        x = (event.x >> 3) << 3
        y = (event.y >> 3) << 3

        tile_id = (x >> 3) + (y << 1)

        self.app.clearEntry("TC_Mapping_Tile", callFunction=False, setFocus=False)
        self.app.setEntry("TC_Mapping_Tile", f"0x{tile_id:02X}", callFunction=False)

        self._charset_canvas.coords(self._charset_selection, x, y, x + 8, y + 8)
