from oauth2client.service_account import ServiceAccountCredentials
from oauth2client import crypt, GOOGLE_REVOKE_URI

import gspread_asyncio
from gspread.exceptions import SpreadsheetNotFound

import asyncio
from re import search
import os

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


agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)


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
        self.users_on_sheet = {}
        self.url = None

        # settings user can modify
        self.format = settings['format']
        self.site = settings['site']
        self.game = settings['game']

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
            self.sheet = await agc.open(self.channel_name)
        except SpreadsheetNotFound:
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
        # TODO: update column here

    async def set_site(self, value):
        if value == self.site:
            return
        if value not in ('chess.com', 'lichess'):
            raise ValueError(f"{value} is not an available site. Try lichess or chess.com")
        self.site = value
        self._create_header_data()
        await self.refresh_headers()

    async def set_game(self, value):
        if value == self.game:
            return
        game_types = ('blitz', 'bullet', 'rapid')
        if value not in game_types:
            raise ValueError(f"Available game types are {', '.join(game_types)}")
        self.game = value
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
        last_entry = self.users_on_sheet.get(twitch_name)

        # replace user data
        if last_entry:
            prev_ws, prev_row_nr = last_entry
            if ws == prev_ws:
                await self._replace(ws, prev_row_nr, row_values)
                res = 'updated'

            # user changed sub status
            else:
                await prev_ws.delete_row(prev_row_nr)
                await self._append(ws, twitch_name, row_values)
                res = "moved"
        # append new row
        else:
            await self._append(ws, twitch_name, row_values)
            res = "new"
        return res

    async def _append(self, ws, user_id, row_values):
        ret = await ws.append_row(row_values)
        row_nr = int(search(r'\d+$', ret['updates']['updatedRange']).group())
        self.users_on_sheet[user_id] = ws, row_nr

    async def _replace(self, ws, row_nr, values):
        cells = await ws.range(f'A{row_nr}:{self.last_col}{row_nr}')
        for cell, value in zip(cells, values):
            cell.value = value
        await ws.update_cells(cells)

    async def remove(self):
        agc = await agcm.authorize()
        await agc.del_spreadsheet(self.sheet.id)
        title = self.channel_name
        if title in agc._ss_cache_title:
            del agc._ss_cache_title[title]  # gspread_asyncio forgot to remove sheet from this cache (v1.1.0)

    async def refresh_users(self):
        d = {}
        worksheets = await self.sheet.worksheets()
        for ws in worksheets:
            twitch_name_col = await ws.col_values(1)
            twitch_name_to_row_nr = {name: (ws, n) for n, name in enumerate(twitch_name_col[1:], 2)}
            d.update(twitch_name_to_row_nr)
        self.users_on_sheet = d

    async def refresh_headers(self):
        worksheets = await self.sheet.worksheets()
        for ws in worksheets:
            await ws.batch_update([self._header_data])
            # TODO: can this formatting line be awaited?
            ws.ws.format(self._header_data['range'], {"textFormat": {"bold": True}})

    async def clear(self):
        worksheets = await self.sheet.worksheets()
        for ws in worksheets:
            await ws.clear()
        await self.refresh_headers()
        self.users_on_sheet = {}


async def all_sheet_names():
    agc = await agcm.authorize()
    sheets = await agc.openall()
    return [await sheet.get_title() for sheet in sheets]
