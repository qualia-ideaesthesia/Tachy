import os
import sqlite3

from config.config import Config

LINK_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "tachy.db",
)


# Look up an Arcaea user ID by name.
def get_user_id(name):
    conn = sqlite3.connect(Config.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id FROM user WHERE name = ?",
            (name,),
        )
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


# Create the Discord account link table if needed.
def init_link_table():
    conn = sqlite3.connect(LINK_DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS discord_link (
                discord_user_id TEXT PRIMARY KEY,
                arcaea_username TEXT NOT NULL,
                arcaea_user_id INTEGER NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


# Link a Discord account to an Arcaea account.
def link_user(discord_user_id, arcaea_username, arcaea_user_id):
    conn = sqlite3.connect(LINK_DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO discord_link
            (discord_user_id, arcaea_username, arcaea_user_id)
            VALUES (?, ?, ?)
            """,
            (
                str(discord_user_id),
                arcaea_username,
                arcaea_user_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# Return the Arcaea user ID linked to Discord.
def get_linked_user_id(discord_user_id):
    conn = sqlite3.connect(LINK_DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT arcaea_user_id
            FROM discord_link
            WHERE discord_user_id = ?
            """,
            (str(discord_user_id),),
        )
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


# Return the Arcaea username linked to Discord.
def get_linked_username(discord_user_id):
    conn = sqlite3.connect(LINK_DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT arcaea_username
            FROM discord_link
            WHERE discord_user_id = ?
            """,
            (str(discord_user_id),),
        )
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


# Change user's memory value.
def set_user_memory(arcaea_user_id, memory):
    if not isinstance(memory, int) or isinstance(memory, bool) or memory <= 0:
        raise ValueError("Memory value must be a positive integer.")

    conn = sqlite3.connect(Config.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE user SET ticket = ? WHERE user_id = ?",
            (memory, arcaea_user_id),
        )

        if cursor.rowcount == 0:
            return False

        conn.commit()
        return True
    finally:
        conn.close()
