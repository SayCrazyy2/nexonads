# Nexon Ads — Folder/Group Selection Update

This update replaces the old string-based group include/exclude system with:

- Telegram user accounts with phone/code/2FA login.
- Native Telegram dialog-folder discovery through `messages.getDialogFilters`.
- Shared-folder import through `https://t.me/addlist/<slug>`.
- Per-account folder persistence.
- Per-folder group persistence.
- Include/exclude toggle for every group.
- Broadcasts that target only groups marked included.
- Rich Message tables and Rich Button rows for the manager UI.

## Setup

1. Copy `.env.example` to `.env` and fill in your values.
2. Set `BOT_TOKEN`, `ADMIN_ID`, `API_ID`, and `API_HASH`.
3. Keep `SESSIONS_DIR` writable.
4. Install dependencies from `requirements.txt`.
5. Start the bot with `python main.py`.

### Environment variables

Required:

- `BOT_TOKEN`
- `ADMIN_ID`
- `API_ID`
- `API_HASH`

Optional:

- `SUDO_USERS` (comma-separated user IDs, defaults to `ADMIN_ID`)
- `DB_PATH` (default `data/bot.db`)
- `SESSIONS_DIR` (default `sessions`)
- `DEFAULT_DELAY` (default `1s`)
- `DEFAULT_LOOP_DELAY` (default `1h`)
- `DEFAULT_SCHEDULE`
- `USE_RICH_MARKDOWN` (default `true`)

Railway bucket (S3-compatible) optional persistence:

- `RAILWAY_BUCKET_ENDPOINT`
- `RAILWAY_BUCKET_NAME`
- `RAILWAY_BUCKET_ACCESS_KEY`
- `RAILWAY_BUCKET_SECRET_KEY`
- `RAILWAY_BUCKET_REGION` (optional)
- `RAILWAY_BUCKET_PREFIX` (optional)

When all required Railway bucket variables are set, the bot restores the SQLite database and Telethon sessions from the bucket on startup and syncs local changes back on shutdown. If bucket access fails, the bot continues with local storage.

### Railway bucket notes

1. Create a Railway Bucket and copy its S3 endpoint, bucket name, access key, and secret key.
2. Add the six `RAILWAY_BUCKET_*` variables in your Railway service.
3. Optionally set `RAILWAY_BUCKET_PREFIX` to isolate environments (for example `prod/nexonads`).
4. Do not store `.env` in the bucket. Only the SQLite DB artifacts and Telethon session files are synced.

## Important

Existing SQLite data is retained. The new `folders` and `folder_groups` tables are created automatically.

A shared `addlist` folder is imported into the Telegram user account first. Telegram then exposes it as a dialog folder; the bot synchronizes that folder into its own database so the include/exclude state is independent and persistent.
