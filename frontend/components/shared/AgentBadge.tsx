// components/shared/AgentBadge.tsx
// Reusable agent identifier badge
// FE-1 @nabilfauzandafa

type Agent = "guardian" | "cortex" | "review" | string;

interface Props {
  agent: Agent;
  showDot?: boolean;
}

const STYLES: Record<string, string> = {
  guardian: "text-blue-400",
  cortex:   "text-purple-400",
  review:   "text-slate-300",
};

const DOTS: Record<string, string> = {
  guardian: "bg-blue-400",
  cortex:   "bg-purple-400",
  review:   "bg-slate-400",
};

export default function AgentBadge({ agent, showDot = true }: Props) {
  const key = agent.toLowerCase();
  return (
    <span className={`flex items-center gap-1 text-xs font-medium ${STYLES[key] ?? "text-slate-400"}`}>
      {showDot && (
        <span className={`w-1.5 h-1.5 rounded-full inline-block ${DOTS[key] ?? "bg-slate-400"}`} />
      )}
      {agent.charAt(0).toUpperCase() + agent.slice(1)}
    </span>
  );
}
