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
    # Alternate existing ordered lists; this is not a new cross-domain risk rank.
    rows = []
    for index in range(max(len(safety_rows), len(vehicle_rows))):
        if index < len(safety_rows):
            rows.append(safety_rows[index])
        if index < len(vehicle_rows):
            rows.append(vehicle_rows[index])
    return rows
