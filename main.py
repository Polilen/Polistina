import json
import os
import random
import threading
import base64
import requests
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)
from PIL import Image

TOKEN = "8320309750:AAHoAET0wBIIwMx49pr6k-2ArGK2mnwxQeA"

friends_file = "friends.json"
known_users_file = "known_users.json"

# --- Локи для потокобезпеки ---
friends_lock = threading.Lock()
users_lock = threading.Lock()

# --- Функції для GitHub ---
def save_file_to_github(file_path):
    """
    Зберігає конкретний JSON файл у GitHub
    """
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPO", "Polilen/tgbot").strip()

    if not token:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
        headers = {"Authorization": f"Bearer {token}"}

        # Отримуємо SHA поточного файлу
        r = requests.get(url, headers=headers)
        sha = r.json().get("sha") if r.status_code == 200 else None

        # Кодуємо файл у Base64
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        data = {
            "message": f"update {file_path}",
            "content": encoded_content,
            "sha": sha
        }

        response = requests.put(url, headers=headers, json=data)
        if response.status_code in (200, 201):
            print(f"✅ {file_path} успішно оновлено у GitHub")
        else:
            print(f"❌ Не вдалося оновити {file_path} у GitHub: {response.text}")
    except Exception as e:
        print(f"❌ Помилка при збереженні {file_path} в GitHub: {e}")

def load_file_from_github(file_path):
    """
    Завантажує конкретний JSON файл з GitHub
    """
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPO", "Polilen/tgbot").strip()
    
    if not token:
        return None
    
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            content = response.json()
            decoded = base64.b64decode(content["content"]).decode("utf-8")
            print(f"✅ {file_path} завантажено з GitHub")
            return json.loads(decoded)
        else:
            return None
    except Exception as e:
        print(f"❌ Помилка при завантаженні {file_path} з GitHub: {e}")
        return None

# --- Система рівнів ---
LEVELS = [
    (0, "Знайомі"),
    (10, "Хороші друзі"),
    (25, "Близькі друзі"),
    (45, "Вірні друзі"),
    (70, "Справжні друзі"),
    (100, "Кращі друзі"),
    (140, "Друзі назавжди"),
    (185, "Нерозлучні"),
    (235, "Дружна сім'я"),
    (300, "Легендарні друзі")
]

def get_level_and_name(xp):
    level = 0
    next_xp = 0
    name = "Знайомі"
    for i, (xp_threshold, lvl_name) in enumerate(LEVELS):
        if xp >= xp_threshold:
            level = i + 1
            name = lvl_name
            next_xp = LEVELS[i + 1][0] - xp if i + 1 < len(LEVELS) else 0
        else:
            break
    return level, next_xp, name

# --- Безпечне завантаження JSON ---
def safe_load_json(path, default=None):
    if default is None:
        default = {}
    
    # Спочатку пробуємо завантажити з GitHub
    github_data = load_file_from_github(path)
    if github_data is not None:
        return github_data
    
    # Якщо GitHub недоступний, працюємо з локальним файлом
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        return default

friends = safe_load_json(friends_file)
known_users = safe_load_json(known_users_file)

def save_friends():
    with friends_lock:
        with open(friends_file, "w", encoding="utf-8") as f:
            json.dump(friends, f, ensure_ascii=False, indent=2)
        save_file_to_github(friends_file)

def save_known_users():
    with users_lock:
        with open(known_users_file, "w", encoding="utf-8") as f:
            json.dump(known_users, f, ensure_ascii=False, indent=2)
        save_file_to_github(known_users_file)

KIEV_TZ = timezone(timedelta(hours=3))

def parse_datetime(dt_str):
    try:
        return datetime.fromisoformat(dt_str).astimezone(KIEV_TZ)
    except:
        return None

def format_duration(delta):
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    parts = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} год.")
    if minutes > 0:
        parts.append(f"{minutes} хв.")
    return ", ".join(parts) if parts else "менше хвилини"

def find_user(username_fragment):
    username_fragment = username_fragment.lower()
    if username_fragment in known_users:
        return username_fragment
    for uname in known_users.keys():
        if uname.startswith(username_fragment):
            return uname
    return None

async def check_level_up(username, friend_username, old_xp, new_xp, context, chat_id):
    old_level, _, old_level_name = get_level_and_name(old_xp)
    new_level, _, new_level_name = get_level_and_name(new_xp)

    if new_level > old_level:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⬆️ Рівень дружби між @{username} і @{friend_username} підвищено! "
                 f"Тепер рівень {new_level} — «{new_level_name}»"
        )


async def add_friend(proposer, target_username, context=None, chat_id=None):
    now_iso = datetime.now(KIEV_TZ).isoformat()
    friends.setdefault(proposer, {})[target_username] = {"since": now_iso, "xp": 0}
    friends.setdefault(target_username, {})[proposer] = {"since": now_iso, "xp": 0}
    save_friends()
    if context and chat_id:
        await context.bot.send_message(chat_id=chat_id, text=f"🫶 @{proposer} і @{target_username} тепер друзі!")

# --- Новый класс для hug / бream ---
class ActionHandler:
    def __init__(self, friends_data, users_data):
        self.friends = friends_data
        self.users = users_data

    async def perform_action(self, update, context, action_type="hug"):
        user = update.effective_user
        sender_username = user.username.lower() if user.username else None
        if not sender_username:
            await update.message.reply_text("У тебе немає username.")
            return

        target_username = None
        text_lower = update.message.text.strip().lower()
        
        # Перевіряємо чи є слово "всіх" (для hug) або "всім" (для bream)
        if "всіх" in text_lower or ("всім" in text_lower and action_type == "bream"):
            # Обіймаємо/даємо ляща ВСІМ друзям
            if sender_username in self.friends and self.friends[sender_username]:
                targets = list(self.friends[sender_username].keys())
            else:
                await update.message.reply_text("В тебе ще немає друзів 😅")
                return
        else:
            # Шукаємо конкретну людину через reply або @username
            
            # 1. Перевіряємо reply
            if update.message.reply_to_message:
                target_user = update.message.reply_to_message.from_user
                target_username = target_user.username.lower() if target_user.username else None
                
                if not target_username:
                    await update.message.reply_text("У цього користувача немає username 😅")
                    return
                
                if target_username not in self.friends.get(sender_username, {}):
                    action_text = "обійняти" if action_type == "hug" else "дати йому ляща"
                    await update.message.reply_text(f"@{target_username} не є твоїм другом 😅 Ти не можеш його {action_text}.")
                    return
            
            # 2. Якщо немає reply — шукаємо @username
            if not target_username:
                words = update.message.text.strip().split()
                username_candidates = [w.lstrip("@").lower() for w in words if w.startswith("@")]
                
                if username_candidates:
                    candidate = username_candidates[0]
                    found_user = None
                    
                    if candidate in self.friends.get(sender_username, {}):
                        found_user = candidate
                    else:
                        for friend in self.friends.get(sender_username, {}):
                            if friend.startswith(candidate):
                                found_user = friend
                                break
                    
                    if found_user:
                        target_username = found_user
                    else:
                        await update.message.reply_text(f"Користувача '{candidate}' не знайдено серед твоїх друзів 😅")
                        return
            
            # 3. Якщо нічого не вказано — помилка
            if not target_username:
                if action_type == "hug":
                    action_text = "обійняти"
                    suffix = "всіх' щоб обійняти всіх друзів"
                else:
                    action_text = "дати ляща"
                    suffix = "всім' щоб дати ляща всім друзям"
                
                await update.message.reply_text(
                    f"Вкажи кого хочеш {action_text}:\n"
                    f"• Через @username\n"
                    f"• Або напиши '{suffix}"
                )
                return
            
            targets = [target_username]

        sender_data = self.users.get(sender_username, {})
        sender_name = sender_data.get("name") or user.first_name or f"@{user.username}"
        sender_gender = sender_data.get("gender")

        for friend_username in targets:
            friend_data = self.users.get(friend_username, {})
            friend_name = friend_data.get("name") or f"@{friend_username}"
            friend_gender = friend_data.get("gender")

            if action_type == "hug":
                if sender_username in self.friends and friend_username in self.friends[sender_username]:
                    old_xp = self.friends[sender_username][friend_username].get("xp", 0)
                    self.friends[sender_username][friend_username]["xp"] += 2
                    self.friends[friend_username][sender_username]["xp"] += 2
                    save_friends()
                    new_xp = self.friends[sender_username][friend_username]["xp"]
                    await check_level_up(sender_username, friend_username, old_xp, new_xp, context, update.effective_chat.id)

            folder = self.choose_folder(sender_gender, friend_gender, action_type)
            images = [f for f in os.listdir(folder) if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
            if not images:
                continue
            image_path = os.path.join(folder, random.choice(images))
            action_text = "обійняв(ла)" if action_type=="hug" else "дав(ла) ляща"
            text = f"[{friend_name}](tg://user?id={friend_data.get('id')})\n" \
                f"🤗 • [{sender_name}](tg://user?id={sender_data.get('id')}) {action_text} {friend_name} 🫶"

            with open(image_path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=text,
                    parse_mode="Markdown",
                    reply_to_message_id=update.message.message_id
                )
    
    async def remove_friend(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        sender_username = user.username.lower() if user.username else None
        if not sender_username:
            await update.message.reply_text("У тебе немає username.")
            return

        text_parts = update.message.text.strip().split(maxsplit=2)
        if len(text_parts) < 2:
            await update.message.reply_text("Вкажіть, кого хочете видалити з друзів 😅")
            return
        raw_target = text_parts[-1].lstrip("@").lower()
        target_username = find_user(raw_target)

        if not target_username:
            await update.message.reply_text(f"Користувача '{raw_target}' не знайдено.")
            return

        if target_username not in self.friends.get(sender_username, {}):
            await update.message.reply_text(f"@{target_username} не є вашим другом 😅")
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    "Так, перестати дружити 😢",
                    callback_data=f"unfriend_yes|{sender_username}|{target_username}"
                ),
                InlineKeyboardButton("Ні, залишити дружбу 😊", callback_data="unfriend_no")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Ви впевнені, що хочете перестати дружити з @{target_username}? 😢",
            reply_markup=reply_markup
        )

    async def unfriend_callback(self, update, context):
        query = update.callback_query
        await query.answer()
        data = query.data

        if data == "unfriend_no":
            await query.edit_message_text("Дружба залишилася 😊")
            return

        if data.startswith("unfriend_yes"):
            _, sender_username, target_username = data.split("|")

            # Удаляем дружбу с обеих сторон
            friends.get(sender_username, {}).pop(target_username, None)
            friends.get(target_username, {}).pop(sender_username, None)
            save_friends()

            await query.edit_message_text(f"Ви перестали дружити з @{target_username} 😢")

    def choose_folder(self, sender_gender, friend_gender, action_type):
        if action_type == "hug":
            if sender_gender=="male" and friend_gender=="male":
                return "friendsboys"
            elif sender_gender=="female" and friend_gender=="female":
                return "friendsgirls"
            else:
                return "friends"
        elif action_type == "bream":
            if sender_gender=="female" and friend_gender=="male":
                return "breamfromGirltoBoy"
            elif sender_gender=="female" and friend_gender=="female":
                return "breamfromGirltoGirl"
            elif sender_gender=="male" and friend_gender=="female":
                return "breamfromBoytoGirl"
            elif sender_gender=="male" and friend_gender=="male":
                return "breamfromBoytoBoy"


# --- Класс для трат монет и XP пар ---
class SpendCoins:
    def __init__(self, users_data, friends_data):
        self.users = users_data
        self.friends = friends_data  # словарь дружбы

    async def handle_action(self, text, update, context):
        username = update.effective_user.username.lower() if update.effective_user.username else None
        if not username:
            await update.message.reply_text("У тебе немає username.")
            return True

        user_data = self.users.get(username)
        if not user_data:
            return False

        # --- Подарувати білу шоколадку другу ---
        if text.startswith("подарити білу шоколадку") or text.startswith("подарувати білу шоколадку"):
            # Определяем получателя
            target_username = None
            if update.message.reply_to_message:
                target_user = update.message.reply_to_message.from_user
                target_username = target_user.username.lower() if target_user.username else None
            else:
                parts = update.message.text.strip().split(maxsplit=3)
                if len(parts) == 4:
                    target_username = parts[3].lstrip("@").lower()

            if not target_username:
                await update.message.reply_text("Не вказано користувача, якому подарувати шоколадку.")
                return True

            if target_username not in self.users:
                await update.message.reply_text("Користувач не знайдений у системі.")
                return True

            if username == target_username:
                await update.message.reply_text("Неможливо подарувати шоколадку самому собі 😅")
                return True

            cost = 5
            if user_data.get("coins", 0) < cost:
                await update.message.reply_text(f"У тебе недостатньо монет для подарунка ({cost} монет потрібно).")
                return True

            # Списываем монеты
            user_data["coins"] -= cost

            # --- Добавляем 5 XP паре в friends.json ---
            xp_gained = 5
            if username in self.friends and target_username in self.friends[username]:
                old_xp = self.friends[username][target_username].get("xp", 0)
                self.friends[username][target_username]["xp"] += xp_gained
                self.friends[target_username][username]["xp"] += xp_gained
                save_friends()
                new_xp = self.friends[username][target_username]["xp"]
                await check_level_up(username, target_username, old_xp, new_xp, context, update.effective_chat.id)
            save_known_users()

            await update.message.reply_text(
                f"🍫 @{username} подарував(ла) білу шоколадку @{target_username}!\n"
                f"⭐ XP дружби +{xp_gained}\n"
                f"💰 У тебе залишилось: {user_data['coins']} монет."
            )
            return True

        return False


# --- Создаем экземпляры ---
action_handler = ActionHandler(friends, known_users)
spend_coins_handler = SpendCoins(known_users, friends)

# --- Функции команд ---
async def hug(update, context):
    user = update.effective_user
    username = user.username.lower() if user.username else None
    if not username:
        await update.message.reply_text("У тебе немає username.")
        return
    # Вызываем perform_action без target_username, чтобы бот сам определял всех друзей
    await action_handler.perform_action(update, context, action_type="hug")

async def give_bream(update, context):
    await action_handler.perform_action(update, context, action_type="bream")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username.lower() if user and user.username else None
    text = update.message.text.strip().lower() if update.message else ""
    chat_id = update.effective_chat.id

    if not username:
        await update.message.reply_text("У тебе немає username.")
        return

    # Инициализация пользователя
    user_data = known_users.setdefault(username, {
        "id": user.id,
        "gender": None,
        "name": user.first_name,
        "coins": 0,
        "last_salary": None
    })

    # --- Проверка трат монет ---
    handled = await spend_coins_handler.handle_action(text, update, context)
    if handled:
        return

    # --- Половые команды ---
    if text.startswith("стать чоловіча"):
        known_users[username]["gender"] = "male"
        save_known_users()
        await update.message.reply_text("Стать встановлена як Чоловіча ♂.")
        return
    elif text.startswith("стать жіноча"):
        known_users[username]["gender"] = "female"
        save_known_users()
        await update.message.reply_text("Стать встановлена як Жіноча ♀.")
        return

 # --- Дружба ---
# Пропозиція дружби
    if text.startswith("др пропозиція"):
        words = text.split()
        if len(words) < 3:
            await update.message.reply_text("Формат: др пропозиція @username")
            return
        
        proposer = username
        target_raw = words[-1].lstrip("@").lower()
        target_username = find_user(target_raw)
        
        if not target_username:
            await update.message.reply_text(f"Користувача '{target_raw}' не знайдено.")
            return
        
        if target_username == proposer:
            await update.message.reply_text("Неможливо дружити з самим собою!")
            return
        
        if target_username in friends.get(proposer, {}):
            await update.message.reply_text(f"@{proposer} і @{target_username} вже друзі! 🫶")
            return
        
        # Перевіряємо стать пропонуючого
        if known_users.get(proposer, {}).get("gender") is None:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🟦 Чоловіча", callback_data=f"set_gender|{proposer}|male"),
                InlineKeyboardButton("🩷 Жіноча", callback_data=f"set_gender|{proposer}|female")
            ]])
            await update.message.reply_text(f"@{proposer}, спершу обери свою стать:", reply_markup=keyboard)
            return
        
        # Перевіряємо стать цілі (НОВИЙ БЛОК)
        if known_users.get(target_username, {}).get("gender") is None:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🟦 Чоловіча", callback_data=f"set_gender_and_propose|{target_username}|male|{proposer}"),
                InlineKeyboardButton("🩷 Жіноча", callback_data=f"set_gender_and_propose|{target_username}|female|{proposer}")
            ]])
            await update.message.reply_text(
                f"@{target_username}, спершу обери свою стать, щоб @{proposer} міг запропонувати тобі дружбу:",
                reply_markup=keyboard
            )
            return
        
        # Якщо обидва вказали стать — надсилаємо пропозицію
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Так 🫶", callback_data=f"accept|{proposer}|{target_username}"),
            InlineKeyboardButton("Ні 🙃", callback_data=f"reject|{proposer}|{target_username}")
        ]])
        await update.message.reply_text(
            f"@{target_username}, @{proposer} хоче стати твоїм другом! Приймаєш?",
            reply_markup=keyboard
        )
        return

    if text.startswith("дати ляща"):
        await give_bream(update, context)
        return

    if text.startswith("др обійняти"):
        await hug(update, context)
        return

    if text.startswith("перестати дружити"):
        words = text.split()
        if len(words) < 3:
            await update.message.reply_text("Вкажіть користувача, якого хочете видалити з друзів 😅")
            return
        raw_target = words[-1].lstrip("@").lower()
        target_username = find_user(raw_target)
        if not target_username:
            await update.message.reply_text(f"Користувача '{raw_target}' не знайдено.")
            return
        if target_username not in friends.get(username, {}):
            await update.message.reply_text(f"@{target_username} не є вашим другом 😅")
            return
        await action_handler.remove_friend(update, context)

    # --- Новый блок для зарплаты и баланса ---
    if text == "зп":
        now = datetime.now(KIEV_TZ)
        last_time_str = user_data.get("last_salary")
        if last_time_str:
            last_time = parse_datetime(last_time_str)
            if last_time and now < last_time + timedelta(hours=4):
                remaining = (last_time + timedelta(hours=4)) - now
                await update.message.reply_text(
                    f"💰 Зачекай, поки закінчиться кулдаун: {format_duration(remaining)}"
                )
                return
        coins_earned = random.randint(1, 30)
        user_data["coins"] = user_data.get("coins", 0) + coins_earned
        user_data["last_salary"] = now.isoformat()
        save_known_users()
        await update.message.reply_text(
            f"💵 @{username} отримав(ла) {coins_earned} монет! Зараз у тебе: {user_data['coins']} монет."
        )
        return

    if text == "баланс":
        coins = user_data.get("coins", 0)
        await update.message.reply_text(f"💰 @{username}, твій баланс: {coins} монет.")
        return

# --- Остальные функции и команды ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    if not data:
        return
    action = data[0]

    # Обробка видалення всіх друзів
    if action == "unfriend_all":
        sender_username = data[1]
        for friend in list(friends.get(sender_username, {})):
            friends[friend].pop(sender_username, None)
        friends[sender_username] = {}
        save_friends()
        await query.edit_message_text("Ви більше ні з ким не дружите 💔")
        return

    # Обробка відміни видалення
    if action == "unfriend_no":
        await query.edit_message_text("Дружба залишилася 😊")
        return

    # Обробка видалення конкретного друга
    if action == "unfriend_yes":
        if len(data) < 3:
            await query.edit_message_text("Помилка: невірний формат даних")
            return
        sender_username = data[1]
        target_username = data[2]
        
        if sender_username in friends:
            friends[sender_username].pop(target_username, None)
        if target_username in friends:
            friends[target_username].pop(sender_username, None)
        save_friends()
        
        await query.edit_message_text(f"Ви перестали дружити з @{target_username} 😢")
        return

    # Обробка встановлення статі (звичайний випадок)
    if action == "set_gender":
        usern, gender = data[1], data[2]
        known_users[usern]["gender"] = gender
        save_known_users()
        await query.edit_message_text(f"Стать встановлена як '{gender}'. Тепер можна пропонувати дружбу.")
        return

    # НОВИЙ БЛОК: Встановлення статі + автоматична пропозиція дружби
    if action == "set_gender_and_propose":
        target_username = data[1]
        gender = data[2]
        proposer = data[3]
        
        # Встановлюємо стать
        known_users[target_username]["gender"] = gender
        save_known_users()
        
        # Надсилаємо пропозицію дружби
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Так 🫶", callback_data=f"accept|{proposer}|{target_username}"),
            InlineKeyboardButton("Ні 🙃", callback_data=f"reject|{proposer}|{target_username}")
        ]])
        
        await query.edit_message_text(
            f"Стать встановлена як '{gender}'.\n\n"
            f"@{target_username}, @{proposer} хоче стати твоїм другом! Приймаєш?",
            reply_markup=keyboard
        )
        return

    # Обробка прийняття/відхилення дружби
    if len(data) != 3:
        return

    action, proposer, proposee = data
    user = query.from_user
    user_username = user.username.lower() if user.username else None

    if user_username != proposee:
        await query.answer("Ти не можеш приймати цю пропозицію.", show_alert=True)
        return

    if action == "accept":
        await add_friend(proposer, proposee, context, query.message.chat_id)
        await query.edit_message_text(f"🫶 Дружба підтверджена!")
    elif action == "reject":
        await query.edit_message_text(f"🙃 @{proposee} відмовився(лась) дружити з @{proposer}.")

async def friends_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(KIEV_TZ)
    lines = []
    shown_pairs = set()

    for user, friends_dict in friends.items():
        for friend, data in friends_dict.items():
            pair = tuple(sorted([user, friend]))
            if pair in shown_pairs:
                continue
            shown_pairs.add(pair)

            since_dt = parse_datetime(data.get("since"))
            duration = format_duration(now - since_dt) if since_dt else "невідомо"
            xp = data.get("xp", 0)
            level, _, level_name = get_level_and_name(xp)
            # Выбираем эмодзи по уровню отношений
            if level_name == "Знайомі":
                emoji = "🌱"
            elif level_name == "Хороші друзі":
                emoji = "🌸"
            elif level_name == "Близькі друзі":
                emoji = "💞"
            elif level_name == "Кращі друзі":
                emoji = "🔥"
            elif level_name == "Душевні друзі":
                emoji = "🌈"
            elif level_name == "Нерозлучні":
                emoji = "💍"
            else:
                emoji = "⭐"

            lines.append(
                f"{emoji} @{pair[0]} 🤝 @{pair[1]}\n"
                f" 📅 {duration}\n"
                f" ✨ XP: {xp} | 🧩 Рівень: {level} — «{level_name}»\n"
            )


    if lines:
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text("Друзів поки що немає.")


async def my_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username.lower() if user.username else None
    if not username:
        await update.message.reply_text("У тебе немає username.")
        return
    user_data = known_users.get(username, {})
    user_name = user_data.get("name") or user.first_name or f"@{user.username}"
    gender = user_data.get("gender")
    gender_text = "Чоловічий ♂" if gender=="male" else "Жіночий ♀" if gender=="female" else "Не вказано ⚧"
    text_lines = [f"👤 [{user_name}](tg://user?id={user_data.get('id')})", f"⚥ Стать: {gender_text}"]

    if username in friends and friends[username]:
        for friend_username, data in friends[username].items():
            friend_data = known_users.get(friend_username,{})
            friend_name = friend_data.get("name") or f"@{friend_username}"
            since_dt = parse_datetime(data.get("since"))
            duration = format_duration(datetime.now(KIEV_TZ) - since_dt) if since_dt else "невідомо"
            friend_xp = data.get("xp",0)
            friend_level, _, friend_level_name = get_level_and_name(friend_xp)
            text_lines.append(
                f"🫶 Дружить з {friend_name}\n"
                f"📅 З {since_dt.strftime('%d.%m.%Y %H:%M') if since_dt else 'невідомо'}\n"
                f"⏳ Разом вже: {duration}\n"
                f"⭐ Рівень: {friend_level} — «{friend_level_name}» (XP: {friend_xp})"
            )
    else:
        text_lines.append("🫶 Поки що без друзів")
    await update.message.reply_text("\n\n".join(text_lines), parse_mode="Markdown")

async def unfriend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username.lower() if user and user.username else None
    if not username:
        await update.message.reply_text("У вас немає username.")
        return

    # Проверяем, есть ли друзья
    if username not in friends or not friends[username]:
        await update.message.reply_text("У вас немає друзів.")
        return

    # Создаем инлайн-кнопки
    keyboard = [
        [
            InlineKeyboardButton("Так, розірвати всі дружби 💔", callback_data=f"unfriend_all|{username}"),
            InlineKeyboardButton("Ні, залишити друзів 😊", callback_data="unfriend_no")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Ви впевнені, що хочете розірвати всі дружби? 💔",
        reply_markup=reply_markup
    )

async def updates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔄 <b>Останнє оновлення бота</b>\n\n"
        "📅 <b>Дата:</b> 17.10.2025\n\n"
        "✨ <b>Що нового:</b>\n\n"
        "1️⃣ <b>Виправлено помилку</b> з командою 'перестати дружити @username' — тепер працює коректно!\n\n"
        "2️⃣ <b>Покращено систему пропозиції дружби:</b>\n"
        "   • Тепер якщо у користувача, якому пропонують дружбу, не вказана стать — бот спочатку попросить вказати стать\n"
        "   • Після вибору статі пропозиція дружби надсилається автоматично\n\n"
        "3️⃣ <b>Додано команду /updates</b> — тепер ти можеш переглянути всі останні оновлення!\n\n"
        "📝 Використовуй /help щоб побачити всі команди!"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def zp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text(update, context)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 <b>Команди бота дружби:</b>\n\n"
        "📜 <b>Команди:</b>\n"
        "/friends — Список всіх друзів та як довго дружать\n"
        "/my — Показати твою картку (ім'я, стать, друзі)\n"
        "/unfriend — Розірвати всі дружби\n"
        "/updates — Показати останні оновлення бота\n"
        "/help — Показати цю довідку\n\n"
        "💬 <b>Текстові команди:</b>\n"
        "др пропозиція @username — Запропонувати дружбу\n"
        "др обійняти всіх— Обійняти усіх друзів або конкретного @username)\n"
        "др обійняти @username — Обійняти конкретного друга\n"
        "дати ляща всім — Дати ляща усім друзям або конкретному через @username\n"
        "дати ляща @username — Дати ляща конкретному другу\n"
        "перестати дружити @username — Видалити конкретного друга з дружби\n"
        "стать чоловіча / стать жіноча — Встановити або поміняти стать\n"
        "зп — Отримати зарплату (монети)\n"
        "баланс — Показати баланс монет\n"
        "🎁 <b>Подарунки:</b>\n"
        "подарити білу шоколадку @username — Подарувати другу шоколадку (+5 XP для дружби)"
    )
    await update.message.reply_text(text, parse_mode="HTML")

# --- Запуск бота ---
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
app.add_handler(CommandHandler("friends", friends_list))
app.add_handler(CommandHandler("my", my_card))
app.add_handler(CommandHandler("unfriend", unfriend))
app.add_handler(CommandHandler("hug", hug))
app.add_handler(CommandHandler("give_bream", give_bream))
app.add_handler(CommandHandler("zp", zp))
app.add_handler(CommandHandler("balance", balance))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("updates", updates_command))
app.add_handler(CallbackQueryHandler(button_handler))

if __name__ == "__main__":
    print("Бот запущено ✅")
    app.run_polling()