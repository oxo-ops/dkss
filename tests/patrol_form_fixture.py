"""Fresh patrol forms for existing callers; explicit stale proofs stay intact."""
import html
import re


def fresh_patrol_data(client, path, data):
    if not isinstance(data, dict) or 'person_selection_token' in data:
        return data
    if not re.fullmatch(r'/pointouts/(new|\d+/edit)', path):
        return data
    if not data.get('target_user') or (path == '/pointouts/new' and data.get('target_type') != 'user'):
        return data
    response = client.get(path)
    try:
        if response.status_code != 200:
            return data
        match = re.search(r'name="person_selection_token"\s+value="([^"]+)"', response.get_data(as_text=True))
        return dict(data, person_selection_token=html.unescape(match[1])) if match else data
    finally:
        response.close()
