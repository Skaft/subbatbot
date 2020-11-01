from twitchio.ext.commands import command, check
from twitchio.ext.commands.core import cog

from aio_lookup import APIError, UserNotFound
from twitch_api import add_follow, get_moderated_channels
from globals import *
from exts import checks
from sheet import BattleSheet

import logging
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


@cog()
class Commands:
    def __init__(self, bot):
        self.bot = bot

    @check(checks.is_bot_channel)
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
        await self.bot.join_channel(channel_name, greet=True)
        try:
            add_follow(username=channel_name, db=self.bot.db)
        except Exception as e:
            msg = f"Tried to follow {channel_name} but failed!"
            await self.bot._whisper(user, msg, ctx)
            log.error(e)

    @command(name='leave')
    async def leave(self, ctx, channel_name=None):
        """leave - Make the bot leave the channel"""
        if channel_name is None or ctx.author.id != SED_ID:
            channel_name = ctx.channel.name
        await self.bot.leave_channel(channel_name)
        log.info(f"({ctx.channel.name}) Leaving {channel_name}")

    @command(name='clear')
    async def clear(self, ctx):
        """clear - Reset the spreadsheet"""
        log.debug(f"({ctx.channel.name}) {ctx.author.display_name} uses ?clear")
        sheet = self.bot.get_sheet(ctx.channel.name)
        await sheet.clear()

    @command(name='link')
    async def link(self, ctx):
        """link - Post link to the spreadsheet"""
        url = self.bot.get_sheet(ctx.channel.name).url
        user = ctx.author.name
        msg = f"Find the sheet for channel '{ctx.channel.name}' at {url}"
        await self.bot._whisper(user, msg, ctx)

        log.debug(f"({ctx.channel.name}) {user} got the sheet link by whisper")

    @command(name='help')
    async def help(self, ctx):
        """help - Provide some assistance"""
        log.debug(f"({ctx.channel.name}) {ctx.author.display_name} uses ?help")
        await ctx.send(self.bot.help_msg_template.substitute(prefix=ctx.prefix))

    # disabled command. Should it be a thing? Current version untested.
    # @command(name='draw')
#    async def draw(self, ctx, sub_tickets=3, pleb_tickets=1):
#        log.debug(f"({ctx.channel.name}) {ctx.author.display_name} uses ?draw {sub_tickets} {pleb_tickets}")
#        try:
#            sub_tickets = int(sub_tickets)
#            pleb_tickets = int(pleb_tickets)
#            if sub_tickets < 0 or pleb_tickets < 0:
#                raise ValueError
#        except ValueError:
#            ctx.send('Use non-negative integer numbers for ticket counts, like ?draw 3 1.')
#            return
#        sheet = self.get_sheet(ctx.channel.name)
#        tickets = []
#        for twitch_name, (ws, row) in sheet.users_on_sheet.items():
#            if ws.title.lower() == 'subs':
#                tickets.extend([twitch_name] * sub_tickets)
#            else:
#                tickets.extend([twitch_name] * pleb_tickets)
#        if not tickets:
#            await ctx.send("No names to draw a winner from!")
#        else:
#            winner = choice(tickets)
#            is_sub = sheet.users_on_sheet[winner][0].title.lower() == 'subs'
#            n_tickets = sub_tickets if is_sub else pleb_tickets
#            ticket_str = f"{n_tickets} ticket" if n_tickets == 1 else f"{n_tickets} tickets"
#            await ctx.send(
#                f"/me Out of {len(sheet.users_on_sheet)} players, and a total number of {len(tickets)} tickets, the winner is... *drumroll* ...")
#            await asyncio.sleep(10)
#            await ctx.send(f"/me ... {winner}, who entered with {ticket_str}! Congratulations!")

    @command(name='set')
    async def set(self, ctx, setting: str, value: str):
        """set setting value - Change settings. Use without arguments for current settings"""
        log.debug(f"({ctx.channel.name}) {ctx.author.display_name} sets {setting} to {value}")
        channel_name = ctx.channel.name
        sheet = self.bot.get_sheet(channel_name)
        try:
            set_method = getattr(sheet, f"set_{setting}")
            await set_method(value)
            self.bot.db.update_setting(channel_name, setting, value)

        # not a valid setting
        except AttributeError:
            await ctx.send(BattleSheet.settings_help_string)

        # not a valid value
        except ValueError as e:
            await ctx.send(f"@{ctx.author.display_name}: {e}")

    @check(checks.is_me)
    @command(name='test', no_global_checks=True)
    async def test(self, ctx, channel=None):
        pass

    @command(name='apply', no_global_checks=True)
    async def apply(self, ctx, chess_name):
        """apply chess_name - Add user and chess stats to spreadsheet"""
        if chess_name == 'username':
            return
        user = ctx.author
        twitch_name = user.display_name
        sub = user.is_subscriber or 'founder' in user.badges
        sheet = self.bot.get_sheet(ctx.channel.name)
        site = sheet.site
        api = self.bot.apis[site]
        game_type = sheet.game
        try:
            # regrabbing chess_name to (possibly) collect correct casing from lookup
            chess_name, rating, *peak_data = await api.lookup(chess_name, game_type)
        except UserNotFound:
            msg = f"Lookup failed, couldn't find player \"{chess_name}\" on {site}!"
            await self.bot._whisper(user.name, msg, ctx)
        except APIError as e:
            log.error(
                f"({ctx.channel.name}) APIError: The lookup for {site}, {game_type}, {chess_name} resulted in '{e}'")
            await self.bot._whisper(user.name, str(e), ctx)
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
                log.error(
                    f"bot.apply: The result {result} from add_data is not being handled! No message sent to {twitch_name}.")
                return
            await self.bot._whisper(user.name, msg, ctx)