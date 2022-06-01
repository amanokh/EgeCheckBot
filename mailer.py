import asyncio
import logging
import utils

from datetime import datetime
from aiogram import types, exceptions
from config import relax_mailer, relax_retry_error


class Mailer:
    def __init__(self, region, title, exam_id, bot, except_from_id=1):
        self.logger = logging.getLogger("mailer_{}_{}".format(region, exam_id))
        self.logger.setLevel(logging.DEBUG)

        c_handler = logging.StreamHandler()
        f_handler = logging.FileHandler("mailer_{}_{}.log".format(region, exam_id))

        c_handler.setFormatter(logging.Formatter('%(name)s:%(message)s'))
        f_handler.setFormatter(logging.Formatter('%(asctime)s:%(name)s:%(message)s'))

        self.logger.addHandler(c_handler)
        self.logger.addHandler(f_handler)

        self.region = region
        self.title = title
        self.exam_id = exam_id
        self.except_chat_id = except_from_id
        self.bot = bot

    def run(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self._mailer())

    async def _send_message(self, chat_id):
        markup_button = types.InlineKeyboardButton("Обновить результаты", callback_data="results_update")
        markup = types.InlineKeyboardMarkup().add(markup_button)
        message = "⚡️*Доступны результаты по предмету %s*⚡️\nОбновите, чтобы узнать баллы:" % self.title.upper()

        await self.bot.send_message(chat_id, message, parse_mode="MARKDOWN", reply_markup=markup)

    async def _mailer(self):
        self.logger.warning("MAILER STARTED %d %s" % (self.region, self.title))
        time_start = datetime.now().timestamp()
        users_count = 0
        users_fetched = await utils.users_table.custom_fetch(
            "select * from users where $1 = any(exams) and region = $2 and chat_id <> $3 and notify = 1",
            self.exam_id,
            self.region,
            self.except_chat_id)

        for user in users_fetched:
            chat_id = user["chat_id"]
            try:
                users_count += 1
                await self._send_message(chat_id)
                await asyncio.sleep(relax_mailer)
            except exceptions.RetryAfter:
                await asyncio.sleep(relax_retry_error)
                await self._send_message(chat_id)
            except exceptions.BotBlocked:
                self.logger.warning("User: %d blocked a bot while notifying" % chat_id)
            except:
                self.logger.warning("User: %d unexpected error while notifying" % chat_id)

        total_time = datetime.now().timestamp() - time_start
        self.logger.warning("MAILER FINISHED %d %s %d users, in %f secs\n",
                            self.region, self.title, users_count, total_time)
