import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types # type: ignore
from aiogram.filters import Command, StateFilter # type: ignore
from aiogram.fsm.context import FSMContext # type: ignore
from aiogram.fsm.state import State, StatesGroup # type: ignore
from aiogram.fsm.storage.memory import MemoryStorage # type: ignore
from apscheduler.schedulers.asyncio import AsyncIOScheduler # type: ignore

BOT_TOKEN = "token"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

class NotificationStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_postpone = State()

notifications = {}
user_last_notification = {}  # Храним последнее напоминание пользователя

async def send_notification(user_id, notification_id):
    if notification_id in notifications:
        notification = notifications[notification_id]
        text = notification["text"]
       
        # Создаем клавиатуру для откладывания
        keyboard = types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="Отложить на 5 минут")],
                [types.KeyboardButton(text="Отложить на 15 минут")],
                [types.KeyboardButton(text="Отложить на 1 час")],
                [types.KeyboardButton(text="Отложить на 3 часа")],
            ],
            resize_keyboard=True
        )
       
        await bot.send_message(
            user_id,
            f"🔔 Напоминание: {text}",
            reply_markup=keyboard
        )
       
        # Обновляем последнее активное напоминание
        user_last_notification[user_id] = notification_id

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="Создать напоминание")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "⏰ Бот-напоминалка\nНажмите кнопку ниже, чтобы создать новое напоминание",
        reply_markup=keyboard
    )

@dp.message(lambda message: message.text == "Создать напоминание")
async def create_notification(message: types.Message, state: FSMContext):
    await message.answer(
        "Введите текст напоминания:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(NotificationStates.waiting_for_text)

@dp.message(StateFilter(NotificationStates.waiting_for_text))
async def process_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer(
        "Введите дату напоминания в формате ДД.ММ.ГГГГ (например, 31.12.2023):"
    )
    await state.set_state(NotificationStates.waiting_for_date)

@dp.message(StateFilter(NotificationStates.waiting_for_date))
async def process_date(message: types.Message, state: FSMContext):
    try:
        date = datetime.strptime(message.text, "%d.%m.%Y").date()
        await state.update_data(date=message.text)
        await message.answer(
            "Введите время напоминания в формате ЧЧ:ММ (например, 14:30):"
        )
        await state.set_state(NotificationStates.waiting_for_time)
    except ValueError:
        await message.answer("❌ Неверный формат даты. Введите ДД.ММ.ГГГГ")

@dp.message(StateFilter(NotificationStates.waiting_for_time))
async def process_time(message: types.Message, state: FSMContext):
    try:
        time = datetime.strptime(message.text, "%H:%M").time()
        data = await state.get_data()
       
        notification_datetime = datetime.strptime(
            f"{data['date']} {message.text}",
            "%d.%m.%Y %H:%M"
        )
       
        if notification_datetime < datetime.now():
            await message.answer("❌ Это время уже прошло. Введите будущую дату и время.")
            return
       
        notification_id = f"{len(notifications)}_{message.from_user.id}"
       
        notifications[notification_id] = {
            "text": data["text"],
            "datetime": notification_datetime,
            "user_id": message.from_user.id,
            "original_datetime": notification_datetime  # Сохраняем оригинальное время
        }
       
        scheduler.add_job(
            send_notification,
            'date',
            run_date=notification_datetime,
            args=[message.from_user.id, notification_id]
        )
       
        await message.answer(
            f"✅ Напоминание установлено на {data['date']} в {message.text}:\n"
            f"📝 Текст: {data['text']}"
        )
        await state.clear()
       
    except ValueError:
        await message.answer("❌ Неверный формат времени. Введите ЧЧ:ММ")

@dp.message(lambda message: message.text.startswith("Отложить на"))
async def postpone_notification(message: types.Message):
    try:
        user_id = message.from_user.id
        if user_id not in user_last_notification:
            await message.answer("❌ Нет активных напоминаний для откладывания", reply_markup=types.ReplyKeyboardRemove())
            return
           
        notification_id = user_last_notification[user_id]
        if notification_id not in notifications:
            await message.answer("❌ Напоминание больше не активно", reply_markup=types.ReplyKeyboardRemove())
            return
       
        # Парсим время откладывания
        parts = message.text.split()
        if len(parts) != 4:  # "Отложить на 5 минут" - 4 части
            raise ValueError
       
        num = int(parts[2])
        unit = parts[3]
       
        # Определяем дельту времени
        if "минут" in unit:
            delta = timedelta(minutes=num)
        elif "час" in unit:
            delta = timedelta(hours=num)
        else:
            raise ValueError
       
        # Обновляем время напоминания
        notification = notifications[notification_id]
        new_time = datetime.now() + delta
       
        # Отменяем старое задание (если есть)
        for job in scheduler.get_jobs():
            if job.args and len(job.args) >= 2 and job.args[1] == notification_id:
                job.remove()
       
        # Создаем новое задание
        scheduler.add_job(
            send_notification,
            'date',
            run_date=new_time,
            args=[user_id, notification_id],
            id=f"notify_{notification_id}"
        )
       
        # Обновляем данные
        notification["datetime"] = new_time
        notifications[notification_id] = notification
       
        await message.answer(
            f"⏳ Напоминание отложено на {parts[2]} {parts[3]}.\n"
            f"Новое время срабатывания: {new_time.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=types.ReplyKeyboardRemove()
        )
       
    except (ValueError, IndexError):
        await message.answer(
           "❌ Используйте один из форматов:\n"
           "Отложить на 5 минут\n"
           "Отложить на 15 минут\n"
           "Отложить на 1 час\n"
           "Отложить на 3 часа",
           reply_markup=types.ReplyKeyboardRemove()
       )

async def on_startup():
    scheduler.start()
    now = datetime.now()
    for notification_id, notification in list(notifications.items()):
        if notification["datetime"] < now:
            await send_notification(notification["user_id"], notification_id)

async def on_shutdown():
    scheduler.shutdown()

if __name__ == "__main__":
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    asyncio.run(dp.start_polling(bot))
