const {piRequest}=require('../../lib/pi-service');
const {issue,cookie}=require('../../lib/hosted-session');
const { config, mac, safeEqual, html, cookies, stateCookie, exchangeCode } = require('../../lib/instagram-oauth');

module.exports = async function callback(req, res) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).send('Method not allowed');
  }
  let cfg;
  try { cfg = config(); }
  catch (error) { return html(res, 503, `<h1>Setup required</h1><p>${error.message}</p>`); }

  const query = new URL(req.url, 'https://vercel.invalid').searchParams;
  const saved = cookies(req).ig_oauth_state || '';
  res.setHeader('Set-Cookie', stateCookie('', 0));
  const dot = saved.lastIndexOf('.');
  const savedState = dot > 0 ? saved.slice(0, dot) : '';
  const savedMac = dot > 0 ? saved.slice(dot + 1) : '';
  const state = query.get('state') || '';
  if (!state || !savedState || !safeEqual(state, savedState) || !safeEqual(savedMac, mac(savedState, cfg.stateSecret))) {
    return html(res, 400, '<h1>Login expired</h1><p>The security check failed or timed out. Return to the connection page and try again.</p>');
  }
  if (query.has('error')) return html(res, 400, '<h1>Instagram connection was cancelled</h1><p>No account token was issued to this page.</p>');
  const code = query.get('code');
  if (!code) return html(res, 400, '<h1>Instagram did not return an authorization code</h1><p>Check the Business Login configuration and try again.</p>');

  try {
    const result = await exchangeCode(code, cfg);
    const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
    const savedAccount=await piRequest('/host/connect',{access_token:result.accessToken,app_id:cfg.appId,account_id:result.accountId,expires_at:result.expiresIn?Math.floor(Date.now()/1000)+result.expiresIn:0});
    if(!savedAccount.stored||savedAccount.account_id!==result.accountId)throw Error('Account was not saved.');
    res.setHeader('Set-Cookie',[stateCookie('',0),cookie(issue(result.accountId,cfg.stateSecret))]);
    const username=escape(result.username);
    return html(res,200,`<h1>Connected as @${username}</h1><p>Your connection is saved in encrypted storage on the Raspberry Pi. Your access token stays on the server.</p><p>New account workspaces start paused. Review your campaigns before activating them.</p><p>Open your private Pi dashboard through an SSH tunnel to manage this account.</p>`);
  } catch (error) {
    return html(res, 400, `<h1>Could not finish Instagram login</h1><p>The connection could not be saved on the Pi. No token will be displayed. Please try again.</p><p>Check the exact redirect URL, app review/tester access, and granted permissions, then try again.</p>`);
  }
};
