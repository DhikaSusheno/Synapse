// lib/proxyGuard.ts
// Guard bersama untuk SEMUA route proxy di frontend.
//
// Repo ini punya DUA proxy yang menyuntikkan SYNAPSE_API_TOKEN dari sisi
// server:
//   - app/backend/[...path]/route.ts  (proxy utama, kebanyakan endpoint)
//   - app/api/graph/route.ts          (proxy kedua, ke /graph/nodes + /graph/edges)
//
// Guard-nya dulu hanya ada di proxy utama (isu #63) dan proxy /api/graph
// jalan tanpa satupun: tanpa cek Sec-Fetch-Site, dan tanpa penolakan kalau
// token belum disetel sehingga request tetap diteruskan lalu gagal 401
// membingungkan di ujung. Dua file yang sama-sama menyuntik token tidak
// boleh memakai dua tingkat keamanan berbeda — karena itu logikanya dipindah
// ke sini supaya keduanya memakai SATU implementasi dan testnya juga cuma
// satu.

/** Nilai Sec-Fetch-Site yang menandakan request datang dari aplikasi ini sendiri. */
export const SAFE_FETCH_SITES: ReadonlySet<string> = new Set([
  "same-origin",
  "same-site",
  "none",
]);

export type ProxyDenial = {
  status: number;
  error: string;
  hint?: string;
};

/**
 * Tolak request yang jelas berasal dari origin lain atau dari browser
 * foreign. Mengembalikan objek penolakan, atau `null` kalau diperbolehkan.
 *
 * CORS hanya memblokir PEMBACAAN respons, bukan eksekusinya — jadi tanpa
 * guard ini halaman mana pun bisa membuat browser korban memicu POST ke
 * proxy (CSRF nyata, karena proxy-lah yang menyuntikkan kredensial server).
 *
 * @param fetchSite nilai header `sec-fetch-site` (null kalau tidak dikirim)
 * @param origin    nilai header `origin` (null kalau tidak dikirim)
 * @param allowedOrigins daftar origin yang diizinkan; kosong = tidak ada
 *        pembatasan origin selain Sec-Fetch-Site
 */
export function crossSiteDenial(
  fetchSite: string | null,
  origin: string | null,
  allowedOrigins: ReadonlySet<string> = new Set<string>()
): ProxyDenial | null {
  if (fetchSite && !SAFE_FETCH_SITES.has(fetchSite.toLowerCase())) {
    return {
      status: 403,
      error: "Cross-site request ditolak",
      hint: "Proxy hanya melayani request dari aplikasi Synapse itu sendiri",
    };
  }

  if (allowedOrigins.size > 0) {
    // Origin hanya dikirim browser pada request non-GET. Untuk GET, andalkan
    // Sec-Fetch-Site yang sudah dicek di atas.
    if (origin && !allowedOrigins.has(origin)) {
      return { status: 403, error: "Origin tidak diizinkan", hint: `Origin: ${origin}` };
    }
  }

  return null;
}

/**
 * Tolak kalau server tidak punya token sama sekali.
 *
 * Tanpa guard ini proxy meneruskan request apa adanya ke backend tanpa
 * kredensial: yang terjadi hanya 401 membingungkan di ujung, atau — lebih
 * buruk — kalau kebijakan auth backend berubah, endpoint jadi terbuka.
 * Proxy yang menyuntik token harus gagal-cepat sebelum menyentuh jaringan.
 */
export function missingTokenDenial(token: string): ProxyDenial | null {
  if (token) return null;
  return {
    status: 503,
    error: "SYNAPSE_API_TOKEN belum di-set di server",
    hint: "Proxy tidak akan meneruskan request tanpa kredensial",
  };
}

/**
 * Parsing daftar origin dari env (comma-separated) jadi Set.
 * Nilai kosong menghasilkan Set kosong, yang berarti "tanpa pembatasan
 * origin" — perilaku ini disengaja dan sama dengan versi lama.
 */
export function parseAllowedOrigins(raw: string | undefined): Set<string> {
  return new Set(
    (raw ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
  );
}
