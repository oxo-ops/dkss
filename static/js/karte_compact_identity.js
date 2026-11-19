/* Preserve original authorised nodes and handlers; only compact the mobile presentation. */
(()=>{
 const header=document.querySelector('.vehicle-karte-header.karte-header-compact');
 if(!header||typeof HTMLDialogElement==='undefined')return;
 const attrs=header.querySelector('.karte-header-attributes'),summary=header.querySelector('.vehicle-karte-summary'),row=header.querySelector('.vehicle-karte-number-row');
 if(!attrs||!summary||!row)return;
 const mq=matchMedia('(max-width:767px)'),moves=[];
 const button=document.createElement('button');button.type='button';button.className='karte-identity-open';button.hidden=true;button.setAttribute('aria-label','車両情報と点検予定を開く');button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','karte-identity-dialog');button.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>';row.append(button);
 const dialog=document.createElement('dialog');dialog.id='karte-identity-dialog';dialog.className='karte-identity-dialog';dialog.setAttribute('aria-labelledby','karte-identity-title');
 const heading=document.createElement('div');heading.className='karte-identity-dialog-heading';const title=document.createElement('h2');title.id='karte-identity-title';title.textContent='車両情報';const close=document.createElement('button');close.type='button';close.className='karte-identity-close';close.textContent='×';close.setAttribute('aria-label','車両情報を閉じる');heading.append(title,close);dialog.append(heading);document.body.append(dialog);
 const alerts=document.createElement('div');alerts.className='karte-identity-alerts';header.append(alerts);
 const move=(node,parent)=>{const anchor=document.createComment('karte original location');node.before(anchor);moves.push([node,anchor]);parent.append(node);};
 const dismiss=()=>{if(dialog.open)dialog.close();button.setAttribute('aria-expanded','false');button.focus();};
 button.addEventListener('click',()=>{if(dialog.open)return;dialog.showModal();button.setAttribute('aria-expanded','true');close.focus();});close.addEventListener('click',dismiss);dialog.addEventListener('cancel',e=>{e.preventDefault();dismiss();});
 const sync=()=>{
  if(mq.matches){if(header.classList.contains('karte-identity-condensed'))return;
   // Important existing warning/issue/expiry controls stay visible and keep their handlers.
   header.querySelectorAll('.karte-mileage-warning').forEach(n=>move(n,alerts));
   const defect=header.querySelector('.vehicle-karte-defect-count');if(defect&&Number.parseInt(defect.querySelector('strong')?.textContent||'0',10)>0)move(defect,alerts);
   header.querySelectorAll('.ip-compact-deadline').forEach(n=>{if(n.querySelector('strong')?.textContent.trim().startsWith('期限'))move(n,alerts);});
   move(attrs,dialog);move(summary,dialog);header.classList.add('karte-identity-condensed');button.hidden=false;
  }else{if(dialog.open)dialog.close();button.setAttribute('aria-expanded','false');for(const[n,a]of moves.reverse()){a.replaceWith(n);}moves.length=0;header.classList.remove('karte-identity-condensed');button.hidden=true;}
 };
 dialog.addEventListener('click',e=>{if(e.target.closest('[data-inspection-plan-open]'))dismiss();},true);
 mq.addEventListener('change',sync);sync();
})();
