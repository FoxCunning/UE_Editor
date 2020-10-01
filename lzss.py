"""Based on code by Darren A.K.A. "Phantasm"
"""

__author__ = "Fox Cunning"
__credits__ = ["Fox Cunning", "Darren A.K.A. 'Phantasm'", "Michael Dipperstein (hash key implementation)"]

from debug import log

from io import BytesIO

WINDOW_SIZE = 256
MAX_UNENCODED = 2
MAX_CODED = MAX_UNENCODED + 256
HASH_SIZE = 1024


class FlagData:
    def __init__(self):
        pass

    flag_position: int = 0
    flags: int = 0
    next_encoded: int = 0


# --- update_flags() ---

def update_flags(flag_data: FlagData, encoded_data: bytearray, writer: BytesIO):
    if flag_data.flag_position == 0x80:
        writer.write(flag_data.flags.to_bytes(1, "little"))
        for i in range(flag_data.next_encoded):
            writer.write(encoded_data[i].to_bytes(1, "little"))

        flag_data.flags = 0
        flag_data.flag_position = 1
        flag_data.next_encoded = 0

    else:
        flag_data.flag_position = flag_data.flag_position << 1


# --- EncodedString ---

class EncodedString:
    def __init__(self):
        pass

    offset: int = 0
    length: int = 0


hash_table: list  # list = [0] * HASH_SIZE


# --- get_hash_key() ---

def get_hash_key(data: any, offset: int) -> int:
    """This method generates a hash key for a (MAX_UNENCODED + 1)
       long string
    """
    hash_key: int = 0

    for i in range(0, MAX_UNENCODED + 1):
        hash_key = (hash_key << 5) ^ data[offset]
        hash_key = hash_key % HASH_SIZE
        offset = offset + 1

    return hash_key


# --- find_match() ---

def find_match(data: any, offset: int) -> EncodedString:
    """This method searches through the data or the longest sequence matching the MAX_CODED
       long string that is before the current offset
    """
    match_data = EncodedString()

    if offset > len(data) - (MAX_UNENCODED + 1):
        return match_data

    j = 0

    key_index = get_hash_key(data, offset)
    hash_key = hash_table[key_index]
    for i in hash_key:

        if i >= offset:
            continue

        if i < offset - WINDOW_SIZE:
            continue

        # First symbol matched
        if data[i] == data[offset]:

            j = 1

            while (offset + j) < len(data) and data[i + j] == data[offset + j]:
                if j >= MAX_CODED:
                    break
                j = j + 1

            if j > match_data.length:
                match_data.length = j
                match_data.offset = i

        if j >= MAX_CODED:
            match_data.length = MAX_CODED
            break

    return match_data


# --- encode() ---

def encode(data: any) -> memoryview:
    """
    Perform LZSS Algorithm Encoding
    """
    global hash_table

    writer = BytesIO()
    input_buffer = bytearray(data)

    length = len(input_buffer)
    if length == 0:
        return memoryview(bytes(0))

    # Start with an empty list
    hash_table = list()
    for i in range(0, HASH_SIZE):
        hash_table.append([])

    flag_data = FlagData()

    # 8 code flags and 8 encoded strings
    flag_data.flags = 0
    flag_data.flag_position = 1
    encoded_data = bytearray(256 * 8)
    flag_data.next_encoded = 0  # Next index of encoded data

    input_buffer_position = 0  # Head of encoded lookahead

    for i in range(0, length - MAX_UNENCODED):
        hash_key = get_hash_key(input_buffer, i)
        hash_table[hash_key].append(i)

    match_data = find_match(input_buffer, input_buffer_position)

    while input_buffer_position < length:

        # Extend match length if trailing rubbish is present
        if input_buffer_position + match_data.length > length:
            match_data.length = length - input_buffer_position

        # Write unencoded byte if match is not long enough
        if match_data.length <= MAX_UNENCODED:

            match_data.length = 1  # 1 unencoded byte

            flag_data.flags = flag_data.flags | flag_data.flag_position  # Flag unencoded byte
            encoded_data[flag_data.next_encoded] = input_buffer[input_buffer_position]
            flag_data.next_encoded = flag_data.next_encoded + 1
            update_flags(flag_data, encoded_data, writer)

        # Encode as offset and length if match length >= max unencoded
        else:
            match_data.offset = (input_buffer_position - 1) - match_data.offset
            if match_data.offset > 255 or match_data.offset < 0:
                log(2, "LZZ encode", "Match Data Offset out of range!")
                return memoryview(bytes(0))
            if match_data.length - (MAX_UNENCODED + 1) > 255:
                log(2, "LZSS encode", "Match Data Length out of range!")
                return memoryview(bytes(0))

            encoded_data[flag_data.next_encoded] = match_data.offset
            flag_data.next_encoded = flag_data.next_encoded + 1

            encoded_data[flag_data.next_encoded] = match_data.length - (MAX_UNENCODED + 1)
            flag_data.next_encoded = flag_data.next_encoded + 1
            update_flags(flag_data, encoded_data, writer)

        input_buffer_position = input_buffer_position + match_data.length

        # Find next match
        match_data = find_match(input_buffer, input_buffer_position)

    # Write any remaining encoded data
    if flag_data.next_encoded != 0:
        writer.write(flag_data.flags.to_bytes(1, "little"))
        for i in range(0, flag_data.next_encoded):
            writer.write(encoded_data[i].to_bytes(1, "little"))

    return writer.getbuffer()


# --- decode() ---

def decode(data: bytes) -> bytearray:
    """
    Performs LZSS decoding

    Parameters
    ----------
    data: bytes
        A string of bytes to decompress

    Returns
    -------
    bytearray
        A bytearray containing the uncompressed data
    """
    reader = BytesIO(data)

    flags = 0  # Encoded flag
    flags_used = 7  # Unencoded flag

    out_data = bytearray()

    while True and len(out_data) < 4096:

        flags = flags >> 1
        flags_used = flags_used + 1

        # If all flag bits have been shifted out, read a new flag
        if flags_used == 8:

            if reader.tell() == len(reader.getbuffer()):
                break

            flags = reader.read(1)[0]
            flags_used = 0

        # Found an unencoded byte
        if (flags & 1) != 0:

            if reader.tell() == len(reader.getbuffer()):
                break

            out_data.append(reader.read(1)[0])

        # Found encoded data
        else:

            if reader.tell() == len(reader.getbuffer()):
                break

            code_offset = reader.read(1)[0]

            if reader.tell() == len(reader.getbuffer()):
                break

            code_length = reader.read(1)[0] + MAX_UNENCODED + 1

            for i in range(0, code_length):
                out_data.append(out_data[len(out_data) - (code_offset + 1)])

    return out_data
