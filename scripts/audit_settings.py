"""Checked follow-up patches for the September settings/interaction audit.

Apply to the generated checkout after the original Plus setting patches.
"""

from pathlib import Path


def replace(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8-sig")
    count = text.count(before)
    if count != 1:
        raise RuntimeError(f"{path}: expected one settings audit anchor, got {count}: {before[:100]!r}")
    path.write_text(text.replace(before, after, 1), encoding="utf-8")


THRESHOLD_FIELD = '''function NotificationThresholdField({
  id,
  value,
  disabled,
  onCommit,
  onError,
  invalidMessage,
  saveFailedMessage,
}: {
  id: string;
  value: number;
  disabled: boolean;
  onCommit(value: number): Promise<unknown>;
  onError(message: string | null): void;
  invalidMessage: string;
  saveFailedMessage: string;
}) {
  const [draft, setDraft] = useState(String(value));
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const editing = useRef(false);
  const savedValue = useRef(value);
  savedValue.current = value;

  useEffect(() => {
    if (!editing.current && !savingRef.current) setDraft(String(value));
  }, [value]);

  const commit = () => {
    editing.current = false;
    if (savingRef.current) return;
    const next = Number(draft);
    if (draft.trim() === "" || !Number.isInteger(next) || next < 0 || next > 100) {
      setDraft(String(savedValue.current));
      onError(invalidMessage);
      return;
    }
    if (next === savedValue.current) {
      setDraft(String(next));
      return;
    }
    savingRef.current = true;
    setSaving(true);
    onError(null);
    void Promise.resolve()
      .then(() => onCommit(next))
      .catch((reason: unknown) => {
        setDraft(String(savedValue.current));
        onError(reason === "SETTINGS_NOTIFICATION_THRESHOLDS_INVALID"
          ? invalidMessage : saveFailedMessage);
      })
      .finally(() => {
        savingRef.current = false;
        setSaving(false);
      });
  };

  return <input
    id={id}
    type="number"
    min="0"
    max="100"
    step="1"
    value={draft}
    disabled={disabled || saving}
    onFocus={() => { editing.current = true; }}
    onChange={(event) => { setDraft(event.target.value); onError(null); }}
    onBlur={commit}
    onKeyDown={(event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        event.currentTarget.blur();
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setDraft(String(savedValue.current));
        onError(null);
      }
    }}
  />;
}

'''


def patch_notifications(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/surfaces/settings/tabs/NotificationsTab.tsx"
    replace(path, "function NotificationSwitch({", THRESHOLD_FIELD + "function NotificationSwitch({")
    replace(path, '''    void update({ notifications: { [field]: value } }).catch((reason: unknown) => {
      setError(
        reason === "SETTINGS_NOTIFICATION_THRESHOLDS_INVALID"
          ? copy.notifications.thresholdInvalid
          : copy.notifications.saveFailed,
      );
    });''', '''    const warning = field === "warningRemainingPercent"
      ? value : notifications.warningRemainingPercent;
    const danger = field === "dangerRemainingPercent"
      ? value : notifications.dangerRemainingPercent;
    if (danger >= warning) {
      return Promise.reject("SETTINGS_NOTIFICATION_THRESHOLDS_INVALID");
    }
    return update({ notifications: { [field]: value } });''')
    for field, label in [("warningRemainingPercent", "warning"), ("dangerRemainingPercent", "danger")]:
        replace(path, f'''          <input
            id="notification-{label}-threshold"
            type="number"
            min="0"
            max="100"
            step="1"
            value={{notifications.{field}}}
            disabled={{!notifications.enabled}}
            onChange={{(event) =>
              saveThreshold("{field}", Number(event.target.value))
            }}
          />''', f'''          <NotificationThresholdField
            id="notification-{label}-threshold"
            value={{notifications.{field}}}
            disabled={{!notifications.enabled}}
            onCommit={{(value) => saveThreshold("{field}", value)}}
            onError={{setError}}
            invalidMessage={{copy.notifications.thresholdInvalid}}
            saveFailedMessage={{copy.notifications.saveFailed}}
          />''')
    replace(path, '''    const saveSound = save
      ? update({ notifications: { resetSound: sound } })
      : Promise.resolve();
    void saveSound
      .then(() => previewSound(sound))
      .catch((reason: unknown) => {
        if (reason === "NOTIFICATION_PERMISSION_DISABLED") {
          refreshCapability();
          return;
        }
        setError(
          save ? copy.notifications.saveFailed : copy.notifications.soundPreviewFailed,
        );
      })
      .finally(() => setPreviewingSound(false));''', '''    void (async () => {
      try {
        if (save) {
          try {
            await update({ notifications: { resetSound: sound } });
          } catch {
            setError(copy.notifications.saveFailed);
            return;
          }
        }
        try {
          await previewSound(sound);
        } catch (reason: unknown) {
          if (reason === "NOTIFICATION_PERMISSION_DISABLED") {
            refreshCapability();
          }
          setError(copy.notifications.soundPreviewFailed);
        }
      } finally {
        setPreviewingSound(false);
      }
    })();''')

    tests = source / "apps/desktop-tauri/src/surfaces/settings/tabs/NotificationsTab.test.tsx"
    replace(tests, '''    fireEvent.change(warning, { target: { value: "20" } });

    expect(await screen.findByRole("alert"))''', '''    fireEvent.change(warning, { target: { value: "20" } });
    fireEvent.blur(warning);

    expect(await screen.findByRole("alert"))''')
    replace(tests, '''    fireEvent.change(screen.getByRole("spinbutton", { name: /warning remaining/i }), {
      target: { value: "20" },
    });

    expect(await screen.findByRole("alert"))''', '''    const warning = screen.getByRole("spinbutton", { name: /warning remaining/i });
    fireEvent.change(warning, { target: { value: "50" } });
    fireEvent.blur(warning);

    expect(await screen.findByRole("alert"))''')


def patch_taskbar(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/surfaces/settings/tabs/TaskbarTrayTab.tsx"
    replace(path, "  enabled: boolean;\n  presentation:", "  enabled: boolean;\n  showFiveHour: boolean;\n  presentation:")
    replace(path, "return { enabled: settings.taskbarStatusEnabled, presentation: settings.taskbarPresentation };", "return { enabled: settings.taskbarStatusEnabled, showFiveHour: settings.taskbarShowFiveHour ?? true, presentation: settings.taskbarPresentation };")
    replace(path, "}, [settings.taskbarStatusEnabled, settings.taskbarPresentation]);", "}, [settings.taskbarStatusEnabled, settings.taskbarShowFiveHour, settings.taskbarPresentation]);")
    replace(path, "const visibleTaskbarItems = TASKBAR_ITEM_FIELDS.filter((field) => draft.presentation[field]).length;", "const visibleTaskbarItems = Number(draft.showFiveHour) + TASKBAR_ITEM_FIELDS.filter((field) => draft.presentation[field]).length;")
    replace(path, "  const taskbarItems = [", '''  const setFiveHour = (showFiveHour: boolean) => {
    const nextDraft = { ...draftRef.current, showFiveHour };
    commitDraft(nextDraft, () => update({ taskbarShowFiveHour: showFiveHour }));
  };
  const taskbarItems = [''')
    replace(path, '''checked={settings.taskbarShowFiveHour ?? true} disabled={isSavingPreferences} onChange={(event) => void update({ taskbarShowFiveHour: event.target.checked })}''', '''checked={draft.showFiveHour} disabled={isSavingPreferences || (draft.enabled && draft.showFiveHour && visibleTaskbarItems === 1)} aria-describedby="taskbar-visible-item-help" onChange={(event) => setFiveHour(event.target.checked)}''')

    storage = source / "rust/src/storage/settings_repository.rs"
    replace(storage, "        if self.notifications.danger_remaining_percent\n", '''        let presentation = &self.taskbar_presentation;
        if self.taskbar_status_enabled
            && !self.taskbar_show_five_hour
            && !presentation.show_taskbar_icon
            && !presentation.show_taskbar_account
            && !presentation.show_weekly_label
            && !presentation.show_weekly_percent
            && !presentation.show_reset_date
        {
            return Err(StorageError::new(
                crate::core::AppErrorKind::StorageFailure,
                "SETTINGS_TASKBAR_ITEMS_EMPTY",
                "at least one taskbar item must be visible while taskbar status is enabled",
            ));
        }
        if self.notifications.danger_remaining_percent
''')
    replace(storage, "    fn settings_fixture() -> (SettingsRepository, Arc<AppDatabase>) {", '''    #[test]
    fn five_hour_only_taskbar_is_valid_and_cannot_hide_its_last_item() {
        let (repository, _) = settings_fixture();
        repository.update(SettingsPatch {
            taskbar_status_enabled: Some(true),
            taskbar_show_five_hour: Some(true),
            taskbar_tray: Some(TaskbarTrayPreferencesPatch {
                show_taskbar_icon: Some(false),
                show_taskbar_account: Some(false),
                show_weekly_label: Some(false),
                show_weekly_percent: Some(false),
                show_reset_date: Some(false),
                ..Default::default()
            }),
            ..Default::default()
        }).unwrap();

        let error = repository.update(SettingsPatch {
            taskbar_show_five_hour: Some(false),
            ..Default::default()
        }).unwrap_err();
        assert_eq!(error.code(), "SETTINGS_TASKBAR_ITEMS_EMPTY");
        assert!(repository.load().unwrap().taskbar_show_five_hour);

        let disabled = repository.update(SettingsPatch {
            taskbar_status_enabled: Some(false),
            taskbar_show_five_hour: Some(false),
            ..Default::default()
        }).unwrap();
        assert!(!disabled.taskbar_status_enabled);
        assert!(!disabled.taskbar_show_five_hour);

        let error = repository.update(SettingsPatch {
            taskbar_status_enabled: Some(true),
            ..Default::default()
        }).unwrap_err();
        assert_eq!(error.code(), "SETTINGS_TASKBAR_ITEMS_EMPTY");

        let account_only = repository.update(SettingsPatch {
            taskbar_status_enabled: Some(true),
            taskbar_tray: Some(TaskbarTrayPreferencesPatch {
                show_taskbar_account: Some(true),
                ..Default::default()
            }),
            ..Default::default()
        }).unwrap();
        assert!(account_only.taskbar_presentation.show_taskbar_account);
    }

    fn settings_fixture() -> (SettingsRepository, Arc<AppDatabase>) {''')


def apply(source: Path) -> None:
    patch_notifications(source)
    patch_taskbar(source)
