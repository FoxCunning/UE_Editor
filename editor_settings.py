__author__ = "Fox Cunning"

import configparser
import os
from dataclasses import dataclass

# ----------------------------------------------------------------------------------------------------------------------
from typing import Union

from debug import log


@dataclass(init=True, repr=False)
class EditorSettings:
    """
    A fairly generic class for keeping track of settings, loading/saving etc.
    """
    SETTINGS_FILE: str = "settings.conf"
    config: configparser.ConfigParser = configparser.ConfigParser()
    _path: str = ""

    KEYS = {"last rom path": "",
            "make backups": True,
            "close sub-window after saving": False,
            "emulator": "",
            "emulator parameters": "%%f",
            "last map import path": "",
            "last map export path": "",
            "last music import path": "",
            "last music export path": "",
            "editor fonts": "Consolas",
            "sync npc sprites": True,
            "fix envelope bug": True,
            "sample rate": 44100,
            "audio host": "directsound"
            }

    # ------------------------------------------------------------------------------------------------------------------

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
        self._path: str = os.path.realpath(__file__)
        try:
            last = self._path.rindex('\\')
        except ValueError:
            try:
                last = self._path.rindex('/')
            except ValueError:
                # Does not look like a directory name
                return False
        self._path = self._path[:last + 1]
        self._path = self._path + EditorSettings.SETTINGS_FILE

        try:
            self.config.read(self._path)
        except configparser.ParsingError:
            log(3, "EditorSettings", "Could not load settings from file. A default one will be created.")

            self.config.add_section("SETTINGS")
            for k in EditorSettings.KEYS:
                self.config.set("SETTINGS", k, EditorSettings.KEYS.get(k))

            self.config.write(open(self._path, "w"))

        return True

    # ------------------------------------------------------------------------------------------------------------------

    def save(self) -> bool:
        """
        Saves current settings to file

        Returns
        -------
        bool
            True if settings were successfully saved. False otherwise.
        """
        success = True

        try:
            self.config.write(open(self._path, "w"))

        except IOError as error:
            log(2, "EditorSettings", f"Error saving configuration file: '{error}'.")
            success = False

        return success

    # ------------------------------------------------------------------------------------------------------------------

    def get(self, key: str) -> Union[int, bool, str]:
        if (key == "make backups" or key[:8] == "sync npc" or key[:12] == "fix envelope" or
                key[:16] == "close sub-window"):
            return self.config.getboolean("SETTINGS", key, fallback=True)

        if key == "sample rate":
            return self.config.getint("SETTINGS", key, fallback=44100)

        return self.config.get("SETTINGS", key, fallback="")

    # ------------------------------------------------------------------------------------------------------------------

    def set(self, key: str, value: Union[int, bool, str]) -> None:
        self.config.set("SETTINGS", key, value)
