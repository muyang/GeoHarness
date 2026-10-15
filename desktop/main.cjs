'use strict';
const {app,BrowserWindow,Menu,shell,session}=require('electron');
const path=require('node:path');
const {clientURL,navigationAllowed}=require('./policy.cjs');
const home=clientURL(process.env.GEOHARNESS_CLIENT_URL);
let window;
app.enableSandbox();
if(!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance',()=>{if(window){window.restore();window.focus();}});
  app.whenReady().then(()=>{
    // No filesystem/process bridge is exposed to the shared web application.
    const local=session.fromPartition('geoharness-desktop');
    local.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
    local.setPermissionCheckHandler(()=>false);
    window=new BrowserWindow({width:1440,height:940,minWidth:960,minHeight:650,title:'GeoHarness',backgroundColor:'#f3f7f7',
      webPreferences:{session:local,nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
    window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    window.webContents.on('will-navigate',(event,url)=>{if(!navigationAllowed(url,home))event.preventDefault();});
    window.webContents.on('will-redirect',(event,url)=>{if(!navigationAllowed(url,home))event.preventDefault();});
    window.webContents.on('will-attach-webview',event=>event.preventDefault());
    window.webContents.on('did-fail-load',(_event,code,_description,_url,isMainFrame)=>{
      if(isMainFrame && code!==-3)window.loadFile(path.join(__dirname,'offline.html'));
    });
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {label:'GeoHarness',submenu:[{label:'连接工作台',click:()=>window.loadURL(home)},
        {label:'登录 / 切换账号',click:()=>window.loadURL(home+'login')},
        {label:'打开 Platform',click:()=>shell.openExternal('http://127.0.0.1:3301/')},{type:'separator'},{role:'quit'}]},
      {label:'编辑',submenu:[{role:'undo'},{role:'redo'},{type:'separator'},{role:'cut'},{role:'copy'},{role:'paste'},{role:'selectAll'}]},
      {label:'显示',submenu:[{role:'reload'},{role:'resetZoom'},{role:'zoomIn'},{role:'zoomOut'},{role:'togglefullscreen'}]}
    ]));
    window.loadURL(home);
  });
  app.on('window-all-closed',()=>app.quit());
}
