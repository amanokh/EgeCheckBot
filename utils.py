import aiohttp
import os
import logging
import base64
import pytz
import ast
import sys
import asyncio
import shelve

from datetime import datetime
from hashlib import md5
from config import db_table_login, db_table_users, EGE_URL, EGE_HEADERS, EGE_TOKEN_URL, \
    EGE_LOGIN_URL, db_table_regions, db_table_examsinfo, proxy_url, relax_timer
from db_worker import DbConnection, DbTable
from pypika import Column
from json.decoder import JSONDecodeError
from aiogram import types, exceptions

db_conn = DbConnection().conn

users_table = DbTable(db_conn, db_table_users,
                      (Column("chat_id", "bigint", nullable=False),
                       Column("region", "int", nullable=False),
                       Column("notify", "int", nullable=False, default=1),
                       Column("token", "text", nullable=False),
                       Column("login_date", "int"),
                       Column("exams", "text"),
                       Column("exams_hash", "text")),
                      pk_id="chat_id")
login_table = DbTable(db_conn, db_table_login,
                      (Column("chat_id", "bigint", nullable=False),
                       Column("status", "text", nullable=False),
                       Column("_name", "text"),
                       Column("region", "int"),
                       Column("passport", "text"),
                       Column("captcha_token", "text"),
                       Column("captcha_answer", "text")),
                      pk_id="chat_id")

regions_table = DbTable(db_conn, db_table_regions,
                        (Column("region", "int", nullable=False),
                         Column("exams", "text", default="[]"),
                         Column("notified_exams", "text", default="[]")),
                        pk_id="region")

examsinfo_table = DbTable(db_conn, db_table_examsinfo,
                          (Column("exam_id", "int", nullable=False),
                           Column("title", "text", nullable=False),
                           Column("exam_date", "text"),
                           Column("res_date_official", "text"),
                           Column("res_date_predicted", "text")),
                          pk_id="exam_id")


async def table_count():
    try:
        users_count = await users_table.count()
        login_count = await login_table.count()

        exams_count = await examsinfo_table.count()

        return "Users logged: %d, not logged: %d, Parsed exams: %d, Server time: %s" % (
            users_count, login_count, exams_count, datetime.utcnow().strftime("%D, %H:%M:%S UTC"))
    except Exception as e:
        return str(e)


def emoji_get():
    with shelve.open('emoji.shelve') as emoji_db:
        return emoji_db["counters"]


def emoji_add(emoji):
    with shelve.open('emoji.shelve') as emoji_db:
        temp = emoji_db["counters"]
        temp[emoji] += 1
        emoji_db["counters"] = temp
        return temp


async def user_check_logged(chat_id):
    return await users_table.get(chat_id)


async def user_get_login_status(chat_id):
    if await users_table.get(chat_id):
        return "logged"
    else:
        user = await login_table.get(chat_id)
        if user:
            return user["status"]


async def user_get_notify_status(chat_id):
    user = await users_table.get(chat_id)
    if user:
        return user["notify"]


async def user_clear(chat_id):
    if await users_table.get(chat_id):
        await users_table.delete(chat_id)
        return True


async def user_login_stop(chat_id):
    if await login_table.get(chat_id):
        await login_table.delete(chat_id)
        return True


async def user_login_start(chat_id):
    await user_clear(chat_id)
    await user_login_stop(chat_id)

    await login_table.insert({
        "chat_id": chat_id,
        "status": "_name"
    })


async def user_login_setName(chat_id, name):
    a = name.split(" ")
    name_merged = md5(''.join(a).lower().replace("ё", "е").replace("й", "и").replace("-", "").encode()).hexdigest()

    if len(a) >= 2:
        await login_table.update(chat_id, {
            "status": "region",
            "_name": name_merged
        })
        return True


async def user_login_setRegion(chat_id, region):
    if len(region) == 2 and region.isdigit():
        await login_table.update(chat_id, {
            "status": "passport",
            "region": int(region)
        })
        return True


async def user_login_setPassport(chat_id, passport):
    if 5 <= len(passport) <= 12:
        await login_table.update(chat_id, {
            "status": "captcha",
            "passport": passport
        })
        return True


async def user_login_checkCaptcha(chat_id, text):
    if len(text) == 6 and text.isdigit():
        await login_table.update(chat_id, {
            "status": "login",
            "captcha_answer": text
        })
        return True


async def user_get_token(chat_id):
    user = await users_table.get(chat_id)
    if user:
        return user["token"]


async def user_get_region(chat_id):
    user = await users_table.get(chat_id)
    if user:
        return user["region"]


async def regions_update_exams(region, response):
    exams = set()
    for exam in response:
        exams.add(exam["ExamId"])

    region_info = await regions_table.get(region)
    if region_info:
        exams_db = set(ast.literal_eval(region_info["exams"]))
        exams.update(exams_db)
        await regions_table.update(region, {"region": region, "exams": str(list(exams))})
    else:
        await regions_table.insert({"region": region, "exams": str(list(exams))})


async def examsinfo_update(response):
    for exam in response:
        exam_id = exam["ExamId"]
        title = exam["Subject"]
        exam_date = exam["ExamDate"]

        if not await examsinfo_table.get(exam_id):
            await examsinfo_table.insert({
                "exam_id": exam_id,
                "title": title,
                "exam_date": exam_date
            })


def handle_captchaDelete(chat_id):
    try:
        os.remove("_captcha" + str(chat_id))
    except FileNotFoundError:
        return None


async def handle_captchaGet(chat_id):
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.get(EGE_TOKEN_URL, timeout=5, proxy=proxy_url)
            json = await response.json()

        await login_table.update(chat_id, {
            "captcha_token": json["Token"]
        })
        with open("_captcha" + str(chat_id), "wb") as f:
            f.write(base64.b64decode(json["Image"]))
        return json
    except (aiohttp.ClientConnectionError, AttributeError):
        return None
    except:
        return None


async def handle_login(chat_id):
    try:
        user = await login_table.get(chat_id)
        if 5 <= len(user["passport"]) < 12:
            params = {
                "Hash": user["_name"],
                "Document": user["passport"].rjust(12, '0'),
                "Region": user["region"],
                "Captcha": user["captcha_answer"],
                "Token": user["captcha_token"]
            }
        else:
            params = {
                "Hash": user["_name"],
                "Code": user["passport"],
                "Region": user["region"],
                "Captcha": user["captcha_answer"],
                "Token": user["captcha_token"]
            }
        async with aiohttp.ClientSession() as session:
            response = await session.post(EGE_LOGIN_URL, data=params, timeout=10)
            token = response.cookies["Participant"].value

        await users_table.insert({
            "chat_id": chat_id,
            "region": user["region"],
            "token": token,
            "notify": 1,
            "exams": "[]",
            "login_date": int(datetime.now().timestamp())
        })

        await login_table.delete(chat_id)
        with open('log_login_activity.txt', 'a') as logfile:
            logfile.write("%s, %d\n" % (datetime.utcnow().strftime("%D, %H:%M:%S"), chat_id))
        return 204
    except KeyError:
        return 450
    except aiohttp.ClientConnectionError:
        return 452


async def handle_get_results_json(chat_id, attempts=5, logs=True, is_user_request=True):
    if attempts == 0:
        return ["Сервер ЕГЭ не ответил на запрос. Попробуйте получить результаты ещё раз."]
    try:
        user = await users_table.get(chat_id)
        if user:
            token = user["token"]
            headers = EGE_HEADERS.copy()
            headers["Cookie"] = "Participant=" + token

            async with aiohttp.ClientSession() as session:
                response = await session.get(EGE_URL, headers=headers, timeout=5, proxy=proxy_url)
                json = await response.json()
            if logs:
                logging.log(logging.INFO, "User: %d results got" % chat_id)
                with open('log_time_activity.txt', 'a') as logfile:
                    logfile.write("%s %d\n" % (datetime.utcnow().strftime("%D, %H:%M:%S"), chat_id))

            return [0, json["Result"]["Exams"]]
        else:
            logging.log(logging.WARNING, "User: %d results UNSUCCESSFUL: unlogged" % chat_id)
            return ["Возникла ошибка при авторизации. Пожалуйста, попробуйте войти заново с помощью /logout."]
    except aiohttp.ClientConnectionError:
        logging.log(logging.WARNING, str(chat_id) + " REQUESTS.PY Exc, attempt: %d" % attempts)
        return await handle_get_results_json(chat_id, attempts - 1, logs=logs, is_user_request=is_user_request)
    except (KeyError, JSONDecodeError):
        logging.log(logging.WARNING, str(chat_id) + str(response.content) + " attempt: %d" % attempts)
        return await handle_get_results_json(chat_id, attempts - 1, logs=logs, is_user_request=is_user_request)


async def handle_get_results_json_token(token, attempts=5):
    if attempts == 0:
        return [1]
    try:
        headers = EGE_HEADERS.copy()
        headers["Cookie"] = "Participant=" + token
        async with aiohttp.ClientSession() as session:
            response = await session.get(EGE_URL, headers=headers, timeout=5, proxy=proxy_url)
            json = await response.json()
        return [0, json["Result"]["Exams"]]
    except aiohttp.ClientConnectionError:
        return await handle_get_results_json_token(token, attempts - 1)
    except (KeyError, JSONDecodeError):
        return await handle_get_results_json_token(token, attempts - 1)


# преобразование падежа слова "балл"
def count_case(mark):
    if mark % 10 == 1:
        return " балл"
    elif 1 < mark % 10 < 5:
        return " балла"
    else:
        return " баллов"


# проверка на прохождение порога по баллам
def check_threshold(mark, mark_threshold, title):
    if "устн" in title:
        return ""
    else:
        return " ✅" if mark >= mark_threshold else "❗️(порог не пройден)"


# проверка на наличие обновлений с прошлой проверки
# запускает рассылку, если необходимо
async def check_results_updates(chat_id, response, callback_bot=None, is_user_request=True):
    user = await users_table.get(chat_id)
    if user:
        # update hash (and exams list) in 'users.db'
        old_hash = user["exams_hash"]
        region = user["region"]

        new_hash = md5(str(response).encode()).hexdigest()
        exams = set()
        for exam in response:
            exams.add(exam["ExamId"])

        if old_hash != new_hash:  # результаты обновились
            if is_user_request:
                await users_table.update(chat_id, {
                    "exams": str(list(exams)),
                    "exams_hash": new_hash
                })
                await on_results_updated(response, region, chat_id, callback_bot)
            else:
                await on_results_updated(response, region, 1, callback_bot)
            return True

    else:  # user logged out
        logging.log(logging.WARNING, "User: %d results after log out" % chat_id)


async def on_results_updated(response, region, except_from_id=1, callback_bot=None):
    for exam in response:
        title = exam["Subject"]
        exam_id = exam["ExamId"]
        date = exam["ExamDate"]
        is_composition = exam["IsComposition"]
        is_hidden = exam["IsHidden"]
        has_result = exam["HasResult"]
        mark = exam["TestMark"]

        ignored_exams = []

        if (has_result and not is_hidden) or int(mark):  # есть ли результат
            if exam_id not in ignored_exams and not is_composition:  # проверка на thrown/composition
                region_info = await regions_table.get(region)
                if region_info:
                    region_exams = set(ast.literal_eval(region_info["notified_exams"]))
                    if exam_id not in region_exams:  # проверка на существующее оповещение
                        region_exams.add(exam_id)
                        await regions_table.update(region, {"notified_exams": str(list(region_exams))})

                        logging.log(logging.WARNING, "MAIL REGION: %d EXAM: %d %s %s" % (region, exam_id, title, date))
                        asyncio.create_task(run_mailer(region, title, exam_id, except_from_id, bot=callback_bot))


async def run_mailer(region, title, exam_id, except_from_id=1, bot=None):
    logging.log(logging.WARNING, "MAILER STARTED %d %s" % (region, title))
    time = datetime.now().timestamp()
    users_count = 0

    with open('log_notify.txt', 'a') as logfile:
        logfile.write("%s MAILER STARTED %d %s\n" % (datetime.now().strftime("%D %H:%M:%S"), region, title))

    markup_button1 = types.InlineKeyboardButton("Обновить результаты", callback_data="results_update")
    markup = types.InlineKeyboardMarkup().add(markup_button1)
    message = "⚡️*Доступны результаты по предмету %s*⚡️\nОбновите, чтобы узнать баллы:" % title.upper()

    for user in await users_table.rows_where("region = $1 AND notify = 1", region):
        chat_id = user["chat_id"]
        if bot:
            try:
                user_exams_string = user["exams"]
                if user_exams_string:
                    user_exams = ast.literal_eval(user_exams_string)
                else:
                    user_exams = []
                if chat_id != except_from_id and exam_id in user_exams:
                    try:
                        users_count += 1
                        await bot.send_message(chat_id, message, parse_mode="MARKDOWN", reply_markup=markup)
                        await asyncio.sleep(0.2)
                    except exceptions.RetryAfter:
                        await asyncio.sleep(10)
                        await bot.send_message(chat_id, message, parse_mode="MARKDOWN", reply_markup=markup)
                    except exceptions.BotBlocked:
                        logging.log(logging.WARNING, "User: %d blocked a bot while notifying" % chat_id)
                    except:
                        logging.log(logging.WARNING, "User: %d unexpected error while notifying" % chat_id)
            except:
                logging.log(logging.WARNING,
                            "User: %d may have been deleted %s" % (chat_id, sys.exc_info()[1]))
        else:
            logging.log(logging.WARNING, "CALLBACK BOT is unspecified")

    time_stop = datetime.now().timestamp()
    logging.log(logging.WARNING, "MAILER FINISHED %d %s in %f secs" % (region, title, time_stop - time))
    with open('log_notify.txt', 'a') as logfile:
        logfile.write(
            "%s MAILER FINISHED %d %s %d users, in %f secs\n" % (datetime.now().strftime("%D %H:%M:%S"), region,
                                                                 title, users_count, time_stop - time))


async def parse_results_message(chat_id, response, is_first=False, callback_bot=None):
    time = datetime.now(pytz.timezone('Europe/Moscow')).strftime("%H:%M")

    updates = await check_results_updates(chat_id, response, callback_bot)

    mark_sum = 0
    show_sum = True

    # message = "🔥 *Наблюдается большая нагрузка на сервер. Из-за ограничений Telegram результаты можно запрашивать только раз в минуту. Пожалуйста, делайте запросы реже и подключите уведомления о новых результатах!*\n\n"
    message = ""

    if is_first:
        message += "*Текущие результаты:* (на %s МСК)\n\n" % time
    elif updates:
        message += "*⚡️Есть обновления⚡️\n*(на %s МСК)\n\n" % time
    else:
        message += "*Текущие результаты:*\nОбновлений нет (на %s МСК)\n\n" % time

    for exam in response:
        title = exam["Subject"]
        is_composition = exam["IsComposition"]
        is_hidden = exam["IsHidden"]
        has_result = exam["HasResult"]
        mark = exam["TestMark"]
        mark_threshold = exam["MinMark"]

        if has_result and not is_hidden:
            if is_composition:
                mark_string = "*Зачёт* ✅" if mark == 1 else "*Незачёт* ❗️"
            else:
                mark_string = "*" + str(mark) + count_case(mark) + check_threshold(mark, mark_threshold, title) + "*"
                mark_sum += int(mark)
        elif int(mark):
            mark_string = "*" + str(mark) + count_case(mark) + check_threshold(mark,
                                                                               mark_threshold,
                                                                               title) + "* _(результат скрыт)_"
            show_sum = False
        else:
            mark_string = "_нет результата_"
            show_sum = False

        message += title + " — " + mark_string + "\n"

    if show_sum:
        message += "\n_Сумма по всем предметам_ — *" + str(mark_sum) + count_case(mark_sum) + "*"

    return message
