"""Safety Permissions responsibilities; routes are registered by the application factory."""
from . import checklist_common as _dkss_checklist_common, common as _dkss_common, models as _dkss_models
from . import safety_identity as _person_identity


def is_same_company_result(result):
    company_code = result.get("company_code")
    return company_code == _dkss_common.session.get("company_code")



def can_view_patrol_result(result):
    role = _dkss_common.session.get("role")

    if role in ["itc", "admin"]:
        return is_same_company_result(result)

    if not is_same_company_result(result):
        return False

    if result.get("target_type") == "delivery_place":
        return True

    if _person_identity.is_current(result.get("created_by_identity")):
        return True

    return (
        result.get("target_type") == "user"
        and _person_identity.is_current(result.get("target_identity"))
    )



def can_edit_patrol_result(result):
    if not is_same_company_result(result):
        return False

    if _dkss_common.session.get("role") in ["admin", "itc"]:
        return True

    return (
        _person_identity.is_current(result.get("created_by_identity"))
    )



def can_countermeasure_patrol_result(result):
    if not is_same_company_result(result):
        return False

    if _dkss_common.session.get("role") in ["admin", "itc"]:
        return True

    # 作成者
    if (
        _person_identity.is_current(result.get("created_by_identity"))
    ):
        return True

    # 個人対象なら対象本人
    return (
        result.get("target_type") == "user"
        and _person_identity.is_current(result.get("target_identity"))
    )



def can_delete_patrol_result(result):
    return can_edit_patrol_result(result)



def can_approve_patrol_result(result):
    if not is_same_company_result(result):
        return False

    return _dkss_common.session.get("role") in ["admin", "itc"]



def can_view_checklist_result(result):
    role = _dkss_common.session.get("role")

    if not is_same_company_result(result):
        return False

    if role in ["admin", "itc"]:
        return True

    if (
        _person_identity.is_current(result.get("checked_by_identity"))
    ):
        return True

    if (
        result.get("target_type") == "user"
        and _person_identity.is_current(result.get("target_identity"))
    ):
        return True

    # Reading the result and its attachments must be possible before approving it.
    # Preserve access for selected/previous approvers after the workflow advances.
    if role != "user":
        return False
    approvals = result.get("approvals") or []
    checklist = result.get("checklist_snapshot") or {}
    if not checklist and result.get("checklist_id"):
        record = _dkss_models.Checklist.query.filter_by(
            id=result["checklist_id"], company_code=result["company_code"]
        ).first()
        if record:
            checklist = _dkss_checklist_common.checklist_to_dict(record)
    definitions = [item for item in checklist.get("items", [])
                   if item.get("item_type") == "approval"]
    if not approvals:
        approvals = [{} for _ in definitions]
    approvals = [
        dict(approval, allow_general=approval.get(
            "allow_general",
            definitions[index].get("approval_allow_general", False)
            if index < len(definitions) else False,
        ))
        for index, approval in enumerate(approvals)
    ]
    if any(
        (
            _person_identity.is_current(approval.get("approved_by_identity"))
            or (approval.get("allow_general")
                and _person_identity.is_candidate(approval))
        )
        for approval in approvals
    ):
        return True
    current = next((approval for approval in approvals
                    if not (approval.get("approved_by")
                            or approval.get("approved_by_username"))), None)
    return (result.get("status") == "承認待ち"
            and can_approve_checklist_result(result, current))



def can_manage_checklist_result(result):
    role = _dkss_common.session.get("role")

    if not is_same_company_result(result):
        return False

    if role in ["admin", "itc"]:
        return True

    return (
        _person_identity.is_current(result.get("checked_by_identity"))
    )



def can_approve_checklist_result(result, approval=None):
    if not is_same_company_result(result):
        return False

    if not approval:
        return False

    approval_user = _dkss_models.User.query.filter_by(
        company_code=result.get("company_code"),
        username=_dkss_common.session.get("username")
    ).first()

    if not approval_user:
        return False

    if approval_user.role == "admin":
        return True

    return (
        approval.get("allow_general", False)
        and approval_user.role == "user"
    )



def can_reject_checklist_result(result, approval=None):
    return can_approve_checklist_result(result, approval)
