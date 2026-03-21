# Googleスプレッドシートへの動画統計書き込みモジュール

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

from analytics_base import StatsStore
from auth_utils import get_credentials

load_dotenv(Path(__file__).parent.parent / ".env")

_SHEET_NAME = "動画統計"
_HEADERS    = ["動画ID", "タイトル", "投稿日", "再生数", "いいね数", "コメント数", "URL", "更新日時"]


class GoogleSheetsStore(StatsStore):
    """Google スプレッドシートに動画統計を保存・読み込む"""

    def __init__(self, spreadsheet_id: str = ""):
        self._spreadsheet_id = spreadsheet_id or os.getenv("SPREADSHEET_ID", "")
        if not self._spreadsheet_id:
            raise ValueError(
                "SPREADSHEET_ID が .env に設定されていません。\n"
                "GoogleスプレッドシートのURLから ID を取得して設定してください。"
            )

    def _service(self):
        return build("sheets", "v4", credentials=get_credentials())

    def _ensure_sheet(self, service) -> None:
        meta       = service.spreadsheets().get(spreadsheetId=self._spreadsheet_id).execute()
        sheet_names = [s["properties"]["title"] for s in meta["sheets"]]
        if _SHEET_NAME not in sheet_names:
            service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": _SHEET_NAME}}}]},
            ).execute()
            service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{_SHEET_NAME}!A1",
                valueInputOption="RAW",
                body={"values": [_HEADERS]},
            ).execute()
            print(f"  シート「{_SHEET_NAME}」を作成しました")

    def _load_existing_ids(self, service) -> dict[str, int]:
        result = service.spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id,
            range=f"{_SHEET_NAME}!A2:A",
        ).execute()
        rows = result.get("values", [])
        return {row[0]: i + 2 for i, row in enumerate(rows) if row}

    def write(self, stats: list[dict]) -> None:
        service  = self._service()
        sheets   = service.spreadsheets()
        now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")

        self._ensure_sheet(service)
        existing_ids = self._load_existing_ids(service)

        update_data = []
        append_rows = []

        for video in stats:
            row = [
                video["video_id"],
                video["title"],
                video["published_at"],
                video["views"],
                video["likes"],
                video["comments"],
                video["url"],
                now_str,
            ]
            if video["video_id"] in existing_ids:
                row_num = existing_ids[video["video_id"]]
                update_data.append({
                    "range":  f"{_SHEET_NAME}!A{row_num}:H{row_num}",
                    "values": [row],
                })
            else:
                append_rows.append(row)

        if update_data:
            sheets.values().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"valueInputOption": "RAW", "data": update_data},
            ).execute()
            print(f"  {len(update_data)} 件を更新しました")

        if append_rows:
            sheets.values().append(
                spreadsheetId=self._spreadsheet_id,
                range=f"{_SHEET_NAME}!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": append_rows},
            ).execute()
            print(f"  {len(append_rows)} 件を新規追加しました")

        print(f"スプレッドシートへの書き込み完了（合計 {len(update_data) + len(append_rows)} 件）")

    def read(self) -> list[dict]:
        service = self._service()
        result  = service.spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id,
            range=f"{_SHEET_NAME}!A2:H",
        ).execute()
        stats = []
        for row in result.get("values", []):
            if len(row) < 7:
                continue
            stats.append({
                "video_id":     row[0],
                "title":        row[1],
                "published_at": row[2],
                "views":        int(row[3]) if row[3] else 0,
                "likes":        int(row[4]) if row[4] else 0,
                "comments":     int(row[5]) if row[5] else 0,
                "url":          row[6],
            })
        return stats
