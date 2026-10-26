"""Knowledge responsibilities; routes are registered by the application factory."""
from . import access as _dkss_access, common as _dkss_common, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization


def maintenance_knowledge_master():
    from flask import abort

    company = _dkss_common.session.get("company_code")
    if not _dkss_common.session.get("username") or not company or not _dkss_access.require_master_admin():
        abort(403)
    now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo"))
    error = None
    values = {}
    if _dkss_common.request.method == "POST":
        action = _dkss_common.request.form.get("action", "")
        if action == "create":
            limits = {
                "title": 150, "part_name": 100, "manufacturer": 100,
                "model_code": 100, "conditions": 1500, "guidance": 2500,
                "source_reference": 1500, "provider": 150,
            }
            values = {name: _dkss_common.request.form.get(name, "").strip() for name in limits}
            values["source_kind"] = _dkss_common.request.form.get("source_kind", "").strip()
            values["valid_from"] = _dkss_common.request.form.get("valid_from", "").strip()
            values["valid_until"] = _dkss_common.request.form.get("valid_until", "").strip()
            required = set(limits) - {"manufacturer", "model_code"}
            if any(not values[name] for name in required):
                error = "部品・箇所、適用条件、確認内容、出典、提供者を含む必須項目を入力してください。"
            elif any(len(values[name]) > limit for name, limit in limits.items()):
                error = "入力項目の文字数上限を超えています。"
            elif values["source_kind"] not in _dkss_common.MAINTENANCE_KNOWLEDGE_KINDS:
                error = "出典区分を選択してください。"
            try:
                for name in ("valid_from", "valid_until"):
                    if values[name]:
                        parsed = _dkss_common.datetime.strptime(values[name], "%Y-%m-%d").date()
                        if parsed.isoformat() != values[name]:
                            raise ValueError
                if not values["valid_from"] or (
                    values["valid_until"]
                    and values["valid_until"] < values["valid_from"]
                ):
                    raise ValueError
            except ValueError:
                error = "有効期間を正しく入力してください。"
            if not error:
                row = _dkss_models.VehicleMaintenanceKnowledge(
                    company_code=company, **values, status="draft",
                    created_by=_dkss_common.session["username"],
                    created_at=now.strftime("%Y/%m/%d %H:%M"),
                )
                _dkss_common.db.session.add(row)
        elif action in {"confirm", "retire"}:
            row = _dkss_models.VehicleMaintenanceKnowledge.query.filter_by(
                id=_dkss_common.request.form.get("knowledge_id", type=int), company_code=company,
            ).first_or_404()
            if action == "confirm":
                if row.status != "draft" or _dkss_common.request.form.get("reviewed") != "1":
                    abort(400)
                changed = _dkss_models.VehicleMaintenanceKnowledge.query.filter_by(
                    id=row.id, company_code=company, status="draft",
                ).update({
                    "status": "active", "confirmed_by": _dkss_common.session["username"],
                    "confirmed_at": now.strftime("%Y/%m/%d %H:%M"),
                }, synchronize_session=False)
                if changed != 1:
                    abort(409)
            else:
                reason = _dkss_common.request.form.get("retirement_reason", "").strip()
                if row.status == "retired" or not 1 <= len(reason) <= 1000:
                    abort(400)
                changed = _dkss_models.VehicleMaintenanceKnowledge.query.filter_by(
                    id=row.id, company_code=company,
                ).filter(_dkss_models.VehicleMaintenanceKnowledge.status.in_({"draft", "active"})).update({
                    "status": "retired", "retired_by": _dkss_common.session["username"],
                    "retired_at": now.strftime("%Y/%m/%d %H:%M"),
                    "retirement_reason": reason,
                }, synchronize_session=False)
                if changed != 1:
                    abort(409)
        else:
            abort(400)
        if not error:
            _dkss_common.db.session.commit()
            return _dkss_common.redirect(_dkss_common.url_for("maintenance_knowledge_master"))
    return _dkss_common.redirect(_dkss_common.url_for("vehicle_karte_list"))



def maintenance_knowledge_detail(knowledge_id):
    from flask import abort

    if not _dkss_common.session.get("username") or not _dkss_common.session.get("company_code"):
        abort(403)
    row = _dkss_models.VehicleMaintenanceKnowledge.query.filter_by(
        id=knowledge_id, company_code=_dkss_common.session["company_code"],
    ).first_or_404()
    return _dkss_common.render_template(
        "maintenance_knowledge.html", rows=[row], selected=row,
        kinds=_dkss_common.MAINTENANCE_KNOWLEDGE_KINDS, error=None, values={},
        today=_dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date().isoformat(),
    )



def build_vehicle_certificate_specification_evidence(original, extraction):
    """Retain candidates; only exact same-page PDF identity/label matches verify facts."""
    import copy
    import hashlib
    import re
    import unicodedata
    from io import BytesIO
    def normalized(value):
        value = unicodedata.normalize('NFKC', str(value or ''))
        return re.sub(r'\s+', '', value).translate(str.maketrans({'‐':'-', '－':'-', '−':'-'}))
    if not isinstance(original,bytes) or not original or len(original)>20*1024*1024:
        raise ValueError('CERTIFICATE_SOURCE_BYTES_INVALID')
    if not isinstance(extraction,dict) or not isinstance(extraction.get('vehicle'),dict):
        raise ValueError('CERTIFICATE_SOURCE_EXTRACTION_INVALID')
    vehicle = extraction['vehicle']
    identity = {name: normalized(vehicle.get(name)) for name in ('chassis_number', 'model_code')}
    fields = {'type_designation_number':('型式指定番号',5), 'type_classification_number':('類別区分番号',4)}
    result = {'document_checksum':hashlib.sha256(original).hexdigest(), 'identity':identity,
              'scope':'literal_same_page_vehicle_certificate_fields_only', 'fields':{}}
    for name, (label, size) in fields.items():
        candidate = normalized(vehicle.get(name))
        result['fields'][name] = {'value':candidate or None, 'status':'not_recorded' if not candidate else 'source_unverified', 'pages':[]}
        if candidate and not re.fullmatch(r'[0-9]{'+str(size)+'}',candidate):
            raise ValueError('CERTIFICATE_SPECIFICATION_NUMBER_INVALID')
    cache_key = (result['document_checksum'], identity['chassis_number'], identity['model_code'],
                 *(result['fields'][name]['value'] for name in fields))
    cache = getattr(build_vehicle_certificate_specification_evidence, '_verified_cache', {})
    if cache_key in cache:
        return copy.deepcopy(cache[cache_key])
    pages = []
    if original.startswith(b'%PDF-'):
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(original), strict=False)
            if not reader.is_encrypted and 1 <= len(reader.pages) <= 10:
                for page in reader.pages:
                    content = page.get_contents()
                    if content is not None and len(content.get_data()) > 5*1024*1024:
                        pages.append('')
                        continue
                    text = page.extract_text() or ''
                    pages.append(normalized(text) if len(text) <= 200000 else '')
        except Exception:
            pages = []
    if not identity['chassis_number'] or not identity['model_code']:
        return result
    def literal_token(value, text):
        return re.search(r'(?<![A-Z0-9])'+re.escape(value)+r'(?![A-Z0-9])',text,re.I) is not None
    for index, text in enumerate(pages, 1):
        if not all(literal_token(value,text) for value in identity.values()):
            continue
        # A multi-vehicle page cannot bind a neighbouring row's identifier.
        detected = re.findall(r'[A-Z][A-Z0-9]{2,12}-[0-9]{4,12}(?![A-Z0-9])',text,re.I)
        if text.count('車台番号') != 1 or len(set(detected)) != 1 or normalized(detected[0]) != identity['chassis_number']:
            continue
        for name, (label, size) in fields.items():
            field = result['fields'][name]
            value = field['value']
            if not value:
                continue
            pattern = re.escape(label)+r'[:：]?'+re.escape(value)+r'(?![0-9])'
            if text.count(label)==1 and re.search(pattern,text):
                field['pages'].append(index)
                field['status'] = 'literal_same_page_matched'
    if all(field['status']=='literal_same_page_matched' for field in result['fields'].values()):
        if len(cache)>=8:
            cache.clear()
        cache[cache_key] = copy.deepcopy(result)
        build_vehicle_certificate_specification_evidence._verified_cache = cache
    return result



def remember_vehicle_certificate_specification_source(original, filename, extraction):
    """Preserve original source in existing draft storage; no vehicle or approval update."""
    import hashlib
    from uuid import uuid4
    evidence = build_vehicle_certificate_specification_evidence(original, extraction)
    draft = _dkss_models.VehicleDocumentImportDraft(
        id=str(uuid4()), batch_id=str(uuid4()),
        company_code=_dkss_common.session['company_code'], created_by_username=_dkss_common.session['username'],
        document_type='certificate', source_filename=filename[:255], source_file=original,
        source_sha256=hashlib.sha256(original).hexdigest(),
        preview_json=_dkss_common.json.dumps({'certificate_extraction':extraction, 'specification_evidence':evidence},ensure_ascii=False),
        result_json='{}', status='certificate_pending',
    )
    _dkss_common.db.session.add(draft)
    _dkss_common.db.session.commit()
    refs = _dkss_common.session.get('certificate_specification_refs') or []
    if not isinstance(refs,list):
        refs=[]
    _dkss_common.session['certificate_specification_refs'] = [r for r in refs if isinstance(r,str)][-4:]+[draft.id]



def link_vehicle_certificate_specification_source(vehicle):
    """Link an authenticated source on final vehicle save, in the same transaction."""
    import unicodedata
    def normalized(value):
        return _dkss_common.re.sub(r'\s+', '', unicodedata.normalize('NFKC',str(value or ''))).translate(str.maketrans({'‐':'-', '－':'-', '−':'-'}))
    if not vehicle.id or vehicle.company_code != _dkss_common.session.get('company_code'):
        return
    refs = _dkss_common.session.get('certificate_specification_refs') or []
    if not isinstance(refs,list):
        return
    for ident in reversed(refs[-5:]):
        if not isinstance(ident,str):
            continue
        draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
            id=ident, company_code=vehicle.company_code,
            created_by_username=_dkss_common.session.get('username'), document_type='certificate',
            status='certificate_pending',
        ).first()
        if draft is None:
            continue
        data = _dkss_serialization.safe_json_dict(draft.preview_json)
        identity = (data.get('specification_evidence') or {}).get('identity') or {}
        actual = {name:normalized(getattr(vehicle,name,None)) for name in ('chassis_number','model_code')}
        if not all(actual.values()) or identity != actual:
            continue
        draft.result_json = _dkss_common.json.dumps({'vehicle_record_id':vehicle.id,'identity':actual},ensure_ascii=False)
        draft.status='certificate_linked'
        draft.completed_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo('UTC'))
        return



def get_vehicle_certificate_specification_source(vehicle):
    """Read only fields whose saved original still verifies the exact current vehicle."""
    import hashlib
    import unicodedata
    def normalized(value):
        return _dkss_common.re.sub(r'\s+', '', unicodedata.normalize('NFKC',str(value or ''))).translate(str.maketrans({'‐':'-', '－':'-', '−':'-'}))
    drafts = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
        company_code=vehicle.company_code, document_type='certificate', status='certificate_linked',
    ).order_by(_dkss_models.VehicleDocumentImportDraft.created_at.desc(), _dkss_models.VehicleDocumentImportDraft.id.desc()).all()
    expected = {name:normalized(getattr(vehicle,name,None)) for name in ('chassis_number','model_code')}
    if not all(expected.values()):
        return {'status':'not_available'}
    pending = None
    for draft in drafts:
        binding = _dkss_serialization.safe_json_dict(draft.result_json)
        if type(binding.get('vehicle_record_id')) is not int or binding['vehicle_record_id'] != vehicle.id:
            continue
        if binding.get('identity') != expected:
            return {'status':'vehicle_identity_changed'}
        checksum = hashlib.sha256(draft.source_file).hexdigest()
        if checksum != draft.source_sha256:
            return {'status':'source_checksum_mismatch'}
        data = _dkss_serialization.safe_json_dict(draft.preview_json)
        extraction = data.get('certificate_extraction')
        if not isinstance(extraction,dict):
            return {'status':'invalid_saved_extraction'}
        evidence = build_vehicle_certificate_specification_evidence(draft.source_file, extraction)
        if evidence.get('identity') != expected:
            return {'status':'source_identity_mismatch'}
        fields = evidence['fields']
        selected = {name:entry['value'] for name,entry in fields.items() if entry['status']=='literal_same_page_matched'}
        candidate = {'status':'source_matched' if len(selected)==2 else 'source_unverified',
                     'document_id':draft.id,'document_checksum':checksum,'values':selected,
                     'verification':fields,'scope':evidence['scope']}
        if len(selected)==2:
            if pending:
                candidate['newer_unverified_document_id'] = pending['document_id']
            return candidate
        if pending is None:
            pending = candidate
    return pending or {'status':'not_available'}



def get_vehicle_verified_model_specification(vehicle):
    """Exact-model official facts; no master updates or network requests."""
    import copy
    import unicodedata
    registry = {'QPG-SH1EDDG': {'manufacturer': '日野', 'commercial_name': 'プロフィア', 'vehicle_category': 'truck', 'vehicle_class': 'large_truck', 'identity_url': 'https://www.hino.co.jp/corp/news/2014/20140128.html', 'transmission_categories': ['MT', 'AMT'], 'transmission_url': 'https://www.mlit.go.jp/jidosha/content/H31_truck_JH15_rev.xls', 'scope': 'published_factory_specifications_only', 'model_match': 'exact_full_model', 'transmission_evidence': {'sheet': 'Hino_rev.', 'rows': [2337, 2338, 2339, 2340, 2341, 2342, 2343], 'scope': 'all_published_variants_for_exact_model_not_individual_vehicle'}}, '2PG-SH1EDGG': {'manufacturer': '日野', 'commercial_name': 'プロフィア', 'vehicle_category': 'truck', 'vehicle_class': 'large_truck', 'identity_url': 'https://www.hino.co.jp/corp/news/2018/20180531.html', 'transmission_categories': ['MT', 'AMT'], 'transmission_url': 'https://wwwtb.mlit.go.jp/kanto/content/000302541.pdf', 'scope': 'published_factory_specifications_only', 'model_match': 'exact_full_model', 'transmission_evidence': {'page': 125, 'scope': 'all_published_variants_for_exact_model_not_individual_vehicle'}}, 'QPG-FW1EXEG': {'manufacturer': '日野', 'commercial_name': 'プロフィア', 'vehicle_category': 'truck', 'vehicle_class': 'large_truck', 'identity_url': 'https://www.hino.co.jp/corp/news/2014/20140129.html', 'transmission_categories': ['MT', 'AMT'], 'transmission_url': 'https://www.mlit.go.jp/jidosha/content/H31_truck_JH15_rev.xls', 'scope': 'published_factory_specifications_only', 'model_match': 'exact_full_model', 'transmission_evidence': {'sheet': 'Hino_rev.', 'rows': [2084, 2085, 2086, 2087, 2088, 2089], 'scope': 'all_published_variants_for_exact_model_not_individual_vehicle'}}, '2RG-FW1AHG': {'manufacturer': '日野', 'commercial_name': 'プロフィア', 'vehicle_category': 'truck', 'vehicle_class': 'large_truck', 'identity_url': 'https://www.hino.co.jp/recall/detail_4478.html', 'transmission_categories': ['AMT'], 'transmission_url': 'https://www.mlit.go.jp/report/press/content/001611884.pdf', 'scope': 'published_factory_specifications_only', 'model_match': 'exact_full_model', 'transmission_evidence': {'page': 4, 'published_model': '2RG-FW1AHG', 'published_transmission': '12速AMT', 'reevaluated_model': '2DG-FW1AHG', 'scope': 'published_factory_specification_for_exact_original_model_not_transmission_subtype'}}, 'QKG-FQ1ARBA': {'manufacturer': '日野', 'commercial_name': 'プロフィア', 'vehicle_category': 'truck', 'vehicle_class': 'large_truck', 'identity_url': 'https://www.hino.co.jp/recall/detail_4378.html', 'transmission_categories': ['MT'], 'transmission_url': 'https://www.mlit.go.jp/jidosha/content/H31_truck_JH15_rev.xls', 'scope': 'published_factory_specifications_only', 'model_match': 'exact_full_model', 'transmission_evidence': {'sheet': 'Hino_rev.', 'rows': [2057], 'scope': 'all_published_variants_for_exact_model_not_individual_vehicle'}}, '2DG-FQ1AJC': {'manufacturer': '日野', 'commercial_name': 'プロフィア', 'vehicle_category': 'truck', 'vehicle_class': 'large_truck', 'identity_url': 'https://www.hino.co.jp/recall/detail_4594.html', 'transmission_categories': [], 'transmission_url': None, 'scope': 'published_factory_specifications_only', 'model_match': 'exact_full_model'}, '2PG-FE2ABA': {'manufacturer': '日野', 'commercial_name': 'レンジャー', 'vehicle_category': 'truck', 'vehicle_class': 'medium_truck', 'identity_url': 'https://www.hino.co.jp/recall/detail_4515.html', 'transmission_categories': [], 'transmission_url': None, 'scope': 'published_factory_specifications_only', 'model_match': 'exact_full_model'}, '2RG-FP84VDR': {'manufacturer': '三菱', 'commercial_name': 'スーパーグレート', 'vehicle_category': 'truck', 'vehicle_class': 'large_truck', 'identity_url': 'https://assets.mitsubishi-fuso.com/fusoassets/2026/03/R5797.pdf', 'transmission_categories': [], 'transmission_url': None, 'scope': 'published_factory_specifications_only', 'model_match': 'exact_full_model'}}
    model = unicodedata.normalize("NFKC", str(vehicle.model_code or "")).strip().upper()
    record = registry.get(model)
    if record is None:
        return {"status": "not_indexed", "model_code": model, "facts": {}}
    # CERTIFICATE_SPECIFICATION_SOURCE_V1
    record = copy.deepcopy(record)
    if model == "2DG-FQ1AJC":
        # Full model has AT, MT and AMT variants; never choose by model alone.
        record["transmission_categories"] = ["MT", "AMT", "AT"]
        record["transmission_url"] = "https://www.mlit.go.jp/jidosha/content/truck_hino_jh25.xlsx"
        record["transmission_evidence"] = {
            "sheet": "3-2", "rows": [524,525,526,527,699,700,701,702],
            "source_sha256": "98600e1476521022623c1ad67fab77bbb870f269bf03d80195ec5563166cba55",
            "scope": "published_variants_for_exact_model",
        }
        certificate = get_vehicle_certificate_specification_source(vehicle)
        record["certificate_specification"] = certificate
        if certificate.get("status") == "source_matched":
            number = certificate["values"].get("type_classification_number")
            # Only explicit individual numbers in official rows 699-702.
            known = {"3010":"MT", "3011":"MT", "3012":"AMT", "3013":"AT",
                     "3014":"MT", "3015":"MT", "3016":"MT", "3017":"MT", "3018":"AMT"}
            if number in known:
                record["transmission_categories"] = [known[number]]
                record["transmission_evidence"]["scope"] = "exact_model_and_verified_source_classification"
    maker = unicodedata.normalize("NFKC", str(vehicle.manufacturer or "")).strip().casefold()
    maker = {"hino": "日野", "日野自動車": "日野", "日野自動車株式会社": "日野",
             "三菱ふそう": "三菱", "三菱ふそうトラック・バス": "三菱"}.get(maker, maker)
    return {
        "status": "matched" if maker == record["manufacturer"] else "manufacturer_conflict",
        "model_code": model, "facts": copy.deepcopy(record),
        "registry_version": "OFFICIAL_MODEL_SPECIFICATIONS_V3",
        "registry_checksum": 'fd5fbc1eff6ca46e10406e788010db71c950860759caa03ad0859f516959d921',
    }



def resolve_verified_maintenance_source_conditions(rule, specification, symbol):
    """Resolve known source conditions by explicit facts, preserving AI review."""
    definitions = {'対象はポスト新長期規制以降。規制の「以降」を許容分類の列挙に置き換えない。': ['post_2009_emissions'], '車種の限定は大型トラック・大型観光バス。vehicle_categoryだけでは大型・観光の限定を表現できない。': ['large_truck_or_tourism_bus'], '原文は車両や搭載装置による相違を明示するが、トレーラコントロールバルブの搭載仕様の詳細は列挙していない。': ['installed_trailer_control_valve'], '大型トラックの「大型」という限定はvehicle_categoryだけでは表現できない。': ['large_truck'], '対象車両の「ポスト新長期規制以降」という限定は、許容される排出ガス規制区分の列挙ではないため、構造化条件とは別に保持する。対象は大型トラック。': ['post_2009_emissions', 'large_truck'], '対象車両の「ポスト新長期規制以降」という限定は、許容される排出ガス規制区分の列挙ではないため、構造化条件とは別に保持する。対象は大型観光バス。': ['post_2009_emissions', 'large_tourism_bus']}
    checksum = "80a351761072cbc07a0a6a64f84c4ebf2fd247091c1241a3355b02029f60ba25"
    semantic = rule.get("semantic_review") or {}
    applicability = semantic.get("applicability") or {}
    notes = applicability.get("unresolved_conditions") or []
    facts = specification.get("facts") or {}
    states = []
    for note in notes:
        components = definitions.get(note) if semantic.get("document_checksum") == checksum else None
        checks = []
        for component in components or []:
            value = "unknown"
            urls = []
            if component == "post_2009_emissions":
                # Only explicitly researched heavy-diesel symbols. Registration
                # dates are never a substitute for an emissions regulation.
                if symbol in {"QPG", "QKG", "2PG", "2RG", "2DG"}:
                    value = "matched"
                    urls = ["https://www.mlit.go.jp/common/001179991.pdf"]
            elif component in {"large_truck", "large_tourism_bus", "large_truck_or_tourism_bus"}:
                actual = facts.get("vehicle_class")
                if actual:
                    accepted = {component} if component != "large_truck_or_tourism_bus" else {"large_truck", "large_tourism_bus"}
                    value = "matched" if actual in accepted else "not_matched"
                    urls = [facts["identity_url"]]
            checks.append({"condition": component, "status": value, "source_urls": urls})
        status = ("not_matched" if any(c["status"] == "not_matched" for c in checks)
                  else "matched" if checks and all(c["status"] == "matched" for c in checks)
                  else "unknown")
        states.append({"attribute": "source_condition", "original_condition": note,
                       "status": status, "condition_checks": checks})
    return states



def evaluate_vehicle_maintenance_rule(
    vehicle, rule, *, document_checksum, vehicle_category=None,
):
    """登録値と適用条件を照合する。基準採用・期限計算は行わない。"""
    import unicodedata

    # OFFICIAL_MODEL_SPECIFICATIONS_V1
    checks = []
    specification = {}

    def result(status, reason):
        return {
            "status": status,
            "reason": reason,
            "vehicle_source_id": f"vehicle:{vehicle.id}",
            "scope": "registered_and_verified_official_model_facts",
            "official_specification": specification,
            "calculation_permitted": False,
            "checks": checks,
        }

    def normalize(value):
        if not isinstance(value, str):
            return ""
        return unicodedata.normalize("NFKC", value).strip().casefold()

    def manufacturer(value):
        value = normalize(value)
        return {
            "hino": "日野",
            "日野自動車": "日野",
            "日野自動車株式会社": "日野",
        }.get(value, value)

    try:
        if (
            not isinstance(document_checksum, str)
            or not _dkss_common.re.fullmatch(r"[a-f0-9]{64}", document_checksum)
        ):
            return result("unknown", "document_not_identified")

        source = rule.get("source_verification") or {}
        semantic = rule.get("semantic_review") or {}
        numeric = rule.get("numeric_evidence") or {}
        if (
            source.get("status") != "quote_matched"
            or source.get("document_checksum") != document_checksum
            or numeric.get("status") != "tokens_present"
            or semantic.get("status") != "supported"
            or semantic.get("document_checksum") != document_checksum
        ):
            return result("unknown", "source_review_not_supported")

        evidence = semantic.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3:
            return result("unknown", "review_evidence_missing")
        for entry in evidence:
            verification = entry["source_verification"]
            if (
                verification.get("status") != "quote_matched"
                or verification.get("document_checksum") != document_checksum
            ):
                return result("unknown", "review_evidence_not_verified")

        applicability = semantic["applicability"]
        scope = applicability["scope"]
        coverage = applicability["coverage"]
        requirements = applicability["requirements"]
        unresolved = applicability["unresolved_conditions"]

        if (
            scope not in {"restricted", "unrestricted", "unknown"}
            or coverage not in {"complete", "uncertain"}
            or not isinstance(requirements, list)
            or len(requirements) > 20
            or not isinstance(unresolved, list)
        ):
            return result("unknown", "invalid_applicability")

        if scope == "unknown":
            return result("unknown", "scope_not_identified")
        if scope == "restricted" and not requirements:
            return result("unknown", "requirements_missing")
        if scope == "unrestricted" and (
            requirements
            or rule.get("model_codes")
            or rule.get("engine_codes")
        ):
            return result("unknown", "scope_conflicting")

        specification = get_vehicle_verified_model_specification(vehicle)
        if specification["status"] == "manufacturer_conflict":
            return result("conditions_not_matched", "official_model_conflicts_with_registered_manufacturer")
        official = specification.get("facts") or {}
        if vehicle_category and official.get("vehicle_category") and vehicle_category != official["vehicle_category"]:
            return result("unknown", "registered_category_conflicts_with_official_model")
        registered = {
            "manufacturer": vehicle.manufacturer,
            "model_code": vehicle.model_code,
            "engine_code": getattr(vehicle, "engine_code", None),
            "vehicle_category": vehicle_category or official.get("vehicle_category"),
            "commercial_name": official.get("commercial_name"),
            "first_registration_date": vehicle.first_registration_date,
        }
        # RULE_MODEL_EMISSIONS_V1
        # The prefix is already present in the registered full model code.
        # Do not infer vehicle series, equipment or manufacture date from it.
        full_model = normalize(vehicle.model_code).upper()
        model_match = _dkss_common.re.fullmatch(r"([A-Z0-9]{3})-[A-Z0-9]+", full_model)
        registered["emission_standard"] = (
            model_match.group(1) if model_match else None
        )
        date_attributes = {
            "manufacture_date", "first_registration_date",
        }
        attributes = {
            *registered,
            "engine_code", "manufacture_date", "equipment",
            "usage_condition", "part_specification", "commercial_name", "emission_standard",
        }

        for requirement in requirements:
            attribute = requirement["attribute"]
            operator = requirement["operator"]
            values = requirement["values"]
            indexes = requirement["evidence_indexes"]
            if (
                attribute not in attributes
                or operator not in {
                    "one_of", "not_one_of", "on_or_after", "on_or_before", "unknown",
                }
                or not isinstance(values, list)
                or len(values) > 20
                or any(
                    not isinstance(value, str) or not value.strip()
                    for value in values
                )
                or not isinstance(indexes, list)
                or not indexes
                or any(
                    type(index) is not int
                    or not 0 <= index < len(evidence)
                    for index in indexes
                )
            ):
                return result("unknown", "invalid_requirement")

            state = "unknown"
            actual = registered.get(attribute)
            if operator == "unknown":
                if values:
                    return result("unknown", "invalid_unknown_requirement")
            elif not values:
                return result("unknown", "requirement_values_missing")
            elif operator in {"on_or_after", "on_or_before"}:
                if attribute not in date_attributes or len(values) != 1:
                    return result("unknown", "invalid_date_requirement")
                boundary = _dkss_common.datetime.strptime(
                    values[0], "%Y-%m-%d",
                ).date()
                if boundary.isoformat() != values[0]:
                    return result("unknown", "invalid_date_requirement")
                if isinstance(actual, str):
                    text = normalize(actual).replace("/", "-")
                    if len(text) == 10:
                        try:
                            measured = _dkss_common.datetime.strptime(
                                text, "%Y-%m-%d",
                            ).date()
                            if (
                                measured.isoformat() == text
                                and measured <= _dkss_common.datetime.now(
                                    _dkss_common.ZoneInfo("Asia/Tokyo")
                                ).date()
                            ):
                                matched = (
                                    measured >= boundary
                                    if operator == "on_or_after"
                                    else measured <= boundary
                                )
                                state = (
                                    "matched" if matched else "not_matched"
                                )
                        except ValueError:
                            pass
            elif attribute in date_attributes:
                return result("unknown", "invalid_date_operator")
            elif attribute == "equipment":
                # OFFICIAL_TRANSMISSION_VARIANTS_V2: retain every published option.
                possible = official.get("transmission_categories") or []
                categories = {normalize(value).upper() for value in values}
                allowed = set(possible)
                if allowed and categories <= {"MT", "AMT"}:
                    if allowed <= categories:
                        state = "matched" if operator == "one_of" else "not_matched"
                    elif allowed.isdisjoint(categories):
                        state = "not_matched" if operator == "one_of" else "matched"
                elif allowed and categories and all(
                    _dkss_common.re.fullmatch(r"AMT\((?:MZ12|M112)\)", value)
                    for value in categories
                ) and allowed.isdisjoint({"AMT"}):
                    # Known MT-only specifications exclude any AMT subtype.
                    state = "not_matched" if operator == "one_of" else "matched"
                actual = possible[0] if len(possible) == 1 else None
            elif attribute == "emission_standard":
                patterns = [normalize(value).upper() for value in values]
                # A star replaces exactly the middle character, never an
                # arbitrary substring. Other descriptions need interpretation.
                if actual and all(_dkss_common.re.fullmatch(
                    r"(?:[SLQ2]\*G|[A-Z0-9]{3})", value,
                ) for value in patterns):
                    matches_value = any(_dkss_common.re.fullmatch(
                        _dkss_common.re.escape(value).replace(r"\*", r"[A-Z0-9]"), actual,
                    ) for value in patterns)
                    matched = bool(matches_value)
                    if operator == "not_one_of":
                        matched = not matched
                    state = "matched" if matched else "not_matched"
            elif attribute in registered:
                normalizer = (
                    manufacturer
                    if attribute == "manufacturer" else normalize
                )
                actual_value = normalizer(actual)
                if actual_value:
                    # APPLICABILITY_NAMED_SCOPE_V2
                    matches_value = actual_value in {
                        normalizer(value) for value in values
                    }
                    matched = (
                        matches_value if operator == "one_of"
                        else not matches_value
                    )
                    state = "matched" if matched else "not_matched"

            checks.append({
                "attribute": attribute,
                "operator": operator,
                "required_values": list(values),
                "registered_value": actual,
                **({"official_source_url": official.get("identity_url")}
                   if attribute in {"commercial_name", "vehicle_category"} and official else {}),
                **({"official_source_url": official.get("transmission_url"),
                    "official_possible_categories": list(official.get("transmission_categories") or []),
                    "official_evidence": official.get("transmission_evidence"),
                    "reason_detail": (
                        "Exact model has multiple transmission variants; no individual variant selected"
                        if len(official.get("transmission_categories") or []) > 1
                        else "Exact transmission subtype and installation require separate evidence"
                    )}
                   if attribute == "equipment" and official else {}),
                **({
                    "registered_value_basis": {
                        "field": "model_code",
                        "value": vehicle.model_code,
                        "derivation": "leading_three_character_emissions_symbol",
                        "reference_url": "https://www.mlit.go.jp/common/001179991.pdf",
                    },
                } if attribute == "emission_standard" and actual else {}),
                "reason": (
                    "registered_value_matches" if state == "matched"
                    else "registered_value_differs" if state == "not_matched"
                    else "vehicle_field_not_available"
                    if attribute not in registered
                    else "registered_field_missing_or_ambiguous"
                    if not actual
                    else "condition_requires_interpretation"
                ),
                "status": state,
                "evidence_indexes": list(indexes),
            })

        for attribute, field in (
            ("model_code", "model_codes"),
            ("engine_code", "engine_codes"),
        ):
            declared = rule.get(field) or []
            if not isinstance(declared, list) or any(
                not isinstance(value, str) or not value.strip()
                for value in declared
            ):
                return result("unknown", "invalid_declared_scope")
            if declared:
                actual = registered.get(attribute)
                value = normalize(actual)
                checks.append({
                    "attribute": attribute,
                    "operator": "one_of",
                    "required_values": list(declared),
                    "registered_value": actual,
                    "status": (
                        "matched" if value in {
                            normalize(entry) for entry in declared
                        }
                        else "not_matched" if value else "unknown"
                    ),
                    "basis": field,
                })

        source_conditions = resolve_verified_maintenance_source_conditions(
            rule, specification, registered.get("emission_standard"),
        )
        checks.extend(source_conditions)
        # A disproven necessary condition excludes the rule even when other
        # conditions remain unknown. No unknown condition may create a match.
        if any(check["status"] == "not_matched" for check in checks):
            return result("conditions_not_matched", "registered_value_differs")
        if unresolved:
            if not source_conditions or any(c["status"] != "matched" for c in source_conditions):
                return result("unknown", "source_conditions_need_additional_evidence")
        elif coverage != "complete":
            return result("unknown", "conditions_not_fully_structured")
        if any(
            requirement["operator"] == "unknown"
            for requirement in requirements
        ):
            return result("unknown", "condition_not_interpreted")
        if any(check["status"] == "not_matched" for check in checks):
            return result("conditions_not_matched", "registered_value_differs")
        if any(check["status"] == "unknown" for check in checks):
            return result("unknown", "required_vehicle_fact_unavailable")
        return result("conditions_matched", "registered_conditions_matched")

    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return result("unknown", "invalid_applicability_data")



def maintenance_knowledge_model_scope_matches(vehicle, knowledge_row, rule=None):
    """Match literal model codes; accept source-bound commercial-name scopes separately."""
    import re
    import unicodedata

    def normalize(value):
        return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()

    declared = normalize(knowledge_row.model_code)
    if not declared or declared == normalize(vehicle.model_code):
        return True
    if (
        knowledge_row.status != "draft"
        or knowledge_row.source_kind != "メーカー公式資料"
        or not isinstance(rule, dict)
    ):
        return False

    # The document reader binds this rule to the unchanged extracted knowledge row.
    # A descriptive vehicle name is accepted only when the reviewed rule explicitly
    # retains that same positive scope. Vehicle applicability is still checked below.
    semantic = rule.get("semantic_review") or {}
    if semantic.get("status") != "supported":
        return False
    applicability = semantic.get("applicability") or {}
    requirements = applicability.get("requirements") or []
    declared_names = [normalize(value) for value in re.split(r"[、,]", declared)]
    if not declared_names or any(not value for value in declared_names):
        return False
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        if (
            requirement.get("attribute") != "commercial_name"
            or requirement.get("operator") != "one_of"
        ):
            continue
        values = requirement.get("values")
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            continue
        names = {normalize(value) for value in values}
        if set(declared_names) <= names:
            return True
    return False



def assess_public_maintenance_rule_adoption(
    vehicle, knowledge_row, evidence, rule,
    *, vehicle_category=None,
):
    """原本・車両条件による採用候補判定。状態変更・期限計算は行わない。"""
    import unicodedata

    def decision(status, reason, **details):
        return {
            "status": status,
            "reason": reason,
            "calculation_permitted": False,
            "scope": "automatic_adoption_eligibility",
            **details,
        }

    def maker(value):
        if not isinstance(value, str):
            return ""
        value = unicodedata.normalize(
            "NFKC", value,
        ).strip().casefold()
        return {
            "hino": "日野",
            "日野自動車": "日野",
            "日野自動車株式会社": "日野",
        }.get(value, value)

    try:
        if knowledge_row.company_code != vehicle.company_code:
            return decision("not_eligible", "company_mismatch")
        if knowledge_row.status not in {"draft", "active"}:
            return decision("not_eligible", "knowledge_unavailable")
        if knowledge_row.source_kind != "メーカー公式資料":
            return decision("not_eligible", "not_public_manufacturer_source")

        registered_maker = maker(vehicle.manufacturer)
        source_maker = maker(knowledge_row.manufacturer)
        if not registered_maker or source_maker != registered_maker:
            return decision("not_eligible", "manufacturer_not_confirmed")

        today = _dkss_common.datetime.now(
            _dkss_common.ZoneInfo("Asia/Tokyo")
        ).date().isoformat()
        valid_from = knowledge_row.valid_from
        valid_until = knowledge_row.valid_until
        for value in (valid_from, valid_until):
            if value and (
                not isinstance(value, str)
                or _dkss_common.datetime.strptime(
                    value, "%Y-%m-%d",
                ).date().isoformat() != value
            ):
                return decision("not_eligible", "invalid_validity_period")
        if (
            not valid_from
            or valid_from > today
            or (valid_until and valid_until < today)
            or (valid_until and valid_until < valid_from)
        ):
            return decision("not_eligible", "outside_validity_period")

        if evidence.get("knowledge_id") != knowledge_row.id:
            return decision("not_eligible", "knowledge_identity_mismatch")
        stored_rules = evidence.get("rules")
        if (
            not isinstance(stored_rules, list)
            or not isinstance(rule, dict)
            or rule not in stored_rules
        ):
            return decision("not_eligible", "rule_not_bound_to_knowledge")
        if evidence.get("status") != "candidates":
            return decision("not_eligible", "stored_candidate_not_verified")
        if not maintenance_knowledge_model_scope_matches(vehicle, knowledge_row, rule):
            return decision("not_eligible", "knowledge_model_scope_not_confirmed")

        if evidence.get("public_source_status") != "available":
            return decision("not_eligible", "public_source_reader_unavailable")

        document_id = evidence.get("document_id")
        checksum = evidence.get("document_checksum")
        marker = f"[knowledge-document:{document_id}]"
        reference = knowledge_row.source_reference or ""
        if marker not in reference:
            return decision("not_eligible", "knowledge_document_mismatch")

        observed = []
        for state in evidence.get("public_document_states", []):
            url = state.get("source_url")
            if (
                state.get("company_code") == vehicle.company_code
                and state.get("document_id") == document_id
                and state.get("document_checksum") == checksum
                and state.get("source_state") == "observed"
                and state.get("available") is True
                and isinstance(url, str)
                and url.startswith("https://")
                and reference.startswith(url + " /")
            ):
                observed.append(state)

        if not observed:
            return decision("not_eligible", "matching_public_version_unavailable")

        if rule.get("cycle") not in {"first", "repeat", "all"}:
            return decision("not_eligible", "cycle_not_interpreted")
        if rule.get("relation") not in {"single", "any", "all"}:
            return decision("not_eligible", "criteria_relation_not_interpreted")

        matched = evaluate_vehicle_maintenance_rule(
            vehicle,
            rule,
            document_checksum=checksum,
            vehicle_category=vehicle_category,
        )
        if matched["status"] != "conditions_matched":
            return decision(
                "not_eligible", "vehicle_conditions_not_confirmed",
                vehicle_applicability=matched,
            )

        return decision(
            "eligible", "source_and_vehicle_conditions_confirmed",
            document_id=document_id,
            document_checksum=checksum,
            source_url=observed[0]["source_url"],
            vehicle_applicability=matched,
        )

    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return decision("not_eligible", "invalid_adoption_data")



def get_vehicle_maintenance_knowledge(vehicle, records=()):
    import unicodedata

    def normalize(value):
        return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()

    def normalize_manufacturer(value):
        value = normalize(value)
        aliases = {
            "hino": "日野",
            "日野自動車": "日野",
            "日野自動車株式会社": "日野",
        }
        return aliases.get(value, value)

    today = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date().isoformat()
    rows = _dkss_models.VehicleMaintenanceKnowledge.query.filter_by(
        company_code=vehicle.company_code,
    ).filter(
        _dkss_models.VehicleMaintenanceKnowledge.status.in_({"active", "draft"}),
        _dkss_models.VehicleMaintenanceKnowledge.valid_from <= today,
        _dkss_common.db.or_(
            _dkss_models.VehicleMaintenanceKnowledge.valid_until == "",
            _dkss_models.VehicleMaintenanceKnowledge.valid_until >= today,
        ),
    ).all()
    matched = [row for row in rows if (
        (not row.manufacturer or normalize_manufacturer(row.manufacturer) == normalize_manufacturer(vehicle.manufacturer))
        and (
            not row.model_code
            or normalize(row.model_code) == normalize(vehicle.model_code)
            or (
                row.status == "draft"
                and row.source_kind == "メーカー公式資料"
            )
        )
    )]
    def relevance_terms(value):
        text = normalize(value).replace("フィルター", "フィルタ")
        text = _dkss_common.re.sub(r"[^\w]+", "", text)
        return {
            text[index:index + 3]
            for index in range(max(0, len(text) - 2))
        }

    record_terms = []
    for record in records:
        source_id = str(record.get("source_id") or "")
        findings = " ".join(
            str(item.get("content") or "")
            + " " + str(item.get("comment") or "")
            for item in (record.get("findings") or [])
            if isinstance(item, dict)
        )
        line_item_text = " ".join(
            value
            for item in (record.get("line_items") or [])
            if isinstance(item, dict)
            for value in item.values()
            if isinstance(value, str)
        )
        text = " ".join(
            str(record.get(name) or "")
            for name in (
                "content", "symptom", "cause",
                "temporary_action", "repair_content", "notes",
            )
        ) + " " + findings + " " + line_item_text
        attention = (
            source_id.startswith("defect:")
            and record.get("status") in {"未対応", "対応中"}
        ) or (
            source_id.startswith("inspection:")
            and bool(record.get("has_attention"))
        )
        group = (
            0 if attention
            else 1 if source_id.startswith("part:")
            else 2
        )
        record_terms.append((group, relevance_terms(text)))

    def knowledge_order(row):
        subject = relevance_terms(row.part_name)
        scores = [0, 0, 0]
        for group, terms in record_terms:
            combined = subject | terms
            similarity = (
                len(subject & terms) / len(combined)
                if combined else 0
            )
            scores[group] = max(scores[group], similarity)
        return (
            *scores,
            bool(row.model_code),
            bool(row.manufacturer),
            row.id,
        )

    scope_reader = _dkss_runtime.app.extensions.get(
        "maintenance_knowledge_import", {},
    ).get("get_vehicle_scopes")
    if scope_reader:
        scopes, rule_evidence = scope_reader(
            matched, include_rule_evidence=True,
        )
    else:
        scopes, rule_evidence = {}, {}

    category_aliases = {
        "トラック": "truck",
        "大型トラック": "truck",
        "中型トラック": "truck",
        "小型トラック": "truck",
        "トラクタ": "truck",
        "トラクター": "truck",
        "バス": "bus",
    }
    registered_categories = {
        category_aliases[value]
        for value in (
            normalize(vehicle.body_type),
            normalize(vehicle.type),
        )
        if value in category_aliases
    }
    vehicle_category = (
        next(iter(registered_categories))
        if len(registered_categories) == 1 else None
    )

    matched = [
        row for row in matched
        if not (
            vehicle_category is not None
            and scopes.get(row.id, {}).get("mode") == "restricted"
            and vehicle_category not in scopes[row.id]["categories"]
        )
    ]
    matched.sort(key=knowledge_order, reverse=True)
    knowledge = []
    sources = {}
    eligible_count = 0
    selected_candidates = []
    for row in matched:
        item = {
            name: getattr(row, name)
            for name in (
                "title", "part_name", "manufacturer", "model_code",
                "conditions", "guidance", "source_kind", "source_reference",
                "provider", "valid_from", "valid_until", "confirmed_by", "confirmed_at", "status",
            )
        }
        source_id = f"knowledge:{row.id}"
        item["source_id"] = source_id
        item["vehicle_scope"] = scopes.get(row.id, {
            "mode": "unknown",
            "categories": [],
            "quote": "",
        })
        item["vehicle_category_match"] = (
            "matched"
            if vehicle_category is not None
            and item["vehicle_scope"]["mode"] == "restricted"
            and vehicle_category in item["vehicle_scope"]["categories"]
            else "unrestricted"
            if item["vehicle_scope"]["mode"] == "unrestricted"
            else "unknown"
        )
        item["maintenance_rule_evidence"] = rule_evidence.get(
            row.id,
            {
                "status": "not_available",
                "calculation_permitted": False,
                "requires_semantic_review": True,
                "requires_applicability_check": True,
                "rules": [],
            },
        )
        adopted_rules = []
        for rule_index, rule in enumerate(
            item["maintenance_rule_evidence"].get("rules", []), 1,
        ):
            rule["vehicle_applicability"] = evaluate_vehicle_maintenance_rule(
                vehicle,
                rule,
                document_checksum=item["maintenance_rule_evidence"].get(
                    "document_checksum"
                ),
                vehicle_category=vehicle_category,
            )
            assessment = assess_public_maintenance_rule_adoption(
                vehicle,
                row,
                item["maintenance_rule_evidence"],
                rule,
                vehicle_category=vehicle_category,
            )
            rule["adoption_assessment"] = {
                "status": assessment["status"],
                "reason": assessment["reason"],
            }

            if assessment["status"] == "eligible":
                identity = {
                    "knowledge_id": row.id,
                    "document_id": assessment["document_id"],
                    "document_checksum": assessment["document_checksum"],
                    "rule": {
                        name: rule[name]
                        for name in (
                            "action", "criteria", "relation", "cycle",
                            "model_codes", "engine_codes", "conditions",
                            "source_page", "source_quote",
                        )
                    },
                }
                rule["analysis_adoption"] = {
                    "status": "adopted_for_analysis",
                    "method": "automatic_source_and_vehicle_checks",
                    "rule_index": rule_index,
                    "rule_key": _dkss_common.hashlib.sha256(
                        _dkss_common.json.dumps(
                            identity,
                            sort_keys=True,
                            ensure_ascii=False,
                            default=str,
                        ).encode("utf-8")
                    ).hexdigest(),
                    "knowledge_source_id": source_id,
                    "vehicle_source_id": f"vehicle:{vehicle.id}",
                    "document_id": assessment["document_id"],
                    "document_checksum": assessment["document_checksum"],
                    "source_url": assessment["source_url"],
                    "calculation_permitted": False,
                    "calculation_status": "baseline_not_evaluated",
                }
                adopted_rules.append(rule)
            else:
                rule["analysis_adoption"] = {
                    "status": "held",
                    "calculation_permitted": False,
                }
        item["applicability_status"] = "requires_condition_check"
        item["applicability_note"] = (
            "有効期間内で、登録されたメーカー・型式の"
            "絞込条件に一致した候補。空欄は対象範囲の"
            "確認済みを意味しない。conditionsに記載された"
            "車種・年式・装備・症状・使用条件は未照合。"
            "activeは知識の利用状態であり、この車両への"
            "適用確認済みを意味しない。"
        )
        if row.status == "draft":
            if not adopted_rules:
                continue

            item["analysis_usage"] = "verified_rules_only"
            item["conditions"] = ""
            item["guidance"] = ""
            item["source_reference"] = (
                adopted_rules[0]["analysis_adoption"]["source_url"]
                + " [knowledge-document:"
                + str(item["maintenance_rule_evidence"]["document_id"])
                + "]"
            )
            item["maintenance_rule_evidence"] = {
                **item["maintenance_rule_evidence"],
                "rules": adopted_rules,
            }
            item["applicability_status"] = "verified_rules_only"
            item["applicability_note"] = (
                "原本の版・引用・数値・意味・車両条件を照合した"
                "規則だけを分析へ提供。下書きの説明文は提供しない。"
                "規則ごとのanalysis_adoptionを参照。"
                "期限計算に必要な交換実績等の照合は別工程。"
            )
        else:
            item["analysis_usage"] = "active_knowledge"

        eligible_count += 1
        # PREVENTIVE_RULE_SELECTION_V1: an adopted rule is usable evidence;
        # legacy prose must not displace it before the common input cap is applied.
        selected_candidates.append((bool(adopted_rules), knowledge_order(row), row, item))

    selected_candidates.sort(key=lambda candidate: candidate[:2], reverse=True)
    for _, _, row, item in selected_candidates[:20]:
        # VERIFIED_DOCUMENT_CONTEXT_V1: retain checked impact and daily tasks,
        # independently of numeric-rule calculation permissions.
        context_reader = _dkss_runtime.app.extensions.get(
            "maintenance_knowledge_import", {},
        ).get("get_verified_document_context")
        if context_reader:
            context = context_reader(vehicle.company_code, item)
            if context:
                item["verified_document_context"] = context
        source_id = item["source_id"]
        knowledge.append(item)
        sources[source_id] = {
            "label": f"{row.source_kind}：{row.title}（提供：{row.provider}）",
            "url": _dkss_runtime.app.extensions["dkss"]['knowledge_import_link'](row) or _dkss_common.url_for("maintenance_knowledge_detail", knowledge_id=row.id),
            "snapshot": item,
        }
    return knowledge, sources, eligible_count
