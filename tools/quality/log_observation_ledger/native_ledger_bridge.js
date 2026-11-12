'use strict';
// Candidate only: convert transient connector pages to a pseudonymous transcript.
// Never mix its pseudonymous state with an original-resource ledger.
const {sha256,project,validTime}=require('./native_render_projection');
function bridgePage(result,resource){
 const safe=project(result,resource); // bounded wrapper, markers and schema validation
 let page=result.structuredContent;
 if(page==null)page=JSON.parse(result.content[0].text);
 const alias='srv-'+sha256(resource).slice(0,32);
 const logs=page.logs.map(row=>{
  const one=project({isError:false,structuredContent:{hasMore:false,logs:[row]}},resource);
  if(one.counts.rejected){
   const labels=Object.create(null);let valid=true;
   if(!row||!Array.isArray(row.labels))return {};
   for(const item of row.labels){if(!item||typeof item.name!=='string'||typeof item.value!=='string'||Object.hasOwn(labels,item.name)){valid=false;break;}labels[item.name]=item.value;}
   if(!valid||labels.resource!==resource||labels.type!=='app'||typeof row.id!=='string'||! /^[A-Za-z0-9_.:-]{1,128}$/.test(row.id)||!validTime(row.timestamp)||typeof row.message!=='string'||row.message.length>65536)return {};
   const known=['UPLOAD_DELETE_FAILED','EMAIL_DELIVERY_FAILED','WEB_PUSH_SEND_FAILED','DOCUMENT_IMPORT_FAILED','INVOICE_REVIEW_FAILED'];
   const markers=[...row.message.matchAll(/(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]*_FAILED(?![A-Za-z0-9_])/g)].map(x=>known.includes(x[0])?x[0]:'Q09_UNCLASSIFIED_FAILED');
   const counts=Object.create(null), bounded=markers.filter(v=>{counts[v]=(counts[v]||0)+1;return counts[v]<=2;});
   return{id:sha256(resource+'\0'+row.id),timestamp:row.timestamp,labels:[{name:'resource',value:alias},{name:'type',value:'app'}],message:bounded.join(' ')};
  }
  if(typeof row.id!=='string'||! /^[A-Za-z0-9_.:-]{1,128}$/.test(row.id))return {};
  // The ledger validates the timestamp, including unrelated records.
  const timestamp=typeof row.timestamp==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)$/.test(row.timestamp)?row.timestamp:null;
  let message='';
  if(one.records.length){const r=one.records[0];message=r.event+' '+Object.entries(r.details).map(([k,v])=>k+'='+v).join(' ');}
  return{id:sha256(resource+'\0'+row.id),timestamp,labels:[{name:'resource',value:alias},{name:'type',value:'app'}],message};
 });
 const sanitized={hasMore:safe.page_has_more,logs};
 // Cursor strings may contain private garbage: only timestamp-shaped strings cross.
 for(const k of ['nextStartTime','nextEndTime'])if(typeof page[k]==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)$/.test(page[k]))sanitized[k]=page[k];
 return{resource:alias,page:sanitized};
}
module.exports={bridgePage};
