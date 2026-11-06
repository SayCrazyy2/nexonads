import asyncio
import logging
from datetime import datetime, timezone

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    RichBlockTableCell,
    RichMessageButton,
)

from accounts import AccountManager
from broadcast import BroadcastManager, format_duration, parse_duration
from config import ADMIN_ID, API_HASH, API_ID, DB_PATH, SESSIONS_DIR, SUDO_USERS
from database import BotDatabase

logger = logging.getLogger(__name__)
router = Router()
db = BotDatabase(DB_PATH)
am = AccountManager(db, API_ID, API_HASH, SESSIONS_DIR)

MANAGER = "Nexon Ads"
MANAGER_USERNAME = "@Nexon_Ads_Bot"
RUNNING_PROCESSES = {}
_PROCESS_COUNTER = 0


def _next_process_id() -> str:
    global _PROCESS_COUNTER
    _PROCESS_COUNTER += 1
    return f"proc{_PROCESS_COUNTER}"


def _current_processes():
    stale = [
        process_id
        for process_id, info in RUNNING_PROCESSES.items()
        if info["task"].done()
    ]

    for process_id in stale:
        RUNNING_PROCESSES.pop(process_id, None)

    return sorted(
        RUNNING_PROCESSES.items(),
        key=lambda item: item[1]["started_at"],
    )


def _register_process(
    *,
    task: asyncio.Task,
    user_id: int,
    process_type: str,
    account_id: int,
    targets: int,
    delay: float,
    loop_delay: float | None = None,
):
    process_id = _next_process_id()
    RUNNING_PROCESSES[process_id] = {
        "task": task,
        "user_id": user_id,
        "type": process_type,
        "account_id": account_id,
        "targets": targets,
        "delay": delay,
        "loop_delay": loop_delay,
        "started_at": datetime.now(timezone.utc),
    }

    def _cleanup(_):
        RUNNING_PROCESSES.pop(process_id, None)

    task.add_done_callback(_cleanup)
    return process_id


class MenuState(StatesGroup):
    main = State()
    broadcast = State()
    groups = State()
    account_phone = State()
    account_code = State()
    account_password = State()
    folder_link = State()
    schedule = State()


class BroadcastText(StatesGroup):
    setting_text = State()
    loop_delay = State()


def btn(text: str, callback_data: str, style: str = "primary"):
    return RichMessageButton(text=text, style=style, callback_data=callback_data)


def button_row(*buttons):
    return InputRichBlockButtons(buttons=list(buttons), align="center")


def back_row(callback_data: str):
    return button_row(btn("← Back", callback_data, "link"))


def rich_table(headers, rows, *, bordered=True, striped=True, compact=True):
    cells = [[
        RichBlockTableCell(text=str(h), align="center", valign="middle", is_header=True)
        for h in headers
    ]]
    for row in rows:
        cells.append([
            RichBlockTableCell(text=str(v), align="left", valign="middle")
            for v in row
        ])
    return InputRichBlockTable(
        cells=cells,
        is_bordered=bordered,
        is_striped=striped,
        is_compact=compact,
    )


def rich_screen(
    header,
    paragraph,
    table=None,
    button_rows=None,
):
    blocks = [
        InputRichBlockSectionHeading(
            text=header,
            size=2,
        ),
        InputRichBlockParagraph(
            text=paragraph.replace("**", "").replace("`", ""),
        ),
    ]
    if table is not None:
        blocks.append(table)
    if button_rows is not None:
        if isinstance(button_rows, InputRichBlockButtons):
            blocks.append(button_rows)
        else:
            blocks.extend(button_rows)
    return InputRichMessage(blocks=blocks)


def main_menu_message():
    return rich_screen(
        f"🛠️ {MANAGER} — Menu",
        "Manage accounts, folders, groups and broadcasts.",
        button_rows=(
            button_row(btn("📡 Broadcast", "menu_broadcast"), btn("📦 Accounts", "menu_accounts")),
            button_row(btn("⚙️ Settings", "menu_settings"), btn("ℹ️ Info", "menu_info")),
        ),
    )


def accounts_message():
    return rich_screen(
        f"📦 {MANAGER} — Accounts",
        "Add Telegram user accounts and manage their sessions.",
        button_rows=(
            button_row(btn("📋 List", "accounts_list"), btn("➕ Add", "accounts_add", "success")),
            button_row(btn("♻️ Delete", "accounts_delete", "danger")),
            back_row("menu_main"),
        ),
    )


def settings_message():
    return rich_screen(
        f"⚙️ {MANAGER} — Settings",
        "Configure folders, group selection and broadcast behavior.",
        button_rows=(
            button_row(btn("👥 Groups & Folders", "settings_groups")),
            button_row(btn("⏱️ Delay", "settings_delay")),
            back_row("menu_main"),
        ),
    )


def broadcast_message():
    return rich_screen(
        f"📡 {MANAGER} — Broadcast",
        "Send a message to the groups marked as included for a Telegram account.",
        button_rows=(
            button_row(btn("📤 Send Now", "broadcast_now", "success")),
            button_row(btn("⚙️ Processes", "processes_menu")),
            back_row("menu_main"),
        ),
    )


def account_rows():
    accounts = db.get_accounts()
    rows = []
    for index, account in enumerate(accounts, 1):
        account_id, client_key, phone, connected = account
        rows.append([str(index), phone, "Online" if connected else "Saved", str(account_id)])
    return accounts, rows


async def edit(callback, message):
    try:
        await callback.message.edit_text(
            rich_message=message
        )
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def require_approved(message):
    if not db.is_user_approved(message.from_user.id):
        return False
    return True


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    db.add_user(user_id, message.from_user.username, 1 if user_id in SUDO_USERS else 0)
    if not db.is_user_approved(user_id):
        if user_id in SUDO_USERS or user_id == ADMIN_ID:
            db.set_approval(user_id, True, user_id)
        else:
            await message.answer_rich(rich_message=rich_screen(
                f"❌ {MANAGER}",
                "You are not approved to use this bot. Contact an administrator.",
            ))
            return
    await message.answer_rich(rich_message=main_menu_message())
    await state.set_state(MenuState.main)


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    if not await require_approved(message):
        return
    await message.answer_rich(rich_message=rich_screen(
        f"🛠️ {MANAGER} — Help",
        "/start — open the manager\n\nAccounts → Groups & Folders → select included groups → Broadcast.",
        button_rows=back_row("menu_main"),
    ))


@router.callback_query(F.data.in_({"menu_main", "menu_broadcast", "menu_accounts", "menu_settings", "menu_info"}))
async def main_menu(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "menu_main":
        await edit(callback, main_menu_message())
        await state.set_state(MenuState.main)
    elif data == "menu_broadcast":
        await edit(callback, broadcast_message())
        await state.set_state(MenuState.broadcast)
    elif data == "menu_accounts":
        await edit(callback, accounts_message())
        await state.set_state(MenuState.main)
    elif data == "menu_settings":
        await edit(callback, settings_message())
        await state.set_state(MenuState.main)
    else:
        await edit(callback, rich_screen(
            f"ℹ️ {MANAGER} — Info",
            f"Manager: **{MANAGER_USERNAME}**\nAccount type: **Telegram user sessions**",
            button_rows=back_row("menu_main"),
        ))
    await callback.answer()


# ---------------------------------------------------------------------------
# ACCOUNTS
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "accounts_list")
async def accounts_list(callback: types.CallbackQuery):
    accounts, rows = account_rows()
    if not accounts:
        await edit(callback, rich_screen(
            f"📦 {MANAGER} — Accounts",
            "No Telegram accounts have been added.",
            button_rows=(button_row(btn("➕ Add Account", "accounts_add", "success")), back_row("menu_accounts")),
        ))
    else:
        await edit(callback, rich_screen(
            f"📦 {MANAGER} — Accounts",
            f"Total accounts: **{len(accounts)}**",
            rich_table(["#", "Phone", "Status", "ID"], rows),
            (button_row(btn("➕ Add", "accounts_add", "success"), btn("♻️ Delete", "accounts_delete", "danger")),
             button_row(btn("🔄 Refresh", "accounts_list")), back_row("menu_accounts")),
        ))
    await callback.answer()


@router.callback_query(F.data == "accounts_add")
async def accounts_add(callback: types.CallbackQuery, state: FSMContext):
    if not API_ID or not API_HASH:
        await edit(callback, rich_screen(
            f"❌ {MANAGER} — Telegram API",
            "Set API_ID and API_HASH in config.py first. These are Telegram user-account API credentials, not the bot token.",
            button_rows=back_row("menu_accounts"),
        ))
        await callback.answer()
        return
    # Set the FSM state before rendering the prompt so the next message is
    # definitely handled by the phone-login step.
    await state.clear()
    await state.set_state(MenuState.account_phone)

    await edit(callback, rich_screen(
        f"➕ {MANAGER} — Add Account",
        "Enter the Telegram phone number with country code.\n\nExample: `+919876543210`",
        button_rows=back_row("menu_accounts"),
    ))
    await callback.answer()


@router.message(MenuState.account_phone)
async def account_phone(message: types.Message, state: FSMContext):
    # Accept a typed phone number or a Telegram shared-contact message.
    phone = (message.text or "").strip()
    if not phone and message.contact:
        phone = (message.contact.phone_number or "").strip()

    # Telegram can provide a contact without the leading +.
    if phone and not phone.startswith("+"):
        phone = "+" + phone

    if not phone or not phone[1:].replace(" ", "").replace("-", "").isdigit():
        await message.answer_rich(rich_message=rich_screen(
            f"❌ {MANAGER} — Add Account",
            "Use the international format, for example `+919876543210`.",
            button_rows=back_row("menu_accounts"),
        ))
        return
    client_key = "acc_" + "".join(ch for ch in phone if ch.isdigit())
    try:
        result = await am.start_login(client_key, phone)
        if result["authorized"]:
            db.add_account(client_key, phone)
            account = db.get_account(client_key)
            db.set_account_connected(account[0], True)
            await message.answer_rich(rich_message=rich_screen(
                f"✅ {MANAGER} — Account Added",
                f"The session for `{phone}` is already authorized.",
                button_rows=(button_row(btn("👥 Configure Groups", "settings_groups")), back_row("menu_accounts")),
            ))
            await state.set_state(MenuState.main)
            return
        await state.update_data(login_client_key=client_key, login_phone=phone)
        await message.answer_rich(rich_message=rich_screen(
            f"🔐 {MANAGER} — Verification Code",
            "Telegram sent a login code to this account. Enter the code here.",
            button_rows=back_row("menu_accounts"),
        ))
        await state.set_state(MenuState.account_code)
    except Exception as exc:
        logger.exception("Account login start failed")
        await state.clear()
        await message.answer_rich(rich_message=rich_screen(
            f"❌ {MANAGER} — Add Account",
            f"Could not start login:\n`{exc}`\n\nTap Add Account and try again.",
            button_rows=back_row("menu_accounts"),
        ))


@router.message(MenuState.account_code)
async def account_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        result = await am.sign_in_code(data["login_client_key"], (message.text or "").strip())
        if result["password_required"]:
            await message.answer_rich(rich_message=rich_screen(
                f"🔐 {MANAGER} — Two-Step Verification",
                "This account has Telegram 2FA enabled. Enter the Telegram password.",
                button_rows=back_row("menu_accounts"),
            ))
            await state.set_state(MenuState.account_password)
            return
        db.add_account(data["login_client_key"], data["login_phone"])
        account = db.get_account(data["login_client_key"])
        db.set_account_connected(account[0], True)
        await message.answer_rich(rich_message=rich_screen(
            f"✅ {MANAGER} — Account Added",
            f"`{data['login_phone']}` is now authorized.",
            button_rows=(button_row(btn("👥 Configure Groups", "settings_groups")), back_row("menu_accounts")),
        ))
        await state.set_state(MenuState.main)
    except Exception as exc:
        await message.answer_rich(rich_message=rich_screen(
            f"❌ {MANAGER} — Verification",
            f"Login failed:\n`{exc}`",
            button_rows=back_row("menu_accounts"),
        ))


@router.message(MenuState.account_password)
async def account_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        await am.sign_in_password(data["login_client_key"], message.text or "")
        db.add_account(data["login_client_key"], data["login_phone"])
        account = db.get_account(data["login_client_key"])
        db.set_account_connected(account[0], True)
        await message.answer_rich(rich_message=rich_screen(
            f"✅ {MANAGER} — Account Added",
            f"`{data['login_phone']}` is authorized and ready.",
            button_rows=(button_row(btn("👥 Configure Groups", "settings_groups")), back_row("menu_accounts")),
        ))
        await state.set_state(MenuState.main)
    except Exception as exc:
        await message.answer_rich(rich_message=rich_screen(
            f"❌ {MANAGER} — 2FA",
            f"Password verification failed:\n`{exc}`",
            button_rows=back_row("menu_accounts"),
        ))


@router.callback_query(F.data == "accounts_delete")
async def accounts_delete(callback: types.CallbackQuery):
    accounts = db.get_accounts()
    if not accounts:
        await edit(callback, rich_screen(f"📦 {MANAGER} — Accounts", "No accounts to delete.", button_rows=back_row("menu_accounts")))
    else:
        rows = []
        buttons = []
        for account_id, client_key, phone, connected in accounts:
            rows.append([str(account_id), phone, "Online" if connected else "Saved"])
            buttons.append(btn(f"♻️ {phone}", f"account_delete:{account_id}", "danger"))
        await edit(callback, rich_screen(
            f"♻️ {MANAGER} — Delete Account",
            "Select an account. Its database record and local Telethon session will be removed.",
            rich_table(["ID", "Phone", "Status"], rows),
            tuple(button_row(b) for b in buttons) + (back_row("menu_accounts"),),
        ))
    await callback.answer()


@router.callback_query(F.data.startswith("account_delete:"))
async def account_delete(callback: types.CallbackQuery):
    account_id = int(callback.data.split(":", 1)[1])
    account = db.get_account_by_id(account_id)
    if account:
        _, client_key, _, _ = account
        client = am.clients.pop(client_key, None)
        if client:
            await client.disconnect()
        db.remove_account(client_key)
    await callback.answer("Account deleted")
    await accounts_list(callback)


# ---------------------------------------------------------------------------
# FOLDERS / GROUPS
# ---------------------------------------------------------------------------

async def render_account_picker(callback, back="menu_settings"):
    accounts = db.get_accounts()
    if not accounts:
        await edit(callback, rich_screen(
            f"👥 {MANAGER} — Groups",
            "Add a Telegram account first.",
            button_rows=(button_row(btn("📦 Accounts", "menu_accounts")), back_row(back)),
        ))
        return
    rows = [[str(a[0]), a[2], "Online" if a[3] else "Saved"] for a in accounts]
    buttons = [button_row(btn(f"📱 {a[2]}", f"groups_account:{a[0]}")) for a in accounts]
    await edit(callback, rich_screen(
        f"👥 {MANAGER} — Select Account",
        "Choose which Telegram account's folders and groups you want to manage.",
        rich_table(["ID", "Phone", "Status"], rows),
        tuple(buttons) + (back_row(back),),
    ))


@router.callback_query(F.data == "settings_groups")
async def settings_groups(callback: types.CallbackQuery, state: FSMContext):
    await render_account_picker(callback)
    await state.set_state(MenuState.groups)
    await callback.answer()


async def render_folders(callback, account_id: int):
    account = db.get_account_by_id(account_id)
    if not account:
        await render_account_picker(callback)
        return
    _, client_key, phone, connected = account
    try:
        await am.sync_all_folders(client_key, account_id)
        folders = db.get_folders(account_id)
    except Exception as exc:
        await edit(callback, rich_screen(
            f"❌ {MANAGER} — Folders",
            f"Could not read Telegram folders:\n`{exc}`",
            button_rows=back_row("settings_groups"),
        ))
        return

    rows = []
    buttons = []
    for row in folders:
        folder_db_id, _, folder_id, name, invite = row
        groups = db.get_folder_groups(folder_db_id)
        included = sum(1 for g in groups if g[5])
        rows.append([str(folder_id), name, f"{included}/{len(groups)}"])
        buttons.append(button_row(btn(f"📁 {name}", f"folder_open:{folder_db_id}")))

    if not folders:
        paragraph = f"Account: `{phone}`\n\nNo folders were found on this account. You can import a shared folder link."
    else:
        paragraph = f"Account: `{phone}`\n\nSelect a folder, or import another folder using an `addlist` link."
    await edit(callback, rich_screen(
        f"📁 {MANAGER} — Folders",
        paragraph,
        rich_table(["ID", "Folder", "Included"], rows) if rows else None,
        tuple(buttons) + (
            button_row(btn("🔗 Add Folder Link", f"folder_add:{account_id}", "success")),
            button_row(btn("🔄 Refresh", f"groups_account:{account_id}")),
            back_row("settings_groups"),
        ),
    ))


@router.callback_query(F.data.startswith("groups_account:"))
async def groups_account(callback: types.CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split(":", 1)[1])
    await state.update_data(selected_account_id=account_id)
    await render_folders(callback, account_id)
    await callback.answer()


@router.callback_query(F.data.startswith("folder_open:"))
async def folder_open(callback: types.CallbackQuery):
    folder_db_id = int(callback.data.split(":", 1)[1])
    folder = db.get_folder(folder_db_id)
    if not folder:
        await callback.answer("Folder not found", show_alert=True)
        return
    _, account_id, folder_id, name, invite = folder
    account = db.get_account_by_id(account_id)
    try:
        await am.sync_all_folders(account[1], account_id)
    except Exception:
        pass
    groups = db.get_folder_groups(folder_db_id)
    rows = []
    buttons = []
    for group_db_id, _, chat_id, title, username, included in groups:
        rows.append(["✓" if included else "✗", title, username or "—"])
        icon = "✓" if included else "✗"
        style = "success" if included else "danger"
        buttons.append(button_row(btn(f"{icon} {title[:38]}", f"group_toggle:{group_db_id}", style)))

    await edit(callback, rich_screen(
        f"📁 {MANAGER} — {name}",
        f"Select each group to toggle Include / Exclude.\nIncluded: **{sum(1 for g in groups if g[5])}** / {len(groups)}",
        rich_table(["Use", "Group", "Username"], rows) if rows else None,
        tuple(buttons) + (back_row(f"groups_account:{account_id}"),),
    ))
    await callback.answer()


@router.callback_query(F.data.startswith("group_toggle:"))
async def group_toggle(callback: types.CallbackQuery):
    group_db_id = int(callback.data.split(":", 1)[1])
    group = db.conn.execute("SELECT folder_id FROM folder_groups WHERE id=?", (group_db_id,)).fetchone()
    if not group:
        await callback.answer("Group not found", show_alert=True)
        return
    db.toggle_group(group_db_id)
    folder = db.get_folder(group[0])
    await callback.answer("Selection updated")
    await folder_open(callback)


@router.callback_query(F.data.startswith("folder_add:"))
async def folder_add(callback: types.CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split(":", 1)[1])
    await state.update_data(selected_account_id=account_id)
    await edit(callback, rich_screen(
        f"🔗 {MANAGER} — Add Folder",
        "Send a Telegram shared-folder link.\n\nExample:\n`https://t.me/addlist/XXXXXXXX`",
        button_rows=back_row(f"groups_account:{account_id}"),
    ))
    await state.set_state(MenuState.folder_link)
    await callback.answer()


@router.message(MenuState.folder_link)
async def folder_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("selected_account_id")
    account = db.get_account_by_id(account_id) if account_id else None
    link = (message.text or "").strip()
    if not account:
        await message.answer_rich(rich_message=rich_screen(f"❌ {MANAGER}", "Select an account first.", button_rows=back_row("settings_groups")))
        return
    try:
        folder = await am.import_folder_link(account[1], link)
        row, _ = await am.sync_folder(account[1], account_id, folder, link)
        await message.answer_rich(rich_message=rich_screen(
            f"✅ {MANAGER} — Folder Added",
            f"Folder **{row[3]}** was imported.\n\nYou can now select which groups are included.",
            button_rows=(button_row(btn("📁 Open Folder", f"folder_open:{row[0]}", "success")), back_row(f"groups_account:{account_id}")),
        ))
        await state.set_state(MenuState.groups)
    except Exception as exc:
        logger.exception("Folder import failed")
        await message.answer_rich(rich_message=rich_screen(
            f"❌ {MANAGER} — Folder Import",
            f"Could not import the folder:\n`{exc}`",
            button_rows=back_row(f"groups_account:{account_id}"),
        ))


# ---------------------------------------------------------------------------
# DELAY
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "settings_delay")
async def settings_delay(callback: types.CallbackQuery, state: FSMContext):
    setting = db.get_broadcast_setting(callback.from_user.id)

    current_delay = (
        setting[2]
        if setting and setting[2] is not None
        else 1.0
    )

    await edit(
        callback,
        rich_screen(
            f"⏱️ {MANAGER} — Delay",
            (
                f"Current delay: {format_duration(current_delay)}\n\n"
                "Send a custom delay such as:\n"
                "• 5s — 5 seconds\n"
                "• 10m — 10 minutes\n"
                "• 2h — 2 hours\n"
                "• 1d — 1 day\n"
                "• 1h 30m — 1 hour 30 minutes\n\n"
                "The delay is applied between each group."
            ),
            button_rows=(
                button_row(
                    btn("1s", "delay:1"),
                    btn("5s", "delay:5"),
                    btn("10s", "delay:10"),
                ),
                button_row(
                    btn("1m", "delay:60"),
                    btn("5m", "delay:300"),
                    btn("10m", "delay:600"),
                ),
                button_row(
                    btn("1h", "delay:3600"),
                    btn("1d", "delay:86400"),
                ),
                button_row(
                    btn("✏️ Custom", "delay_custom", "success"),
                ),
                back_row("menu_settings"),
            ),
        ),
    )

    await state.set_state(MenuState.schedule)
    await callback.answer()


@router.callback_query(F.data.startswith("delay:"))
async def set_delay(callback: types.CallbackQuery):
    value = float(
        callback.data.split(":", 1)[1]
    )

    db.add_broadcast_setting(
        callback.from_user.id,
        delay=value,
    )

    await callback.answer(
        f"Delay set to {format_duration(value)}"
    )

    setting = db.get_broadcast_setting(
        callback.from_user.id
    )

    current_delay = (
        setting[2]
        if setting and setting[2] is not None
        else value
    )

    await edit(
        callback,
        rich_screen(
            f"⏱️ {MANAGER} — Delay",
            (
                f"Current delay: {format_duration(current_delay)}\n\n"
                "Choose another delay or use Custom."
            ),
            button_rows=(
                button_row(
                    btn("1s", "delay:1"),
                    btn("5s", "delay:5"),
                    btn("10s", "delay:10"),
                ),
                button_row(
                    btn("1m", "delay:60"),
                    btn("5m", "delay:300"),
                    btn("10m", "delay:600"),
                ),
                button_row(
                    btn("1h", "delay:3600"),
                    btn("1d", "delay:86400"),
                ),
                button_row(
                    btn("✏️ Custom", "delay_custom", "success"),
                ),
                back_row("menu_settings"),
            ),
        ),
    )


@router.message(MenuState.schedule)
async def process_custom_delay(
    message: types.Message,
    state: FSMContext,
):
    data = await state.get_data()

    if not data.get("waiting_for_delay"):
        return

    value = (message.text or "").strip()

    try:
        seconds = parse_duration(value)

        if seconds <= 0:
            raise ValueError(
                "Delay must be greater than zero."
            )

        db.add_broadcast_setting(
            message.from_user.id,
            delay=seconds,
        )

        await message.answer_rich(
            rich_message=rich_screen(
                f"✅ {MANAGER} — Delay Updated",
                (
                    f"Delay: {format_duration(seconds)}\n\n"
                    "This delay will be used between each group."
                ),
                button_rows=back_row("menu_settings"),
            )
        )

        await state.clear()

    except ValueError as exc:
        await message.answer_rich(
            rich_message=rich_screen(
                f"❌ {MANAGER} — Invalid Delay",
                (
                    f"{exc}\n\n"
                    "Examples:\n"
                    "5s\n"
                    "10m\n"
                    "2h\n"
                    "1d\n"
                    "1h 30m"
                ),
                button_rows=back_row("settings_delay"),
            )
        )


# ---------------------------------------------------------------------------
# BROADCAST
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "broadcast_now")
async def broadcast_now(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    accounts = db.get_accounts()

    if not accounts:
        await edit(
            callback,
            rich_screen(
                f"❌ {MANAGER} — Broadcast",
                "Add a Telegram account before broadcasting.",
                button_rows=back_row("menu_broadcast"),
            ),
        )
        await callback.answer()
        return

    buttons = tuple(
        button_row(
            btn(
                f"📱 {account[2]}",
                f"broadcast_account:{account[0]}",
            )
        )
        for account in accounts
    )

    await edit(
        callback,
        rich_screen(
            f"📡 {MANAGER} — Select Account",
            "The broadcast will use the groups included for the selected account.",
            button_rows=buttons + (
                back_row("menu_broadcast"),
            ),
        ),
    )

    await callback.answer()


@router.callback_query(F.data.startswith("broadcast_account:"))
async def broadcast_account(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    account_id = int(
        callback.data.split(":", 1)[1]
    )

    await state.clear()

    await state.update_data(
        broadcast_account_id=account_id
    )

    setting = db.get_broadcast_setting(
        callback.from_user.id
    )

    delay = (
        setting[2]
        if setting and setting[2] is not None
        else 1.0
    )

    targets = db.get_included_groups(account_id)

    await edit(
        callback,
        rich_screen(
            f"📤 {MANAGER} — Send Broadcast",
            (
                f"Included groups: {len(targets)}\n"
                f"Delay: {format_duration(delay)}\n\n"
                "Enter your broadcast message."
            ),
            button_rows=back_row("menu_broadcast"),
        ),
    )

    await state.set_state(
        BroadcastText.setting_text
    )

    await callback.answer()


@router.message(BroadcastText.setting_text)
async def process_broadcast_text(
    message: types.Message,
    state: FSMContext,
):
    data = await state.get_data()

    account_id = data.get(
        "broadcast_account_id"
    )

    if not account_id:
        await message.answer_rich(
            rich_message=rich_screen(
                f"❌ {MANAGER}",
                "No broadcast account selected.",
                button_rows=back_row(
                    "menu_broadcast"
                ),
            )
        )
        return

    # Preserve the user's formatting where Telegram provides entities.
    text = (
        message.html_text
        if message.entities
        else (message.text or "")
    )

    if not text.strip():
        await message.answer_rich(
            rich_message=rich_screen(
                f"❌ {MANAGER} — Broadcast",
                "The broadcast message cannot be empty.",
                button_rows=back_row(
                    "menu_broadcast"
                ),
            )
        )
        return

    targets = db.get_included_groups(
        account_id
    )

    if not targets:
        await message.answer_rich(
            rich_message=rich_screen(
                f"❌ {MANAGER} — Broadcast",
                (
                    "No groups are currently included.\n\n"
                    "Open Groups & Folders and enable at least one group."
                ),
                button_rows=(
                    button_row(
                        btn(
                            "👥 Groups",
                            "settings_groups",
                        )
                    ),
                    back_row("menu_broadcast"),
                ),
            )
        )

        await state.set_state(
            MenuState.main
        )
        return

    setting = db.get_broadcast_setting(
        message.from_user.id
    )

    delay = (
        setting[2]
        if setting and setting[2] is not None
        else 1.0
    )

    await state.update_data(
        broadcast_message=text,
        broadcast_delay=delay,
    )

    await message.answer_rich(
        rich_message=rich_screen(
            f"🔁 {MANAGER} — Loop Broadcast",
            (
                f"Targets: {len(targets)}\n"
                f"Delay between groups: {format_duration(delay)}\n\n"
                "Do you want to repeat this broadcast?"
            ),
            button_rows=(
                button_row(
                    btn(
                        "📤 Send Once",
                        "broadcast_once",
                        "success",
                    ),
                    btn(
                        "🔁 Enable Loop",
                        "broadcast_loop",
                    ),
                ),
                button_row(
                    btn(
                        "⏱️ Change Delay",
                        "settings_delay",
                    ),
                ),
                back_row("menu_broadcast"),
            ),
        )
    )


@router.callback_query(F.data == "processes_menu")
async def processes_menu(callback: types.CallbackQuery):
    await _show_processes_menu(callback)
    await callback.answer()


async def _show_processes_menu(callback: types.CallbackQuery):
    processes = _current_processes()

    if not processes:
        await edit(
            callback,
            rich_screen(
                f"⚙️ {MANAGER} — Processes",
                "No running broadcasts or loops.",
                button_rows=back_row("menu_broadcast"),
            ),
        )
        return

    rows = []
    buttons = []

    for process_id, info in processes:
        account = db.get_account_by_id(info["account_id"])
        phone = account[2] if account else f"#{info['account_id']}"
        rows.append([process_id, info["type"], phone, "Running"])
        buttons.append(
            button_row(
                btn(f"ℹ️ {process_id}", f"process_view:{process_id}", "link"),
                btn(f"⛔ Stop {process_id}", f"process_stop:{process_id}", "danger"),
            )
        )

    await edit(
        callback,
        rich_screen(
            f"⚙️ {MANAGER} — Processes",
            "Manage running broadcasts and loops.",
            rich_table(["ID", "Type", "Account", "State"], rows),
            button_rows=tuple(buttons) + (back_row("menu_broadcast"),),
        ),
    )


@router.callback_query(F.data.startswith("process_view:"))
async def process_view(callback: types.CallbackQuery):
    process_id = callback.data.split(":", 1)[1]
    info = RUNNING_PROCESSES.get(process_id)

    if not info or info["task"].done():
        RUNNING_PROCESSES.pop(process_id, None)
        await callback.answer("Process is no longer running.", show_alert=True)
        await _show_processes_menu(callback)
        return

    account = db.get_account_by_id(info["account_id"])
    phone = account[2] if account else f"#{info['account_id']}"
    elapsed = datetime.now(timezone.utc) - info["started_at"]

    details = (
        f"ID: {process_id}\n"
        f"Type: {info['type']}\n"
        f"Account: {phone}\n"
        f"Targets: {info['targets']}\n"
        f"Delay: {format_duration(info['delay'])}\n"
    )

    if info["loop_delay"] is not None:
        details += f"Loop interval: {format_duration(info['loop_delay'])}\n"

    details += f"Running for: {format_duration(elapsed.total_seconds())}"

    await edit(
        callback,
        rich_screen(
            f"ℹ️ {MANAGER} — Process Details",
            details,
            button_rows=(
                button_row(
                    btn("⛔ Stop", f"process_stop:{process_id}", "danger"),
                    btn("🔄 Refresh", f"process_view:{process_id}"),
                ),
                back_row("processes_menu"),
            ),
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("process_stop:"))
async def process_stop(callback: types.CallbackQuery):
    process_id = callback.data.split(":", 1)[1]
    info = RUNNING_PROCESSES.get(process_id)

    if not info or info["task"].done():
        RUNNING_PROCESSES.pop(process_id, None)
        await callback.answer("Process already stopped.", show_alert=True)
        await _show_processes_menu(callback)
        return

    info["task"].cancel()
    await callback.answer(f"Stopping {process_id}...")
    await _show_processes_menu(callback)


@router.callback_query(F.data == "broadcast_once")
async def broadcast_once(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()

    account_id = data.get(
        "broadcast_account_id"
    )

    message_text = data.get(
        "broadcast_message"
    )

    if not account_id or not message_text:
        await callback.answer(
            "Broadcast data expired. Start again.",
            show_alert=True,
        )
        await state.clear()
        return

    setting = db.get_broadcast_setting(
        callback.from_user.id
    )

    delay = (
        setting[2]
        if setting and setting[2] is not None
        else 1.0
    )

    targets = db.get_included_groups(
        account_id
    )

    bm = BroadcastManager(
        db,
        API_ID,
        API_HASH,
        SESSIONS_DIR,
        account_manager=am,
    )

    async def run_broadcast():
        try:
            results = await bm.broadcast_to_account(
                account_id=account_id,
                message=message_text,
                delay=delay,
                loop=False,
            )

            logger.info(
                "One-time broadcast completed: "
                "account=%s results=%s",
                account_id,
                len(results),
            )

        except asyncio.CancelledError:
            logger.info(
                "One-time broadcast cancelled: account=%s",
                account_id,
            )

        except Exception:
            logger.exception(
                "One-time broadcast failed: account=%s",
                account_id,
            )

    process_id = _register_process(
        task=asyncio.create_task(run_broadcast()),
        user_id=callback.from_user.id,
        process_type="Broadcast",
        account_id=account_id,
        targets=len(targets),
        delay=delay,
    )

    await callback.answer(
        "Broadcast started"
    )

    await edit(
        callback,
        rich_screen(
            f"🔄 {MANAGER} — Broadcast Started",
            (
                f"Targets: {len(targets)}\n"
                f"Delay: {format_duration(delay)}\n"
                f"Process ID: {process_id}\n\n"
                "The broadcast is running asynchronously."
            ),
            button_rows=(
                button_row(
                    btn(
                        "📡 Broadcast",
                        "menu_broadcast",
                    ),
                    btn(
                        "⚙️ Processes",
                        "processes_menu",
                    ),
                    btn(
                        "🏠 Main Menu",
                        "menu_main",
                        "link",
                    ),
                ),
            ),
        ),
    )

    await state.set_state(
        MenuState.main
    )


@router.callback_query(F.data == "broadcast_loop")
async def broadcast_loop(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    await edit(
        callback,
        rich_screen(
            f"🔁 {MANAGER} — Loop Interval",
            (
                "Enter how long to wait between complete "
                "broadcast rounds.\n\n"
                "Examples:\n"
                "30s\n"
                "5m\n"
                "1h\n"
                "1d\n"
                "1h 30m\n\n"
                "The broadcast will continue until the bot is stopped."
            ),
            button_rows=back_row(
                "menu_broadcast"
            ),
        ),
    )

    await state.set_state(
        BroadcastText.loop_delay
    )

    await callback.answer()


@router.message(BroadcastText.loop_delay)
async def process_loop_delay(
    message: types.Message,
    state: FSMContext,
):
    data = await state.get_data()

    account_id = data.get(
        "broadcast_account_id"
    )

    message_text = data.get(
        "broadcast_message"
    )

    if not account_id or not message_text:
        await message.answer_rich(
            rich_message=rich_screen(
                f"❌ {MANAGER}",
                "Broadcast data expired. Start again.",
                button_rows=back_row(
                    "menu_broadcast"
                ),
            )
        )
        await state.clear()
        return

    value = (message.text or "").strip()

    try:
        loop_delay = parse_duration(value)

        if loop_delay <= 0:
            raise ValueError(
                "Loop interval must be greater than zero."
            )

    except ValueError as exc:
        await message.answer_rich(
            rich_message=rich_screen(
                f"❌ {MANAGER} — Invalid Loop Interval",
                (
                    f"{exc}\n\n"
                    "Examples:\n"
                    "30s\n"
                    "5m\n"
                    "1h\n"
                    "1d\n"
                    "1h 30m"
                ),
                button_rows=back_row(
                    "menu_broadcast"
                ),
            )
        )
        return

    setting = db.get_broadcast_setting(
        message.from_user.id
    )

    delay = (
        setting[2]
        if setting and setting[2] is not None
        else 1.0
    )

    db.add_broadcast_setting(
        message.from_user.id,
        delay=delay,
        loop_enabled=1,
        loop_delay=loop_delay,
    )

    targets = db.get_included_groups(
        account_id
    )

    bm = BroadcastManager(
        db,
        API_ID,
        API_HASH,
        SESSIONS_DIR,
        account_manager=am,
    )

    async def run_loop():
        try:
            results = await bm.broadcast_to_account(
                account_id=account_id,
                message=message_text,
                delay=delay,
                loop=True,
                loop_delay=loop_delay,
            )

            logger.info(
                "Looping broadcast finished: "
                "account=%s results=%s",
                account_id,
                len(results),
            )

        except asyncio.CancelledError:
            logger.info(
                "Looping broadcast cancelled: account=%s",
                account_id,
            )

        except Exception:
            logger.exception(
                "Looping broadcast failed: account=%s",
                account_id,
            )

    process_id = _register_process(
        task=asyncio.create_task(run_loop()),
        user_id=message.from_user.id,
        process_type="Loop",
        account_id=account_id,
        targets=len(targets),
        delay=delay,
        loop_delay=loop_delay,
    )

    await message.answer_rich(
        rich_message=rich_screen(
            f"🔁 {MANAGER} — Loop Broadcast Started",
            (
                f"Targets: {len(targets)}\n"
                f"Delay between groups: {format_duration(delay)}\n"
                f"Loop interval: {format_duration(loop_delay)}\n"
                f"Process ID: {process_id}\n\n"
                "The broadcast will repeat continuously."
            ),
            button_rows=(
                button_row(
                    btn(
                        "📡 Broadcast",
                        "menu_broadcast",
                    ),
                    btn(
                        "⚙️ Processes",
                        "processes_menu",
                    ),
                    btn(
                        "🏠 Main Menu",
                        "menu_main",
                        "link",
                    ),
                ),
            ),
        )
    )

    await state.set_state(
        MenuState.main
    )


# ---------------------------------------------------------------------------
# MENU CALLBACKS
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "menu_settings")
async def menu_settings_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    await edit(
        callback,
        settings_message(),
    )

    await state.set_state(
        MenuState.main
    )

    await callback.answer()


@router.callback_query(F.data == "menu_accounts")
async def menu_accounts_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    await edit(
        callback,
        accounts_message(),
    )

    await state.set_state(
        MenuState.main
    )

    await callback.answer()


@router.callback_query(F.data == "menu_broadcast")
async def menu_broadcast_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    await edit(
        callback,
        broadcast_message(),
    )

    await state.set_state(
        MenuState.broadcast
    )

    await callback.answer()