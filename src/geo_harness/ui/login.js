'use strict';
const field = id => document.getElementById(id);
let csrf;
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
}
field('login-form').addEventListener('submit', async event => {
  event.preventDefault(); field('submit').disabled = true;field('status').textContent = '正在验证 Platform 账号…';
  try {
    if (!csrf) await ready();
    const result = await request('account/login', {username:field('username').value.trim(),password:field('password').value,
      import_local_model:field('import-model').checked});
    location.assign(result.workspace_url);
  } catch (error) { field('status').textContent = error.message; }
  finally { field('password').value = '';field('submit').disabled = false; }
});
ready().catch(error => {field('status').textContent = error.message;});
