import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState } from "react";

/** Sidecar status returned by invoke_sidecar_status */
interface SidecarStatus {
  running: boolean;
  port: number;
  base_url: string;
  crash_restarts: number;
}

/** Generic JSON value type matching serde_json::Value */
type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

/** Query request parameters */
interface QueryRequest {
  query: string;
  scope_id?: string;
  stream?: boolean;
}

/** Import request parameters — 对齐 Python remnant_core.models.ImportRequest */
interface ImportRequest {
  deceased_profile_id: string;
  file_path: string;
  file_type: string;
  scope_id?: string;
  encoding?: string;
  metadata?: Record<string, unknown>;
}

/** Profile resolve request parameters */
interface ProfileResolveRequest {
  profile_name: string;
}

/** Scope create request parameters — 对齐 Python remnant_core.models.ScopeCreateRequest */
interface ScopeCreateRequest {
  deceased_profile_id: string;
  scope_name: string;
  relationship_type: string; // child / spouse / sibling / parent / friend / colleague / other
  scope_description?: string;
}

/** Scope delete request parameters */
interface ScopeDeleteRequest {
  scope_id: string;
}

/** Safety evaluate request parameters */
interface SafetyEvaluateRequest {
  scope_id: string;
}

/** Safety policy get request parameters */
interface SafetyPolicyGetRequest {
  scope_id: string;
}

/** Safety policy update request parameters */
interface SafetyPolicyUpdateRequest {
  scope_id: string;
  max_session_minutes?: number;
  max_sessions_daily?: number;
  late_night_start?: string;
  late_night_end?: string;
  max_late_night_sessions?: number;
  dependency_threshold?: number;
  farewell_refusal_limit?: number;
  cooldown_minutes?: number;
  hard_break_enabled?: boolean;
  escalate_on_crisis?: boolean;
}

/** Safety events request parameters */
interface SafetyEventsRequest {
  scope_id: string;
  days?: number;
}

/** Data destroy request parameters */
interface DataDestroyRequest {
  scope_id: string;
  confirm?: boolean;
}

/** Evidence trace inspection request parameters */
interface EvidenceTraceRequest {
  trace_id: string;
}

/**
 * Custom hook for communicating with the Python sidecar via Tauri IPC.
 *
 * Provides typed wrappers for all sidecar API commands and automatically
 * manages SSE streaming event listeners for query responses.
 */
function useSidecar() {
  const [status, setStatus] = useState<SidecarStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const unlistenRefs = useRef<UnlistenFn[]>([]);

  /** Get sidecar health (re-export for convenience) */
  const checkHealth = useCallback(async (): Promise<boolean> => {
    try {
      const healthy = await invoke<boolean>("invoke_health_check");
      return healthy;
    } catch (_e) {
      return false;
    }
  }, []);

  /** Refresh sidecar status */
  const refreshStatus = useCallback(async (): Promise<void> => {
    try {
      const result = await invoke<SidecarStatus>("invoke_sidecar_status");
      setStatus(result);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  /** Send a query to the sidecar */
  const query = useCallback(
    async (params: QueryRequest): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_query", {
          request: params,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Import data into the sidecar */
  const importData = useCallback(
    async (params: ImportRequest): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_import", {
          request: params,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Resolve a user-facing profile name into the internal deceased_profile ID */
  const resolveProfile = useCallback(
    async (params: ProfileResolveRequest): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_profile_resolve", {
          request: params,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Create a new scope */
  const createScope = useCallback(
    async (params: ScopeCreateRequest): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_scope_create", {
          request: params,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Delete a scope */
  const deleteScope = useCallback(
    async (params: ScopeDeleteRequest): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_scope_delete", {
          request: params,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Evaluate safety for a scope */
  const evaluateSafety = useCallback(
    async (params: SafetyEvaluateRequest): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_safety_evaluate", {
          request: params,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Get safety policy for a scope */
  const getSafetyPolicy = useCallback(
    async (scopeId: string): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_safety_policy_get", {
          request: { scope_id: scopeId },
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Update safety policy for a scope */
  const updateSafetyPolicy = useCallback(
    async (
      scopeId: string,
      policy: Record<string, unknown>
    ): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_safety_policy_update", {
          request: {
            scope_id: scopeId,
            max_session_minutes: policy.max_session_minutes as number | undefined,
            max_sessions_daily: policy.max_sessions_daily as number | undefined,
            late_night_start: policy.late_night_start as string | undefined,
            late_night_end: policy.late_night_end as string | undefined,
            max_late_night_sessions: policy.max_late_night_sessions as number | undefined,
            dependency_threshold: policy.dependency_threshold as number | undefined,
            farewell_refusal_limit: policy.farewell_refusal_limit as number | undefined,
            cooldown_minutes: policy.cooldown_minutes as number | undefined,
            hard_break_enabled: policy.hard_break_enabled as boolean | undefined,
            escalate_on_crisis: policy.escalate_on_crisis as boolean | undefined,
          },
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Get safety events for a scope */
  const getSafetyEvents = useCallback(
    async (scopeId: string, days: number = 7): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_safety_events", {
          request: { scope_id: scopeId, days },
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Destroy data for a scope */
  const destroyData = useCallback(
    async (params: DataDestroyRequest): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_data_destroy", {
          request: params,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Inspect evidence for a retrieval trace */
  const getEvidenceTrace = useCallback(
    async (traceId: string): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_evidence_trace", {
          request: { trace_id: traceId },
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Listen to SSE query streaming events */
  const listenQueryStream = useCallback(
    (
      onChunk: (data: string) => void,
      onError: (err: string) => void,
      onDone: () => void
    ): void => {
      const setup = async (): Promise<void> => {
        const chunkUnlisten = await listen<string>(
          "sidecar:query:chunk",
          (event) => {
            onChunk(event.payload);
          }
        );
        const errorUnlisten = await listen<string>(
          "sidecar:query:error",
          (event) => {
            onError(event.payload);
          }
        );
        const doneUnlisten = await listen<string>(
          "sidecar:query:done",
          () => {
            onDone();
          }
        );
        unlistenRefs.current = [chunkUnlisten, errorUnlisten, doneUnlisten];
      };
      setup();
    },
    []
  );

  /** Clean up event listeners on unmount */
  useEffect(() => {
    return () => {
      unlistenRefs.current.forEach((unlisten) => unlisten());
      unlistenRefs.current = [];
    };
  }, []);

  /** List all scopes for a deceased profile */
  const listScopes = useCallback(
    async (deceasedProfileId: string): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_scope_list", {
          deceasedProfileId,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Get scope detail by ID */
  const getScopeDetail = useCallback(
    async (scopeId: string): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_scope_detail", {
          scopeId,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Get scope permissions */
  const getScopePermissions = useCallback(
    async (scopeId: string): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_scope_permissions", {
          scopeId,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Set a single permission for a scope */
  const setScopePermission = useCallback(
    async (
      scopeId: string,
      permissionKey: string,
      permissionValue: string
    ): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_scope_set_permission", {
          scopeId,
          permissionKey,
          permissionValue,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Get chunk visibility for a scope */
  const getScopeVisibility = useCallback(
    async (scopeId: string): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>("invoke_scope_visibility", {
          scopeId,
        });
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /** Upgrade chunk visibility */
  const upgradeScopeVisibility = useCallback(
    async (
      scopeId: string,
      chunkId: string,
      targetVisibility: string
    ): Promise<JsonValue> => {
      setLoading(true);
      setError(null);
      try {
        const result = await invoke<JsonValue>(
          "invoke_scope_visibility_upgrade",
          { scopeId, chunkId, targetVisibility }
        );
        return result;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        throw new Error(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  return {
    status,
    loading,
    error,
    checkHealth,
    refreshStatus,
    query,
    importData,
    resolveProfile,
    createScope,
    deleteScope,
    evaluateSafety,
    getSafetyPolicy,
    updateSafetyPolicy,
    getSafetyEvents,
    destroyData,
    getEvidenceTrace,
    listenQueryStream,
    listScopes,
    getScopeDetail,
    getScopePermissions,
    setScopePermission,
    getScopeVisibility,
    upgradeScopeVisibility,
  };
}

export default useSidecar;
export type {
  SidecarStatus,
  JsonValue,
  QueryRequest,
  ImportRequest,
  ProfileResolveRequest,
  ScopeCreateRequest,
  ScopeDeleteRequest,
  SafetyEvaluateRequest,
  SafetyPolicyGetRequest,
  SafetyPolicyUpdateRequest,
  SafetyEventsRequest,
  DataDestroyRequest,
  EvidenceTraceRequest,
};
