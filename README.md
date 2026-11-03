# ASUFX Forex Factory Alerts

## GitHub repository setup

Open **Settings → Secrets and variables → Actions → New repository secret** and add:

- `DISCORD_WEBHOOK_URL` — your Discord webhook URL
- `PING_ROLE_ID` — the numeric ID of the Discord role to mention

The role ID is read from GitHub Secrets and is not hardcoded in the Python files.
Both the calendar digest and the upcoming-event alert workflow use this secret.

To copy a Discord role ID: enable Developer Mode in Discord, right-click the role,
and select **Copy Role ID**.

The bot only processes Forex Factory events with `High` impact (red folder).
