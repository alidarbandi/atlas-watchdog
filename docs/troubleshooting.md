# Troubleshooting

| Symptom | Check and action |
|---|---|
| Missing source | Inspect the resolved full path and filename. Engine's prefilled folder is only a suggestion; execution folder is separate. Wait for ATLAS to create it or select the correct explicit path. The app does not create source logs. |
| Windows code 3 | The containing path was not found. Open Sources → ENGINE → Choose log file, select the actual engine log, then Validate / test read and restart monitoring. `FIBIC` and `Fibics` are different folder names; neither suggestion is auto-substituted. On a PC without ATLAS, use Demo or review the supplied historical samples. See [Microsoft error codes](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-). |
| Unreadable/sharing violation | Check normal user permissions and whether ATLAS denies readers. The app retries without bypassing locks. Stop monitoring while investigating with an expendable acquisition; do not modify ATLAS permissions/configuration as a workaround. |
| Explorer reports 0 KB | The reader does not gate on directory metadata. Validate/Test Read and the source card indicate handle-based read results. Bytes not written by ATLAS cannot be recovered. |
| Catching up or coverage gap | Batches are bounded; both sources are scheduled fairly. Rotation/rewrite/replacement can leave unrecoverable unread data. Review details and the chosen new/resume/history policy. |
| No silence alerts | Keyword monitoring and Expect activity are separate. Confirm the source's arm/pause/lifecycle state, startup grace, cycle count, interval and threshold. Failed reads are source-health failures, not empty successful reads. |
| Unexpected silence alert | Check actual source cadence and long autofocus/milling/paused periods. The execution starting values are sample-derived, and engine messages may be hourly. Adjust thresholds or pause Expect activity. Silence is not a crash diagnosis. |
| No phrase match | Check source-specific rule enable, case sensitivity, scope, component and mode. `Turning EHT OFF` and `Turning SEM EHT off` are distinct literal phrases. Use the sample-text tester. Rule edits affect future records only. |
| Error missing from alerts | Check explicit ignore rules, channel selection, channel configuration and the two top-level controls. An ignore can intentionally suppress an Error-level record; inspect its audit details. Historical review and old sessions do not send automatically. |
| Gmail auth failure | Use an app password, exact sender and two-step verification. Account policies may not offer app passwords; password changes can revoke them. No regular password or less-secure-app mode is supported. |
| Gmail timeout/TLS failure | SMTP may be blocked even when HTTPS works. Ask IT about 465/587, proxy/CA policy and network. Keep TLS verification enabled. |
| Telegram invalid token/chat | Check bot identity, token and numeric chat ID. Open/unblock the bot and press Start. Revoke a leaked token. Never paste token-bearing API URLs into public diagnostics. |
| Find my chat empty/conflict | Send `/start` first. Updates may already have been consumed, or a webhook/another consumer may conflict. Use a dedicated bot; enter a known numeric ID manually. The app does not remove another webhook or silently discard updates. |
| Accepted but no popup | Acceptance is provider submission only. Check recipient account/chat, spam, phone permissions, sound, DND and battery/background limits. |
| Unknown acceptance | A request may already have been accepted before connectivity/process loss. Inspect provider/chat before deliberate resend. Exactly-once external delivery is impossible after this uncertainty. |
| Failed/cancelled old queue | Old process/session queues require deliberate resend/discard. Rearming does not send them automatically. |
| Config reset/recovery warning | Review current and recoverable previous config under `%LOCALAPPDATA%\ATLASWatchdog`. Invalid settings use safe defaults; external sending still starts off. Re-enter credentials after importing a portable config. |
| Database/disk warning | Free local disk space or restore normal user write access outside source directories. Preserve the database for diagnosis. Reliability is degraded; emergency memory is bounded and cannot replace persistence. |
| Retention cap warning | Unacknowledged faults and unresolved delivery history are protected. Review/acknowledge/export deliberately; deleting history is separate from clearing the display. |
| App gone after logout/power loss | This is a user desktop process, not a service. Restart and review coverage. A separate external observer would be required for reliable remote machine-failure detection. |
| EXE blocked or Qt cannot start | Confirm OS build/architecture and keep the one-folder bundle intact. Use the diagnostic executable and normal IT review. Do not disable antivirus or institutional execution controls. |

Before sharing diagnostics, remove secrets and consider experiment paths, user/instrument identifiers and scientific messages. Configuration export contains no credentials, but event history can contain sensitive experiment context. Export only what you deliberately choose. Never send the whole source logs automatically.

For a reproducible issue, use a sanitized demo file and a separate test-state directory; record source mode, rule/timing policy, OS build, version, event ID and channel status. Real source files must remain read-only to this utility and tests.
