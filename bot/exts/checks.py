import os

from bot.globals import *


def mod_or_sed(ctx):
    user = ctx.author
    return user.is_mod or user.id == SED_ID


def is_me(ctx):
    return ctx.author.id == SED_ID


def is_bot_channel(ctx):
    return ctx.channel.name.lower() == os.environ['BOT_NICK'].lower()
