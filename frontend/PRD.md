# PRD — Synapse Frontend: UI/UX Wrap + Landing Page

> Source of truth untuk scope frontend **hackathon demo**.
> Konteks produk: [`../SYNAPSE.md`](../SYNAPSE.md). Spec visual: [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md).
> Prompt untuk lanjut dikerjakan AI agent: [`MASTER_PROMPT.md`](./MASTER_PROMPT.md).

Owner FE-1: [@nabilfauzandafa](https://github.com/nabilfauzandafa) — Graph + halaman core
Owner FE-2: [@ShannWasHere](https://github.com/ShannWasHere) — Approvals + Operations + GuardianPanel

---

## 1. Why this document exists

PRD sebelumnya (38 baris) hanya berisi deliverable FE-1/FE-2 dan sudah tidak
mencerminkan pekerjaan yang sedang berjalan. Yang belum pernah ada di dokumen
mana pun:

1. **Halaman Explainer / landing** untuk juri dan calon pengguna. Tidak ada sama
   sekali di repo — juri hanya melihat dashboard.
2. **Daftar bug UI** yang ditemukan lewat inspeksi visual. Semua lolos
   `lint`, `typecheck`, 36 test, dan `build` — tidak ada satu pun yang
   terdeteksi toolchain, karena semuanya cacat *runtime* dan *visual*.
3. **Aturan kejujuran data**: mock data tidak boleh tampil seolah-olah nyata.

---

## 2. Problem

Juri hackathon punya 3 menit.Repo ini confronted them with a 9-page dashboard
sebagai halaman pertama:-layout padat, tanpa penjelasan masalah yang diselesaikan,
tanpa urutan demo. Yang dijawab "apa ini?" bukan "kenapa ini penting?".

Di sisi lain, dashboard punya cacat yang hanya terlihat saat dibuka di browser:
tombol yang tidak melakukan apa-apa, dropdown native yang APPEAR terang di atas
UI gelap, dan banner yang menutupi seluruh top bar.

---

## 3. Goal

Satu kalimat: **juri bisa memahami apa yang Synapse selesaikan, melihat bukti
running, dan menjalankan demo sendiri — tanpa perlu explanations dari pemateri.**

Sub-goal yang bisa diukur:

| # | Goal | Ukuran |
|---|---|---|
| G1 | Halaman pertama menjelaskan produk tanpa bantuan pemateri | `/landing` reachable, semua section terisi konten faktual |
| G2 | Tidak ada kontrol mati di shell utama | 0 tombol tanpa handler, 0 affordance yang tidak terhubung |
| G3 | Status koneksi konsisten di seluruh UI | 1 sumber kebenaran, tidak bisa tampil "Live" dan "Offline" bersamaan |
| G4 | Data mock tidak pernah menyamar jadi data nyata | Badge `DEMO DATA` terlihat di mode mock |
| G5 | Biaya landing page hampir nol | Statis, tanpa dependency baru, < 10 kB route |

## 4. Non-Goals

- **Bukan** product page untuk pemasaran. Tidak ada pricing, tidak ada signup,
  tidak ada analytics tracking. Ini halaman untuk juri, bukan untuk konversi.
- **Bukan** tempatImplementasi aturan bisnis. Rollback, conflict detection, dan
  blast radius tetap milik backend; frontend hanya merender state.
- **Bukan** CMD palette. `⌘K` global search dihapus, bukan diimplementasikan.
  Search milik halaman Code Graph (dan sekarang benar-benar bekerja).
- **Bukan** redesign visual total. Token warna, radius, dan border tetap seperti
  `DESIGN_SYSTEM.md`. Yang diperbaiki adalah cacatnya, bukan identitasnya.
- **Bukan** dependency baru. Nol paket baru. Semua perbaikan memakai platform dan
  kode yang sudah ada.

---

## 5. Deliverables

| # | Deliverable | Status | File |
|---|---|---|---|
| D1 | Shell layout tidak menutupi top bar | ✅ | `app/layout.tsx`, `components/shared/BackendStatusBanner.tsx` |
| D2 | Satu sumber kebenaran status backend | ✅ | `hooks/useBackendStatus.ts` |
| D3 | Dropdown & input native tampil gelap | ✅ | `app/globals.css` (`color-scheme: dark`) |
| D4 | Search + filter graph benar-benar bekerja | ✅ | `lib/graphFilter.ts`, `components/SynapseGraph.tsx` |
| D5 | Tombol shell yang sebelumnya mati | ✅ | `components/TopNavbar.tsx` |
| D6 | Logo replaced, nav icons konsisten, status jujur | ✅ | `components/LeftNav.tsx` |
| D7 | Settings menyimpan dan bisa di-reset | ✅ | `components/pages/SettingsPage.tsx` |
| D8 | Badge `DEMO DATA` di mode mock | ✅ | `components/shared/BackendStatusBanner.tsx` |
| D9 | Halaman Explainer `/landing` | ✅ | `app/landing/page.tsx` |
| D10 | Test untuk logic filter graph | ✅ 9 test | `lib/graphFilter.test.ts` |
| D11 | Font Inter benar-benar terpakai | ✅ | `app/globals.css`, `app/layout.tsx` |
| D12 | Aksesibilitas dasar untuk input & toggle | ✅ | `components/pages/SettingsPage.tsx`, `app/globals.css` |

---

## 6. Spec — Halaman Explainer (`/landing`)

Route: `/landing`. Server component, tanpa state, tanpa fetch, tanpa `"use client"`.

### 6.1 Struktur

| Section | Isi | Syarat |
|---|---|---|
| Nav | Logo Synapse, 4 anchor section, CTA `Open Live Demo` | Sticky, CTA menuju `/` |
| Hero | Nama hackathon, satu headline, satu paragraf value, 2 CTA, 4 stat faktual | Headline menyebut masalah, bukan fitur |
| Problem | 3 kartu: agent lebih cepat dari review, tidak ada pemahaman bersama, perubahan sulit dibatalkan | Framing masalah, bukan daftar fitur |
| How it works | 4 langkah: Understand → Propose → Guard → Verify | Incluye blast radius + conflict + rollback |
| Properties | 4 kartu: Reversible, Conflict-aware, Fail-closed, Human in the loop | Tidak boleh ada yang tidak diimplementasikan di backend |
| Agents | 3 kartu: Guardian, Cortex, Review | Satu kartu per agent, tanpa tumpang tindih |
| Demo path | 3 langkah bernomor, tiap langkah menyebut halaman tujuan | Jalur yang bisa di demonstrations manual |
| Stack | 8 chip teknologi | Hanya yang benar-benar ada di `package.json` |
| Footer | Satu kalimat produk + link kembali ke demo | — |

### 6.2 Aturan konten

- **Faktual saja.** Setiap klaim harus bisa diverifikasi ke kode. Dilarang
  menyertakan angka traction, pengguna, atau performa yang tidak ada di repo.
- **Tidak ada slug generik.** "Revolusioner", "game-changing", "next-generation"
  dilarang. Judul kartu Problem harus berupa masalah nyata.
- **Demo path wajib menyebut halaman tujuan.** Nilai utama ada di CTA: juri harus tahu
  persis halaman mana yang dibuka berikutnya.
- Bahasa: Inggris untuk UI (konsisten dengan 9 halaman yang sudah jadi), komentar
  kode dan dokumen ini dalam Bahasa Indonesia.

### 6.3 Aturan visual

- `bg-app #080d14`, `bg-panel #0d1117`, `border slate-800/60` — identik dengan app.
-aksen tunggal: biru `#3b82f6`. Tanpa gradien ungu-biru, tanpa drop shadow besar.
- Radius `rounded-xl` untuk kartu, `rounded-lg` untuk kontrol.
- Lebar konten `max-w-6xl`, padding `px-6`.
- Heading: `h1` satu per halaman, `h2` per section, `h3` per kartu.

### 6.4 Acceptance criteria

- [x] `/landing` bisa diakses dan ter-prerender sebagai statis
- [x] First Load JS route ini < 10 kB
- [x] Semua CTA mengarah ke `/` yang valid
- [x] Anchor `#problem`, `#how`, `#agents`, `#demo` punya target yang ada
- [x] Tidak ada emoji sebagai ikon
- [x] `h1` → `h2` → `h3` tidak melompat
- [x] Teks minimal kontras AA terhadap background (`slate-400` di `#080d14` ≈ 7.4:1)

---

## 7. Bug ledger

Semua di bawah ini **lolos** `lint`, `typecheck`, 36 test, dan `build` pada
commit `8a5081b`.

### 7.1 Critical —(Media rusak di layar pertama)

| ID | Bug | Akar masalah | Fix |
|---|---|---|---|
| B-01 | Banner `fixed top-0 z-50` menutupi seluruh `TopNavbar` dan logo `LeftNav` di mode MOCK | Banner `fixed`vs shell `h-screen` tanpa offset | Banner masuk flow layout; `h-screen` pindah ke `<body>`, halaman jadi `h-full` |
| B-02 | "Live Connection" (hijau) dan "OFFLINE" (merah) tampil bersamaan | `TopNavbar` baca const env, banner baca `/health` | `useBackendStatus` jadi satu poller dengan banyak subscriber |
| B-03 | Dropdown `<select>` terbuka dengan latar terang | Tidak ada `color-scheme` | `color-scheme: dark` di `globals.css` |
| B-04 | Font Inter tidak pernah terpakai, jatuh ke system-ui | `globals.css` `:root` mendefinisikan `--font-inter` lebih dulu, menimpa nama family dari `next/font` | Deklarasi `:root` dihapus; `var(--font-inter)` dari `next/font/local` yang dipakai |

### 7.2 Dead controls — kontrol yang tidak melakukan apa-apa

| ID | Bug | Fix |
|---|---|---|
| B-05 | Tombol gear Settings tanpa `onClick` | Props `onOpenSettings` → navigasi ke halaman Settings |
| B-06 | Search + filter di Code Graph: state ada, tapi tidak pernah diteruskan ke `SynapseGraph` | `lib/graphFilter.ts` + wiring, 9 test |
| B-07 | `Browse` di Settings — tidak mungkin memilih folder server dari browser | Dihapus |
| B-08 | `View Schema` di Settings — tidak ada endpoint schema | Dihapus |
| B-09 | `Save Changes` dan `Reset to Default` tanpa handler | Persistensi `localStorage` dengan umpan balik "Saved to this browser" |
| B-10 | Toggle `Conflict auto-deny` hardcoded `value={true} onChange={() => {}}` | State nyata |
| B-11 | Branch selector dengan chevron, tidak terhubung ke endpoint mana pun | Chevron dihapus, jadi label statis |
| B-12 | Search box + `⌘K` di TopNavbar, tidak ada handler keyboard | Dihapus; search milik Code Graph |
| B-13 | Logo `LeftNav` bukan link | Jadi `Link` ke `/landing` |
| B-14 | "System Healthy" hardcoded hijau, hijau walaupun backend mati | Baca status sebenarnya |
| B-15 | "View Details →" di panel node | Di luar scope demo, tetap deferred — lihat §9 |

### 7.3 Visual & consistency

| ID | Bug | Fix |
|---|---|---|
| B-16 | Entitas HTML di dalam string literal JS (`"SQLite &#183; FastAPI"`) tampil literal | Karakter asli (`·`) |
| B-17 | Ikon navigasi campur: entitas geometris + emoji 🛡 berwarna + ⚙ dobel untuk Operations dan Settings | Semua ikon SVG garis 24×24, `stroke=currentColor` |
| B-18 | Logo gradien biru→ungu + huruf "S" | Glyph sinaps SVG, aksen tunggal |
| B-19 | `graphData` tidak pernah difilter; kanvas `#0f172a` vs spec `#080d14` | Filter ditambahkan, warna disamakan |
| B-20 | `dangerouslySetInnerHTML` untuk ikon statis | Teks biasa |
| B-21 | `onNodeClick` diteruskan ke `app/page.tsx` yangState-nya tidak pernah dibaca | Rantai dipotong, prop jadi opsional |
| B-22 | Nav item punya field `icon` yang mati dan berbeda dengan switch `NavIcon` | Satu sumber: path SVG di `NAV_ITEMS` |

### 7.4 Aksesibilitas

| ID | Bug | Fix |
|---|---|---|
| B-23 | `Field` memakai `<span>`, bukan `<label>` — input tanpa accessible name | `<label htmlFor>` + `useId` |
| B-24 | Toggle tidak punya `role="switch"` / `aria-checked` | Ditambahkan |
| B-25 | Tidak ada `:focus-visible` di seluruh aplikasi | Ring global di `globals.css` |
| B-26 | Ikon-only button tanpa accessible name | `aria-label` |
| B-27 | `catch { return; }` menelan error `/health` dan `/graph/summary` | Error dirender di Settings; `AbortController` saat unmount |

---

## 8. Acceptance criteria — UI/UX wrap

- [x] `npm run lint` hijau
- [x] `npm run typecheck` hijau
- [x] `npm test` hijau, 36 test (termasuk 9 test filter graph baru)
- [x] `npm run build` hijau
- [x] `/landing` ter-prerender statis
- [x] Nol dependency baru di `package.json`
- [x] Banner tidak menutupi shell di mode apa pun
- [x] Hanya satu polling `/health` di seluruh aplikasi
- [x] Mode mock menandai dirinya sendiri sebagai `DEMO DATA`

---

## 9. Utang yang sengaja ditunda

| Utang | Alasan | Kapanadding |
|---|---|---|
| `View Details →` di panel node (B-15) | Butuh route/halaman detail; tidak ada di 9 halaman sekarang | Kalau juri sempat menanyakan "buka detailnya" |
| Search global / CMD palette | Cmd palette adalah fitur, bukan perbaikan | Setelah demo path stabil |
| Selector branch | Butuh endpoint daftar branch | Kalau backend meng-expose branch |
| Visual regression test | Butuh runner browser di CI | Kalau CI sudah punya Playwright |
| Halaman detail Settings > Storage | Butuh `GET /schema` | Kalau endpoint itu ada |

Semua baris di atas **tidak** ditulis di UI sebagai kontrol yang tidak berfungsi.
Kontrol yang tidak bisa dikerjakan harus dihapus, bukan dipalsukan.

---

## 10. Checklist demo (hackathon)

1. Buka `/landing` — 30 detik, problem → how it works → agents.
2. Klik `Open Live Demo` — pastikan banner tidak menutupi top bar.
3. **Code Graph** — cari `auth`, filter `Symbol`, klik satu node.
4. **Guardian** — setujui satu operasi; perhatikan perubahan status di grafik.
5. **Approvals** lalu **Security** — tunjukkan jejak audit.
6. Kalau ditanya "ini data beneran?" — tunjuk badge `DEMO DATA`, jelaskan cara
   mengaktifkan data live. Jangan pernah mengklaim mock sebagai nyata.

---

## 11. Maintenance

- **Two files, satu aturan warna.** Token ada di `DESIGN_SYSTEM.md` dan dipakai
  lewat kelas Tailwind di komponen. Tidak ada CSS variable untuk warna. Kalau
  token berubah, `DESIGN_SYSTEM.md` + `app/landing/page.tsx` + komponen shell
  harus berubah bersamaan.
- **Satu sumber status.** Jangan pernah memanggil `/health` dari komponen baru.
  Pakai `useBackendStatus()`.
- **Test untuk logic, bukan untuk render.** `lib/*.ts` yang punya cabang wajib punya
  `lib/*.test.ts`. Command: `npm test` (`node --test`).
- **Verifikasi 4 perintah.** `lint`, `typecheck`, `test`, `build`. Hijau di tiga
  pertama tidak menjamin build — jalankan keempatnya.
