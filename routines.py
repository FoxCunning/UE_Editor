# --- PartyEditor.AttributeCheck class ---
from dataclasses import dataclass, field
from typing import List


@dataclass(init=True, repr=False)
class AttributeCheck:
    """
    Helper class for the magic system: pointers to subroutines used to roll a Level/INT/WIS check
    """
    name: str = ""
    address: int = 0


# --- PartyEditor.Parameter class ---

@dataclass(init=True, repr=False)
class Parameter:
    """
    A helper sub-class to store spell parameter data
    """
    # Bank 0xF if address >= 0xC000; banks 0x0 and 0x6 otherwise
    address: int = 0
    # Could be a byte (e.g. for LDA or CMP), or word (e.g. for a JMP or JSR instruction)
    value: int = 0
    # Description that will be displayed in the editor
    description: str = ""
    # Type is used to choose what kind of UI to build for this parameter, values can be:
    # 0 = Decimal, 1 = 8-bit Hex, 2 = 16-bit Address, 3 = Attribute index, 4 = Dialogue ID
    type: int = 0
    # Constants used for types
    TYPE_DECIMAL = 0
    TYPE_HEX = 1
    TYPE_POINTER = 2
    TYPE_ATTRIBUTE = 3
    TYPE_BOOL = 4
    TYPE_STRING = 5
    TYPE_CHECK = 6
    TYPE_LOCATION = 7
    TYPE_MARK = 8


# --- PartyEditor.Routine class ---
@dataclass(init=True, repr=False)
class Routine:
    """
    A helper class used to store routine data (magic, tools, commands, special dialogue...)
    """
    # Parameters for each specific spell
    parameters: list = field(default_factory=list)
    # Ignored for actual spells, used in the UI only by common routines that are unnamed in the game
    name: str = ""
    # Notes will appear in the UI when this spell is selected
    notes: str = ""
    # Flags determine when/where a spell can be used (e.g. dungeon, battle, everywhere, etc.)
    flags: int = 0
    # Fine flags are used in the second check, for example to make a spell work only on one specific map
    fine_flags: int = 0
    # MP needed for the spell to appear on the caster's list of available spells
    mp_display: int = 0
    # MP actually consumed upon casting the spell / number of items consumed on use
    mp_cast: int = 0
    # Address where the MP to cast value is stored in ROM
    mp_address: int = 0
    # Address of the subroutine, in bank 0xF
    address: int = 0
    # This will be True if the spell code was not recognised and parameters could not be extracted
    custom_code: bool = True