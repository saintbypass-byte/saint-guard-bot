import sqlite3
from threading import RLock


class Database:
    def __init__(self, path):
        self.path = path
        self.lock = RLock()
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    chat_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY(chat_id, key)
                );
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL, admin_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                    action TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS filters (
                    chat_id INTEGER NOT NULL, keyword TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(chat_id, keyword)
                );
                CREATE TABLE IF NOT EXISTS blocklist (
                    chat_id INTEGER NOT NULL, phrase TEXT NOT NULL,
                    PRIMARY KEY(chat_id, phrase)
                );
                CREATE TABLE IF NOT EXISTS notes (
                    chat_id INTEGER NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL,
                    PRIMARY KEY(chat_id, name)
                );
            """)

    def connect(self):
        con = sqlite3.connect(self.path, timeout=20)
        con.row_factory = sqlite3.Row
        return con

    def set_setting(self, chat_id, key, value):
        with self.lock, self.connect() as con:
            con.execute("INSERT INTO settings(chat_id,key,value) VALUES(?,?,?) "
                        "ON CONFLICT(chat_id,key) DO UPDATE SET value=excluded.value",
                        (chat_id, key, str(value)))

    def get_setting(self, chat_id, key, default=""):
        with self.lock, self.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE chat_id=? AND key=?",
                              (chat_id, key)).fetchone()
            return row["value"] if row else default

    def add_warning(self, chat_id, user_id, admin_id):
        with self.lock, self.connect() as con:
            con.execute("INSERT INTO warnings(chat_id,user_id,admin_id) VALUES(?,?,?)",
                        (chat_id, user_id, admin_id))
            return con.execute("SELECT COUNT(*) AS n FROM warnings WHERE chat_id=? AND user_id=?",
                               (chat_id, user_id)).fetchone()["n"]

    def warning_count(self, chat_id, user_id):
        with self.lock, self.connect() as con:
            return con.execute("SELECT COUNT(*) AS n FROM warnings WHERE chat_id=? AND user_id=?",
                               (chat_id, user_id)).fetchone()["n"]

    def add_log(self, chat_id, action):
        with self.lock, self.connect() as con:
            con.execute("INSERT INTO logs(chat_id,action) VALUES(?,?)", (chat_id, action[:1000]))

    def add_filter(self, chat_id, keyword, response):
        with self.lock, self.connect() as con:
            con.execute("INSERT INTO filters(chat_id,keyword,response) VALUES(?,?,?) "
                        "ON CONFLICT(chat_id,keyword) DO UPDATE SET response=excluded.response",
                        (chat_id, keyword.lower()[:80], response[:1000]))

    def remove_filter(self, chat_id, keyword):
        with self.lock, self.connect() as con:
            con.execute("DELETE FROM filters WHERE chat_id=? AND keyword=?",
                        (chat_id, keyword.lower()[:80]))

    def get_filters(self, chat_id):
        with self.lock, self.connect() as con:
            rows = con.execute("SELECT keyword,response FROM filters WHERE chat_id=? ORDER BY keyword",
                               (chat_id,)).fetchall()
            return [(r["keyword"], r["response"]) for r in rows]

    def increment_member_count(self, chat_id):
        try:
            self.set_setting(chat_id, "members",
                             int(self.get_setting(chat_id, "members", "0")) + 1)
        except ValueError:
            self.set_setting(chat_id, "members", 1)

    def decrement_member_count(self, chat_id):
        try:
            self.set_setting(chat_id, "members",
                             max(0, int(self.get_setting(chat_id, "members", "0")) - 1))
        except ValueError:
            self.set_setting(chat_id, "members", 0)

    def stats(self, chat_id):
        with self.lock, self.connect() as con:
            warnings = con.execute("SELECT COUNT(*) n FROM warnings WHERE chat_id=?", (chat_id,)).fetchone()["n"]
            logs = con.execute("SELECT COUNT(*) n FROM logs WHERE chat_id=?", (chat_id,)).fetchone()["n"]
        members = int(self.get_setting(chat_id, "members", "0") or 0)
        return {"members": members, "warnings": warnings, "logs": logs}

    def add_blocklist(self, chat_id, phrase):
        with self.lock, self.connect() as con:
            con.execute("INSERT OR IGNORE INTO blocklist(chat_id,phrase) VALUES(?,?)",
                        (chat_id, phrase.lower()[:120]))

    def remove_blocklist(self, chat_id, phrase):
        with self.lock, self.connect() as con:
            con.execute("DELETE FROM blocklist WHERE chat_id=? AND phrase=?",
                        (chat_id, phrase.lower()[:120]))

    def get_blocklist(self, chat_id):
        with self.lock, self.connect() as con:
            rows = con.execute("SELECT phrase FROM blocklist WHERE chat_id=? ORDER BY phrase",
                               (chat_id,)).fetchall()
            return [r["phrase"] for r in rows]

    def clear_blocklist(self, chat_id):
        with self.lock, self.connect() as con:
            con.execute("DELETE FROM blocklist WHERE chat_id=?", (chat_id,))

    def save_note(self, chat_id, name, content):
        with self.lock, self.connect() as con:
            con.execute("INSERT INTO notes(chat_id,name,content) VALUES(?,?,?) "
                        "ON CONFLICT(chat_id,name) DO UPDATE SET content=excluded.content",
                        (chat_id, name.lower()[:50], content[:3000]))

    def get_note(self, chat_id, name):
        with self.lock, self.connect() as con:
            row = con.execute("SELECT content FROM notes WHERE chat_id=? AND name=?",
                              (chat_id, name.lower()[:50])).fetchone()
            return row["content"] if row else None

    def list_notes(self, chat_id):
        with self.lock, self.connect() as con:
            rows = con.execute("SELECT name FROM notes WHERE chat_id=? ORDER BY name", (chat_id,)).fetchall()
            return [r["name"] for r in rows]

    def remove_note(self, chat_id, name):
        with self.lock, self.connect() as con:
            con.execute("DELETE FROM notes WHERE chat_id=? AND name=?", (chat_id, name.lower()[:50]))
