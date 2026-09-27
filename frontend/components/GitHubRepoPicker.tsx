"use client";

// components/GitHubRepoPicker.tsx
// Modal untuk memilih repository GitHub

import { useState, useEffect } from "react";
import { useGitHubRepo, GitHubRepo } from "@/hooks/useGitHubRepo";

interface GitHubRepoPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (repo: GitHubRepo) => void;
}

export default function GitHubRepoPicker({ isOpen, onClose, onSelect }: GitHubRepoPickerProps) {
  const { repos, loading, error, notConnected, fetchRepos } = useGitHubRepo();
  const [search, setSearch] = useState("");

  // Daftar diambil saat modal dibuka, bukan saat mount: komponen ini mount
  // sekali di halaman Settings, jadi mount-time fetch akan berjalan tanpa
  // ada yang melihat hasilnya.
  useEffect(() => {
    if (!isOpen) return;
    setSearch("");
    void fetchRepos();
  }, [isOpen, fetchRepos]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  const filteredRepos = repos.filter((repo) =>
    repo.full_name.toLowerCase().includes(search.toLowerCase()) ||
    repo.description?.toLowerCase().includes(search.toLowerCase())
  );

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-2xl rounded-xl border border-slate-700/60 bg-[#0d1117] shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-800/60 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-sm">
              <svg className="w-4 h-4 text-purple-400" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.36 3.497.277.079-.528 1.386-.95 2.37-1.87-.258-1.721-1.022-1.822-2.09-.192-.664-.664-2.192-.851-3.588-.137-.445-.546-2.32 1.165-2.779.329-.255.7-.804 1.272-.987.249-.075.508-.136.77-.156 1.602-.11 3.244.842 3.672 2.551.103-.168.225-.417.376-.644C20.286 10.297 24 7.938 24 5.373 24 5.373 18.626 0 12 0z"/>
              </svg>
            </span>
            <span className="text-sm font-semibold text-white">Pilih Repository</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
          >
            Tutup
          </button>
        </div>

        <div className="p-4">
          <div className="relative mb-4">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Cari repository..."
              className="w-full bg-slate-800/60 border border-slate-700/60 rounded-lg px-10 py-2 text-xs text-slate-300 outline-none placeholder-slate-600"
            />
          </div>

          {error && (
            <div className="mb-4 p-3 text-xs text-red-400 bg-red-900/20 border border-red-500/30 rounded-lg">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-6 w-6 border-2 border-blue-500 border-t-transparent" />
              <span className="ml-2 text-xs text-slate-400">Memuat repository...</span>
            </div>
          ) : notConnected ? (
            <div className="text-center py-8 text-slate-400 text-xs space-y-1">
              <p>Belum ada koneksi GitHub.</p>
              <p className="text-slate-500">
                Hubungkan lewat tab <span className="font-mono text-slate-300">GitHub</span> di Settings
                (Personal Access Token atau OAuth).
              </p>
            </div>
          ) : repos.length === 0 ? (
            <div className="text-center py-8 text-slate-500 text-xs">
              Tidak ada repository ditemukan
            </div>
          ) : (
            <div className="max-h-80 overflow-y-auto space-y-1">
              {filteredRepos.map((repo) => (
                <button
                  key={repo.id}
                  onClick={() => {
                    onSelect(repo);
                    onClose();
                  }}
                  className="w-full flex items-start gap-3 p-3 rounded-lg border border-slate-700/60 bg-[#0d1117] hover:bg-slate-800/60 hover:border-slate-600/60 transition-colors text-left"
                >
                  <svg className="w-5 h-5 text-purple-400 shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.36 3.497.277.079-.528 1.386-.95 2.37-1.87-.258-1.721-1.022-1.822-2.09-.192-.664-.664-2.192-.851-3.588-.137-.445-.546-2.32 1.165-2.779.329-.255.7-.804 1.272-.987.249-.075.508-.136.77-.156 1.602-.11 3.244.842 3.672 2.551.103-.168.225-.417.376-.644C20.286 10.297 24 7.938 24 5.373 24 5.373 18.626 0 12 0z"/>
                  </svg>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-white truncate">{repo.full_name}</span>
                      {repo.private && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30">
                          Private
                        </span>
                      )}
                    </div>
                    <p className="text-[10px] text-slate-500 truncate mt-0.5">{repo.description || "Tidak ada deskripsi"}</p>
                    <div className="flex items-center gap-2 mt-1 text-[9px] text-slate-500">
                      {repo.language && (
                        <span className="flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                          {repo.language}
                        </span>
                      )}
                      <span className="text-slate-600">★ {repo.stargazers_count}</span>
                      <span className="text-slate-600">{repo.default_branch}</span>
                    </div>
                  </div>
                  <svg className="w-4 h-4 text-slate-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              ))}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}