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
        self._sql_insert_template = None
        self.cur.execute("SELECT * FROM settings LIMIT 0;")
        self.col_names = [desc.name for desc in self.cur.description]
        self._make_templates()

    def _make_templates(self):
        # make sql string templates
        cols = ', '.join(self.col_names)
        placeholders = ', '.join(['%s'] * len(self.col_names))
        self._sql_insert_template = f"INSERT INTO settings ({cols}) VALUES ({placeholders});"

    def add_channel(self, channel):
        values = (channel, *SettingsDatabase.defaults.values())
        self._commit(self._sql_insert_template, values)

    def delete_channel(self, channel):
        sql = "DELETE FROM settings WHERE channel = %s"
        self._commit(sql, (channel,))
    
    def clear(self):
        self._commit("DELETE FROM settings")

    def update_setting(self, channel, setting, value):
        sql = f"UPDATE settings SET {setting} = %s WHERE channel = %s;"
        self._commit(sql, (value, channel))

    def get_settings(self, channel):
        self.cur.execute("SELECT * FROM settings WHERE channel = %s;", (channel,))
        stored = self.cur.fetchall()
        if stored:
            return dict(zip(self.col_names[1:], stored[0][1:]))
        else:
            self.add_channel(channel)
            return {**SettingsDatabase.defaults}

    def get_all_records(self):
        self.cur.execute("SELECT * FROM settings;")
        return self.cur.fetchall()

    def get_all_channels(self):
        self.cur.execute("SELECT channel FROM settings;")
        return [c[0] for c in self.cur]

    def _new_token(self, token, type='access'):
        if type not in ('access', 'refresh'):
            raise ValueError('Token can only be access or refresh')
        sql = f"INSERT INTO params (var, val) VALUES (%s, %s);"
        self._commit(sql, (f"{type}_token", token))

    def update_token(self, token, type='access'):
        if type not in ('access', 'refresh'):
            raise ValueError('Token can only be access or refresh')
        sql = f"UPDATE params SET val = %s WHERE var=%s;"
        varname = f"{type}_token"
        self._commit(sql, (token, varname))

    def get_token(self, type='access'):
        if type not in ('access', 'refresh'):
            raise ValueError('Token can only be access or refresh')
        sql = "SELECT val FROM params WHERE var=%s;"
        varname = f"{type}_token"
        self.cur.execute(sql, (varname,))
        return self.cur.fetchall()[0][0]

    def _commit(self, sql, values):
        self.cur.execute(sql, values)
        self.conn.commit()

if __name__ == '__main__':
    db = SettingsDatabase()
    print(db.get_token('refresh'))