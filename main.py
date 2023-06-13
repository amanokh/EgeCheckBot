import asyncio
import logging
import auto_checker
import config
import os
import utils

from aiogram import Bot, Dispatcher, executor, types
from aiogram.utils.exceptions import MessageNotModified, MessageTextIsEmpty, InvalidQueryID, RetryAfter, \
    MessageIdInvalid, MessageToEditNotFound
from common import strings, buttons, db
from random import choice

from common.throttler import Throttler

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOGLEVEL", logging.DEBUG))

# Initialize bot and dispatcher
bot = Bot(token=config.API_TOKEN)
dp = Dispatcher(bot)

relax = False
throttled_by_id = {}


class OneEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    _loop = None

    def __init__(self, set_loop):
        super().__init__()
        self._loop = set_loop

    def get_event_loop(self):
        return self._loop


# Captcha handler:
async def bot_send_captcha(chat_id):
    await bot.send_message(chat_id, strings.login_captcha_prompt, parse_mode="MARKDOWN")

    shelve_result = await utils.handle_captcha_get(chat_id)
    if shelve_result:
        with open("_captcha" + str(chat_id), "rb") as photo:
            await bot.send_photo(chat_id, photo)
        utils.handle_captcha_delete(chat_id)
    else:
        markup_button = types.InlineKeyboardButton("Запросить капчу заново", callback_data="captcha_retry")
        markup = types.InlineKeyboardMarkup().add(markup_button)
        await bot.send_message(chat_id,
                               strings.err_captcha_noans,
                               reply_markup=markup)


# Results get handler:
async def bot_send_results(chat_id, is_first_user_hash=False):
    throttled_by_id.setdefault(chat_id, Throttler())
    if throttled_by_id[chat_id]():
        logger.debug("%d throttled" % chat_id)
        return

    if await utils.user_check_logged(chat_id):
        try:
            err_msg, response = await utils.handle_get_results_json(chat_id)

            if err_msg:  # throws Error
                text = err_msg
            elif response:  # else answer not null -> send response
                updates = await utils.check_results_updates(chat_id, response, callback_bot=bot)
                text = await utils.parse_results_message(response, updates, is_first_user_hash)
            else:  # response is Null
                text = "Пока результатов в вашем профиле нет.\nПопробуйте обновить позже."

            await bot.send_message(chat_id,
                                   text,
                                   parse_mode="MARKDOWN",
                                   reply_markup=buttons.markup_inline_results())

            if is_first_user_hash:
                region = await utils.user_get_region(chat_id)
                await utils.regions_update_exams(region, response)
                await utils.examsinfo_update(response)
                await utils.pass_stats_exams_by_user_hash(is_first_user_hash, response)
        except RetryAfter:
            logger.warning("User: %d FLOOD CONTROL" % chat_id)


async def bot_login_attempt(chat_id):
    if await utils.user_get_login_status(chat_id) == "login":
        shelve_answer, user_hash = await utils.handle_login(chat_id)

        if shelve_answer == 204:
            logger.debug("User: %d user authened" % chat_id)
            await bot.send_message(chat_id, strings.login_authened, reply_markup=buttons.markup_logged())
            await bot_send_results(chat_id, is_first_user_hash=user_hash)

        elif shelve_answer == 450:
            logger.debug("User: %d 450err" % chat_id)
            await bot.send_message(chat_id, strings.login_wrong_data, reply_markup=buttons.markup_inline_retry_login())

        elif shelve_answer == 452:
            logger.debug("User: %d 452err" % chat_id)
            await bot.send_message(chat_id,
                                   strings.err_noans_wrong_data,
                                   reply_markup=buttons.markup_inline_retry_login())
        else:
            logger.debug("User: %d ??err" % chat_id)
            await bot.send_message(chat_id, strings.err_results_unexpected % shelve_answer)
            await utils.user_clear(chat_id)
            await utils.user_login_stop(chat_id)


async def clear_user(chat_id):
    is_user_cleaned = await utils.user_clear(chat_id)
    is_login_cleaned = await utils.user_login_stop(chat_id)
    shelve_result = is_user_cleaned or is_login_cleaned
    if shelve_result:
        await bot.send_message(chat_id, strings.clear_done, reply_markup=buttons.markup_init())
        # logger.info("User: %s logout", chat_id)

    else:
        await bot.send_message(chat_id, strings.clear_not_found, reply_markup=buttons.markup_init())


async def send_notify_region_site(chat_id, region):
    if region == "77":
        await bot.send_message(chat_id, strings.warn_region_mos, parse_mode="MARKDOWN")
    elif region == "50":
        await bot.send_message(chat_id, strings.warn_region_mo, parse_mode="MARKDOWN")
    elif region == "78":
        await bot.send_message(chat_id, strings.warn_region_spb, parse_mode="MARKDOWN")


# Commands handlers:
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    logger.debug(message.chat.id)
    shelve_result = await utils.user_check_logged(int(message.chat.id))
    if not relax:
        if shelve_result:
            await message.answer(strings.start_authed)
        else:
            # logger.info("User: %s start", message.chat.id)
            await message.answer(strings.start_agree, reply_markup=buttons.markup_login(), parse_mode="MARKDOWN")
            await message.answer(strings.start_name)
            await utils.user_login_start(int(message.chat.id))


@dp.message_handler(commands=['logout', 'stop'])
async def clear_request(message: types.Message):
    await clear_user(message.chat.id)


@dp.message_handler(commands=['check'])
async def check_request(message: types.Message):
    await bot_send_results(message.chat.id)


@dp.message_handler(commands=['version'])
async def check_request(message: types.Message):
    if str(message.chat.id) in config.admin_ids:
        await message.answer(config.VERSION_BUILD)


@dp.message_handler(commands=['stats'])
async def check_request(message: types.Message):
    if str(message.chat.id) in config.admin_ids:
        await message.answer(await utils.table_count())


# Button callbacks:
@dp.callback_query_handler(lambda c: c.data == 'results_update')
async def process_callback_results_update(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    text = ""
    callback_text = ""

    throttled_by_id.setdefault(chat_id, Throttler())
    if throttled_by_id[chat_id]():
        logger.debug("%d throttled" % chat_id)
        await bot.answer_callback_query(callback_query.id)
        return

    try:
        if await utils.user_check_logged(chat_id):
            err_msg, response = await utils.handle_get_results_json(chat_id)
            if err_msg:  # throws Error
                text = err_msg
            elif response:  # else answer not null -> send response
                updates = await utils.check_results_updates(chat_id, response, callback_bot=bot)
                text = await utils.parse_results_message(response, updates)
                if not updates:
                    callback_text = "Обновлений нет"
            else:  # response is Null
                text = "Пока результатов в вашем профиле нет.\nПопробуйте обновить позже."

        await bot.edit_message_text(chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    text=text,
                                    parse_mode="MARKDOWN",
                                    reply_markup=buttons.markup_inline_results())
        await bot.answer_callback_query(callback_query.id, text=callback_text)

    except MessageNotModified:
        await bot.answer_callback_query(callback_query.id, text=callback_text)
    except MessageTextIsEmpty:
        pass
    except MessageIdInvalid:
        logger.warning("MessageIdInvalid, uid: %d, msg_id: %d", chat_id, callback_query.message.message_id)
        await bot_send_results(chat_id)
        logger.warning("Sent as alternative, uid: %d, msg_id: %d", chat_id, callback_query.message.message_id)
    except MessageToEditNotFound:
        logger.warning("MessageToEditNotFound, uid: %d, msg_id: %d", chat_id, callback_query.message.message_id)
        await bot_send_results(chat_id)
        logger.warning("Sent as alternative, uid: %d, msg_id: %d", chat_id, callback_query.message.message_id)
    except InvalidQueryID:
        # logger.warning("User: %d results-->Invalid Query ID (callback)" % chat_id)
        pass


@dp.callback_query_handler(lambda c: c.data == 'regions_btn_show')
async def process_callback_regions_show(callback_query: types.CallbackQuery):
    try:
        markup_button = types.InlineKeyboardButton("Скрыть список регионов", callback_data="regions_btn_hide")
        markup = types.InlineKeyboardMarkup().add(markup_button)

        await bot.answer_callback_query(callback_query.id)
        await bot.edit_message_text(chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    text=strings.list_regions(),
                                    parse_mode="MARKDOWN",
                                    reply_markup=markup)
    except MessageNotModified:
        # logger.warning("User: %d regions-->MessageNotModified (callback)" % chat_id)
        pass
    except MessageTextIsEmpty:
        # logger.warning("User: %d regions-->MessageTextIsEmpty (callback)" % chat_id)
        pass
    except InvalidQueryID:
        # logger.warning("User: %d regions-->Invalid Query ID (callback)" % chat_id)
        pass


@dp.callback_query_handler(lambda c: c.data == 'regions_btn_hide')
async def process_callback_regions_hide(callback_query: types.CallbackQuery):
    try:
        markup_button = types.InlineKeyboardButton("Показать список регионов", callback_data="regions_btn_show")
        markup = types.InlineKeyboardMarkup().add(markup_button)

        await bot.answer_callback_query(callback_query.id)
        await bot.edit_message_text(chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    text=strings.login_region,
                                    reply_markup=markup)
    except MessageNotModified:
        pass
    except MessageTextIsEmpty:
        pass
    except InvalidQueryID:
        pass


@dp.callback_query_handler(lambda c: c.data == 'captcha_retry')
async def process_callback_captcha_again(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    if await utils.user_get_login_status(callback_query.message.chat.id) == "captcha":
        await bot_send_captcha(callback_query.message.chat.id)


@dp.callback_query_handler(lambda c: c.data == 'login_retry')
async def process_callback_login_retry(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    await bot_login_attempt(chat_id)
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == 'start_over')
async def process_callback_start_over(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(chat_id, strings.start_name, reply_markup=buttons.markup_login())
    await utils.user_login_start(chat_id)


# Regexp handlers:
@dp.message_handler(regexp='Авторизоваться ➡️')
async def btn_login_start(message: types.Message):
    shelve_result = await utils.user_check_logged(int(message.chat.id))
    if not relax:
        if shelve_result:
            await message.answer(strings.start_authed)
        else:
            await message.answer(strings.start_name, reply_markup=buttons.markup_login())
            await utils.user_login_start(int(message.chat.id))


@dp.message_handler(regexp='Помощь')
async def btn_help(message: types.Message):
    if not relax:
        await message.answer(strings.help_message, parse_mode="MARKDOWN")


@dp.message_handler(regexp='Даты')
async def btn_timetable(message: types.Message):
    if not relax:
        await message.answer(strings.timetable_message, parse_mode="MARKDOWN")


@dp.message_handler(regexp='Получить результаты 🔄')
async def btn_results(message: types.Message):
    if await utils.user_check_logged(message.chat.id):
        await bot_send_results(message.chat.id)


@dp.message_handler(regexp='Выйти')
async def btn_logout(message: types.Message):
    await clear_user(message.chat.id)


@dp.message_handler(regexp='Начать заново')
async def btn_clear(message: types.Message):
    await clear_user(message.chat.id)


@dp.message_handler(regexp='Поддержать автора')
async def btn_donate(message: types.Message):
    if not relax:
        await bot.send_sticker(message.chat.id,
                               sticker="CAACAgIAAxkBAAEKasBgy2lj2DqnFd0sPmUAAZUqXxptRE8AAk4CAAJWnb0KMP5rbYEyA28fBA")
        await message.answer(strings.donate_message, parse_mode="MARKDOWN", reply_markup=buttons.markup_inline_donate())


@dp.message_handler(regexp="Написать автору ✏️")
async def btn_donate(message: types.Message):
    await message.answer("По любым вопросам можешь писать сюда 👉 @amanokh")


@dp.message_handler(content_types=['sticker'])
async def sticker_answer(message: types.Message):
    stickers = ['CAACAgIAAxkBAAEP-Zxij1NtuP32jpseIMLLMgH_qyuPsgACbRQAAvh48Ev_35tLbqKxRyQE',
                'CAACAgIAAxkDAAG-w9Bij1K0doS19MChTh1Zv5XuiUY_vQAC9RQAAvA6-UgpYiz-I0hBSSQE',
                'CAACAgIAAxkBAAEP-ahij1QLj4Eh4L_U1DeTbI2MCu4CTAAC_hEAAo6E8Eup_sGzXXLhQCQE',
                'CAACAgQAAxkBAAEP-apij1RAmV0JdJfhjzRzyb0kh0beqQACTAEAAqghIQZjKrRWscYWyCQE',
                'CAACAgIAAxkBAAEP-axij1RxuV6WmfbixVXdsSHHBG4ppwAClgsAAgGxSUrXP-UOB9uGfyQE']

    if message.sticker.file_unique_id == 'AgADfhAAAowt_Qc':
        await utils.stats_table.collect_sticker_feature(message.sticker.file_unique_id)
    if not relax:
        await bot.send_sticker(message.chat.id, sticker=choice(stickers))


@dp.message_handler()
async def echo(message: types.Message):
    text = message.text
    chat_id = message.chat.id
    status = await utils.user_get_login_status(chat_id)

    if status == '_name':
        shelve_result = await utils.user_login_set_name(chat_id, text)

        if shelve_result:
            await message.answer(strings.login_region, reply_markup=buttons.markup_inline_regions())
        else:
            await message.answer(strings.login_name_incorrect)

    elif status == 'region':
        if len(text) == 2 and text.isdigit() and int(text) in strings.regions:
            await utils.user_login_set_region(chat_id, text)
            await bot.send_message(chat_id, strings.confirm_region(int(text)), parse_mode="MARKDOWN")
            await send_notify_region_site(chat_id, text)
            await message.answer(strings.login_passport, parse_mode="MARKDOWN")
        else:
            await message.answer(strings.login_region_incorrect, reply_markup=buttons.markup_inline_regions())

    elif status == 'passport':
        shelve_result = await utils.user_login_set_passport(chat_id, text)

        if shelve_result:
            await bot_send_captcha(chat_id)
        else:
            await message.answer(strings.login_passport_incorrect)

    elif status == "captcha":
        # Check captcha:
        shelve_answer = await utils.user_login_check_captcha(chat_id, text)
        if shelve_answer:
            await bot_login_attempt(chat_id)
        else:
            await message.answer(strings.login_captcha_incorrect, reply_markup=buttons.markup_inline_retry_captcha())

    elif status == "login":
        await message.answer(strings.login_auth_process)
        await bot_login_attempt(chat_id)

    elif status == "logged":  # incorrect command
        logger.debug("User: %d unknown command: %s" % (chat_id, text))
        if not relax:
            await message.answer(strings.command_incorrect, reply_markup=buttons.markup_logged())

    else:
        if not relax:
            logger.debug("User: %d unknown command: %s" % (chat_id, text))
            await message.answer(strings.login_unauthorized)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.init_db())

    loop.create_task(auto_checker.check_thread_runner(bot))

    asyncio.set_event_loop_policy(OneEventLoopPolicy(loop))

    executor.start_polling(dp, skip_updates=True,
                           allowed_updates=types.AllowedUpdates.MESSAGE + types.AllowedUpdates.CALLBACK_QUERY)
