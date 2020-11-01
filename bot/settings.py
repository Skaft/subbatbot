import aiosqlite


class SettingsError(Exception):
    pass


class ChannelSettings:
    def __init__(self):
        self.fmt = 'none'
        self.site = 'chess.com'
        self.unique_users = 'on'


class Settings:

    options = {
        # default value first
        'site': ['chess.com', 'lichess'],
        'unique_users': ['on', 'off'],
        'format': ['none', 'bracket', 'space'],
    }

    def __init__(self):
        self.help_string = "?set site lichess (or chess.com); ?set unique_users off (if you want to allow users making multiple entries)"
        self.cache = {}

    async def set(self, *args):
        if len(args) < 2:
            raise SettingsError("Missing info; need both a setting and a value")
        setting, value = args
        setting = setting.lower()
        value = value.lower()
        valid = Settings.options

        if setting not in valid:
            raise SettingsError(f'Available settings: {",".join(valid)} (not {setting})')
        if value not in valid[setting]:
            raise SettingsError(f'Available values for {setting}: {",".join(valid[setting])} (not {value})')
        if setting == 'unique_users':
            value = value == 'on'

        self.cache[channel_name][setting] = value
        #TODO: update database here

    async def get(self, channel_name, setting):
        # should read cached values unless missing, in which case read async from DB (and store in cache)
        return self.cache[channel_name][setting]

    async def add_channel(self, channel_name):
        self.cache[channel_name] = {setting: values[0] for setting, values in Settings.options.items()}
        # TODO: add to database here

    async def remove_channel(self, channel_name):
        self.cache.pop(channel_name)
        # TODO: remove from database here
