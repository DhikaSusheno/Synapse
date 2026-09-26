"use client";

// components/TopNavbar.tsx
// Top navigation bar sesuai prototype Synapse
// FE-1 @nabilfauzandafa

interface Props {
  isLive: boolean;
  nodeCount: number;
  edgeCount: number;
}

export default function TopNavbar({ isLive, nodeCount, edgeCount }: Props) {
  return (
    <header className="h-12 shrink-0 flex items-center gap-3 px-4 border-b border-slate-800/60 bg-[#0d1117]">
      {/* Repo info */}
      <div className="flex items-center gap-2">
        <svg className="w-4 h-4 text-slate-400" fill="currentColor" viewBox="0 0 16 16">
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
        </svg>
        <span className="text-sm text-slate-300 font-medium">DhikaSusheno/Synapse</span>
        <span className="text-xs px-1.5 py-0.5 rounded border border-slate-700 text-slate-500">public</span>
      </div>

      <div className="w-px h-4 bg-slate-700 mx-1" />

      {/* Branch */}
      <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/60 border border-slate-700/60 text-xs text-slate-300">
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        main
        <svg className="w-3 h-3 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Live Connection */}
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${isLive ? "bg-green-400" : "bg-yellow-400"}`} />
        <div>
          <div className="text-xs font-medium text-white leading-none">
            {isLive ? "Live Connection" : "Mock Mode"}
          </div>
          <div className="text-[10px] text-slate-500 leading-none mt-0.5">
            {isLive ? "SQLite &#183; FastAPI &#183; SSE" : "Simulation active"}
          </div>
        </div>
      </div>

      <div className="w-px h-4 bg-slate-700 mx-1" />

      {/* Agents */}
      <div className="flex items-center gap-2">
        <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <div>
          <div className="text-xs font-medium text-white leading-none">3 Agents</div>
          <div className="text-[10px] text-slate-500 leading-none mt-0.5">
            <span className="text-blue-400">&#183; Guardian</span>
            <span className="text-purple-400"> &#183; Cortex</span>
            <span className="text-slate-400"> &#183; Review</span>
          </div>
        </div>
      </div>

      <div className="w-px h-4 bg-slate-700 mx-1" />

      {/* Search */}
      <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/60 w-52">
        <svg className="w-3.5 h-3.5 text-slate-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <span className="text-xs text-slate-500 flex-1">Search files, nodes, or operations...</span>
        <kbd className="text-[10px] text-slate-600 font-mono">&#8984;K</kbd>
      </div>

      {/* Settings icon */}
      <button className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </button>
    </header>
  );
}
