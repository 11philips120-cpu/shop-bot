import asyncio
import logging
import aiosqlite
import os
import aiohttp
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [375707434]
SHEETS_URL = "https://script.google.com/macros/s/AKfycbxbxQf3KzySaMp94IPLtuToXspYmOFo5UZQKFYr2qaewZZlcdoe7gllqbohnb_Fx2iOtQ/exec"
CASHIERS = [
    "Ліля",
    "Зінаїда",
    "Галина"
]
DB_NAME = "shop_reports.db"
# ===============================================

logging.basicConfig(level=logging.INFO)
router = Router()


class ReportForm(StatesGroup):
    surname = State()
    cash_in = State()          # Приход наличных
    card_in = State()          # Приход безнал
    cash_out = State()         # Товар от поставщика
    card_out = State()         # Расход безнал
    cash_start = State()       # Остаток нал на утро
    confirm = State()
    confirm_cancel = State()


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                surname TEXT,
                report_date TEXT,
                cash_in REAL,
                card_in REAL,
                cash_out REAL,
                card_out REAL,
                cash_start REAL,
                card_start REAL,
                cash_end REAL,
                card_end REAL,
                total_in REAL,
                total_out REAL,
                total_end REAL,
                user_id INTEGER,
                username TEXT,
                created_at TEXT
            )
        """)
        await db.commit()


async def save_report(data: dict, user_id: int, username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO reports (
                surname, report_date,
                cash_in, card_in, cash_out, card_out,
                cash_start, card_start,
                cash_end, card_end,
                total_in, total_out, total_end,
                user_id, username, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["surname"], data["date"],
            data["cash_in"], data["card_in"], data["cash_out"], data["card_out"],
            data["cash_start"], data["card_start"],
            data["cash_end"], data["card_end"],
            data["total_in"], data["total_out"], data["total_end"],
            user_id, username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        await db.commit()

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(SHEETS_URL, json=data, timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        logging.error(f"Не вдалося записати в Google Таблицю: {e}")


async def delete_last_report(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "DELETE FROM reports WHERE id = (SELECT id FROM reports WHERE user_id = ? ORDER BY id DESC LIMIT 1)",
            (user_id,)
        )
        await db.commit()

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(SHEETS_URL, json={"action": "delete_last"}, timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        logging.error(f"Не вдалося видалити рядок в Google Таблиці: {e}")


async def get_reports_by_date(date_str: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM reports WHERE report_date = ? ORDER BY id DESC", (date_str,))
        return await cursor.fetchall()


async def get_last_reports(limit: int = 50):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,))
        return await cursor.fetchall()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отчет"), KeyboardButton(text="Исправить")]],
        resize_keyboard=True
    )


def cashiers_kb():
    buttons = [[KeyboardButton(text=name)] for name in CASHIERS]
    buttons.append([KeyboardButton(text="Скасувати")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)


def confirm_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Так"), KeyboardButton(text="Ні")],
            [KeyboardButton(text="Скасувати")]
        ],
        resize_keyboard=True, one_time_keyboard=True
    )


def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Скасувати")]],
        resize_keyboard=True
    )


def parse_number(text: str) -> float:
    return float(text.replace(",", ".").replace(" ", ""))


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Вітаю! Натисніть <b>Отчет</b>, щоб здати звіт.\n"
        "Якщо помилилися — натисніть <b>Исправить</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb()
    )


@router.message(Command("отчет"))
@router.message(F.text == "Отчет")
async def start_report(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ReportForm.surname)
    await message.answer("Виберіть себе зі списку:", reply_markup=cashiers_kb())


@router.message(Command("исправить"))
@router.message(F.text.in_({"Исправить", "Исправить отчет", "Виправити", "Удалить отчет"}))
async def edit_last_report(message: Message, state: FSMContext):
    await delete_last_report(message.from_user.id)
    await state.clear()
    await state.set_state(ReportForm.surname)
    await message.answer(
        "Останній звіт видалено.\nВиберіть себе зі списку і здайте звіт заново:",
        reply_markup=cashiers_kb()
    )


@router.message(F.text.in_({"Скасувати", "скасувати", "Отмена", "отмена"}))
async def cancel_any(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None or current_state == ReportForm.confirm_cancel.state:
        return
    await state.update_data(_previous_state=current_state)
    await state.set_state(ReportForm.confirm_cancel)
    await message.answer("Ви дійсно хочете скасувати звіт?", reply_markup=confirm_kb())


@router.message(ReportForm.confirm_cancel, F.text.in_({"Так", "так", "Да", "да"}))
async def confirm_cancel_yes(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Звіт скасовано.", reply_markup=main_kb())


@router.message(ReportForm.confirm_cancel, F.text.in_({"Ні", "ні", "Нет", "нет"}))
async def confirm_cancel_no(message: Message, state: FSMContext):
    data = await state.get_data()
    previous_state = data.get("_previous_state")
    await state.set_state(previous_state)
    await message.answer("Добре, продовжуємо заповнення звіту.", reply_markup=cancel_kb())


@router.message(ReportForm.surname)
async def process_surname(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    await state.update_data(surname=message.text.strip())
    await state.set_state(ReportForm.cash_in)
    await message.answer(
        "1. <b>Приход наличных</b> (готівка за день):",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_kb()
    )


@router.message(ReportForm.cash_in)
async def process_cash_in(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = parse_number(message.text)
        await state.update_data(cash_in=value)
        await state.set_state(ReportForm.card_in)
        await message.answer(
            "2. <b>Приход безнал</b> (термінал за день):",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_kb()
        )
    except Exception:
        await message.answer("Введите только число")


@router.message(ReportForm.card_in)
async def process_card_in(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = parse_number(message.text)
        await state.update_data(card_in=value)
        await state.set_state(ReportForm.cash_out)
        await message.answer(
            "3. <b>Товар от поставщика</b>:",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_kb()
        )
    except Exception:
        await message.answer("Введите только число")


@router.message(ReportForm.cash_out)
async def process_cash_out(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = parse_number(message.text)
        await state.update_data(cash_out=value)
        await state.set_state(ReportForm.card_out)
        await message.answer(
            "4. <b>Расход безнал</b> (оплата з рахунку / карти):",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_kb()
        )
    except Exception:
        await message.answer("Введите только число")


@router.message(ReportForm.card_out)
async def process_card_out(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = parse_number(message.text)
        await state.update_data(card_out=value)
        await state.set_state(ReportForm.cash_start)
        await message.answer(
            "5. <b>Остаток наличных на утро</b>:",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_kb()
        )
    except Exception:
        await message.answer("Введите только число")


@router.message(ReportForm.cash_start)
async def process_cash_start(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = parse_number(message.text)
        await state.update_data(cash_start=value, card_start=0)

        data = await state.get_data()
        data["date"] = datetime.now().strftime("%d.%m")

        # ===== АЛГОРИТМ =====
        data["total_in"] = data["cash_in"] + data["card_in"]
        data["total_out"] = data["cash_out"] + data["card_out"]
        data["cash_end"] = data["cash_start"] + data["cash_in"] - data["cash_out"]
        data["card_end"] = data["card_in"] - data["card_out"]
        data["total_end"] = data["cash_end"] + data["card_end"]
        data["change"] = data["total_in"] - data["total_out"]
        await state.update_data(data)

        text = (
            f"Перевірте звіт:\n\n"
            f"<b>Касир:</b> {data['surname']}\n"
            f"<b>Дата:</b> {data['date']}\n\n"
            f"📥 <b>Приход</b>\n"
            f"Нал: <b>{data['cash_in']:.0f}</b>\n"
            f"Безнал: <b>{data['card_in']:.0f}</b>\n"
            f"Всього: <b>{data['total_in']:.0f}</b>\n\n"
            f"📤 <b>Расход</b>\n"
            f"Товар от поставщика: <b>{data['cash_out']:.0f}</b>\n"
            f"Расход безнал: <b>{data['card_out']:.0f}</b>\n"
            f"Всього: <b>{data['total_out']:.0f}</b>\n\n"
            f"🌅 Остаток нал на утро: <b>{data['cash_start']:.0f}</b>\n\n"
            f"💰 <b>На кінець дня</b>\n"
            f"Нал: <b>{data['cash_end']:.0f}</b>\n"
            f"Безнал (за день): <b>{data['card_end']:.0f}</b>\n"
            f"Загалом: <b>{data['total_end']:.0f}</b>\n\n"
            f"Всё верно?"
        )
        await state.set_state(ReportForm.confirm)
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=confirm_kb())
    except Exception:
        await message.answer("Введите только число")


@router.message(ReportForm.confirm, F.text.in_({"Так", "так", "Да", "да"}))
async def process_confirm_yes(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await save_report(data, message.from_user.id, message.from_user.username or "")

    change_text = f"+{data['change']:.0f}" if data["change"] >= 0 else f"{data['change']:.0f}"

    await message.answer(
        f"✅ Отчёт збережено!\n"
        f"Касир: <b>{data['surname']}</b>\n"
        f"Загальний остаток: <b>{data['total_end']:.0f} грн</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb()
    )

    admin_text = (
        f"📥 <b>Новий звіт</b>\n\n"
        f"<b>Касир:</b> {data['surname']}\n"
        f"<b>Дата:</b> {data['date']}\n\n"
        f"📥 <b>Приход</b>\n"
        f"Нал: <b>{data['cash_in']:.0f} грн</b>\n"
        f"Безнал: <b>{data['card_in']:.0f} грн</b>\n"
        f"Всього приход: <b>{data['total_in']:.0f} грн</b>\n\n"
        f"📤 <b>Расход</b>\n"
        f"Товар от поставщика: <b>{data['cash_out']:.0f} грн</b>\n"
        f"Расход безнал: <b>{data['card_out']:.0f} грн</b>\n"
        f"Всього расход: <b>{data['total_out']:.0f} грн</b>\n\n"
        f"📈 Зміна за день: <b>{change_text} грн</b>\n\n"
        f"🌅 Остаток нал на утро: <b>{data['cash_start']:.0f} грн</b>\n\n"
        f"💰 <b>На кінець дня</b>\n"
        f"Нал: <b>{data['cash_end']:.0f} грн</b>\n"
        f"Безнал (за день): <b>{data['card_end']:.0f} грн</b>\n"
        f"<b>Загальний остаток: {data['total_end']:.0f} грн</b>"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"Не вдалося надіслати адміну {admin_id}: {e}")

    await state.clear()


@router.message(ReportForm.confirm, F.text.in_({"Ні", "ні", "Нет", "нет"}))
async def process_confirm_no(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Звіт скасовано.", reply_markup=main_kb())


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())


@router.message(Command("сегодня"))
async def cmd_today(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Немає доступу")
    today = datetime.now().strftime("%d.%m")
    reports = await get_reports_by_date(today) or await get_last_reports(5)
    if not reports:
        return await message.answer("Немає звітів")
    text = f"📅 Звіти:\n\n"
    for r in reports:
        total = r["total_end"] if "total_end" in r.keys() else r["total_in"]
        text += f"• <b>{r['surname']}</b> ({r['report_date']}) — {total:.0f} грн\n"
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("статистика"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Немає доступу")
    reports = await get_last_reports(50)
    if not reports:
        return await message.answer("Немає даних")
    total = 0
    for r in reports:
        total += r["total_in"] if "total_in" in r.keys() else 0
    await message.answer(
        f"📊 Всього звітів: {len(reports)}\nЗагальний приход: <b>{total:.0f} грн</b>",
        parse_mode=ParseMode.HTML
    )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Секрет BOT_TOKEN не знайдено")
    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    print("Бот запущений!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
