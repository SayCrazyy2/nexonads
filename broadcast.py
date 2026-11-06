import asyncio
import logging
import re
import uuid

from telethon import TelegramClient

from database import BotDatabase


logger = logging.getLogger(__name__)


def parse_duration(value) -> float:
    """
    Convert a duration string into seconds.

    Supported:
        5s
        10m
        2h
        1d
        1h 30m
        2d 5h 20m 10s
        1.5h

    A plain number is treated as seconds.
    """

    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds < 0:
            raise ValueError("Duration cannot be negative")
        return seconds

    text = str(value).strip().lower()

    if not text:
        raise ValueError("Duration cannot be empty")

    # Plain number = seconds.
    try:
        seconds = float(text)
        if seconds < 0:
            raise ValueError("Duration cannot be negative")
        return seconds
    except ValueError:
        pass

    pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*(d|h|m|s)"
    )

    matches = list(pattern.finditer(text))

    if not matches:
        raise ValueError(
            "Invalid duration. Examples: 5s, 10m, 2h, 1d, 1h 30m"
        )

    # Make sure there isn't unsupported text between tokens.
    cleaned = pattern.sub("", text)
    if cleaned.strip():
        raise ValueError(
            "Invalid duration. Examples: 5s, 10m, 2h, 1d, 1h 30m"
        )

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    total = 0.0

    for match in matches:
        amount = float(match.group(1))
        unit = match.group(2)
        total += amount * multipliers[unit]

    if total < 0:
        raise ValueError("Duration cannot be negative")

    return total


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration."""

    seconds = float(seconds)

    if seconds < 0:
        seconds = 0

    if seconds == 0:
        return "0s"

    parts = []

    days = int(seconds // 86400)
    seconds %= 86400

    hours = int(seconds // 3600)
    seconds %= 3600

    minutes = int(seconds // 60)
    seconds %= 60

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if seconds:
        if seconds.is_integer():
            parts.append(f"{int(seconds)}s")
        else:
            parts.append(f"{seconds:g}s")

    return " ".join(parts)

class BroadcastManager:
    def __init__(
        self,
        db,
        api_id,
        api_hash,
        sessions_dir="sessions",
        account_manager=None,
    ):
        self.db = db
        self.api_id = api_id
        self.api_hash = api_hash
        self.sessions_dir = sessions_dir
        self.account_manager = account_manager

    async def _init_client(self, client_key):
        client = TelegramClient(
            f"{self.sessions_dir}/{client_key}",
            self.api_id,
            self.api_hash,
            device_model="Nexon Ads Broadcast",
            system_version="4.0.0",
            app_version="1.0.0",
        )

        try:
            await client.connect()
        
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telegram account is not authorized"
                )

            return client
    
        except BaseException:
            await client.disconnect()
            raise

    async def _load_entities(self, client):
        """
        Load Telegram dialogs once so Telethon has the correct
        entity/access-hash information.
        """

        dialogs = await client.get_dialogs()

        entity_map = {}

        for dialog in dialogs:
            try:
                entity = dialog.entity
                entity_id = getattr(entity, "id", None)

                if entity_id is not None:
                    entity_map[int(entity_id)] = entity

            except Exception:
                logger.exception(
                    "Could not cache Telegram dialog entity"
                )

        logger.info(
            "Loaded %s Telegram dialog entities",
            len(entity_map),
        )

        return entity_map

    async def _send_round(
        self,
        client,
        entity_map,
        account_id,
        targets,
        message,
        delay,
        loop_number,
    ):
        """
        Send one complete broadcast round.
        """

        broadcast_id = (
            f"bc_{uuid.uuid4().hex}"
        )

        results = []

        logger.info(
            "Broadcast round started: account=%s round=%s targets=%s",
            account_id,
            loop_number,
            len(targets),
        )

        for chat_id, title, username, folder_name in targets:
            chat_id = int(chat_id)

            try:
                entity = entity_map.get(chat_id)

                if entity is None:
                    raise ValueError(
                        f"Telegram entity not found for chat_id={chat_id}"
                    )

                logger.info(
                    "Sending broadcast: account=%s round=%s "
                    "group=%s folder=%s chat_id=%s",
                    account_id,
                    loop_number,
                    title,
                    folder_name,
                    chat_id,
                )

                await client.send_message(
                    entity,
                    message,
                    parse_mode="markdown",
                )

                self.db.add_broadcast_log(
                    broadcast_id=broadcast_id,
                    account_id=account_id,
                    group_id=str(chat_id),
                    status="sent",
                )

                results.append({
                    "group": title,
                    "folder": folder_name,
                    "status": "success",
                })

                logger.info(
                    "Broadcast sent successfully: %s",
                    title,
                )

            except Exception as exc:
                logger.exception(
                    "Failed to send broadcast to %s (%s)",
                    title,
                    chat_id,
                )

                self.db.add_broadcast_log(
                    broadcast_id=broadcast_id,
                    account_id=account_id,
                    group_id=str(chat_id),
                    status="failed",
                )

                results.append({
                    "group": title,
                    "folder": folder_name,
                    "status": "failed",
                    "error": str(exc),
                })

            if delay > 0:
                await asyncio.sleep(delay)

        sent = sum(
            1
            for result in results
            if result["status"] == "success"
        )

        failed = sum(
            1
            for result in results
            if result["status"] == "failed"
        )

        logger.info(
            "Broadcast round finished: "
            "account=%s round=%s sent=%s failed=%s",
            account_id,
            loop_number,
            sent,
            failed,
        )

        return results

    async def broadcast_to_account(
        self,
        account_id: int,
        message: str,
        delay: float = 1.0,
        loop: bool = False,
        loop_delay: float = 0.0,
    ):
        """
        Broadcast to all included groups.

        delay:
            Delay between individual groups.

        loop:
            False = send once.
            True  = repeat forever.

        loop_delay:
            Delay between complete broadcast rounds.
        """

        account = self.db.get_account_by_id(account_id)

        if not account:
            raise ValueError("Account not found")

        _, client_key, _, _ = account

        targets = self.db.get_included_groups(account_id)

        if not targets:
            logger.warning(
                "Broadcast skipped: no included groups "
                "for account %s",
                account_id,
            )
            return []

        delay = float(delay)
        loop_delay = float(loop_delay)

        if delay < 0:
            raise ValueError("Delay cannot be negative")

        if loop_delay < 0:
            raise ValueError("Loop delay cannot be negative")

        if self.account_manager is None:
            raise RuntimeError("AccountManager is required")

        client = await self.account_manager.get_client(client_key)

        all_results = []
        loop_number = 0

        try:
            entity_map = await self._load_entities(client)

            while True:
                loop_number += 1

                results = await self._send_round(
                    client=client,
                    entity_map=entity_map,
                    account_id=account_id,
                    targets=targets,
                    message=message,
                    delay=delay,
                    loop_number=loop_number,
                )

                all_results.extend(results)

                if not loop:
                    break

                logger.info(
                    "Looping broadcast waiting %s before round %s",
                    format_duration(loop_delay),
                    loop_number + 1,
                )

                if loop_delay > 0:
                    await asyncio.sleep(loop_delay)

                # Refresh included groups between rounds.
                targets = self.db.get_included_groups(account_id)

                if not targets:
                    logger.warning(
                        "Looping broadcast stopped: "
                        "no included groups remain"
                    )
                    break

        except asyncio.CancelledError:
            logger.info(
                "Broadcast task cancelled: account=%s",
                account_id,
            )
            raise

        except Exception:
            logger.exception(
                "Broadcast task crashed: account=%s",
                account_id,
            )
            raise

        logger.info(
            "Broadcast finished: account=%s rounds=%s",
            account_id,
            loop_number,
        )

        return all_results