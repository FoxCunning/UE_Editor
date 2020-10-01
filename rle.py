"""
An implementation of the RLE algorithm used by Konami and others

Control byte    ->  Action
00-7F	            Read another byte, and write it to the output n times.
80                  Write the following 256 bytes
81-FE	            Copy n - 128 bytes from input to output.
FF	                End of compressed data
"""

__author__ = "Fox Cunning"
__credits__ = ["Fox Cunning", "Derrick Sobodash <derrick@sobodash.com>"]


class RLE:

    def __init__(self):
        pass


# --- encode() ---

def encode(data: bytearray) -> bytearray:
    """Encode data into RLE compressed format

    Parameters
    ----------
    data: bytearray
        A bytearray containing the data to be encoded

    Returns
    -------
    bytearray
        A bytearray containing the RLE encoded data
    """
    output = bytearray()

    run = bytearray()

    running = False

    i = 0
    while i < len(data):
        value = data[i]

        last = i
        count = 0

        while i < len(data) and data[i] == value:
            count = count + 1
            i = i + 1

        if count > 2:
            if running:
                output.append(0x80 + len(run))
                output = output + run

            while count > 0x7F:
                output.append(0x7F)
                output.append(value)
                count = count - 0x7F

            output.append(count)
            output.append(value)

            running = False

        else:
            if running is False:
                run = bytearray(data[last:i])
                running = True

            else:
                if len(run) > 0xFC - 0x80:
                    output.append(0x80 + len(run))
                    output = output + run
                    running = False

                else:
                    run = run + bytearray(data[last:i])

    if running:
        output.append(0x80 + len(run))
        output = output + run

    # Add terminator character
    output.append(0xFF)

    return output


# --- decode() ---

def decode(data: bytearray) -> bytearray:
    """Decode RLE compressed data

    Parameters
    ----------
    data: bytearray
        Bytes to decode

    Returns
    -------
    bytearray
        A bytearray containing the decompressed data
    """

    output = bytearray()

    i = 0
    for _ in range(0, len(data)):
        control = data[i] & 0xFF

        if control < 0x80:
            # Read next byte
            i = i + 1
            value = data[i] & 0xFF

            # then write it to the output 'control' times
            for o in range(0, control):
                output.append(value)

            i = i + 1

        elif control == 0x80:
            # Read next 256 bytes and write them to output
            count = 256
            i = i + 1
            for o in range(i, i + count):
                value = data[o] & 0xFF
                output.append(value)
            i = i + count

        elif control < 0xFF:
            # Read the next 'control - 128' bytes and copy them to output
            count = control - 128
            i = i + 1
            for o in range(i, i + count):
                value = data[o] & 0xFF
                output.append(value)
            i = i + count

        else:
            break

    return output
