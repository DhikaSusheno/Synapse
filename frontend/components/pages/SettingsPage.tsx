"use client";
// components/pages/SettingsPage.tsx
// Halaman Settings — sesuai design section 8
// FE-1 @nabilfauzandafa

import { useEffect, useState } from "react";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

type Tab = "General" | "MCP / Server" | "Storage" | "Repository" | "Approval";

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={`w-10 h-5 rounded-full transition-colors relative ${
        value ? "bg-blue-600" : "bg-slate-700"
      }`}
    >
      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
        value ? "translate-x-5" : "translate-x-0.5"
      }`} />
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-800/40 last:border-0">
      <span className="text-xs text-slate-300">{label}</span>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("General");
  const [platformName, setPlatformName] = useState("Synapse");
  const [environment, setEnvironment] = useState("Production");
  const [logLevel, setLogLevel] = useState("INFO");
  const [devMode, setDevMode] = useState(false);
  const [workspacePath, setWorkspacePath] = useState("./workspace");
  const [defaultBranch, setDefaultBranch] = useState("main");
  const [autoMigrate, setAutoMigrate] = useState(true);
  const [conflictDetect, setConflictDetect] = useState(true);
  const [sseEnabled, setSseEnabled] = useState(true);
  const [serverHealth, setServerHealth] = useState<{status:string}|null>(null);
  const [graphSummary, setGraphSummary] = useState<{total_nodes:number;total_edges:number}|null>(null);

  useEffect(() => {
    if (!USE_LIVE) return;
    fetch(`${BACKEND_URL}/health`).then((r) => r.json()).then(setServerHealth).catch(() => null);
    fetch(`${BACKEND_URL}/graph/summary`).then((r) => r.json()).then(setGraphSummary).catch(() => null);
  }, []);

  const TABS: Tab[] = ["General", "MCP / Server", "Storage", "Repository", "Approval"];

  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">Settings</h1>
        <p className="text-sm text-slate-400 mt-0.5">Configure Synapse platform</p>
      </div>

      <div className="flex gap-1 bg-[#0d1117] rounded-xl border border-slate-800/60 p-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 text-xs py-1.5 rounded-lg transition-colors ${
              activeTab === tab ? "bg-slate-700 text-white font-medium" : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-5">
        {activeTab === "General" && (
          <div className="space-y-0">
            <Field label="Platform Name">
              <input value={platformName} onChange={(e) => setPlatformName(e.target.value)}
                className="bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-300 outline-none w-36" />
            </Field>
            <Field label="Environment">
              <select value={environment} onChange={(e) => setEnvironment(e.target.value)}
                className="bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-300 outline-none">
                {["Production", "Staging", "Development"].map((e) => <option key={e}>{e}</option>)}
              </select>
            </Field>
            <Field label="Log Level">
              <select value={logLevel} onChange={(e) => setLogLevel(e.target.value)}
                className="bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-300 outline-none">
                {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => <option key={l}>{l}</option>)}
              </select>
            </Field>
            <Field label="Developer Mode">
              <Toggle value={devMode} onChange={setDevMode} />
            </Field>
          </div>
        )}

        {activeTab === "MCP / Server" && (
          <div className="space-y-0">
            <Field label="FastAPI Server">
              <span className="flex items-center gap-1.5 text-xs">
                <span className={`w-1.5 h-1.5 rounded-full ${
                  serverHealth?.status === "ok" ? "bg-green-400" : "bg-red-400"
                }`}></span>
                <span className="text-slate-300">{serverHealth?.status === "ok" ? "Running" : USE_LIVE ? "Offline" : "Mock"}</span>
                <span className="text-slate-600">:{" "}{USE_LIVE ? "8000" : "3000"}</span>
              </span>
            </Field>
            <Field label="SSE Stream">
              <span className="flex items-center gap-1.5 text-xs">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400"></span>
                <span className="text-slate-300">Connected</span>
                <span className="text-slate-600">/ stream</span>
              </span>
            </Field>
            <Field label="MCP Task">
              <span className="text-xs text-slate-500">5 / 5 min</span>
            </Field>
          </div>
        )}

        {activeTab === "Storage" && (
          <div className="space-y-0">
            <Field label="Database File">
              <span className="text-xs text-slate-400 font-mono">synapse.db</span>
            </Field>
            <Field label="Total Nodes">
              <span className="text-xs text-slate-300">{graphSummary?.total_nodes ?? "~"}</span>
            </Field>
            <Field label="Total Edges">
              <span className="text-xs text-slate-300">{graphSummary?.total_edges ?? "~"}</span>
            </Field>
            <Field label="Tables">
              <span className="text-xs text-slate-400">nodes, edges, operations</span>
            </Field>
            <div className="pt-3">
              <button className="text-xs text-slate-400 border border-slate-700/60 rounded-lg px-3 py-1.5 hover:text-slate-200 hover:border-slate-600 transition-colors">
                View Schema &#8594;
              </button>
            </div>
          </div>
        )}

        {activeTab === "Repository" && (
          <div className="space-y-0">
            <Field label="Default Branch">
              <input value={defaultBranch} onChange={(e) => setDefaultBranch(e.target.value)}
                className="bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-300 outline-none w-28 font-mono" />
            </Field>
            <Field label="Workspace Path">
              <div className="flex items-center gap-2">
                <input value={workspacePath} onChange={(e) => setWorkspacePath(e.target.value)}
                  className="bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-300 outline-none w-36 font-mono" />
                <button className="text-[10px] text-slate-400 border border-slate-700/60 rounded px-2 py-1 hover:text-slate-200">Browse</button>
              </div>
            </Field>
            <Field label="Auto DB Migration"><Toggle value={autoMigrate} onChange={setAutoMigrate} /></Field>
            <Field label="Enable Conflict Detection"><Toggle value={conflictDetect} onChange={setConflictDetect} /></Field>
            <Field label="Enable SSE Events"><Toggle value={sseEnabled} onChange={setSseEnabled} /></Field>
          </div>
        )}

        {activeTab === "Approval" && (
          <div className="space-y-0">
            <Field label="Default approval mode">
              <select className="bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1 text-xs text-slate-300 outline-none">
                <option>Manual (human required)</option>
                <option>Auto-approve low risk</option>
                <option>Auto-deny all</option>
              </select>
            </Field>
            <Field label="Conflict auto-deny">
              <Toggle value={true} onChange={() => {}} />
            </Field>
          </div>
        )}
      </div>

      {/* Footer buttons */}
      <div className="flex justify-end gap-3">
        <button className="text-xs text-slate-400 border border-slate-700/60 rounded-lg px-4 py-2 hover:text-slate-200 hover:border-slate-600 transition-colors">
          Reset to Default
        </button>
        <button className="text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 font-bold transition-colors">
          Save Changes
        </button>
      </div>
    </div>
  );
}
