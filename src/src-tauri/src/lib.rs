mod bridge;
mod sidecar;

use sidecar::{create_sidecar_state, SidecarState};
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_state = create_sidecar_state();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Start the Python sidecar during app setup
            let state = app.state::<SidecarState>();
            let sidecar = state.inner().clone();
            tauri::async_runtime::spawn(async move {
                let mut manager = sidecar.lock().await;
                match manager.start().await {
                    Ok(()) => log::info!("Sidecar started successfully"),
                    Err(e) => log::error!("Failed to start sidecar: {}", e),
                }
            });

            Ok(())
        })
        .manage(sidecar_state)
        .on_window_event(|window, event| {
            // Gracefully stop the sidecar when the main window closes
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window.state::<SidecarState>();
                let sidecar = state.inner().clone();
                tauri::async_runtime::block_on(async {
                    let mut manager = sidecar.lock().await;
                    if let Err(e) = manager.stop().await {
                        log::error!("Failed to stop sidecar on close: {}", e);
                    }
                });
            }
        })
        .invoke_handler(tauri::generate_handler![
            bridge::invoke_query,
            bridge::invoke_import,
            bridge::invoke_scope_create,
            bridge::invoke_scope_delete,
            bridge::invoke_safety_evaluate,
            bridge::invoke_data_destroy,
            bridge::invoke_health_check,
            bridge::invoke_sidecar_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}