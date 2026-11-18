const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
(async()=>{const browser=await chromium.launch({headless:true});const results=[];const folder=process.argv[2],out=process.argv[3];fs.mkdirSync(out,{recursive:true});
for(const width of [320,390,768,1316])for(const [s,v] of [[0,0],[1,0],[0,1],[5,5],[6,11],[60,60]]){
 const page=await browser.newPage({viewport:{width,height:900}});
 let blocked=0;await page.route('**/*',r=>{blocked++;r.abort()});
 await page.setContent(fs.readFileSync(path.join(folder,s+'-'+v+'.html'),'utf8'));
 const panel=page.locator('[data-office-actions]');
 assert.equal(await page.locator('.office-action-link').count(),s+v);
 if(s+v){
 const tabs=panel.getByRole('tab');
 const countKinds=Number(s>0)+Number(v>0);
 assert.equal(await panel.locator('[role=tablist]').isVisible(),countKinds>1);
 for(const [kind,n] of [['安全',s],['車両',v]]){
  if(!n)continue;
  if(countKinds>1)await tabs.filter({hasText:kind}).click();
  const expected=Array.from({length:n},(_,i)=>'/fixture/'+(kind==='安全'?'safety':'vehicle')+'/'+i);
  const seen=[];
  for(let start=0;start<n;start+=5){
   const links=panel.locator('li:not([hidden]) .office-action-link');
   assert.equal(await links.count(),Math.min(5,n-start));
   seen.push(...await links.evaluateAll(es=>es.map(e=>e.getAttribute('href'))));
   const overflow=await panel.evaluate(e=>e.scrollWidth>e.clientWidth+1);
   assert(!overflow,'panel overflow');
   const h=await panel.evaluate(e=>e.getBoundingClientRect().height);
   assert(h<650,'unbounded panel '+h);
   if(start+5<n)await panel.getByRole('button',{name:'次の5件',exact:true}).click();
  }
  assert.deepEqual(seen,expected);
  if(n>5){assert(await panel.getByRole('button',{name:'次の5件',exact:true}).isDisabled());await panel.getByRole('button',{name:'前の5件',exact:true}).click();}
 }
 if(countKinds>1){await tabs.first().click();await tabs.first().press('ArrowRight');assert.equal(await tabs.last().getAttribute('aria-selected'),'true');}
 if(s===6&&v===11)await page.screenshot({path:path.join(out,'actions-'+width+'.png'),fullPage:true});
 }else{assert(await panel.getByText('現在、確認できる対応事項はありません。').isVisible());}
 assert.equal(blocked,0,'external request');
 results.push({width,safety:s,vehicle:v,passed:true});await page.close();
}
await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exit(1)});

