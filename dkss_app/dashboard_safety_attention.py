"""Read-only safety follow-ups for the dashboard's actual office and viewer."""
from . import models
from .checklist_common import patrol_result_to_dict
from .common import url_for
from .safety_permissions import can_view_patrol_result


def safety_attention(scope):
    result = {"available": bool(scope.company_code and scope.office), "items": []}
    if not result["available"]:
        return result
    rows = models.PatrolResult.query.filter(
        models.PatrolResult.company_code == scope.company_code,
        models.PatrolResult.office == scope.office,
        models.PatrolResult.target_type.in_(("user", "delivery_place")),
    ).order_by(models.PatrolResult.id.desc()).all()
    for row in rows:
        item = patrol_result_to_dict(row)
        # Apply the detail page's permission before displaying content OR counts.
        if not can_view_patrol_result(item):
            continue
        if item["category"] == "Good" or item["approval_status"] == "承認済み":
            continue
        if item["approval_status"] == "差し戻し":
            state, action = "差し戻し", "差し戻し理由と対策を確認"
        elif item["countermeasure"] and item["approval_status"] == "承認待ち":
            state, action = "対策確認待ち", "写真と対策内容を確認"
        else:
            state, action = "対策未確認", "記録を確認して対策を検討"
        result["items"].append({
            "id": row.id,
            "content": item["content"] or "内容未登録",
            "location": item["delivery_place"] or item["target_user"] or "対象未登録",
            "office": item["office"],
            "state": state,
            "action": action,
            "due_date": item["countermeasure_due_date"] or "",
            "date": item["date"] or "",
            "url": url_for("pointout_detail", index=row.id),
        })
    # Workflow state is not a risk/priority score. Preserve newest-first within it.
    order = {"対策確認待ち": 0, "差し戻し": 1, "対策未確認": 2}
    result["items"].sort(key=lambda item: order[item["state"]])
    return result
