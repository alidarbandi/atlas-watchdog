# Gmail setup

Use **Check SMTP connection (no email)** to test DNS/TCP, verified TLS, and SMTP capabilities from the executable itself. This action needs no credential, performs no authentication, sends no message, and does not mark provider acceptance. It can help distinguish application-specific network restrictions from an account/password problem. Actual delivery still requires a deliberate **Send TEST email**.

Failures identify the endpoint and phase (connection/greeting, STARTTLS, authentication, sender/recipient acceptance, or message submission). A retryable TEST result does not cause automatic resending; inspect the result and retry deliberately. Network reachability can change between checks. Gmail uses `smtp.gmail.com:465` for implicit TLS and `smtp.gmail.com:587` for mandatory STARTTLS; never turn off TLS verification. See [Google's SMTP ports](https://developers.google.com/workspace/gmail/imap/imap-smtp).

The application sends through your Gmail account using SMTP and an **app password**. A browser session is not needed at runtime. OAuth is not implemented in this version. Never enter a regular Google account password or enable obsolete “less secure app” access.

1. Choose a dedicated personal Gmail account for the watchdog.
2. Turn on two-step verification in Google Account security settings.
3. Open [Google App Passwords](https://myaccount.google.com/apppasswords) and create an app password for ATLAS Watchdog. Some organization policies and account configurations do not offer app passwords. [Google's app-password guidance](https://support.google.com/accounts/answer/185833) explains availability; changing the Google account password revokes existing app passwords.
4. In the Gmail setup page, enter the sender address and one or more recipient addresses. A recipient need not use Gmail. Enter the app password in the masked field and save it. The result panel identifies secure persistent storage or session-only storage. Replace/Remove manages the saved credential.
5. Select port 465 (implicit TLS, the default) or 587 (mandatory STARTTLS). Both verify certificates. Sender authentication uses the configured sender address.
6. Click **Send test email**. This sends only the requested TEST, even while monitoring or automatic alerts are off. Verify receipt and spam/junk folders. Test each intended recipient and verify the sender account's security notices.
7. Check **Enable this external notification channel** and click **Apply settings and rules**. Then start monitoring and click **Start alerts**. A successful test does not turn automatic alerts on. The Gmail channel choice and saved app password persist on this Windows account and PC; monitoring and automatic alerts must be started again after relaunch.

SMTP uses `smtp.gmail.com`, explicit 15-second socket timeouts and a verifying SSL context, consistent with [Google's SMTP settings](https://developers.google.com/workspace/gmail/imap/imap-smtp). Recipient outbox entries are separate, so acceptance for one recipient is not retried because another was refused. Transient failures may retry only while the same monitoring/alert session remains eligible; permanent authentication or recipient problems require action. A disconnect after message submission can mean **Unknown acceptance**; it is not treated as a guaranteed safe retry.

Gmail is rate-limited; see [personal account sending limits](https://support.google.com/mail/answer/22839). Low-volume grouped messages reduce bursts, but this free service has no promised alert delivery time. A result of Accepted means Gmail accepted the submission for that recipient, not that the recipient saw it.

App passwords are stored in Windows Credential Manager for the current user on this PC. Configuration contains a reference, never the secret. If secure persistence is unavailable, session-only storage is disclosed and expires when the process exits. Configuration export clears credential references; re-enter credentials on import or another PC. Do not include credentials in screenshots, support bundles or messages.

For authentication failure, verify app-password availability, two-step verification, exact sender, and password revocation. For TLS, timeouts or blocked ports, ask your lab IT team about SMTP policy; Telegram HTTPS may work independently. Do not disable certificate checking or institutional controls.
