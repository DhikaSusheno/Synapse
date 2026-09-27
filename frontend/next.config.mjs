/** @type {import('next').NextConfig} */
const BACKEND_ORIGIN = process.env.BACKEND_URL ?? "http://localhost:8000";
const API_TOKEN = process.env.SYNAPSE_API_TOKEN ?? "";

const nextConfig = {
  async rewrites() {
    return [
      {
        // BUG-11: proxy same-origin ini menyuntikkan header token di sisi
        // SERVER Next.js, jadi token tidak pernah masuk bundle browser dan
        // tidak bisa dibaca situs lain. Browser juga jadi same-origin sehingga
        // CORS tidak relevan untuk jalur ini.
        source: "/backend/:path*",
        destination: `${BACKEND_ORIGIN}/:path*`,
        headers: API_TOKEN ? { "X-Synapse-Token": API_TOKEN } : undefined,
      },
    ];
  },
};

export default nextConfig;
