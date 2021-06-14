import os
import logging
import base64
import pytz
import ast
import sys
import asyncio
import shelve
import requests_async as requests

from datetime import datetime
from hashlib import md5
from config import db_users_filename, db_table_login, db_table_users, EGE_URL, EGE_HEADERS, EGE_TOKEN_URL, \
    EGE_LOGIN_URL, \
    db_regions_filename, db_table_regions, db_examsinfo_filename, db_table_examsinfo
from sqlite_utils import Database
from sqlite_utils.db import NotFoundError
from json.decoder import JSONDecodeError
from aiogram import types, exceptions

db_users = Database(db_users_filename)
users_table = db_users.table(db_table_users)
login_table = db_users.table(db_table_login)

db_regions = Database(db_regions_filename)
regions_table = db_regions.table(db_table_regions)

db_examsinfo = Database(db_examsinfo_filename)
examsinfo_table = db_examsinfo.table(db_table_examsinfo)


def db_init():
    if not users_table.exists():
        users_table.create({
            "chat_id": int,
            "region": int,
            "notify": int,
            "token": str,
            "login_date": int,
            "exams": str,
            "exams_hash": str,
            "exams_date": int
        }, pk="chat_id", not_null={"region", "token", "notify"}, defaults={"notify": 1})
        logging.log(logging.WARNING, "Users.db->users was created")
    if not login_table.exists():
        login_table.create({
            "chat_id": int,
            "status": str,
            "name": str,
            "region": int,
            "passport": str,
            "captcha_token": str,
            "captcha_answer": str
        }, pk="chat_id", not_null={"status"})
        logging.log(logging.WARNING, "Users.db->login was created")

    if not regions_table.exists():
        regions_table.create({
            "region": int,
            "exams": str,
            "notified_exams": str
        }, pk="region", defaults={"exams": "[]", "notified_exams": "[]"})
        logging.log(logging.WARNING, "Regions.db->regions was created")
    if not examsinfo_table.exists():
        examsinfo_table.create({
            "exam_id": int,
            "title": str,
            "exam_date": str,
            "res_date_official": str,
            "res_date_predicted": str
        }, pk="exam_id", not_null={"title", "exam_date"})
        logging.log(logging.WARNING, "Exams_info.db->exams_info was created")


def table_count():
    try:
        users_count = users_table.count
        login_count = login_table.count

        exams_count = examsinfo_table.count

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


def user_check_logged(chat_id):
    try:
        users_table.get(chat_id)
        return True
    except NotFoundError:
        return False


def user_get_login_status(chat_id):
    try:
        if user_check_logged(chat_id):
            return "logged"
        else:
            return login_table.get(chat_id)["status"]
    except NotFoundError:
        return None


def user_get_notify_status(chat_id):
    try:
        if user_check_logged(chat_id):
            return users_table.get(chat_id)["notify"]
    except NotFoundError:
        return None


def user_clear(chat_id):
    try:
        users_table.delete(chat_id)
        return True
    except NotFoundError:
        return False


def user_login_stop(chat_id):
    try:
        login_table.delete(chat_id)
        return True
    except NotFoundError:
        return False


def user_login_start(chat_id):
    user_clear(chat_id)
    user_login_stop(chat_id)

    login_table.insert({
        "chat_id": chat_id,
        "status": "name"
    })


def user_login_setName(chat_id, name):
    a = name.split(" ")
    name_merged = md5(''.join(a).lower().replace("ё", "е").replace("й", "и").replace("-", "").encode()).hexdigest()

    if len(a) >= 2:
        login_table.update(chat_id, {
            "status": "region",
            "name": name_merged
        })
        return True
    else:
        return False


def user_login_setRegion(chat_id, region):
    if len(region) == 2 and region.isdigit():
        login_table.update(chat_id, {
            "status": "passport",
            "region": int(region)
        })
        return True
    else:
        return False


def user_login_setPassport(chat_id, passport):
    if 5 <= len(passport) <= 12:
        login_table.update(chat_id, {
            "status": "captcha",
            "passport": passport
        })
        return True
    else:
        return False


def user_login_checkCaptcha(chat_id, text):
    if len(text) == 6 and text.isdigit():
        login_table.update(chat_id, {
            "status": "login",
            "captcha_answer": text
        })
        return True
    else:
        return False


def user_get_token(chat_id):
    try:
        return users_table.get(chat_id)["token"]
    except NotFoundError:
        return None


def user_get_region(chat_id):
    try:
        return users_table.get(chat_id)["region"]
    except NotFoundError:
        return None


def regions_update_exams(region, response):
    try:
        exams = set(ast.literal_eval(regions_table.get(region)["exams"]))
    except NotFoundError:
        exams = set()

    for exam in response:
        exams.add(exam["ExamId"])

    regions_table.upsert({"region": region, "exams": str(list(exams))}, pk="region")


def examsinfo_update(response):
    for exam in response:
        exam_id = exam["ExamId"]
        title = exam["Subject"]
        exam_date = exam["ExamDate"]

        try:
            examsinfo_table.get(exam_id)
        except NotFoundError:
            examsinfo_table.insert({
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
        response = await requests.get(EGE_TOKEN_URL, timeout=5)
        login_table.update(chat_id, {
            "captcha_token": response.json()["Token"]
        })
        with open("_captcha" + str(chat_id), "wb") as f:
            f.write(base64.b64decode(response.json()["Image"]))
        return response.json()
    except (requests.RequestException, AttributeError):
        return None
    except:
        return None


async def handle_login(chat_id):
    try:
        user = login_table.get(chat_id)
        if 5 <= len(user["passport"]) < 12:
            params = {
                "Hash": user["name"],
                "Document": user["passport"].rjust(12, '0'),
                "Region": user["region"],
                "Captcha": user["captcha_answer"],
                "Token": user["captcha_token"]
            }
        else:
            params = {
                "Hash": user["name"],
                "Code": user["passport"],
                "Region": user["region"],
                "Captcha": user["captcha_answer"],
                "Token": user["captcha_token"]
            }
        session = requests.Session()
        response = await session.post(EGE_LOGIN_URL, data=params, timeout=10)
        token = session.cookies.get_dict()["Participant"]

        users_table.insert({
            "chat_id": chat_id,
            "region": user["region"],
            "token": token,
            "notify": 1,
            "exams": "[]",
            "login_date": int(datetime.now().timestamp())
        })

        login_table.delete(chat_id)
        return 204
    except KeyError:
        return 450
    except NotFoundError:
        return 451
    except requests.RequestException:
        return 452


async def handle_get_results_json(chat_id, attempts=5, logs=True):
    if attempts == 0:
        return ["Сервер ЕГЭ не ответил на запрос. Попробуйте получить результаты ещё раз."]
    try:
        date = users_table.get(chat_id)["exams_date"]
        if not date or datetime.now().timestamp() - date > 10:
            token = users_table.get(chat_id)["token"]
            headers = EGE_HEADERS.copy()
            headers["Cookie"] = "Participant=" + token
            response = await requests.get(EGE_URL, headers=headers, timeout=5)
            users_table.update(chat_id, {"exams_date": int(datetime.now().timestamp())})
            if logs:
                logging.log(logging.INFO, "User: %d results got" % chat_id)
                with open('log_res_activity.txt', 'a') as logfile:
                    logfile.write("%d\n" % chat_id)

            return [0, response.json()["Result"]["Exams"]]
        else:
            return [1, ""]
    except NotFoundError:
        logging.log(logging.WARNING, "User: %d results UNSUCCESSFUL: unlogged" % chat_id)
        return ["Возникла ошибка при авторизации. Пожалуйста, попробуйте войти заново с помощью /logout."]
    except requests.RequestException:
        logging.log(logging.WARNING, str(chat_id) + " REQUESTS.PY Exc, attempt: %d" % attempts)
        return await handle_get_results_json(chat_id, attempts - 1)
    except (KeyError, JSONDecodeError):
        logging.log(logging.WARNING, str(chat_id) + str(response.content) + " attempt: %d" % attempts)
        return await handle_get_results_json(chat_id, attempts - 1)


async def handle_get_results_json_token(token, attempts=5):
    if attempts == 0:
        return [1]
    try:
        headers = EGE_HEADERS.copy()
        headers["Cookie"] = "Participant=" + token
        response = await requests.get(EGE_URL, headers=headers, timeout=5)
        return [0, response.json()["Result"]["Exams"]]
    except requests.RequestException:
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
def check_results_updates(chat_id, response, callback_bot=None, is_user_request=True):
    try:
        # update hash (and exams list) in 'users.db'
        user = users_table.get(chat_id)
        old_hash = user["exams_hash"]
        region = user["region"]

        new_hash = md5(str(response).encode()).hexdigest()
        exams = set()
        for exam in response:
            exams.add(exam["ExamId"])

        if old_hash != new_hash:  # результаты обновились
            if is_user_request:
                users_table.update(chat_id, {
                    "exams": str(list(exams)),
                    "exams_hash": new_hash,
                    "exams_date": int(datetime.now().timestamp())
                })
                on_results_updated(response, region, chat_id, callback_bot)
            else:
                on_results_updated(response, region, 1, callback_bot)
            return True
        else:
            return False

    except NotFoundError:  # user logged out
        logging.log(logging.WARNING, "User: %d results after log out" % chat_id)
        return False


def on_results_updated(response, region, except_from_id=1, callback_bot=None):
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
                region_exams = set(ast.literal_eval(regions_table.get(region)["notified_exams"]))
                if exam_id not in region_exams:  # проверка на существующее оповещение
                    region_exams.add(exam_id)
                    regions_table.update(region, {"notified_exams": str(list(region_exams))})

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

    for user in users_table.rows_where("region = ? AND notify = 1", [region]):
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


def parse_results_message(chat_id, response, is_first=False, callback_bot=None):
    time = datetime.now(pytz.timezone('Europe/Moscow')).strftime("%H:%M")

    updates = check_results_updates(chat_id, response, callback_bot)

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
