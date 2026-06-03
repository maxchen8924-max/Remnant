use crate::sidecar::SidecarState;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};

/// Generic error response from the sidecar.
#[derive(Debug, Serialize, Deserialize)]
#[allow(dead_code)]
pub struct SidecarError {
    pub error: String,
    pub code: Option<String>,
}

/// Query request body matching the Python sidecar API.
#[derive(Debug, Serialize, Deserialize)]
pub struct QueryRequest {
    pub query: String,
    pub scope_id: Option<String>,
    #[serde(default)]
    pub stream: bool,
}

/// Import request body — 对齐 Python remnant_core.models.ImportRequest。
#[derive(Debug, Serialize, Deserialize)]
pub struct ImportRequest {
    pub deceased_profile_id: String,
    pub file_path: String,
    pub file_type: String,
    pub scope_id: Option<String>,
    #[serde(default = "default_encoding")]
    pub encoding: String,
    #[serde(default)]
    pub metadata: serde_json::Value,
}

fn default_encoding() -> String {
    "utf-8".to_string()
}

/// Scope create request body — 对齐 Python remnant_core.models.ScopeCreateRequest。
#[derive(Debug, Serialize, Deserialize)]
pub struct ScopeCreateRequest {
    pub deceased_profile_id: String,
    pub scope_name: String,
    pub relationship_type: String, // child / spouse / sibling / parent / friend / colleague / other
    pub scope_description: Option<String>,
}

/// Scope delete request body.
#[derive(Debug, Serialize, Deserialize)]
pub struct ScopeDeleteRequest {
    pub scope_id: String,
}

/// Safety evaluate request body.
#[derive(Debug, Serialize, Deserialize)]
pub struct SafetyEvaluateRequest {
    pub scope_id: String,
    pub session_id: String,
    pub current_query: String,
    #[serde(default)]
    pub session_stats: Option<serde_json::Value>,
}

/// Data destroy request body.
#[derive(Debug, Serialize, Deserialize)]
pub struct DataDestroyRequest {
    pub scope_id: String,
    #[serde(default)]
    pub confirm: bool,
}

/// Safety policy get request body.
#[derive(Debug, Serialize, Deserialize)]
pub struct SafetyPolicyGetRequest {
    pub scope_id: String,
}

/// Safety policy update request body.
#[derive(Debug, Serialize, Deserialize)]
pub struct SafetyPolicyUpdateRequest {
    pub scope_id: String,
    pub max_session_minutes: Option<i32>,
    pub max_sessions_daily: Option<i32>,
    pub late_night_start: Option<String>,
    pub late_night_end: Option<String>,
    pub max_late_night_sessions: Option<i32>,
    pub dependency_threshold: Option<f64>,
    pub farewell_refusal_limit: Option<i32>,
    pub cooldown_minutes: Option<i32>,
    pub hard_break_enabled: Option<bool>,
    pub escalate_on_crisis: Option<bool>,
}

/// Safety events request body.
#[derive(Debug, Serialize, Deserialize)]
pub struct SafetyEventsRequest {
    pub scope_id: String,
    pub days: Option<i32>,
}

/// Invokes the query endpoint on the Python sidecar.
///
/// For streaming queries, the response is emitted as Tauri events chunk by chunk.
/// For non-streaming queries, the full JSON response is returned directly.
#[tauri::command]
pub async fn invoke_query(
    state: State<'_, SidecarState>,
    app: AppHandle,
    request: QueryRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager); // Release lock before making HTTP request

    let url = format!("{}/api/v1/query", base_url);

    if request.stream {
        // SSE streaming mode: stream response chunks and emit them as Tauri events
        let response = client
            .post(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Accept", "text/event-stream")
            .json(&request)
            .send()
            .await
            .map_err(|e| format!("Query request failed: {}", e))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(format!("Query failed ({}): {}", status, body));
        }

        // Use Tauri event system to stream SSE chunks to the frontend
        use futures_util::StreamExt;
        let mut stream = response.bytes_stream();
        while let Some(chunk_result) = stream.next().await {
            match chunk_result {
                Ok(chunk) => {
                    let text = String::from_utf8_lossy(&chunk).to_string();
                    let _ = app.emit("sidecar:query:chunk", &text);
                }
                Err(e) => {
                    let _ = app.emit("sidecar:query:error", format!("Stream error: {}", e));
                    break;
                }
            }
        }

        let _ = app.emit("sidecar:query:done", "stream_complete");

        Ok(serde_json::json!({"status": "streaming", "event": "sidecar:query:chunk"}))
    } else {
        // Non-streaming mode: return full JSON response
        let response = client
            .post(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Content-Type", "application/json")
            .json(&request)
            .send()
            .await
            .map_err(|e| format!("Query request failed: {}", e))?;

        let status = response.status();
        let body = response
            .text()
            .await
            .map_err(|e| format!("Failed to read response: {}", e))?;

        if !status.is_success() {
            return Err(format!("Query failed ({}): {}", status, body));
        }

        let json: serde_json::Value =
            serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

        Ok(json)
    }
}

/// Invokes the import endpoint on the Python sidecar.
#[tauri::command]
pub async fn invoke_import(
    state: State<'_, SidecarState>,
    request: ImportRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!("{}/api/v1/import", base_url);

    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("Import request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Import failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Invokes the scope create endpoint on the Python sidecar.
#[tauri::command]
pub async fn invoke_scope_create(
    state: State<'_, SidecarState>,
    request: ScopeCreateRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!("{}/api/v1/scope/create", base_url);

    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("Scope create request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Scope create failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Invokes the scope delete endpoint on the Python sidecar.
#[tauri::command]
pub async fn invoke_scope_delete(
    state: State<'_, SidecarState>,
    request: ScopeDeleteRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!("{}/api/v1/scope/delete", base_url);

    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("Scope delete request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Scope delete failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Invokes the safety evaluate endpoint on the Python sidecar.
#[tauri::command]
pub async fn invoke_safety_evaluate(
    state: State<'_, SidecarState>,
    request: SafetyEvaluateRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!("{}/api/v1/safety/evaluate", base_url);

    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("Safety evaluate request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Safety evaluate failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Invokes the data destroy endpoint on the Python sidecar.
#[tauri::command]
pub async fn invoke_data_destroy(
    state: State<'_, SidecarState>,
    request: DataDestroyRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!("{}/api/v1/data/destroy", base_url);

    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("Data destroy request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Data destroy failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Lists all scopes for a given deceased profile.
#[tauri::command]
pub async fn invoke_scope_list(
    state: State<'_, SidecarState>,
    deceased_profile_id: String,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!(
        "{}/api/v1/scope/list/{}",
        base_url, deceased_profile_id
    );

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .send()
        .await
        .map_err(|e| format!("Scope list request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Scope list failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Gets scope detail by ID.
#[tauri::command]
pub async fn invoke_scope_detail(
    state: State<'_, SidecarState>,
    scope_id: String,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!("{}/api/v1/scope/{}", base_url, scope_id);

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .send()
        .await
        .map_err(|e| format!("Scope detail request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Scope detail failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Gets scope permissions by ID.
#[tauri::command]
pub async fn invoke_scope_permissions(
    state: State<'_, SidecarState>,
    scope_id: String,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!(
        "{}/api/v1/scope/{}/permissions",
        base_url, scope_id
    );

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .send()
        .await
        .map_err(|e| format!("Scope permissions request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!(
            "Scope permissions failed ({}): {}",
            status, body
        ));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Updates a single permission for a scope.
#[tauri::command]
pub async fn invoke_scope_set_permission(
    state: State<'_, SidecarState>,
    scope_id: String,
    permission_key: String,
    permission_value: String,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!(
        "{}/api/v1/scope/{}/permissions/{}",
        base_url, scope_id, permission_key
    );

    let response = client
        .put(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .query(&[("permission_value", &permission_value)])
        .send()
        .await
        .map_err(|e| format!("Set permission request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Set permission failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Gets chunk visibility for a scope.
#[tauri::command]
pub async fn invoke_scope_visibility(
    state: State<'_, SidecarState>,
    scope_id: String,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!(
        "{}/api/v1/scope/{}/visibility",
        base_url, scope_id
    );

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .send()
        .await
        .map_err(|e| format!("Scope visibility request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!(
            "Scope visibility failed ({}): {}",
            status, body
        ));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Upgrades chunk visibility for a scope.
#[tauri::command]
pub async fn invoke_scope_visibility_upgrade(
    state: State<'_, SidecarState>,
    scope_id: String,
    chunk_id: String,
    target_visibility: String,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!(
        "{}/api/v1/scope/{}/visibility/upgrade",
        base_url, scope_id
    );

    let body = serde_json::json!({
        "chunk_id": chunk_id,
        "target_visibility": target_visibility,
    });

    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Visibility upgrade request failed: {}", e))?;

    let status = response.status();
    let resp_body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!(
            "Visibility upgrade failed ({}): {}",
            status, resp_body
        ));
    }

    let json: serde_json::Value =
        serde_json::from_str(&resp_body).unwrap_or(serde_json::json!({ "raw": resp_body }));

    Ok(json)
}

/// Checks the health of the Python sidecar.
#[tauri::command]
pub async fn invoke_health_check(state: State<'_, SidecarState>) -> Result<bool, String> {
    let manager = state.lock().await;
    Ok(manager.health_check().await)
}

/// Gets the safety policy for a scope.
#[tauri::command]
pub async fn invoke_safety_policy_get(
    state: State<'_, SidecarState>,
    request: SafetyPolicyGetRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!(
        "{}/api/v1/safety/policy/{}",
        base_url, request.scope_id
    );

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .send()
        .await
        .map_err(|e| format!("Safety policy get request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Safety policy get failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Updates the safety policy for a scope.
#[tauri::command]
pub async fn invoke_safety_policy_update(
    state: State<'_, SidecarState>,
    request: SafetyPolicyUpdateRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let url = format!(
        "{}/api/v1/safety/policy/{}",
        base_url, request.scope_id
    );

    // Build the update payload excluding scope_id
    let mut payload = serde_json::Map::new();
    if let Some(v) = &request.max_session_minutes {
        payload.insert("max_session_minutes".to_string(), serde_json::Value::Number((*v).into()));
    }
    if let Some(v) = &request.max_sessions_daily {
        payload.insert("max_sessions_daily".to_string(), serde_json::Value::Number((*v).into()));
    }
    if let Some(v) = &request.late_night_start {
        payload.insert("late_night_start".to_string(), serde_json::Value::String(v.clone()));
    }
    if let Some(v) = &request.late_night_end {
        payload.insert("late_night_end".to_string(), serde_json::Value::String(v.clone()));
    }
    if let Some(v) = &request.max_late_night_sessions {
        payload.insert("max_late_night_sessions".to_string(), serde_json::Value::Number((*v).into()));
    }
    if let Some(v) = &request.dependency_threshold {
        payload.insert("dependency_threshold".to_string(), serde_json::Value::from(*v));
    }
    if let Some(v) = &request.farewell_refusal_limit {
        payload.insert("farewell_refusal_limit".to_string(), serde_json::Value::Number((*v).into()));
    }
    if let Some(v) = &request.cooldown_minutes {
        payload.insert("cooldown_minutes".to_string(), serde_json::Value::Number((*v).into()));
    }
    if let Some(v) = &request.hard_break_enabled {
        payload.insert("hard_break_enabled".to_string(), serde_json::Value::Bool(*v));
    }
    if let Some(v) = &request.escalate_on_crisis {
        payload.insert("escalate_on_crisis".to_string(), serde_json::Value::Bool(*v));
    }

    let response = client
        .put(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .json(&serde_json::Value::Object(payload))
        .send()
        .await
        .map_err(|e| format!("Safety policy update request failed: {}", e))?;

    let status = response.status();
    let resp_body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!(
            "Safety policy update failed ({}): {}",
            status, resp_body
        ));
    }

    let json: serde_json::Value =
        serde_json::from_str(&resp_body).unwrap_or(serde_json::json!({ "raw": resp_body }));

    Ok(json)
}

/// Gets safety events for a scope.
#[tauri::command]
pub async fn invoke_safety_events(
    state: State<'_, SidecarState>,
    request: SafetyEventsRequest,
) -> Result<serde_json::Value, String> {
    let manager = state.lock().await;
    let base_url = manager.get_base_url();
    let token = manager.get_auth_token().to_string();
    let client = manager.get_http_client().clone();
    drop(manager);

    let days = request.days.unwrap_or(7);
    let url = format!(
        "{}/api/v1/safety/events/{}?days={}",
        base_url, request.scope_id, days
    );

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("Content-Type", "application/json")
        .send()
        .await
        .map_err(|e| format!("Safety events request failed: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if !status.is_success() {
        return Err(format!("Safety events failed ({}): {}", status, body));
    }

    let json: serde_json::Value =
        serde_json::from_str(&body).unwrap_or(serde_json::json!({ "raw": body }));

    Ok(json)
}

/// Checks whether the sidecar process is currently running.
#[tauri::command]
pub async fn invoke_sidecar_status(state: State<'_, SidecarState>) -> Result<serde_json::Value, String> {
    let mut manager = state.lock().await;
    Ok(serde_json::json!({
        "running": manager.is_running(),
        "port": manager.get_port(),
        "base_url": manager.get_base_url(),
        "python_bin": manager.get_python_bin(),
        "crash_restarts": manager.get_crash_restarts()
    }))
}
