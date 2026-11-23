# 🛡️ SAINT GUARD BOT v2.0 — Dark Edition

A Python Telegram group manager with moderation, flood protection, welcome/goodbye messages, keyword filters, statistics, inline menus and admin logs.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/saintbypass-byte/saint-guard-bot)

The button above deploys the included `render.yaml` Blueprint as a free Web Service. Render will ask you to provide `BOT_TOKEN` and any optional environment variables before starting the bot.

## Requirements
- Python 3.10+ (Python 3.12 recommended)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- The bot added to your group as an administrator

## 1. Create your bot
1. Open Telegram and message **@BotFather**.
2. Run `/newbot`, choose a display name and username.
3. Copy the token. Keep it secret.
4. Add your bot to your group and promote it to administrator.
5. Grant the permissions it needs: delete messages, ban/restrict users, invite users (optional), and manage messages.
6. In @BotFather, use `/setprivacy` and disable privacy if you want keyword filters and flood detection to inspect ordinary group messages. Re-add the bot to the group after changing privacy mode if Telegram requires it.

## 2. Configure
Copy `.env.example` to `.env`, then put your token in `BOT_TOKEN`.

Linux/macOS:
```bash
cp .env.example .env
nano .env
```

Windows PowerShell:
```powershell
Copy-Item .env.example .env
notepad .env
```

Never upload `.env` to GitHub or share your token. If it leaks, revoke it through @BotFather and generate a new one.

## 3. Run locally
```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
python -m saint_guard.bot
```

## 4. Cloud deployment (Docker / Render)
### Docker
Install Docker, create `.env`, then:
```bash
docker compose up -d --build
docker compose logs -f
```
The SQLite database is stored in `./data/`.

### Render
1. Click the **Deploy to Render** button above, or create a new Blueprint from this repository.
2. Set `BOT_TOKEN` in the service's environment settings; add `LOG_CHAT_ID` and `BOT_OWNER_ID` if needed.
3. Choose the **Free** plan and deploy it as a **Web Service**. The app exposes `/health` on Render's `PORT` so it passes the web-service port check while Telegram polling runs in the same container.
4. The free plan has an ephemeral filesystem, so the SQLite database at `/tmp/saint_guard.sqlite3` can reset after restarts or redeploys. Use a paid persistent disk or external PostgreSQL if durable data is required.
5. Check the service logs for `Health endpoint listening` and `SAINT GUARD is starting...`.

Other cloud providers can run the included Dockerfile as a long-running worker/container. Do not use a serverless function that stops between requests: this project uses long polling.

## Commands
| Command | What it does |
|---|---|
| `/start` | Premium welcome panel |
| `/help` | Command guide |
| `/ban` | Ban replied-to member |
| `/unban` | Unban replied-to member |
| `/kick` | Remove replied-to member |
| `/mute [minutes]` | Mute replied-to member (default 10 minutes) |
| `/unmute` | Restore replied-to member's messaging permissions |
| `/warn` | Add a warning; 3 warnings trigger a 1-hour mute |
| `/warnings` | Show warning count for replied-to member (or yourself) |
| `/purge [count]` | Delete up to 100 messages starting at the replied-to message |
| `/lock` / `/unlock` | Restrict or restore group messaging |
| `/welcome on|off` | Toggle join greeting |
| `/goodbye on|off` | Toggle leave notice |
| `/setrules text` | Set group rules |
| `/rules` | Display group rules |
| `/filter add keyword \| response` | Add a keyword response |
| `/filter remove keyword` | Remove a filter |
| `/filters` | List filters |
| `/blocklist add phrase` | Automatically remove messages containing a blocked phrase |
| `/blocklist remove phrase` | Remove a blocked phrase |
| `/blocklist list` / `/blocklist clear` | View or clear blocked phrases |
| `/locklinks on|off` | Toggle deletion of ordinary URLs and Telegram invite links |
| `/setflood 2-20` / `/flood` | Configure or view the per-group flood threshold |
| `/adminlist` | List group administrators |
| `/report` | Reply to a message with `/report [reason]` to notify admins and log the report |
| `/kickme` | Leave the group voluntarily |
| `/note save name \| content` | Save a reusable group note (admin-only) |
| `/get name` / `/notes` | Retrieve a note or list saved notes |
| `/delnote name` | Delete a saved note (admin-only) |
| `/stats` | Show group statistics |
| `/id` | Show user and chat IDs |
| `/ping` | Check bot response |

Moderation commands require a reply to the target member's message, except `/unban` (reply to a message from the user if available; for an ID-based unban, use Telegram's admin tools).

## Admin logs
Set `LOG_CHAT_ID` to a private channel/group ID. Add SAINT GUARD there and allow it to send messages. All recorded moderation and membership actions are also stored in SQLite.

## Important notes / limitations
- This is a starter production-style project, not a fully audited enterprise security product.
- Telegram must grant the bot the relevant administrator rights. The bot cannot moderate the group owner or administrators.
- Anti-spam is a lightweight flood/repeated-message filter. Tune the `.env` thresholds or use `/setflood`; false positives are possible.
- Blocklist and link-lock rules delete matching messages. Test them in a small private group first and keep a clear appeals/moderation process.
- `/report` attempts to notify admins by private message; Telegram may prevent delivery if an admin has not started the bot. Reports are also written to the configured log channel/database.
- Notes, filters, blocklist entries, settings, warnings and logs are stored per group in SQLite.
- The `/purge` command can only delete messages Telegram still permits the bot to delete.
- SQLite is suitable for a small/medium bot on one persistent instance. Use PostgreSQL and a migration plan before scaling to multiple instances.
- Group statistics are based on locally observed join/leave events plus Telegram's live member count when available; they are not historical analytics.
- The `/unban` command is reply-based in this starter. Use Telegram's own member management if you need to unban someone without a message to reply to.
- Inline menu buttons are available from private `/start`. The statistics button shows stats for the current group when invoked from a group message.
- Test in a private test group before adding the bot to a large public community.

## Project structure
```text
saint_guard_bot/
├── saint_guard/
│   ├── __init__.py
│   ├── bot.py
│   └── db.py
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── render.yaml
└── requirements.txt
```

## License
Use and modify this project for your own communities. You are responsible for configuring permissions and complying with Telegram's rules.
