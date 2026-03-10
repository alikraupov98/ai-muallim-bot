# ai_muallim_bot.py
# Бот с памятью контекста + новый промпт
# Запуск: python ai_muallim_bot.py

import os
import logging
import asyncio
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Загрузка переменных окружения
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PUTER_AUTH_TOKEN = os.getenv("PUTER_AUTH_TOKEN")

if not BOT_TOKEN or not PUTER_AUTH_TOKEN:
    print("❌ ОШИБКА: Создай файл .env с BOT_TOKEN и PUTER_AUTH_TOKEN")
    exit(1)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= ПАМЯТЬ БОТА (контекст пользователей) =================
# Хранит: user_id -> {class, subject, name, messages_history}
user_contexts = {}

def get_user_context(user_id: int) -> dict:
    """Возвращает или создаёт контекст для пользователя"""
    if user_id not in user_contexts:
        user_contexts[user_id] = {
            "name": None,
            "class": None,      # синф
            "subject": None,    # фан
            "messages": []      # история диалога (последние 10 сообщений)
        }
    return user_contexts[user_id]

def add_to_history(user_id: int, role: str, content: str, max_len: int = 10):
    """Добавляет сообщение в историю пользователя"""
    ctx = get_user_context(user_id)
    ctx["messages"].append({"role": role, "content": content})
    # Ограничиваем историю, чтобы не переполнять память
    if len(ctx["messages"]) > max_len:        ctx["messages"] = ctx["messages"][-max_len:]

# ================= НАСТРОЙКИ PUTER API =================
PUTER_API_URL = "https://api.puter.com/puterai/openai/v1/chat/completions"
AI_MODEL = "grok-4-1-fast"  # Можно заменить на: gpt-5-nano, claude-sonnet-4-5, llama-4

# ================= НОВЫЙ SYSTEM PROMPT (твой вариант) =================
SYSTEM_PROMPT = """
Ту AI Муаллим ҳастӣ — репетитори хушмуомила ва ҳавасмандкунанда барои хонандагони синфҳои 5–9 дар Тоҷикистон.
Ҳадафи ягонаи ту — кӯмак расонидан ба дарсҳои мактабӣ.

Қоидаҳои қатъӣ (ҳеҷ гоҳ вайрон накун):
1. Ҳаргиз аз саволи ҳозираи хонанда дур нашав. Ба мавзӯъҳои дигар нагузар, "ё чизи дигар мехоҳӣ?" нагӯ.
2. Агар синф ё фанро нагуфта бошад — як бор пурс: "Кадом синф ҳастӣ? Кадом фан мехоҳӣ омӯзем?" — ва то ҷавоб надиҳад, шарҳ надиҳ.
3. Баъд аз гирифтани синф ва фан — дигар ҳеҷ гоҳ инро напурс, то хонанда худ тағйир надиҳад.
4. Усули Сократро истифода кун: 1–2 саволи роҳнамоӣ диҳ, то хонанда худ ба ҷавоб расад. Ҷавоби тайёрро фавран надиҳ.
5. Ҳар вақт таъриф кун, аммо кӯтоҳ: «Афарин!», «Молодец!», «Хеле хуб!», «Хеле хуб фикр кардӣ!».
6. Мисолҳо аз ҳаёти Тоҷикистонро танҳо ҳангоме истифода кун, ки ба фаҳмидани мавзӯъ кӯмак мерасонад (бозор, Помир, помидор, бодиринг, пахта, Душанбе, кӯҳҳо, себҳо ва ғ.).
7. Ҷавобҳо ҳамеша ба тоҷикӣ ё русӣ бошанд (омезиш додан мумкин, аммо ба забонҳои дигар нагузар).
8. Ҷавобҳо кӯтоҳ, равшан ва барои телефон мувофиқ бошанд. Ҳеҷ гоҳ аз 5–7 сатр зиёд нанавис.
9. Агар хонанда аз мавзӯъ дур шавад (шӯхӣ, гапҳои шахсӣ, ҳазлҳо) — нарм ба дарс баргардон: «Биё ба дарс баргардем 😊 Чӣ мехоҳӣ ҳал кунем?».
10. Ҳаргиз аз нақши репетитор берун нашав. Ҳазлҳо, хабарҳо, ҳикояҳо нақл накун, агар ба дарс кӯмак нарасонад.

Мисоли рафтори дуруст:
Хонанда: Касрҳо чист?
Ту: Офарин, ки пурсидӣ! 😊 Аввал бигӯ, кадом синф ҳастӣ? 5, 6 ё 7?

Хонанда: 6 синф
Ту: Хеле хуб! Каср — ин вақте ки як чизро ба қисмҳо тақсим мекунем. Масалан, як себро ба 4 қисм кардӣ — ин чӣ мешавад? Чӣ фикр мекунӣ?
"""

# ================= ФУНКЦИЯ ЗАПРОСА К PUTER =================
async def get_ai_response(user_id: int, user_message: str) -> str:
    """Отправляет запрос к Puter API с историей диалога"""
    try:
        ctx = get_user_context(user_id)
        
        def _make_request():
            # Формируем messages: system + история + текущий вопрос
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(ctx["messages"])  # добавляем историю
            messages.append({"role": "user", "content": user_message})  # текущий вопрос
            
            payload = {
                "model": AI_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 400  # коротки ответи барои телефон
            }
            headers = {                "Authorization": f"Bearer {PUTER_AUTH_TOKEN}",
                "Content-Type": "application/json"
            }
            return requests.post(
                PUTER_API_URL,
                headers=headers,
                json=payload,
                timeout=30
            )

        response = await asyncio.to_thread(_make_request)
        
        if response.status_code != 200:
            logger.error(f"Puter API Error {response.status_code}: {response.text[:200]}")
            return f"❌ Хатои сервер ({response.status_code}). Кӯшиш кунед баъдтар."
        
        data = response.json()
        ai_reply = data["choices"][0]["message"]["content"].strip()
        
        # Сохраняем диалог в память
        add_to_history(user_id, "user", user_message)
        add_to_history(user_id, "assistant", ai_reply)
        
        return ai_reply

    except requests.exceptions.Timeout:
        logger.error("Timeout error")
        return "⏳ Сервер дер ҷавоб дод. Лутфан, дубора нависед."
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return f"❌ Хато: {str(e)[:100]}..."

# ================= ОБРАБОТЧИКИ TELEGRAM =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start — сбрасывает контекст для нового диалога"""
    user = update.effective_user
    user_id = user.id
    
    # Сброс контекста при новом старте
    user_contexts[user_id] = {
        "name": user.first_name,
        "class": None,
        "subject": None,
        "messages": []
    }
    
    text = (
        f"Салом, {user.first_name}! 👋\n\n"
        "Ман **AI Муаллим** ҳастам — репетитори шахсии ту.\n"
        "✅ Математика, забони тоҷикӣ, русӣ, физика ва ғ.\n"        "✅ Синфҳои 5-9\n"
        "✅ Ҷавобҳо бо мисолҳо аз ҳаёти Тоҷикистон 🇹🇯\n\n"
        "Аввал бигӯ: **кадом синф ҳастӣ?** ва **кадом фан мехоҳӣ омӯзем?**"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений с памятью контекста"""
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_id = user.id
    user_text = update.message.text.strip()
    
    if len(user_text) < 2:
        await update.message.reply_text("Лутфан, каме муфассалтар нависед 😊")
        return

    # Показываем индикатор
    thinking_msg = await update.message.reply_text("🤔 Фикр мекунам...")

    # Получаем ответ от AI (с историей диалога!)
    ai_answer = await get_ai_response(user_id, user_text)

    # Отправляем ответ
    try:
        await thinking_msg.edit_text(ai_answer)
    except Exception:
        await update.message.reply_text(ai_answer)
        await thinking_msg.delete()

# ================= ЗАПУСК БОТА =================
def main():
    logger.info(f"Запуск бота с моделью: {AI_MODEL} + ПАМЯТЬ КОНТЕКСТА")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print(f"✅ Бот запущен! Модель: {AI_MODEL}")
    print("🧠 Память контекста: ВКЛЮЧЕНА")
    print("💡 Нажмите Ctrl+C для остановки")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
