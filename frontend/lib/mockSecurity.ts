// lib/mockSecurity.ts
// Mock data untuk halaman Security (mode MOCK)
// FE-1 @nabilfauzandafa

export interface SecurityOverview {
  total_checks: number;
  violations: number;
  blocked_ops: number;
  rules_active: number;
  is_healthy: boolean;
}

export interface SecurityRule {
  name: string;
  description: string;
  enabled: boolean;
}

export interface AdversarialTest {
  name: string;
  passed: boolean;
}

export interface ConflictCheck {
  opId: string;
  description: string;
  timestamp: string;
}

export interface RollbackVerification {
  total: number;
  successful: number;
  recent: { opId: string; timestamp: string; success: boolean }[];
}

export interface SecurityEvent {
  timestamp: string;
  event: string;
  detail: string;
  severity: "blocked" | "warning" | "info" | "ok";
}

export const MOCK_SECURITY_OVERVIEW: SecurityOverview = {
  total_checks: 12,
  violations: 1,
  blocked_ops: 2,
  rules_active: 8,
  is_healthy: true,
};

export const MOCK_SECURITY_RULES: SecurityRule[] = [
  { name: "Dangerous operation detection",          description: "Block ops flagged as destructive",        enabled: true },
  { name: "Conflict detection (overlapping resources)", description: "Deny concurrent ops on same target",  enabled: true },
  { name: "Reversibility requirement",              description: "Require snapshot before execution",       enabled: true },
  { name: "Unknown operation fail-closed",           description: "Unknown tool_names require approval",     enabled: true },
  { name: "Blast radius classification",            description: "Auto-classify ops by impact scope",       enabled: true },
];

export const MOCK_ADVERSARIAL_TESTS: AdversarialTest[] = [
  { name: "Prompt injection",           passed: true },
  { name: "Malicious file operation",   passed: true },
  { name: "Privilege escalation",       passed: true },
  { name: "Bypass approval",            passed: true },
  { name: "Data exfiltration",          passed: false },
];

export const MOCK_CONFLICT_CHECKS: ConflictCheck[] = [
  { opId: "op::migrate-priority", description: "Target overlap: synapse.db::nodes", timestamp: "08:42" },
];

export const MOCK_ROLLBACK_VERIFICATION: RollbackVerification = {
  total: 3,
  successful: 2,
  recent: [
    { opId: "op::migrate-broken",   timestamp: "08:45", success: true },
    { opId: "op::migrate-priority", timestamp: "07:15", success: true },
    { opId: "op::migrate-tag",      timestamp: "06:33", success: false },
  ],
};

export const MOCK_SECURITY_EVENTS: SecurityEvent[] = [
  { timestamp: "08:42", event: "operation_blocked",    detail: "db/migration — conflict detected",      severity: "blocked" },
  { timestamp: "07:15", event: "rule_violation",       detail: "Unknown tool_name detected",             severity: "warning" },
  { timestamp: "06:45", event: "rollback_executed",    detail: "op::migrate-broken rolled back OK",      severity: "ok" },
  { timestamp: "06:33", event: "operation_blocked",    detail: "service.restart — fail-closed policy",   severity: "blocked" },
];
