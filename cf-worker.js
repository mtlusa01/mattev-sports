// ============================================
// CLOUDFLARE WORKER — Claude API Proxy
// Deploy: Workers → Create → paste → add ANTHROPIC_API_KEY secret
// ============================================

const ALLOWED_ORIGIN = 'https://mtlusa01.github.io';

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin === ALLOWED_ORIGIN ? origin : '',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const headers = corsHeaders(origin);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405, headers });
    }

    const body = await request.text();
    const resp = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body,
    });

    const data = await resp.text();
    return new Response(data, {
      status: resp.status,
      headers: { ...headers, 'Content-Type': 'application/json' },
    });
  },
};
