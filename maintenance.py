import logging
import config

from aiogram import Bot, Dispatcher, executor, types
from common import strings

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.API_TOKEN)
dp = Dispatcher(bot)


@dp.message_handler()
async def echo(message: types.Message):
    await message.answer(strings.maintenance_msg)


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True,
                           allowed_updates=types.AllowedUpdates.MESSAGE)
