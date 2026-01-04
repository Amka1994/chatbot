from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
import requests
import logging
from xai_sdk import Client
from xai_sdk.chat import user, system
from prompts.system_prompt import SYSTEM_PROMPT
from prompts.faq_keywords import FAQ_KEYWORDS

load_dotenv()

app = Flask(__name__)

# Лог хадгалах (алдаа шалгахад амар болно)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Grok клиент
client = Client(api_key=os.getenv("XAI_API_KEY"))

# Хэрэглэгч бүрийн чат түүх (memory)
user_chats = {}

# Түүхийг хязгаарлах (давхар хариулахыг багасгах)
MAX_HISTORY_MESSAGES = 40  # system + 20 user/assistant pair

def get_chat(user_id: str):
    if user_id not in user_chats:
        chat = client.chat.create(model="grok-4-1-fast-reasoning")
        chat.append(system(SYSTEM_PROMPT))
        user_chats[user_id] = chat
    else:
        chat = user_chats[user_id]
        # Түүхийг хэт урт болгохгүй
        if len(chat.messages) > MAX_HISTORY_MESSAGES:
            # System prompt хадгалаад сүүлийн 38-г авна
            chat.messages = chat.messages[:1] + chat.messages[- (MAX_HISTORY_MESSAGES - 1):]
    return chat

def send_message(recipient_id: str, text: str):
    token = os.getenv("PAGE_ACCESS_TOKEN")
    if not token:
        logger.error("PAGE_ACCESS_TOKEN .env-д байхгүй байна!")
        return False

    url = "https://graph.facebook.com/v20.0/me/messages"  # Шинэ version
    payload = {
        "messaging_type": "RESPONSE",
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    try:
        response = requests.post(
            url,
            json=payload,
            params={"access_token": token},
            timeout=10
        )
        if response.status_code == 200:
            logger.info(f"Хариу амжилттай илгээгдлээ ({len(text)} тэмдэгт)")
            return True
        else:
            logger.error(f"Facebook алдаа ({response.status_code}): {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Хүсэлт илгээхэд алдаа: {e}")
        return False

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        # Verification
        verify_token = os.getenv("VERIFY_TOKEN")
        if request.args.get('hub.verify_token') == verify_token:
            return request.args.get('hub.challenge')
        return 'Invalid verify token', 403

    elif request.method == 'POST':
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data"}), 400

        try:
            for entry in data.get('entry', []):
                for messaging in entry.get('messaging', []):
                    if 'message' in messaging:
                        sender_id = messaging['sender']['id']
                        message = messaging['message']

                        if message.get('is_echo'):  # Өөрийн илгээсэн мессеж бол алгас
                            continue

                        if 'text' in message:
                            text = message['text'].strip()
                            if not text:
                                continue

                            logger.info(f"Мессеж хүлээн авлаа from {sender_id}: {text}")

                            text_lower = text.lower()

                            # FAQ шалгалт (хурдан, алдаагүй хариу)
                            reply = None
                            for keyword, faq_response in FAQ_KEYWORDS.items():
                                if keyword in text_lower:
                                    reply = faq_response
                                    logger.info("FAQ таарсан – шууд хариулна")
                                    break

                            # Hybrid: FAQ олдвол шууд, олдвол Grok
                            if reply:
                                send_message(sender_id, reply)
                            else:
                                try:
                                    chat = get_chat(sender_id)
                                    chat.append(user(text))
                                    grok_response = chat.sample(
)
                                    reply = grok_response.content.strip()
                                    send_message(sender_id, reply)
                                except Exception as e:
                                    logger.error(f"Grok алдаа: {e}")
                                    send_message(sender_id, "Уучлаарай, одоо хариулахад асуудал гарлаа. Дараа дахин оролдоно уу 🙏")
        except Exception as e:
            logger.error(f"Webhook боловсруулахад алдаа: {e}")

        return jsonify({"status": "ok"}), 200

# Production-д зориулсан сервер (локал туршилтад Flask dev сервер хэрэглэ)
if __name__ == '__main__':
    debug_mode = os.getenv("DEBUG", "True").lower() == "true"
    if debug_mode:
        print("🚀 Development сервер аслаа – http://127.0.0.1:5000")
        app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
    else:
        # Production-д Waitress ашигла (Render дээр автоматаар ажиллана)
        from waitress import serve
        print("🚀 Production сервер аслаа – http://0.0.0.0:5000")
        serve(app, host="0.0.0.0", port=5000, threads=16)