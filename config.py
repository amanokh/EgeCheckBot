API_TOKEN = open("token.txt", "r").read() # put your Telegram Bot API token here
NOTIFY_TIME = 0
VERSION_BUILD = "1.9.1_20210609_1520"

db_users_filename = "users.db"
db_regions_filename = "regions.db"
db_examsinfo_filename = "exams_info.db"

db_table_users = "users"
db_table_login = "login"
db_table_regions = "regions"
db_table_examsinfo = "exams_info"

EGE_URL = "http://check.ege.edu.ru/api/exam"
EGE_TOKEN_URL = "http://check.ege.edu.ru/api/captcha"
EGE_LOGIN_URL = "http://check.ege.edu.ru/api/participant/login"

EGE_HEADERS = {"Cookie":'', "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 Safari/537.36"}
