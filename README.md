#Ultima: Exodus Editor
####A comprehensive editor for the NES version of *Ultima III: Exodus.*

###Included modules:
- Map Editor
    - Continent / Town editor
      - NPC editor
    - Dungeon editor
    - Battlefield editor
    
- Text Editor
    - NPC Dialogue editor
    - Interface text editor
    - NPC name editor (only for Remastered ROM)
    - Enemy name editor
    - Menu / Intro text editor
    - Character mapping editor

- Music / Sound Effect editor
  - Instrument editor
  - Track editor
- SFX editor
  
- Palette Editor
- Enemy Encounter Editor
- Screen / Cutscene Editor
    
- Other / Misc Editor Modules
    - Command editor
    - Player race editor
    - Player class editor
    - Weapon / armour editor
    - Magic editor
    - Item editor
    - CHR tile editor
    - Pre-made party editor (Remastered ROM only)
    - Special ability editor (Remastered ROM only)
    - Special dialogue editor (e.g. vendors, Lord British, etc.)
    - Game credits editor (opening and end credits)
    - Game ending editor
  
###To do / stretch goals:
- Music tracker:
  - Import/export music from/to FamiTracker
- Add an options for an alternative weapon / armour system
- Major refactoring in most modules
- Some extra features that would be nice to have:
    - Full-featured integrated tile editor, to make external tools entirely optional
    - An embedded assembler / code editor with basic syntax highlighting, for advanced hacking 

###Requirements:
- Python (3.8)
- Pillow (7.2.0)
- pyo (1.0.3)
- AppJar (0.94, a slightly altered version is included with this project)
- TCL 8.6
- TK 8.6
- Dataclasses

#
###Disclaimer:
This project was in big part an occasion for me to learn Python. You may notice my coding style changed as I learnt more
techniques,
and while I often do go back and improve older code, a full restructuring will have to happen at some point.

Hopefully you will still find it fun and useful ☻
