"use client";
// components/pages/SecurityPage.tsx
// Halaman Security — sesuai design section 7
// FE-1 @nabilfauzandafa

import {
  MOCK_SECURITY_OVERVIEW, MOCK_SECURITY_RULES, MOCK_ADVERSARIAL_TESTS,
  MOCK_CONFLICT_CHECKS, MOCK_ROLLBACK_VERIFICATION, MOCK_SECURITY_EVENTS,
} from "@/lib/mockSecurity";

const SEVERITY_STYLES: Record<string, string> = {
  blocked: "text-red-400 bg-red-900/20",
  warning: "text-yellow-400 bg-yellow-900/20",
  ok:      "text-green-400 bg-green-900/20",
  info:    "text-slate-400 bg-slate-800/40",
};

export default function SecurityPage() {
  const overview  = MOCK_SECURITY_OVERVIEW;
  const rules     = MOCK_SECURITY_RULES;
  const tests     = MOCK_ADVERSARIAL_TESTS;
  const conflicts = MOCK_CONFLICT_CHECKS;
  const rollbacks = MOCK_ROLLBACK_VERIFICATION;
  const events    = MOCK_SECURITY_EVENTS;

  const passedTests = tests.filter((t) => t.passed).length;

  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Security</h1>
          <p className="text-sm text-slate-400 mt-0.5">Security audit and rule engine (rule-based / heuristic).</p>
        </div>
        <span className={`text-[10px] px-2.5 py-1 rounded-full font-bold border ${
          overview.is_healthy ? "bg-green-500/20 text-green-400 border-green-500/30" : "bg-red-500/20 text-red-400 border-red-500/30"
        }`}>
          &#9679; {overview.is_healthy ? "Healthy" : "Warning"}
        </span>
      </div>

      {/* Top row: 4 stat cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Checks",  value: overview.total_checks,  delta: null,    color: "text-white" },
          { label: "Violations",    value: overview.violations,     delta: "-75%",  color: "text-red-400" },
          { label: "Blocked Ops",   value: overview.blocked_ops,    delta: "+100%", color: "text-yellow-400" },
          { label: "Rules Active",  value: overview.rules_active,   delta: "100%",  color: "text-green-400" },
        ].map((stat) => (
          <div key={stat.label} className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4">
            <div className={`text-2xl font-bold ${stat.color}`}>{stat.value}</div>
            <div className="text-xs text-slate-400 mt-1">{stat.label}</div>
            {stat.delta && <div className="text-[10px] text-slate-600 mt-0.5">{stat.delta}</div>}
          </div>
        ))}
      </div>

      {/* Middle row: Rule Engine + Adversarial Tests + Conflict Checks */}
      <div className="grid grid-cols-3 gap-4">
        {/* Rule Engine */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div>
            <div className="text-sm font-semibold text-white">Rule Engine</div>
            <div className="text-[10px] text-slate-500">Static rules &amp; heuristics (not ML)</div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-slate-400">Policy</span>
            <span className="text-[10px] bg-red-500/20 text-red-400 border border-red-500/30 rounded-full px-2 py-0.5 font-semibold">Fail-closed (default)</span>
          </div>
          <div className="space-y-1.5">
            {rules.map((rule, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className={`shrink-0 mt-0.5 text-[10px] ${rule.enabled ? "text-green-400" : "text-slate-600"}`}>&#9679;</span>
                <div>
                  <div className="text-[10px] text-slate-300 font-medium">{rule.name}</div>
                  <div className="text-[9px] text-slate-600">{rule.description}</div>
                </div>
              </div>
            ))}
          </div>
          <button className="w-full text-[10px] text-slate-400 border border-slate-700/60 rounded-lg py-1.5 hover:text-slate-200 hover:border-slate-600 transition-colors">
            View Rules &#8594;
          </button>
        </div>

        {/* Adversarial Tests */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-sm font-semibold text-white">Adversarial Test Results</div>
              <div className="text-[10px] text-slate-500">Automated security test suite</div>
            </div>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
              passedTests === tests.length
                ? "bg-green-500/20 text-green-400 border-green-500/30"
                : "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
            }`}>
              {passedTests}/{tests.length} passed
            </span>
          </div>
          <div className="space-y-1.5">
            {tests.map((test, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className={`text-[10px] shrink-0 ${test.passed ? "text-green-400" : "text-red-400"}`}>
                  {test.passed ? "&#10003;" : "&#10007;"}
                </span>
                <span className="text-[10px] text-slate-300">{test.name}</span>
              </div>
            ))}
          </div>
          <button className="w-full text-[10px] text-slate-400 border border-slate-700/60 rounded-lg py-1.5 hover:text-slate-200 hover:border-slate-600 transition-colors">
            View Details &#8594;
          </button>
        </div>

        {/* Conflict Checks + Rollback Verification */}
        <div className="space-y-3">
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-white">Conflict Checks</span>
              <span className="text-[9px] bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded-full px-1.5 py-0.5 font-bold">
                {conflicts.length} today
              </span>
            </div>
            {conflicts.map((c, i) => (
              <div key={i} className="bg-slate-800/40 rounded-lg p-2 text-[10px]">
                <div className="text-slate-300 font-medium">{c.opId}</div>
                <div className="text-slate-500">{c.description}</div>
                <div className="text-slate-600">{c.timestamp}</div>
              </div>
            ))}
          </div>

          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-white">Rollback Verification</span>
              <span className="text-[9px] bg-green-500/20 text-green-400 border border-green-500/30 rounded-full px-1.5 py-0.5 font-bold">
                {rollbacks.successful}/{rollbacks.total} successful
              </span>
            </div>
            {rollbacks.recent.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px]">
                <span className={r.success ? "text-green-400" : "text-red-400"}>{r.success ? "&#10003;" : "&#10007;"}</span>
                <span className="text-slate-400">{r.timestamp}</span>
                <span className="text-slate-300 truncate">{r.opId.split("::")[1] ?? r.opId}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Security Event Feed */}
      <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
        <div className="text-sm font-semibold text-white">Security Event Feed</div>
        <div className="divide-y divide-slate-800/40">
          {events.map((ev, i) => (
            <div key={i} className="flex items-center gap-3 py-2">
              <span className="text-[10px] text-slate-600 font-mono w-12 shrink-0">{ev.timestamp}</span>
              <span className={`text-[10px] px-2 py-0.5 rounded font-semibold shrink-0 ${
                SEVERITY_STYLES[ev.severity] ?? SEVERITY_STYLES.info
              }`}>{ev.event.replace(/_/g, " ").toUpperCase()}</span>
              <span className="text-[10px] text-slate-400 flex-1">{ev.detail}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
