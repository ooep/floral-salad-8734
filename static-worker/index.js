/**
 * jr-static — Mini JapanRail 纯静态资源 Worker
 *
 * 职责：仅从 Worker Static Assets 读取静态文件（data/ logos/ seo/img 图标等），
 * 统一补充 CORS 与缓存头。无任何外部请求、无第三方依赖，纯静态零计费（免费档内）。
 *
 * 上线路径：https://jr-static.suki.ing/（与主站 jr.suki.ing 同 zone）
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 仅允许 GET / HEAD
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method Not Allowed', { status: 405 });
    }

    // 可选：/healthz 探活
    if (url.pathname === '/healthz') {
      return new Response('ok', { status: 200 });
    }

    // 纯静态 CDN：禁止爬虫收录（防止重复内容抢占 SEO）
    if (url.pathname === '/robots.txt') {
      return new Response('User-agent: *\nDisallow: /\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'Access-Control-Allow-Origin': '*',
        },
      });
    }

    const response = await env.ASSETS.fetch(request);

    // 缺失文件：保持 404（不落入 SPA fallback，静态资源必须精确命中）
    if (response.status === 404) {
      return new Response('Not Found', { status: 404 });
    }

    // 复制响应并注入跨域 + 缓存头
    const headers = new Headers(response.headers);
    headers.set('Access-Control-Allow-Origin', '*');
    headers.set('Access-Control-Expose-Headers', 'Last-Modified, ETag, Content-Length, Content-Type');
    headers.set('Vary', 'Accept-Encoding');
    if (!headers.has('Cache-Control')) {
      // 数据每周刷新 + 客户端带 If-Modified-Since/ETag 条件重验证，短缓存即可
      headers.set('Cache-Control', 'public, max-age=300');
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
