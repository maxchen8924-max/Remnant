use rand::Rng;
use reqwest::Client;
use std::sync::Arc;
use std::time::Duration;
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

/// Default port for the Python sidecar.
const DEFAULT_PORT: u16 = 18731;

/// Maximum number of health check retries before declaring sidecar unhealthy.
const HEALTH_CHECK_MAX_RETRIES: u32 = 15;

/// Interval between health check retries in seconds.
const HEALTH_CHECK_INTERVAL_SECS: u64 = 2;

/// Maximum number of crash restarts before giving up.
#[allow(dead_code)]
const MAX_CRASH_RESTARTS: u32 = 3;

/// Grace period (in seconds) after SIGTERM before sending SIGKILL.
const GRACEFUL_SHUTDOWN_SECS: u64 = 5;

/// Startup timeout for the sidecar in seconds.
const STARTUP_TIMEOUT_SECS: u64 = 30;

/// Manages the lifecycle of the Python sidecar process.
///
/// Based on the Remnant whitepaper Ch11 design:
/// - Port: 127.0.0.1:18731 (overridable via `REMNANT_SIDECAR_PORT` env)
/// - Health check: GET /health, up to 15 retries, 2s interval
/// - Startup timeout: 30s
/// - Crash restart: up to 3 times, then manual restart required
/// - Graceful shutdown: SIGTERM → wait 5s → SIGKILL
/// - Ephemeral token: randomly generated, passed to Python via env var
pub struct SidecarManager {
    /// Port the sidecar listens on.
    port: u16,
    /// Ephemeral auth token for sidecar communication.
    auth_token: String,
    /// The child process handle, if running.
    child: Option<Child>,
    /// Number of crash restarts attempted.
    crash_restarts: u32,
    /// HTTP client for health checks and API calls.
    http_client: Client,
}

impl SidecarManager {
    /// Creates a new SidecarManager instance with the configured port and a generated auth token.
    pub fn new() -> Self {
        let port = std::env::var("REMNANT_SIDECAR_PORT")
            .ok()
            .and_then(|v| v.parse::<u16>().ok())
            .unwrap_or(DEFAULT_PORT);

        let auth_token = generate_ephemeral_token();

        let http_client = Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .unwrap_or_else(|_| Client::new());

        Self {
            port,
            auth_token,
            child: None,
            crash_restarts: 0,
            http_client,
        }
    }

    /// Starts the Python sidecar process.
    ///
    /// Spawns `python -m remnant_bridge` with the auth token and port set as
    /// environment variables, then performs health checks to confirm readiness.
    pub async fn start(&mut self) -> Result<(), String> {
        if self.is_running() {
            log::warn!("Sidecar is already running on port {}", self.port);
            return Ok(());
        }

        log::info!(
            "Starting Python sidecar on port {} with token {}...",
            self.port,
            &self.auth_token[..8]
        );

        let child = Command::new("python3")
            .arg("-m")
            .arg("remnant_bridge")
            .env("REMNANT_SIDECAR_PORT", self.port.to_string())
            .env("REMNANT_AUTH_TOKEN", &self.auth_token)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn Python sidecar: {}", e))?;

        self.child = Some(child);

        // Wait for sidecar to become healthy with timeout
        let healthy = tokio::time::timeout(
            Duration::from_secs(STARTUP_TIMEOUT_SECS),
            self.wait_for_health(),
        )
        .await
        .map_err(|_| "Sidecar startup timed out after 30 seconds".to_string())?
        .map_err(|_| "Sidecar failed health checks".to_string())?;

        if healthy {
            log::info!("Python sidecar is healthy and ready on port {}", self.port);
            Ok(())
        } else {
            Err("Sidecar failed health checks".to_string())
        }
    }

    /// Performs a graceful shutdown of the sidecar process.
    ///
    /// Sends SIGTERM, waits up to 5 seconds, then sends SIGKILL if necessary.
    pub async fn stop(&mut self) -> Result<(), String> {
        if let Some(ref mut child) = self.child {
            log::info!("Stopping Python sidecar (graceful shutdown)...");

            // Send SIGTERM
            let pid = child.id().unwrap_or(0) as i32;
            #[cfg(unix)]
            {
                if pid > 0 {
                    unsafe {
                        libc::kill(pid, libc::SIGTERM);
                    }
                }
            }
            #[cfg(windows)]
            {
                child.kill().await.map_err(|e| format!("Failed to kill sidecar: {}", e))?;
            }

            // Wait for graceful exit with timeout
            match tokio::time::timeout(Duration::from_secs(GRACEFUL_SHUTDOWN_SECS), child.wait()).await
            {
                Ok(Ok(_status)) => {
                    log::info!("Sidecar exited gracefully");
                }
                Ok(Err(e)) => {
                    log::warn!("Error waiting for sidecar exit: {}", e);
                }
                Err(_) => {
                    log::warn!("Sidecar did not exit within {}s, sending SIGKILL", GRACEFUL_SHUTDOWN_SECS);
                    let _ = child.kill().await;
                    let _ = child.wait().await;
                }
            }

            self.child = None;
            log::info!("Python sidecar stopped");
        } else {
            log::warn!("No sidecar process to stop");
        }

        Ok(())
    }

    /// Performs a single health check against the sidecar's /health endpoint.
    pub async fn health_check(&self) -> bool {
        let url = format!("http://127.0.0.1:{}/health", self.port);
        match self.http_client.get(&url).send().await {
            Ok(resp) => resp.status().is_success(),
            Err(_) => false,
        }
    }

    /// Checks whether the sidecar process is still alive.
    pub fn is_running(&mut self) -> bool {
        if let Some(ref mut child) = self.child {
            match child.try_wait() {
                Ok(Some(_status)) => false, // process has exited
                Ok(None) => true,           // process still running
                Err(_) => false,
            }
        } else {
            false
        }
    }

    /// Returns the base URL for the sidecar (e.g., http://127.0.0.1:18731).
    pub fn get_base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    /// Returns the current ephemeral auth token.
    pub fn get_auth_token(&self) -> &str {
        &self.auth_token
    }

    /// Returns the port the sidecar is configured to use.
    pub fn get_port(&self) -> u16 {
        self.port
    }

    /// Returns the number of crash restarts attempted so far.
    pub fn get_crash_restarts(&self) -> u32 {
        self.crash_restarts
    }

    /// Attempts to restart the sidecar after a crash.
    ///
    /// Returns Ok if the restart succeeds, or Err if max crash restarts exceeded.
    #[allow(dead_code)]
    pub async fn restart_after_crash(&mut self) -> Result<(), String> {
        if self.crash_restarts >= MAX_CRASH_RESTARTS {
            return Err(format!(
                "Exceeded maximum crash restarts ({})",
                MAX_CRASH_RESTARTS
            ));
        }

        self.crash_restarts += 1;
        log::warn!(
            "Attempting crash restart #{} of {}",
            self.crash_restarts,
            MAX_CRASH_RESTARTS
        );

        // Clean up the dead child process
        self.child = None;

        self.start().await
    }

    /// Waits for the sidecar health check to succeed, retrying up to HEALTH_CHECK_MAX_RETRIES times.
    async fn wait_for_health(&self) -> Result<bool, ()> {
        for attempt in 1..=HEALTH_CHECK_MAX_RETRIES {
            if self.health_check().await {
                return Ok(true);
            }
            log::debug!(
                "Health check attempt {}/{} failed, retrying in {}s...",
                attempt,
                HEALTH_CHECK_MAX_RETRIES,
                HEALTH_CHECK_INTERVAL_SECS
            );
            tokio::time::sleep(Duration::from_secs(HEALTH_CHECK_INTERVAL_SECS)).await;
        }
        Err(())
    }

    /// Returns a reference to the HTTP client for making API calls to the sidecar.
    pub fn get_http_client(&self) -> &Client {
        &self.http_client
    }
}

/// Generates a random ephemeral token for sidecar authentication.
fn generate_ephemeral_token() -> String {
    let mut rng = rand::thread_rng();
    let bytes: [u8; 32] = rng.gen();
    hex::encode(bytes)
}

/// Hex encoding utility (simple, zero-dependency).
mod hex {
    const HEX_CHARS: &[u8; 16] = b"0123456789abcdef";

    pub fn encode(bytes: [u8; 32]) -> String {
        let mut s = String::with_capacity(64);
        for &b in &bytes {
            s.push(HEX_CHARS[(b >> 4) as usize] as char);
            s.push(HEX_CHARS[(b & 0x0f) as usize] as char);
        }
        s
    }
}

/// Thread-safe wrapper for SidecarManager, safe to use as Tauri managed state.
pub type SidecarState = Arc<Mutex<SidecarManager>>;

/// Creates a new SidecarState for use with Tauri's .manage() API.
pub fn create_sidecar_state() -> SidecarState {
    Arc::new(Mutex::new(SidecarManager::new()))
}