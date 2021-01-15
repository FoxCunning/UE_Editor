__author__ = "Fox Cunning"

import os
from typing import List

from debug import log
from rom import ROM


class MusicEditor:

    def __init__(self, rom: ROM):
        self.rom = rom

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
    def read_music_titles(self) -> List[str]:
        music_titles: List[str] = []

        rom_file = os.path.splitext(self.rom.path)[0]
        if os.path.exists(f"music_{rom_file}"):
            file_name = f"music_{rom_file}"
        else:
            file_name = "music.txt"

        try:
            file = open(file_name, "r")
            music_titles = file.readlines()
            file.close()

            for m in range(len(music_titles)):
                music_titles[m] = music_titles[m].rstrip("\n\a\r")

        except OSError as error:
            self.error(f"Could not read '{file_name}'.")

        return music_titles
