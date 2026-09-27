// app/landing/page.tsx
// Landing page penjelasan Synapse untuk demo hackathon.
// Server component: tanpa state, tanpa fetch, jadi prerender statis dan bundle-nya kecil.
//
// Isi halaman ini sengaja hanya berisi fakta yang benar-benar ada di repo ini.
// Tidak ada angka traction atau performa yang dikarang - juri bisa memverifikasi
// setiap klaim ke kode, dan setiap file yang disebut di bagian Docs benar-benar
// ada di root repository.
//
// ponytail: palet, radius, dan border memakai kelas Tailwind yang sama dengan
// DESIGN_SYSTEM.md. Kalau token berubah, dua tempat harus ikut berubah.

import Link from "next/link";

const AGENTS = [
  {
    name: "Guardian",
    role: "Protection & Safety",
    accent: "text-blue-400 border-blue-500/30 bg-blue-500/10",
    body: "Mengawasi setiap operasi yang mengusulkan agent. Menghitung blast radius, mendeteksi konflik dengan operasi lain yang masih berjalan, dan menahan operasi berisiko tinggi sampai ada persetujuan manusia.",
  },
  {
    name: "Cortex",
    role: "Understanding & Review",
    accent: "text-purple-400 border-purple-500/30 bg-purple-500/10",
    body: "Menjaga pemahaman tentang codebase. Membangun code graph (file, symbol, dependency, doc), menjawab pertanyaan tentang topik lewat LLM yang dikonfigurasi user, dan menilai artifact terhadap spesifikasi.",
  },
  {
    name: "Review",
    role: "Code Review & Analysis",
    accent: "text-slate-300 border-slate-500/30 bg-slate-500/10",
    body: "Menilai hasil kerja agent di luar guardrail: apakah perubahan sudah lengkap, jelas, dan benar terhadap spesifikasi yang diberikan, serta seberapa besar risikonya.",
  },
];

const PROBLEMS = [
  {
    title: "Agent bergerak lebih cepat dari review",
    body: "Coding agent bisa mengusulkan puluhan perubahan dalam semenit. Validator manusia tidak akan sempat membaca semuanya, jadi keputusan jatuh pada tidak seorang pun.",
  },
  {
    title: "Tidak ada pemahaman bersama",
    body: "Setiap sesi agent mulai dari nol. Konteks tentang mengapa sebuah file penting, dan hubungannya dengan file lain, hilang setiap kali agent baru dijalankan.",
  },
  {
    title: "Perubahan sulit dibatalkan",
    body: "Ketika agent menjalankan operasi yang merusak, memulihkan keadaan sebelumnya hampir selalu berarti membaca log dan melakukan perbaikan manual satu per satu.",
  },
];

const LOOP = [
  {
    n: "01",
    title: "Understand",
    body: "Cortex membangun dan menyegarkan code graph milik target aktif. Node file, symbol, dependency, dan doc saling terhubung, jadi perubahan bisa dibaca dalam konteksnya.",
  },
  {
    n: "02",
    title: "Propose",
    body: "Agent mengusulkan operasi. Guardian menghitung blast radius, memeriksa konflik dengan operasi lain yang belum selesai, lalu menentukan apakah perlu persetujuan manusia.",
  },
  {
    n: "03",
    title: "Guard",
    body: "Operasi berisiko tinggi berhenti di approval gate. Manusia melihat rencana pembatalan dan daftar konflik sebelum menyetujui atau menolak.",
  },
  {
    n: "04",
    title: "Verify",
    body: "Setelah disetujui, operasi dijalankan lalu diverifikasi. Kalau verifikasi gagal, sistem menjalankan rollback dan grafik menampilkan state akhir secara terbuka.",
  },
];

const PROPERTIES = [
  {
    title: "Reversible",
    body: "Setiap operasi menyimpan rencana pembatalan sebelum dijalankan, jadi kegagalan bukan akhir cerita.",
  },
  {
    title: "Conflict-aware",
    body: "Dua operasi yang menyentuh resource yang sama dikenali sebelum dijalankan, bukan setelah kerusakannya terlihat.",
  },
  {
    title: "Fail-closed",
    body: "Operasi yang tidak dikenal sistem ditolak secara default, bukan diizinkan dengan asumsi aman.",
  },
  {
    title: "Human in the loop",
    body: "Keputusan berisiko tinggi tetap milik manusia. Sistem mempercepat yang bisa diotomatisasi, bukan keputusan yang penting.",
  },
];

// Pemisahan per target adalah fitur yang paling mudah kehilangan di demo:
// registry target, file graph per target, dan capping history operasi.
const TARGETING = [
  {
    title: "Satu target aktif, graph terisolasi",
    body: "Setiap repository atau folder punya id sendiri dan file database graph sendiri. Pindah target mengganti seluruh isi Overview, Cortex, dan Code Graph - bukan menambah file ke data lama, jadi tidak ada lagi bentrok id entity antar repo.",
  },
  {
    title: "Folder PC bisa dipilih langsung",
    body: "Telusuri folder membuka direktori di mesin server dan hanya mengembalikan nama folder, bukan nama file. Path yang diketik manual tetap diterima, dan root drive, folder home, serta folder kredensial tetap ditolak.",
  },
  {
    title: "Sinkronisasi GitHub tanpa git clone",
    body: "Repository disinkronkan lewat tarball API GitHub, diekstrak dengan filter yang menolak symlink dan path traversal, lalu diindeks. Repo yang sudah pernah disinkronkan diperbarui, bukan diduplikasi.",
  },
  {
    title: "Approval tidak bercampur antar target",
    body: "Setiap operasi dicap dengan target aktif saat dibuat. Ganti repository dan riwayat approval ikut berubah - jadi tidak mungkin menyetujui perubahan di repo yang salah, dan menghapus target tidak menghapus riwayat yang sudah berjalan.",
  },
];

const LLM_PROVIDERS = [
  {
    title: "Provider bebas, bukan daftar tertutup",
    body: "Tipe provider di luar daftar bawaan tetap bisa ditambahkan, selama base URL diisi manual. Tipe yang dikenal mendapat base URL default, jadi OpenAI, Anthropic, Ollama, dan DeepSeek cukup diisi nama dan token.",
  },
  {
    title: "Lokal dikenali, bukan diasumsikan",
    body: "Provider dengan base URL loopback atau file:/// mengirim request tanpa header Authorization. Menebak salah di sini berarti membocorkan API key user ke host yang salah.",
  },
  {
    title: "Kunci tidak pernah masuk browser",
    body: "Token provider disimpan terenkripsi di backend dan hanya dipakai saat request keluar dari server. Frontend tidak pernah membaca atau menyimpan kunci API.",
  },
];

const SAFETY = [
  {
    title: "Path di luar zona ditolak",
    body: "Pembacaan file dibatasi ke root yang terdaftar. Path traversal, root drive, dan file sensitif ditolak - dan aturan ini dikunci test keamanan terpisah.",
  },
  {
    title: "Folder kredensial di-blacklist",
    body: "Folder seperti .ssh, .aws, .gnupg, .kube, dan .config/gcloud tidak bisa dipilih sebagai target maupun dijelajah lewat pemilih folder.",
  },
  {
    title: "Ekstraksi repo ditolak traversal",
    body: "Tarball dari GitHub diekstrak tanpa symlink dan tanpa path keluar dari folder tujuan, jadi token sinkronisasi tidak bisa diarahkan menulis ke luar workspace.",
  },
  {
    title: "API token tetap di server",
    body: "Semua endpoint berada di balik token API yang hanya dibaca server. Browser talking ke backend lewat proxy, tidak pernah memegang token itu.",
  },
];

const DOCS = [
  {
    file: "SYNAPSE.md",
    title: "Arsitektur & kontrak bersama",
    body: "Sumber kebenaran untuk skema SQLite, rule table Guardian, dan bentuk event SSE. Semua PRD tim diturunkan dari dokumen ini.",
  },
  {
    file: "README.md",
    title: "Ikhtisar & alur kerja",
    body: "Peta tim, ownership per folder, dan jadwal 48 jam beserta checkpoint di tiap fase.",
  },
  {
    file: "backend/PRD.md",
    title: "PRD backend",
    body: "Spesifikasi Guardian dan Cortex: propose, execute, verify, rollback, ingest, dan review artifact.",
  },
  {
    file: "frontend/PRD.md",
    title: "PRD frontend",
    body: "Spesifikasi live graph, dashboard, dan konsumen SSE beserta aturan state yang harus dipatuhi.",
  },
  {
    file: "security/PRD.md",
    title: "PRD security & QC",
    body: "Rule engine, pengujian adversarial, fail-closed, dan keandalan rollback.",
  },
  {
    file: "synapse-build-flow.html",
    title: "Diagram alur build",
    body: "Rincian per jam: tugas, output, dan batas mana tim boleh menyentuh apa.",
  },
];

const DEMO_STEPS = [
  {
    page: "Target",
    body: "Buka Settings lalu Target. Daftarkan folder lokal lewat pemilih folder, atau sinkronkan repository GitHub. Lihat file database graph yang berbeda muncul per target.",
  },
  {
    page: "Code Graph",
    body: "Buka Code Graph. Tunjukkan node dan hubungan antar node, lalu pakai kotak pencarian dan filter tipe untuk mempersempit pandangan. Ganti target dan wholegraf ikut berubah.",
  },
  {
    page: "Guardian",
    body: "Buka Guardian. Ada operasi yang menunggu persetujuan lengkap dengan blast radius, rencana pembatalan, dan deteksi konflik. Setujui salah satunya dan lihat statusnya berubah di grafik.",
  },
  {
    page: "Cortex",
    body: "Buka Cortex, pilih provider LLM, lalu ajukan pertanyaan tentang kode. Jawabannya datang dari model milik user, dengan konteks file dari target aktif.",
  },
  {
    page: "Approvals & Security",
    body: "Buka Approvals lalu Security. Riwayat keputusan dan event feed keamanan menunjukkan setiap tindakan meninggalkan jejak yang bisa diaudit - dan terisolasi per repository.",
  },
];

const FACTS = [
  { k: "3", v: "agents: Guardian, Cortex, Review" },
  { k: "9", v: "halaman dashboard" },
  { k: "Per-target", v: "graph dan approval terisolasi per repo atau folder" },
  { k: "Fail-closed", v: "default untuk operasi tak dikenal" },
];

const STACK = [
  "Next.js 14",
  "React 18",
  "TypeScript",
  "Tailwind CSS",
  "react-force-graph-2d",
  "FastAPI",
  "SQLite",
  "tree-sitter",
  "networkx",
  "Server-Sent Events",
];

function LogoMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="w-full h-full" fill="none" stroke="#3b82f6" strokeWidth={1.6} strokeLinecap="round">
      <path d="M12 12L6 6.5M12 12l6-5.5M12 12l-5.5 6M12 12l5.5 6" opacity={0.55} />
      <circle cx="12" cy="12" r="3.1" fill="#3b82f6" stroke="none" />
      <circle cx="6" cy="6.5" r="1.9" />
      <circle cx="18" cy="6.5" r="1.9" />
      <circle cx="6.5" cy="18" r="1.9" />
      <circle cx="17.5" cy="18" r="1.9" />
    </svg>
  );
}

export default function LandingPage() {
  return (
    <div className="h-full overflow-y-auto bg-[#080d14]">
      {/* ---------- Nav ---------- */}
      <header className="sticky top-0 z-10 border-b border-slate-800/60 bg-[#080d14]/90 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-4">
          <span className="flex items-center gap-2.5">
            <span className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/30 flex items-center justify-center">
              <LogoMark />
            </span>
            <span className="text-sm font-bold text-white tracking-tight">SYNAPSE</span>
          </span>
          <nav aria-label="Sections" className="hidden md:flex items-center gap-5 text-xs text-slate-400 ml-4">
            <a href="#problem" className="hover:text-slate-200 transition-colors">Problem</a>
            <a href="#how" className="hover:text-slate-200 transition-colors">How it works</a>
            <a href="#agents" className="hover:text-slate-200 transition-colors">Agents</a>
            <a href="#targets" className="hover:text-slate-200 transition-colors">Targets</a>
            <a href="#docs" className="hover:text-slate-200 transition-colors">Docs</a>
            <a href="#demo" className="hover:text-slate-200 transition-colors">Demo</a>
          </nav>
          <div className="flex-1" />
          <Link href="/" className="text-xs font-semibold px-3.5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors">
            Open Live Demo
          </Link>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6">
        {/* ---------- Hero ---------- */}
        <section className="py-20 sm:py-28 border-b border-slate-800/60">
          <p className="text-xs font-semibold uppercase tracking-widest text-blue-400 mb-5">
            IBM Bob 2.0 Hackathon
          </p>
          <h1 className="text-4xl sm:text-5xl font-bold text-white tracking-tight leading-[1.1] max-w-3xl">
            An understanding layer for AI coding agents that can be stopped and undone.
          </h1>
          <p className="mt-6 text-base text-slate-400 max-w-2xl leading-relaxed">
            Synapse memberi agent satu code graph yang selalu segar, dan menempatkan manusia
            sebagai pengambil keputusan untuk setiap perubahan berisiko - lengkap dengan deteksi
            konflik dan rollback.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link href="/" className="text-sm font-semibold px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors">
              Open Live Demo
            </Link>
            <a href="#how" className="text-sm px-5 py-2.5 rounded-lg border border-slate-700 text-slate-300 hover:border-slate-500 hover:text-white transition-colors">
              How it works
            </a>
            <a href="#docs" className="text-sm px-5 py-2.5 rounded-lg border border-slate-700 text-slate-300 hover:border-slate-500 hover:text-white transition-colors">
              Docs &amp; specs
            </a>
          </div>
          <dl className="mt-14 grid grid-cols-2 sm:grid-cols-4 gap-6">
            {FACTS.map((s) => (
              <div key={s.v} className="border-l border-slate-800 pl-4">
                <dt className="text-xl font-bold text-white">{s.k}</dt>
                <dd className="text-xs text-slate-500 mt-1 leading-snug">{s.v}</dd>
              </div>
            ))}
          </dl>
        </section>

        {/* ---------- Problem ---------- */}
        <section id="problem" className="scroll-mt-14 py-20 border-b border-slate-800/60">
          <h2 className="text-2xl font-bold text-white">The problem</h2>
          <p className="mt-2 text-sm text-slate-400 max-w-2xl">
            Agent sudah bagus menulis kode. Yang belum ada adalah cara melihat dan menghentikan
            apa yang mereka lakukan.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {PROBLEMS.map((p) => (
              <article key={p.title} className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5">
                <h3 className="text-sm font-semibold text-white">{p.title}</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">{p.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------- How it works ---------- */}
        <section id="how" className="scroll-mt-14 py-20 border-b border-slate-800/60">
          <h2 className="text-2xl font-bold text-white">How it works</h2>
          <p className="mt-2 text-sm text-slate-400 max-w-2xl">
            Satu siklus tertutup: memahami konteks, mengusulkan perubahan, menahan yang
            berisiko, lalu memverifikasi hasilnya.
          </p>
          <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {LOOP.map((s) => (
              <li key={s.n} className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5">
                <span className="text-xs font-mono text-blue-400">{s.n}</span>
                <h3 className="mt-2 text-sm font-semibold text-white">{s.title}</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">{s.body}</p>
              </li>
            ))}
          </ol>

          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {PROPERTIES.map((p) => (
              <div key={p.title} className="rounded-xl border border-slate-800/60 p-5">
                <h3 className="text-sm font-semibold text-white">{p.title}</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">{p.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ---------- Agents ---------- */}
        <section id="agents" className="scroll-mt-14 py-20 border-b border-slate-800/60">
          <h2 className="text-2xl font-bold text-white">The three agents</h2>
          <p className="mt-2 text-sm text-slate-400 max-w-2xl">
            Tanggung jawabnya dipisah supaya tidak tumpang tindih.
          </p>
          <div className="mt-10 grid gap-4 lg:grid-cols-3">
            {AGENTS.map((a) => (
              <article key={a.name} className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5">
                <span className={`inline-block text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border ${a.accent}`}>
                  {a.role}
                </span>
                <h3 className="mt-3 text-base font-bold text-white">{a.name}</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">{a.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------- Targets ---------- */}
        <section id="targets" className="scroll-mt-14 py-20 border-b border-slate-800/60">
          <h2 className="text-2xl font-bold text-white">Multi-target, satu-satu</h2>
          <p className="mt-2 text-sm text-slate-400 max-w-2xl">
            Analisis nyata selalu berpindah antara project. Synapse tidak menyatukan semuanya
            jadi satu graph, karena itu membuat nomor, riwayat, dan approval milik repo berbeda
            tercampur.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2">
            {TARGETING.map((p) => (
              <article key={p.title} className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5">
                <h3 className="text-sm font-semibold text-white">{p.title}</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">{p.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------- LLM ---------- */}
        <section id="llm" className="scroll-mt-14 py-20 border-b border-slate-800/60">
          <h2 className="text-2xl font-bold text-white">LLM provider milik user</h2>
          <p className="mt-2 text-sm text-slate-400 max-w-2xl">
            Cortex tidak punya model bawaan. Provider, base URL, dan token dikelola user, dan
            kunci API tidak pernah menyentuh browser.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {LLM_PROVIDERS.map((p) => (
              <article key={p.title} className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5">
                <h3 className="text-sm font-semibold text-white">{p.title}</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">{p.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------- Safety ---------- */}
        <section id="safety" className="scroll-mt-14 py-20 border-b border-slate-800/60">
          <h2 className="text-2xl font-bold text-white">Path &amp; secret handling</h2>
          <p className="mt-2 text-sm text-slate-400 max-w-2xl">
            Fitur yang membaca disk atau mengunduh repository adalah tempat paling rawan
            kebocoran. Empat aturan di bawah mengunci jalur itu.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {SAFETY.map((p) => (
              <article key={p.title} className="rounded-xl border border-slate-800/60 p-5">
                <h3 className="text-sm font-semibold text-white">{p.title}</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">{p.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------- Docs ---------- */}
        <section id="docs" className="scroll-mt-14 py-20 border-b border-slate-800/60">
          <h2 className="text-2xl font-bold text-white">Docs &amp; specs</h2>
          <p className="mt-2 text-sm text-slate-400 max-w-2xl">
            Semua ada di root repository, ditulis tim yang mengerjakannya, dan dipakai juri
            untuk memverifikasi klaim di halaman ini.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2">
            {DOCS.map((d) => (
              <article key={d.file} className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5">
                <code className="text-[11px] font-mono text-blue-300">{d.file}</code>
                <h3 className="mt-2 text-sm font-semibold text-white">{d.title}</h3>
                <p className="mt-1.5 text-xs text-slate-400 leading-relaxed">{d.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------- Demo script ---------- */}
        <section id="demo" className="scroll-mt-14 py-20 border-b border-slate-800/60">
          <h2 className="text-2xl font-bold text-white">Demo path</h2>
          <p className="mt-2 text-sm text-slate-400 max-w-2xl">
            Lima langkah yang cukup untuk melihat sistem bekerja dari ujung ke ujung.
          </p>
          <ol className="mt-10 space-y-3">
            {DEMO_STEPS.map((s, i) => (
              <li key={s.page} className="flex gap-4 rounded-xl border border-slate-800/60 bg-[#0d1117] p-5">
                <span className="text-xs font-mono text-slate-500 pt-0.5">{i + 1}</span>
                <div>
                  <h3 className="text-sm font-semibold text-white">{s.page}</h3>
                  <p className="mt-1.5 text-xs text-slate-400 leading-relaxed">{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-8">
            <Link href="/" className="inline-block text-sm font-semibold px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors">
              Start the demo
            </Link>
          </div>
        </section>

        {/* ---------- Stack ---------- */}
        <section className="py-20">
          <h2 className="text-2xl font-bold text-white">Built with</h2>
          <div className="mt-6 flex flex-wrap gap-2">
            {STACK.map((t) => (
              <span key={t} className="text-xs text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-800/40">
                {t}
              </span>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-800/60">
        <div className="max-w-6xl mx-auto px-6 py-8 flex flex-col sm:flex-row items-start sm:items-center gap-3 justify-between">
          <p className="text-xs text-slate-500">
            Synapse - reversible, conflict-aware guardrails for AI coding agents.
          </p>
          <div className="flex items-center gap-4">
            <a href="#docs" className="text-xs text-slate-400 hover:text-slate-200 transition-colors">
              Docs
            </a>
            <Link href="/" className="text-xs font-semibold text-blue-400 hover:text-blue-300 transition-colors">
              Open Live Demo
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
