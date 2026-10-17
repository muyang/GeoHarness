'use strict';
const field = id => document.getElementById(id);
let csrf;
const THEME_KEY='geonexus.console8793.theme.v1';
function theme(value){document.documentElement.dataset.theme=value==='light'?'light':'dark';localStorage.setItem(THEME_KEY,document.documentElement.dataset.theme);field('theme-toggle').textContent=value==='light'?'☾':'☼';field('theme-toggle').setAttribute('aria-label',value==='light'?'切换深色模式':'切换浅色模式');}
theme(new URLSearchParams(location.search).get('theme')||localStorage.getItem(THEME_KEY)||'dark');
field('theme-toggle').onclick=()=>theme(document.documentElement.dataset.theme==='dark'?'light':'dark');
function lock(busy){field('submit').disabled=busy;document.querySelectorAll('[data-demo-account]').forEach(b=>b.disabled=busy);}
async function demoLogin(profile){lock(true);field('status').textContent='正在验证 '+profile.label+'…';try{const result=await request('account/demo-login',{account:profile.id});location.assign(result.workspace_url)}catch(error){field('status').textContent=error.message}finally{field('password').value='';lock(false)}}

async function request(path, body) {
  const response = await fetch('/api/' + path, {method: body ? 'POST' : 'GET',
    headers: body ? {'Content-Type':'application/json', 'X-Geo-CSRF':csrf} : {},
    body: body ? JSON.stringify(body) : undefined});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '登录未通过，请检查统一服务。');
  return value;
}
async function ready() {
  csrf = (await request('session')).csrf;
  const config = await request('account/status');
  field('platform-url').textContent = config.platform_url;
  field('open-platform').href = config.platform_url;
  try{const profiles=await request('account/demo-accounts');field('demo-accounts').hidden=!profiles.enabled;field('demo-buttons').replaceChildren(...(profiles.accounts||[]).map(profile=>{const button=document.createElement('button'),label=document.createElement('strong'),description=document.createElement('small');button.type='button';button.dataset.demoAccount=profile.id;label.textContent=profile.label;description.textContent=profile.description;button.append(label,description);button.onclick=()=>demoLogin(profile);return button;}));}catch{field('demo-accounts').hidden=true;}

}
field('login-form').addEventListener('submit', async event => {
  event.preventDefault(); lock(true);field('status').textContent = '正在验证 Platform 账号…';
  try {
    if (!csrf) await ready();
    const result = await request('account/login', {username:field('username').value.trim(),password:field('password').value,
      import_local_model:field('import-model').checked});
    location.assign(result.workspace_url);
  } catch (error) { field('status').textContent = error.message; }
  finally { field('password').value = '';lock(false); }
});
ready().catch(error => {field('status').textContent = error.message;});
