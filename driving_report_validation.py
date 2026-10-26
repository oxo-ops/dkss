"""Preserve OCR candidates while keeping invalid facts out of typed fields."""
import copy
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

LABELS = {'operation_date':'運行開始日','operation_end_date':'運行終了日','operation_start_time':'運行開始時刻','operation_end_time':'運行終了時刻','mileage':'終了積算距離','start_mileage':'開始積算距離','distance':'走行距離','source_pages':'原本ページ','source_page':'明細の原本ページ','report_scope':'集計粒度','item_name':'項目名','value':'数値','numerator':'分子','denominator':'分母','status':'読取状態','speaker':'コメントの話者'}


class DrivingReportValidationError(ValueError):
    def __init__(self, path, reason):
        super().__init__('INVALID_DRIVING_REPORT_EXTRACTION: '+path+'; '+reason)
        names={**LABELS,'records':'記録','report_items':'日報項目','events':'発生事象','duties':'乗務・作業区間','extra_items':'独自項目','document':'文書','warnings':'確認メモ'}
        labels=[]
        for part in path.split('.'):
            match=re.fullmatch(r'(\w+)\[(\d+)\]',part)
            labels.append((names.get(match[1],match[1])+str(int(match[2])+1)) if match else names.get(part,part))
        self.user_message = '安全運転日報の読取結果を確認できませんでした。確認箇所：'+'／'.join(labels)+'（'+reason+'）。'


def _number(raw, *, mileage=False):
    if raw is None or str(raw).strip() == '': return None
    if isinstance(raw, bool): raise ValueError()
    text = unicodedata.normalize('NFKC',str(raw)).strip()
    if mileage: text = re.sub(r'\s*(?:km|キロメートル)\s*$', '', text, flags=re.I).strip()
    if not re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?(?:[eE][+-]?\d+)?',text): raise ValueError()
    value = Decimal(text.replace(',',''))
    limit = Decimal('999999999999.99') if mileage else Decimal('999999999999999')
    if not value.is_finite() or abs(value)>limit or (mileage and (value<0 or value!=value.quantize(Decimal('.01')))): raise ValueError()
    return format(value,'f')


def prepare_candidates(data, page_count, text_fields, item_fields, collections):
    """No unit conversion, date inference, fabricated page, retry or network request."""
    def fail(path, reason): raise DrivingReportValidationError(path,reason)
    if not isinstance(data,dict) or not isinstance(data.get('records'),list): fail('records','記録一覧の形式が不正')
    if len(data['records'])>200: fail('records','記録数の上限超過')
    for ri,row in enumerate(data['records']):
        base=f'records[{ri}]'
        if not isinstance(row,dict): fail(base,'記録の形式が不正')
        original=copy.deepcopy(row);issues=[]
        if not isinstance(row.get('warnings',[]),list): fail(base+'.warnings','確認メモの形式が不正')
        row.setdefault('warnings',[])
        def issue(field, raw, reason):
            label=LABELS.get(field.rsplit('.',1)[-1],field)
            match=re.fullmatch(r'(report_items|events|duties|extra_items)\[(\d+)\]\.(\w+)',field)
            if match:
                source_items=original.get(match[1])
                if isinstance(source_items,list) and int(match[2])<len(source_items) and isinstance(source_items[int(match[2])],dict):
                    label=str(source_items[int(match[2])].get('item_name') or '項目名不明')+'／'+label
            issues.append({'field':field,'label':label,'raw':copy.deepcopy(raw),'display':raw if isinstance(raw,str) else json.dumps(raw,ensure_ascii=False),'reason':reason})
        def text_fields_of(target, fields, prefix=''):
            for key,limit in fields.items():
                raw=target.get(key)
                if raw is None: target[key]=None;continue
                if isinstance(raw,(int,float)) and not isinstance(raw,bool):
                    target[key]=str(raw);issue(prefix+key,raw,'返却された数値を文字表記として保持')
                elif not isinstance(raw,str):
                    target[key]=None;issue(prefix+key,raw,'文字欄に解釈できない返却値。元の値を保持')
                elif len(raw)>limit and not (not prefix and key in {'operation_date','operation_end_date'}):
                    if prefix: target['status']='unknown'
                    target[key]=raw[:limit] if key in {'item_name','raw_result','content','notes'} else None
                    issue(prefix+key,raw,'入力欄の文字数上限を超過。省略前の値を保持')
                elif not raw.strip(): target[key]=None
        # Older saved trip-only drafts may omit scope; an explicit unknown stays unknown.
        row.setdefault('report_scope','trip')
        text_fields_of(row,text_fields)
        for key in ('operation_date','operation_end_date'):
            raw=row.get(key)
            if raw is None:continue
            normalized=unicodedata.normalize('NFKC',raw).strip()
            match=re.fullmatch(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?',normalized)
            try:
                if not match:raise ValueError()
                value=date(*map(int,match.groups())).isoformat()
            except ValueError:
                row[key]=None;issue(key,raw,'運行日を確定できないため未取得。出力日から補わない')
            else:
                row[key]=value
                if value!=raw:issue(key,raw,'明記された年月日の表記だけを統一')
        if row.get('operation_date') and row.get('operation_end_date') and row['operation_end_date']<row['operation_date']:
            issue('operation_end_date',row['operation_end_date'],'開始日より前のため終了日を要確認として保持');row['operation_end_date']=None
        for key in ('distance','start_mileage','mileage'):
            raw=row.get(key)
            try:value=_number(raw,mileage=True)
            except (ValueError,InvalidOperation):
                value=None;issue(key,raw,'kmの距離として確定できないため未取得。単位換算・逆算をしない')
            else:
                if raw is not None and value!=raw:issue(key,raw,'明記されたkm値の桁区切り・数値表記だけを統一')
            row[key]=value
        scopes={'1運行':'trip','運行':'trip','日別':'daily','月次':'monthly','月次集計':'monthly','不明':'unknown'}
        raw=row.get('report_scope');scope=scopes.get(raw,raw)
        if scope not in {'trip','daily','monthly','unknown'}:scope='unknown'
        if scope!=raw:issue('report_scope',raw,'原文の粒度を保持。不明な粒度は集計しない')
        row['report_scope']=scope
        raw_pages=row.get('source_pages')
        if not isinstance(raw_pages,list) or not raw_pages:fail(base+'.source_pages','原本ページを特定できない')
        pages=[]
        for p in raw_pages:
            value=int(p) if isinstance(p,str) and re.fullmatch(r'[0-9]+',p) else p
            if type(value) is not int or not 1<=value<=page_count:fail(base+'.source_pages','PDFに存在しないページ番号')
            if value not in pages:pages.append(value)
        if pages!=raw_pages:issue('source_pages',raw_pages,'明示された原本ページの重複・数字表記だけを整理')
        row['source_pages']=pages
        for collection in collections:
            items=row.setdefault(collection,[])
            if not isinstance(items,list) or len(items)>1000:fail(base+'.'+collection,'明細一覧の形式・件数が不正')
            kept=[]
            for ii,item in enumerate(items):
                path=f'{collection}[{ii}].'
                if not isinstance(item,dict):fail(base+'.'+path,'明細の形式が不正')
                raw_item=copy.deepcopy(item);raw_page=item.get('source_page')
                page=int(raw_page) if isinstance(raw_page,str) and re.fullmatch(r'[0-9]+',raw_page) else raw_page
                if type(page) is not int or not 1<=page<=page_count:
                    issue(path+'source_page',raw_item,'原本ページが不明・範囲外の明細。値は下に保持し、集計項目へ採用しない');continue
                item['source_page']=page
                if page not in pages:
                    pages.append(page);issue(path+'source_page',page,'明細が明示するページを確認対象へ追加。原本との対応を要確認')
                text_fields_of(item,item_fields,path)
                if not item.get('item_name'):
                    item['status']='unknown';item['item_name']='項目名不明（要確認）';issue(path+'item_name',raw_item.get('item_name'),'項目名を判読できないため仮の表示名。明細の値は保持')
                for key in ('value','numerator','denominator'):
                    raw=item.get(key)
                    try:value=_number(raw)
                    except (ValueError,InvalidOperation):
                        value=None;item['status']='unknown';issue(path+key,raw,'数値として確定できないため未取得。単位付き原文は保持')
                    else:
                        if raw is not None and value!=raw:issue(path+key,raw,'明記された数値の表記だけを統一')
                    item[key]=value
                if item.get('status') == 'confirmed':
                    issue(path+'status',item['status'],'AI返却値を人の確認済みとは扱わない');item['status']='candidate'
                allowed={'candidate','illegible','not_recorded','not_applicable','unknown'}
                if item.get('status') is not None and item['status'] not in allowed:
                    issue(path+'status',item['status'],'未定義の読取状態は不明として保持');item['status']='unknown'
                if item.get('speaker') is not None and item['speaker'] not in {'auto','driver','manager','unknown'}:
                    issue(path+'speaker',item['speaker'],'話者を確定できないため不明として保持');item['speaker']='unknown'
                kept.append(item)
            row[collection]=kept
        if issues:
            row['_ocr_raw_candidate']=original
            row['_ocr_issues']=issues
            row['warnings'].append(f'読取値の表記・要確認箇所が{len(issues)}件あります。「読取時に要確認となった項目」で返却時の値を確認してください。')
