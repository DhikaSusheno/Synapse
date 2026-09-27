import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Tanpa ini Next menebak workspace root dari file lockfile terdekat, dan
  // di mesin ini ketemu package-lock.json di direktori home - satu level di
  // atas repo. Akibatnya output file tracing memindai seluruh home directory.
  // Akar workspace yang benar adalah root repo (sibling dari backend/).
  outputFileTracingRoot: path.join(here, ".."),

  // Token API disuntikkan oleh route handler /backend/[...path], bukan di sini.
  // Next.js tidak mengizinkan field 'headers' pada rewrite, dan menaruh token
  // di NEXT_PUBLIC_* akan membocorkannya ke bundle browser.
};

export default nextConfig;
