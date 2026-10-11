const crypto = require('node:crypto');
const { SCOPES, config, mac, html, stateCookie } = require('../../lib/instagram-oauth');

module.exports = function login(req, res) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).send('Method not allowed');
  }
  let cfg;
  try { cfg = config(); }
  catch (error) { return html(res, 503, `<h1>Setup required</h1><p>${error.message}</p><p>Add the required environment settings in Vercel, then redeploy.</p>`); }

  const state = crypto.randomBytes(32).toString('base64url');
  const signed = `${state}.${mac(state, cfg.stateSecret)}`;
  const auth = new URL('https://www.instagram.com/oauth/authorize');
  auth.search = new URLSearchParams({
    client_id: cfg.appId,
    redirect_uri: cfg.redirectUri,
    response_type: 'code',
    scope: SCOPES.join(','),
    state,
    enable_fb_login: '0',
    force_authentication: '1',
  });
  res.setHeader('Set-Cookie', stateCookie(signed, 600));
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.statusCode = 302;
  res.setHeader('Location', auth.toString());
  return res.end();
};
