__author__ = "Fox Cunning"

from dataclasses import dataclass


# ----------------------------------------------------------------------------------------------------------------------

@dataclass(init=True, repr=False)
class Point2D:
    x: int = 0xFF
    y: int = 0xFF

    def __call__(self, x: int, y: int):
        self.x = x
        self.y = y
