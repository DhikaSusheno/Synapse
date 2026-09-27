"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BACKEND_URL,
  USE_LIVE,
  browsePath,
  getSettings,
  getStorage,
  resetSettings,
  saveSettings,
  subscribe,
  refreshSettings,
  type BrowseResult,
  type PlatformSettings,
  type StorageOverview,
} from "@/lib/platformSettings";

type Tab = "General" | "MCP / Server" | "Storage" | "Repository" | "Approval";

const EDITABLE_KEYS = [
  "platform_name",
  "environment",
  "log_level",
  "dev_mode",
  "workspace_path",
  "default_branch",
  "auto_migrate",
  "conflict_detect",
  "sse_enabled",
  "approval_mode",
  "conflict_auto_deny",
] as const;

type EditableKey = (typeof EDITABLE_KEYS)[number];

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      className={`w-10 h-5 rounded-full transition-colors relative ${
        value ? "bg-blue-600" : "bg-slate-700"
      }`}
    >
      <span
        className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
          value ? "translate-x-5" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-slate-800/40 last:border-0">
      <span className="text-xs text-slate-300 shrink-0">{label}</span>
      <div className="flex items-center gap-2 min-w-0">{children}</div>
    </div>
  );
}

const inputCls =
  "bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-300 outline-none focus:border-blue-500/60";

function formatSize(bytes: number | null) {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function BrowseDialog({
  onClose,
  onPick,
}: {
  onClose: () => void;
  onPick: (path: string) => void;
}) {
  const [result, setResult] = useState<BrowseResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      setResult(await browsePath(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load("");
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const dirs = (result?.entries ?? []).filter((e) => e.type === "dir");
  const files = (result?.entries ?? []).filter((e) => e.type === "file");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg rounded-xl border border-slate-700/60 bg-[#0d1117] shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800/60 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-white">Pilih Workspace</h2>
            <p className="mt-0.5 font-mono text-[10px] text-slate-500">
              {result?.absolute_path ?? "memuat..."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            Tutup
          </button>
        </div>

        <div className="max-h-72 overflow-y-auto px-2 py-2">
          {error && (
            <p className="px-2 py-3 text-xs text-red-400">{error}</p>
          )}
          {loading && !result && (
            <p className="px-2 py-3 text-xs text-slate-500">Memuat...</p>
          )}

          {result?.parent !== null && result?.parent !== undefined && (
            <button
              type="button"
              onClick={() => void load(result.parent!)}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-slate-300 hover:bg-slate-800"
            >
              <span className="text-slate-500">&#8593;</span> parent
            </button>
          )}

          {dirs.map((entry) => (
            <button
              key={`d-${entry.name}`}
              type="button"
              onClick={() => void load(`${result?.path === "." ? "" : result?.path}/${entry.name}`)}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-slate-200 hover:bg-slate-800"
            >
              <span className="text-amber-400">&#128193;</span>
              <span className="truncate">{entry.name}</span>
            </button>
          ))}

          {files.length > 0 && (
            <div className="mt-1 border-t border-slate-800/60 pt-1">
              {files.map((entry) => (
                <div
                  key={`f-${entry.name}`}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-slate-500"
                >
                  <span>&#128196;</span>
                  <span className="truncate">{entry.name}</span>
                  <span className="ml-auto shrink-0 font-mono text-[10px]">
                    {formatSize(entry.size)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {result && result.entries.length === 0 && (
            <p className="px-2 py-3 text-xs text-slate-500">Folder kosong</p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-800/60 px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700/60 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200"
          >
            Batal
          </button>
          <button
            type="button"
            disabled={!result}
            onClick={() => onPick(result!.path === "." ? "./" : result!.path)}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-40"
          >
            Pilih folder ini
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("General");
  const [draft, setDraft] = useState<PlatformSettings | null>(getSettings());
  const [saved, setSaved] = useState<PlatformSettings | null>(getSettings());
  const [storage, setStorage] = useState<StorageOverview | null>(getStorage());
  const [serverHealth, setServerHealth] = useState<{ status: string } | null>(null);
  const [graphSummary, setGraphSummary] = useState<{
    total_nodes: number;
    total_edges: number;
  } | null>(null);
  const [browseOpen, setBrowseOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    const sync = () => {
      setStorage(getStorage());
      setDraft(getSettings());
    };
    const unsubscribe = subscribe(sync);
    void refreshSettings();
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (!USE_LIVE) return;
    fetch(`${BACKEND_URL}/health`)
      .then((r) => r.json())
      .then(setServerHealth)
      .catch(() => setServerHealth({ status: "offline" }));
    fetch(`${BACKEND_URL}/graph/summary`)
      .then((r) => r.json())
      .then(setGraphSummary)
      .catch(() => setGraphSummary(null));
  }, []);

  const set = useCallback(<K extends EditableKey>(key: K, value: PlatformSettings[K]) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
    setNotice(null);
  }, []);

  const dirty = useCallback(() => {
    if (!draft || !saved) return false;
    return EDITABLE_KEYS.some((k) => draft[k] !== saved[k]);
  }, [draft, saved]);

  const handleSave = useCallback(async () => {
    if (!draft) return;
    setBusy(true);
    setNotice(null);
    try {
      const next = await saveSettings(draft);
      setSaved(next);
      setDraft(next);
      setNotice({ kind: "ok", text: "Pengaturan disimpan" });
    } catch (err) {
      setNotice({ kind: "err", text: `Gagal menyimpan: ${err instanceof Error ? err.message : err}` });
    } finally {
      setBusy(false);
    }
  }, [draft]);

  const handleReset = useCallback(async () => {
    setBusy(true);
    setNotice(null);
    try {
      const next = await resetSettings();
      setSaved(next);
      setDraft(next);
      setNotice({ kind: "ok", text: "Dikembalikan ke default" });
    } catch (err) {
      setNotice({ kind: "err", text: `Gagal reset: ${err instanceof Error ? err.message : err}` });
    } finally {
      setBusy(false);
    }
  }, []);

  const TABS: Tab[] = ["General", "MCP / Server", "Storage", "Repository", "Approval"];
  const online = serverHealth?.status === "ok";
  const tableList = Object.entries(storage?.tables ?? {});
  const totalTables = tableList.reduce((sum, [, names]) => sum + names.length, 0);

  if (!USE_LIVE) {
    return (
      <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
        <div>
          <h1 className="text-xl font-bold text-white">Settings</h1>
          <p className="mt-0.5 text-sm text-slate-400">Configure Synapse platform</p>
        </div>
        <p className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5 text-sm text-slate-400">
          Mode mock aktif. Set <code className="font-mono text-slate-300">NEXT_PUBLIC_USE_LIVE_SSE=true</code> di{" "}
          <code className="font-mono text-slate-300">.env.local</code> untuk menyimpan pengaturan ke backend.
        </p>
      </div>
    );
  }

  if (!draft || !saved) {
    return (
      <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
        <div>
          <h1 className="text-xl font-bold text-white">Settings</h1>
          <p className="mt-0.5 text-sm text-slate-400">Configure Synapse platform</p>
        </div>
        <p className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5 text-sm text-slate-400">
          {notice?.text ?? "Menghubungkan ke backend..."}
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">Settings</h1>
        <p className="mt-0.5 text-sm text-slate-400">Configure Synapse platform</p>
      </div>

      <div className="flex gap-1 rounded-xl border border-slate-800/60 bg-[#0d1117] p-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`flex-1 rounded-lg py-1.5 text-xs transition-colors ${
              activeTab === tab
                ? "bg-slate-700 font-medium text-white"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-slate-800/60 bg-[#0d1117] p-5">
        {activeTab === "General" && (
          <div>
            <Field label="Platform Name">
              <input
                value={draft.platform_name}
                onChange={(e) => set("platform_name", e.target.value)}
                className={`${inputCls} w-40`}
                placeholder="Synapse"
              />
            </Field>
            <Field label="Environment">
              <select
                value={draft.environment}
                onChange={(e) => set("environment", e.target.value)}
                className={inputCls}
              >
                {["Production", "Staging", "Development"].map((e) => (
                  <option key={e}>{e}</option>
                ))}
              </select>
            </Field>
            <Field label="Log Level">
              <select
                value={draft.log_level}
                onChange={(e) => set("log_level", e.target.value)}
                className={inputCls}
              >
                {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
            </Field>
            <Field label="Developer Mode">
              <Toggle value={draft.dev_mode} onChange={(v) => set("dev_mode", v)} />
            </Field>
          </div>
        )}

        {activeTab === "MCP / Server" && (
          <div>
            <Field label="FastAPI Server">
              <span className="flex items-center gap-1.5 text-xs">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    online ? "bg-green-400" : "bg-red-400"
                  }`}
                />
                <span className="text-slate-300">{online ? "Running" : "Offline"}</span>
                <span className="text-slate-600">: 8000</span>
              </span>
            </Field>
            <Field label="SSE Stream">
              <span className="flex items-center gap-1.5 text-xs">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    online && draft.sse_enabled ? "bg-green-400" : "bg-slate-600"
                  }`}
                />
                <span className="text-slate-300">
                  {!online ? "Offline" : draft.sse_enabled ? "Enabled" : "Disabled"}
                </span>
                <span className="text-slate-600">/stream</span>
              </span>
            </Field>
            <Field label="Settings File">
              <span className="font-mono text-[10px] text-slate-400">synapse_settings.json</span>
            </Field>
            <Field label="SSE Stream (opsional)">
              <Toggle value={draft.sse_enabled} onChange={(v) => set("sse_enabled", v)} />
            </Field>
          </div>
        )}

        {activeTab === "Storage" && (
          <div>
            <Field label="Database Files">
              <div className="flex flex-col items-end gap-0.5">
                {(storage?.files ?? []).length === 0 && (
                  <span className="text-xs text-slate-500">-</span>
                )}
                {(storage?.files ?? []).map((f) => (
                  <span key={f.label} className="font-mono text-[10px] text-slate-400">
                    {f.file} <span className="text-slate-600">({formatSize(f.size_bytes)})</span>
                  </span>
                ))}
              </div>
            </Field>
            <Field label="Total Nodes">
              <span className="text-xs text-slate-300">{graphSummary?.total_nodes ?? "~"}</span>
            </Field>
            <Field label="Total Edges">
              <span className="text-xs text-slate-300">{graphSummary?.total_edges ?? "~"}</span>
            </Field>
            <Field label="Tables">
              <span className="text-xs text-slate-400">
                {totalTables > 0 ? `${totalTables} tabel` : "-"}
              </span>
            </Field>
            {tableList.map(([label, names]) => (
              <Field key={label} label={`&nbsp;&nbsp;&nbsp;${label}`}>
                <span className="truncate font-mono text-[10px] text-slate-500">
                  {names.join(", ") || "-"}
                </span>
              </Field>
            ))}
          </div>
        )}

        {activeTab === "Repository" && (
          <div>
            <Field label="Default Branch">
              <input
                value={draft.default_branch}
                onChange={(e) => set("default_branch", e.target.value)}
                className={`${inputCls} w-28 font-mono`}
                placeholder="main"
              />
            </Field>
            <Field label="Workspace Path">
              <div className="flex min-w-0 items-center gap-2">
                <input
                  value={draft.workspace_path}
                  onChange={(e) => set("workspace_path", e.target.value)}
                  className={`${inputCls} w-40 font-mono`}
                  placeholder="./workspace"
                />
                <button
                  type="button"
                  onClick={() => setBrowseOpen(true)}
                  className="shrink-0 rounded border border-slate-700/60 px-2 py-1 text-[10px] text-slate-400 hover:border-slate-600 hover:text-slate-200"
                >
                  Browse
                </button>
              </div>
            </Field>
            <Field label="Auto DB Migration">
              <Toggle value={draft.auto_migrate} onChange={(v) => set("auto_migrate", v)} />
            </Field>
            <Field label="Enable Conflict Detection">
              <Toggle value={draft.conflict_detect} onChange={(v) => set("conflict_detect", v)} />
            </Field>
            <Field label="Enable SSE Events">
              <Toggle value={draft.sse_enabled} onChange={(v) => set("sse_enabled", v)} />
            </Field>
          </div>
        )}

        {activeTab === "Approval" && (
          <div>
            <Field label="Default approval mode">
              <select
                value={draft.approval_mode}
                onChange={(e) => set("approval_mode", e.target.value)}
                className={inputCls}
              >
                {["Manual (human required)", "Auto-approve low risk", "Auto-deny all"].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </Field>
            <Field label="Conflict auto-deny">
              <Toggle
                value={draft.conflict_auto_deny}
                onChange={(v) => set("conflict_auto_deny", v)}
              />
            </Field>
          </div>
        )}
      </div>

      {notice && (
        <p
          className={`text-xs ${
            notice.kind === "ok" ? "text-green-400" : "text-red-400"
          }`}
        >
          {notice.text}
        </p>
      )}

      <div className="flex items-center justify-end gap-3">
        {dirty() && <span className="mr-auto text-xs text-amber-400">Perubahan belum disimpan</span>}
        <button
          type="button"
          onClick={() => {
            setDraft(saved);
            setNotice(null);
          }}
          disabled={!dirty() || busy}
          className="rounded-lg border border-slate-700/60 px-4 py-2 text-xs text-slate-400 transition-colors hover:border-slate-600 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Discard
        </button>
        <button
          type="button"
          onClick={() => void handleReset()}
          disabled={busy}
          className="rounded-lg border border-slate-700/60 px-4 py-2 text-xs text-slate-400 transition-colors hover:border-slate-600 hover:text-slate-200 disabled:opacity-40"
        >
          Reset to Default
        </button>
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={!dirty() || busy}
          className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-bold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Menyimpan..." : "Save Changes"}
        </button>
      </div>

      {browseOpen && (
        <BrowseDialog
          onClose={() => setBrowseOpen(false)}
          onPick={(path) => {
            set("workspace_path", path);
            setBrowseOpen(false);
          }}
        />
      )}
    </div>
  );
}
