const { chromium }=require('playwright'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({headless:true});const rows=[];try{
for(const width of [320,390,1440])for(const name of fs.readdirSync('out').filter(n=>n.endsWith('.html'))){
 const p=await b.newPage({viewport:{width,height:900}});await p.route('**/*',r=>r.abort());
 await p.setContent('<html lang="ja"><meta name="viewport" content="width=device-width,initial-scale=1"><body><main class="driving-page driving-insights">'+fs.readFileSync(path.join('out',name),'utf8')+'</main></body></html>');
 for(const css of ['static/css/style.css','static/css/driving_reports.css'])if(fs.existsSync(css))await p.addStyleTag({content:fs.readFileSync(css,'utf8')});
 assert.equal(await p.getByText('根拠・比較条件を見る',{exact:false}).count(),0);
 assert.equal(await p.locator('.driving-finding').count(),3);assert.equal(await p.locator('.driving-finding details').count(),0);
 assert(await p.locator('[data-analysis-destination]').count()>=3);
 for(const a of await p.locator('[data-analysis-destination]').all()){assert(await a.isVisible());assert((await a.getAttribute('href')).startsWith('/'));}
 const geometry=await p.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(geometry.scroll<=width+1,JSON.stringify(geometry));
 if(name==='cards-0-0-0.html'||name==='cards-1-1-1.html')await p.screenshot({path:`out/${name}-${width}.png`,fullPage:true});rows.push({width,name,cards:3,linksVisible:true,noDisclosure:true,...geometry});await p.close();
}fs.writeFileSync('out/browser.json',JSON.stringify(rows,null,2));}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
