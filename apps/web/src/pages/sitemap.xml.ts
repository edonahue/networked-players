import type { APIRoute } from 'astro';

export const prerender = true;

const escapeXml = (value: string) =>
  value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');

const paths = ['/', '/about/', '/demo/'];

export const GET: APIRoute = async ({ site }) => {
  if (!site) return new Response('Site URL is not configured.', { status: 500 });

  const urls = paths
    .map((path) => `<url><loc>${escapeXml(new URL(path, site).toString())}</loc></url>`)
    .join('');

  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`,
    { headers: { 'Content-Type': 'application/xml; charset=utf-8' } },
  );
};
