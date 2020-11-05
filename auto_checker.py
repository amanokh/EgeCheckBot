import ast
import asyncio
import logging
import utils
from datetime import datetime


# deprecated-реализация из прошлых версий! (на вход подаётся список id экзаменов к отслеживанию):
async def check_thread_runner(exam_id, bot):
    logging.log(logging.INFO, "Checker: started")
    while exam_id:
        for exam in exam_id:
            time = datetime.now().timestamp()
            regions = set()
            for user in utils.users_table.rows_where("exams IS NOT NULL"):
                try:
                    chat_id = user["chat_id"]
                    user_exams = ast.literal_eval(user["exams"])
                    user_region = user["region"]

                    if user_region not in regions and exam in user_exams and utils.user_check_logged(chat_id):
                        response = await utils.handle_get_results_json(chat_id, logs=False)
                        await asyncio.sleep(0.5)

                        if not response[0] and len(response[1]):
                            regions.add(user_region)
                            utils.check_results_updates(chat_id, response[1], callback_bot=bot, is_user_request=False)
                except:
                    pass
            time_stop = datetime.now().timestamp()
            logging.log(logging.INFO,
                        "Checker: loop with %d regions, exam %d, time %f" % (len(regions), exam, time_stop - time))

