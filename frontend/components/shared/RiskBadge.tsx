// components/shared/RiskBadge.tsx
// Reusable risk level badge
// FE-1 @nabilfauzandafa

interface Props {
  level: "high" | "medium" | "low" | "unknown";
  size?: "sm" | "md";
}

const STYLES: Record<string, string> = {
  high:    "bg-red-500/20 text-red-400 border border-red-500/30",
  medium:  "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  low:     "bg-green-500/20 text-green-400 border border-green-500/30",
  unknown: "bg-slate-700 text-slate-400 border border-slate-600",
};

const LABELS: Record<string, string> = {
  high: "High Risk", medium: "Medium Risk", low: "Low Risk", unknown: "Unknown",
};

export default function RiskBadge({ level, size = "sm" }: Props) {
  const base = size === "md" ? "text-xs px-2.5 py-1" : "text-[10px] px-2 py-0.5";
  return (
    <span className={`${base} rounded-full font-semibold ${STYLES[level] ?? STYLES.unknown}`}>
      {LABELS[level] ?? level}
    </span>
  );
}
