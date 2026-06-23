import os
import json
import gspread
from google.oauth2.service_account import Credentials

BP_SHEET_ID = os.environ.get("BP_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(info, scopes=scopes)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key(BP_SHEET_ID)

src = spreadsheet.worksheet("血壓紀錄")

try:
    trend = spreadsheet.worksheet("趨勢圖")
    spreadsheet.del_worksheet(trend)
except gspread.exceptions.WorksheetNotFound:
    pass

trend = spreadsheet.add_worksheet(title="趨勢圖", rows=200, cols=10)
trend_sheet_id = trend.id

trend.update("A1:E1", [["日期", "早上收縮壓", "早上舒張壓", "晚上收縮壓", "晚上舒張壓"]])

all_vals = src.get_all_values()
num_rows = len(all_vals) - 1

if num_rows > 0:
    formulas = []
    for i in range(2, num_rows + 2):
        formulas.append([
            f"='血壓紀錄'!A{i}",
            f"='血壓紀錄'!B{i}",
            f"='血壓紀錄'!C{i}",
            f"='血壓紀錄'!F{i}",
            f"='血壓紀錄'!G{i}",
        ])
    trend.update(f"A2:E{num_rows+1}", formulas, value_input_option="USER_ENTERED")

requests_body = {
    "requests": [
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "血壓趨勢圖（早晚收縮壓/舒張壓）",
                        "basicChart": {
                            "chartType": "LINE",
                            "legendPosition": "BOTTOM_LEGEND",
                            "axis": [
                                {"position": "BOTTOM_AXIS", "title": "日期"},
                                {"position": "LEFT_AXIS", "title": "mmHg"}
                            ],
                            "domains": [{
                                "domain": {
                                    "sourceRange": {
                                        "sources": [{
                                            "sheetId": trend_sheet_id,
                                            "startRowIndex": 0,
                                            "endRowIndex": num_rows + 1,
                                            "startColumnIndex": 0,
                                            "endColumnIndex": 1
                                        }]
                                    }
                                }
                            }],
                            "series": [
                                {"series": {"sourceRange": {"sources": [{"sheetId": trend_sheet_id, "startRowIndex": 0, "endRowIndex": num_rows + 1, "startColumnIndex": 1, "endColumnIndex": 2}]}}, "targetAxis": "LEFT_AXIS"},
                                {"series": {"sourceRange": {"sources": [{"sheetId": trend_sheet_id, "startRowIndex": 0, "endRowIndex": num_rows + 1, "startColumnIndex": 2, "endColumnIndex": 3}]}}, "targetAxis": "LEFT_AXIS"},
                                {"series": {"sourceRange": {"sources": [{"sheetId": trend_sheet_id, "startRowIndex": 0, "endRowIndex": num_rows + 1, "startColumnIndex": 3, "endColumnIndex": 4}]}}, "targetAxis": "LEFT_AXIS"},
                                {"series": {"sourceRange": {"sources": [{"sheetId": trend_sheet_id, "startRowIndex": 0, "endRowIndex": num_rows + 1, "startColumnIndex": 4, "endColumnIndex": 5}]}}, "targetAxis": "LEFT_AXIS"}
                            ],
                            "headerCount": 1
                        }
                    },
                    "position": {
                        "newSheet": False,
                        "overlayPosition": {
                            "anchorCell": {"sheetId": trend_sheet_id, "rowIndex": 1, "columnIndex": 6},
                            "widthPixels": 900,
                            "heightPixels": 450
                        }
                    }
                }
            }
        }
    ]
}

spreadsheet.batch_update(requests_body)
print("✅ 趨勢圖分頁建立完成！")
