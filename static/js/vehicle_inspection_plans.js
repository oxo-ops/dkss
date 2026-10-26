(() => {
    'use strict';
    const panel = document.querySelector('#inspection-plan-panel');
    if (!panel || panel.dataset.initialized) return;
    panel.dataset.initialized = 'true';
    const review = document.querySelector('#inspection-plan-review');
    const planner = document.querySelector('[data-inspection-planner]');
    const form = panel.querySelector('#inspection-plan-form');
    const executionForm = panel.querySelector('#inspection-execution-form');
    let executionInitial = '', editorSequence = 0;
    const states = {unreserved:'未予約', reserved:'予約済み', awaiting:'実施確認待ち', completed:'実施済み', candidate:'予定未登録'};
    const labels = { '3month': '3か月点検', '12month': '12か月点検', ad_hoc: '突発点検' };
    const sourceLabels = { expiry: '車検満了日からの候補', manual: '手動で登録した予定', document: '点検簿の次回記載から反映', calculated: '周期から自動算出した候補' };
    let current = null, vehicle = null, initial = '', pending = null, data = null, selected = new Set();
    const args = planner ? JSON.parse(planner.dataset.planArgs || '{}') : {};
    if (args.kind === 'vehicle_inspection') args.kind = '12month';
    const filters = planner?.querySelector('[data-plan-filters]');
    const node = (tag, text, cls) => {
        const el = document.createElement(tag);
        if (text !== undefined) el.textContent = text;
        if (cls) el.className = cls;
        return el;
    };
    function error(root, selector, message = '') {
        const el = root.querySelector(selector);
        el.textContent = message; el.hidden = !message;
    }
    async function api(path = '', body) {
        const response = await fetch('/api/vehicle/inspection-plans' + path, {
            method: body ? 'POST' : 'GET', credentials: 'same-origin',
            headers: body ? { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' } : {},
            body: body ? JSON.stringify(body) : undefined
        });
        const text = await response.text();
        let value; try { value = JSON.parse(text); } catch (_) { value = null; }
        if (!response.ok || !value) {
            const parsed = new DOMParser().parseFromString(text, 'text/html');
            throw new Error(value?.message || parsed.querySelector('p')?.textContent || '保存できませんでした。内容を保持しています。最新の予定を確認してください。');
        }
        return value;
    }
    function annualURL(scope = 'office') {
        const url = new URL('/vehicle/inspection-plans', location.origin);
        url.searchParams.set('scope', scope);
        if (vehicle?.id) url.searchParams.set('vehicle_id', vehicle.id);
        if (current?.kind) url.searchParams.set('kind', current.kind);
        if (vOffice()) url.searchParams.set('office', vOffice());
        return url;
    }
    function vOffice() { return vehicle?.office && vehicle.office !== '営業所未設定' ? vehicle.office : ''; }
    function dirty() { return (initial && new URLSearchParams(new FormData(form)).toString() !== initial) || (!executionForm.hidden && executionInitial !== new URLSearchParams(new FormData(executionForm)).toString()); }
    function closePanel() {
        if (dirty() && !window.confirm('変更を保存せずに閉じますか？')) return;
        panel.close();
    }
    function openEditor(row, v, editable = true) {
        current = { ...row }; vehicle = v;
        panel.querySelector('[data-plan-kind-label]').textContent = labels[row.kind];
        panel.querySelector('[data-plan-vehicle-label]').textContent = v.number;
        panel.querySelector('[data-plan-office-label]').textContent = v.office || '営業所未設定';
        ['planned_month', 'reservation_date', 'factory', 'note'].forEach(key => {
            form.elements[key].value = row[key] || ''; form.elements[key].disabled = !editable;
        });
        panel.querySelector('[data-plan-source]').textContent = row.kind==='12month'&&row.status==='candidate'&&row.expiry_date ? '車検満了日：'+row.expiry_date+' ／ 予定未登録（予約はまだ登録されていません）' : (sourceLabels[row.source] || '') + (row.document_date ? ' ／ 原本記載日 ' + row.document_date : '');
        panel.querySelector('[data-plan-save]').hidden = !editable || row.status === 'completed';
        panel.querySelector('[data-plan-cancel-record]').hidden = !editable || !row.id || ['cancelled','completed'].includes(row.status);
        const link = panel.querySelector('[data-plan-annual]');
        link.href = annualURL(v.office ? 'office' : 'company');
        panel.querySelector('[data-plan-scope="office"]').disabled = !v.office;
        initial = new URLSearchParams(new FormData(form)).toString();
        error(panel, '[data-plan-error]');
        executionForm.reset(); executionForm.hidden = true; form.hidden = false;
        const toggle = panel.querySelector('[data-execution-toggle]');
        toggle.hidden = !editable || row.status === 'cancelled';
        executionForm.querySelector('[data-certificate-evidence]').hidden = row.kind !== '12month';
        executionForm.querySelector('[data-periodic-next]').hidden = row.kind === 'ad_hoc';
        executionForm.elements.confirmation.required = false;
        executionForm.elements.confirmed.required = false;
        executionForm.elements.performed_date.value = row.performed_date || '';
        executionForm.elements.new_expiry.value = row.new_expiry || '';
        executionForm.elements.confirmation.value = row.evidence_note || '';
        const docs = executionForm.elements.document_id; docs.replaceChildren();
        const pendingDoc = node('option', '未受領・後日追加'); pendingDoc.value = ''; docs.append(pendingDoc);
        const targets = executionForm.elements.target_plan;
        targets.replaceChildren(); const empty = node('option', '過去の実施（対象予定なし）'); empty.value = ''; targets.append(empty);
        if (row.id && row.status === 'planned') {
            const option = node('option', row.planned_month + ' の予定を実施済みにする'); option.value = row.id; targets.append(option);
            const currentMonth = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit' }).format(new Date());
            if (row.planned_month <= currentMonth) targets.value = String(row.id);
        }
        executionForm.elements.factory.value = row.factory || '';
        const sequence = ++editorSequence;
        panel.querySelector('[data-plan-current-status]').textContent = row.status === 'completed' ? '実施済み ' + (row.performed_date || '') + ' ／ 書類' + (row.document_status || '未確認') : states[row.display_state] || (row.reservation_date ? '予約済み' : row.id ? '未予約' : '予定未登録');
        panel.querySelector('[data-plan-last]').textContent = '実施記録を確認中…';
        panel.querySelector('[data-plan-record-link]').hidden = true;
        panel.querySelector('[data-plan-evidence]').textContent = row.evidence_note ? '確認根拠：' + row.evidence_note + (row.new_expiry ? ' ／ 更新後満了日 ' + row.new_expiry : '') : '';
        api('?detail=1&vehicle_id=' + encodeURIComponent(v.id)).then(value => {
            if (sequence !== editorSequence) return;
            (value.documents || []).forEach(d => { const o = node('option', d.name); o.value = d.id; docs.append(o); });
            const actual = value.latest[row.kind];
            panel.querySelector('[data-plan-last]').textContent = actual ? '直近の実施：' + actual.performed_date + ' ／ 書類' + actual.document_status + (actual.factory ? ' ／ ' + actual.factory : '') : '実施記録なし（実施したかは未確認）';
            const link = panel.querySelector('[data-plan-record-link]'); link.hidden = !actual?.record_url;
            if (actual?.record_url) link.href = actual.record_url;
        }).catch(e => { if (sequence === editorSequence) panel.querySelector('[data-plan-last]').textContent = e.message; });
        panel.showModal();
    }
    document.querySelectorAll('[data-inspection-plan-open]').forEach(button => button.addEventListener('click', async () => {
        button.disabled = true;
        try {
            const value = await api('?detail=1&vehicle_id=' + encodeURIComponent(button.dataset.vehicleId));
            const kind = button.dataset.inspectionPlanOpen;
            openEditor(value.plans[kind] || { id: null, version: 0, vehicle_record_id: value.vehicle.id, kind, planned_month: '', source: 'manual' }, value.vehicle, value.can_edit);
        } catch (e) { window.alert(e.message); }
        finally { button.disabled = false; }
    }));
    panel.querySelectorAll('[data-plan-close]').forEach(b => b.addEventListener('click', closePanel));
    panel.addEventListener('cancel', e => { e.preventDefault(); closePanel(); });
    panel.querySelectorAll('[data-plan-scope]').forEach(b => b.addEventListener('click', () => {
        if (b.dataset.planScope === 'vehicle') return;
        if (dirty() && !window.confirm('未保存の変更があります。保存せずに年間計画へ移りますか？')) return;
        location.href = annualURL(b.dataset.planScope);
    }));
    async function showReview(changes) {
        const value = await api('/preview', { changes });
        pending = { changes, token: value.token };
        review.dataset.savePath = '/save';
        review.querySelector('#inspection-plan-review-title').textContent = '予定の変更を確認';
        review.querySelector('[data-plan-review-count]').textContent = value.changes.length + '件の変更。確定済みの予約変更もここで確認してください。';
        const tbody = review.querySelector('[data-plan-review-rows]'); tbody.replaceChildren();
        const description = p => p ? (p.status === 'cancelled' ? '取消' : p.planned_month) + '\n予約日 ' + (p.reservation_date || '未定') + '\n' + (p.factory || '実施先未定') + (p.note ? '\n' + p.note : '') : '未登録';
        value.changes.forEach(change => {
            const tr = node('tr');
            [change.number + '\n' + labels[change.after.kind], description(change.before), description(change.after)].forEach(text => tr.append(node('td', text)));
            tbody.append(tr);
        });
        error(review, '[data-review-error]'); review.showModal();
    }
    form.addEventListener('submit', async e => {
        e.preventDefault();
        if (!form.reportValidity()) return;
        const button = form.querySelector('[data-plan-save]'); button.disabled = true;
        try {
            const values = Object.fromEntries(new FormData(form));
            await showReview([{ ...current, ...values, status: 'planned', period_key: current.period_key || values.planned_month }]);
        } catch (e) { error(panel, '[data-plan-error]', e.message); }
        finally { button.disabled = false; }
    });
    panel.querySelector('[data-plan-cancel-record]').addEventListener('click', async () => {
        try { await showReview([{ ...current, status: 'cancelled' }]); }
        catch (e) { error(panel, '[data-plan-error]', e.message); }
    });
    review.querySelectorAll('[data-review-close]').forEach(b => b.addEventListener('click', () => review.close()));
    review.querySelector('[data-review-save]').addEventListener('click', async e => {
        const button = e.currentTarget; button.disabled = true;
        try {
            await api(review.dataset.savePath || '/save', pending);
            review.close(); panel.close(); initial = '';
            if (planner) { await load(); } else location.reload();
        } catch (e) { error(review, '[data-review-error]', e.message); }
        finally { button.disabled = false; }
    });
    panel.querySelector('[data-execution-toggle]').addEventListener('click', () => {
        executionForm.hidden = false; form.hidden = true;
        panel.querySelector('[data-execution-toggle]').hidden = true;
        executionInitial = new URLSearchParams(new FormData(executionForm)).toString();
        error(panel, '[data-execution-error]'); executionForm.elements.performed_date.focus();
    });
    panel.querySelector('[data-execution-back]').addEventListener('click', () => {
        if (executionInitial !== new URLSearchParams(new FormData(executionForm)).toString() && !window.confirm('実施登録の入力を保存せずに戻りますか？')) return;
        executionForm.hidden = true; form.hidden = false; panel.querySelector('[data-execution-toggle]').hidden = false;
    });
    executionForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!executionForm.reportValidity()) return;
        const button = executionForm.querySelector('[type=submit]'); button.disabled = true;
        try {
            const values = Object.fromEntries(new FormData(executionForm));
            const payload = { ...values, confirmed: executionForm.elements.confirmed.checked, vehicle_record_id: vehicle.id, kind: current.kind,
                plan_id: values.target_plan || null, version: values.target_plan ? current.version : 0 };
            const response = await api('/execution/preview', payload), result = response.result, actual = result.execution;
            pending = { ...payload, token: response.token }; review.dataset.savePath = '/execution/save';
            review.querySelector('#inspection-plan-review-title').textContent = '点検の実施登録を確認';
            review.querySelector('[data-plan-review-count]').textContent = (values.document_id ? '根拠書類を関連付けて登録します。' : '実施済み・書類未受領として登録します。') + (result.warning || '');
            const tbody = review.querySelector('[data-plan-review-rows]'); tbody.replaceChildren();
            const tr = node('tr');
            [result.number + '\n' + labels[actual.kind], result.before ? result.before.planned_month + ' の予定（実施未確認）' : '実施記録なし',
                '実施済み ' + actual.performed_date + '\n' + (actual.factory || '実施先未登録') + (result.certificate_evidence ? '\n更新後満了日 ' + (result.certificate_evidence?.new_expiry || '未確認') + '\n確認根拠 ' + result.certificate_evidence.confirmation : actual.kind === 'ad_hoc' ? '\n次回予定の自動作成なし' : '\n次回予定月 ' + actual.next_month) + (actual.next_source === 'calculated' ? '（周期から算出）' : '') + (result.skip_next_for_newer_record ? '\n新しい実績があるため次回予定は更新しません。' : '') + (result.existing_next.length ? '\n既存の予定・予約は保持します。' : '')].forEach(text => tr.append(node('td', text)));
            tbody.append(tr); error(review, '[data-review-error]'); review.showModal();
        } catch (e) { error(panel, '[data-execution-error]', e.message); }
        finally { button.disabled = false; }
    });
    if (!planner) return;
    if (planner.querySelector('[data-alert-check-status]')) {
        api('/alerts/status').then(value => {
            planner.querySelector('[data-alert-check-status]').textContent = value.last_checked_at ? '／確認済み' : '／未確認';
            const missing = value.report.no_recipient || 0, invalid = value.report.invalid || 0;
            const warning = planner.querySelector('[data-alert-recipient-warning]');
            warning.textContent = (missing ? '通知先がない予定 ' + missing + '件。車両と管理者の所属営業所を確認してください。' : '') + (invalid ? ' 予定月・予約日の要確認 ' + invalid + '件。' : '');
            warning.hidden = !warning.textContent;
        }).catch(() => { planner.querySelector('[data-alert-check-status]').textContent = '／確認できませんでした'; });
    }
    let view = ['year','calendar'].includes(args.view) ? args.view : 'month', kind = args.kind || '', state = args.state || '';
    const periodControl=planner.querySelector('[data-plan-period]'),periodHome=planner.querySelector('[data-period-home]');
    const monthInput=filters.elements.month;
    monthInput.addEventListener('click',()=>{try{monthInput.showPicker?.();}catch(_){}});
    let focus = args.vehicle_id ? Number(args.vehicle_id) : null;
    let loadNumber = 0, initialized = false;
    filters.elements.search.value=new URLSearchParams(location.search).get('q')||'';
    const localMonth = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit'}).format(new Date());
    filters.elements.month.value = args.month || (args.year ? args.year + '-04' : localMonth());
    const norm = s => (s || '').normalize('NFKC').replace(/\s/g, '').toLowerCase();
    function monthYear() { const m = filters.elements.month.value; return Number(m.slice(0,4)) - (Number(m.slice(5)) < 4 ? 1 : 0); }
    function periodRows() {
        if (!data) return [];
        const search = norm(filters.elements.search.value);
        const vehicles = data.vehicles.filter(v => (!focus || v.id === focus) && (!search || norm(v.number+' '+v.chassis_number).includes(search)));
        const ids = new Set(vehicles.map(v=>v.id));
        return data.plans.filter(p => ids.has(p.vehicle_record_id) && p.status !== 'cancelled' && (!kind || p.kind === kind) &&
            (view === 'year' || p.planned_month === filters.elements.month.value || p.performed_date?.slice(0,7) === filters.elements.month.value || p.expiry_date?.slice(0,7) === filters.elements.month.value));
    }
    function visiblePlans() { return periodRows().filter(p => !state || p.display_state === state); }
    function selectionChanged() {
        planner.querySelector('[data-plan-selected]').textContent = selected.size + '台選択';
        planner.querySelector('[data-plan-bulk]').hidden = !data.can_edit || !selected.size;
    }
    function edit(p,v) { openEditor(p,v,data.can_edit && (['planned','candidate','cancelled'].includes(p.status) || (p.kind === '12month' && p.status === 'completed' && p.document_status === '未受領'))); }
    function vehicleCell(v) {
        const td = node('td'), link = node('a',v.number); link.href = '/vehicle/karte/' + v.id + '/inspections'; link.className='ip-vehicle-link';
        td.append(link,node('small',v.office)); return td;
    }
    function checkbox(v) {
        const td=node('td'),cb=node('input');cb.type='checkbox';cb.checked=selected.has(v.id);cb.disabled=!data.can_edit;cb.setAttribute('aria-label',v.number+'を選択');
        cb.addEventListener('change',()=>{cb.checked?selected.add(v.id):selected.delete(v.id);draw();});td.append(cb);return td;
    }
    function badge(p) { const b=node('span',states[p.display_state] || '確認が必要','ip-badge');b.dataset.state=p.display_state;return b; }
    const eventLabels = {booking:'入庫予約', expiry:'車検満了', previous_expiry:'当時の満了日', actual:'実施済み'};
    function calendarEntries(rows,mon) {
        const result=[];
        for(const p of rows) {
            for(const [type,day] of [['booking',p.reservation_date],['expiry',p.expiry_date],['actual',p.performed_date]]) {
                if(day?.slice(0,7)!==mon)continue;
                // A completed booking stays as history; it is not a future slot to fill.
                if(type==='booking'&&p.status==='completed'&&day===p.performed_date)continue;
                result.push({p,day,type:type==='expiry'&&p.status==='completed'?'previous_expiry':type});
            }
        }
        return result.sort((a,b)=>a.day.localeCompare(b.day)||a.p.vehicle_record_id-b.p.vehicle_record_id||a.type.localeCompare(b.type));
    }
    const shortKinds={'3month':'3か月','12month':'12か月',ad_hoc:'突発'};
    const stateMarks={unreserved:'○',reserved:'●',awaiting:'!',completed:'✓',candidate:'＋'};
    function deadlineState(p) {
        if(!p.expiry_date||p.status==='completed')return '';
        return p.expiry_date<data.today?'overdue':p.expiry_date===data.today?'today':'';
    }
    const deadlineLabels={overdue:'期限超過',today:'本日期限'};
    const shortDate=day=>day?Number(day.slice(5,7))+'/'+Number(day.slice(8,10)):'';
    const calendarDays=new WeakMap();
    function openEntries(title,entries) {
        const dialog=document.querySelector('#inspection-plan-events');
        dialog.querySelector('#ip-events-title').textContent=title;
        const list=dialog.querySelector('[data-events-list]');list.replaceChildren();
        entries.forEach(entry=>list.append(calendarEvent(entry)));dialog.showModal();
    }
    document.querySelector('[data-events-close]')?.addEventListener('click',()=>document.querySelector('#inspection-plan-events').close());
    function calendarEvent(entry,compact=false) {
        const v=data.vehicles.find(v=>v.id===entry.p.vehicle_record_id);
        const button=node('button',undefined,'ip-cal-event');button.type='button';button.dataset.event=entry.type;
        const due=entry.type==='expiry'?deadlineState(entry.p):'';if(due)button.dataset.due=due;
        if(compact){button.classList.add('ip-cal-event-compact');button.append(node('span',deadlineLabels[due]||(entry.type==='booking'?'予約':entry.type==='actual'?'実施':entry.type==='previous_expiry'?'旧満了':'満了'),'ip-cal-event-type'),node('span',v.number+' '+shortKinds[entry.p.kind]));}
        else button.append(node('span',eventLabels[entry.type],'ip-cal-event-type'),node('strong',v.number),node('span',labels[entry.p.kind]+' · '+(entry.p.status==='completed'?'実施済み':states[entry.p.display_state])));
        if(!compact&&due)button.append(node('span',deadlineLabels[due],'ip-deadline-label'));
        if(!compact&&entry.type==='booking'&&entry.p.factory)button.append(node('small',entry.p.factory));
        button.setAttribute('aria-label',entry.day+' '+eventLabels[entry.type]+' '+v.number+' '+labels[entry.p.kind]+(due?' '+deadlineLabels[due]:''));
        button.title=(due?deadlineLabels[due]+' ／ ':'')+entry.day+' '+eventLabels[entry.type]+' '+v.number+' '+labels[entry.p.kind]+' ／ '+states[entry.p.display_state]+(entry.p.factory?' ／ '+entry.p.factory:'');
        button.addEventListener('click',()=>{const dialog=document.querySelector('#inspection-plan-events');if(dialog?.open)dialog.close();edit(entry.p,v);});return button;
    }
    function drawCalendar(rows) {
        const root=planner.querySelector('[data-plan-calendar]');root.replaceChildren();
        const mon=filters.elements.month.value,entries=calendarEntries(rows,mon),[year,m]=mon.split('-').map(Number);
        const legend=node('div',undefined,'ip-cal-legend');
        for(const type of ['booking','expiry','actual']){const item=node('span',eventLabels[type]);item.dataset.event=type;legend.append(item);}root.append(legend);
        const unscheduled=rows.filter(p=>!p.reservation_date&&p.status!=='completed'&&p.planned_month===mon).sort((a,b)=>(a.expiry_date||'9999').localeCompare(b.expiry_date||'9999')||a.vehicle_record_id-b.vehicle_record_id);
        const pending=node('section',undefined,'ip-cal-pending');pending.setAttribute('aria-label','予約日未定の予定');
        pending.append(node('h3','予約日未定 '+unscheduled.length+'件'));pending.title='表示月の予約日が未登録の予定';
        if(unscheduled.length){
            const cards=node('div',undefined,'ip-cal-pending-items');
            unscheduled.forEach(p=>{
                const v=data.vehicles.find(v=>v.id===p.vehicle_record_id),b=node('button',undefined,'ip-cal-pending-item');b.type='button';
                const due=deadlineState(p),status=p.status==='candidate'?'予定未登録':'予約未登録';
                const detail=(p.expiry_date?'車検期限 '+shortDate(p.expiry_date):labels[p.kind])+' · '+status;
                if(due){b.dataset.due=due;b.append(node('span',deadlineLabels[due],'ip-deadline-label'));}
                b.append(node('strong',v.number),node('span',detail));b.title=v.number+' ／ '+(p.expiry_date?'車検満了 '+p.expiry_date:labels[p.kind])+' ／ '+status+(due?' ／ '+deadlineLabels[due]:'');
                b.setAttribute('aria-label',b.title);b.addEventListener('click',()=>edit(p,v));cards.append(b);
            });pending.append(cards);
        }else pending.append(node('p','予約日が未定の予定はありません。'));
        root.append(pending,periodControl);
        const grid=node('div',undefined,'ip-cal-grid'),offset=(new Date(year,m-1,1).getDay()+6)%7,days=new Date(year,m,0).getDate();
        grid.setAttribute('aria-label',mon+' 日別の予定');grid.style.setProperty('--ip-weeks',Math.ceil((days+offset)/7));
        for(const [index,weekday] of ['月','火','水','木','金','土','日'].entries()){const label=node('div',weekday,'ip-cal-weekday');label.dataset.weekday=String((index+1)%7);grid.append(label);}
        for(let index=0;index<Math.ceil((days+offset)/7)*7;index++) {
            const n=index-offset+1,cell=node('section',undefined,'ip-cal-day');cell.dataset.weekday=String((index+1)%7);
            if(n<1||n>days){cell.classList.add('ip-cal-outside');cell.setAttribute('aria-hidden','true');grid.append(cell);continue;}
            const day=mon+'-'+String(n).padStart(2,'0'),events=entries.filter(e=>e.day===day),header=node('div',undefined,'ip-cal-day-head');
            const dateButton=node('button',String(n),'ip-cal-date');dateButton.type='button';dateButton.disabled=!data.can_edit||!data.vehicles.length;
            dateButton.setAttribute('aria-label',day+'の予定を追加');dateButton.addEventListener('click',()=>newPlan(null,mon,day));header.append(dateButton);
            const booked=new Set(events.filter(e=>e.type==='booking'&&e.p.status!=='completed').map(e=>e.p.vehicle_record_id)).size;
            if(booked)header.append(node('span','入庫 '+booked+'台','ip-cal-day-count'));
            cell.append(header);cell.dataset.date=day;cell.setAttribute('aria-label',day);cell.classList.toggle('ip-cal-today',day===data.today);if(day===data.today)dateButton.setAttribute('aria-current','date');cell.classList.toggle('ip-cal-no-events',!events.length);
            cell.append(node('span',day+'（'+['日','月','火','水','木','金','土'][new Date(year,m-1,n).getDay()]+'）','ip-cal-mobile-date'));
            const items=node('div',undefined,'ip-cal-items');cell.append(items);calendarDays.set(cell,events);events.forEach(e=>items.append(calendarEvent(e)));grid.append(cell);
        }
        root.append(grid);
        requestAnimationFrame(fitCalendar);
        if(!entries.length)root.append(node('p','この月の日付付きの予定・実績はありません。','ip-cal-empty'));
    }
    function fitCalendar() {
        if(view!=='calendar')return;
        const grid=planner.querySelector('.ip-cal-grid');if(!grid)return;
        const mobile=window.matchMedia('(max-width:700px)').matches;
        grid.style.height=mobile?'auto':Math.max(150,remainingHeight(grid)-footerHeight()-32-extraHeight())+'px';
        for(const cell of grid.querySelectorAll('[data-date]')) {
            const entries=calendarDays.get(cell)||[],items=cell.querySelector('.ip-cal-items');items.replaceChildren();
            const head=cell.querySelector('.ip-cal-day-head');
            const available=mobile?entries.length:Math.max(0,Math.floor((cell.clientHeight-head.offsetHeight-8)/22));
            const limit=mobile?entries.length:entries.length>available?Math.max(0,available-1):available;
            entries.slice(0,limit).forEach(entry=>items.append(calendarEvent(entry,!mobile)));
            if(entries.length>limit){const more=node('button','＋'+(entries.length-limit)+'件','ip-cal-more');more.type='button';more.setAttribute('aria-label',cell.dataset.date+'の予定をすべて表示');more.addEventListener('click',()=>openEntries(cell.dataset.date+' の予定・実績',entries));items.append(more);}
        }
    }
    // Use the app's scrolling viewport, including the space below the grid.
    function remainingHeight(element) {
        const main=planner.closest('.main-content');
        const bottom=Math.min(window.innerHeight,main?main.getBoundingClientRect().top+main.clientHeight:window.innerHeight);
        return bottom-element.getBoundingClientRect().top-window.scrollY-(main?.scrollTop||0);
    }
    function footerHeight() {
        return Math.max(...[...planner.querySelectorAll(':scope > details')].map(d=>d.querySelector('summary').offsetHeight),0)+12;
    }
    function extraHeight() {
        const empty=view==='calendar'?planner.querySelector('.ip-cal-empty'):null,action=planner.querySelector('[data-empty-action]');
        return (empty?empty.offsetHeight+8:0)+(action&&!action.hidden?action.offsetHeight+8:0);
    }
    function fitTable() {
        const scroll=planner.querySelector('.ip-grid-scroll');
        if(view==='calendar'||window.matchMedia('(max-width:700px)').matches){scroll.style.maxHeight='';return;}
        scroll.style.maxHeight=Math.max(100,remainingHeight(scroll)-footerHeight()-32-extraHeight())+'px';
    }
    function fitLayout(){fitTable();fitCalendar();}
    let fitFrame;
    window.addEventListener('resize',()=>{cancelAnimationFrame(fitFrame);fitFrame=requestAnimationFrame(fitLayout);});
    // Recalculate when filters wrap or the sidebar changes the available width.
    const calendarResize=new ResizeObserver(()=>{cancelAnimationFrame(fitFrame);fitFrame=requestAnimationFrame(fitLayout);});
    calendarResize.observe(filters);
    calendarResize.observe(planner.querySelector('[data-plan-bulk]'));
    function comparePlans(a,b) {
        const rank=p=>p.status==='completed'?3:p.display_state==='awaiting'||(p.expiry_date&&p.expiry_date<=data.today)?0:!p.reservation_date?1:2;
        return rank(a)-rank(b)||(a.expiry_date||a.reservation_date||a.planned_month).localeCompare(b.expiry_date||b.reservation_date||b.planned_month)||a.vehicle_record_id-b.vehicle_record_id;
    }
    function draw() {
        if (!data) return;
        planner.dataset.view=view;
        periodHome.append(periodControl);
        const selectedMonth=filters.elements.month.value;
        planner.querySelector('[data-period-title]').textContent=view==='year'?monthYear()+'年度':Number(selectedMonth.slice(0,4))+'年'+Number(selectedMonth.slice(5))+'月';
        periodControl.querySelector('[data-period="-1"]').setAttribute('aria-label',view==='year'?'前の年度':'前の月');
        periodControl.querySelector('[data-period="1"]').setAttribute('aria-label',view==='year'?'次の年度':'次の月');
        const period=periodRows(), rows=visiblePlans();
        const visibleIds=new Set(rows.map(p=>p.vehicle_record_id));
        const search=norm(filters.elements.search.value);
        const vehicles=data.vehicles.filter(v=>(!focus||v.id===focus)&&(!search||norm(v.number+' '+v.chassis_number).includes(search))&&(!state||visibleIds.has(v.id)));
        selected=new Set([...selected].filter(id=>vehicles.some(v=>v.id===id)));
        planner.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(view===b.dataset.view)));
        planner.querySelectorAll('[data-kind]').forEach(b=>b.setAttribute('aria-pressed',String(kind===b.dataset.kind)));
        const focusButton=planner.querySelector('[data-plan-focus]');focusButton.hidden=!focus;focusButton.textContent='対象車両の絞込を解除 ×';
        const counts=planner.querySelector('[data-plan-states]');counts.replaceChildren();
        for(const [key,label] of [['','すべて'],...Object.entries(states)]) {
            const count=period.filter(p=>key?p.display_state===key:true).length;
            const b=node('button',(stateMarks[key]?stateMarks[key]+' ':'')+label+' '+count+'件');b.type='button';b.dataset.state=key;b.setAttribute('aria-pressed',String(state===key));
            b.addEventListener('click',()=>{state=key;draw();});counts.append(b);
        }
        const year=monthYear(), months=Array.from({length:12},(_,i)=>`${year+(i>=9?1:0)}-${String((i+3)%12+1).padStart(2,'0')}`);
        const bulkMonth=planner.querySelector('[data-plan-bulk-month]'),old=bulkMonth.value;bulkMonth.replaceChildren();
        months.forEach(m=>{const o=node('option',m);o.value=m;bulkMonth.append(o);});bulkMonth.value=months.includes(old)?old:filters.elements.month.value;
        const head=planner.querySelector('[data-plan-grid-head]'),body=planner.querySelector('[data-plan-grid-body]');head.replaceChildren();body.replaceChildren();
        const hr=node('tr'),allCell=node('th'),all=node('input');all.type='checkbox';all.disabled=!data.can_edit;all.setAttribute('aria-label','表示中の車両を全選択');
        const targetVehicles=view==='year'?vehicles:vehicles.filter(v=>visibleIds.has(v.id));
        all.checked=!!targetVehicles.length&&targetVehicles.every(v=>selected.has(v.id));
        all.addEventListener('change',()=>{selected=all.checked?new Set(targetVehicles.map(v=>v.id)):new Set();draw();});allCell.append(all);hr.append(allCell);
        const columns=view==='year'?['車両・営業所',...months.map(m=>Number(m.slice(5))+'月')]:['車両・営業所','点検種別','期限・予定月','入庫予定','実施先','状態','実施日','操作'];
        columns.forEach((label,i)=>{const th=node('th',label);if(view==='year'&&months[i-1]===localMonth())th.classList.add('ip-current-month');hr.append(th);});head.append(hr);
        planner.querySelector('.ip-grid-scroll').hidden=view==='calendar';
        planner.querySelector('[data-plan-calendar]').hidden=view!=='calendar';
        if(view==='calendar')drawCalendar(rows);
        planner.querySelector('.ip-grid').classList.toggle('ip-month-table',view==='month');
        planner.querySelector('.ip-grid').classList.toggle('ip-year-table',view==='year');
        if(view==='year') {
            for(const v of vehicles) {
                const tr=node('tr');tr.append(checkbox(v),vehicleCell(v));
                for(const mon of months) {
                    const td=node('td');if(mon===localMonth())td.classList.add('ip-current-month');td.append(node('span',mon,'ip-mobile-month'));
                    const items=rows.filter(p=>p.vehicle_record_id===v.id&&(p.planned_month===mon||p.performed_date?.slice(0,7)===mon)).sort(comparePlans);
                    const stack=node('div',undefined,'ip-year-items');
                    items.slice(0,items.length>3?2:3).forEach(p=>{
                        const expiryCandidate=p.kind==='12month'&&p.status==='candidate'&&p.expiry_date;
                        const b=node('button',expiryCandidate?'車検期限':stateMarks[p.display_state]+' '+shortKinds[p.kind],'ip-chip');b.classList.toggle('ip-expiry-candidate',expiryCandidate);b.type='button';b.dataset.status=p.status;b.dataset.state=p.display_state;
                        b.title=(expiryCandidate?'車検満了日を基に表示 ／ 予定未登録（予約なし）':labels[p.kind]+' ／ '+states[p.display_state])+' ／ 予定月 '+p.planned_month+(p.reservation_date?' ／ 予約 '+p.reservation_date:'')+(p.expiry_date?' ／ 満了 '+p.expiry_date:'')+(p.performed_date?' ／ 実施 '+p.performed_date:'');
                        b.setAttribute('aria-label',v.number+' '+mon+' '+b.title);b.addEventListener('click',()=>edit(p,v));stack.append(b);
                    });
                    if(items.length>3){const more=node('button','＋'+(items.length-2)+'件','ip-year-more');more.type='button';more.addEventListener('click',()=>openEntries(v.number+' ／ '+mon,items.map(p=>({p,day:p.performed_date||p.reservation_date||mon,type:p.status==='completed'?'actual':p.expiry_date?'expiry':'booking'}))));stack.append(more);}
                    if(!items.length){if(data.can_edit){const add=node('button','＋','ip-cell-add');add.type='button';add.setAttribute('aria-label',v.number+' '+mon+'の予定を追加');add.addEventListener('click',()=>newPlan(v,mon));stack.append(add);}else stack.append(node('span','—','ip-year-empty'));}
                    td.append(stack);tr.append(td);
                }body.append(tr);
            }
        } else {
            for(const p of rows.sort(comparePlans)) {
                const v=data.vehicles.find(v=>v.id===p.vehicle_record_id),tr=node('tr');tr.append(checkbox(v),vehicleCell(v),node('td',labels[p.kind]));
                const due=node('td');if(p.expiry_date)due.append(node('span',(p.status==='completed'?'当時の満了日 ':'車検満了 ')+p.expiry_date));due.append(node('small',(p.status==='candidate'?'候補月 ':'予定月 ')+p.planned_month));tr.append(due,node('td',p.reservation_date||'未定'),node('td',p.factory||'—'));
                const status=node('td');status.append(badge(p));if(p.status==='completed')status.append(node('small','書類'+(p.document_status||'未確認')));tr.append(status,node('td',p.performed_date||'—'));
                const action=node('td'),b=node('button',p.status==='completed'?'実施内容':p.display_state==='awaiting'?'実施を確認':p.status==='candidate'?'予定に登録':!p.reservation_date?'予約日を登録':'予約を確認','btn btn-outline');b.type='button';b.addEventListener('click',()=>edit(p,v));action.append(b);tr.append(action);body.append(tr);
                Array.from(tr.children).forEach((td,i)=>{td.dataset.label=['選択',...columns][i];});
            }
        }
        if(!body.children.length){const tr=node('tr'),td=node('td',data.needs_office?'営業所を選択してください。':state?'この条件に該当する点検はありません。':'この期間の予定・実績はありません。','ip-empty');td.colSpan=columns.length+1;tr.append(td);body.append(tr);}
        const missing=data.missing.filter(p=>(!kind||p.kind===kind)&&vehicles.some(v=>v.id===p.vehicle_record_id));
        planner.querySelector('[data-plan-missing-count]').textContent='基準未設定 '+missing.length+'件';
        const list=planner.querySelector('[data-plan-missing]');list.replaceChildren();missing.forEach(p=>{const v=data.vehicles.find(v=>v.id===p.vehicle_record_id);list.append(node('li',v.number+' ／ '+labels[p.kind]+'：'+p.reason));});
        planner.querySelector('[data-plan-status]').textContent=data.needs_office?'所属営業所が未設定です。':(view==='year'?year+'年度（4月〜翌3月） ／ ':'')+vehicles.length+'台 ／ 対象'+period.length+'件（登録済み'+period.filter(p=>p.status!=='candidate').length+'件・予定未登録'+period.filter(p=>p.status==='candidate').length+'件）'+(state?' ／ 絞込後'+rows.length+'件':'');
        planner.querySelector('[data-plan-add]').hidden=!data.can_edit||!data.vehicles.length;
        selectionChanged();
        planner.querySelector('[data-empty-action]').hidden=!!rows.length||data.needs_office||view==='year';
        planner.querySelector('[data-empty-add]').hidden=!data.can_edit||!data.vehicles.length;
        const filtered=!!(kind||state||filters.elements.search.value||focus);
        planner.querySelector('[data-clear-filters]').hidden=!filtered;
        planner.querySelector('[data-empty-message]').textContent=filtered?'この条件に該当する点検はありません。':'予定を追加するか、基準未設定の車両を確認してください。';
        const url=new URL(location.href);url.search='';
        const office=filters.elements.office.value;url.searchParams.set('scope',office==='__company'?'company':'office');if(office&&office!=='__company')url.searchParams.set('office',office);
        for(const [k,v] of Object.entries({month:filters.elements.month.value,view,kind,state,q:filters.elements.search.value,vehicle_id:focus||''}))if(v)url.searchParams.set(k,v);
        history.replaceState(null,'',url);
        requestAnimationFrame(fitLayout);
    }
    async function load() {
        const seq=++loadNumber;error(planner,'[data-planner-error]');
        const params=new URLSearchParams({month:filters.elements.month.value,year:monthYear()});
        if(initialized){const office=filters.elements.office.value;params.set('scope',office==='__company'?'company':'office');if(office&&office!=='__company')params.set('office',office);if(focus)params.set('vehicle_id',focus);}
        else {for(const k of ['scope','office','vehicle_id'])if(args[k])params.set(k,args[k]);}
        const value=await api('?'+params);if(seq!==loadNumber)return;data=value;
        if(!initialized){const select=filters.elements.office;select.replaceChildren();for(const [val,label] of [['','営業所を選択'],['__company','会社全体'],...data.offices.map(o=>[o,o])]){const o=node('option',label);o.value=val;select.append(o);}select.value=data.scope==='company'?'__company':data.office;initialized=true;}
        draw();
    }
    const safeLoad=()=>load().catch(e=>error(planner,'[data-planner-error]',e.message));
    filters.addEventListener('submit',e=>{e.preventDefault();safeLoad();});
    filters.elements.office.addEventListener('change',()=>{focus=null;selected.clear();safeLoad();});
    filters.elements.search.addEventListener('input',draw);
    monthInput.addEventListener('change',()=>{if(monthInput.checkValidity()){selected.clear();safeLoad();}});
    planner.querySelector('[data-plan-focus]').addEventListener('click',()=>{focus=null;safeLoad();});
    planner.querySelectorAll('[data-kind]').forEach(b=>b.addEventListener('click',()=>{kind=b.dataset.kind;selected.clear();draw();}));
    planner.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.view;selected.clear();draw();}));
    planner.querySelectorAll('[data-period]').forEach(b=>b.addEventListener('click',()=>{
        const parts=monthInput.value.split('-').map(Number),n=parts[0]*12+parts[1]-1+Number(b.dataset.period)*(view==='year'?12:1);
        if(n<2000*12||n>2098*12+11)return;monthInput.value=Math.floor(n/12)+'-'+String(n%12+1).padStart(2,'0');selected.clear();safeLoad();
    }));
    const newDialog=document.querySelector('#inspection-plan-new'),newForm=newDialog.querySelector('form');
    function newPlan(v=null,mon=filters.elements.month.value,day=''){
        newForm.dataset.reservation=day;
        const select=newForm.elements.vehicle;select.replaceChildren();data.vehicles.forEach(v=>{const o=node('option',v.number+' ／ '+v.office);o.value=v.id;select.append(o);});
        if(v||focus)select.value=String(v?.id||focus);newForm.elements.kind.value=kind||'3month';newForm.elements.month.value=mon;newDialog.showModal();
    }
    planner.querySelector('[data-clear-filters]').addEventListener('click',()=>{kind='';state='';focus=null;filters.elements.search.value='';selected.clear();safeLoad();});
    planner.querySelector('[data-empty-add]').addEventListener('click',()=>newPlan());
    planner.querySelector('[data-plan-add]').addEventListener('click',()=>newPlan());
    newDialog.querySelectorAll('[data-new-close]').forEach(b=>b.addEventListener('click',()=>newDialog.close()));
    newForm.addEventListener('submit',e=>{e.preventDefault();const v=data.vehicles.find(v=>v.id===Number(newForm.elements.vehicle.value)),k=newForm.elements.kind.value,mon=newForm.elements.month.value;newDialog.close();const existing=k==='ad_hoc'?null:data.plans.find(p=>p.vehicle_record_id===v.id&&p.kind===k&&p.planned_month===mon&&p.status!=='cancelled');openEditor(existing||{id:null,version:0,kind:k,vehicle_record_id:v.id,planned_month:mon,period_key:mon,reservation_date:newForm.dataset.reservation?.slice(0,7)===mon?newForm.dataset.reservation:'',source:'manual',status:'candidate'},v,data.can_edit && existing?.status!=='completed');});
    planner.querySelector('[data-plan-generate]').addEventListener('click',async()=>{
        try{const rows=visiblePlans().filter(p=>selected.has(p.vehicle_record_id)&&p.status==='candidate');if(!rows.length)throw new Error('登録する候補のある車両を選択してください。');await showReview(rows.map(p=>({...p,status:'planned'})));}catch(e){error(planner,'[data-planner-error]',e.message);}
    });
    planner.querySelector('[data-plan-bulk-apply]').addEventListener('click',async()=>{
        try{const mon=planner.querySelector('[data-plan-bulk-month]').value,reservation=planner.querySelector('[data-plan-bulk-date]').value,factory=planner.querySelector('[data-plan-bulk-factory]').value.trim();if(!reservation&&!factory)throw new Error('予約日か実施先を入力してください。空欄は現在の値を維持します。');const rows=visiblePlans().filter(p=>selected.has(p.vehicle_record_id)&&p.planned_month===mon&&['candidate','planned'].includes(p.status));if(!rows.length)throw new Error('変更する予定のある車両と月を選択してください。');await showReview(rows.map(p=>({...p,reservation_date:reservation||p.reservation_date,factory:factory||p.factory,status:'planned'})));}catch(e){error(planner,'[data-planner-error]',e.message);}
    });
    safeLoad();
})();
