"use client";

// components/LocalFolderPanel.tsx
// Tab Folder Lokal: pilih folder di mesin sendiri, telusuri isinya, kirim satu
// file ke Cortex sebagai artefak review.
//
// Dibaca lewat File System Access API di dalam browser, jadi tidak ada request
// ke backend dan tidak ada token yang berpindah tangan. File yang dipilih tidak
// dikirim ke mana pun sampai user menekan "Kirim ke Cortex".
//
// Batasan yang harus jujur ke user: izin folder tidak bertahan lintas reload.
// Setelah refresh, folder harus dipilih ulang. Ditulis eksplisit di UI, bukan
// disembunyikan - user akan mengira ada bug kalau tidak disebut.

import { useCallback, useState } from "react";
import FileTreeBrowser from "@/components/FileTreeBrowser";
import {
  buildLocalTree,
  formatSize,
  isFolderAccessSupported,
  pickDirectory,
  readLocalFile,
  walkDirectory,
  type LocalFile,
} from "@/lib/localFolder";
import { countDirs, countFiles, type FileTreeNode } from "@/lib/fileTree";
import { ARTIFACT_MAX_CHARS, clampArtifact, setArtifact } from "@/lib/workspaceArtifact";

const inputCls =
  "bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-200 outline-none placeholder-slate-600 focus:border-blue-500/60";
const btnPrimary =
  "rounded-lg bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed";
const btnGhost =
  "rounded-lg border border-slate-700/60 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800/60 disabled:opacity-40 disabled:cursor-not-allowed";

const PREVIEW_MAX_CHARS = 100_000;

function Notice({ kind, text }: { kind: "ok" | "err"; text: string }) {
  const cls =
    kind === "ok"
      ? "border-emerald-500/30 bg-emerald-900/20 text-emerald-300"
      : "border-red-500/30 bg-red-900/20 text-red-400";
  return <p className={`rounded-lg border px-3 py-2 text-xs ${cls}`}>{text}</p>;
}

export default function LocalFolderPanel() {
  const supported = isFolderAccessSupported();
  const [folderName, setFolderName] = useState<string | null>(null);
  const [nodes, setNodes] = useState<FileTreeNode[]>([]);
  const [byPath, setByPath] = useState<Map<string, LocalFile>>(new Map());
  const [truncated, setTruncated] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ path: string; text: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const scan = useCallback(async () => {
    setScanning(true);
    setError(null);
    setNotice(null);
    setPreview(null);
    try {
      const handle = await pickDirectory();
      // null = user menekan Cancel di dialog, bukan kegagalan.
      if (!handle) {
        setNotice("Pemilihan folder dibatalkan.");
        return;
      }
      const { files, truncated: capped } = await walkDirectory(handle);
      const tree = buildLocalTree(files);
      setFolderName(handle.name);
      setNodes(tree.nodes);
      setByPath(tree.byPath);
      setTruncated(capped);
      if (files.length === 0) {
        setNotice(`Folder "${handle.name}" tidak punya file yang ditampilkan.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setScanning(false);
    }
  }, []);

  const openFile = useCallback(async (path: string) => {
    const file = byPath.get(path);
    if (!file) return;
    setPreviewLoading(true);
    setError(null);
    try {
      const text = await readLocalFile(file);
      setPreview({ path, text });
    } catch (err) {
      setPreview(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoading(false);
    }
  }, [byPath]);

  // Ukuran byte asli dari handle, bukan text.length: text.length menghitung
  // karakter UTF-16, jadi file dengan banyak karakter non-ASCII akan terlihat
  // lebih kecil daripada ukuran aslinya.
  const previewBytes = preview ? (byPath.get(preview.path)?.size ?? null) : null;

  const sendToCortex = () => {    if (!folderName || !preview) return;
    const { text, truncated: clipped } = clampArtifact(preview.text);
    setArtifact({
      label: `${folderName}/${preview.path}`,
      content: text,
      source: "local",
      at: Date.now(),
    });
    setNotice(
      clipped
        ? `"${preview.path}" dikirim ke Cortex (dipotong di ${ARTIFACT_MAX_CHARS} karakter).`
        : `"${preview.path}" dikirim ke artefak Cortex.`,
    );
  };

  if (!supported) {
    return (
      <Notice
        kind="err"
        text="Browser ini belum mendukung File System Access API. Pilih folder dari backend lewat tab Repository (workspace_path) kalau mau tetap jalan."
      />
    );
  }

  return (
    <div className="space-y-4">
      {notice && <Notice kind="ok" text={notice} />}
      {error && <Notice kind="err" text={error} />}

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-700/60 bg-[#0d1117] p-3">
        <button type="button" className={btnPrimary} disabled={scanning} onClick={() => void scan()}>
          {scanning ? "Membaca folder..." : folderName ? "Ganti Folder" : "Pilih Folder"}
        </button>
        {folderName && (
          <>
            <span className="truncate text-xs font-medium text-white">{folderName}</span>
            <span className="text-[10px] text-slate-500">
              {countFiles(nodes)} file, {countDirs(nodes)} folder
            </span>
          </>
        )}
        <button
          type="button"
          className={btnGhost}
          disabled={!preview}
          onClick={() => {
            if (!preview) return;
            void navigator.clipboard
              ?.writeText(preview.text)
              .then(() => setNotice(`Isi "${preview.path}" disalin ke clipboard.`))
              .catch(() => setError("Browser menolak akses clipboard."));
          }}
        >
          Salin isi
        </button>
      </div>

      {truncated && (
        <Notice
          kind="err"
          text="Folder lebih besar dari batas tampilan, jadi yang tampil tidak lengkap. Folder berat seperti node_modules, .git, dan .next otomatis dilewati."
        />
      )}

      {!folderName && (
        <p className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-4 text-xs text-slate-500">
          Pilih folder lokal untuk menelusurinya di sini. Isi file dibaca di browser dan
          tidak dikirim ke backend kecuali kamu menekan &quot;Kirim ke Cortex&quot;.
          <br />
          <span className="text-slate-600">
            Izin folder tidak bertahan setelah reload halaman - pilih ulang setelah refresh.
          </span>
        </p>
      )}

      {folderName && (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="min-h-48 max-h-96 overflow-hidden rounded border border-slate-800/60">
            <FileTreeBrowser
              nodes={nodes}
              onFileClick={(node) => void openFile(node.path)}
              emptyLabel={scanning ? "Membaca folder..." : "Folder kosong."}
            />
          </div>

          <div className="min-h-48 max-h-96 overflow-auto rounded border border-slate-800/60 bg-slate-900/30 p-2">
            {previewLoading ? (
              <p className="text-[11px] text-slate-500 animate-pulse">Membaca file...</p>
            ) : preview ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-slate-400">
                    {preview.path}
                    {previewBytes !== null && (
                      <span className="ml-1 text-slate-600">({formatSize(previewBytes)})</span>
                    )}
                  </span>
                  <button type="button" className={btnPrimary} onClick={sendToCortex}>
                    Kirim ke Cortex
                  </button>
                </div>
                <pre className="whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-slate-300">
                  {preview.text.slice(0, PREVIEW_MAX_CHARS)}
                </pre>
                {preview.text.length > PREVIEW_MAX_CHARS && (
                  <p className="text-[10px] text-amber-400">
                    Pratinjau dipotong di {PREVIEW_MAX_CHARS.toLocaleString("id-ID")} karakter.
                    Tekan &quot;Salin isi&quot; untuk mendapat seluruhnya.
                  </p>
                )}
              </div>
            ) : (
              <p className="text-[11px] text-slate-500">
                Pilih file di tree untuk melihat isinya di sini.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
