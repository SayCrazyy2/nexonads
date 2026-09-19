import os
import sqlite3
from datetime import datetime


class BotDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            is_approved INTEGER DEFAULT 0,
            is_sudo INTEGER DEFAULT 0,
            added_at TEXT
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_key TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            is_connected INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS pending_approvals (
            user_id INTEGER PRIMARY KEY,
            requested_at TEXT,
            approved_by INTEGER
        );

        CREATE TABLE IF NOT EXISTS broadcast_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            group_include TEXT DEFAULT '',
            group_exclude TEXT DEFAULT '',
            delay REAL DEFAULT 1.0,
            schedule TEXT DEFAULT NULL,
            loop_enabled INTEGER DEFAULT 0,
            loop_delay REAL DEFAULT 0,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS broadcast_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broadcast_id TEXT,
            account_id INTEGER,
            group_id TEXT,
            status TEXT,
            sent_at TEXT
        );

        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            folder_id INTEGER NOT NULL,
            folder_name TEXT NOT NULL,
            invite_link TEXT,
            UNIQUE(account_id, folder_id),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS folder_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            chat_id TEXT NOT NULL,
            title TEXT NOT NULL,
            username TEXT,
            included INTEGER DEFAULT 1,
            UNIQUE(folder_id, chat_id),
            FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE
        );
        """)
        self.conn.commit()
        
        columns = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA table_info(broadcast_settings)"
            ).fetchall()
        }

        if "loop_enabled" not in columns:
            self.conn.execute(
                """
                ALTER TABLE broadcast_settings
                ADD COLUMN loop_enabled INTEGER DEFAULT 0
                """
            )

        if "loop_delay" not in columns:
            self.conn.execute(
                """
                ALTER TABLE broadcast_settings
                ADD COLUMN loop_delay REAL DEFAULT 0
                """
            )

        self.conn.commit()

    # users
    def add_user(self, user_id, username, is_sudo=0):
        self.conn.execute(
            "INSERT OR IGNORE INTO users(user_id, username, is_sudo, added_at) VALUES (?, ?, ?, ?)",
            (user_id, username, is_sudo, datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    def is_user_approved(self, user_id):
        row = self.conn.execute(
            "SELECT is_approved FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row[0])

    def set_approval(self, user_id, approved=True, by_sudo=None):
        self.conn.execute(
            "UPDATE users SET is_approved = ? WHERE user_id = ?",
            (1 if approved else 0, user_id),
        )
        if by_sudo is not None:
            self.conn.execute(
                "INSERT OR REPLACE INTO pending_approvals(user_id, requested_at, approved_by) VALUES (?, ?, ?)",
                (user_id, datetime.utcnow().isoformat(), by_sudo),
            )
        self.conn.commit()

    def is_user_sudo(self, user_id):
        row = self.conn.execute(
            "SELECT is_sudo FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row[0])

    def add_sudo_user(self, user_id, username):
        self.conn.execute(
            "INSERT OR IGNORE INTO users(user_id, username, is_sudo, added_at) VALUES (?, ?, 1, ?)",
            (user_id, username, datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    # accounts
    def add_account(self, client_key, phone):
        self.conn.execute(
            "INSERT OR IGNORE INTO accounts(client_key, phone, created_at) VALUES (?, ?, ?)",
            (client_key, phone, datetime.utcnow().isoformat()),
        )
        self.conn.commit()
        return self.get_account(client_key)

    def get_account(self, client_key):
        return self.conn.execute(
            "SELECT id, client_key, phone, is_connected FROM accounts WHERE client_key = ?",
            (client_key,),
        ).fetchone()

    def get_account_by_id(self, account_id):
        return self.conn.execute(
            "SELECT id, client_key, phone, is_connected FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()

    def get_accounts(self):
        return self.conn.execute(
            "SELECT id, client_key, phone, is_connected FROM accounts ORDER BY id"
        ).fetchall()

    def set_account_connected(self, account_id, connected=True):
        self.conn.execute(
            "UPDATE accounts SET is_connected = ? WHERE id = ?",
            (1 if connected else 0, account_id),
        )
        self.conn.commit()

    def remove_account(self, client_key):
        self.conn.execute("DELETE FROM accounts WHERE client_key = ?", (client_key,))
        self.conn.commit()

    # folders
    def upsert_folder(self, account_id, folder_id, folder_name, invite_link=None):
        self.conn.execute("""
            INSERT INTO folders(account_id, folder_id, folder_name, invite_link)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id, folder_id) DO UPDATE SET
                folder_name=excluded.folder_name,
                invite_link=COALESCE(excluded.invite_link, folders.invite_link)
        """, (account_id, folder_id, folder_name, invite_link))
        self.conn.commit()
        return self.conn.execute(
            "SELECT id, account_id, folder_id, folder_name, invite_link FROM folders WHERE account_id=? AND folder_id=?",
            (account_id, folder_id),
        ).fetchone()

    def get_folders(self, account_id):
        return self.conn.execute(
            "SELECT id, account_id, folder_id, folder_name, invite_link FROM folders WHERE account_id=? ORDER BY folder_name",
            (account_id,),
        ).fetchall()

    def get_folder(self, folder_db_id):
        return self.conn.execute(
            "SELECT id, account_id, folder_id, folder_name, invite_link FROM folders WHERE id=?",
            (folder_db_id,),
        ).fetchone()

    # folder groups
    def sync_folder_groups(self, folder_db_id, groups):
        seen_chat_ids = set()
    
        for group in groups:
            chat_id, title, username = group
            chat_id = str(chat_id)

            if chat_id in seen_chat_ids:
                continue
    
            seen_chat_ids.add(chat_id)
    
            existing = self.conn.execute("""
                SELECT id
                FROM folder_groups
                WHERE folder_id=? AND chat_id=?
                """, (
                folder_db_id,
                chat_id,
            )).fetchone()

            if existing:
                self.conn.execute("""
                    UPDATE folder_groups
                    SET title=?, username=?
                    WHERE id=?
                """, (
                    title,
                    username,
                    existing[0],
                ))
            else:
                self.conn.execute("""
                    INSERT INTO folder_groups(
                        folder_id,
                        chat_id,
                        title,
                        username,
                        included
                    )
                    VALUES (?, ?, ?, ?, 1)
                """, (
                    folder_db_id,
                    chat_id,
                    title,
                    username,
                ))

        # Remove database entries that are no longer in Telegram.
        if seen_chat_ids:
            placeholders = ",".join("?" for _ in seen_chat_ids)

            self.conn.execute(
                f"""
                DELETE FROM folder_groups
                WHERE folder_id=?
                  AND chat_id NOT IN ({placeholders})
                """,
                (folder_db_id, *seen_chat_ids),
            )
        else:
            self.conn.execute(
                "DELETE FROM folder_groups WHERE folder_id=?",
                (folder_db_id,),
            )
    
        self.conn.commit()

    def get_folder_groups(self, folder_db_id):
        return self.conn.execute("""
            SELECT id, folder_id, chat_id, title, username, included
            FROM folder_groups
            WHERE folder_id=?
            ORDER BY title COLLATE NOCASE
        """, (folder_db_id,)).fetchall()

    def toggle_group(self, group_db_id):
        self.conn.execute(
            "UPDATE folder_groups SET included = CASE included WHEN 1 THEN 0 ELSE 1 END WHERE id=?",
            (group_db_id,),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT included FROM folder_groups WHERE id=?", (group_db_id,)
        ).fetchone()[0]

    def get_included_groups(self, account_id):
        return self.conn.execute("""
            SELECT DISTINCT fg.chat_id, fg.title, fg.username, f.folder_name
            FROM folder_groups fg
            JOIN folders f ON f.id=fg.folder_id
            WHERE f.account_id=? AND fg.included=1
            ORDER BY fg.title COLLATE NOCASE
        """, (account_id,)).fetchall()

    def count_group_stats(self, account_id):
        return self.conn.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN fg.included=1 THEN 1 ELSE 0 END), 0) AS included,
                COALESCE(SUM(CASE WHEN fg.included=0 THEN 1 ELSE 0 END), 0) AS excluded
            FROM folder_groups fg
            JOIN folders f ON f.id=fg.folder_id
            WHERE f.account_id=?
        """, (account_id,)).fetchone()

    # broadcast
    def add_broadcast_setting(
        self,
        user_id,
        group_include="",
        group_exclude="",
        delay=1.0,
        schedule=None,
        loop_enabled=0,
        loop_delay=0,
    ):
        self.conn.execute(
            """
            INSERT OR IGNORE INTO users(user_id, username, added_at)
            VALUES (?, ?, ?)
            """,
            (user_id, None, datetime.utcnow().isoformat()),
        )

        self.conn.execute("""
            INSERT INTO broadcast_settings(
                user_id,
                group_include,
                group_exclude,
                delay,
                schedule,
                loop_enabled,
                loop_delay,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(user_id) DO UPDATE SET
                group_include=excluded.group_include,
                group_exclude=excluded.group_exclude,
                delay=excluded.delay,
                schedule=excluded.schedule,
                loop_enabled=excluded.loop_enabled,
                loop_delay=excluded.loop_delay
        """, (
            user_id,
            group_include,
            group_exclude,
            delay,
            schedule,
            1 if loop_enabled else 0,
            loop_delay,
            datetime.utcnow().isoformat(),
        ))
        self.conn.commit()

    def get_broadcast_setting(self, user_id):
        return self.conn.execute(
            "SELECT group_include, group_exclude, delay, schedule FROM broadcast_settings WHERE user_id=?",
            (user_id,),
        ).fetchone()

    def add_broadcast_log(self, broadcast_id, account_id, group_id, status):
        self.conn.execute(
            "INSERT INTO broadcast_logs(broadcast_id, account_id, group_id, status, sent_at) VALUES (?, ?, ?, ?, ?)",
            (broadcast_id, account_id, group_id, status, datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
