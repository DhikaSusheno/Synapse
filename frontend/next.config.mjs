/** @type {import('next').NextConfig} */
const nextConfig = {
  // Token API disuntikkan oleh route handler /backend/[...path], bukan di sini.
  // Next.js tidak mengizinkan field 'headers' pada rewrite, dan menaruh token
  // di NEXT_PUBLIC_* akan membocorkannya ke bundle browser.
};

export default nextConfig;
