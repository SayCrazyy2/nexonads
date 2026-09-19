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

1. Copy the four Python files over the existing project files.
2. Put your existing bot token in `config.py`.
3. Set `API_ID` and `API_HASH` from Telegram's developer portal.
4. Keep the `sessions/` directory writable.
5. Install/update Aiogram and Telethon.
6. Start the bot.

## Important

Existing SQLite data is retained. The new `folders` and `folder_groups` tables are created automatically.

A shared `addlist` folder is imported into the Telegram user account first. Telegram then exposes it as a dialog folder; the bot synchronizes that folder into its own database so the include/exclude state is independent and persistent.
