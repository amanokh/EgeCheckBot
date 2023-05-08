import asyncio
import logging
import os
import utils

from datetime import datetime
from aiogram import types, exceptions
from config import relax_mailer, relax_retry_error


class Mailer:
    def __init__(self, region, title, exam_id, bot, except_from_id=1):
        logging.basicConfig()
        self.logger = logging.getLogger("mailer_{}_{}".format(region, exam_id))
        self.logger.setLevel(os.environ.get("LOGLEVEL", logging.DEBUG))

        self.region = region
        self.title = title
        self.exam_id = exam_id
        self.except_chat_id = except_from_id
        self.bot = bot

    def run(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self._mailer())

    async def _send_message(self, chat_id, attempts=5):
        markup_button = types.InlineKeyboardButton("Обновить результаты", callback_data="results_update")
        markup = types.InlineKeyboardMarkup().add(markup_button)
        message = "⚡️*В вашем регионе доступны результаты по предмету %s*⚡️\nОбновите, чтобы узнать баллы:" % self.title.upper()

        try:
            await self.bot.send_message(chat_id, message, parse_mode="MARKDOWN", reply_markup=markup)
        except exceptions.RetryAfter:
            self.logger.warning("User: %d RetryAfter error, waiting..." % chat_id)
            await asyncio.sleep(relax_retry_error)
            if attempts > 0:
                await self._send_message(chat_id, attempts-1)
        except exceptions.BotBlocked:
            self.logger.warning("User: %d blocked a bot while notifying" % chat_id)
        except Exception as e:
            self.logger.warning("User: %d unexpected error while notifying: %s", chat_id, e)

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
            users_count += 1
            await self._send_message(chat_id)
            await asyncio.sleep(relax_mailer)

        total_time = datetime.now().timestamp() - time_start
        self.logger.warning("MAILER FINISHED %d %s %d users, in %f secs\n",
                            self.region, self.title, users_count, total_time)
