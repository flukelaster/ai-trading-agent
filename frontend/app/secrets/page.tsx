"use client";

import { useEffect, useState, useCallback } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  getVaultStatus,
  getSecrets,
  getSecret,
  upsertSecret,
  deleteSecret,
  testSecret,
  getSecretHistory,
} from "@/lib/api";

interface SecretItem {
  key: string;
  category: string;
  description: string | null;
  is_required: boolean;
  has_value: boolean;
  last_rotated_at: string | null;
  created_at: string;
}

interface AuditEntry {
  id: number;
  action: string;
  actor: string;
  detail: Record<string, unknown> | null;
  success: boolean;
  created_at: string;
}

const CATEGORIES = ["auth", "broker", "notification", "macro", "general"];

export default function SecretsPage() {
  const [vaultAvailable, setVaultAvailable] = useState(true);
  const [secrets, setSecrets] = useState<SecretItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Edit dialog state
  const [editKey, setEditKey] = useState("");
  const [editValue, setEditValue] = useState("");
  const [editCategory, setEditCategory] = useState("general");
  const [editDescription, setEditDescription] = useState("");
  const [editRequired, setEditRequired] = useState(false);
  const [editMode, setEditMode] = useState<"create" | "update">("create");
  const [showEdit, setShowEdit] = useState(false);
  const [saving, setSaving] = useState(false);

  // Test state
  const [testingKey, setTestingKey] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { status: string; message: string; latency_ms?: number }>>({});

  // History state
  const [historyKey, setHistoryKey] = useState<string | null>(null);
  const [historyEntries, setHistoryEntries] = useState<AuditEntry[]>([]);

  // Masked values cache
  const [maskedValues, setMaskedValues] = useState<Record<string, string>>({});

  const fetchSecrets = useCallback(async () => {
    setLoading(true);
    try {
      const [vaultRes, secretsRes] = await Promise.all([
        getVaultStatus(),
        getSecrets(),
      ]);
      setVaultAvailable(vaultRes.data.available);
      setSecrets(secretsRes.data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSecrets();
  }, [fetchSecrets]);

  // Fetch masked value for a secret
  const fetchMasked = async (key: string) => {
    try {
      const res = await getSecret(key);
      setMaskedValues((prev) => ({ ...prev, [key]: res.data.masked_value }));
    } catch {
      setMaskedValues((prev) => ({ ...prev, [key]: "*** (error)" }));
    }
  };

  // Open edit dialog
  const openCreate = () => {
    setEditKey("");
    setEditValue("");
    setEditCategory("general");
    setEditDescription("");
    setEditRequired(false);
    setEditMode("create");
    setShowEdit(true);
  };

  const openEdit = (s: SecretItem) => {
    setEditKey(s.key);
    setEditValue("");
    setEditCategory(s.category);
    setEditDescription(s.description || "");
    setEditRequired(s.is_required);
    setEditMode("update");
    setShowEdit(true);
  };

  const handleSave = async () => {
    if (!editKey.trim() || !editValue.trim()) return;
    setSaving(true);
    try {
      await upsertSecret(editKey.trim(), {
        value: editValue,
        category: editCategory,
        description: editDescription || undefined,
        is_required: editRequired,
      });
      setShowEdit(false);
      await fetchSecrets();
    } catch {
      // error handled by interceptor
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (key: string) => {
    if (!confirm(`Delete secret "${key}"?`)) return;
    try {
      await deleteSecret(key);
      await fetchSecrets();
    } catch {
      // error handled by interceptor
    }
  };

  const handleTest = async (key: string) => {
    setTestingKey(key);
    setTestResults((prev) => ({ ...prev, [key]: { status: "testing", message: "Testing..." } }));
    try {
      const res = await testSecret(key);
      setTestResults((prev) => ({ ...prev, [key]: res.data }));
    } catch {
      setTestResults((prev) => ({ ...prev, [key]: { status: "error", message: "Test failed" } }));
    } finally {
      setTestingKey(null);
    }
  };

  const handleHistory = async (key: string) => {
    if (historyKey === key) {
      setHistoryKey(null);
      return;
    }
    setHistoryKey(key);
    try {
      const res = await getSecretHistory(key);
      setHistoryEntries(res.data);
    } catch {
      setHistoryEntries([]);
    }
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <PageHeader
        title="Secrets Vault"
        subtitle="Manage encrypted API keys and tokens"
      />

      {!vaultAvailable && (
        <div className="rounded-md bg-amber-500/10 border border-amber-500/30 p-4 text-sm text-amber-400">
          Vault is locked — set <code className="bg-amber-500/20 px-1 rounded">VAULT_MASTER_KEY</code> environment variable to manage secrets.
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={openCreate}
          disabled={!vaultAvailable}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          + Add Secret
        </button>
      </div>

      {loading ? (
        <div className="text-center text-muted-foreground py-8">Loading secrets...</div>
      ) : secrets.length === 0 ? (
        <div className="text-center text-muted-foreground py-8">No secrets configured yet.</div>
      ) : (
        <div className="space-y-3">
          {secrets.map((s) => (
            <div key={s.key} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono font-semibold text-sm">{s.key}</span>
                    {s.is_required && (
                      <span className="text-xs bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded">Required</span>
                    )}
                    <span className="text-xs bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">{s.category}</span>
                  </div>
                  {s.description && (
                    <p className="text-xs text-muted-foreground mb-1">{s.description}</p>
                  )}
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <span>
                      Value: {maskedValues[s.key] || (
                        <button
                          onClick={() => fetchMasked(s.key)}
                          className="text-primary hover:underline"
                          disabled={!vaultAvailable}
                        >
                          Show
                        </button>
                      )}
                    </span>
                    <span>Rotated: {formatDate(s.last_rotated_at)}</span>
                    {testResults[s.key] && (
                      <span className={testResults[s.key].status === "ok" ? "text-green-400" : testResults[s.key].status === "testing" ? "text-yellow-400" : "text-red-400"}>
                        {testResults[s.key].status === "ok" ? "Valid" : testResults[s.key].status === "testing" ? "Testing..." : testResults[s.key].message}
                        {testResults[s.key].latency_ms != null && ` (${testResults[s.key].latency_ms}ms)`}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => openEdit(s)}
                    disabled={!vaultAvailable}
                    className="text-xs px-2 py-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-50"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => handleTest(s.key)}
                    disabled={!vaultAvailable || testingKey === s.key}
                    className="text-xs px-2 py-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-50"
                  >
                    {testingKey === s.key ? "..." : "Test"}
                  </button>
                  <button
                    onClick={() => handleHistory(s.key)}
                    className="text-xs px-2 py-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                  >
                    History
                  </button>
                  <button
                    onClick={() => handleDelete(s.key)}
                    className="text-xs px-2 py-1 rounded hover:bg-accent text-red-400 hover:text-red-300"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {/* History panel */}
              {historyKey === s.key && (
                <div className="mt-3 pt-3 border-t border-border">
                  <h4 className="text-xs font-medium mb-2 text-muted-foreground">Audit History</h4>
                  {historyEntries.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No history entries.</p>
                  ) : (
                    <div className="space-y-1 max-h-48 overflow-y-auto">
                      {historyEntries.map((e) => (
                        <div key={e.id} className="flex items-center gap-3 text-xs">
                          <span className="text-muted-foreground w-32 shrink-0">{formatDate(e.created_at)}</span>
                          <span className={e.success ? "text-green-400" : "text-red-400"}>
                            {e.action}
                          </span>
                          <span className="text-muted-foreground truncate">
                            {e.detail ? JSON.stringify(e.detail) : ""}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Edit/Create Dialog */}
      {showEdit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card border border-border rounded-lg p-6 w-full max-w-md mx-4 space-y-4">
            <h3 className="text-lg font-semibold">
              {editMode === "create" ? "Add Secret" : `Edit: ${editKey}`}
            </h3>

            {editMode === "create" && (
              <div>
                <label className="block text-sm font-medium mb-1">Key</label>
                <input
                  type="text"
                  value={editKey}
                  onChange={(e) => setEditKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""))}
                  placeholder="e.g. CLAUDE_OAUTH_TOKEN"
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-medium mb-1">Value</label>
              <input
                type="password"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                placeholder={editMode === "update" ? "Enter new value" : "Secret value"}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Category</label>
              <select
                value={editCategory}
                onChange={(e) => setEditCategory(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Description</label>
              <input
                type="text"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder="Optional description"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="required"
                checked={editRequired}
                onChange={(e) => setEditRequired(e.target.checked)}
                className="rounded"
              />
              <label htmlFor="required" className="text-sm">Required for operation</label>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowEdit(false)}
                className="px-4 py-2 text-sm rounded-md hover:bg-accent"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !editKey.trim() || !editValue.trim()}
                className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
