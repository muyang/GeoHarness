'use strict';
function clientURL(value='http://127.0.0.1:8810/') {
  const url=new URL(value);
  if(url.protocol!=='http:' || !['127.0.0.1','localhost','[::1]'].includes(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname!=='/') throw new Error('GeoHarness desktop requires a local runtime root URL');
  return url.href;
}
function navigationAllowed(target, home) {
  try { const url=new URL(target);return url.origin===new URL(home).origin && !url.username && !url.password; }
  catch { return false; }
}
module.exports={clientURL,navigationAllowed};
