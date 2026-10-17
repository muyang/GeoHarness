const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(require('node:path').join(__dirname,'../src/geo_harness/ui/theme.js'),'utf8');
function theme(query='',stored){const dom=new JSDOM('<button id="theme-toggle"></button>',{url:'http://localhost:8810/'+query,runScripts:'outside-only'});if(stored)dom.window.localStorage.setItem('geonexus.console8793.theme.v1',stored);dom.window.eval(source);return dom;}
test('theme toggle persists, restores and updates accessible control',()=>{const dom=theme('', 'light'),w=dom.window,b=w.document.getElementById('theme-toggle');assert.equal(w.document.documentElement.dataset.theme,'light');b.click();assert.equal(w.document.documentElement.dataset.theme,'dark');assert.equal(w.document.body.classList.contains('wb-dark'),true);assert.equal(w.localStorage.getItem('geonexus.console8793.theme.v1'),'dark');assert.equal(b.getAttribute('aria-label'),'切换浅色模式');w.close();});
test('embedded explicit theme overrides client preference and ignores storage events',()=>{const dom=theme('?theme=light','dark'),w=dom.window;w.dispatchEvent(new w.StorageEvent('storage',{key:'geonexus.console8793.theme.v1',newValue:'dark'}));assert.equal(w.document.documentElement.dataset.theme,'light');assert.equal(w.localStorage.getItem('geonexus.console8793.theme.v1'),'dark');w.close();});
test('standalone views synchronize theme changes from another tab',()=>{const dom=theme(),w=dom.window;w.dispatchEvent(new w.StorageEvent('storage',{key:'geonexus.console8793.theme.v1',newValue:'light'}));assert.equal(w.document.documentElement.dataset.theme,'light');assert.equal(w.document.body.classList.contains('wb-dark'),false);w.close();});
