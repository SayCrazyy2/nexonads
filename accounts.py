import logging
import os
import re
from urllib.parse import urlparse

from telethon import TelegramClient, functions, types
from telethon.errors import SessionPasswordNeededError

from database import BotDatabase

logger = logging.getLogger(__name__)


class AccountManager:
    def __init__(self, db: BotDatabase, api_id: int, api_hash: str, sessions_dir="sessions"):
        self.db = db
        self.api_id = api_id
        self.api_hash = api_hash
        self.sessions_dir = sessions_dir
        os.makedirs(sessions_dir, exist_ok=True)
        self.clients = {}
        self.pending = {}

    def session_path(self, client_key: str):
        return os.path.join(self.sessions_dir, client_key)

    async def _client(self, client_key):
        if client_key in self.clients:
            return self.clients[client_key]
        client = TelegramClient(
            self.session_path(client_key),
            self.api_id,
            self.api_hash,
            device_model="TelegramBot",
            system_version="4.0.0",
            app_version="1.0.0",
        )
        await client.connect()
        self.clients[client_key] = client
        return client

    async def start_login(self, client_key: str, phone: str):
        client = await self._client(client_key)
        if await client.is_user_authorized():
            return {"authorized": True, "client": client}
        sent = await client.send_code_request(phone)
        self.pending[client_key] = {
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
        }
        return {"authorized": False, "client": client}

    async def sign_in_code(self, client_key: str, code: str):
        pending = self.pending.get(client_key)
        if not pending:
            raise RuntimeError("No pending login for this account")
        client = await self._client(client_key)
        try:
            await client.sign_in(
                pending["phone"],
                code,
                phone_code_hash=pending["phone_code_hash"],
            )
            self.pending.pop(client_key, None)
            return {"authorized": True, "password_required": False}
        except SessionPasswordNeededError:
            return {"authorized": False, "password_required": True}

    async def sign_in_password(self, client_key: str, password: str):
        client = await self._client(client_key)
        await client.sign_in(password=password)
        self.pending.pop(client_key, None)
        return True

    async def get_client(self, client_key: str):
        client = await self._client(client_key)
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram account is not authorized")
        return client

    async def get_me(self, client_key):
        client = await self.get_client(client_key)
        return await client.get_me()

    async def get_dialogs(self, client_key: str):
        client = await self.get_client(client_key)
        return await client.get_dialogs()


    async def get_folder_dialogs(self, client_key: str, folder_id: int):
        client = await self.get_client(client_key)

        # Do not use client.get_dialogs(folder=folder_id).
        # Some Telethon/Telegram combinations return FolderIdInvalidError
        # for custom dialog-filter IDs.
        dialogs = await client.get_dialogs()

        filters = await self.get_dialog_filters(client_key)

        selected_filter = None
        for dialog_filter in filters:
            if int(getattr(dialog_filter, "id", -1)) == int(folder_id):
                selected_filter = dialog_filter
                break

        if selected_filter is None:
            return []

        include_peers = getattr(selected_filter, "include_peers", []) or []
        exclude_peers = getattr(selected_filter, "exclude_peers", []) or []
        pinned_peers = getattr(selected_filter, "pinned_peers", []) or []

        async def peer_key(peer):
            try:
                entity = await client.get_entity(peer)
                return int(getattr(entity, "id", 0))
            except Exception:
                return None

        include_ids = set()
        exclude_ids = set()
        pinned_ids = set()

        for peer in include_peers:
            value = await peer_key(peer)
            if value is not None:
                include_ids.add(value)

        for peer in exclude_peers:
            value = await peer_key(peer)
            if value is not None:
                    exclude_ids.add(value)

        for peer in pinned_peers:
            value = await peer_key(peer)
            if value is not None:
                pinned_ids.add(value)

        result = []

        for dialog in dialogs:
            entity = dialog.entity
            chat_id = int(getattr(entity, "id", 0))

            # Only groups/supergroups/channels.
            if not (dialog.is_group or dialog.is_channel):
                continue

            # Telegram folder semantics:
            # explicitly excluded peers are never part of the folder.
            if chat_id in exclude_ids:
                continue

            # Explicitly included/pinned peers belong to the folder.
            if chat_id in include_ids or chat_id in pinned_ids:
                result.append(dialog)
                continue

            # If the filter has no explicit include peers, don't invent
            # membership for unrelated dialogs.
            if not include_ids:
                continue

        return result

    async def get_dialog_filters(self, client_key: str):
        client = await self.get_client(client_key)

        result = await client(
            functions.messages.GetDialogFiltersRequest()
        )

        filters = []

        for item in getattr(result, "filters", []):
            folder_id = getattr(item, "id", None)

            if folder_id is None:
                continue

            filters.append(item)

        return filters

    @staticmethod
    def extract_addlist_slug(link: str):
        value = link.strip()
        if value.startswith("tg://addlist?"):
            match = re.search(r"(?:^|&)slug=([^&]+)", value)
            return match.group(1) if match else None
        parsed = urlparse(value)
        path = parsed.path.rstrip("/")
        match = re.search(r"/addlist/([A-Za-z0-9_-]+)$", path)
        return match.group(1) if match else None

    async def import_folder_link(self, client_key: str, link: str):
        slug = self.extract_addlist_slug(link)
        if not slug:
            raise ValueError("Invalid folder link. Expected https://t.me/addlist/<slug>")

        client = await self.get_client(client_key)
        invite = await client(functions.chatlists.CheckChatlistInviteRequest(slug=slug))

        if isinstance(invite, types.chatlists.ChatlistInviteAlready):
            folder_id = invite.filter_id
            title = f"Imported folder {folder_id}"
        else:
            peers = []
            for peer in getattr(invite, "peers", []):
                try:
                    peers.append(await client.get_input_entity(peer))
                except Exception:
                    logger.warning("Could not resolve shared-folder peer %r", peer)
            if not peers:
                raise ValueError("The shared folder contains no importable chats")

            await client(functions.chatlists.JoinChatlistInviteRequest(
                slug=slug,
                peers=peers,
            ))
            folder_id = None
            title = getattr(getattr(invite, "title", None), "text", None) or "Imported folder"

        # Telegram stores imported shared folders as dialog filters. Re-fetch to
        # obtain the actual local folder ID after joining.
        filters = await self.get_dialog_filters(client_key)
        for item in filters:
            if folder_id is not None and getattr(item, "id", None) == folder_id:
                return item
            item_title = getattr(getattr(item, "title", None), "text", None) or getattr(item, "title", None)
            if item_title == title:
                return item

        raise RuntimeError("Folder was imported, but Telegram did not return it in the folder list")

    async def sync_folder(self, client_key: str, account_id: int, folder, invite_link=None):
        folder_id = int(folder.id)
        title_obj = getattr(folder, "title", None)
        title = (
            getattr(title_obj, "text", None)
            or str(title_obj or f"Folder {folder_id}")
        )

        row = self.db.upsert_folder(
            account_id,
            folder_id,
            title,
            invite_link,
        )

        dialogs = await self.get_folder_dialogs(
            client_key,
            folder_id,
        )

        groups = []
        seen_chat_ids = set()

        for dialog in dialogs:
            entity = dialog.entity

            # Use the real Telegram entity ID for deduplication.
            chat_id = getattr(entity, "id", None)
    
            if chat_id is None:
                continue

            chat_id = int(chat_id)

            # Same Telegram chat can appear more than once
            # because of folder include/pinned rules.
            if chat_id in seen_chat_ids:
                continue

            seen_chat_ids.add(chat_id)
    
            username = getattr(entity, "username", None)

            groups.append(
                (
                    chat_id,
                    dialog.title or "Untitled",
                    username,
                )
            )

        self.db.sync_folder_groups(
            row[0],
            groups,
        )

        return row, dialogs

    async def sync_all_folders(self, client_key: str, account_id: int):
        filters = await self.get_dialog_filters(client_key)
        result = []
        for folder in filters:
            try:
                row, _ = await self.sync_folder(client_key, account_id, folder)
                result.append(row)
            except Exception:
                logger.exception("Failed to sync folder %s", getattr(folder, "id", "?"))
        return result

    async def disconnect_all(self):
        for client in list(self.clients.values()):
            await client.disconnect()
        self.clients.clear()
        self.pending.clear()
