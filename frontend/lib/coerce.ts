// lib/coerce.ts
// Coercion defensif untuk JSON dari backend.
//
// Kenapa ada: frontend meng-cast JSON apa adanya (`as RepoHealth`) lalu memakai
// field-nya langsung di render. TypeScript happily percaya cast itu, jadi satu
// field yang hilang di response = satu halaman mati whole screen.
//
//   health.health_score.toFixed(1)  ->  TypeError: Cannot read properties of
//   undefined (reading 'toFixed')
//
// Fungsi di sini jadi satu-satunya tempat penanganan. Panggil di parse site
// (trust boundary), bukan di setiap JSX.

/** Angka yang selalu finite. String numerik diterima; NaN/Infinity -> fallback. */
export function num(v: unknown, fallback = 0): number {
  if (typeof v === "number") return Number.isFinite(v) ? v : fallback;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }
  return fallback;
}

/** Array yang selalu iterable. Non-array -> array kosong. */
export function arr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

/** String yang selalu punya metode. Non-string -> fallback. */
export function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}
