import os

API_TOKEN = os.environ.get("TG_API_TOKEN")
NOTIFY_TIME = 0
VERSION_BUILD = "3.0.0_04062022_2322"

relax_timer = 5
relax_mailer = 0.2
relax_retry_error = 10
relax_checker = 0.2

admin_id = os.environ.get("ADMIN_CHAT_ID")

db_url = os.environ.get("DATABASE_URL")

db_table_users = "users"
db_table_login = "login"
db_table_regions = "regions"
db_table_examsinfo = "exams_info"
db_table_stats = "stats"

EGE_URL = "https://checkege.rustest.ru/api/exam"
EGE_TOKEN_URL = "https://checkege.rustest.ru/api/captcha"
EGE_LOGIN_URL = "https://checkege.rustest.ru/api/participant/login"

EGE_HEADERS = {"Cookie":'', "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 Safari/537.36"}

proxy_url = os.environ.get("PROXY_URL")