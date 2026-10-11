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
    const safeToken = escape(result.accessToken);
    const username = escape(result.username), accountId = escape(result.accountId);
    const expiry = result.expiresIn ? ` Meta reports an expiry of ${Math.floor(result.expiresIn / 86400)} days.` : '';
    return html(res, 200, `<h1>Connected as @${username}</h1><p>Instagram account ID: <code>${accountId}</code>. Copy this account ID and the access token into your own Reel Follow-up bot’s private Instagram configuration.${expiry}</p><label for="token">Instagram access token</label><textarea id="token" readonly spellcheck="false">${safeToken}</textarea><p><button type="button" onclick="navigator.clipboard.writeText(document.getElementById('token').value).then(()=>document.getElementById('copy-status').textContent='Token copied.').catch(()=>document.getElementById('copy-status').textContent='Select the token above and copy it manually.')">Copy token</button></p><p id="copy-status" role="status" aria-live="polite"></p><small>Keep the token private. It is displayed only in this response and is not added to a URL or saved by this Vercel function.</small><p><a href="/">Connect another account</a></p>`);
  } catch (error) {
    return html(res, 400, `<h1>Could not finish Instagram login</h1><p>${error.message.replace(/[<>]/g, '')}</p><p>Check the exact redirect URL, app review/tester access, and granted permissions, then try again.</p>`);
  }
};
