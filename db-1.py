import sqlite3

DB_FILE = "shop.db"


def connect():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init():
    con = connect()
    con.execute("PRAGMA journal_mode=WAL")
    con.commit()
    con.close()
