"""Text measurement shared by checklist Excel exports."""
import unicodedata


def spreadsheet_text_width(text):
    width = 0

    for char in str(text or ""):
        if unicodedata.east_asian_width(char) in ("W", "F", "A"):
            width += 2
        else:
            width += 1

    return width
