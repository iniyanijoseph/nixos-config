'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('discordLogin',{
 start:()=>ipcRenderer.invoke('start-login'),
 copy:()=>ipcRenderer.invoke('copy-login'),
 onStatus:callback=>ipcRenderer.on('status',(_event,status)=>callback(status))
});
