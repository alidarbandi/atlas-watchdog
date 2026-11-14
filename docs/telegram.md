# Telegram setup

Ordinary low-volume bot notifications do not require Premium, a paid broadcast feature, a paid bot host, or a public webhook. Both the PC and phone need connectivity. Phone sound/popups also depend on notifications permission, Do Not Disturb, battery/background restrictions and Telegram settings.

1. Install Telegram, sign in, and open the official verified **@BotFather** account.
2. Use `/newbot` and create a dedicated watchdog bot. Keep the issued token private. Follow the [official bot tutorial](https://core.telegram.org/bots/tutorial).
3. Open the new bot from your own Telegram account and press Start or send `/start`. A bot needs a chat it can contact.
4. In the Telegram setup page, enter the token in the masked field and save it. The panel reports Windows Credential Manager or session-only storage. Use **Check bot** to call `getMe` and confirm the bot identity.
5. Use **Find my chat** after `/start`, then deliberately select your private chat. Candidates show a friendly name and numeric ID; multiple candidates are never resolved by silently taking the first. You can enter a numeric chat ID manually.
6. Enable the Telegram channel and click **Send test notification**. Verify the received TEST and phone sound/popup. This does not arm automatic alerts.
7. Start monitoring and arm automatic alerts separately when ready.

Chat discovery is an explicit bounded `getUpdates` setup action, not a permanent command listener. A pre-existing webhook or another update consumer can conflict with it. Use a dedicated bot. This app does not remove webhooks, advance an update offset to discard messages, or accept remote microscope/shell commands.

The transport uses verified HTTPS to Telegram's Bot API, explicit connection/read timeouts and plain text `sendMessage`. Messages are conservatively bounded with the event identity retained; there is no paid-broadcast flag. A Bot API success means **Accepted by provider**, not that a person received a phone popup. See the [Bot API](https://core.telegram.org/bots/api) and [rate-limit FAQ](https://core.telegram.org/bots/faq).

The token appears inside Bot API request URLs. Never paste token-bearing URLs into a browser, public chat, screenshot or diagnostic report. The app redacts URL tokens and transport exceptions, stores references in non-secret configuration, and uses Credential Manager or disclosed session-only credentials. Remove/replace a compromised token through BotFather and the setup panel.

Typical results:

| Result | Action |
|---|---|
| 401 invalid token | Replace the token; check bot identity. |
| 403 blocked/inaccessible chat | Open the bot, unblock it, press Start, and check chat ID. |
| 409 discovery conflict | Check for a webhook or another consumer; use a dedicated bot. |
| 429 rate limit | The outbox honors `retry_after` while that session remains eligible. |
| Server/network failure | Bounded retry or uncertain-acceptance state, according to whether submission may have occurred. |

Stopping alerts does not retract an already accepted request. Events from an old session require deliberate resend; they do not automatically reappear on your phone after rearming.
