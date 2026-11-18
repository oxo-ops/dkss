/* Isolated real-template surface comparison. No business POST or external network. */
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);
const theme=fs.readFileSync(process.env.THEME_PATH||path.join(repo,'static/css/shared_actions.css'),'utf8');
const ordinary=theme.match(/(:where\([\s\S]+?\):not\(:where\([\s\S]+?\)\)) \{/)[1];
const state='.status-badge,.comment-cell,.choice-btn,.vehicle-process-step,.inspection-item-detail,.btn-approve,.vehicle-check-complete-primary,.js-vehicle-checklist-reject,[aria-pressed],[aria-selected],[role=tab],[role=option]';
const snapshots=loc=>loc.evaluateAll(es=>es.map(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {text:e.textContent,attrs:[...e.attributes].map(x=>[x.name,x.value]),display:s.display,visibility:s.visibility,opacity:s.opacity,pointer:s.pointerEvents,w:r.width,h:r.height,bg:s.background,color:s.color,disabled:e.disabled}}));
(async()=>{fs.mkdirSync(out,{recursive:true});const b=await chromium.launch({headless:true,...(process.env.CHROMIUM?{executablePath:process.env.CHROMIUM}:{}),args:['--no-sandbox']});let rows=[],posts=0,external=0,websockets=0,current=null,currentCase=null;
try{for(const width of [320,390,768,1316])for(const file of fs.readdirSync(html).filter(x=>x.endsWith('.html'))){
const name=file.slice(0,-5),info=JSON.parse(fs.readFileSync(path.join(html,'routes.json'))).find(x=>x.endpoint===name);assert.equal(info.status,200);
const c=await b.newContext({viewport:{width,height:900}}),page=await c.newPage();current=page;currentCase={endpoint:name,width};await page.routeWebSocket('**/*',ws=>{websockets++;ws.close()});
await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());if(req.method()!=='GET'){posts++;return route.abort()}if(u.origin!=='https://fixture.invalid'){external++;return route.abort()}
if(u.pathname==='/static/css/shared_actions.css')return route.fulfill({contentType:'text/css',body:''});
if(u.pathname===new URL(info.path,'https://fixture.invalid').pathname)return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,file),'utf8')});
if(u.pathname.startsWith('/static/')){const f=path.resolve(repo,'.'+u.pathname);if(f.startsWith(repo+'/static/')&&fs.existsSync(f))return route.fulfill({path:f})}
return route.fulfill({status:404,body:'offline fixture'});});
await page.goto(new URL(info.path,'https://fixture.invalid').href);await page.keyboard.press('Escape');
const controls=page.locator(ordinary),before=await snapshots(controls);
const states=await snapshots(page.locator(state));
await page.addStyleTag({content:theme});
const after=await snapshots(controls);assert.equal(after.length,before.length);
for(let i=0;i<before.length;i++){for(const k of ['text','attrs','display','visibility','opacity','pointer','disabled'])assert.deepEqual(after[i][k],before[i][k],`${name} control${i} ${k}`);for(const k of ['w','h'])assert(Math.abs(after[i][k]-before[i][k])<=1,`${name} control${i} geometry ${k}`)}
const stateAfter=await snapshots(page.locator(state));assert.deepEqual(stateAfter,states,`${name} state/selection unchanged`);
const focus=controls.filter({visible:true}).first();if(await focus.count()){await focus.focus();assert(await focus.evaluate(e=>e.disabled||document.activeElement===e),'focus');}
await page.screenshot({path:path.join(out,`${name}-${width}.png`),fullPage:true});rows.push({endpoint:name,width,controls:before.length,stateControls:states.length});await c.close();}
assert.equal(posts,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({rows,posts,blockedExternal:external,blockedWebsockets:websockets,synthetic:true,live:false,fullSystemAccepted:false},null,2));}catch(e){fs.writeFileSync(path.join(out,'failure-report.json'),JSON.stringify({case:currentCase,completed:rows,posts,external,websockets,error:String(e)},null,2));if(current&&!current.isClosed())await current.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});
