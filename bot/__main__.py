import os

from dotenv import load_dotenv
load_dotenv()

from bot import SubBatBot


if __name__ == "__main__":
    bot = SubBatBot(
        irc_token=os.environ['TMI_TOKEN'],
        client_id=os.environ['CLIENT_ID'],
        nick=os.environ['BOT_NICK'],
        prefix=os.environ['BOT_PREFIX'],
        initial_channels=[os.environ['CHANNEL']],
    )
    bot.run()