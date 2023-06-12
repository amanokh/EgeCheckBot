from aiogram import types


# ReplyKeyboardMarkup mockups:
def markup_logged():
    markup_btn_update = types.KeyboardButton("Получить результаты 🔄")
    markup_btn_logout = types.KeyboardButton("Выйти ❌")
    markup_btn_help = types.KeyboardButton("Помощь ℹ️")
    markup_btn_timetable = types.KeyboardButton("Даты 🗓")
    markup_btn_donate = types.KeyboardButton("Поддержать автора 💗")

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add(
        markup_btn_update).add(markup_btn_help, markup_btn_timetable, markup_btn_logout).add(markup_btn_donate)

    return markup


def markup_login():
    markup_btn_login = types.KeyboardButton("Начать заново")
    markup_btn_help = types.KeyboardButton("Помощь ℹ️")
    markup_btn_timetable = types.KeyboardButton("Даты 🗓")

    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True
                                       ).add(markup_btn_login).add(
        markup_btn_help, markup_btn_timetable)
    return markup


def markup_init():
    markup_btn_login = types.KeyboardButton("Авторизоваться ➡️")
    markup_btn_help = types.KeyboardButton("Помощь ℹ️")
    markup_btn_timetable = types.KeyboardButton("Даты 🗓")

    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True).add(markup_btn_login).add(
        markup_btn_help, markup_btn_timetable)
    return markup


def markup_closed():
    markup_btn_login = types.KeyboardButton("Написать автору ✏️")
    markup_btn_donate = types.KeyboardButton("Поддержать автора 💗")

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add(markup_btn_login).add(markup_btn_donate)
    return markup


def markup_inline_regions():
    markup_button = types.InlineKeyboardButton("Показать список регионов", callback_data="regions_btn_show")
    markup = types.InlineKeyboardMarkup().add(markup_button)
    return markup


def markup_inline_results():
    markup_button = types.InlineKeyboardButton("Обновить результаты", callback_data="results_update")
    return types.InlineKeyboardMarkup().add(markup_button)


def markup_inline_donate():
    markup_button1 = types.InlineKeyboardButton("Отправить донейт",
                                                url="https://manokh.com/donate")
    markup = types.InlineKeyboardMarkup().add(markup_button1)
    return markup


def markup_inline_retry_login():
    markup_button1 = types.InlineKeyboardButton("Повторить попытку", callback_data="login_retry")
    markup_button2 = types.InlineKeyboardButton("Исправить данные", callback_data="start_over")
    markup = types.InlineKeyboardMarkup().add(markup_button1).add(markup_button2)
    return markup


def markup_inline_retry_captcha():
    markup_button1 = types.InlineKeyboardButton("Запросить новую капчу", callback_data="captcha_retry")
    markup = types.InlineKeyboardMarkup().add(markup_button1)
    return markup
