'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {isAccountRequest,userToken}=require('./discord-login-policy.cjs');
test('only successful own-account requests may supply a session token',()=>{
 assert.equal(isAccountRequest('https://discord.com/api/v10/users/@me'),true);
 for(const url of ['https://discord.com.evil.example/api/v10/users/@me','http://discord.com/api/v10/users/@me','https://discord.com/api/v10/users/@me/guilds','https://discord.com/api/v10/users/another','not a url'])assert.equal(isAccountRequest(url),false);
});
test('token capture rejects bot credentials and malformed headers',()=>{
 const token='a'.repeat(60);assert.equal(userToken({Authorization:token}),token);
 assert.equal(userToken({authorization:token}),token);
 assert.equal(userToken({Authorization:'Bot '+token}),null);
 assert.equal(userToken({Authorization:'Bearer '+token}),null);
 assert.equal(userToken({Authorization:'short'}),null);
 assert.equal(userToken({}),null);
});
