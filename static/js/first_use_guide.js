(function () {
  'use strict';
  const plans = {
    "dashboard": [
        {
            "selector": ".dashboard-vehicles-section",
            "title": "使用車両を確認する",
            "text": "上部に、自分が使用する車両が表示されます。"
        },
        {
            "selector": ".dashboard-vehicle-action-primary",
            "title": "日常点検を開く",
            "text": "使用車両の「日常点検」から点検表を開きます。"
        },
        {
            "selector": ".dashboard-safety-opening",
            "title": "安全管理の対応を見る",
            "text": "内容を押すと、確認・対応する画面を開きます。"
        },
        {
            "selector": ".dashboard-attention-preview a.dashboard-video-proposal, .dashboard-attention-table td:last-child a",
            "title": "AIの整備提案を見る",
            "text": "「詳細」から提案の理由と対応を確認します。"
        },
        {
            "selector": ".dashboard-trend-tabs",
            "title": "営業所の傾向を見る",
            "text": "安全・点検と整備費を切り替えて確認できます。"
        },
        {
            "selector": "[data-reference-target=\"#dashboard-reference-inspection\"]",
            "title": "期限や集計を確認する",
            "text": "車検期限が近い車両など、下の集計を開けます。"
        },
        {
            "selector": "#sidebarToggle",
            "title": "メニューから画面を選ぶ",
            "text": "メニューを開き、安全管理や車両管理の画面へ進めます。"
        }
    ],
    "vehicle_karte": [
        {
            "selector": ".ko-status-tile",
            "title": "点検・運行判断を確認する",
            "text": "状態を押すと、この車両の点検記録を開きます。"
        },
        {
            "selector": ".ko-action-button",
            "title": "必要な対応を開く",
            "text": "対応ボタンから、内容を確認する画面へ進みます。"
        },
        {
            "selector": ".vehicle-karte-tab[href*=\"/history\"]",
            "title": "これまでの記録を見る",
            "text": "「履歴」で点検・整備・日報を時系列で確認できます。"
        },
        {
            "selector": ".vehicle-karte-tab[href*=\"/analysis\"]",
            "title": "分析を見る",
            "text": "「分析」で実績の集計や整備提案を確認できます。"
        }
    ],
    "vehicle_karte_history": [
        {
            "selector": ".vehicle-history-categories",
            "title": "記録の種類を選ぶ",
            "text": "見たいカテゴリを押すと、記録を絞れます。"
        },
        {
            "selector": ".vehicle-karte-history-filters select[name=\"event_type\"]",
            "title": "種別を選ぶ",
            "text": "見たい記録の種別を選びます。"
        },
        {
            "selector": "#history_start_date",
            "title": "期間を指定する",
            "text": "開始日と終了日を選びます。"
        },
        {
            "selector": ".vehicle-karte-history-filters button[type=\"submit\"]",
            "title": "条件を反映する",
            "text": "「絞り込み」を押すと、選んだ条件の履歴を表示します。"
        },
        {
            "selector": ".vehicle-history-record-link",
            "title": "元の記録を見る",
            "text": "記録のリンクから、内容を詳しく確認できます。"
        },
        {
            "selector": ".vehicle-karte-tab:first-child",
            "title": "概要へ戻る",
            "text": "「概要」で車両の状態と次の対応を確認できます。"
        }
    ],
    "vehicle_karte_analysis": [
        {
            "selector": "#ka-start-date",
            "title": "集計期間を選ぶ",
            "text": "開始日と終了日を選びます。"
        },
        {
            "selector": ".ka-period-form button[type=\"submit\"]",
            "title": "実績を集計する",
            "text": "「集計」を押すと、選んだ期間の実績を表示します。"
        },
        {
            "selector": ".ka7-kpis",
            "title": "実績を確認する",
            "text": "選んだ期間の走行距離・整備費などを確認します。"
        },
        {
            "selector": "#ka-ai-results",
            "title": "整備提案を確認する",
            "text": "表示された提案の内容を確認します。"
        },
        {
            "selector": ".ka7-proposals .ka-reference-detail-button",
            "title": "提案の根拠と対応を見る",
            "text": "詳細ボタンで根拠や対応記録を開きます。"
        },
        {
            "selector": ".vehicle-karte-tab[href*=\"/history\"]",
            "title": "記録を確認する",
            "text": "「履歴」から、この車両の点検・整備・日報を確認できます。"
        }
    ],
    "pointouts": [
        {
            "selector": ".safety-summary-grid",
            "title": "状態で絞る",
            "text": "集計を押すと、その状態の指摘を確認できます。"
        },
        {
            "selector": "#pointouts-list",
            "title": "指摘を確認する",
            "text": "一覧から指摘の詳細を開きます。"
        }
    ],
    "pointout_detail": [
        {
            "selector": ".pointout-basic-grid",
            "title": "指摘の状態を確認する",
            "text": "対象と現在の状態を確認します。"
        },
        {
            "selector": ".pointout-content-card",
            "title": "指摘内容を見る",
            "text": "指摘された内容を確認します。"
        },
        {
            "selector": ".pointout-countermeasure-form",
            "title": "対策を記録する",
            "text": "対策と担当者を確認して保存します。"
        },
        {
            "selector": ".pointout-approval-card",
            "title": "対策を確認・判断する",
            "text": "表示された内容を確認して判断します。"
        }
    ],
    "driving_reports": [
        {
            "selector": "#driving-filter-form",
            "title": "実績の範囲を選ぶ",
            "text": "対象期間などの条件で実績を絞れます。"
        },
        {
            "selector": ".driving-view-switch",
            "title": "表示を切り替える",
            "text": "自分の実績と管理画面を切り替えます。"
        }
    ],
    "driving_report_detail": [
        {
            "selector": ".driving-heading",
            "title": "日報を確認する",
            "text": "日付と車両を確認します。"
        },
        {
            "selector": "#report-source-info",
            "title": "詳しい情報を見る",
            "text": "開くと、運行や帳票の詳しい情報を確認できます。"
        },
        {
            "selector": ".driving-actions",
            "title": "元資料や一覧へ進む",
            "text": "表示されているボタンから、元資料や一覧へ進めます。"
        }
    ],
    "vehicle_karte_inspections": [
        {
            "selector": ".vehicle-karte-inspections-panel",
            "title": "点検の記録を見る",
            "text": "この車両の点検記録と実施状況を確認します。"
        }
    ],
    "vehicle_karte_maintenance": [
        {
            "selector": "#km-maintenance-filters",
            "title": "整備履歴を絞る",
            "text": "条件を選んで整備・修理の履歴を確認します。"
        },
        {
            "selector": ".km-list-panel",
            "title": "整備内容を見る",
            "text": "整備・修理の記録を確認します。"
        }
    ],
    "vehicle_karte_parts": [
        {
            "selector": "#kp-filter-form",
            "title": "交換履歴を絞る",
            "text": "条件を選んで部品交換の履歴を確認します。"
        },
        {
            "selector": "#kp-current-title",
            "title": "部品の状態を見る",
            "text": "この車両の部品状態を確認します。"
        }
    ],
    "vehicle_karte_costs": [
        {
            "selector": "#kc-year",
            "title": "集計する年を選ぶ",
            "text": "表示する年を選びます。"
        },
        {
            "selector": ".kc-summary-grid",
            "title": "費用の内訳を見る",
            "text": "整備などの費用を確認します。"
        },
        {
            "selector": ".kc-table",
            "title": "集計の数値を見る",
            "text": "表で詳しい金額を確認できます。"
        }
    ],
    "vehicle_karte_documents": [
        {
            "selector": ".kd-type-tabs",
            "title": "書類の種類を選ぶ",
            "text": "確認したい書類の種類に切り替えます。"
        },
        {
            "selector": ".kd-document-table",
            "title": "書類を確認する",
            "text": "一覧から書類を確認します。"
        }
    ],
    "vehicle_inspection_plans": [
        {
            "selector": "#inspection-plan-filters",
            "title": "計画の条件を選ぶ",
            "text": "車両などの条件で点検計画を絞れます。"
        },
        {
            "selector": ".ip-month-picker",
            "title": "表示する月を選ぶ",
            "text": "確認したい年月を選びます。"
        },
        {
            "selector": ".ip-grid-scroll",
            "title": "予定を確認する",
            "text": "表示された予定から詳しい内容を確認します。"
        }
    ],
    "safety_checklists": [
        {
            "selector": ".safety-checklist-list-table",
            "title": "チェックリストを選ぶ",
            "text": "一覧から確認するチェックリストを選びます。"
        }
    ],
    "safety_checklist_results": [
        {
            "selector": ".safety-results-table",
            "title": "点検結果を確認する",
            "text": "記録の日付と結果を確認します。"
        },
        {
            "selector": ".safety-results-mobile-list",
            "title": "点検結果を確認する",
            "text": "記録の日付と結果を確認します。"
        }
    ],
    "notifications": [
        {
            "selector": ".notification-tabs",
            "title": "通知を絞る",
            "text": "表示する通知を切り替えます。"
        },
        {
            "selector": "#notificationReadAllButton",
            "title": "まとめて既読にする",
            "text": "内容を確認したら、まとめて既読にできます。"
        }
    ],
    "notification_detail": [
        {
            "selector": ".nd-content",
            "title": "通知の内容を見る",
            "text": "対象と通知内容を確認します。"
        },
        {
            "selector": ".nd-close",
            "title": "通知一覧へ戻る",
            "text": "閉じると通知一覧に戻ります。"
        }
    ],
    "new_pointout": [
        {
            "selector": "#event_date",
            "title": "日付と分類を確認する",
            "text": "指摘した日付と分類を選びます。"
        },
        {
            "selector": "#target_user_search",
            "title": "対象を選ぶ",
            "text": "対象者を検索し、候補から選びます。"
        },
        {
            "selector": "#delivery_place",
            "title": "対象の場所を選ぶ",
            "text": "指摘する対象の場所を確認します。"
        },
        {
            "selector": "#content_editor",
            "title": "指摘内容を入力する",
            "text": "指摘の内容を入力します。"
        },
        {
            "selector": ".file-upload-cell",
            "title": "写真や資料を添える",
            "text": "必要な写真やファイルを選びます。"
        },
        {
            "selector": ".form-actions button[type=\"submit\"]",
            "title": "内容を確認して登録する",
            "text": "入力した内容を確認して登録します。"
        }
    ],
    "edit_pointout": [
        {
            "selector": "#event_date",
            "title": "変更する記録を確認する",
            "text": "日付と対象を確認します。"
        },
        {
            "selector": "#content_editor",
            "title": "指摘内容を編集する",
            "text": "変更する内容を入力します。"
        },
        {
            "selector": ".pointout-file-upload-cell",
            "title": "添付を確認する",
            "text": "残す添付と追加する写真・ファイルを確認します。"
        },
        {
            "selector": ".pointout-edit-actions button[type=\"submit\"]",
            "title": "変更を保存する",
            "text": "内容を確認して更新します。"
        }
    ],
    "vehicle_data_import": [
        {
            "selector": ".vehicle-registration-method-grid",
            "title": "資料の種類を選ぶ",
            "text": "取り込む資料に合う欄を選びます。"
        },
        {
            "selector": ".import-dropzone",
            "title": "ファイルを選ぶ",
            "text": "その資料の欄へファイルを追加します。"
        },
        {
            "selector": ".import-read",
            "title": "読み取りを始める",
            "text": "選んだファイルを確認して「読み込む」を押します。"
        },
        {
            "selector": ".import-receipts-heading",
            "title": "受付済み資料を確認する",
            "text": "受付済みの資料から進み具合や結果を確認できます。"
        }
    ],
    "document_import_job": [
        {
            "selector": "#jobSummary",
            "title": "読み取り状況を確認する",
            "text": "完了・種類の確認・失敗の件数を確認します。"
        },
        {
            "selector": "#jobFiles",
            "title": "資料ごとの状態を見る",
            "text": "種類の確認が必要な資料は、該当するリンクから確認します。"
        },
        {
            "selector": "#jobPreview",
            "title": "読取結果を確認する",
            "text": "準備ができた資料の読取結果を開きます。"
        }
    ],
    "document_import_kind": [
        {
            "selector": ".document-kind-source",
            "title": "原本を確認する",
            "text": "原本を見て資料の種類を確認します。"
        },
        {
            "selector": "#document-kind",
            "title": "種類を選び直す",
            "text": "読み直す種類を選びます。読み直すと修正中の読取結果は置き換わります。"
        }
    ],
    "vehicle_document_import_preview": [
        {
            "selector": ".vehicle-document-import-preview",
            "title": "原本と読取内容を照合する",
            "text": "登録する記録と対象車両を確認します。"
        },
        {
            "selector": ".invoice-primary-action",
            "title": "確認した記録を登録する",
            "text": "内容を確認してから登録します。"
        }
    ]
,
    vehicle_checklist_results: [
      { selector: '#vehicle_search', title: '車両を選ぶ', text: '車両を検索するか、使用車両のボタンから選びます。' },
      { selector: '.inspection-item-detail', title: '項目の詳細を見る', text: '項目名を押すと詳細が開きます。水色はコメントや写真・添付がある印です。押すと内容を確認できます。' },
      { selector: '.check-choice-buttons', title: '評価を入れる', text: '各項目の評価を選びます。✓・×の意味は、その項目の評価基準で確認できます。' },
      { selector: '.vehicle-check-complete-form .approval-user-search', title: '依頼先を選ぶ', text: '名前で検索し、候補から依頼先を選びます。' },
      { selector: '#notify_user_search', title: '点検完了通知先を選ぶ', text: '点検が完了したことを知らせる相手を、名前で検索して選びます。' },
      { selector: '#reminder_notify_user_search', title: '点検未実施通知先を選ぶ', text: '未実施のときに通知する相手を、名前で検索して選びます。' },
      { selector: '.reminder-readonly', title: '点検未実施通知先を確認する', text: '設定されている通知先を確認します。変更は管理者が行います。' },
      { selector: '.vehicle-check-complete-primary', title: '点検を完了する', text: '評価と依頼先を確認したら「点検完了」を押します。差し戻し後は「修正して再申請」です。' }
    ]
  };
  const normalPlans = {"dashboard":[{"selector":".dashboard-vehicle-action-primary","title":"日常点検を開く","text":"ここから、この車両の日常点検表を開けます。"},{"selector":".dashboard-vehicle-action","title":"車両の点検表","text":"車両ごとの点検表を開けます。"},{"selector":"#sidebarToggle","title":"メニューから画面を選ぶ","text":"メニューを開き、「安全管理」「車両管理」から使いたい画面を選べます。"}],"vehicle_checklist_results":[{"selector":"#vehicle_check_filter select[name=\"vehicle_record_id\"]","title":"車両を選ぶ","text":"ここで、点検表を表示する車両を選べます。"},{"selector":".inspection-item-detail","title":"項目の詳細を見る","text":"項目名を押すと、評価基準や詳細が開きます。入力できる記録では、コメントや写真も追加できます。"},{"selector":".check-choice-buttons","title":"評価を入れる","text":"各項目の評価を選びます。✓・×の意味は、その項目の評価基準で確認できます。"},{"selector":".vehicle-check-complete-form .approval-user-search","title":"依頼先を選ぶ","text":"名前で検索し、候補から依頼先を選びます。"},{"selector":"#notify_user_search","title":"点検完了通知先を選ぶ","text":"点検が完了したことを知らせる相手を、名前で検索して選びます。"},{"selector":"#reminder_notify_user_search","title":"点検未実施通知先を選ぶ","text":"未実施のときに通知する相手を、名前で検索して選びます。"},{"selector":".reminder-readonly","title":"点検未実施通知先を確認する","text":"設定されている通知先を確認します。変更は管理者が行います。"},{"selector":".vehicle-check-complete-primary","title":"点検を完了する","text":"評価と依頼先を確認したら「点検完了」を押します。差し戻し後は「修正して再申請」です。"}]};
  function key(mode, page) { return 'dkss:first-guide:v1:' + mode + ':' + page; }
  function state(storage, name) {
    try { const test=name+':probe'; storage.setItem(test,'1'); storage.removeItem(test); return { available:true, seen:storage.getItem(name)==='1' }; }
    catch (_) { return { available:false, seen:true }; }
  }
  function candidates(page, find, mode = "normal") {
    if (mode === "demo" && page === "notifications" && find("#notificationDetailPane .dkss-notification-detail")) page="notification_detail";
    const result=[];
    for (const step of (mode === "demo" ? plans[page] : normalPlans[page]) || []) {
      const target=find(step.selector);
      if (target && !result.some(s=>s.target===target)) {
        const content=target.dataset || {};
        result.push({...step,target,title:content.guideTitle || step.title,text:content.guideText || step.text});
      }
    }
    return result;
  }
  // Explicit help may reveal an existing record; automatic help never changes disclosure state.
  function revealRecord(page, manual, record) {
    if (!manual || page !== 'vehicle_checklist_results' || !record ||
        record.tagName !== 'DETAILS' || record.open ||
        record.closest('[hidden], [inert]') || !record.querySelector('.inspection-item-detail')) return false;
    record.open = true;
    return true;
  }
  // A guide step is not navigation. Keep the current viewport whenever the
  // target is already visible; large regions only need to intersect it.
  function revealOptions(rect, viewport, reducedMotion) {
    const margin=0, left=viewport.left+margin, top=viewport.top+margin;
    const right=viewport.left+viewport.width-margin, bottom=viewport.top+viewport.height-margin;
    const fits=(start,end,low,high)=>end-start>high-low ? end>low && start<high : start>=low && end<=high;
    if(fits(rect.left,rect.right,left,right) && fits(rect.top,rect.bottom,top,bottom)) return null;
    return {block:'nearest',inline:'nearest',behavior:reducedMotion?'instant':'smooth'};
  }
  function coachmarkPlacement(rect, viewport, width, height) {
    const gap=12, edge=12, leftEdge=viewport.left+edge, rightEdge=viewport.left+viewport.width-edge;
    const topEdge=viewport.top+edge, bottomEdge=viewport.top+viewport.height-edge;
    const left=Math.max(leftEdge,Math.min(rightEdge-width,rect.left));
    const below=rect.bottom+gap, above=rect.top-height-gap;
    let side='below', top=below;
    if(below+height>bottomEdge){side='above';top=above;}
    if(top<topEdge){top=Math.max(topEdge,bottomEdge-height);side='overlap';}
    const targetCenter=Math.max(rect.left,Math.min(rect.right,(left+width/2)));
    const arrow=Math.max(20,Math.min(width-20,targetCenter-left));
    return {left,top,side,arrow};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports={key,state,candidates,revealRecord,revealOptions,coachmarkPlacement};
  if (typeof document === 'undefined') return;
  const root=document.getElementById('firstUseGuide');
  if (!root) return;
  const panel=root.querySelector('.first-guide-panel'), launch=root.querySelector('[data-guide-open]');
  const title=root.querySelector('[data-guide-title]'), text=root.querySelector('[data-guide-text]'), count=root.querySelector('[data-guide-count]');
  const next=root.querySelector('[data-guide-next]');
  const picture=root.querySelector('[data-guide-picture]');
  const aiPicture=root.querySelector('[data-guide-ai-picture]');
  const name=key(root.dataset.mode,root.dataset.page);
  let storage; try { storage=window.localStorage; } catch (_) { storage=null; }
  const initial=state(storage,name);
  let steps=[], index=0, active=null, previous=null;
  let resumeSelector=null;
  const resumable=root.dataset.mode==='demo' && root.dataset.page==='vehicle_checklist_results';
  const launchLabel=launch.querySelector('span:last-child');
  function clearResume(){resumeSelector=null;if(launchLabel)launchLabel.textContent='使い方';}
  function pauseForOperation(target){
    if(resumable && steps[index]) {
      const actedOnTarget=active && active.contains(target);
      resumeSelector=(actedOnTarget && steps[index+1] ? steps[index+1] : steps[index]).selector;
      if(launchLabel)launchLabel.textContent='案内を再開';
    }
    close(false,true);
  }
  const visible=el=>el && el.isConnected && el.getClientRects().length && getComputedStyle(el).visibility!=='hidden' && !el.closest('[hidden], [inert]');
  const find=selector=>Array.from(document.querySelectorAll(selector)).find(visible);
  if(find('.public-demo-notice')) { root.hidden=true; return; }
  function remember(){try{storage.setItem(name,'1');}catch(_){}}
  function clearTarget(){if(active) active.classList.remove('first-guide-target'); active=null;}
  function close(restore=true, keepResume=false){if(!keepResume)clearResume();clearTarget();panel.hidden=true;remember();if(restore && previous && previous.isConnected) previous.focus({preventScroll:true});}
  function position(){
    if(panel.hidden || !active) return;
    if(!visible(active)){close(false);return;}
    const visual=window.visualViewport;
    const viewport={left:visual?visual.offsetLeft:0,top:visual?visual.offsetTop:0,width:visual?visual.width:innerWidth,height:visual?visual.height:innerHeight};
    // DOMRect is visual geometry; fixed style coordinates remain unzoomed.
    // Convert once, preserving target/scroll behavior under CSS layout zoom.
    const before=panel.getBoundingClientRect();
    const scale=panel.offsetWidth>0 && before.width>0 ? before.width/panel.offsetWidth : 1;
    panel.style.maxHeight=Math.max(80,viewport.height-24)/scale+'px';
    panel.style.width=Math.min(330,viewport.width-24)/scale+'px';
    const bounds=panel.getBoundingClientRect();
    const p=coachmarkPlacement(active.getBoundingClientRect(),viewport,bounds.width,bounds.height);
    panel.style.top=p.top/scale+'px';panel.style.left=p.left/scale+'px';panel.dataset.side=p.side;
    panel.style.setProperty('--guide-arrow-x',p.arrow/scale+'px');
  }
  function show(){
    clearTarget();
    while(index<steps.length && !visible(steps[index].target)) index++;
    if(index>=steps.length){close();return;}
    const s=steps[index];active=s.target;active.classList.add('first-guide-target');
    title.textContent=s.title;text.textContent=s.text;count.textContent=(index+1)+' / '+steps.length;
    if(picture) picture.hidden=s.selector!=='.inspection-item-detail';
    if(aiPicture) aiPicture.hidden=s.selector!=='.ka7-proposals .ka-reference-detail-button';
    next.textContent=index===steps.length-1?'終了':'次へ';panel.hidden=false;
    const visual=window.visualViewport;
    const viewport={left:visual?visual.offsetLeft:0,top:visual?visual.offsetTop:0,width:visual?visual.width:innerWidth,height:visual?visual.height:innerHeight};
    const options=revealOptions(active.getBoundingClientRect(),viewport,window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    if(options) active.scrollIntoView(options);
    position();
  }
  function open(manual){
    if(document.querySelector('dialog[open], .modal-bg.is-open, .ka-reference-drawer:not([hidden])')) return;
    if(root.dataset.page==='vehicle_karte_analysis' && window.location.hash.startsWith('#proposal=')) return;
    if(find('.public-demo-notice')) return; // Never restore/interfere with initial role selection.
    revealRecord(root.dataset.page,manual,document.getElementById('vehicle-inspection-record'));
    steps=candidates(root.dataset.page,find,root.dataset.mode);if(!steps.length)return;
    previous=document.activeElement;
    const resumeIndex=manual && resumeSelector ? steps.findIndex(step=>step.selector===resumeSelector) : -1;
    index=resumeIndex>=0?resumeIndex:0;clearResume();show();remember();
    if(manual) root.querySelector('[data-guide-close]').focus({preventScroll:true});
  }
  launch.addEventListener('click',()=>open(true));
  root.querySelector('[data-guide-close]').addEventListener('click',()=>close(true));
  next.addEventListener('click',()=>{index++;show();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden){e.preventDefault();close();}});
  // If the user operates the real UI, get out of the way. Never trigger that UI ourselves.
  document.addEventListener('click',e=>{if(!panel.hidden&&!root.contains(e.target)) {if(resumable)pauseForOperation(e.target);else close(false);}},true);
  new MutationObserver(()=>{if(!panel.hidden && active && !visible(active)) close(false);}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class']});
  window.addEventListener('resize',position);window.addEventListener('scroll',position,{passive:true});
  if(window.visualViewport){window.visualViewport.addEventListener('resize',position);window.visualViewport.addEventListener('scroll',position,{passive:true});}
  function startInitialGuide(){
    if(initial.available&&!initial.seen && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) open(false);
  }
  // Inspection layout marks responsive columns on DOMContentLoaded. Select targets
  // after those handlers, rather than opening on a cell that is about to be hidden.
  if(resumable){
    const afterLayout=()=>requestAnimationFrame(startInitialGuide);
    if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',afterLayout,{once:true});
    else afterLayout();
  }else startInitialGuide();
})();
