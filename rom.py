__author__ = "Fox Cunning"

# import sys
from array import array
from typing import Union, List

from PIL import Image

from debug import log


feature_names = ["custom map colours",
                 "extra map flags",
                 "map compression",
                 "portraits",
                 "2-colour sprites",
                 "special encounter",
                 "extra menu strings",
                 "enhanced party",
                 "new profession gfx",
                 "weapon gfx",
                 "map tilesets"]


# ----------------------------------------------------------------------------------------------------------------------

class ROM:
    """
    ROM handler class

    Attributes
    ----------
    path: str
        Full path of the ROM file
    size: int
        File size, in bytes
    trainer_size: int
        Size of the trainer, if any, in bytes
    """
    # --- constructor ---

    def __init__(self):
        self._romFile = None
        self.path: str = ""
        self._buf = []
        self.size: int = 0
        self.trainer_size: int = 0

        self._features = {"custom map colours": False,  # True if the ROM has a table with custom map colours
                          "extra map flags": False,     # True if the ROM supports Continent and Guards flags per map
                          "map compression": False,     # True if LZSS/RLE map compression is supported
                          "portraits":  False,          # True if the ROM supports dialogue names/portraits
                          "2-colour sprites": False,    # True if two-colour character sprites are supported
                          "special encounter": False,   # True if the special encounter (chest) is implemented
                          "extra menu strings": False,  # True if there is room for extra text in bank $0C (no pre-made)
                          "enhanced party": False,      # True if the new varied race/class attributes are supported
                          "new profession gfx": False,  # True if profession gfx for Status is 32x32 instead of 48x48
                          "weapon gfx": False,          # True if weapon gfx is shown when choosing attack direction
                          "map tilesets": False         # True if the ROM implements the tileset table (1 entry/map)
                          }

    # ------------------------------------------------------------------------------------------------------------------

    def open(self, file_name: str) -> any:
        """
        Opens a ROM file

        Parameters
        ----------
        file_name: str
            Full path of the file

        Returns
        -------
        any
            "OK" or error instance
        """
        self.close()
        try:
            self._romFile = open(file_name, "rb+")
        except OSError as err:
            self._romFile = None
            return err
        except Exception as err:
            self._romFile = None
            return err  # sys.exc_info()[0]

        # Buffer the whole file
        self._buf = array('B', self._romFile.read())
        self.path = file_name
        self.size = len(self._buf)
        self._romFile.close()

        # Detect features

        if self.read_word(0xB, 0x86AF) == 0x86FC:
            self._features["custom map colours"] = True
        else:
            self._features["custom map colours"] = False

        if self.read_byte(0xF, 0xC461) == 0x1F:
            self._features["extra map flags"] = True
        else:
            self._features["extra map flags"] = False

        if self.read_word(0xF, 0xF50F) == 0x8000:
            self._features["map compression"] = True
        else:
            self._features["map compression"] = False

        if self.read_byte(0xB, 0xAA1F) == 0xA5 and self.read_byte(0xB, 0xAA20) == 0x8C:
            self._features["portraits"] = True
        else:
            self._features["portraits"] = False

        if self.read_word(0xF, 0xCA1B) == 0xBD34:
            self._features["2-colour sprites"] = True
        else:
            self._features["2-colour sprites"] = False

        if self.read_word(0x0, 0xAFE8) == 0x0777:
            self._features["special encounter"] = True
        else:
            self._features["special encounter"] = False

        if self.read_word(0xC, 0x8094) == 0x8072:
            self._features["extra menu strings"] = False
        else:
            self._features["extra menu strings"] = True

        if self.read_word(0xC, 0x9192) == 0xB7C7:
            self._features["enhanced party"] = True
        else:
            self._features["enhanced party"] = False

        if self.read_byte(0xC, 0x96CE) == 4:
            self._features["new profession gfx"] = True
        else:
            self._features["new profession gfx"] = False

        if self.read_word(0xF, 0xD26E) == 0xFDF3:
            self._features["weapon gfx"] = True
        else:
            self._features["weapon gfx"] = False

        if self.read_word(0xA, 0x9DA9) == 0xFB9F:
            self._features["map tilesets"] = True
        else:
            self._features["map tilesets"] = False

        print(f"ROM Features:\n{self._features}")

        return "OK"

    # ------------------------------------------------------------------------------------------------------------------

    def close(self) -> None:
        """
        Closes the current ROM file
        """
        if self._romFile is not None:
            self._romFile.close()
            self._romFile = None
        self._buf = []
        self.size = 0
        self.trainer_size = 0
        self.path = ""

    # ------------------------------------------------------------------------------------------------------------------

    def header(self) -> list:
        """
        Reads the header from the cached ROM buffer

        Returns
        -------
        list
            The ROM header as a list of bytes
        """
        header: list = []
        if self.size < 16:
            return header
        return list(self._buf[0:16])

    # ------------------------------------------------------------------------------------------------------------------

    def write_word(self, bank: int, address: int, word: int) -> None:
        """
        Writes a 2-byte value to ROM, converting it to little indian

        Parameters
        ----------
        bank: int
            Destination bank number (0x00-0x0F)
        address: in
            Destination address (0x8000-0xFFFF)
        word: in
            The value to write
        """
        offset = self._get_offset(bank, address)
        value = word.to_bytes(2, "little")
        self._buf[offset] = int(value[0])
        self._buf[offset + 1] = int(value[1])

    # ------------------------------------------------------------------------------------------------------------------

    def write_byte(self, bank: int, address: int, byte: int) -> None:
        """
        Writes one byte to ROM at the specified address and bank

        Parameters
        ----------
        bank: int
            The bank number (0x00-0x0F)
        address: int
            The address at which to write (0x8000, 0xFFFF)
        byte: int
            The value to write
        """
        offset = self._get_offset(bank, address)
        self._buf[offset] = (byte & 0xFF)

    # ------------------------------------------------------------------------------------------------------------------

    def write_bytes(self, bank: int, address: int, data: Union[bytes, bytearray]) -> None:
        """
        Writes an arbitrary amount of data starting from the specified location

        Parameters
        ----------
        bank: int
            Bank number
        address: int
            Starting address
        data: Union[bytes, bytearray]
            The data to be written
        """
        offset = self._get_offset(bank, address)
        for i in range(0, len(data)):
            self._buf[offset + i] = data[i]

    # ------------------------------------------------------------------------------------------------------------------

    def read_byte(self, bank: int, address: int) -> int:
        """
        Returns one byte of data from the specified bank at the specified address (0x8000-0xFFFF)

        Parameters
        ----------
        bank: int
            ROM Bank number
        address: int
            Address in ROM

        Returns
        -------
        int
            The value at the requested Bank:Address
        """
        ofs = self._get_offset(bank, address)
        if ofs < self.size:
            return self._buf[ofs]
        else:
            raise Exception('Address / bank out of range')

    # --- ROM.read_bytes() ---

    def read_bytes(self, bank: int, address: int, count: int) -> bytearray:
        """
        Reads the specified number of bytes read from the desired bank:address

        Parameters
        ----------
        bank: int
            ROM Bank number
        address: int
            Address in ROM
        count: int
            The number of bytes to read

        Returns
        -------
        bytearray
            A byte array containing the values read from bank:address
        """
        ofs = self._get_offset(bank, address)
        output = bytearray()
        while ofs < self.size and count > 0:
            output.append(self._buf[ofs])
            ofs = ofs + 1
            count = count - 1
        return output

    # ------------------------------------------------------------------------------------------------------------------

    def read_signed_word(self, bank: int, address: int) -> int:
        """
        Reads a signed word (two bytes) of data from the specified bank at the specified address (0x8000-0xFFFF)

        Parameters
        ----------
        bank: int
            ROM Bank number
        address: int
            Address in ROM

        Returns
        -------
        int
            The two-bytes value at the desired bank:address as a signed int
        """
        ofs = self._get_offset(bank, address)

        if ofs < (self.size - 1):
            value = bytearray([self._buf[ofs], self._buf[ofs + 1]])
            return int.from_bytes(value, "little", signed=True)
        else:
            raise Exception("Address/ bank out of range")

    # ------------------------------------------------------------------------------------------------------------------

    def read_word(self, bank: int, address: int) -> int:
        """
        Reads a word (two bytes) of data from the specified bank at the specified address (0x8000-0xFFFF)

        Parameters
        ----------
        bank: int
            ROM Bank number
        address: int
            Address in ROM

        Returns
        -------
        int
            The two-bytes value at the desired bank:address
        """
        ofs = self._get_offset(bank, address)
        if ofs < (self.size - 1):
            lo = int(self._buf[ofs])
            hi = int(self._buf[ofs + 1])
            return (hi << 8) | (lo & 0xFF)
        else:
            raise Exception("Address/ bank out of range")

    # ------------------------------------------------------------------------------------------------------------------

    def write_pattern(self, bank: int, address: int, pixels: Union[list, bytearray]) -> None:
        # We need two offsets: one for each bit-plane
        ofs_0 = self._get_offset(bank, address)
        ofs_1 = ofs_0 + 8
        if ofs_1 > self.size:
            raise Exception("Address/ bank out of range")

        plane_0 = plane_1 = count = 0
        for c in pixels:
            # Each entry is two bits, we put each bit into a separate 8-bit 'plane'
            bit_0 = c & 0x1
            bit_1 = (c >> 1) & 0x1

            plane_0 = (plane_0 << 1) | bit_0
            plane_1 = (plane_1 << 1) | bit_1

            count += 1
            if count == 8:
                # We filled two 8-bit planes that make up a line of pixels
                self._buf[ofs_0] = plane_0
                ofs_0 += 1
                self._buf[ofs_1] = plane_1
                ofs_1 += 1

                plane_0 = plane_1 = count = 0

    # ------------------------------------------------------------------------------------------------------------------

    def _get_offset(self, bank: int, address: int) -> int:
        """
        Calculates the offset in the raw ROM file for reading data that would appear
        in 0x8000-0xFFFF once loaded in memory

        Parameters
        ----------
        bank: int
            ROM Bank number
        address: int
            Address in ROM

        Returns
        -------
        int
            The offset of the given bank:address in the ROM file
        """
        if bank == 0xF:
            ofs = 0x3C010 + self.trainer_size + address
            return ofs - 0xC000
        else:
            ofs = (bank * 0x4000) + 0x10 + self.trainer_size + address
            return ofs - 0x8000

    # ------------------------------------------------------------------------------------------------------------------

    def read_pattern(self, bank: int, address: int) -> list:
        """Read pixel data from an 8x8 pattern stored in ROM

        Parameters
        ----------
        bank: int
            ROM Bank number
        address: int
            Address in ROM

        Returns
        -------
        list
            Pattern data as a list of bytes
        """
        plane_0 = []
        plane_1 = []
        pixels = []
        # Read first plane (bit 0 of each pixel)
        for _ in range(8):
            plane_0.append(self.read_byte(bank, address))
            address = address + 1
        # Read second plane (bit 1 of each pixel)
        for _ in range(8):
            plane_1.append(self.read_byte(bank, address))
            address = address + 1
        # Combine the two planes
        for index in range(8):
            for _ in range(8):
                bit_0 = (plane_0[index] & 0x80) != 0
                bit_1 = (plane_1[index] & 0x80) != 0
                plane_0[index] = plane_0[index] << 1
                plane_1[index] = plane_1[index] << 1
                pixels.append((bit_1 << 1) | bit_0)
        return pixels

    # ------------------------------------------------------------------------------------------------------------------

    def save(self, file_name: str = '') -> bool:
        """
        Saves the currently opened ROM to file

        Parameters
        ----------
        file_name: str
            Full path of the file to save to. If unspecified, the current file will be overwritten

        Returns
        -------
        bool
            True on success, False otherwise
        """
        file = None

        try:
            file = open(file_name, "wb")

            # file.write(bytes(self.header()))
            file.write(bytes(self._buf))

            file.close()

        except OSError as error:
            log(2, f"{self}", f"{error} whilst saving as '{file_name}'.")
            if file is not None:
                file.close()
            return False

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def has_feature(self, feature: str) -> bool:
        """
        Use this method to determine whether the ROM supports a specific feature

        Parameters
        ----------
        feature: str
            A string describing the feature to test.
            Possible values:
            "custom map colours"

        Returns
        -------
        bool
            True if the ROM supports this feature, False otherwise
        """
        return self._features.get(feature, False)

    # ------------------------------------------------------------------------------------------------------------------

    def read_sprite(self, bank: int, address: int, colours: List[int]) -> Image.Image:
        """
        Reads 8x8 pattern data from ROM.

        Parameters
        ----------
        bank: int
            ROM bank containing the sprite's pattern
        address: int
            Address of the sprite's pattern
        colours: List[int]
            An array of colours in the form R, G, B, R, G, B, R, G, B...

        Returns
        -------
        Image.Image
            The resulting image with colour 0 set as transparent
        """
        pixels = bytes(bytearray(self.read_pattern(bank, address)))
        image = Image.frombytes('P', (8, 8), pixels)
        image.info['transparency'] = 0
        image.putpalette(colours)
        return image
