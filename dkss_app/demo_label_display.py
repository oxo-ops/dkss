"""Exact presentation aliases for verified legacy demo labels; never writes."""
from flask import current_app, has_request_context, request, session


def _in_demo(company, endpoint):
    # The existing before_request guard authenticates, verifies active demo
    # session/expiry and company before either route can render this text.
    return (has_request_context()
            and request.endpoint == endpoint
            and current_app.config.get('PUBLIC_DEMO_CANDIDATE') is True
            and current_app.config.get('PUBLIC_DEMO_SHARED_COMPANY') is True
            and current_app.config.get('PUBLIC_DEMO_COMPANY') == 'AONAGI'
            and session.get('aonagi_readonly_demo') is True
            and session.get('company_code') == company == 'AONAGI')


def plan_factory(value, *, company, vehicle_id, plan_id, event_id):
    if (_in_demo(company, 'vehicle_karte_history')
            and (vehicle_id, plan_id, event_id) == (649, 8, 8)
            and value == '港南車両サービス（架空）'):
        return '港南車両サービス'
    return value


def approval_label(value, *, company, checklist_id, result_id):
    if (_in_demo(company, 'checklist_result_detail')
            and checklist_id == 13 and result_id in (14, 15, 16, 17)
            and value == '体験用管理者確認'):
        return '管理者確認'
    return value

# Verified sample records only. Raw content and approval/audit data are unchanged.
_PATROL_CONTENT = {
    8: "【体験用・架空】102号車の出庫前点検で灯火・タイヤ・積載固定を指差し確認し、気付いた点を管理者へ共有した。安全確認の良い取組として紹介する記録。",
    11: "【体験用・架空】102号車で交差部手前の一時停止位置を再確認した。歩行者の動きを見てから発進し、接触なし。確認事項：停止線手前で確実に停止し左右を確認する。",
    12: "【体験用・架空】102号車の荷台整理と点検道具の定位置管理を実施し、出庫前の確認時間を短縮した。整理整頓を継続する良い取組の記録。",
}


def patrol_content(value, *, company, result_id):
    if (has_request_context() and request.method == 'GET'
            and (_in_demo(company, 'pointouts')
                 or _in_demo(company, 'pointout_detail'))
            and result_id in _PATROL_CONTENT
            and value == _PATROL_CONTENT[result_id]):
        return value.removeprefix('【体験用・架空】')
    return value


def safety_criteria(value, *, company, checklist_id, result_id):
    raw = '2＝確認できている、1＝一部改善が必要、0＝未実施。架空の機能確認用評価。'
    if (_in_demo(company, 'checklist_result_detail')
            and request.method == 'GET'
            and checklist_id == 13 and result_id == 17 and value == raw):
        return '2＝確認できている、1＝一部改善が必要、0＝未実施。'
    return value



# Read-only aliases for four verified legacy sample notifications. Match the
# complete stored body before touching either the summary or expanded display.
_NOTIFICATION_LABELS = {
    259: ("【体験用・架空】照合の実施者と確認タイミングを具体化してください。荷札と伝票のどこを確認するかを追記し、再提出してください。", "【体験用・架空】"),
    262: ("点検日：2026-11-10\n判断：判定保留\n理由：【体験用・架空】11月10日の入力は正常例ですが、画面に別日11月16日の未解消不具合も表示されています。別日の対応状況を確認するため、この例では判断保留とします。実車の運行許可ではありません。", "【体験用・架空】"),
    264: ("点検日：2026-11-09\n判断：運行不可\n理由：【体験用・架空】左前輪の空気圧低下について原因確認と整備後の再確認が完了していないため、この記録では運行不可とする。対応完了後に再判断する。実車への指示ではありません。", "【体験用・架空】"),
    282: ("点検日：2026-11-17\n判断：運行不可\n理由：【架空・通し検証 QA-20261117-103】始動時異音の原因確認と整備後の再確認が未完了という想定のため、練習上は運行不可。実車への指示ではありません。通知から管理者が内容を確認し、手動で判断する流れの確認です。", "【架空・通し検証 QA-20261117-103】"),
}


def notification_text(value, *, raw, company, notification_id):
    sample = _NOTIFICATION_LABELS.get(notification_id)
    if (sample and raw == sample[0] and has_request_context()
            and request.method == 'GET'
            and any(_in_demo(company, endpoint) for endpoint in
                    ('notifications', 'notification_recent', 'notification_detail'))):
        return value.replace(sample[1], '', 1)
    return value
