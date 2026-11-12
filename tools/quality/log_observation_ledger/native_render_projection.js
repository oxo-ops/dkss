'use strict';
// Native connector-runtime projection. No network, persistence or notification.
// Only the caller may invoke its existing authorized list_logs capability.
const FIELDS = {
 UPLOAD_DELETE_FAILED:{backend:['s3','local'],error_type:['ClientError','OSError']},
 EMAIL_DELIVERY_FAILED:{purpose:['notification','email_change','unknown'],stage:['connect','starttls','authenticate','send','close','unknown'],error_type:['authentication','recipient_refused','sender_refused','data_rejected','tls','connection','smtp','unexpected']},
 WEB_PUSH_SEND_FAILED:{error_type:['provider','unexpected']},
 DOCUMENT_IMPORT_FAILED:{mode:['form','progress','unknown'],stage:['extract','process','persist','unknown'],error_type:['input','runtime','database','unexpected']},
 INVOICE_REVIEW_FAILED:{action:['already_recorded','initial_cost','additional_cost','correction','parts_review','unknown'],error_type:['integrity','operational','data','statement','database','unexpected']}
};
// SHA-256 of ASCII routing/provider identifiers only, not raw log messages.
function sha256(s) {
 if(typeof s!=='string'||/[^\x00-\x7f]/.test(s)) throw Error('INVALID_ID');
 const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
 let H=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
 const a=Array.from(s,c=>c.charCodeAt(0)), bits=a.length*8; a.push(128); while(a.length%64!==56)a.push(0); a.push(0,0,0,0,(bits>>>24)&255,(bits>>>16)&255,(bits>>>8)&255,bits&255);
 const r=(v,n)=>(v>>>n)|(v<<(32-n));
 for(let i=0;i<a.length;i+=64){const w=[];for(let j=0;j<16;j++)w[j]=(a[i+4*j]<<24)|(a[i+4*j+1]<<16)|(a[i+4*j+2]<<8)|a[i+4*j+3];for(let j=16;j<64;j++){let x=w[j-15],y=w[j-2];w[j]=(w[j-16]+(r(x,7)^r(x,18)^(x>>>3))+w[j-7]+(r(y,17)^r(y,19)^(y>>>10)))|0;}
 let [b,c,d,e,f,g,h,k]=H;for(let j=0;j<64;j++){let t=(k+(r(f,6)^r(f,11)^r(f,25))+((f&g)^(~f&h))+K[j]+w[j])|0,u=((r(b,2)^r(b,13)^r(b,22))+((b&c)^(b&d)^(c&d)))|0;k=h;h=g;g=f;f=(e+t)|0;e=d;d=c;c=b;b=(t+u)|0;}H=H.map((v,j)=>(v+[b,c,d,e,f,g,h,k][j])|0);}
 return H.map(v=>(v>>>0).toString(16).padStart(8,'0')).join('');
}
function validTime(value) {
 if(typeof value!=='string')return false;
 const m=/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.\d{1,9})?(Z|[+-](\d\d):(\d\d))$/.exec(value);
 if(!m)return false;
 const [y,mo,d,h,mi,se]=m.slice(1,7).map(Number);
 const leap=y%4===0&&(y%100!==0||y%400===0),days=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31];
 return y>=1&&mo>=1&&mo<=12&&d>=1&&d<=days[mo-1]&&h<24&&mi<60&&se<60&&(m[7]==='Z'||(Number(m[8])<24&&Number(m[9])<60));
}
function project(result, resource) {
 const bad=()=>{throw Error('INVALID_RENDER_REPLY');};
 if(!/^srv-[a-z0-9]{8,64}$/.test(resource)||!result||result.isError!==false)bad();
 let page=result.structuredContent;
 if(page==null){if(!Array.isArray(result.content)||result.content.length!==1||result.content[0].type!=='text'||typeof result.content[0].text!=='string'||result.content[0].text.length>1048576)bad();try{page=JSON.parse(result.content[0].text);}catch{bad();}}
 if(!page||typeof page.hasMore!=='boolean'||!Array.isArray(page.logs)||page.logs.length>1000||JSON.stringify(page).length>1048576)bad();
 const records=[], counts={unrelated:0,rejected:0}, seen=new Set();
 for(const row of page.logs){if(!row||!Array.isArray(row.labels)||typeof row.message!=='string'||row.message.length>65536){counts.rejected++;continue;}
 const labels=Object.create(null);let valid=true;for(const x of row.labels){if(!x||typeof x.name!=='string'||typeof x.value!=='string'||Object.hasOwn(labels,x.name)){valid=false;break;}labels[x.name]=x.value;}
 if(!valid||labels.resource!==resource||labels.type!=='app'){counts.rejected++;continue;}
 const tokens=[...row.message.matchAll(/(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]*_FAILED(?![A-Za-z0-9_])/g)];
 if(!tokens.length){counts.unrelated++;continue;}
 if(tokens.length!==1||!Object.hasOwn(FIELDS,tokens[0][0])||typeof row.id!=='string'||! /^[A-Za-z0-9_.:-]{1,128}$/.test(row.id)||!validTime(row.timestamp)){counts.rejected++;continue;}
 const event=tokens[0][0],tail=row.message.slice(tokens[0].index+event.length),details={};let review=/[\x00-\x1f\x7f]/.test(tail);
 for(const [key,allow]of Object.entries(FIELDS[event])){const vals=[...tail.matchAll(new RegExp('(?<!\\S)'+key+'=([^\\s]+)','g'))];details[key]=vals.length===1&&allow.includes(vals[0][1])&&!/[\x00-\x1f\x7f]/.test(tail)?vals[0][1]:'unverified';if(details[key]==='unverified')review=true;}
 const record={receipt_id:sha256(resource+'\0'+row.id),event,observed_at:row.timestamp,details,requires_review:review};const key=JSON.stringify(record);if(!seen.has(key)){records.push(record);seen.add(key);}}
 return {format:'q09-native-projection-candidate-v1',records,counts,page_has_more:page.hasMore,coverage_status:'unverified_single_page',read_checkpoint:null,scheduled:false,sent:false};
}
if(typeof module!=='undefined')module.exports={sha256,project,validTime};
