'use strict';
(() => {
 const key='geonexus.console8793.theme.v1';
 const explicit=new URLSearchParams(location.search).get('theme');
 const stored=()=>{try{return localStorage.getItem(key)}catch{return null}};
 function apply(value,persist=false){
  const theme=value==='light'?'light':'dark';
  document.documentElement.dataset.theme=theme;
  document.body.classList.toggle('wb-dark',theme==='dark');
  if(persist)try{localStorage.setItem(key,theme)}catch{}
  const button=document.getElementById('theme-toggle');
  if(button){button.textContent=theme==='dark'?'☼':'☾';button.setAttribute('aria-label',theme==='dark'?'切换浅色模式':'切换深色模式');button.title=button.getAttribute('aria-label')}
 }
 apply(explicit||stored()||'dark');
 document.getElementById('theme-toggle')?.addEventListener('click',()=>apply(document.documentElement.dataset.theme==='dark'?'light':'dark',true));
 window.addEventListener('storage',event=>{if(event.key===key&&!explicit)apply(event.newValue)});
})();
