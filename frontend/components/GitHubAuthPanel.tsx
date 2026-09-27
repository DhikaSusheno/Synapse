"use client";

// components/GitHubAuthPanel.tsx
// Tab GitHub di Settings: hubungkan akun, pilih repo, telusuri file, kirim
// satu file ke Cortex sebagai artefak review.
//
// Soal kredensial: PAT diketik user, langsung dikirim ke backend untuk
// divalidasi dan dienkripsi (auth.encrypt_token), lalu dibuang dari state.
// Yang tampil di panel ini cuma login dan avatar. Tidak ada localStorage, dan
// tidak ada header token yang dibuat di browser - proxy
// app/backend/[...path] yang menyuntik SYNAPSE_API_TOKEN.

import { useCallback, useEffect, useState } from "react";
import GitHubRepoPicker from "@/components/GitHubRepoPicker";
import FileTreeBrowser from "@/components/FileTreeBrowser";
import { useGitHubAuth } from "@/hooks/useGitHubAuth";
import {
  buildFileTree,
  fetchFileContent,
  fetchRepoTree,
  type GitHubRepo,
} from "@/lib/githubApi";
import { countDirs, countFiles, type FileTreeNode } from "@/lib/fileTree";
import { ARTIFACT_MAX_CHARS, clampArtifact, setArtifact } from "@/lib/workspaceArtifact";

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

export default function GitHubAuthPanel() {
  const {
    user,
    connection,
    mode,
    busy,
    error: authError,
    oauthUnavailable,
    refresh: refreshAuth,
    connectPat,
    disconnect: disconnectGitHub,
    getOAuthUrl,
  } = useGitHubAuth();
  const authUserLogin = user?.login;
  const authUserAvatar = user?.avatar_url;
  const authType = connection?.type;
  const [pickerOpen, setPickerOpen] = useState(false);
  const [repo, setRepo] = useState<GitHubRepo | null>(null);
  const [branch, setBranch] = useState("main");
  const [nodes, setNodes] = useState<FileTreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ path: string; text: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pat, setPat] = useState("");

  // GitHub OAuth berakhir di backend yang lalu meng-redirect ke
  // /settings?github=connected. Banner itu perlu dibersihkan supaya tidak
  // menempel terus setiap kali user membuka tab lain.
  //
  // Dependensi cuma `refreshAuth`, bukan objek hasil hook: objek itu identitasnya
  // baru tiap render, jadi memakainya sebagai dependensi menjalankan efek ini
  // terus-menerus.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("github") !== "connected") return;
    setNotice(`Terhubung sebagai ${params.get("login") ?? "?"}.`);
    void refreshAuth();
    params.delete("github");
    params.delete("login");
    const query = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}`,
    );
  }, [refreshAuth]);

  const loadTree = useCallback(async (target: GitHubRepo, targetBranch: string) => {
    const [owner, name] = target.full_name.split("/");
    if (!owner || !name) return;
    setTreeLoading(true);
    setTreeError(null);
    setPreview(null);
    try {
      const items = await fetchRepoTree(owner, name, targetBranch);
      setNodes(buildFileTree(items));
    } catch (err) {
      setNodes([]);
      setTreeError(err instanceof Error ? err.message : String(err));
    } finally {
      setTreeLoading(false);
    }
  }, []);

  const chooseRepo = useCallback(
    (target: GitHubRepo) => {
      setRepo(target);
      setBranch(target.default_branch || "main");
      setNotice(null);
      void loadTree(target, target.default_branch || "main");
    },
    [loadTree],
  );

  const openFile = useCallback(
    async (path: string) => {
      if (!repo) return;
      const [owner, name] = repo.full_name.split("/");
      if (!owner || !name) return;
      setPreviewLoading(true);
      setPreviewError(null);
      try {
        setPreview({ path, text: await fetchFileContent(owner, name, path, branch) });
      } catch (err) {
        setPreview(null);
        setPreviewError(err instanceof Error ? err.message : String(err));
      } finally {
        setPreviewLoading(false);
      }
    },
    [repo, branch],
  );

  const sendToCortex = () => {
    if (!repo || !preview) return;
    const { text, truncated } = clampArtifact(preview.text);
    setArtifact({
      label: `${repo.full_name}@${branch}/${preview.path}`,
      content: text,
      source: "github",
      at: Date.now(),
    });
    setNotice(
      truncated
        ? `"${preview.path}" dikirim ke Cortex (dipotong di ${ARTIFACT_MAX_CHARS} karakter).`
        : `"${preview.path}" dikirim ke artefak Cortex.`,
    );
  };

  if (mode === "unknown") {
    return <p className="text-xs text-slate-500 animate-pulse">Memuat status koneksi...</p>;
  }

  return (
    <div className="space-y-4">
      {notice && <Notice kind="ok" text={notice} />}
      {authError && <Notice kind="err" text={authError} />}

      {mode === "connected" ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-700/60 bg-[#0d1117] p-3">
          {authUserAvatar ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={authUserAvatar}
              alt=""
              className="h-8 w-8 rounded-full border border-slate-700/60"
            />
          ) : null}
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-white">
              {authUserLogin ?? "terhubung"}
            </p>
            <p className="text-[10px] text-slate-500">
              via {authType === "pat" ? "Personal Access Token" : "OAuth"}
            </p>
          </div>
          <button type="button" className={btnPrimary} onClick={() => setPickerOpen(true)}>
            Pilih Repository
          </button>
          <button
            type="button"
            className={btnGhost}
            disabled={busy}
            onClick={() => {
              if (!window.confirm("Putuskan GitHub dan hapus token yang tersimpan?")) return;
              void disconnectGitHub().then((removed) => {
                setRepo(null);
                setNodes([]);
                setPreview(null);
                setNotice(
                  removed > 0
                    ? "Koneksi GitHub diputus, token dihapus."
                    : "Tidak ada koneksi untuk diputus.",
                );
              });
            }}
          >
            Putuskan
          </button>
        </div>
      ) : (
        <ConnectForm
          busy={busy}
          pat={pat}
          oauthUnavailable={oauthUnavailable}
          onPat={setPat}
          onConnectPat={() => {
            const value = pat.trim();
            if (!value) return;
            void connectPat(value)
              .then(() => {
                setPat("");
                setNotice("GitHub terhubung.");
              })
              .catch(() => undefined);
          }}
          onOAuth={() => {
            void getOAuthUrl().then((url) => {
              if (url) window.location.href = url;
            });
          }}
        />
      )}

      {repo && (
        <div className="space-y-3 rounded-lg border border-slate-700/60 bg-[#0d1117] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-xs font-medium text-white">
              {repo.full_name}
            </span>
            <span className="text-[10px] text-slate-600">@</span>
            <input
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && repo) void loadTree(repo, branch.trim());
              }}
              className={`${inputCls} w-32 font-mono`}
              aria-label="Branch"
            />
            <button
              type="button"
              className={btnGhost}
              disabled={treeLoading}
              onClick={() => void loadTree(repo, branch.trim())}
            >
              {treeLoading ? "Memuat..." : "Muat tree"}
            </button>
            <span className="text-[10px] text-slate-500">
              {countFiles(nodes)} file, {countDirs(nodes)} folder
            </span>
          </div>

          {treeError && <Notice kind="err" text={treeError} />}

          <div className="grid gap-3 md:grid-cols-2">
            <div className="min-h-48 max-h-96 overflow-hidden rounded border border-slate-800/60">
              <FileTreeBrowser
                nodes={nodes}
                onFileClick={(node) => void openFile(node.path)}
                emptyLabel={treeLoading ? "Memuat tree..." : "Tree kosong atau belum dimuat."}
              />
            </div>

            <div className="min-h-48 max-h-96 overflow-auto rounded border border-slate-800/60 bg-slate-900/30 p-2">
              {previewLoading ? (
                <p className="text-[11px] text-slate-500 animate-pulse">Mengambil file...</p>
              ) : previewError ? (
                <Notice kind="err" text={previewError} />
              ) : preview ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-slate-400">
                      {preview.path}
                    </span>
                    <button type="button" className={btnPrimary} onClick={sendToCortex}>
                      Kirim ke Cortex
                    </button>
                  </div>
                  <pre className="whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-slate-300">
                    {preview.text}
                  </pre>
                </div>
              ) : (
                <p className="text-[11px] text-slate-500">
                  Pilih file di tree untuk melihat isinya. File dikirim ke backend lewat
                  proxy server-side; token GitHub tidak pernah masuk browser.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      <GitHubRepoPicker
        isOpen={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={chooseRepo}
      />
    </div>
  );
}

const ARTIFACT_NOTE = "batas aman";

function ConnectForm({
  busy,
  pat,
  oauthUnavailable,
  onPat,
  onConnectPat,
  onOAuth,
}: {
  busy: boolean;
  pat: string;
  oauthUnavailable: boolean;
  onPat: (value: string) => void;
  onConnectPat: () => void;
  onOAuth: () => void;
}) {
  return (
    <div className="space-y-3 rounded-lg border border-slate-700/60 bg-[#0d1117] p-3">
      <p className="text-xs text-slate-400">
        Belum terhubung. Hubungkan lewat Personal Access Token, atau OAuth kalau backend
        punya <span className="font-mono text-slate-300">GITHUB_CLIENT_ID</span> dan{" "}
        <span className="font-mono text-slate-300">GITHUB_CLIENT_SECRET</span>.
      </p>

      <div className="space-y-1.5">
        <label className="block text-[10px] uppercase tracking-wide text-slate-500">
          Personal Access Token
        </label>
        <div className="flex gap-1.5">
          <input
            type="password"
            value={pat}
            onChange={(e) => onPat(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onConnectPat();
            }}
            placeholder="ghp_... (scope: repo, read:org, read:user)"
            className={`${inputCls} flex-1 font-mono`}
            autoComplete="off"
          />
          <button
            type="button"
            className={btnPrimary}
            disabled={busy || !pat.trim()}
            onClick={onConnectPat}
          >
            Hubungkan
          </button>
        </div>
        <p className="text-[10px] text-slate-500">
          Token dikirim ke backend, divalidasi ke api.github.com, lalu dienkripsi sebelum
          disimpan. Setelah tombol ditekan, nilai PAT dibuang dari halaman ini.
        </p>
      </div>

      {oauthUnavailable ? (
        <p className="rounded-lg border border-amber-500/30 bg-amber-900/10 px-3 py-2 text-[11px] text-amber-300">
          OAuth tidak aktif. Set <span className="font-mono">GITHUB_CLIENT_ID</span> dan{" "}
          <span className="font-mono">GITHUB_CLIENT_SECRET</span> di environment backend,
          lalu daftarkan callback <span className="font-mono">/api/github/callback</span> di
          GitHub OAuth App. meantime, Personal Access Token di atas sudah cukup.
        </p>
      ) : (
        <button type="button" className={btnGhost} disabled={busy} onClick={onOAuth}>
          Hubungkan lewat OAuth
        </button>
      )}
    </div>
  );
}
