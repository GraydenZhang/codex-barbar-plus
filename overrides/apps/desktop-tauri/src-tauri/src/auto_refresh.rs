//! Periodic refresh for the desktop shell, with a small reset-aware probe.
//!
//! Upstream refresh cadence is preserved. Plus additionally checks the cached
//! 5-hour/weekly `resetAt` values and requests a real app-server refresh shortly
//! after a known deadline, even when normal auto-refresh is disabled. The
//! notification engine still confirms the new window before alerting.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use codexbar::core::{ProfileUsageState, RefreshTrigger};
use codexbar::storage::UsageRepository;
use tauri::Manager;

use crate::state::AppState;

const TICK: Duration = Duration::from_secs(15);
const RESET_RETRY: Duration = Duration::from_secs(60);
const FIVE_HOUR_MINUTES: u64 = 300;
const WEEKLY_MINUTES: u64 = 10_080;

pub fn start(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut ticker = tokio::time::interval(TICK);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        let mut last_refresh: Option<Instant> = None;
        let mut last_reset_probe: Option<(DateTime<Utc>, Instant)> = None;

        loop {
            ticker.tick().await;
            let service = {
                let state = app.state::<Mutex<AppState>>();
                let Ok(guard) = state.lock() else {
                    continue;
                };
                guard.account_service.clone()
            };
            let Some(service) = service else {
                continue;
            };
            let Ok(settings) = service.repositories().settings.load() else {
                continue;
            };
            let Ok(accounts) = service.snapshot() else {
                continue;
            };
            let profile_id = accounts.selected_profile_id;

            let due_reset = service
                .repositories()
                .usage
                .load_state(profile_id)
                .ok()
                .and_then(|state| due_reset_at(&state, Utc::now()));

            let reset_probe_due = due_reset.is_some_and(|reset_at| {
                match last_reset_probe {
                    Some((previous_reset, attempted)) if previous_reset == reset_at => {
                        attempted.elapsed() >= RESET_RETRY
                    }
                    _ => true,
                }
            });

            let regular_due = if settings.refresh_interval_seconds == 0 {
                false
            } else {
                match last_refresh {
                    Some(started) => {
                        started.elapsed().as_secs() >= settings.refresh_interval_seconds
                    }
                    None => true,
                }
            };

            if !regular_due && !reset_probe_due {
                continue;
            }

            let attempt_started = Instant::now();
            if let Some(reset_at) = due_reset {
                last_reset_probe = Some((reset_at, attempt_started));
            }
            last_refresh = Some(attempt_started);
            let _ = service
                .request_refresh(profile_id, RefreshTrigger::Timer)
                .await;
        }
    });
}

fn due_reset_at(state: &ProfileUsageState, now: DateTime<Utc>) -> Option<DateTime<Utc>> {
    let snapshot = state.snapshot.as_ref()?;
    snapshot
        .primary
        .iter()
        .chain(snapshot.secondary.iter())
        .chain(snapshot.additional_windows.iter())
        .filter(|window| {
            matches!(
                window.window_duration_minutes,
                Some(FIVE_HOUR_MINUTES) | Some(WEEKLY_MINUTES)
            )
        })
        .filter_map(|window| window.resets_at)
        .filter(|reset_at| *reset_at <= now)
        .min()
}

#[cfg(test)]
mod tests {
    use chrono::{DateTime, Duration as ChronoDuration, Utc};
    use uuid::Uuid;

    use super::due_reset_at;
    use codexbar::core::{
        Freshness, ProfileUsageSnapshot, ProfileUsageState, RefreshStatus, UsageSource,
        UsageWindow,
    };

    #[test]
    fn only_known_rolling_windows_trigger_reset_probe() {
        let id = Uuid::new_v4();
        let now = DateTime::from_timestamp(1_780_000_000, 0).unwrap();
        let state = ProfileUsageState {
            profile_id: id,
            snapshot: Some(ProfileUsageSnapshot {
                profile_id: id,
                plan_type: None,
                primary: Some(
                    UsageWindow::normalized(
                        "five",
                        None,
                        100.0,
                        Some(300),
                        Some(now - ChronoDuration::seconds(1)),
                        None,
                    )
                    .0,
                ),
                secondary: Some(
                    UsageWindow::normalized(
                        "week",
                        None,
                        20.0,
                        Some(10_080),
                        Some(now + ChronoDuration::days(2)),
                        None,
                    )
                    .0,
                ),
                additional_windows: Vec::new(),
                fetched_at: now - ChronoDuration::minutes(1),
                source: UsageSource::AppServer,
                protocol_anomaly: false,
                reset_credits: None,
            }),
            current_error: None,
            refresh_status: RefreshStatus::Idle,
            freshness: Freshness::Fresh,
            manual_cooldown_until: None,
        };
        assert_eq!(
            due_reset_at(&state, now),
            Some(now - ChronoDuration::seconds(1))
        );
    }
}
