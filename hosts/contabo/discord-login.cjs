'use strict';
const {app,BrowserWindow,session,ipcMain,clipboard}=require('electron');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {isAccountRequest,userToken}=require('./discord-login-policy.cjs');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'contabo-discord-login-'));
app.setPath('userData',temporary);
let main,login,validatedToken,clipboardCommand,clearTimer;
const candidates=new Map();
function clearClipboard(){if(clipboardCommand&&clipboard.readText()===clipboardCommand)clipboard.clear();clipboardCommand=null;}
function update(message,ready=false){if(main&&!main.isDestroyed())main.webContents.send('status',{message,ready});}
app.whenReady().then(()=>{
 main=new BrowserWindow({width:620,height:510,webPreferences:{preload:path.join(__dirname,'discord-login-preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true}});
 main.loadFile(path.join(__dirname,'discord-login.html'));
 main.webContents.on('will-navigate',event=>event.preventDefault());
 main.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 main.on('closed',()=>app.quit());
 ipcMain.handle('start-login',event=>{
  if(event.sender!==main.webContents)throw new Error('Untrusted login request');
  if(login&&!login.isDestroyed()){login.focus();return;}
  validatedToken=null;candidates.clear();clearClipboard();
  const browserSession=session.fromPartition('contabo-discord-'+crypto.randomUUID(),{cache:false});
  browserSession.webRequest.onBeforeSendHeaders({urls:['https://discord.com/api/*']},(details,callback)=>{
   if(isAccountRequest(details.url)){const token=userToken(details.requestHeaders);if(token)candidates.set(details.id,token);}
   callback({requestHeaders:details.requestHeaders});
  });
  browserSession.webRequest.onCompleted({urls:['https://discord.com/api/*']},details=>{
   const token=candidates.get(details.id);candidates.delete(details.id);
   if(token&&details.statusCode===200&&isAccountRequest(details.url)){
    validatedToken=token;update('Discord sign-in succeeded. Copy the login command, then paste it into your private Discord bridge bot DM.',true);
    main.show();main.focus();
   }
  });
  browserSession.webRequest.onErrorOccurred({urls:['https://discord.com/api/*']},details=>candidates.delete(details.id));
  login=new BrowserWindow({width:1080,height:800,webPreferences:{session:browserSession,nodeIntegration:false,contextIsolation:true,sandbox:true}});
  login.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  login.webContents.on('will-navigate',(event,url)=>{try{const parsed=new URL(url);if(parsed.protocol!=='https:'||parsed.hostname!=='discord.com')event.preventDefault();}catch{event.preventDefault();}});
  login.loadURL('https://discord.com/login');
  update('Sign in in the Discord window. Complete the CAPTCHA and any two-factor prompt yourself.');
 });
 ipcMain.handle('copy-login',event=>{
  if(event.sender!==main.webContents||!validatedToken)throw new Error('No authenticated Discord session');
  clearClipboard();clipboardCommand='!discord login-token user '+validatedToken;clipboard.writeText(clipboardCommand);
  if(clearTimer)clearTimeout(clearTimer);clearTimer=setTimeout(clearClipboard,60000);
  update('Copied. Paste into the private DM with @discord-nativebot:iniyanjoseph.com within 60 seconds. Keep this helper open until you have pasted it.',true);
  return true;
 });
});
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',()=>{clearClipboard();validatedToken=null;candidates.clear();if(clearTimer)clearTimeout(clearTimer);});
app.on('will-quit',()=>{try{fs.rmSync(temporary,{recursive:true,force:true});}catch{}});
