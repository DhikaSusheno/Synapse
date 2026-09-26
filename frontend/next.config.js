/** @type {import('next').NextConfig} */
const nextConfig = {
  // Izinkan koneksi ke backend lokal saat development
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
