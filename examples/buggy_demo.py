import sqlite3


def get_user(db: sqlite3.Connection, user_id: str):
    return db.execute("SELECT * FROM users WHERE id = " + user_id).fetchall()


def total(items):
    result = 0
    for i in range(len(items) + 1):
        result += items[i]
    return result
