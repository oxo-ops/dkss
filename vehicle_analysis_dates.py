"""Pure date conversion preserving the analysis readers' existing formats."""
from datetime import date, datetime


def parse_record_date(value, *, normalize=False):
    text = str(value or "")
    text = text.strip()[:10].replace("/", "-") if normalize else text[:10]
    # Canonical dates dominate stored rows. Avoid strptime's format/locale work.
    # Other legacy forms still go through exactly the previous parser.
    if (len(text) == 10 and text[4] == "-" and text[7] == "-"
            and (text[:4] + text[5:7] + text[8:]).isascii()
            and (text[:4] + text[5:7] + text[8:]).isdigit()):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
