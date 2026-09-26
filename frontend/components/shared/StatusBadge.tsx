// components/shared/StatusBadge.tsx
// Reusable operation status badge
// FE-1 @nabilfauzandafa

type Status = "idle" | "pending" | "approved" | "executing" | "verified" | "failed" | "rolled_back" | "denied";

interface Props {
  status: Status;
  size?: "sm" | "md";
}

const STYLES: Record<string, string> = {
  pending:     "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  approved:    "bg-blue-500/20 text-blue-400 border border-blue-500/30",
  executing:   "bg-orange-500/20 text-orange-400 border border-orange-500/30",
  verified:    "bg-green-500/20 text-green-400 border border-green-500/30",
  failed:      "bg-red-500/20 text-red-400 border border-red-500/30",
  rolled_back: "bg-red-500/20 text-red-300 border border-red-400/30",
  denied:      "bg-slate-600/40 text-slate-400 border border-slate-600/40",
  idle:        "bg-slate-700/50 text-slate-500 border border-slate-700",
};

export default function StatusBadge({ status, size = "sm" }: Props) {
  const base = size === "md" ? "text-xs px-2.5 py-1" : "text-[10px] px-2 py-0.5";
  return (
    <span className={`${base} rounded-full font-semibold ${STYLES[status] ?? STYLES.idle}`}>
      {status.replace("_", " ").toUpperCase()}
    </span>
  );
}
