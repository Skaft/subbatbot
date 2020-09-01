import os
from random import choice
from string import Template
import asyncio

from twitchio.ext.commands import Bot, command, errors, check
import aiohttp

from aio_lookup import ChessComAPI, LichessAPI, APIError, UserNotFound
from sheet import BattleSheet
from db import SettingsDatabase
from twitch_api import add_follow
from globals import *


# Frontend things to fix:
# TODO: On format setting change, modify sheet accordingly
# TODO: Switching from chess.com to lichess leaves peak columns in place
#       - Separate Header object?
# TODO: Whisper support (when approved for "known" status by twitch)
#       - Setting to make ?link pass through whisper
#       - Notify applying users on success/fail
# TODO: Auto-follow (for followers-only chat)
#       - maybe not - would need some scope thing in auth. manual works for now

# Backend/feelgood stuff:
# TODO: Tests
# TODO: Logging
# TODO: Tidy up error handling
#       - Custom Command (at least) for apply, to use @error and separate away the error handling.
#       - DB has nothing atm
# TODO: Figure out if the _nowait keyword should be used (is it operating in sync now?)
# TODO: users_on_sheet *should* go by user id, not display_name
#       - Needs to either store IDs on the sheet, or in DB, in order to restore on restart
# TODO: ?set procedure is icky
#       -Maybe a @setting deco: verify value (pre) and update DB (post)
# TODO: More game types: 960, bughouse, etc. 4pc seems unavailable =/
# TODO: Custom prefixes?


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


def is_bot_channel(ctx):
    return ctx.channel.name.lower() == os.environ['BOT_NICK'].lower()


class SubBatBot(Bot):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
            print(e)

    async def event_command_error(self, ctx, error):
        user = ctx.author
        name = user.display_name
        pre = ctx.prefix
        if isinstance(error, errors.CheckFailure):
            if str(error).endswith('mod_or_sed'):
                return
                #msg = f"Only the {pre}apply command is available to non-moderators, sorry!"
                #return await ctx.send(f"@{name}: {msg}")
        elif isinstance(error, errors.CommandNotFound):
            # just ignore this error as it doesn't have to be someone trying to use the bot
            return
        elif isinstance(error, errors.MissingRequiredArgument):
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
                msg = str(error)
            return await ctx.send(f"@{name}: {msg}")
        return await super().event_command_error(ctx, error)

    @check(is_bot_channel)
    @command(name='join', no_global_checks=True)
    async def join(self, ctx, channel_name=None):
        """join - Make the bot join the user's channel"""
        # Giving myself the option to make it join others' channels
        user_id = ctx.author.id
        if user_id != SED_ID:
            channel_name = ctx.author.name.lower()
        add_follow(user_id=user_id, db=self.db)
        await self.join_channel(channel_name, greet=True)

    @command(name='leave')
    async def leave(self, ctx, channel_name=None):
        """leave - Make the bot leave the channel"""
        if ctx.author.id == SED_ID:
            await self.leave_channel(channel_name)
        else:
            await self.leave_channel(ctx.channel.name)

    @command(name='clear')
    async def clear(self, ctx):
        """clear - Reset the spreadsheet"""
        sheet = self.sheets[ctx.channel.name]
        await sheet.clear()

    @command(name='link')
    async def link(self, ctx):
        """link - Post link to the spreadsheet"""
        sheet = self.sheets[ctx.channel.name]
        await ctx.send(f"Find the sheet at {sheet.url}")

    @command(name='help')
    async def help(self, ctx):
        """help - Provide some assistance"""
        await ctx.send(self.help_msg_template.substitute(prefix=ctx.prefix))

    @command(name='draw')
    async def draw(self, ctx):
        sheet = self.sheets[ctx.channel.name]
        tickets = []
        for twitch_name, (ws, row) in sheet.users_on_sheet.items():
            if ws.title.lower() == 'subs':
                tickets.extend([twitch_name] * 3)
            else:
                tickets.extend([twitch_name] * 1)
        if not tickets:
            await ctx.send("No names to draw a winner from!")
        else:
            winner = choice(tickets)
            is_sub = sheet.users_on_sheet[winner][0].title.lower() == 'subs'
            ticket_str = "3 tickets" if is_sub else "1 ticket"
            await ctx.send(f"/me Out of {len(sheet.users_on_sheet)} players, and a total number of {len(tickets)} tickets, the winner is... *drumroll* ...")
            await asyncio.sleep(10)
            await ctx.send(f"/me ... {winner}, who entered with {ticket_str}! Congratulations!")

    @command(name='set')
    async def set(self, ctx, setting: str, value: str):
        """set setting value - Change settings. Use without arguments for current settings"""
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

    #@command(name='test')
    #async def test(self, ctx):
    #    pass

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
            await ctx.send(f"@{twitch_name}: Couldn't find player \"{chess_name}\" on {site}!")
        except APIError as e:
            await ctx.send(f"@{twitch_name}: {e}")
        except Exception as e:
            # TODO: actual logging here
            print(f"Unexpected error: {e}")
            await ctx.send(f"Unexpected error, please let Sedsarq know!")
        else:
            result = await sheet.add_data(twitch_name, chess_name, rating, *peak_data, sub=sub)
            #if result == 'new':
            #    await ctx.send(f"Thanks @{twitch_name}! {chess_name} ({rating}) has applied.")
            #elif result == 'updated':
            #    await ctx.send(f"@{twitch_name}: Details updated! ({chess_name}, {rating})")
            #elif result == 'moved':
            #    role = 'sub' if sub else 'non-sub'
            #    await ctx.send(f"@{twitch_name}: You're now on the sheet as a {role}.")


if __name__ == "__main__":
    bot = SubBatBot(
        irc_token=os.environ['TMI_TOKEN'],
        client_id=os.environ['CLIENT_ID'],
        nick=os.environ['BOT_NICK'],
        prefix=os.environ['BOT_PREFIX'],
        initial_channels=[os.environ['CHANNEL']],
    )
    bot.run()
