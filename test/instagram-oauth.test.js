const test = require('node:test');
const assert = require('node:assert/strict');
const { exchangeCode } = require('../lib/instagram-oauth');

test('exchanges an authorized account other than jescojm into a long-lived token with verified identity', async () => {
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (input, init = {}) => {
    const url = new URL(input);
    calls.push({ url, init });

    if (url.hostname === 'api.instagram.com') {
      return Response.json({ access_token: 'short-lived-test-token' });
    }
    if (url.hostname === 'graph.instagram.com' && url.pathname === '/access_token') {
      return Response.json({ access_token: 'long-lived-test-token', expires_in: 5184000 });
    }
    if (url.hostname === 'graph.instagram.com' && url.pathname === '/v22.0/me') {
      return Response.json({ user_id: 'test-account-id', username: 'another_creator' });
    }
    throw new Error(`Unexpected Instagram endpoint: ${url.hostname}${url.pathname}`);
  };

  try {
    const result = await exchangeCode('one-time-test-code', {
      appId: 'instagram-app-id',
      appSecret: 'test-app-secret',
      redirectUri: 'https://example.test/api/instagram/callback',
    });

    assert.equal(calls.length, 3);
    assert.equal(calls[0].url.toString(), 'https://api.instagram.com/oauth/access_token');
    assert.equal(calls[1].url.toString(), 'https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=test-app-secret&access_token=short-lived-test-token');
    assert.equal(result.username, 'another_creator');
    assert.equal(result.accountId, 'test-account-id');
    assert.equal(result.accessToken, 'long-lived-test-token');
    assert.equal(result.expiresIn, 5184000);
  } finally {
    global.fetch = originalFetch;
  }
});
