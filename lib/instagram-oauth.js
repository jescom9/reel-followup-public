const crypto = require('node:crypto');

const SCOPES = [
  'instagram_business_basic',
  'instagram_business_manage_comments',
  'instagram_business_manage_messages',
];

function config() {
  const required = ['IG_APP_ID', 'IG_APP_SECRET', 'IG_REDIRECT_URI', 'LOGIN_STATE_SECRET'];
  const missing = required.filter((key) => !process.env[key]);
  if (missing.length) throw new Error('The Vercel project is missing required environment settings.');
  const redirect = new URL(process.env.IG_REDIRECT_URI);
  if (redirect.protocol !== 'https:' || redirect.pathname !== '/api/instagram/callback' || redirect.search || redirect.hash) {
    throw new Error('IG_REDIRECT_URI must be the exact HTTPS callback URL ending in /api/instagram/callback.');
  }
  return {
    appId: process.env.IG_APP_ID,
    appSecret: process.env.IG_APP_SECRET,
    redirectUri: redirect.toString(),
    stateSecret: process.env.LOGIN_STATE_SECRET,
  };
}

function mac(value, secret) {
  return crypto.createHmac('sha256', secret).update(value).digest('base64url');
}

function safeEqual(a, b) {
  const left = Buffer.from(a || '');
  const right = Buffer.from(b || '');
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function headers(res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, private');
  res.setHeader('Pragma', 'no-cache');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
}

function html(res, status, body) {
  headers(res);
  res.statusCode = status;
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.end(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Instagram connection</title><style>body{font:16px/1.55 system-ui,sans-serif;max-width:680px;margin:8vh auto;padding:0 20px;color:#202124}main{border:1px solid #ddd;border-radius:18px;padding:28px}h1{font-size:28px}a,button{background:#27272a;color:white;border:0;border-radius:9px;padding:12px 18px;text-decoration:none;font:inherit;cursor:pointer}textarea{width:100%;height:110px;box-sizing:border-box;padding:12px;font:13px ui-monospace,monospace}small{color:#555}.error{color:#9b1c1c}</style><main>${body}</main></html>`);
}

function cookies(req) {
  return Object.fromEntries((req.headers.cookie || '').split(';').map((part) => {
    const i = part.indexOf('=');
    return i < 0 ? ['', ''] : [part.slice(0, i).trim(), decodeURIComponent(part.slice(i + 1).trim())];
  }).filter(([key]) => key));
}

function stateCookie(value, maxAge) {
  return `ig_oauth_state=${encodeURIComponent(value)}; HttpOnly; Secure; SameSite=Lax; Path=/api/instagram; Max-Age=${maxAge}`;
}

async function exchangeCode(code, cfg) {
  const form = new URLSearchParams({
    client_id: cfg.appId,
    client_secret: cfg.appSecret,
    grant_type: 'authorization_code',
    redirect_uri: cfg.redirectUri,
    code,
  });
  const shortResponse = await fetch('https://api.instagram.com/oauth/access_token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
    signal: AbortSignal.timeout(15000),
  });
  const shortData = await shortResponse.json().catch(() => ({}));
  if (!shortResponse.ok || !shortData.access_token) throw new Error('Instagram did not return an access token. Check the app settings and redirect URL.');

  const longUrl = new URL('https://graph.instagram.com/access_token');
  longUrl.search = new URLSearchParams({
    grant_type: 'ig_exchange_token',
    client_secret: cfg.appSecret,
    access_token: shortData.access_token,
  });
  const longResponse = await fetch(longUrl, { signal: AbortSignal.timeout(15000) });
  const longData = await longResponse.json().catch(() => ({}));
  if (!longResponse.ok || !longData.access_token) throw new Error('Instagram could not exchange the temporary token. Check the app secret and token permissions.');

  const meUrl = new URL('https://graph.instagram.com/v22.0/me');
  meUrl.search = new URLSearchParams({ fields: 'user_id,username', access_token: longData.access_token });
  const meResponse = await fetch(meUrl, { signal: AbortSignal.timeout(15000) });
  const me = await meResponse.json().catch(() => ({}));
  if (!meResponse.ok || !me.user_id || !me.username) throw new Error('Instagram token was created, but the account profile could not be verified.');
  return { accessToken: longData.access_token, expiresIn: Number(longData.expires_in || 0), username: me.username, accountId: String(me.user_id) };
}

module.exports = { SCOPES, config, mac, safeEqual, html, cookies, stateCookie, exchangeCode };
