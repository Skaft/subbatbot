from os import environ

DEV_MODE = environ['BOT_NICK'].lower() == 'sbbdev'
SED_ID = 88128608
SBB_ID = 565663874
SBBD_ID = 572514237

# twitch usernames which are skipped if trying to use a command. bots should be skipped so
# they can't be used to sneakily access mod commands
USER_BLACKLIST = ['moobot', 'nightbot', environ['BOT_NICK'].lower()]