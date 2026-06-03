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

/** Data destroy request parameters */
interface DataDestroyRequest {
  scope_id: string;
  confirm?: boolean;
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
    createScope,
    deleteScope,
    evaluateSafety,
    destroyData,
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
  ScopeCreateRequest,
  ScopeDeleteRequest,
  SafetyEvaluateRequest,
  DataDestroyRequest,
};