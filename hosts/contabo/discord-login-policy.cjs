'use strict';
function isAccountRequest(url) {
 try {const parsed=new URL(url);return parsed.protocol==='https:'&&parsed.hostname==='discord.com'&&/^\/api\/v\d+\/users\/@me$/.test(parsed.pathname);}
 catch{return false;}
}
function userToken(headers) {
 const entry=Object.entries(headers||{}).find(([name])=>name.toLowerCase()==='authorization');
 const value=entry&&entry[1];
 return typeof value==='string'&&/^[A-Za-z0-9._-]{30,500}$/.test(value)?value:null;
}
module.exports={isAccountRequest,userToken};
