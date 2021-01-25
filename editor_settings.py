__author__ = "Fox Cunning"

import os
from dataclasses import dataclass


# ----------------------------------------------------------------------------------------------------------------------
from debug import log


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

    # ------------------------------------------------------------------------------------------------------------------

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

    # ------------------------------------------------------------------------------------------------------------------

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
            if key == "make backups" or key == "sync npc sprites" or key == "fix envelope bug":
                if value.lower() == "true" or value == "1" or value.lower() == "yes":
                    value = True
                else:
                    value = False

            elif key == "sample rate":
                value = int(value, 10)

            # Assign the value read from file
            self._keys[key] = value
        except KeyError or ValueError:
            log(2, "EDITOR", f"Invalid setting '{key}' in line '{line}'.")

        return

    # ------------------------------------------------------------------------------------------------------------------

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

    # ------------------------------------------------------------------------------------------------------------------
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
