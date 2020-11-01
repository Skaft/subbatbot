"""
A module for looking up blitz stats of players on chess.com.
"""

from aiohttp import ClientResponseError, ClientConnectionError
from datetime import date
import asyncio


class APIError(Exception):
    pass


class UserNotFound(Exception):
    pass


class API:
    site = None

    def __init__(self, session):
        self._session = session
        self.lock = asyncio.Lock()

    def log(*args):
        """Save info of unexpected errors"""
        # TODO
        print(args)


class ChessComAPI(API):
    site = 'chess.com'
    fields = {
        'blitz': 'chess_blitz',
        'bullet': 'chess_bullet',
        'rapid': 'chess_rapid',
    }
    async def lookup(self, name, game_type='blitz'):
        """Return the current and best ever chess.com rating for the given player name"""
        url = f"https://api.chess.com/pub/player/{name}/stats"
        stats = await self._call(url)
        field = ChessComAPI.fields[game_type]
        try:
            rating_data = stats[field]
        except KeyError:
            raise APIError(f"No rating data found for {name} in {game_type}")
        else:
            # last_rating should not be missing since rating_data could be collected
            last_rating = rating_data['last']['rating']

            # but best_rating could be missing, if player has won no games for example
            try:
                best_rating = rating_data['best']['rating']
                best_date = str(date.fromtimestamp(rating_data['best']['date']))
            except KeyError:
                best_rating = '-'
                best_date = '-'
            # could collect proper casing on name from response of https://api.chess.com/pub/player/playername,
            # is it worth a second api call?
            return name, last_rating, best_rating, best_date

    async def _call(self, url):
        try:
            async with self.lock:
                async with self._session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except ClientResponseError as e:
            if resp.status == 404:
                # In the general case, 404 doesn't necessarily mean a *user* doesn't exist!
                raise UserNotFound
            elif resp.status == 410:
                raise APIError("That request confused even chess.com.")
            elif resp.status == 429:
                # hopefully this doesnt happen due to locks
                self.log(f"Hit rate limit from chess.com!")
                raise APIError("Too many requests; try again.")
            else:
                self.log(f"Status code {resp.status} on requesting {url}:\n{e}")
                raise
        except ClientConnectionError:
            raise APIError(f"Couldn't connect to {self.site}")


class LichessAPI(API):
    site = 'lichess'
    fields = {
        'blitz': 'blitz',
        'bullet': 'bullet',
        'rapid': 'rapid',
    }
    async def lookup(self, name, game_type='blitz'):
        """Return the current lichess rating for the given player name"""
        url = f"https://lichess.org/api/user/{name}"
        profile = await self._call(url)
        rating = profile['perfs'][game_type]['rating']
        cased_name = profile['username']
        return [cased_name, rating]

    async def _call(self, url):
        try:
            async with self.lock:
                async with self._session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except ClientResponseError as e:
            if e.status == 404:
                raise UserNotFound
            print(f'lichess {url}', e)
            raise
        except ClientConnectionError:
            raise APIError(f"Couldn't connect to {self.site}")
