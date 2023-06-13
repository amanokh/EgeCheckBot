import os

API_TOKEN = os.environ.get("TG_API_TOKEN")
NOTIFY_TIME = 0
VERSION_BUILD = "3.2.1_13062023"

relax_timer = 5
relax_mailer = 0.2
relax_retry_error = 10
relax_checker = 0.2

admin_ids = list(os.environ.get("ADMIN_CHAT_IDS").split(","))
db_url = os.environ.get("DATABASE_URL")

db_table_users = "users"
db_table_login = "login"
db_table_regions = "regions"
db_table_examsinfo = "exams_info"
db_table_stats = "stats"

EGE_URL = "https://checkege.rustest.ru/api/exam"
EGE_TOKEN_URL = "https://checkege.rustest.ru/api/captcha"
EGE_LOGIN_URL = "https://checkege.rustest.ru/api/participant/login"

EGE_HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'ru,ru-RU;q=0.9,en;q=0.8,sr;q=0.7',
    'Connection': 'keep-alive',
    'Cookie': '',
    'DNT': '1',
    'Referer': 'https://checkege.rustest.ru/exams',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 8.1.0; Redmi 5 Build/OPM1.171019.026; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/111.0.5563.116 YaBrowser/22.8.0.223 (lite) Mobile Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest'
}

proxy_url = os.environ.get("PROXY_URL")
environment_id = os.environ.get("ENVIRONMENT_UID")
