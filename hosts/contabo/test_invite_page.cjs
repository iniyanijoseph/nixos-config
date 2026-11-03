'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(process.env.CONTABO_INVITE_PAGE||path.join(__dirname,'server-invite.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function page(fetch){
 const nodes={};for(const id of ['signup','status','submit','username','password','confirm','login'])nodes['#'+id]={value:'',hidden:id==='login',disabled:false,textContent:'',addEventListener(type,fn){this[type]=fn;}};
 nodes['#username'].value='friend';nodes['#password'].value=nodes['#confirm'].value='fixture-password-only';
 let scrubbed=false;
 vm.runInNewContext(script,{URLSearchParams,location:{hash:'#token=one-time-fixture',pathname:'/invite/'},history:{replaceState(){scrubbed=true;}},document:{querySelector:id=>nodes[id]},fetch});
 return {nodes,submit:()=>nodes['#signup'].submit({preventDefault(){}}),scrubbed};
}
test('invitation UI completes token and dummy stages, then rejects reuse',async()=>{
 let consumed=false,requests=[];
 function fetch(_url,options){const body=JSON.parse(options.body);requests.push(body);
  if(consumed)return {status:403,ok:false,json:async()=>({error:'Invitation already used'})};
  const stage=body.auth&&body.auth.type;
  if(stage==='m.login.dummy'){consumed=true;return {status:200,ok:true,json:async()=>({user_id:'@friend:iniyanjoseph.com'})};}
  if(stage==='m.login.registration_token')assert.equal(body.auth.token,'one-time-fixture');
  return {status:401,ok:false,json:async()=>({session:'session-one',flows:[{stages:['m.login.registration_token','m.login.dummy']}],completed:stage?['m.login.registration_token']:[]})};
 }
 const first=page(fetch);await first.submit();assert.equal(first.scrubbed,true);assert.equal(first.nodes['#login'].hidden,false);assert.equal(first.nodes['#password'].value,'');assert.equal(requests.length,3);
 assert.equal(requests[1].auth.session,'session-one');assert.equal(requests[2].auth.type,'m.login.dummy');
 const reused=page(fetch);await reused.submit();assert.equal(reused.nodes['#login'].hidden,true);assert.match(reused.nodes['#status'].textContent,/already used/);
});
test('invitation UI refuses a flow that lacks token verification',async()=>{
 const p=page(()=>({status:401,ok:false,json:async()=>({session:'bad',flows:[{stages:['m.login.dummy']}]})}));await p.submit();assert.equal(p.nodes['#login'].hidden,true);assert.match(p.nodes['#status'].textContent,/expected invitation/);
});
test('password confirmation fails before any registration request',async()=>{
 let requests=0;const p=page(()=>{requests++;throw new Error('must not call');});p.nodes['#confirm'].value='different';await p.submit();assert.equal(requests,0);assert.match(p.nodes['#status'].textContent,/do not match/);
});
