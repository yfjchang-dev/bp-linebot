import os
import json
import gspread
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage,
    TemplateMessage, ConfirmTemplate, PostbackAction
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, PostbackEvent
)
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
BP_SHEET_ID = os.environ.get("BP_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
LINE_USER_ID = os.environ.get("LINE_USER_ID")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def get_sheet():
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(BP_SHEET_ID)
    try:
        sheet = spreadsheet.worksheet("血壓紀錄")
    except Exception:
        sheet = spreadsheet.add_worksheet(title="血壓紀錄", rows=1000, cols=10)
        sheet.append_row(["日期", "早上收縮壓", "早上舒張壓", "早上脈搏", "早上服藥",
                          "晚上收縮壓", "晚上舒張壓", "晚上脈搏", "晚上服藥", "備註"])
    return sheet

user_state = {}

def bp_status(sys, dia):
    if sys < 120 and dia < 80:
        return "✅ 正常"
    elif sys < 130 and dia < 80:
        return "⚠️ 偏高"
    elif sys < 140 or dia < 90:
        return "⚠️ 高血壓前期"
    else:
        return "🔴 高血壓"

def save_to_sheet(date_str, slot, sys, dia, pulse, took_med):
    sheet = get_sheet()
    records = sheet.get_all_values()
    today_row = None
    for i, row in enumerate(records[1:], start=2):
        if row[0] == date_str:
            today_row = i
            break

    med_str = "✅ 有" if took_med else "❌ 沒有"

    if today_row:
        if slot == "morning":
            sheet.update(f"B{today_row}:E{today_row}", [[sys, dia, pulse, med_str]])
        else:
            sheet.update(f"F{today_row}:I{today_row}", [[sys, dia, pulse, med_str]])
    else:
        if slot == "morning":
            sheet.append_row([date_str, sys, dia, pulse, med_str, "", "", "", "", ""])
        else:
            sheet.append_row([date_str, "", "", "", "", sys, dia, pulse, med_str, ""])

def reply_text(reply_token, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )

def reply_confirm(reply_token, text, label1, data1, label2, data2):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TemplateMessage(
                    alt_text=text,
                    template=ConfirmTemplate(
                        text=text,
                        actions=[
                            PostbackAction(label=label1, data=data1),
                            PostbackAction(label=label2, data=data2),
                        ]
                    )
                )]
            )
        )

def push_text(user_id, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=text)]
            )
        )

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    print(f"User ID: {user_id}")

    state = user_state.get(user_id, {})

    if state.get("step") == "input_sys":
        try:
            sys_val = int(text)
            user_state[user_id]["sys"] = sys_val
            user_state[user_id]["step"] = "input_dia"
            reply_text(event.reply_token, "請輸入舒張壓（低壓）數值：")
        except ValueError:
            reply_text(event.reply_token, "請輸入數字，例如：120")
        return

    if state.get("step") == "input_dia":
        try:
            dia_val = int(text)
            user_state[user_id]["dia"] = dia_val
            user_state[user_id]["step"] = "input_pulse"
            reply_text(event.reply_token, "請輸入脈搏（心跳）數值：")
        except ValueError:
            reply_text(event.reply_token, "請輸入數字，例如：72")
        return

    if state.get("step") == "input_pulse":
        try:
            pulse_val = int(text)
            tz = pytz.timezone("Asia/Taipei")
            now = datetime.now(tz)
            date_str = now.strftime("%Y/%m/%d")
            slot = user_state[user_id]["slot"]
            sys_val = user_state[user_id]["sys"]
            dia_val = user_state[user_id]["dia"]
            took_med = user_state[user_id]["took_med"]

            save_to_sheet(date_str, slot, sys_val, dia_val, pulse_val, took_med)

            status = bp_status(sys_val, dia_val)
            slot_str = "🌅 早上" if slot == "morning" else "🌙 晚上"
            med_str = "✅ 有服藥" if took_med else "❌ 未服藥"

            reply = f"""✅ 紀錄完成！

📅 {date_str} {slot_str}
💉 收縮壓：{sys_val} mmHg
💉 舒張壓：{dia_val} mmHg
❤️ 脈搏：{pulse_val} bpm
💊 服藥：{med_str}

判斷：{status}"""

            reply_text(event.reply_token, reply)
            user_state.pop(user_id, None)
        except ValueError:
            reply_text(event.reply_token, "請輸入數字，例如：72")
        return

    if text in ["早上量血壓", "晚上量血壓", "早上", "晚上"]:
        slot = "morning" if "早" in text else "evening"
        user_state[user_id] = {"slot": slot}
        slot_str = "🌅 早上" if slot == "morning" else "🌙 晚上"
        reply_confirm(
            event.reply_token,
            f"{slot_str} 量血壓\n\n💊 今天有吃血壓藥嗎？",
            "✅ 有吃", f"med=yes&user={user_id}",
            "❌ 沒吃", f"med=no&user={user_id}"
        )
        return

    reply_text(event.reply_token, '請點選「🌅 早上量血壓」或「🌙 晚上量血壓」開始記錄！')

@handler.add(PostbackEvent)
def handle_postback(event):
    data = dict(item.split("=") for item in event.postback.data.split("&"))
    user_id = event.source.user_id
    took_med = data.get("med") == "yes"

    if user_id in user_state:
        user_state[user_id]["took_med"] = took_med
        user_state[user_id]["step"] = "input_sys"

    med_str = "✅ 有吃" if took_med else "❌ 沒吃"
    reply_text(event.reply_token, f"💊 {med_str}\n\n請輸入收縮壓（高壓）數值：")

def send_reminder(slot):
    if not LINE_USER_ID:
        return
    last_date_key = f"last_reminded_{slot}"
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y/%m/%d")

    if user_state.get(last_date_key) == today:
        return
    user_state[last_date_key] = today

    if slot == "morning":
        msg = "🌅 早安！\n\n早上 9:00 量血壓時間到了！\n\n請回覆「早上量血壓」開始記錄 💪"
    else:
        msg = "🌙 晚安！\n\n晚上 8:00 量血壓時間到了！\n\n請回覆「晚上量血壓」開始記錄 💪"

    push_text(LINE_USER_ID, msg)

scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(lambda: send_reminder("morning"), "cron", hour=8, minute=50)
scheduler.add_job(lambda: send_reminder("evening"), "cron", hour=19, minute=50)
scheduler.start()

if __name__ == "__main__":
    app.run(port=5000)
