import asyncio
import io
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from PIL import Image, ImageDraw, ImageFont

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬТЕ_НОВЫЙ_ТОКЕН_СЮДА")

MODULES_LIST = [
    "Телепорт", "Импульс", "Узы", "Дельта-ракета", "Омега-ракета",
    "Бомба замедленного действия", "ЭМИ", "Ингибитор", "Искажение",
    "Восстановление", "Щит", "Лазер", "Ракета", "Дрон"
]

try:
    FONT = ImageFont.truetype("arial.ttf", 20)
    FONT_BOLD = ImageFont.truetype("arialbd.ttf", 26)
except IOError:
    FONT = ImageFont.load_default()
    FONT_BOLD = ImageFont.load_default()


# --- СОСТОЯНИЯ ---
class Form(StatesGroup):
    name = State()
    inventory = State()
    needed = State()


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище данных пользователей: {user_id: {"name":..., "inventory":{...}, "needed":[...]}}
users_data: dict[int, dict] = {}


# --- КЛАВИАТУРЫ ---

def inventory_keyboard(inventory: dict):
    kb = InlineKeyboardBuilder()
    for mod in MODULES_LIST:
        qty = inventory.get(mod, 0)
        mark = f"✅ {mod} ×{qty}" if qty > 0 else mod
        kb.button(text=mark, callback_data=f"inv|{mod}")
    kb.button(text="➡️ Далее (выбрать нужные)", callback_data="inv_done")
    kb.adjust(2)
    return kb.as_markup()


def needed_keyboard(needed: list):
    kb = InlineKeyboardBuilder()
    for mod in MODULES_LIST:
        mark = f"✅ {mod}" if mod in needed else mod
        kb.button(text=mark, callback_data=f"need|{mod}")
    kb.button(text="🏁 Готово — сформировать картинку", callback_data="need_done")
    kb.adjust(2)
    return kb.as_markup()


def edit_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Редактировать", callback_data="edit")
    kb.button(text="✅ Принято, по готовности", callback_data="confirm")
    kb.adjust(2)
    return kb.as_markup()


# --- ХЕНДЛЕРЫ ---

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет! Как тебя зовут? (введи имя)")
    await state.set_state(Form.name)


@dp.message(Form.name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()[:32]
    users_data[message.from_user.id] = {
        "name": name,
        "inventory": {},
        "needed": [],
    }
    await state.update_data(name=name)
    await message.answer(
        f"Отлично, {name}! Теперь выбери модули, которые у тебя **есть**, "
        f"и укажи количество кнопками ниже. По завершении — «Далее».",
        reply_markup=inventory_keyboard({}),
        parse_mode="Markdown",
    )
    await state.set_state(Form.inventory)


@dp.callback_query(F.data.startswith("inv|"), Form.inventory)
async def inv_toggle(call: CallbackQuery):
    mod = call.data.split("|", 1)[1]
    inv = users_data[call.from_user.id]["inventory"]
    inv[mod] = inv.get(mod, 0) + 1
    await call.message.edit_reply_markup(reply_markup=inventory_keyboard(inv))
    await call.answer(f"{mod}: {inv[mod]}")


@dp.callback_query(F.data == "inv_done", Form.inventory)
async def inv_done(call: CallbackQuery, state: FSMContext):
    data = users_data[call.from_user.id]
    text = f"👤 {data['name']}\n\n📦 **Твои модули:**\n"
    if data["inventory"]:
        for mod, qty in data["inventory"].items():
            text += f"• {mod} ×{qty}\n"
    else:
        text += "_пока пусто_\n"
    text += "\nЕсли всё верно — «Принято», иначе — «Редактировать»."
    await call.message.edit_text(text, reply_markup=edit_keyboard(), parse_mode="Markdown")


@dp.callback_query(F.data == "edit", Form.inventory)
async def inv_edit(call: CallbackQuery):
    inv = users_data[call.from_user.id]["inventory"]
    await call.message.edit_text(
        "Редактирование: нажми на модуль, чтобы **+1**, или сбрось количество.",
        reply_markup=inventory_keyboard(inv),
    )
    await call.answer()


@dp.callback_query(F.data == "confirm", Form.inventory)
async def inv_confirm(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "Теперь выбери модули, которые тебе **нужны** (для обмена). "
        "Когда закончишь — «Готово».",
        reply_markup=needed_keyboard([]),
    )
    await state.set_state(Form.needed)
    await call.answer()


@dp.callback_query(F.data.startswith("need|"), Form.needed)
async def need_toggle(call: CallbackQuery):
    mod = call.data.split("|", 1)[1]
    needed = users_data[call.from_user.id]["needed"]
    if mod in needed:
        needed.remove(mod)
    else:
        needed.append(mod)
    await call.message.edit_reply_markup(reply_markup=needed_keyboard(needed))
    await call.answer()


@dp.callback_query(F.data == "need_done", Form.needed)
async def need_done(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    data = users_data.get(user_id)
    if not data:
        await call.answer("Данные не найдены, начни заново /start", show_alert=True)
        return

    await call.message.edit_text("⏳ Формирую картинку…")
    img_bytes = generate_image(users_data)
    photo = BufferedInputFile(img_bytes, filename="trade.png")

    # Рассылка всем участникам
    for uid in users_data.keys():
        try:
            await bot.send_photo(uid, photo, caption="📊 Таблица обмена модулями готова!")
        except Exception:
            pass

    users_data[user_id]["needed"] = data["needed"]
    await state.clear()
    await call.answer()


# --- ГЕНЕРАЦИЯ КАРТИНКИ ---

def generate_image(users: dict[int, dict]) -> bytes:
    """Рисует картинку с таблицей участников, их модулями и стрелками обмена."""
    width = 1200
    row_h = 26
    header_h = 60
    padding = 20

    # Расчёт высоты
    blocks = []
    total_h = header_h
    for uid, d in users.items():
        lines = 2 + len(d["inventory"]) + len(d["needed"])
        h = padding + lines * row_h + padding
        blocks.append((uid, d, h, total_h))
        total_h += h

    height = max(total_h + 80, 400)
    img = Image.new("RGB", (width, height), (24, 26, 32))
    draw = ImageDraw.Draw(img)

    draw.text((width // 2 - 120, 15), "HADES' STAR — Обмен модулями",
              fill=(255, 215, 0), font=FONT_BOLD)

    # Сборка нужд для стрелок
    needs_map = {}
    for uid, d in users.items():
        for mod in d["needed"]:
            needs_map.setdefault(mod, []).append((uid, d["name"]))

    y = header_h
    positions = {}
    for uid, d, h, top in blocks:
        x = padding
        draw.rectangle([x, y, width - padding, y + h], outline=(90, 90, 120), width=2)
        draw.text((x + 10, y + 5), f"👤 {d['name']}", fill=(120, 220, 255), font=FONT_BOLD)
        yy = y + 5 + 30
        draw.text((x + 20, yy), "📦 Есть:", fill=(180, 255, 180), font=FONT)
        yy += row_h
        if d["inventory"]:
            for mod, qty in d["inventory"].items():
                draw.text((x + 40, yy), f"• {mod} ×{qty}", fill=(220, 220, 220), font=FONT)
                yy += row_h
        else:
            draw.text((x + 40, yy), "—", fill=(150, 150, 150), font=FONT)
            yy += row_h
        draw.text((x + 20, yy), "🎯 Нужно:", fill=(255, 220, 150), font=FONT)
        yy += row_h
        if d["needed"]:
            for mod in d["needed"]:
                draw.text((x + 40, yy), f"• {mod}", fill=(220, 220, 220), font=FONT)
                yy += row_h
        else:
            draw.text((x + 40, yy), "—", fill=(150, 150, 150), font=FONT)
            yy += row_h

        positions[uid] = (y, y + h)
        y += h

    # Стрелки обмена (если участников > 2)
    if len(users) > 2:
        for mod, wanters in needs_map.items():
            for w_uid, w_name in wanters:
                for g_uid, gd in users.items():
                    if g_uid == w_uid:
                        continue
                    if mod in gd["inventory"] and gd["inventory"][mod] > 0:
                        y1 = positions[g_uid][1] - 10
                        y2 = positions[w_uid][0] + 10
                        x1 = width // 2
                        x2 = width // 2 + 60
                        draw.line([(x1, y1), (x2, y2)], fill=(255, 100, 100), width=3)
                        draw.text(((x1 + x2) // 2, (y1 + y2) // 2),
                                  mod[:12], fill=(255, 180, 180), font=FONT)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# --- ЗАПУСК ---

async def main():
    print("Бот запущен…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())