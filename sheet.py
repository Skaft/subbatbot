from oauth2client.service_account import ServiceAccountCredentials
from oauth2client import crypt, GOOGLE_REVOKE_URI

import gspread_asyncio
import gspread

from collections import Counter
import asyncio
from re import search
import os
import logging
import time


asyncgspread = logging.getLogger('gspread_asyncio')
log = logging.getLogger(__name__)

def get_creds():
    scopes = ''
    service_account_email = os.environ['goog_client_email']
    private_key_pkcs8_pem = os.environ['goog_private_key'].replace(r"\n", "\n")
    private_key_id = os.environ['goog_private_key_id']
    client_id = os.environ['goog_client_id']
    token_uri = os.environ['goog_token_uri']
    revoke_uri = GOOGLE_REVOKE_URI
    signer = crypt.Signer.from_string(private_key_pkcs8_pem)
    credentials = ServiceAccountCredentials(
        service_account_email, signer, scopes=scopes,
        private_key_id=private_key_id, client_id=client_id,
        token_uri=token_uri, revoke_uri=revoke_uri
    )
    credentials._private_key_pkcs8_pem = private_key_pkcs8_pem
    return credentials


class CustomAGCM(gspread_asyncio.AsyncioGspreadClientManager):
    """Subclassed manager for logging access"""
    gspread_errors = Counter()
    ratelim_bin = None
    ratelim_count = None

    async def before_gspread_call(self, method, args, kwargs):
        """Using this prelude to see if I can track the rate limit from this altitude,
        or if there are repeat calls further down the line that this level can't see."""
        bin = int(time.time() // 100)
        if self.ratelim_bin != bin:
            self.ratelim_bin = bin
            self.ratelim_count = 0
        self.ratelim_count += 1
        #if self.ratelim_count > 95:
        #    asyncgspread.warning(f"Close to rate limit: {self.ratelim_count}/100")
        #print(f"Gspread calls: {CustomAGCM.gsp_calls}, method: {method}, args: {args}")

    async def handle_gspread_error(self, e, method, args, kwargs):
        code = e.response.status_code
        #msg = e.response['message']
        CustomAGCM.gspread_errors[code] += 1
        if code == 429:  # Google API's rate limiting
            # noticed = self.ratelim_count >= 100
            delay = 30
            asyncgspread.error(
                f"Gspread Error, rate limit hit! Recorded calls: {self.ratelim_count}/100. Was calling {method.__name__} {args} {kwargs}. Sleeping for {delay} seconds."
            )
        else:
            delay = self.gspread_delay
            asyncgspread.error(
                f"Gspread Error {e} while calling {method.__name__} {args} {kwargs}. Sleeping for {delay} seconds."
            )
        await asyncio.sleep(delay)

    async def handle_requests_error(self, e, method, args, kwargs):
        asyncgspread.error(
            f"Req Error {e} while calling {method.__name__} {args} {kwargs}. Sleeping for {self.gspread_delay} seconds."
        )
        await asyncio.sleep(self.gspread_delay)

    async def _authorize(self):
        now = self._loop.time()
        if self.auth_time is None or self.auth_time + self.reauth_interval < now:
            creds = await self._loop.run_in_executor(None, self.credentials_fn)
            gc = await self._loop.run_in_executor(None, gspread.authorize, creds)
            agc = CustomAGC(self, gc)
            self._agc_cache[now] = agc
            if self.auth_time in self._agc_cache:
                del self._agc_cache[self.auth_time]
            self.auth_time = now
        else:
            agc = self._agc_cache[self.auth_time]
        return agc


class CustomAGC(gspread_asyncio.AsyncioGspreadClient):
    async def open_by_key(self, key, title=None):
        if key in self._ss_cache_key:
            return self._ss_cache_key[key]
        ss = await self.agcm._call(self.gc.open_by_key, key)
        ass = gspread_asyncio.AsyncioGspreadSpreadsheet(self.agcm, ss)
        if title is None:
            title = await ass.get_title()
        self._ss_cache_title[title] = ass
        self._ss_cache_key[key] = ass
        return ass


agcm = CustomAGCM(get_creds)


class BattleSheet:
    settings_help_string = "Available settings: " \
                           "?set site lichess (or chess.com); " \
                           "?set game bullet (or rapid, or blitz)" \
                           "?set format bracket (or space, or none); "

    def __init__(self, channel_name, settings):
        # Better to create through the async open method, which includes the actual sheet object
        self.channel_name = channel_name

        self.sheet = None
        self.last_col = None
        self._header_data = None

        # dict of {username.lower(): (worksheet_title, row_nr)}.
        # Lowercase names to avoid multiple entries by changing display_name
        self.users_on_sheet = {}
        self.sheet_key = settings.get('sheet_key')
        self.url = None

        # settings user can modify
        self.format = settings['format']
        self.site = settings['site']
        self.game = settings['game']

        if self.sheet_key is None:
            settings_summary = ', '.join(f'{key}={value}' for key, value in settings.items())
        else:
            settings_summary = ', '.join(f'{key}={value:.9}' for key, value in settings.items())
        log.info(f"{channel_name}: Initialized BattleSheet with {settings_summary}")

    @property
    def current_settings(self):
        return f"site={self.site}, game={self.game}, format={self.format}"

    @classmethod
    async def open(cls, channel_name, settings):
        battle_sheet = cls(channel_name, settings)
        battle_sheet._create_header_data()
        await battle_sheet._connect_sheet()
        await battle_sheet.refresh_users()
        return battle_sheet

    def _create_header_data(self):
        """Prepare data used to refresh the sheet header"""
        rating_title = f"{self.game} rating".capitalize()
        if self.site == 'chess.com':
            header = ['Twitch', 'Chess.com', rating_title, 'Formatted', 'Peak rating', 'Peak date']
        elif self.site == 'lichess':
            header = ['Twitch', 'Lichess', rating_title, 'Formatted']
        else:
            raise ValueError("Unknown site")
        self.last_col = chr(64 + len(header))
        self._header_data = {
            'range': f"A1:{self.last_col}1",
            'values': [header]
        }

    async def _connect_sheet(self):
        agc = await agcm.authorize()
        try:
            if self.sheet_key:
                self.sheet = await agc.open_by_key(self.sheet_key, self.channel_name)
            else:
                self.sheet = await agc.open(self.channel_name)
                self.sheet_key = self.sheet.ss.id
        except gspread.exceptions.SpreadsheetNotFound:
            log.info(f"{self.channel_name}: Didn't find sheet, making new")
            self.sheet = await self.new_sheet(self.channel_name)
            await self.refresh_headers()
        self.url = self.sheet.ss.url

    @staticmethod
    async def new_sheet(sheet_name):
        agc = await agcm.authorize()
        sheet = await agc.create(sheet_name)
        sheet.ss.share(None, perm_type='anyone', role='reader', notify=False, with_link=True)
        ws1 = await sheet.get_worksheet(0)
        ws1.ws.update_title('Subs')
        await sheet.add_worksheet('Not subs', 100, 28)
        return sheet

    async def set_format(self, value):
        if value == self.format:
            return
        formats = ('none', 'space', 'bracket')
        if value not in formats:
            raise ValueError("Available formats: " + ', '.join(formats))
        self.format = value
        log.debug(f"{self.channel_name}: Switched format to {value}")
        # TODO: update column here

    async def set_site(self, value):
        if value == self.site:
            return
        if value not in ('chess.com', 'lichess'):
            raise ValueError(f"{value} is not an available site. Try lichess or chess.com")
        self.site = value
        log.debug(f"{self.channel_name:} Switched site to {value}")
        self._create_header_data()
        await self.refresh_headers()

    async def set_game(self, value):
        if value == self.game:
            return
        game_types = ('blitz', 'bullet', 'rapid')
        if value not in game_types:
            raise ValueError(f"Available game types are {', '.join(game_types)}")
        self.game = value
        log.debug(f"{self.channel_name}: Switched game to {value}")
        self._create_header_data()
        await self.refresh_headers()

    async def add_data(self, twitch_name, chess_name, rating, *peak_values, sub=True):
        if self.format == 'none':
            format_name = '-'
        elif self.format == 'bracket':
            format_name = f"{chess_name} ({rating})"
        elif self.format == 'space':
            format_name = f"{chess_name} {rating}"
        row_values = [twitch_name, chess_name, rating, format_name, *peak_values]
        agc = await agcm.authorize()
        sheet = await agc.open(self.channel_name)
        if sub:
            ws = await sheet.get_worksheet(0)
        else:
            ws = await sheet.get_worksheet(1)
        last_entry = self.users_on_sheet.get(twitch_name.lower())

        # replace user data
        if last_entry:
            prev_ws_title, prev_row_nr = last_entry
            if ws.title == prev_ws_title:
                await self._replace(ws, prev_row_nr, row_values)
                res = 'updated'

            # user changed sub status
            else:
                prev_ws = await sheet.worksheet(prev_ws_title)
                await prev_ws.delete_row(prev_row_nr)
                await self._append(ws, twitch_name, row_values)
                res = "moved"
        # append new row
        else:
            await self._append(ws, twitch_name, row_values)
            res = "new"
        return res

    async def _append(self, ws, user_name, row_values):
        sheet_title = ws.title
        log.debug(f"{self.channel_name}: Adding {user_name} to {sheet_title}")
        ret = await ws.append_row(row_values)
        row_nr = int(search(r'\d+$', ret['updates']['updatedRange']).group())
        self.users_on_sheet[user_name.lower()] = sheet_title, row_nr

    async def _replace(self, ws, row_nr, values):
        log.debug(f"{self.channel_name}: Replacing {ws.title} row {row_nr} with {values}")
        cells = await ws.range(f'A{row_nr}:{self.last_col}{row_nr}')
        for cell, value in zip(cells, values):
            cell.value = value
        await ws.update_cells(cells)

    async def remove(self):
        log.debug(f"{self.channel_name}: Deleting sheet")
        agc = await agcm.authorize()
        await agc.del_spreadsheet(self.sheet.id)
        title = self.channel_name
        if title in agc._ss_cache_title:
            del agc._ss_cache_title[title]  # gspread_asyncio forgot to remove sheet from this cache (v1.1.0)

    async def batch_get(self, ranges, **params):
        call = self.sheet.agcm._call
        method = self.sheet.ss.values_batch_get
        return await call(method, ranges, params=params)

    async def refresh_users(self):
        d = {}
        ranges = ["'Subs'!A2:A", "'Not subs'!A2:A"]
        resp = await self.batch_get(ranges, majorDimension='COLUMNS')
        for val_range in resp['valueRanges']:
            sheet_name = val_range['range'].split('!')[0].strip("'")
            if 'values' not in val_range:
                continue
            twitch_names = val_range['values'][0]
            twitch_name_to_row_nr = {
                name.lower(): (sheet_name, n)
                for n, name in enumerate(twitch_names, 2)
            }
            d.update(twitch_name_to_row_nr)
        log.debug(f"{self.channel_name}: Refreshed user dict from {len(self.users_on_sheet)} to {len(d)} users")
        self.users_on_sheet = d

    async def refresh_headers(self):
        log.debug(f"{self.channel_name}: Refreshing headers")
        worksheets = await self.sheet.worksheets()
        for ws in worksheets:
            await ws.batch_update([self._header_data])
            # TODO: can this formatting line be awaited?
            ws.ws.format(self._header_data['range'], {"textFormat": {"bold": True}})

    async def clear(self):
        # TODO: Batch update can probably reduce 3 API calls to 1 here
        log.debug(f"{self.channel_name}: Clearing sheet")
        worksheets = await self.sheet.worksheets()
        for ws in worksheets:
            await ws.clear()
        await self.refresh_headers()
        self.users_on_sheet = {}


async def all_sheet_names():
    agc = await agcm.authorize()
    sheets = await agc.openall()
    return [await sheet.get_title() for sheet in sheets]
