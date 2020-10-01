__author__ = "Fox Cunning"

# Hardcoded log levels
#   0 = Don't log anything
#   1 = Critical errors
#   2 = All errors
#   3 = All errors and Warnings
#   4 = Everything
LOG_LEVEL = 4

_level = ["", "*CRITICAL*", "*ERROR*", "*WARNING*", "*INFO*"]


def log(level, source, text):
    if level > LOG_LEVEL:
        return

    print(f"{_level[level]} [{source}] - {text}")
