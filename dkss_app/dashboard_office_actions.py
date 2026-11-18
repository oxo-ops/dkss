"""Presentation-only projection of already-authorized dashboard follow-ups.

Safety workflow states are NOT risk scores. Do not infer priority from them.
The existing saved vehicle priority, destination, and ordering are preserved.
"""


def office_actions(office, safety, vehicles):
    if not office:
        return []
    safety_rows = [dict(item, kind="安全", title=item["content"])
                   for item in safety.get("items", []) if item.get("office") == office]
    vehicle_rows = []
    for group in ("mine", "office"):
        for item in vehicles.get(group, {}).get("items", []):
            # A user's assigned vehicle may belong to another office.
            if item.get("office") == office:
                vehicle_rows.append(dict(item, kind="車両"))
    # Group domains without changing either domain's authorized membership or order.
    # Safety workflow states are not compared against vehicle priority scores.
    return safety_rows + vehicle_rows
