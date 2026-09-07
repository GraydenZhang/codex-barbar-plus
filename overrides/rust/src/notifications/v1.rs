use std::{collections::BTreeMap, fs, path::PathBuf};

use chrono::{DateTime, Duration as ChronoDuration, Utc};
use serde::{Deserialize, Serialize};

use crate::{
    app_paths::AppPaths,
    core::{ProfileId, ProfileUsageState, UsageWindow},
    storage::NotificationPreferences,
};

const FIVE_HOUR_WINDOW_MINUTES: u64 = 300;
const WEEKLY_WINDOW_MINUTES: u64 = 10_080;
const RESET_RECOVERY_POINTS: u8 = 5;
const RESET_DUE_TOLERANCE_SECONDS: i64 = 90;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum V1NotificationEvent {
    Warning { remaining_percent: u8 },
    Danger { remaining_percent: u8 },
    FiveHourReset,
    WeeklyReset,
    ResetCreditsIncreased { available_count: u64 },
    RefreshFailed,
    RefreshRecovered,
    UpdateAvailable { version: String },
    PricingCatalogChanged { source_count: u8 },
    PricingRefreshFailed,
    PricingRefreshRecovered,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
enum QuotaBand {
    Normal,
    Warning,
    Danger,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
struct NotificationState {
    profiles: BTreeMap<ProfileId, ProfileNotificationState>,
    last_update_version: Option<String>,
    consecutive_pricing_failures: u8,
    pricing_failure_notified: bool,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
struct ProfileNotificationState {
    /// SHA-256 hex of the normalized account email; never raw identity.
    account_marker_hash: Option<String>,

    /// Persist both rolling windows so a reset that happens while Windows is
    /// asleep is still recognized on the first successful refresh after wake.
    five_hour_reset_at: Option<DateTime<Utc>>,
    five_hour_remaining_percent: Option<u8>,
    last_five_hour_notified_reset_at: Option<DateTime<Utc>>,

    weekly_reset_at: Option<DateTime<Utc>>,
    weekly_remaining_percent: Option<u8>,
    last_weekly_notified_reset_at: Option<DateTime<Utc>>,

    armed_band: Option<QuotaBand>,
    known_reset_credits: Option<u64>,
    consecutive_refresh_failures: u8,
    refresh_failure_notified: bool,
}

/// Pure V1 notification decision engine with small, non-secret persisted state.
pub struct V1NotificationEngine {
    state_path: PathBuf,
    state: NotificationState,
}

impl V1NotificationEngine {
    pub fn load(paths: &AppPaths) -> Self {
        let state_path = paths.notification_state.clone();
        let state = match fs::read(&state_path) {
            Ok(bytes) => match serde_json::from_slice(&bytes) {
                Ok(state) => state,
                Err(error) => {
                    tracing::warn!(error = %error, "Ignoring unreadable notification runtime state");
                    NotificationState::default()
                }
            },
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                NotificationState::default()
            }
            Err(error) => {
                tracing::warn!(error = %error, "Unable to read notification runtime state");
                NotificationState::default()
            }
        };
        Self { state_path, state }
    }

    #[cfg(test)]
    pub fn observe_usage(
        &mut self,
        preferences: &NotificationPreferences,
        profile_id: ProfileId,
        state: &ProfileUsageState,
        reset_credits: Option<u64>,
    ) -> Vec<V1NotificationEvent> {
        self.observe_usage_for_account(preferences, profile_id, None, state, reset_credits)
    }

    pub fn observe_usage_for_account(
        &mut self,
        preferences: &NotificationPreferences,
        profile_id: ProfileId,
        account_marker: Option<&str>,
        state: &ProfileUsageState,
        reset_credits: Option<u64>,
    ) -> Vec<V1NotificationEvent> {
        self.prepare_profile_for_account(profile_id, account_marker);
        let Some(snapshot) = state.snapshot.as_ref() else {
            self.persist();
            return Vec::new();
        };

        let five_hour = window_by_duration(state, FIVE_HOUR_WINDOW_MINUTES);
        let weekly = window_by_duration(state, WEEKLY_WINDOW_MINUTES);
        let observed_at = snapshot.fetched_at;
        let profile = self.state.profiles.entry(profile_id).or_default();
        let previous_band = profile.armed_band;
        let previous_credits = profile.known_reset_credits;
        let first_weekly_observation = profile.armed_band.is_none();

        let five_hour_reset = five_hour.is_some_and(|window| {
            confirmed_window_reset(
                profile.five_hour_reset_at,
                profile.five_hour_remaining_percent,
                profile.last_five_hour_notified_reset_at,
                window,
                observed_at,
            )
        });
        let weekly_reset = weekly.is_some_and(|window| {
            confirmed_window_reset(
                profile.weekly_reset_at,
                profile.weekly_remaining_percent,
                profile.last_weekly_notified_reset_at,
                window,
                observed_at,
            )
        });

        if let Some(window) = five_hour {
            profile.five_hour_reset_at = window.resets_at;
            profile.five_hour_remaining_percent = Some(rounded_percent(window.remaining_percent));
            if five_hour_reset {
                profile.last_five_hour_notified_reset_at = window.resets_at;
            }
        }

        let weekly_remaining = weekly.map(|window| rounded_percent(window.remaining_percent));
        let current_band = weekly_remaining.map(|remaining| band_for(remaining, preferences));
        if let Some(window) = weekly {
            profile.weekly_reset_at = window.resets_at;
            profile.weekly_remaining_percent = weekly_remaining;
            if weekly_reset {
                profile.last_weekly_notified_reset_at = window.resets_at;
            }
        }
        if let Some(current_band) = current_band {
            profile.armed_band = Some(current_band);
        }
        profile.known_reset_credits = reset_credits;

        let mut events = Vec::new();
        // Plus treats quota-reset notification as a standalone convenience:
        // the existing reset toggle is on by default and remains effective even
        // when the upstream master switch for warning/update alerts is off.
        if preferences.weekly_reset_enabled {
            if five_hour_reset {
                events.push(V1NotificationEvent::FiveHourReset);
            }
            if weekly_reset {
                events.push(V1NotificationEvent::WeeklyReset);
            }
        }

        if preferences.enabled {
            if !first_weekly_observation && !weekly_reset {
                if let (Some(previous_band), Some(current_band), Some(remaining_percent)) =
                    (previous_band, current_band, weekly_remaining)
                {
                    match (previous_band, current_band) {
                        (QuotaBand::Normal, QuotaBand::Warning)
                            if preferences.warning_enabled =>
                        {
                            events.push(V1NotificationEvent::Warning { remaining_percent });
                        }
                        (QuotaBand::Normal | QuotaBand::Warning, QuotaBand::Danger)
                            if preferences.danger_enabled =>
                        {
                            events.push(V1NotificationEvent::Danger { remaining_percent });
                        }
                        _ => {}
                    }
                }
            }

            if preferences.reset_credit_increase_enabled
                && previous_credits
                    .is_some_and(|previous| reset_credits.is_some_and(|current| current > previous))
            {
                events.push(V1NotificationEvent::ResetCreditsIncreased {
                    available_count: reset_credits.expect("checked above"),
                });
            }
        }

        self.persist();
        events
    }

    #[cfg(test)]
    pub fn observe_refresh(
        &mut self,
        preferences: &NotificationPreferences,
        profile_id: ProfileId,
        success: bool,
    ) -> Vec<V1NotificationEvent> {
        self.observe_refresh_for_account(preferences, profile_id, None, success)
    }

    pub fn observe_refresh_for_account(
        &mut self,
        preferences: &NotificationPreferences,
        profile_id: ProfileId,
        account_marker: Option<&str>,
        success: bool,
    ) -> Vec<V1NotificationEvent> {
        self.prepare_profile_for_account(profile_id, account_marker);
        let profile = self.state.profiles.entry(profile_id).or_default();
        if !preferences.enabled || !preferences.refresh_failure_enabled {
            profile.consecutive_refresh_failures = 0;
            profile.refresh_failure_notified = false;
            self.persist();
            return Vec::new();
        }
        let mut events = Vec::new();
        if success {
            let had_reported_failure = profile.refresh_failure_notified;
            profile.consecutive_refresh_failures = 0;
            profile.refresh_failure_notified = false;
            if had_reported_failure {
                events.push(V1NotificationEvent::RefreshRecovered);
            }
        } else {
            profile.consecutive_refresh_failures =
                profile.consecutive_refresh_failures.saturating_add(1);
            if profile.consecutive_refresh_failures == 3 {
                profile.refresh_failure_notified = true;
                events.push(V1NotificationEvent::RefreshFailed);
            }
        }
        self.persist();
        events
    }

    fn prepare_profile_for_account(&mut self, profile_id: ProfileId, account_marker: Option<&str>) {
        let profile = self.state.profiles.entry(profile_id).or_default();
        if let Some(account_marker) = account_marker {
            if profile
                .account_marker_hash
                .as_deref()
                .is_some_and(|previous| previous != account_marker)
            {
                *profile = ProfileNotificationState::default();
            }
            profile.account_marker_hash = Some(account_marker.to_string());
        }
    }

    pub fn observe_pricing_refresh(
        &mut self,
        preferences: &NotificationPreferences,
        failed: bool,
        source_count: u8,
        catalog_changed: bool,
    ) -> Vec<V1NotificationEvent> {
        let mut events = Vec::new();
        if !preferences.enabled {
            self.state.consecutive_pricing_failures = 0;
            self.state.pricing_failure_notified = false;
            self.persist();
            return events;
        }
        if failed {
            if preferences.pricing_refresh_failure_enabled {
                self.state.consecutive_pricing_failures =
                    self.state.consecutive_pricing_failures.saturating_add(1);
                if self.state.consecutive_pricing_failures == 3 {
                    self.state.pricing_failure_notified = true;
                    events.push(V1NotificationEvent::PricingRefreshFailed);
                }
            } else {
                self.state.consecutive_pricing_failures = 0;
                self.state.pricing_failure_notified = false;
            }
        } else {
            let had_reported_failure = self.state.pricing_failure_notified;
            self.state.consecutive_pricing_failures = 0;
            self.state.pricing_failure_notified = false;
            if had_reported_failure && preferences.pricing_refresh_failure_enabled {
                events.push(V1NotificationEvent::PricingRefreshRecovered);
            }
            if catalog_changed && preferences.pricing_changed_enabled {
                events.push(V1NotificationEvent::PricingCatalogChanged { source_count });
            }
        }
        self.persist();
        events
    }

    pub fn observe_update_available(
        &mut self,
        preferences: &NotificationPreferences,
        version: &str,
    ) -> Vec<V1NotificationEvent> {
        let is_new = self.state.last_update_version.as_deref() != Some(version);
        self.state.last_update_version = Some(version.to_string());
        let events = if is_new && preferences.enabled && preferences.update_available_enabled {
            vec![V1NotificationEvent::UpdateAvailable {
                version: version.to_string(),
            }]
        } else {
            Vec::new()
        };
        self.persist();
        events
    }

    fn persist(&self) {
        let Some(parent) = self.state_path.parent() else {
            tracing::warn!("Notification runtime state has no parent directory");
            return;
        };
        let result = fs::create_dir_all(parent)
            .and_then(|()| serde_json::to_vec(&self.state).map_err(std::io::Error::other))
            .and_then(|encoded| fs::write(&self.state_path, encoded));
        if let Err(error) = result {
            tracing::warn!(error = %error, "Unable to persist notification runtime state");
        }
    }
}

fn window_by_duration(state: &ProfileUsageState, duration_minutes: u64) -> Option<&UsageWindow> {
    let snapshot = state.snapshot.as_ref()?;
    snapshot
        .primary
        .iter()
        .chain(snapshot.secondary.iter())
        .chain(snapshot.additional_windows.iter())
        .filter(|window| window.window_duration_minutes == Some(duration_minutes))
        // Providers can expose the same duration more than once. Match the
        // UI's conservative behavior and track the most depleted copy.
        .min_by(|left, right| {
            left.remaining_percent
                .partial_cmp(&right.remaining_percent)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
}

/// Confirm a real cycle transition rather than treating any `resetAt` edit as
/// a reset. A window must advance, then either (a) the old reset deadline was
/// actually reached (including sleep/wake), or (b) allowance visibly recovered.
fn confirmed_window_reset(
    previous_reset_at: Option<DateTime<Utc>>,
    previous_remaining_percent: Option<u8>,
    last_notified_reset_at: Option<DateTime<Utc>>,
    current: &UsageWindow,
    observed_at: DateTime<Utc>,
) -> bool {
    let (Some(previous_reset_at), Some(current_reset_at)) =
        (previous_reset_at, current.resets_at)
    else {
        return false;
    };
    if current_reset_at <= previous_reset_at || last_notified_reset_at == Some(current_reset_at) {
        return false;
    }

    let old_window_due =
        observed_at + ChronoDuration::seconds(RESET_DUE_TOLERANCE_SECONDS) >= previous_reset_at;
    let current_remaining = rounded_percent(current.remaining_percent);
    let visibly_recovered = previous_remaining_percent.is_some_and(|previous| {
        current_remaining >= previous.saturating_add(RESET_RECOVERY_POINTS)
    });

    old_window_due || visibly_recovered
}

fn rounded_percent(value: f64) -> u8 {
    value.round().clamp(0.0, 100.0) as u8
}

fn band_for(remaining_percent: u8, preferences: &NotificationPreferences) -> QuotaBand {
    if remaining_percent <= preferences.danger_remaining_percent {
        QuotaBand::Danger
    } else if remaining_percent <= preferences.warning_remaining_percent {
        QuotaBand::Warning
    } else {
        QuotaBand::Normal
    }
}

#[cfg(test)]
mod tests {
    use chrono::{DateTime, Duration as ChronoDuration, Utc};
    use tempfile::tempdir;
    use uuid::Uuid;

    use super::{V1NotificationEngine, V1NotificationEvent};
    use crate::{
        app_paths::AppPaths,
        core::{
            Freshness, ProfileUsageSnapshot, ProfileUsageState, RefreshStatus, UsageSource,
            UsageWindow,
        },
        storage::NotificationPreferences,
    };

    fn enabled() -> NotificationPreferences {
        NotificationPreferences {
            enabled: true,
            ..NotificationPreferences::default()
        }
    }

    fn state_with_windows(
        id: Uuid,
        five_used: f64,
        five_reset: DateTime<Utc>,
        weekly_used: f64,
        weekly_reset: DateTime<Utc>,
        fetched_at: DateTime<Utc>,
    ) -> ProfileUsageState {
        ProfileUsageState {
            profile_id: id,
            snapshot: Some(ProfileUsageSnapshot {
                profile_id: id,
                plan_type: None,
                primary: Some(
                    UsageWindow::normalized(
                        "five-hour",
                        None,
                        five_used,
                        Some(300),
                        Some(five_reset),
                        None,
                    )
                    .0,
                ),
                secondary: Some(
                    UsageWindow::normalized(
                        "weekly",
                        None,
                        weekly_used,
                        Some(10_080),
                        Some(weekly_reset),
                        None,
                    )
                    .0,
                ),
                additional_windows: Vec::new(),
                fetched_at,
                source: UsageSource::AppServer,
                protocol_anomaly: false,
                reset_credits: None,
            }),
            current_error: None,
            refresh_status: RefreshStatus::Idle,
            freshness: Freshness::Fresh,
            manual_cooldown_until: None,
        }
    }

    fn state_path() -> (tempfile::TempDir, AppPaths) {
        let temp = tempdir().unwrap();
        let paths = AppPaths::from_local_app_data(temp.path());
        (temp, paths)
    }

    #[test]
    fn five_hour_reset_is_detected_after_old_deadline_and_deduplicated() {
        let (_temp, paths) = state_path();
        let mut engine = V1NotificationEngine::load(&paths);
        let id = Uuid::new_v4();
        let now = DateTime::from_timestamp(1_780_000_000, 0).unwrap();
        let week = now + ChronoDuration::days(4);
        let first_reset = now + ChronoDuration::minutes(2);
        let next_reset = first_reset + ChronoDuration::hours(5);

        assert!(engine
            .observe_usage(
                &enabled(),
                id,
                &state_with_windows(id, 98.0, first_reset, 30.0, week, now),
                None,
            )
            .is_empty());

        let after = first_reset + ChronoDuration::minutes(1);
        assert_eq!(
            engine.observe_usage(
                &enabled(),
                id,
                &state_with_windows(id, 4.0, next_reset, 30.0, week, after),
                None,
            ),
            vec![V1NotificationEvent::FiveHourReset]
        );
        assert!(engine
            .observe_usage(
                &enabled(),
                id,
                &state_with_windows(id, 5.0, next_reset, 30.0, week, after),
                None,
            )
            .is_empty());
    }

    #[test]
    fn early_reset_at_edit_without_recovery_does_not_false_positive() {
        let (_temp, paths) = state_path();
        let mut engine = V1NotificationEngine::load(&paths);
        let id = Uuid::new_v4();
        let now = DateTime::from_timestamp(1_780_000_000, 0).unwrap();
        let five_a = now + ChronoDuration::hours(3);
        let five_b = five_a + ChronoDuration::minutes(15);
        let week = now + ChronoDuration::days(3);

        assert!(engine
            .observe_usage(
                &enabled(),
                id,
                &state_with_windows(id, 70.0, five_a, 20.0, week, now),
                None,
            )
            .is_empty());
        assert!(engine
            .observe_usage(
                &enabled(),
                id,
                &state_with_windows(
                    id,
                    71.0,
                    five_b,
                    20.0,
                    week,
                    now + ChronoDuration::minutes(1),
                ),
                None,
            )
            .is_empty());
    }

    #[test]
    fn weekly_reset_and_warning_lifecycle_still_work() {
        let (_temp, paths) = state_path();
        let mut engine = V1NotificationEngine::load(&paths);
        let id = Uuid::new_v4();
        let now = DateTime::from_timestamp(1_780_000_000, 0).unwrap();
        let five = now + ChronoDuration::hours(4);
        let week_a = now + ChronoDuration::minutes(2);
        let week_b = week_a + ChronoDuration::days(7);

        assert!(engine
            .observe_usage(
                &enabled(),
                id,
                &state_with_windows(id, 10.0, five, 20.0, week_a, now),
                None,
            )
            .is_empty());
        assert_eq!(
            engine.observe_usage(
                &enabled(),
                id,
                &state_with_windows(
                    id,
                    10.0,
                    five,
                    45.0,
                    week_a,
                    now + ChronoDuration::minutes(1),
                ),
                None,
            ),
            vec![V1NotificationEvent::Warning {
                remaining_percent: 55
            }]
        );
        assert_eq!(
            engine.observe_usage(
                &enabled(),
                id,
                &state_with_windows(
                    id,
                    10.0,
                    five,
                    10.0,
                    week_b,
                    week_a + ChronoDuration::minutes(1),
                ),
                None,
            ),
            vec![V1NotificationEvent::WeeklyReset]
        );
    }
}
