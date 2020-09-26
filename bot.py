import os
from random import choice
from string import Template
import asyncio
import logging

from twitchio.ext.commands import Bot, command, errors, check
import aiohttp

from aio_lookup import ChessComAPI, LichessAPI, APIError, UserNotFound
from sheet import BattleSheet
from db import SettingsDatabase
from twitch_api import add_follow, get_moderated_channels
from globals import *


# Frontend things:
# TODO: Bug: Changing username looks like a different user, giving multiple spots on sheet.
#       - Would have to go by user id in users_on_sheet. ID column on sheet?
#       - Currently goes by lowercased name, so display name changes doesn't give multiple spots
# TODO: Bug: Switching from chess.com to lichess leaves peak columns in place
#       - Separate Header object?
# TODO: Do something about users doing multiple identical apply's?
#       - basically self spamming, but also hogging resources
# TODO: On format setting change, modify sheet accordingly
# TODO: More game types? But 960 and 4pc seems unavailable =/ Among others I suppose
# TODO: Custom prefixes?
# TODO: "Extra" column, for whatever data they want to pass?
# TODO: Provisional ratings


# Backend/feelgood stuff:
# TODO: Tests
# TODO: The requests in ?join pipeline are sync. Switch to aiohttp?
# TODO: More/Better Logging - Not very informative atm and some modules still missing
# TODO: Tidy up error handling
#       - Custom Command (at least) for apply, to use @error and separate away the error handling.
#       - DB has nothing atm
# TODO: Figure out if the _nowait keyword should be used (is it operating in sync now?)
# TODO: ?set procedure is icky
#       -Maybe a @setting deco: verify value (pre) and update DB (post)
# TODO: gspread_asyncio randomly spamming 429 errors (
"""ERROR:gspread_asyncio:Gspread Error {'code': 429, 'message': "Quota exceeded for quota group 'ReadGroup'
and limit 'Read requests per user per 100 seconds' of service 'sheets.googleapis.com' for consumer 'project_number:885487243158'.", 'status': 'RESOURCE_E
XHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Google developer console API key', 'url': 'https://con
sole.developers.google.com/project/885487243158/apiui/credential'}]}]} while calling col_values (1,) {'value_render_option': 'FORMATTED_VALUE'}. Sleeping
 for 1.1 seconds."""



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

def mod_or_sed(ctx):
    user = ctx.author
    return user.is_mod or user.id == SED_ID


def is_me(ctx):
    return ctx.author.id == SED_ID


def is_bot_channel(ctx):
    return ctx.channel.name.lower() == os.environ['BOT_NICK'].lower()


class SubBatBot(Bot):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        log.info(f"Initialized {self.nick}, dev mode = {DEV_MODE}")

        self.add_check(mod_or_sed)

        self.sheets = {}
        self.db = SettingsDatabase()

        # create a template for help message (prefix may vary)
        public_commands = ['apply', 'set', 'clear', 'link', 'help', 'leave']
        docstrings = [cmd._callback.__doc__ for cmd in self.commands.values() if cmd.name in public_commands]
        command_help = '; '.join("${prefix}" + doc for doc in docstrings)
        self.help_msg_template = Template(f"Commands: {command_help}")

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
        for channel_name in channel_names:
            await self.join_channel(channel_name, greet=DEV_MODE)
        print(f"{os.environ['BOT_NICK']} is online!")

    async def join_channel(self, channel_name, greet=False):
        await self.join_channels([channel_name])
        channel_settings = self.db.get_settings(channel_name)
        self.sheets[channel_name] = await BattleSheet.open(channel_name, channel_settings)
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
        except errors.MissingRequiredArgument as e:  # TODO: <-- why is this here?
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
                sheet = self.sheets[ctx.channel.name]
                msg = f"Current settings: {sheet.current_settings}"
            elif error.param.name == 'value':
                msg = BattleSheet.settings_help_string
            else:
                log.debug(f"({ctx.channel.name}) {name} caused '{error}' by typing '{ctx.message.content}'")
                msg = str(error)
            return await ctx.send(msg)
        else:
            log.error(f"({ctx.channel.name}) {name} caused '{error}' by typing '{ctx.message.content}'")
        return await super().event_command_error(ctx, error)

    @check(is_bot_channel)
    @command(name='join', no_global_checks=True)
    async def join(self, ctx, channel_name=None):
        """join - Make the bot join the user's channel"""
        user = ctx.author.name
        if channel_name is None:
            channel_name = user
        elif user != channel_name and channel_name not in get_moderated_channels(user) and ctx.author.id != SED_ID:
            await ctx.send(f"@{ctx.author.display_name} That doesn't look like a channel you mod or own. "
                           "If I'm wrong, try again later or ask Sedsarq to send the bot there.")
            return
        await ctx.send(f"Heading to /{channel_name}!")
        log.info(f"({ctx.channel.name}) Joining {channel_name}")
        await self.join_channel(channel_name, greet=True)
        try:
            add_follow(username=channel_name, db=self.db)
        except Exception as e:
            msg = f"Tried to follow {channel_name} but failed!"
            await self._whisper(user, msg, ctx)
            log.error(e)

    @command(name='leave')
    async def leave(self, ctx, channel_name=None):
        """leave - Make the bot leave the channel"""
        if channel_name is None or ctx.author.id != SED_ID:
            channel_name = ctx.channel.name
        await self.leave_channel(channel_name)
        log.info(f"({ctx.channel.name}) Leaving {channel_name}")

    @command(name='clear')
    async def clear(self, ctx):
        """clear - Reset the spreadsheet"""
        log.debug(f"({ctx.channel.name}) {ctx.author.display_name} uses ?clear")
        sheet = self.sheets[ctx.channel.name]
        await sheet.clear()

    @command(name='link')
    async def link(self, ctx):
        """link - Post link to the spreadsheet"""
        url = self.sheets[ctx.channel.name].url
        user = ctx.author.name
        msg = f"Find the {ctx.channel.name} sheet at {url}"
        await self._whisper(user, msg, ctx)

        log.debug(f"({ctx.channel.name}) {user} got the sheet link by whisper")

    @command(name='help')
    async def help(self, ctx):
        """help - Provide some assistance"""
        log.debug(f"({ctx.channel.name}) {ctx.author.display_name} uses ?help")
        await ctx.send(self.help_msg_template.substitute(prefix=ctx.prefix))

    # disabled command. Should it be a thing? Current version untested.
    #@command(name='draw')
    async def draw(self, ctx, sub_tickets=3, pleb_tickets=1):
        log.debug(f"({ctx.channel.name}) {ctx.author.display_name} uses ?draw {sub_tickets} {pleb_tickets}")
        try:
            sub_tickets = int(sub_tickets)
            pleb_tickets = int(pleb_tickets)
            if sub_tickets < 0 or pleb_tickets < 0:
                raise ValueError
        except ValueError:
            ctx.send('Use non-negative integer numbers for ticket counts, like ?draw 3 1.')
            return
        sheet = self.sheets[ctx.channel.name]
        tickets = []
        for twitch_name, (ws, row) in sheet.users_on_sheet.items():
            if ws.title.lower() == 'subs':
                tickets.extend([twitch_name] * sub_tickets)
            else:
                tickets.extend([twitch_name] * pleb_tickets)
        if not tickets:
            await ctx.send("No names to draw a winner from!")
        else:
            winner = choice(tickets)
            is_sub = sheet.users_on_sheet[winner][0].title.lower() == 'subs'
            n_tickets = sub_tickets if is_sub else pleb_tickets
            ticket_str = f"{n_tickets} ticket" if n_tickets == 1 else f"{n_tickets} tickets"
            await ctx.send(f"/me Out of {len(sheet.users_on_sheet)} players, and a total number of {len(tickets)} tickets, the winner is... *drumroll* ...")
            await asyncio.sleep(10)
            await ctx.send(f"/me ... {winner}, who entered with {ticket_str}! Congratulations!")

    @command(name='set')
    async def set(self, ctx, setting: str, value: str):
        """set setting value - Change settings. Use without arguments for current settings"""
        log.debug(f"({ctx.channel.name}) {ctx.author.display_name} sets {setting} to {value}")
        channel_name = ctx.channel.name
        sheet = self.sheets[channel_name]
        try:
            set_method = getattr(sheet, f"set_{setting}")
            await set_method(value)
            self.db.update_setting(channel_name, setting, value)

        # not a valid setting
        except AttributeError:
            await ctx.send(BattleSheet.settings_help_string)

        # not a valid value
        except ValueError as e:
            await ctx.send(f"@{ctx.author.display_name}: {e}")

#   @monitor to track usage stats and watch out for rate limiting
    async def _whisper(self, user, msg, ctx):
        if self.nick == 'sbbdev':
            if ctx is None:
                log.error("Dev bot was asked to whisper, and don't know where to send the message instead")
                return
            await ctx.send(f"@{user}: {msg}")
        else:
            await self._ws._websocket.send(f"PRIVMSG #jtv :/w {user} {msg}")

    @check(is_me)
    @command(name='test', no_global_checks=True)
    async def test(self, ctx, channel=None):
        pass

    @command(name='apply', no_global_checks=True)
    async def apply(self, ctx, chess_name):
        """apply chess_name - Add user and chess stats to spreadsheet"""
        user = ctx.author
        twitch_name = user.display_name
        sub = user.is_subscriber or 'founder' in user.badges
        sheet = self.sheets[ctx.channel.name]
        site = sheet.site
        api = self.apis[site]
        game_type = sheet.game
        try:
            # regrabbing chess_name to (possibly) collect correct casing from lookup
            chess_name, rating, *peak_data = await api.lookup(chess_name, game_type)
        except UserNotFound:
            msg = f"Lookup failed, couldn't find player \"{chess_name}\" on {site}!"
            await self._whisper(user.name, msg, ctx)
        except APIError as e:
            log.error(f"({ctx.channel.name}) APIError: The lookup for {site}, {game_type}, {chess_name} resulted in '{e}'")
            await self._whisper(user.name, str(e), ctx)
        except Exception as e:
            log.exception(f"({ctx.channel.name}) Unexpected lookup fail: {site}, {game_type}, {chess_name} => {e}")
            await ctx.send(f"Unexpected error! Who knows what happened, tbh.")
        else:
            result = await sheet.add_data(twitch_name, chess_name, rating, *peak_data, sub=sub)
            status = "subscriber" if sub else "non-subscriber"
            if result == 'new':
                msg = f"Thanks for applying! {chess_name} ({rating}) is now on the sheet, marked as {status}."
            elif result == 'updated':
                msg = f"Your details were updated to: {chess_name} ({rating})."
            elif result == 'moved':
                msg = f"Your sub status has changed! {chess_name} ({rating}) is now marked as a {status}."
            else:
                log.error(f"bot.apply: The result {result} from add_data is not being handled! No message sent to {twitch_name}.")
                return
            await self._whisper(user.name, msg, ctx)



if __name__ == "__main__":
    bot = SubBatBot(
        irc_token=os.environ['TMI_TOKEN'],
        client_id=os.environ['CLIENT_ID'],
        nick=os.environ['BOT_NICK'],
        prefix=os.environ['BOT_PREFIX'],
        initial_channels=[os.environ['CHANNEL']],
    )
    bot.run()
