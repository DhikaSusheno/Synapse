"use client";

// components/TargetPicker.tsx
// Pilih target analisis: folder lokal di mesin server, atau repository GitHub.
//
// INI BUKAN "upload file" seperti LocalFolderPanel. Target adalah folder yang
// di-indeks seluruh isinya oleh backend (tree-sitter, kompleksitas, relasi),
// dan hanya satu target aktif pada satu waktu. Jadi ganti target di sini
// mengganti SELURUH isi Overview, Cortex, dan Code Graph - bukan menambah file.
//
// Konsekuensi yang harus terlihat di UI: setelah pindah target, angka dan
// grafik di halaman lain berubah total. Itu perilaku yang benar, tapi kalau
// tidak Explained, user akan mengira datanya hilang.

import { useCallback, useId, useState } from "react";
import { useTargets } from "@/hooks/useTargets";
import { browseTargetDirs, joinBrowsePath, type BrowseResult } from "@/lib/platformSettings";
import { summarizeIngest, type Target } from "@/lib/targets";

const inputCls =
  "bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-200 outline-none placeholder-slate-600 focus:border-blue-500/60";
const btnPrimary =
  "rounded-lg bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed";
const btnGhost =
  "rounded-lg border border-slate-700/60 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800/60 disabled:opacity-40 disabled:cursor-not-allowed";

function Notice({ kind, text }: { kind: "ok" | "err"; text: string }) {
  const cls =
    kind === "ok"
      ? "border-emerald-500/30 bg-emerald-900/20 text-emerald-300"
      : "border-red-500/30 bg-red-900/20 text-red-400";
  return <p className={`rounded-lg border px-3 py-2 text-xs ${cls}`}>{text}</p>;
}

function kindBadge(target: Target) {
  return target.kind === "github" ? "GitHub" : "Folder";
}

/**
 * Baris status target. Sengaja menampilkan path server apa adanya: user
 * perlu tahu folder mana yang sedang dianalisis, dan path itu juga satu-
 *-satunya cara membedakan dua target dengan label sama.
 */
function TargetRow({
  target,
  isActive,
  busy,
  onActivate,
  onRemove,
}: {
  target: Target;
  isActive: boolean;
  busy: boolean;
  onActivate: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <li
      className={`rounded-lg border px-3 py-2 ${
        isActive
          ? "border-blue-500/50 bg-blue-900/15"
          : "border-slate-700/60 bg-slate-800/30"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-xs font-medium text-slate-200">
              {target.label}
            </span>
            <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[10px] text-slate-300">
              {kindBadge(target)}
            </span>
            {isActive && (
              <span className="rounded bg-blue-600/25 px-1.5 py-0.5 text-[10px] text-blue-200">
                aktif
              </span>
            )}
            {!target.available && (
              <span
                className="rounded bg-amber-600/25 px-1.5 py-0.5 text-[10px] text-amber-200"
                title="Folder tidak ditemukan atau berada di luar area yang diizinkan"
              >
                tidak tersedia
              </span>
            )}
          </span>
          <span className="mt-0.5 block truncate text-[10px] text-slate-500" title={target.path}>
            {target.source ? `${target.source}@${target.branch ?? "main"} - ` : ""}
            {target.path}
          </span>
        </span>
        {!isActive && (
          <button
            type="button"
            className={btnGhost}
            disabled={busy || !target.available}
            onClick={() => onActivate(target.id)}
            title={
              target.available
                ? "Pindah analisis ke target ini"
                : "Folder target tidak ditemukan atau di luar area yang diizinkan"
            }
          >
            Analisis
          </button>
        )}
        <button
          type="button"
          className={btnGhost}
          disabled={busy}
          onClick={() => onRemove(target.id)}
          title="Hapus dari daftar target. Graph hasil pindai tidak ikut terhapus kecuali centang opsi di bawah."
        >
          Hapus
        </button>
      </div>
    </li>
  );
}

/** Daftar subfolder dari /api/targets/browse, untuk memilih tanpa mengetik path. */
function BrowseList({
  result,
  onPick,
  onUp,
  disabled,
}: {
  result: BrowseResult;
  onPick: (path: string) => void;
  onUp: (path: string) => void;
  disabled: boolean;
}) {
  const dirs = result.entries.filter((e) => e.type === "dir");
  if (!dirs.length) {
    return <p className="px-2 py-1 text-[10px] text-slate-500">Tidak ada subfolder di sini.</p>;
  }
  return (
    <ul className="max-h-52 overflow-y-auto">
      {result.parent !== null && (
        <li>
          <button
            type="button"
            className="w-full px-2 py-1 text-left text-[11px] text-slate-400 hover:bg-slate-800"
            disabled={disabled}
            onClick={() => onUp(result.parent as string)}
          >
            .. (naik)
          </button>
        </li>
      )}
      {dirs.map((entry) => {
        const child = joinBrowsePath(result.absolute_path, entry.name);
        return (
          <li key={entry.name} className="flex items-center gap-1">
            <button
              type="button"
              className="min-w-0 flex-1 truncate px-2 py-1 text-left text-[11px] text-slate-300 hover:bg-slate-800"
              disabled={disabled}
              onClick={() => onPick(child)}
              title={child}
            >
              {entry.name}/
            </button>
            <button
              type="button"
              className="px-2 py-1 text-[10px] text-blue-300 hover:text-blue-200 disabled:opacity-40"
              disabled={disabled}
              onClick={() => onPick(child)}
              title="Pakai folder ini sebagai target"
            >
              pakai
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export default function TargetPicker({ compact = false }: { compact?: boolean }) {
  const {
    targets,
    active,
    ingest,
    loading,
    busy,
    error,
    refresh,
    addLocal,
    addGitHub,
    activate,
    remove,
    clearError,
  } = useTargets();

  const pathId = useId();
  const labelId = useId();
  const sourceId = useId();
  const branchId = useId();

  const [mode, setMode] = useState<"local" | "github">("local");
  const [label, setLabel] = useState("");
  const [path, setPath] = useState("");
  const [source, setSource] = useState("");
  const [branch, setBranch] = useState("main");
  const [notice, setNotice] = useState<string | null>(null);
  const [removeGraph, setRemoveGraph] = useState(false);
  const [browse, setBrowse] = useState<BrowseResult | null>(null);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);

  // Path "" = backend membuka folder home, jadi tombolnya langsung berguna
  // tanpa user harus tahu absolute path-nya dulu.
  const openBrowse = useCallback(async (target: string) => {
    setBrowsing(true);
    setBrowseError(null);
    try {
      const result = await browseTargetDirs(target);
      setBrowse(result);
      setPath(result.absolute_path);
    } catch (err) {
      setBrowse(null);
      setBrowseError(err instanceof Error ? err.message : String(err));
    } finally {
      setBrowsing(false);
    }
  }, []);

  const submitLocal = useCallback(async () => {
    setNotice(null);
    clearError();
    try {
      const res = await addLocal({ kind: "local", label, path });
      const label2 = res.target?.label;
      setNotice(
        `Target "${label2 ?? label}" dibuat. ${summarizeIngest(res.ingest)}`.trim() ||
          "Target dibuat.",
      );
      setLabel("");
      setPath("");
      setBrowse(null);
    } catch {
      // Pesan sudah masuk ke state `error` oleh hook.
    }
  }, [addLocal, clearError, label, path]);

  const submitGitHub = useCallback(async () => {
    setNotice(null);
    clearError();
    try {
      const res = await addGitHub({ kind: "github", source, branch, label: label || undefined });
      setNotice(
        `Repo disinkronkan: ${res.sync?.files ?? 0} file, ${summarizeIngest(res.ingest)}`.trim(),
      );
      setSource("");
      setLabel("");
    } catch {
      // Pesan sudah masuk ke state `error` oleh hook.
    }
  }, [addGitHub, branch, clearError, label, source]);

  const ingestNote = summarizeIngest(ingest);

  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      {!compact && (
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Target analisis
          </h3>
          <button
            type="button"
            className={btnGhost}
            onClick={() => void refresh()}
            disabled={loading || busy}
          >
            Muat ulang
          </button>
        </div>
      )}

      {!compact && (
        <p className="text-[11px] leading-relaxed text-slate-500">
          Target adalah folder yang diindeks <strong>seluruh isinya</strong>. Hanya satu
          target aktif pada satu waktu, jadi mengganti target akan mengganti semua data
          di Overview, Cortex, dan Code Graph - bukan menambah file ke data lama.
        </p>
      )}

      {active && (
        <div className="rounded-lg border border-blue-500/40 bg-blue-900/15 px-3 py-2 text-[11px]">
          <div className="text-slate-400">Sedang dianalisis</div>
          <div className="mt-0.5 font-medium text-blue-200">{active.label}</div>
          <div className="mt-0.5 break-all text-[10px] text-slate-500">{active.path}</div>
          {ingestNote && <div className="mt-1 text-[10px] text-slate-400">{ingestNote}</div>}
        </div>
      )}

      {!loading && targets.length === 0 && !active && (
        <p className="rounded-lg border border-slate-700/60 bg-slate-800/30 px-3 py-2 text-[11px] text-slate-500">
          Belum ada target. Tambahkan folder lokal atau sinkronkan repository GitHub di
          bawah - tanpa target, semua halaman graph akan kosong.
        </p>
      )}

      {targets.length > 0 && (
        <ul className="space-y-1.5">
          {targets.map((t) => (
            <TargetRow
              key={t.id}
              target={t}
              isActive={t.id === active?.id}
              busy={busy}
              onActivate={(id) => void activate(id)}
              onRemove={(id) => void remove(id, { removeGraph })}
            />
          ))}
        </ul>
      )}

      <label className="flex items-center gap-1.5 text-[10px] text-slate-500">
        <input
          type="checkbox"
          checked={removeGraph}
          onChange={(e) => setRemoveGraph(e.target.checked)}
        />
        Saat menghapus target, hapus juga hasil pindai (graph) yang tersimpan
      </label>

      <div className="flex gap-1 border-t border-slate-800 pt-2">
        {(["local", "github"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`rounded-lg px-2.5 py-1 text-[11px] ${
              mode === m
                ? "bg-slate-700 text-slate-100"
                : "text-slate-400 hover:bg-slate-800"
            }`}
          >
            {m === "local" ? "Folder lokal" : "Repository GitHub"}
          </button>
        ))}
      </div>

      {mode === "local" ? (
        <div className="space-y-2">
          <div>
            <label htmlFor={labelId} className="mb-0.5 block text-[10px] text-slate-500">
              Label
            </label>
            <input
              id={labelId}
              className={`${inputCls} w-full`}
              value={label}
              placeholder="mis. synapse-repo"
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor={pathId} className="mb-0.5 block text-[10px] text-slate-500">
              Path folder di mesin server
            </label>
            <input
              id={pathId}
              className={`${inputCls} w-full font-mono`}
              value={path}
              placeholder="C:\Users\dhika\projects\my-app  atau  ./backend"
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitLocal();
              }}
            />
            <p className="mt-1 text-[10px] text-slate-500">
              Path dibaca di backend, bukan di browser. Klik{" "}
              <span className="text-slate-400">Telusuri folder...</span> untuk membuka
              folder PC dan memilihnya tanpa mengetik. Folder home, root drive, dan folder
              kredensial (.ssh, .aws) tidak bisa dijadikan target.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              className={btnGhost}
              onClick={() => void openBrowse(path)}
              disabled={browsing || busy}
            >
              {browsing ? "Membaca..." : "Telusuri folder..."}
            </button>
            {browse && <span className="text-[10px] text-slate-500">{browse.absolute_path}</span>}
          </div>

          {browseError && (
            <p className="text-[10px] text-amber-400">
              Folder ini tidak bisa dibuka: {browseError}
            </p>
          )}

          {browse && (
            <div className="rounded-lg border border-slate-700/60 bg-slate-900/40">
              <BrowseList
                result={browse}
                disabled={busy}
                onPick={(p) => {
                  setPath(p);
                  if (!label.trim()) setLabel(p.split(/[\\/]/).filter(Boolean).pop() ?? "");
                  setBrowse(null);
                }}
                onUp={(p) => void openBrowse(p)}
              />
            </div>
          )}

          <button
            type="button"
            className={btnPrimary}
            onClick={() => void submitLocal()}
            disabled={busy || !label.trim() || !path.trim()}
          >
            {busy ? "Memproses..." : "Tambah dan analisis"}
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <div>
            <label htmlFor={sourceId} className="mb-0.5 block text-[10px] text-slate-500">
              Repository
            </label>
            <input
              id={sourceId}
              className={`${inputCls} w-full font-mono`}
              value={source}
              placeholder="DhikaSusheno/Synapse"
              onChange={(e) => setSource(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitGitHub();
              }}
            />
          </div>
          <div className="flex gap-2">
            <div className="min-w-0 flex-1">
              <label htmlFor={branchId} className="mb-0.5 block text-[10px] text-slate-500">
                Branch
              </label>
              <input
                id={branchId}
                className={`${inputCls} w-full font-mono`}
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
              />
            </div>
            <div className="min-w-0 flex-[2]">
              <label htmlFor={labelId} className="mb-0.5 block text-[10px] text-slate-500">
                Label (opsional)
              </label>
              <input
                id={labelId}
                className={`${inputCls} w-full`}
                value={label}
                placeholder="default: owner/repo"
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
          </div>
          <p className="text-[10px] text-slate-500">
            Backend mengunduh tarball (bukan git clone), mengekstraknya ke folder
            workspace, lalu mengindeks isinya. Repo yang sudah pernah disinkronkan akan
            diperbarui, bukan diduplikasi.
          </p>
          <button
            type="button"
            className={btnPrimary}
            onClick={() => void submitGitHub()}
            disabled={busy || !source.trim()}
          >
            {busy ? "Mengunduh dan mengindeks..." : "Sinkronkan dan analisis"}
          </button>
        </div>
      )}

      {error && <Notice kind="err" text={error} />}
      {notice && !error && <Notice kind="ok" text={notice} />}
    </div>
  );
}
