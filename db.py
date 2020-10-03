import os
import psycopg2

from globals import DEV_MODE


class SettingsDatabase:
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

    def add_channel(self, channel):
        defaults = SettingsDatabase.defaults
        fields = ('channel', *defaults.keys())
        values = (channel, *defaults.values())
        placeholders = ', '.join(['%s'] * len(values))
        sql = f"INSERT INTO settings ({fields}) VALUES ({placeholders});"
        self._commit(sql, values)

    def delete_channel(self, channel):
        sql = "DELETE FROM settings WHERE channel = %s"
        self._commit(sql, (channel,))
    
    def clear(self):
        self._commit("DELETE FROM settings")

    def update_setting(self, channel, setting, value):
        sql = f"UPDATE settings SET {setting} = %s WHERE channel = %s;"
        self._commit(sql, (value, channel))

    def store_key(self, channel, key):
        self.update_setting(channel, 'sheet_key', key)

    def get_settings(self, channel):
        fields = [*SettingsDatabase.defaults.keys(), 'sheet_key']
        fields_string = ', '.join(fields)
        self.cur.execute(f"SELECT {fields_string} FROM settings WHERE channel = %s;", (channel,))
        stored = self.cur.fetchall()
        if stored:
            return dict(zip(fields, stored[0]))
        else:
            self.add_channel(channel)
            return {**SettingsDatabase.defaults, 'sheet_key': None}

    def get_all_settings(self):
        self.cur.execute("SELECT * FROM settings;")
        keys = (*SettingsDatabase.defaults.keys(), 'sheet_key')
        return {t[0]: dict(zip(keys, t[1:])) for t in self.cur}

    def get_all_channels(self):
        self.cur.execute("SELECT channel FROM settings;")
        return [c[0] for c in self.cur]

    def _new_token(self, token, name='twitch_api_token'):
        cols, vals = zip(*token.items())
        vals = (name, *vals)
        sql = f"INSERT INTO params (name, {', '.join(cols)}) VALUES (%s, %s, %s, %s, %s, %s);"
        self._commit(sql, vals)

    def update_token(self, token, name='twitch_api_token'):
        cols, vals = zip(*token.items())
        columns = ', '.join(cols)
        placeholders = ', '.join(['%s'] * len(cols))
        sql = f"UPDATE params SET ({columns}) = ({placeholders}) WHERE name=%s;"
        self._commit(sql, (*vals, name))

    def get_token(self, name='twitch_api_token'):
        keys = ['access_token', 'refresh_token', 'expires_in', 'scope', 'token_type']
        columns = ', '.join(keys)
        sql = f"SELECT {columns} FROM params WHERE name=%s;"
        self.cur.execute(sql, (name,))
        return dict(zip(keys, self.cur.fetchall()[0]))

    def _commit(self, sql, values):
        self.cur.execute(sql, values)
        self.conn.commit()
