# SubBatBot
A Twitch bot for chess streamers who engage in Sub Battles.

## What?

In the [Twitch chess community](https://www.twitch.tv/directory/game/Chess), sub(scriber) battles have become a thing. 
Which channel has the best following? Two streamers decide to duel, and eager viewers sign up to play for their favorite streamer. 
They then battle it out in pairs, with players of similar rating going head to head. 
The streamers broadcast and commentate on the games, cheering on, or roasting, their players.

The SubBatBot aims to help organize these battles in the signup phase. The bot relieves streamers and moderators from
taking note of all names and ratings manually, by looking up names and ratings of applying users through chess site API's. 
The information is presented in a google spreadsheet that is unique to the channel.

## Features

 * Simple setup: no installations, authorizations or moderator privileges needed. Just type a command, and it's in your channel ready to use.
 * Sub status aware: Requests from subscribers and non-subscribers are all collected, but stored separately
 * One-entry-per-user: Prevents confusion by providing a single row per user, which updates if user re-applies 
 * Whispers: notifies users without spamming the chat
 * Moderator-friendly: If you want to set it up for a channel you moderate, it's as easy as if you owned the channel
 * Supports both lichess and chess.com
 * Supports ratings for different time controls
 * (*Upcoming*): See Sub Battle statistics for applicants. Who's played before? How did they do? 
 
Further details on usage can be found on the bot's [Twitch account](https://www.twitch.tv/subbatbot/about).
