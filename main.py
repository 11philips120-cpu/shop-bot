import asyncio
import logging
import aiosqlite
import os
import aiohttp
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
    cash = State()
    card = State()
    supplier = State()
    igor = State()
    yesterday_cash = State()
    confirm = State()
    confirm_cancel = State()


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                surname TEXT,
                report_date TEXT,
                cash REAL,
                card REAL,
                supplier REAL,
                igor REAL,
                total REAL,
                yesterday_cash REAL,
                user_id INTEGER,
                username TEXT,
                created_at TEXT
            )
        """)
        await db.commit()


async def save_report(data: dict, user_id: int, username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO reports 
            (surname, report_date, cash, card, supplier, igor, total, yesterday_cash, user_id, username, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["surname"], data["date"], data["cash"], data["card"],
            data["supplier"], data["igor"], data["total"], data["yesterday_cash"],
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
        keyboard=[[KeyboardButton(text="Отчет")]],
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


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Вітаю! Натисніть кнопку <b>Отчет</b>, щоб здати звіт.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb()
    )


@router.message(Command("отчет"))
@router.message(F.text == "Отчет")
async def start_report(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ReportForm.surname)
    await message.answer(
        "Виберіть себе зі списку:",
        reply_markup=cashiers_kb()
    )


@router.message(Command("исправить"))
async def edit_last_report(message: Message, state: FSMContext):
    await delete_last_report(message.from_user.id)
    await state.clear()
    await state.set_state(ReportForm.surname)
    await message.answer(
        "Останній звіт видалено.\nВиберіть себе зі списку:",
        reply_markup=cashiers_kb()
    )


@router.message(F.text.in_({"Скасувати", "скасувати", "Отмена", "отмена"}))
async def cancel_any(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None or current_state == ReportForm.confirm_cancel:
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
    await state.set_state(ReportForm.cash)
    await message.answer(
        "2. Введите <b>наличные за день</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_kb()
    )


@router.message(ReportForm.cash)
async def process_cash(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = float(message.text.replace(",", ".").replace(" ", ""))
        await state.update_data(cash=value)
        await state.set_state(ReportForm.card)
        await message.answer("3. Введите <b>безналичные за день</b>:", parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
    except:
        await message.answer("Введите только число")


@router.message(ReportForm.card)
async def process_card(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = float(message.text.replace(",", ".").replace(" ", ""))
        await state.update_data(card=value)
        await state.set_state(ReportForm.supplier)
        await message.answer("4. Введите <b>Товар от поставщика</b>:", parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
    except:
        await message.answer("Введите только число")


@router.message(ReportForm.supplier)
async def process_supplier(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = float(message.text.replace(",", ".").replace(" ", ""))
        await state.update_data(supplier=value)
        await state.set_state(ReportForm.igor)
        await message.answer("5. Введите <b>Товар от Игоря</b>:", parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
    except:
        await message.answer("Введите только число")


@router.message(ReportForm.igor)
async def process_igor(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = float(message.text.replace(",", ".").replace(" ", ""))
        await state.update_data(igor=value)
        await state.set_state(ReportForm.yesterday_cash)
        await message.answer("6. Введите <b>Остаток на утро</b>:", parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
    except:
        await message.answer("Введите только число")


@router.message(ReportForm.yesterday_cash)
async def process_yesterday(message: Message, state: FSMContext):
    if message.text in ["Скасувати", "скасувати"]:
        return
    try:
        value = float(message.text.replace(",", ".").replace(" ", ""))
        await state.update_data(yesterday_cash=value)

        data = await state.get_data()
        data["date"] = datetime.now().strftime("%d.%m")
        # Приход = нал + безнал
        data["total"] = data["cash"] + data["card"]
        await state.update_data(data)

        text = (
            f"Перевірте звіт:\n\n"
            f"<b>Касир:</b> {data['surname']}\n"
            f"<b>Дата:</b> {data['date']}\n\n"
            f"Наличные: <b>{data['cash']:.0f}</b>\n"
            f"Безналичные: <b>{data['card']:.0f}</b>\n"
            f"Общая (Приход): <b>{data['total']:.0f}</b>\n\n"
            f"Товар от поставщика: <b>{data['supplier']:.0f}</b>\n"
            f"Товар от Игоря: <b>{data['igor']:.0f}</b>\n"
            f"Остаток на утро: <b>{data['yesterday_cash']:.0f}</b>\n\n"
            f"Всё верно?"
        )
        await state.set_state(ReportForm.confirm)
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=confirm_kb())
    except:
        await message.answer("Введите только число")


@router.message(ReportForm.confirm, F.text.in_({"Так", "так", "Да", "да"}))
async def process_confirm_yes(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await save_report(data, message.from_user.id, message.from_user.username or "")

    prihod = data["total"]  # нал + безнал
    rashod = data["supplier"] + data["igor"]
    # Остаток в кассе = Остаток на утро + Приход − Расход
    ostatok = data["yesterday_cash"] + prihod - rashod
    ostatok_text = f"+{ostatok:.0f}" if ostatok >= 0 else f"{ostatok:.0f}"

    await message.answer(
        f"✅ Отчёт збережено!\nКасир: <b>{data['surname']}</b>\nОбщая: <b>{data['total']:.0f} грн</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb()
    )

    admin_text = (
        f"📥 <b>Новий звіт</b>\n\n"
        f"<b>Касир:</b> {data['surname']}\n"
        f"<b>Дата:</b> {data['date']}\n\n"
        f"Наличные: <b>{data['cash']:.0f} грн</b>\n"
        f"Безналичные: <b>{data['card']:.0f} грн</b>\n"
        f"<b>Приход (Общая): {prihod:.0f} грн</b>\n\n"
        f"Товар от поставщика: <b>{data['supplier']:.0f} грн</b>\n"
        f"Товар от Игоря: <b>{data['igor']:.0f} грн</b>\n"
        f"<b>Расход: {rashod:.0f} грн</b>\n\n"
        f"Остаток на утро: <b>{data['yesterday_cash']:.0f} грн</b>\n"
        f"<b>Остаток в кассе (Разница за день): {ostatok_text} грн</b>"
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
        text += f"• <b>{r['surname']}</b> ({r['report_date']}) — {r['total']:.0f} грн\n"
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("статистика"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Немає доступу")
    reports = await get_last_reports(50)
    if not reports:
        return await message.answer("Немає даних")
    total = sum(r['total'] for r in reports)
    await message.answer(f"📊 Всього звітів: {len(reports)}\nЗагальна виручка: <b>{total:.0f} грн</b>", parse_mode=ParseMode.HTML)


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
