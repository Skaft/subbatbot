import os
import psycopg2

from globals import DEV_MODE


class DB:
    defaults = {
        'site': 'chess.com',
        'game': 'blitz',
        'format': 'none',
    }

    def __init__(self):
        db_conn_string = os.environ['DATABASE_URL']
        if DEV_MODE:
            self.conn = psycopg2.connect(db_conn_string)
        else:
            self.conn = psycopg2.connect(db_conn_string, sslmode='require')
        self.cur = self.conn.cursor()
        self._sql_insert_template = None
        self._make_templates()

    def _make_templates(self):
        # make sql string templates
        self.cur.execute("SELECT * FROM settings LIMIT 0;")
        col_names = [desc.name for desc in self.cur.description]
        cols = ', '.join(col_names)
        placeholders = ', '.join(['%s'] * len(col_names))
        self._sql_insert_template = f"INSERT INTO settings ({cols}) VALUES ({placeholders});"

    def add_channel(self, channel):
        values = (channel, *DB.defaults.values())
        self._commit(self._sql_insert_template, values)

    def delete_channel(self, channel):
        sql = "DELETE FROM settings WHERE channel = %s"
        self._commit(sql, (channel,))
    
    def clear(self):
        self._commit("DELETE FROM settings")

    def update_setting(self, channel, setting, value):
        sql = f"UPDATE settings SET {setting} = %s WHERE channel = %s;"
        self._commit(sql, (value, channel))

    def get_all_records(self):
        self.cur.execute("SELECT * FROM settings;")
        return self.cur.fetchall()

    def get_all_channels(self):
        self.cur.execute("SELECT channel FROM settings;")
        return [c[0] for c in self.cur]

    def _commit(self, sql, values):
        self.cur.execute(sql, values)
        self.conn.commit()
