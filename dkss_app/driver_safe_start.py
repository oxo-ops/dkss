"""Presentation of a known future start day; stored dates remain untouched."""


def scheduled_safe_start_label(start_date, today):
    if start_date <= today:
        return None
    return f"開始予定（{start_date.isoformat().replace('-', '/')}）"
