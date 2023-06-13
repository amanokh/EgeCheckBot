import base64
import logging
import os
import shelve
from asyncio import TimeoutError as ATimeoutError
from datetime import datetime
from hashlib import md5
from json.decoder import JSONDecodeError

import aiohttp
from asyncpg.exceptions import UniqueViolationError

from common.db import users_table, examsinfo_table, login_table, stats_table, regions_table
from common.strings import months
from config import EGE_URL, EGE_HEADERS, EGE_TOKEN_URL, \
    EGE_LOGIN_URL, proxy_url
from mailer import Mailer

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOGLEVEL", logging.DEBUG))

cached_exam_results_dates = {}


async def table_count():
    try:
        users_count = await users_table.count()
        login_count = await login_table.count()
        exams_count = await examsinfo_table.count()
        total_users = await stats_table.count()

        return "Users logged: %d, not logged: %d, Total unique users: %d, Parsed exams: %d, Server time: %s" % (
            users_count, login_count, total_users, exams_count, datetime.utcnow().strftime("%D, %H:%M:%S UTC"))
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


async def user_login_set_name(chat_id, name):
    a = name.split(" ")
    name_merged = md5(''.join(a).lower().replace("ё", "е").replace("й", "и").replace("-", "").encode()).hexdigest()

    if len(a) >= 2:
        await login_table.update(chat_id, {
            "status": "region",
            "_name": name_merged
        })
        return True


async def user_login_set_region(chat_id, region):
    if len(region) == 2 and region.isdigit():
        await login_table.update(chat_id, {
            "status": "passport",
            "region": int(region)
        })
        return True


async def user_login_set_passport(chat_id, passport):
    if 5 <= len(passport) <= 12 and " " not in passport:
        await login_table.update(chat_id, {
            "status": "captcha",
            "passport": passport
        })
        return True


async def user_login_check_captcha(chat_id, text):
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
        exams_db = set(region_info["exams"])
        exams.update(exams_db)
        await regions_table.update(region, {"region": region, "exams": exams})
    else:
        await regions_table.insert({"region": region, "exams": exams})


async def examsinfo_update(response):
    for exam in response:
        exam_id = exam["ExamId"]
        title = exam["Subject"]
        exam_date = exam["ExamDate"]

        if not await examsinfo_table.get(exam_id):
            await examsinfo_table.insert({
                "exam_id": exam_id,
                "title": title,
                "exam_date": datetime.strptime(exam_date, "%Y-%m-%d")
            })


def handle_captcha_delete(chat_id):
    try:
        os.remove("_captcha" + str(chat_id))
    except FileNotFoundError:
        return None


async def handle_captcha_get(chat_id):
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
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
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            response = await session.post(EGE_LOGIN_URL, data=params, timeout=10)

        if "Participant" in response.cookies:
            token = response.cookies["Participant"].value

            await users_table.insert({
                "chat_id": chat_id,
                "region": user["region"],
                "token": token,
                "notify": 1,
                "login_date": int(datetime.now().timestamp())
            })

            user_stats_hash = md5('{}{}'.format(chat_id, user["_name"]).encode()).hexdigest()
            try:
                await stats_table.insert({
                    "user_hash": user_stats_hash,
                    "first_login_time": int(datetime.now().timestamp()),
                    "region": user["region"]
                })
            except UniqueViolationError:
                pass

            await login_table.delete(chat_id)

            return 204, user_stats_hash
        else:
            return 450, ""
    except (aiohttp.ClientConnectionError, ATimeoutError):
        return 452, ""


async def pass_stats_exams_by_user_hash(user_hash, response):
    exams = set()
    for exam in response:
        exams.add(exam["ExamId"])

    await stats_table.update(user_hash, {"exams": exams})


async def handle_get_results_json(chat_id, attempts=5, from_auto_checker=False):
    if attempts == 0:
        return "Сервер ЕГЭ не ответил на запрос. Попробуйте получить результаты ещё раз.", None
    try:
        user = await users_table.get(chat_id)
        if user:
            token = user["token"]
            headers = EGE_HEADERS.copy()
            headers["Cookie"] += "Participant=" + token

            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
                response = await session.get(EGE_URL, headers=headers, timeout=5, proxy=proxy_url)
                if not response.ok:
                    return "Сервер ЕГЭ не ответил на запрос. Пожалуйста, попробуйте повторить запрос позже.", None
                json = await response.json()
            if not from_auto_checker:
                logger.debug("User: %d results got" % chat_id)

            return "", json["Result"]["Exams"]
        else:
            logger.warning("User: %d results UNSUCCESSFUL: unlogged" % chat_id)
            return "Возникла ошибка при авторизации. Пожалуйста, попробуйте войти заново с помощью /logout.", None
    except aiohttp.ClientConnectionError:
        logger.warning(str(chat_id) + " REQUESTS.PY Exc, attempt: %d" % attempts)
        return await handle_get_results_json(chat_id, attempts - 1)
    except (KeyError, JSONDecodeError):
        logger.warning(str(chat_id) + str(response.content) + " attempt: %d" % attempts)
        return await handle_get_results_json(chat_id, attempts - 1)
    except ATimeoutError:
        return await handle_get_results_json(chat_id, attempts - 1)


async def handle_get_results_json_token(token, attempts=5):
    if attempts == 0:
        return [1]
    try:
        headers = EGE_HEADERS.copy()
        headers["Cookie"] = "Participant=" + token
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            response = await session.get(EGE_URL, headers=headers, timeout=5, proxy=proxy_url)
            json = await response.json()
        return [0, json["Result"]["Exams"]]
    except aiohttp.ClientConnectionError:
        return await handle_get_results_json_token(token, attempts - 1)
    except (KeyError, JSONDecodeError):
        return await handle_get_results_json_token(token, attempts - 1)


# преобразование падежа слова "балл"
def count_case(mark, title=""):
    if "Математика базовая" in title:
        return ""
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
        # update hash (and exam list) in 'users.db'
        old_hash = user["exams_hash"]
        region = user["region"]

        new_hash = md5(str(response).encode()).hexdigest()
        exams = set()
        for exam in response:
            exams.add(exam["ExamId"])

        if old_hash != new_hash:  # результаты обновились
            if is_user_request:
                await users_table.update(chat_id, {
                    "exams": exams,
                    "exams_hash": new_hash
                })
                await on_results_updated(response, region, chat_id, callback_bot)
            else:
                await on_results_updated(response, region, 1, callback_bot)
            return True

    else:  # user logged out
        logger.warning("User: %d results after log out" % chat_id)


async def get_exam_result_date(exam_id):
    if exam_id in cached_exam_results_dates:
        return cached_exam_results_dates[exam_id]
    else:
        exam = await examsinfo_table.get(exam_id)
        if exam and exam["res_date_official"]:
            date = exam["res_date_official"]
            cached_exam_results_dates[exam_id] = "%d %s" % (date.day, months[date.month])
            return cached_exam_results_dates[exam_id]


async def parse_results_message(response, updates, is_first=False):
    mark_sum = 0
    show_sum = True

    message = ""

    if is_first:
        message += "*Текущие результаты:* \n\n"
    elif updates:
        message += "*⚡️Есть обновления⚡️*\n\n"
    else:
        message += "*Текущие результаты:* обновлений нет \n\n"

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
                mark_string = "*" + str(mark) + count_case(mark, title) + check_threshold(mark, mark_threshold,
                                                                                          title) + "*"
                mark_sum += int(mark)
        elif int(mark):
            mark_string = "*" + str(mark) + count_case(mark, title) + check_threshold(mark,
                                                                                      mark_threshold,
                                                                                      title) + "* _(результат скрыт)_"
            show_sum = False
        else:
            result_date = await get_exam_result_date(exam["ExamId"])
            mark_string = "_ожидаются до %s_" % result_date if result_date else "_нет результата_"
            show_sum = False

        message += title + " — " + mark_string + "\n"

    if show_sum:
        message += "\n_Сумма по всем предметам_ — *" + str(mark_sum) + count_case(mark_sum) + "*"

    return message


async def on_results_updated(response, region, except_from_id=1, callback_bot=None):
    for exam in response:
        title = exam["Subject"]
        exam_id = exam["ExamId"]
        date = exam["ExamDate"]
        is_composition = exam["IsComposition"]
        is_hidden = exam["IsHidden"]
        has_result = exam["HasResult"]
        mark = exam["TestMark"]

        ignored_exams = set()

        if int(mark):  # есть ли результат
            if exam_id not in ignored_exams and not is_composition:  # проверка на thrown/composition
                region_info = await regions_table.get(region)
                if region_info:
                    region_notified_exams = set(region_info["notified_exams"])
                    if exam_id not in region_notified_exams:  # проверка на существующее оповещение
                        region_notified_exams.add(exam_id)
                        await regions_table.update(region, {"notified_exams": region_notified_exams})

                        logger.warning("MAIL REGION: %d EXAM: %d %s %s" % (region, exam_id, title, date))

                        mailer = Mailer(region=region,
                                        title=title,
                                        exam_id=exam_id,
                                        bot=callback_bot,
                                        except_from_id=except_from_id)
                        mailer.run()
