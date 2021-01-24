__author__ = "Fox Cunning"

from typing import List

from PIL import Image, ImageTk

from appJar import gui
from debug import log
from rom import ROM


# --- _convert_unpacked() ---

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


# --- _convert_packed() ---

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


# --- _ascii_to_exodus() ---

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

    switcher = {
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
            exodus_string.append(switcher.get(ascii_string[c], 0x00))

        c = c + 1

    return exodus_string


# --- _exodus_to_ascii() ---

def exodus_to_ascii(exodus_string: bytearray) -> str:
    """
    Converts a string stored as pattern IDs + special characters to an ASCII sting.
    Non-printable characters will be turned into escape sequences in the form '\\xNN' where NN is the original
    8-bit value

    Parameters
    ----------
    exodus_string

    Returns
    -------
    str
        The converted ASCII string
    """
    ascii_string = ""

    switcher = {
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

    for char in exodus_string:
        if 0x8A <= char <= 0xA3:
            ascii_string = ascii_string + chr(char - 0x49)
        elif 0x38 <= char <= 0x41:
            ascii_string = ascii_string + chr(char - 0x08)
        else:
            value = switcher.get(char, '#')
            if value == '#':
                value = f"\\x{char:02X}"
            ascii_string = ascii_string + value

    return ascii_string


# --- read_text() ---

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


# --- _empty_image() ---

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


# --- TextEditor ---

class TextEditor:

    def __init__(self, rom: ROM, colours: list, app: gui):

        self.text: str = ""  # Text being edited (uncompressed)
        self.type: str = ""  # String type (determines where the pointer is)
        self.index: int = -1  # Index of the pointer to this string
        self.address: int = 0  # Address of compressed text in bank 05

        self.changed: bool = False  # Set this to True when the text has been modified

        self.npc_name_pointers: List[int] = [0]  # Pointer to NPC name for this dialogue
        self.npc_names: List[str] = []  # NPC name as read from ROM using the above pointer

        self.enemy_name_pointers: List[int] = []  # Pointers to enemy names
        self.enemy_names: List[str] = []  # Enemy name strings as read from ROM

        self.menu_text_pointers: List[int] = []
        self.menu_text: List[str] = []

        # Reference to the global ROM instance
        self.rom: ROM = rom

        # Colours used to draw portrait previews
        self.colours: List[int] = colours
        # print("DEBUG: Text/portrait colours:")
        # for c in self.colours:
        #     print(f"0x{c:02X}")

        # Compressed text pointer tables
        self.dialogue_text_pointers: List[int] = []  # Dialogue text, 0xE6 pointers at 05:9D90
        self.special_text_pointers: List[int] = []  # Special text, 0x100 pointers at 05:8000

        # Cached uncompressed text
        self.dialogue_text: List[str] = []
        self.special_text: List[str] = []

        self.app: gui = app

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
                log(3, f"{self}", f"Error parsing portrait descriptions file: {error}.")

            file.close()

        except IOError:
            log(3, f"{self}", "Could not read portrait descriptions file.")

        log(4, f"{self}", "Pre-loading text strings...")

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

        # Read Menu/Intro pointers from ROM
        self.read_menu_text()

        # Read and uncompress dialogue / special strings
        self.uncompress_all_string()

        log(4, f"{self}", "Text loaded.")

    # --- TextEditor.uncompress_all_strings() ---

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

    # --- TextEditor.unpack_text() ---

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

    # --- TextEditor.pack_text ---

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

    # --- TextEditor.show_window() ---

    def show_window(self, string_id: int, string_type: str) -> None:
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

        self.changed = False

        if string_type == "Dialogue":
            self.address = self.dialogue_text_pointers[string_id]
            self.text = self.dialogue_text[string_id]
        elif string_type == "Special":
            self.address = self.special_text_pointers[string_id]
            self.text = self.special_text[string_id]
        elif string_type == "NPC Names":
            self.address = self.npc_name_pointers[string_id]
            self.text = self.npc_names[string_id]
        elif string_type == "Enemy Names":
            self.address = self.enemy_name_pointers[string_id]
            self.text = self.enemy_names[string_id]
        elif string_type == "Menus / Intro":
            self.address = self.menu_text_pointers[string_id]
            self.text = self.menu_text[string_id]
        else:
            log(3, "TEXT EDITOR", f"Invalid string type '{string_type}'.")
            return

        self.app.clearTextArea("TE_Text")
        self.app.setTextArea("TE_Text", self.text)
        self.app.setLabel("TE_Label_Type", f"{string_type} Text")
        self.app.setEntry("TE_Entry_Address", f"0x{self.address:02X}")

        if string_type == "Dialogue" or string_type == "Special":
            # Populate NPC names OptionBox
            names = ["(0xFF) No Name"]
            for i in range(len(self.npc_name_pointers)):
                names.append(f"(0x{self.npc_name_pointers[i]:02X}) {self.npc_names[i]}")
            # for name in self.npc_names:
            #    names.append(name)
            self.app.clearOptionBox("TE_Option_Name")
            self.app.changeOptionBox("TE_Option_Name", names)
            # Select "No Name" by default
            self.app.setOptionBox("TE_Option_Name", 0)

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
                    self.app.setOptionBox("TE_Option_Name", 0)
                else:  # Find pointer in names OptionBox
                    for i in range(len(self.npc_name_pointers)):
                        if pointer == self.npc_name_pointers[i]:
                            self.app.setOptionBox("TE_Option_Name", i + 1)
                            break
            else:
                self.app.setOptionBox("TE_Option_Name", 0)
        # else:
        #     app.setOptionBox("TE_Option_Name", 0)

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

    # --- TextEditor.modify_text() ---

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
            log(3, "TEXT EDITOR", f"Invalid string type for modify_text: '{self.type}'.")
            return

        self.app.clearTextArea("Text_Preview")
        self.app.setTextArea("Text_Preview", new_text)

    # --- TextEditor.hide_window() ---

    def hide_window(self, confirm_quit: bool = True) -> bool:
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
        if confirm_quit is True and self.changed is True:
            choice = self.app.questionBox("Confirm", "Unsaved changes will be lost. Continue?")
            if choice is False:
                return False

        self.app.hideSubWindow("Text_Editor", useStopFunction=False)
        # self.text = ""
        # self.type = ""
        # self.index = 0
        # self.address = 0
        # self.app = None
        # self.changed = False

        return True

    # --- TextEditor.load_portrait() ---

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

    # --- StringList ---

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

    # --- StringMemoryInfo ---

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

    # --- TextEditor.rebuild_pointers() ---

    def rebuild_pointers(self) -> None:
        """
        Rebuilds the pointer tables for dialogues and special text
        """
        log(4, f"{self}", "Saving new special/dialogue text pointers...")

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

        log(4, f"{self}", "Text pointers rebuilt.")
        self.app.setStatusbar("Text pointers successfully rebuilt")

    # --- TextEditor.save_enemy_names() ---

    def save_enemy_names(self) -> None:
        """
        Stores Enemy names shown in the battle screen in ROM and rebuilds their pointers table
        """
        log(4, f"{self}", "Saving Enemy names/pointers...")

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

    # --- TextEditor.read_menu_test() ---

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

    # --- TextEditor.save_menu_text() ---

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

    # --- TextEditor.save_npc_names() ---

    def save_npc_names(self) -> None:
        """
        Stores NPC names shown during dialogue in ROM and rebuilds their pointers
        """
        log(4, f"{self}", "Saving NPC names/pointers for special/dialogue...")

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

        log(4, f"{self}", "NPC names/pointers successfully saved.")
