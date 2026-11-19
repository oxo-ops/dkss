const assert=require('node:assert/strict');
const {coachmarkMaxHeight,coachmarkPlacement}=require('../static/js/first_use_guide.js');
for(const width of [320,390,501,1440])for(const height of [600,700,844]){
 const v={left:0,top:0,width,height},r={left:60,right:width-80,top:height*.48,bottom:height*.48+50};
 const h=coachmarkMaxHeight(r,v),p=coachmarkPlacement(r,v,Math.min(330,width-24),h);
 assert(p.top+h<=r.top-11 || p.top>=r.bottom+11,'coachmark covers target');
 assert(p.top>=12 && p.top+h<=height-12,'outside viewport');
}
console.log('12 viewport non-overlap cases passed');
