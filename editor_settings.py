__author__ = "Fox Cunning"

import configparser
import os

# ----------------------------------------------------------------------------------------------------------------------
import sys
from tkinter import font
from typing import Union

import appJar
import colour
from appJar import gui
from debug import log


class EditorSettings:
    """
    A fairly generic class for keeping track of settings, loading/saving etc.
    """
    SETTINGS_FILE: str = "settings.conf"
    KEYS = {"last rom path": "",
            "make backups": True,
            "close sub-window after saving": False,
            "emulator": "",
            "emulator parameters": "%f",
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

    def __init__(self):
        self.config: configparser.ConfigParser = configparser.RawConfigParser()
        self._path: str = ""
        self.app: Union[any, gui] = None
        self._unsaved = False

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
            self.warning("Could not load settings from file. A default one will be created.")

            self.config.add_section("SETTINGS")
            for k in EditorSettings.KEYS:
                try:
                    self.config.set("SETTINGS", k, EditorSettings.KEYS.get(k))
                except TypeError as error:
                    self.error(f"Error parsing option '{k}': {error}.")

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
            self.error(f"Error saving configuration file: '{error}'.")
            success = False

        return success

    # ------------------------------------------------------------------------------------------------------------------

    def get(self, key: str) -> Union[int, bool, str]:
        if (key == "make backups" or key[:8] == "sync npc" or key[:12] == "fix envelope" or
                key[:16] == "close sub-window"):
            try:
                return self.config.getboolean("SETTINGS", key, fallback=True)
            except ValueError:
                return True

        if key == "sample rate":
            try:
                return self.config.getint("SETTINGS", key, fallback=44100)
            except ValueError:
                return 44100

        try:
            return self.config.get("SETTINGS", key, fallback="")
        except ValueError:
            return ""

    # ------------------------------------------------------------------------------------------------------------------

    def set(self, key: str, value: Union[int, bool, str]) -> None:
        try:
            self.config.set("SETTINGS", key, f"{value}")
        except ValueError as error:
            self.error(f"Could not set '{key}' to '{value}': {error}.")

    # ------------------------------------------------------------------------------------------------------------------

    def close_settings_window(self) -> None:
        self.app.hideSubWindow("Settings")
        self.app.emptySubWindow("Settings")

    # ------------------------------------------------------------------------------------------------------------------

    def show_settings_window(self, app: gui) -> None:
        self.app = app

        # Check if window already exists
        try:
            self.app.getFrameWidget("SS_Frame_Buttons")
            self.app.showSubWindow("Settings")
            return

        except appJar.appjar.ItemLookupError:
            generator = self.app.subWindow("Settings", size=[420, 320], padding=[2, 2],
                                           title="Ultima: Exodus Editor - Settings",
                                           resizable=False, modal=False, blocking=False,
                                           bg=colour.PALE_BLUE, fg=colour.BLACK,
                                           stopFunction=self.close_settings_window)

        self._unsaved = False
        font_bold = font.Font(size=12, weight="bold")
        font_italic = font.Font(size=10, slant="italic")

        if sys.platform.find("win") > -1:
            audio_hosts = ["directsound", "mme", "asio", "wasapi", "wdm-ks"]
        else:
            audio_hosts = ["- Windows Only -"]

        with generator:

            with app.frame("SS_Frame_Buttons", padding=[4, 2], sticky="NEW", row=0, column=0):
                app.button("SS_Apply", self._settings_input, image="res/floppy.gif", bg=colour.PALE_BLUE,
                           row=0, column=1, sticky="W", tooltip="Save all changes")
                app.button("SS_Reload", self._settings_input, image="res/reload.gif", bg=colour.PALE_BLUE,
                           row=0, column=2, sticky="W", tooltip="Reload from file")
                app.button("SS_Close", self._settings_input, image="res/close.gif", bg=colour.PALE_BLUE,
                           row=0, column=3, sticky="W", tooltip="Discard changes and close")

            with app.scrollPane("SS_Pane_Settings", sticky="NEWS", row=1, column=0):

                app.label("SS_Label_General", "General Settings", sticky="WE",  fg=colour.DARK_BLUE,
                          row=0, column=0, font=font_bold)
                with app.frame("SS_Frame_General", padding=[4, 2], sticky="NEW", row=1, column=0):
                    app.checkBox("Set_Make_Backups", self.get("make backups"), text="Make backups", sticky="W",
                                 row=0, column=0, colspan=2, font=11, change=self._settings_input)
                    app.checkBox("Set_Close_After", self.get("close sub-window after saving"),
                                 text="Close sub-windows after saving changes", sticky="W",
                                 row=1, column=0, colspan=2, font=11, change=self._settings_input)
                    app.label("SS_Label_3", "Default fonts*", sticky="E", row=2, column=0, font=11)
                    app.entry("Set_Editor_Fonts", self.get("editor fonts"), sticky="W", width=16,
                              row=2, column=1, font=10, change=self._settings_input)

                app.label("SS_Label_Emulator", "Emulator Settings", sticky="WE", fg=colour.DARK_BLUE,
                          row=2, column=0, font=font_bold)
                with app.frame("SS_Frame_Emulator", padding=[4, 2], sticky="NEW", row=3, column=0):
                    app.label("SS_Label_0", "Emulator path:", sticky="E", row=0, column=0, font=11)
                    app.entry("Set_Emulator_Path", self.get("emulator"), sticky="WE", width=32, limit=256,
                              row=0, column=1, font=10, change=self._settings_input)
                    app.button("SS_Emulator_Browse", self._settings_input, image="res/folder_open-small.gif",
                               row=0, column=2, sticky="W", width=32, height=16, tooltip="Browse...")

                with app.frame("SS_Frame_Emulator_1", padding=[4, 2], sticky="NEW", row=4, column=0):
                    app.label("SS_Label_1", "Command line parameters:", sticky="E", row=0, column=0, font=11)
                    app.entry("Set_Emulator_Cmdline", self.get("emulator parameters"), sticky="WE",
                              change=self._settings_input,
                              row=0, column=1, font=10, tooltip="%f = full path of ROM file")

                app.label("SS_Label_Map", "Map Editor Settings", sticky="WE", fg=colour.DARK_BLUE,
                          row=5, column=0, font=font_bold)
                with app.frame("SS_Frame_Map_Editor", padding=[4, 2], sticky="NEW", row=6, column=0):
                    app.checkBox("Set_Sync_NPC_Sprites", self.get("sync npc sprites"), change=self._settings_input,
                                 row=0, column=0, font=10, text="Sync NPC Sprites")

                app.label("SS_Label_Audio", "Audio Settings", sticky="WE", fg=colour.DARK_BLUE,
                          row=7, column=0, font=font_bold)
                with app.frame("SS_Frame_Audio", padding=[4, 2], sticky="NEW", row=8, column=0):
                    app.checkBox("Set_Fix_Envelope", self.get("fix envelope bug"), text="Fix envelope bug by default*",
                                 row=0, column=0, colspan=2, sticky="W", font=10, change=self._settings_input)
                    app.label("SS_Label_2", "Sampling rate*", sticky="E", row=1, column=0, font=11)
                    app.entry("Set_Sampling_Rate", self.get("sample rate"), kind="numeric", sticky="W",
                              tooltip="For best results, this should be the same as your audio device's sampling rate.",
                              row=1, column=1, width=10, font=10, change=self._settings_input)
                    app.label("SS_Label_4", "Windows Audio Host*", sticky="E", row=2, column=0, font=11)
                    app.optionBox("Set_Audio_Host", audio_hosts, sticky="W", change=self._settings_input,
                                  row=2, column=1, font=10)

            app.label("SS_Label_Note", "*These settings will be applied the next time the application is launched",
                      row=9, column=0, font=font_italic, fg=colour.DARK_RED)

        app.getScrollPaneWidget("SS_Pane_Settings").canvas.configure(width=470, height=250)

        if sys.platform.find("win") > -1:
            host = audio_hosts.index(self.get("audio host"))
            if host > -1:
                app.setOptionBox("Set_Audio_Host", host, callFunction=False)

        app.showSubWindow("Settings")

    # ------------------------------------------------------------------------------------------------------------------

    def _settings_input(self, widget: str) -> None:
        if widget == "SS_Apply":    # ----------------------------------------------------------------------------------
            self._apply_settings()

            if self.save():
                if self.get("close sub-window after saving"):
                    self.close_settings_window()

        elif widget == "SS_Reload":     # ------------------------------------------------------------------------------
            if self._unsaved:
                if not self.app.yesNoBox("Settings", "Are you sure you want to reload all settings from file?\n" +
                                                     "Any unsaved changes will be lost.", "Settings"):
                    return
            self._reload_settings()

        elif widget == "SS_Close":  # ----------------------------------------------------------------------------------
            if self._unsaved:
                if not self.app.yesNoBox("Settings", "Are you sure you want to close this window?\n" +
                                         "Any unsaved changes will be lost.", "Settings"):
                    return

            self.close_settings_window()

        elif widget == "SS_Emulator_Browse":    # ----------------------------------------------------------------------
            if sys.platform.find("win") > -1:
                exe = ("Windows Executable", "*.exe")
            elif sys.platform.find("darwin") > -1:
                exe = ("Application Package", "*.app")
            else:
                exe = ("Shell Script", "*.sh")

            file_name = self.app.openBox("Select Emulator Executable", os.path.dirname(self.get("emulator")),
                                         [exe, ("All Files", "*.*")],
                                         asFile=False, parent="Settings", multiple=False)
            if file_name != "":
                self.app.setEntry("Set_Emulator_Path", file_name, False)
                self._unsaved = True

        elif widget[:4] == "Set_":
            self._unsaved = True

        else:   # ------------------------------------------------------------------------------------------------------
            self.warning(f"Unimplemented input from Settings widget '{widget}'.")

    # ------------------------------------------------------------------------------------------------------------------

    def _reload_settings(self) -> None:
        if not self.load():
            return

        self.app.setCheckBox("Set_Make_Backups", self.get("make backups"), False)
        self.app.setCheckBox("Set_Close_After", self.get("close sub-window after saving"), False)
        self.app.setEntry("Set_Editor_Fonts", self.get("editor fonts"), False)
        self.app.setEntry("Set_Emulator_Path", self.get("emulator"), False)
        self.app.setEntry("Set_Emulator_Cmdline", self.get("emulator parameters"), False)
        self.app.setCheckBox("Set_Sync_NPC_Sprites", self.get("sync npc sprites"), False)
        self.app.setCheckBox("Set_Fix_Envelope", self.get("fix envelope bug"), False)
        self.app.setEntry("Set_Sampling_Rate", self.get("sample rate"), False)

        if sys.platform.find("win") > -1:
            audio_hosts = ["directsound", "mme", "asio", "wasapi", "wdm-ks"]
            host = audio_hosts.index(self.get("audio host"))
            if host > -1:
                self.app.setOptionBox("Set_Audio_Host", host, False)

    # ------------------------------------------------------------------------------------------------------------------

    def _apply_settings(self) -> None:
        self.set("make backups", self.app.getCheckBox("Set_Make_Backups"))
        self.set("close sub-window after saving", self.app.getCheckBox("Set_Close_After"))
        self.set("editor fonts", self.app.getEntry("Set_Editor_Fonts"))
        self.set("emulator", self.app.getEntry("Set_Emulator_Path").replace('\\', '/'))
        self.set("emulator parameters", self.app.getEntry("Set_Emulator_Cmdline"))
        self.set("sync npc sprites", self.app.getCheckBox("Set_Sync_NPC_Sprites"))
        self.set("fix envelope bug", self.app.getCheckBox("Set_Fix_Envelope"))
        self.set("sample rate", int(self.app.getEntry("Set_Sampling_Rate")))
        if sys.platform.find("win") > -1:
            self.set("audio host", self.app.getOptionBox("Set_Audio_Host"))
