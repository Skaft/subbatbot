import os
from random import choice
from string import Template
import logging

from twitchio.ext.commands import Bot, errors
import aiohttp

from aio_lookup import ChessComAPI, LichessAPI
from sheet import BattleSheet
from db import SettingsDatabase
from exts import checks
from globals import DEV_MODE, USER_BLACKLIST



logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
logging.getLogger('websockets').setLevel(logging.ERROR)
logging.getLogger('twitchio').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)

greetings = [
    "/me Is it a bird, is it a plane, etc.",
    "/me is here!",
    "/me You rang?",
    "/me I'm Winston Wolf. I solve problems.",
    "/me Oh sheet!",
    "/me TO WAR!",
    "/me Fight to the death!",
    "/me Hey, I'm on your side. But also maybe on theirs.",
    "/me *sneaks in*",
]


class MissingSheetReference(KeyError):
    """Raised when bot tries to fetch a BattleSheet from cache without finding it.

    Usually caused by ?link used too soon after bot joins channel.
    """
    pass


class SubBatBot(Bot):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        log.info(f"Initialized {self.nick}, dev mode = {DEV_MODE}")

        self.load_module('exts.commands')
        self.add_check(checks.mod_or_sed)

        self.sheets = {}
        self.db = SettingsDatabase()

        # create a template for help message (prefix may vary)
        public_commands = ['apply', 'set', 'clear', 'link', 'help', 'leave']
        docstrings = [cmd._callback.__doc__ for cmd in self.commands.values() if cmd.name in public_commands]
        command_help = '; '.join("${prefix}" + doc for doc in docstrings)
        self.help_msg_template = Template(f"Commands: {command_help}")

    def get_sheet(self, channel_name):
        sheet = self.sheets.get(channel_name)
        if sheet is None:
            raise MissingSheetReference(f"Bot has no sheet called {channel_name}")
        return sheet

    async def event_ready(self):
        # session needs to be created in async function, hence not in __init__
        session = aiohttp.ClientSession()
        self.apis = {
            'lichess': LichessAPI(session),
            'chess.com': ChessComAPI(session)
        }
        if DEV_MODE:
            channel_names = [self.nick]
        else:
            channel_names = self.db.get_all_channels()
        log.debug(f"Found {len(channel_names)} channels to join")
        all_settings = self.db.get_all_settings()
        for channel_name in channel_names:
            await self.join_channel(channel_name, greet=DEV_MODE, channel_settings=all_settings[channel_name])
        print(f"{os.environ['BOT_NICK']} is online!")

    async def join_channel(self, channel_name, greet=False, channel_settings=None):
        await self.join_channels([channel_name])
        if channel_settings is None:
            channel_settings = self.db.get_settings(channel_name)
        self.sheets[channel_name] = await BattleSheet.open(channel_name, channel_settings)
        if channel_settings['sheet_key'] is None:
            sheet_key = self.sheets[channel_name].sheet_key
            log.debug(f"({channel_name}) No sheet key in store, updating db with {sheet_key[:5]}")
            self.db.store_key(channel_name, sheet_key)
        if greet:
            await self._ws.send_privmsg(channel_name, choice(greetings))

    async def leave_channel(self, channel_name):
        await self.part_channels([channel_name])
        sheet = self.sheets.pop(channel_name)
        await sheet.remove()
        self.db.delete_channel(channel_name)

    async def event_message(self, msg):
        if msg.author.name.lower() in USER_BLACKLIST:
            return
        try:
            await self.handle_commands(msg)
        except errors.MissingRequiredArgument as e:  # <-- why is this here? event_command_error is a thing.
            log.error(f"({msg.channel.name}) Missing req argument box! {msg.author.display_name} posted {msg.content}")
            print(e)

    async def event_command_error(self, ctx, error):
        user = ctx.author
        name = user.display_name
        pre = ctx.prefix
        if isinstance(error, errors.CheckFailure):
            log.debug(f"({ctx.channel.name}) {name} caused '{error}' by typing '{ctx.message.content}'")
            #if str(error).endswith('mod_or_sed'):
            return
                #msg = f"Only the {pre}apply command is available to non-moderators, sorry!"
                #return await ctx.send(f"@{name}: {msg}")
        if isinstance(error, errors.CommandNotFound):
            # just ignore this error as it doesn't have to be someone trying to use the bot
            return
        if isinstance(error, errors.MissingRequiredArgument):
            # using apply badly
            if error.param.name == 'chess_name':
                msg = f'{pre}apply username <-- Type this, using your own chess username, to apply!'
            # using set badly
            elif error.param.name == 'setting':
                sheet = self.get_sheet(ctx.channel.name)
                msg = f"Current settings: {sheet.current_settings}"
            elif error.param.name == 'value':
                msg = BattleSheet.settings_help_string
            else:
                log.debug(f"({ctx.channel.name}) {name} caused '{error}' by typing '{ctx.message.content}'")
                msg = str(error)
            return await ctx.send(msg)
        elif isinstance(error, MissingSheetReference):
            log.warning(f"({ctx.channel.name}) {name} caused: {error} by typing '{ctx.message.content}'")
            return await ctx.send("No sheet found for this channel. If I just joined or rebooted, try again soon!")
        else:
            log.error(f"({ctx.channel.name}) {name} caused '{error}' by typing '{ctx.message.content}'")
        return await super().event_command_error(ctx, error)

#   @monitor to track usage stats and watch out for rate limiting
    async def _whisper(self, user, msg, ctx):
        if self.nick == 'sbbdev':
            if ctx is None:
                log.error("Dev bot was asked to whisper, and has no backup context to send to")
                return
            await ctx.send(f"@{user}: {msg}")
        else:
            await self._ws._websocket.send(f"PRIVMSG #jtv :/w {user} {msg}")
