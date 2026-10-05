"""既存チェックリストの登録・更新やDB操作は行わない。
法定／自主の区分と車両条件の適用は、別の処理で照合する。
"""

from copy import deepcopy


EVALUATION_CRITERIA = "\n".join((
    '【注1】点検の結果、点検良は「レ」印を、点検否は「×」印を記入する。',
    '【注2】着色部位の点検は、走行距離、運行時の状態等から判断した適切な時期に行うことで足りる。',
    '【注3】斜体文字（★印）部位の点検は、車両総重量8トン以上又は乗車定員30人以上の自動車に限る。',
    '【注4】太文字部位は、トラック・バスなどのエア・ブレーキが装着されている自動車の点検項目及び点検内容を示す。',
    '【おことわり】この点検表は自主点検項目が加味されております。',
))

# 順番、カテゴリ、文言、網掛け。複数行の項目は一つの行として保持する。
_SOURCE_ROWS = (
    ('運転者席', 'エンジンのかかり具合、異音\n低速、加速の状態', True),
    ('運転者席', 'ブレーキ・ペダルの踏みしろ、効き具合', False),
    ('運転者席', '駐車ブレーキ・レバーの引きしろ（踏みしろ）', False),
    ('運転者席', '空気圧力計の上がり具合', False),
    ('運転者席', 'ブレーキ・バルブの排気音', False),
    ('運転者席', '方向指示器の点滅具合', False),
    ('運転者席', 'ウインド・ウォッシャの液量、噴射状態', True),
    ('運転者席', 'ワイパーの拭き取り状態', True),
    ('車両の周り', 'ラジエータの冷却水の量', True),
    ('車両の周り', 'ファン・ベルトの張り具合、損傷', True),
    ('車両の周り', 'エンジン・オイルの液量、液漏れ', True),
    ('車両の周り', 'バッテリの液量', True),
    ('車両の周り', '前照灯、方向指示器、車幅灯、非常点滅灯、\nその他灯火の点灯、点滅具合', False),
    ('車両の周り', '灯火類のレンズ、反射器の\n汚れ、変色、損傷状況', False),
    ('車両の周り', 'タイヤの空気圧、異状摩耗、亀裂、損傷', False),
    ('車両の周り', 'タイヤの溝の深さ', True),
    ('車両の周り', '冬用タイヤのプラットホームの露出の有無', True),
    ('車両の周り', '★ ディスク・ホイールの取付け状態\nホイール・ボルトの折損・不揃いホイール・ナット\nの緩み・脱落ホイール・ボルト付近のサビ汁', False),
    ('車両の周り', 'エア・タンク内の凝水', False),
    ('車両の周り', '（ブレーキ・ペダルの踏みしろ、効き具合）\nブレーキ・チャンバのロッドのストローク\nドラムとライニングのすき間', True),
    ('車両の周り', '番号灯、方向指示器、尾灯、制動灯、\n後退灯、非常点滅灯、その他灯火の\n点灯、点滅具合', False),
    ('車両の周り', '灯火類のレンズ、反射器の\n汚れ、変色、損傷状況', False),
    ('連結部', 'ジャンパ・ケーブル・ソケットの連結具合\nエア・ホース、カップリングの取付、漏れ、\n損傷状況\nカプラ、ピントルフック、ルネット・アイなどの\n損傷、連結具合', False),
    ('その他', '座席（シートベルト）の装着状況', False),
    ('その他', '工具、スペア・タイヤの固定状況', False),
    ('その他', '非常信号用具、停止表示器材、車検証、\n自賠責保険証、点検整備記録簿等の車載状況', False),
    ('その他', 'チャート紙の装着状況', False),
)

_DEFAULT = {
    'template_code': 'daily_inspection_truck_trailer',
    'template_version': 1,
    'name': '日常点検表',
    'vehicle_scope': 'トラック・トレーラ用',
    'criteria': EVALUATION_CRITERIA,
    'choices': ['✓', '×'],
    'choice_meanings': {'✓': '正常', '×': '異常'},
    'print_half_month': True,
    'comment_required': False,
    'attachment_required': False,
    'items': [
        {
            'item_code': f'daily_{index + 1:02d}',
            'order': index,
            'item_type': 'check',
            'category': category,
            'content': content,
            'input_type': 'select',
            'choices': ['✓', '×'],
            'criteria': EVALUATION_CRITERIA,
            'shaded': shaded,
        }
        for index, (category, content, shaded) in enumerate(_SOURCE_ROWS)
    ],
    'footer_fields': [
        {'order': 27, 'field_type': 'inspector', 'label': '点検実施者（運転者）'},
        {'order': 28, 'field_type': 'check', 'label': '前日における異状箇所の処置状況の確認', 'choices': ['✓', '×']},
        {'order': 29, 'field_type': 'check', 'label': '当日の不具合箇所の処置状況の確認', 'choices': ['✓', '×']},
        {'order': 30, 'field_type': 'approval', 'label': '整備管理者（又は補助者）'},
    ],
}


def get_daily_inspection_default():
    """各呼出元に独立したコピーを返し、共通定義の書換えを防ぐ。"""
    return deepcopy(_DEFAULT)
