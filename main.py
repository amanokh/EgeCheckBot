import asyncio
import logging
import auto_checker
from aiogram import Bot, Dispatcher, executor, types
from aiogram.utils.exceptions import MessageNotModified, MessageTextIsEmpty, InvalidQueryID, RetryAfter

from common import strings, buttons
import config
import utils

logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=config.API_TOKEN)
dp = Dispatcher(bot)

# Initialize database
utils.db_init()

relax = True


# Captcha handler:
async def bot_send_captcha(chat_id):
    await bot.send_message(chat_id, strings.login_captcha_prompt, parse_mode="MARKDOWN")

    shelve_result = await utils.handle_captchaGet(chat_id)
    if shelve_result:
        with open("_captcha" + str(chat_id), "rb") as photo:
            await bot.send_photo(chat_id, photo)
        utils.handle_captchaDelete(chat_id)
    else:
        markup_button = types.InlineKeyboardButton("Запросить капчу заново", callback_data="captcha_retry")
        markup = types.InlineKeyboardMarkup().add(markup_button)
        await bot.send_message(chat_id,
                               strings.err_captcha_noans,
                               reply_markup=markup)


# Results get handler:
async def bot_send_results(chat_id, is_first=False):
    if utils.user_check_logged(chat_id):
        try:
            response = await utils.handle_get_results_json(chat_id)

            if response[0] and response[0] != 1:  # throws Error
                await bot.send_message(chat_id, response[0], reply_markup=buttons.markup_inline_results())

            elif len(response[1]):  # else answer not null -> send response
                await bot.send_message(chat_id,
                                       utils.parse_results_message(chat_id, response[1], is_first, callback_bot=bot),
                                       parse_mode="MARKDOWN", reply_markup=buttons.markup_inline_results())

            elif response[0] != 1:  # response is Null
                await bot.send_message(chat_id, "Пока результатов в вашем профиле нет.\nПопробуйте обновить позже!")

            if is_first:
                region = utils.user_get_region(chat_id)
                utils.regions_update_exams(region, response[1])
                utils.examsinfo_update(response[1])
        except RetryAfter:
            logging.log(logging.WARNING, "User: %d FLOOD CONTROL" % chat_id)


async def bot_login_attempt(chat_id):
    if utils.user_get_login_status(chat_id) == "login":
        shelve_answer = await utils.handle_login(chat_id)

        if shelve_answer == 204:
            logging.log(logging.INFO, "User: %d user authened" % chat_id)
            await bot.send_message(chat_id, strings.login_authened, reply_markup=buttons.markup_logged(chat_id))
            await bot_send_results(chat_id, is_first=True)

        elif shelve_answer == 450:
            # logging.log(logging.WARNING, "User: %d 450err" % chat_id)

            await bot.send_message(chat_id, strings.login_wrong_data, reply_markup=buttons.markup_inline_retry_login())

        elif shelve_answer == 452:
            # logging.log(logging.WARNING, "User: %d 452err" % chat_id)

            await bot.send_message(chat_id,
                                   strings.err_noans_wrong_data,
                                   reply_markup=buttons.markup_inline_retry_login())
        else:
            logging.log(logging.WARNING, "User: %d ??err" % chat_id)
            await bot.send_message(chat_id, strings.err_results_unexpected % shelve_answer)
            utils.user_clear(chat_id)
            utils.user_login_stop(chat_id)


async def clear_user(chat_id):
    is_user_cleaned = utils.user_clear(chat_id)
    is_login_cleaned = utils.user_login_stop(chat_id)
    shelve_result = is_user_cleaned or is_login_cleaned
    if shelve_result:
        await bot.send_message(chat_id, strings.clear_done, reply_markup=buttons.markup_init())
        # logging.log(logging.INFO, "User: %s logout", chat_id)

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
    logging.log(logging.INFO, message.chat.id)
    shelve_result = utils.user_check_logged(int(message.chat.id))
    if relax and utils.user_set_check_request_time(message.chat.id):
        if shelve_result:
            await message.answer(strings.start_authed)
        else:
            # logging.log(logging.INFO, "User: %s start", message.chat.id)
            await message.answer(strings.start_agree, reply_markup=buttons.markup_login(), parse_mode="MARKDOWN")
            await message.answer(strings.start_name)
            utils.user_login_start(int(message.chat.id))


@dp.message_handler(commands=['logout', 'stop'])
async def clear_request(message: types.Message):
    await clear_user(message.chat.id)


@dp.message_handler(commands=['check'])
async def check_request(message: types.Message):
    await bot_send_results(message.chat.id)


@dp.message_handler(commands=['version'])
async def check_request(message: types.Message):
    await message.answer(config.VERSION_BUILD)


@dp.message_handler(commands=['stats'])
async def check_request(message: types.Message):
    await message.answer(utils.table_count())


# Button callbacks:
@dp.callback_query_handler(lambda c: c.data == 'results_update')
async def process_callback_results_update(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    text = ""

    try:
        resp = 0

        if utils.user_check_logged(chat_id):
            response = await utils.handle_get_results_json(chat_id)
            resp = response[0]
            if response[0] and response[0] != 1:  # throws Error
                text = response[0]
            elif len(response[1]):  # else answer not null -> send response
                text = utils.parse_results_message(chat_id, response[1], callback_bot=bot)
            else:  # response is Null
                text = "Пока результатов в вашем профиле нет.\nПопробуйте обновить позже."

        await bot.answer_callback_query(callback_query.id)
        if resp != 1:
            await bot.edit_message_text(chat_id=callback_query.message.chat.id,
                                        message_id=callback_query.message.message_id,
                                        text=text,
                                        parse_mode="MARKDOWN",
                                        reply_markup=buttons.markup_inline_results())
    except MessageNotModified:
        pass
    except MessageTextIsEmpty:
        pass
    except InvalidQueryID:
        # logging.log(logging.WARNING, "User: %d results-->Invalid Query ID (callback)" % chat_id)
        pass


@dp.callback_query_handler(lambda c: c.data == 'regions_btn_show')
async def process_callback_regions_show(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
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
        # logging.log(logging.WARNING, "User: %d regions-->MessageNotModified (callback)" % chat_id)
        pass
    except MessageTextIsEmpty:
        # logging.log(logging.WARNING, "User: %d regions-->MessageTextIsEmpty (callback)" % chat_id)
        pass
    except InvalidQueryID:
        # logging.log(logging.WARNING, "User: %d regions-->Invalid Query ID (callback)" % chat_id)
        pass


@dp.callback_query_handler(lambda c: c.data == 'regions_btn_hide')
async def process_callback_regions_hide(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id

    try:
        markup_button = types.InlineKeyboardButton("Показать список регионов", callback_data="regions_btn_show")
        markup = types.InlineKeyboardMarkup().add(markup_button)

        await bot.answer_callback_query(callback_query.id)
        await bot.edit_message_text(chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    text=strings.login_region,
                                    reply_markup=markup)
    except MessageNotModified:
        # logging.log(logging.WARNING, "User: %d regions-->MessageNotModified (callback)" % chat_id)
        pass
    except MessageTextIsEmpty:
        # logging.log(logging.WARNING, "User: %d regions-->MessageTextIsEmpty (callback)" % chat_id)
        pass
    except InvalidQueryID:
        # logging.log(logging.WARNING, "User: %d regions-->Invalid Query ID (callback)" % chat_id)
        pass


@dp.callback_query_handler(lambda c: c.data == 'captcha_retry')
async def process_callback_captcha_again(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    if utils.user_get_login_status(callback_query.message.chat.id) == "captcha":
        await bot_send_captcha(callback_query.message.chat.id)


@dp.callback_query_handler(lambda c: c.data == 'login_retry')
async def process_callback_login_retry(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    await bot_login_attempt(chat_id)
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == 'notify_on')
async def process_callback_notify_on(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    utils.users_table.update(chat_id, {"notify": 1})
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(chat_id, strings.login_notify_on, reply_markup=buttons.markup_logged(chat_id))


@dp.callback_query_handler(lambda c: c.data == 'start_over')
async def process_callback_start_over(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(chat_id, strings.start_name, reply_markup=buttons.markup_login())
    utils.user_login_start(chat_id)


# Regexp handlers:
@dp.message_handler(regexp='Авторизоваться ➡️')
async def btn_login_start(message: types.Message):
    shelve_result = utils.user_check_logged(int(message.chat.id))
    if relax and utils.user_set_check_request_time(message.chat.id):
        if shelve_result:
            await message.answer(strings.start_authed)
        else:
            await message.answer(strings.start_name, reply_markup=buttons.markup_login())
            utils.user_login_start(int(message.chat.id))


@dp.message_handler(regexp='Помощь')
async def btn_help(message: types.Message):
    if relax and utils.user_set_check_request_time(message.chat.id):
        await message.answer(strings.help_message, parse_mode="MARKDOWN")


@dp.message_handler(regexp='Даты')
async def btn_timetable(message: types.Message):
    if relax and utils.user_set_check_request_time(message.chat.id):
        await message.answer(strings.timetable_message, parse_mode="MARKDOWN")


@dp.message_handler(regexp='Получить результаты 🔄')
async def btn_results(message: types.Message):
    if utils.user_check_logged(message.chat.id):
        await bot_send_results(message.chat.id)


@dp.message_handler(regexp='Выйти')
async def btn_logout(message: types.Message):
    await clear_user(message.chat.id)


@dp.message_handler(regexp='Начать заново')
async def btn_clear(message: types.Message):
    await clear_user(message.chat.id)


@dp.message_handler(regexp='Включить уведомления')
async def btn_notify_on(message: types.Message):
    if relax and utils.user_set_check_request_time(message.chat.id):
        utils.users_table.update(message.chat.id, {"notify": 1})
        await message.answer(strings.login_notify_on, reply_markup=buttons.markup_logged(message.chat.id))


@dp.message_handler(regexp='Выключить уведомления')
async def btn_notify_off(message: types.Message):
    if relax and utils.user_set_check_request_time(message.chat.id):
        utils.users_table.update(message.chat.id, {"notify": 0})
        await message.answer(strings.login_notify_off, reply_markup=buttons.markup_logged(message.chat.id))


@dp.message_handler(regexp='Поддержать автора 💸')
async def btn_donate(message: types.Message):
    if relax and utils.user_set_check_request_time(message.chat.id):
        await bot.send_sticker(message.chat.id,
                               sticker="CAACAgIAAxkBAAEFbFZfExWWz35Cxl39miaINZPBBtbN7AACkgEAAk-cEwJ5I1T3ZxOTnRoE")
        await message.answer(strings.donate_message)


@dp.message_handler(regexp='Отправить пожертвование 💸')
async def btn_donate(message: types.Message):
    if relax and utils.user_set_check_request_time(message.chat.id):
        await bot.send_sticker(message.chat.id,
                               sticker="CAACAgIAAxkBAAEFbFZfExWWz35Cxl39miaINZPBBtbN7AACkgEAAk-cEwJ5I1T3ZxOTnRoE")
        await message.answer(strings.donate_message)


@dp.message_handler(regexp="Написать автору ✏️")
async def btn_donate(message: types.Message):
    await message.answer("По любым вопросам можешь писать сюда 👉 @amanokh")


@dp.message_handler(content_types=['sticker'])
async def sticker_answer(message: types.Message):
    if relax and utils.user_set_check_request_time(message.chat.id):
        await bot.send_sticker(message.chat.id,
                           sticker="CAACAgIAAxkBAAEFeUBfGQABsjZ9enZWh28WepofFX0uLMAAAtAAAzMkAAEMpaqRVXRTgaAaBA")


@dp.message_handler()
async def echo(message: types.Message):
    text = message.text
    chat_id = int(message.chat.id)
    status = utils.user_get_login_status(chat_id)

    if status == 'name':
        # logging.log(logging.INFO, "%d name %s" % (chat_id, text))

        shelve_result = utils.user_login_setName(chat_id, text)

        if shelve_result:
            await message.answer(strings.login_region, reply_markup=buttons.markup_inline_regions())
        else:
            await message.answer(strings.login_name_incorrect)

    elif status == 'region':
        # logging.log(logging.INFO, "User: %d region: %s" % (chat_id, text))

        if len(text) == 2 and text.isdigit() and int(text) in strings.regions:
            utils.user_login_setRegion(chat_id, text)
            await bot.send_message(chat_id, strings.confirm_region(int(text)), parse_mode="MARKDOWN")
            await send_notify_region_site(chat_id, text)
            await message.answer(strings.login_passport)
        else:
            await message.answer(strings.login_region_incorrect, reply_markup=buttons.markup_inline_regions())

    elif status == 'passport':
        shelve_result = utils.user_login_setPassport(chat_id, text)

        if shelve_result:
            await bot_send_captcha(chat_id)
        else:
            await message.answer(strings.login_passport_incorrect)

    elif status == "captcha":
        # Check captcha:
        shelve_answer = utils.user_login_checkCaptcha(chat_id, text)
        if shelve_answer:
            # await message.answer(strings.login_auth_process)
            await bot_login_attempt(chat_id)
        else:
            await message.answer(strings.login_captcha_incorrect, reply_markup=buttons.markup_inline_retry_captcha())

    elif status == "login":
        await message.answer(strings.login_auth_process)
        await bot_login_attempt(chat_id)

    elif status == "logged":  # incorrect command
        # logging.log(logging.INFO, "User: %d unknown command: %s" % (chat_id, text))
        if relax and utils.user_set_check_request_time(message.chat.id):
            await message.answer(strings.command_incorrect, reply_markup=buttons.markup_logged(chat_id))

    else:
        if relax and utils.user_set_check_request_time(message.chat.id):
            logging.log(logging.INFO, "User: %d unknown command: %s" % (chat_id, text))
            await message.answer(strings.login_unauthorized)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(auto_checker.check_thread_runner([21, 335], bot))

    executor.start_polling(dp, skip_updates=True)
