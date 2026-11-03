'use strict';
document.querySelector('#start').addEventListener('click',()=>window.discordLogin.start());
document.querySelector('#copy').addEventListener('click',()=>window.discordLogin.copy());
window.discordLogin.onStatus(status=>{document.querySelector('#status').textContent=status.message;document.querySelector('#copy').disabled=!status.ready;});
