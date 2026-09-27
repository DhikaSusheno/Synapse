"use client";
// components/pages/SettingsPage.tsx
// Halaman Settings — sesuai design section 8
// FE-1 @nabilfauzandafa
//
// Semua preferensi disimpan di localStorage (sesuai DESIGN_SYSTEM.md section 8):
// backend tidak punya endpoint /settings. Yang tampil sebagai "status" (server,
// SSE, storage) SELALU berasal dari backend nyata, tidak bisa diedit di sini.

import { useEffect, useId, useRef, useState } from "react";
import { useBackendStatus } from "@/hooks/useBackendStatus";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";
const STORAGE_KEY = "synapse.settings";

type Tab = "General" | "MCP / Server" | "Storage" | "Repository" | "Approval";

interface Settings {
  platformName: string;
  environment: string;
  logLevel: string;
  devMode: boolean;
  workspacePath: string;
  defaultBranch: string;
  autoMigrate: boolean;
  conflictDetect: boolean;
  sseEnabled: boolean;
  approvalMode: string;
  conflictAutoDeny: boolean;
}

const DEFAULTS: Settings = {
  platformName: "Synapse",
  environment: "Production",
  logLevel: "INFO",
  devMode: false,
  workspacePath: "./workspace",
  defaultBranch: "main",
  autoMigrate: true,
  conflictDetect: true,
  sseEnabled: true,
  approvalMode: "Manual (human required)",
  conflictAutoDeny: true,
};

function Toggle({ id, value, onChange }: { id: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      className={`w-10 h-5 rounded-full transition-colors relative shrink-0 ${
        value ? "bg-blue-600" : "bg-slate-700"
      }`}
    >
      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
        value ? "translate-x-5" : "translate-x-0.5"
      }`} />
    </button>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-slate-800/40 last:border-0">
      <label htmlFor={id} className="text-xs text-slate-300">{label}</label>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

const INPUT = "bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-300 outline-none";

export default function SettingsPage() {
  const uid = useId();
  const id = (name: string) => `${uid}-${name}`;
  const [activeTab, setActiveTab] = useState<Tab>("General");
  const [s, setS] = useState<Settings>(DEFAULTS);
  const [saved, setSaved] = useState(false);
  const [serverHealth, setServerHealth] = useState<{ status: string } | null>(null);
  const [graphSummary, setGraphSummary] = useState<{ total_nodes: number; total_edges: number } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { mode } = useBackendStatus();

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    setS((prev) => ({ ...prev, [key]: value }));

  // Muat preferensi tersimpan. Satu state object, bukan 10 useState terpisah.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setS({ ...DEFAULTS, ...(JSON.parse(raw) as Partial<Settings>) });
    } catch {
      // localStorage tidak tersedia (private mode) — pakai default, jangan crash.
    }
  }, []);

  // Status backend: abort saat unmount, error ditampilkan (tidak ditelan).
  useEffect(() => {
    if (!USE_LIVE) return;
    const ctrl = new AbortController();
    async function load() {
      try {
        const [h, g] = await Promise.all([
          fetch(`${BACKEND_URL}/health`, { signal: ctrl.signal, cache: "no-store" }),
          fetch(`${BACKEND_URL}/graph/summary`, { signal: ctrl.signal, cache: "no-store" }),
        ]);
        if (!h.ok) throw new Error(`/health → ${h.status}`);
        setServerHealth(await h.json());
        if (g.ok) setGraphSummary(await g.json());
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setLoadError(e instanceof Error ? e.message : "Gagal memuat status backend");
      }
    }
    load();
    return () => ctrl.abort();
  }, []);

  useEffect(() => () => { if (savedTimer.current) clearTimeout(savedTimer.current); }, []);

  function flashSaved() {
    setSaved(true);
    if (savedTimer.current) clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => setSaved(false), 2000);
  }

  function save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
      flashSaved();
    } catch {
      setLoadError("localStorage penuh atau ditolak browser — preferensi tidak tersimpan");
    }
  }

  function reset() {
    setS(DEFAULTS);
    try { localStorage.removeItem(STORAGE_KEY); } catch { /* abaikan */ }
    flashSaved();
  }

  const TABS: Tab[] = ["General", "MCP / Server", "Storage", "Repository", "Approval"];

  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">Settings</h1>
        <p className="text-sm text-slate-400 mt-0.5">Configure Synapse platform</p>
      </div>

      <div className="flex gap-1 bg-[#0d1117] rounded-xl border border-slate-800/60 p-1" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 text-xs py-1.5 rounded-lg transition-colors ${
              activeTab === tab ? "bg-slate-700 text-white font-medium" : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {loadError && (
        <div role="alert" className="bg-red-900/20 border border-red-500/30 rounded-xl px-4 py-3 text-xs text-red-400">
          {loadError}
        </div>
      )}

      <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-5">
        {activeTab === "General" && (
          <div className="space-y-0">
            <Field id={id("name")} label="Platform Name">
              <input id={id("name")} value={s.platformName} onChange={(e) => set("platformName", e.target.value)}
                className={`${INPUT} w-36`} />
            </Field>
            <Field id={id("env")} label="Environment">
              <select id={id("env")} value={s.environment} onChange={(e) => set("environment", e.target.value)} className={INPUT}>
                {["Production", "Staging", "Development"].map((e) => <option key={e}>{e}</option>)}
              </select>
            </Field>
            <Field id={id("log")} label="Log Level">
              <select id={id("log")} value={s.logLevel} onChange={(e) => set("logLevel", e.target.value)} className={INPUT}>
                {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => <option key={l}>{l}</option>)}
              </select>
            </Field>
            <Field id={id("dev")} label="Developer Mode">
              <Toggle id={id("dev")} value={s.devMode} onChange={(v) => set("devMode", v)} />
            </Field>
          </div>
        )}

        {activeTab === "MCP / Server" && (
          <div className="space-y-0">
            <Field id={id("srv")} label="FastAPI Server">
              <span className="flex items-center gap-1.5 text-xs">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                  serverHealth?.status === "ok" ? "bg-green-400" : USE_LIVE ? "bg-red-400" : "bg-yellow-400"
                }`} />
                <span className="text-slate-300">{serverHealth?.status === "ok" ? "Running" : USE_LIVE ? "Offline" : "Demo"}</span>
                <span className="text-slate-600">:{USE_LIVE ? "8000" : "3000"}</span>
              </span>
            </Field>
            <Field id={id("sse")} label="SSE Stream">
              <span className="flex items-center gap-1.5 text-xs">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                  mode === "live" ? "bg-green-400" : mode === "offline" ? "bg-red-400" : "bg-yellow-400"
                }`} />
                <span className="text-slate-300">
                  {mode === "live" ? "Connected" : mode === "offline" ? "Unreachable" : "Not connected"}
                </span>
                <span className="text-slate-600">/stream</span>
              </span>
            </Field>
            <Field id={id("mcp")} label="MCP Task">
              <span className="text-xs text-slate-500">5 / 5 min</span>
            </Field>
          </div>
        )}

        {activeTab === "Storage" && (
          <div className="space-y-0">
            <Field id={id("db")} label="Database File">
              <span className="text-xs text-slate-400 font-mono">synapse.db</span>
            </Field>
            <Field id={id("n")} label="Total Nodes">
              <span className="text-xs text-slate-300">{graphSummary?.total_nodes ?? "—"}</span>
            </Field>
            <Field id={id("e")} label="Total Edges">
              <span className="text-xs text-slate-300">{graphSummary?.total_edges ?? "—"}</span>
            </Field>
            <Field id={id("t")} label="Tables">
              <span className="text-xs text-slate-400">nodes, edges, operations</span>
            </Field>
            {/* ponytail: tombol "View Schema" dihapus — tidak ada endpoint schema
                dan daftar tabelnya sudah tampil di baris atas. Tambahkan kalau
                GET /schema benar-benar ada. */}
          </div>
        )}

        {activeTab === "Repository" && (
          <div className="space-y-0">
            <Field id={id("branch")} label="Default Branch">
              <input id={id("branch")} value={s.defaultBranch} onChange={(e) => set("defaultBranch", e.target.value)}
                className={`${INPUT} w-28 font-mono`} />
            </Field>
            <Field id={id("ws")} label="Workspace Path">
              {/* ponytail: tombol "Browse" dihapus. Browser tidak bisa memilih
                  folder di server; <input webkitdirectory> hanya memilih folder
                  LOKAL, yang akan tampil seolah-olah itu path server — lebih buruk
                  daripada tidak ada tombol. */}
              <input id={id("ws")} value={s.workspacePath} onChange={(e) => set("workspacePath", e.target.value)}
                className={`${INPUT} w-44 font-mono`} />
            </Field>
            <Field id={id("mig")} label="Auto DB Migration">
              <Toggle id={id("mig")} value={s.autoMigrate} onChange={(v) => set("autoMigrate", v)} />
            </Field>
            <Field id={id("cd")} label="Enable Conflict Detection">
              <Toggle id={id("cd")} value={s.conflictDetect} onChange={(v) => set("conflictDetect", v)} />
            </Field>
            <Field id={id("sse-en")} label="Enable SSE Events">
              <Toggle id={id("sse-en")} value={s.sseEnabled} onChange={(v) => set("sseEnabled", v)} />
            </Field>
          </div>
        )}

        {activeTab === "Approval" && (
          <div className="space-y-0">
            <Field id={id("mode")} label="Default approval mode">
              <select id={id("mode")} value={s.approvalMode} onChange={(e) => set("approvalMode", e.target.value)} className={INPUT}>
                {["Manual (human required)", "Auto-approve low risk", "Auto-deny all"].map((m) => <option key={m}>{m}</option>)}
              </select>
            </Field>
            <Field id={id("cad")} label="Conflict auto-deny">
              <Toggle id={id("cad")} value={s.conflictAutoDeny} onChange={(v) => set("conflictAutoDeny", v)} />
            </Field>
          </div>
        )}
      </div>

      <div className="flex items-center justify-end gap-3">
        <span aria-live="polite" className={`text-xs ${saved ? "text-green-400" : "text-transparent"}`}>
          {saved ? "Saved to this browser" : "placeholder"}
        </span>
        <button onClick={reset}
          className="text-xs text-slate-400 border border-slate-700/60 rounded-lg px-4 py-2 hover:text-slate-200 hover:border-slate-600 transition-colors">
          Reset to Default
        </button>
        <button onClick={save}
          className="text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 font-bold transition-colors">
          Save Changes
        </button>
      </div>
    </div>
  );
}
