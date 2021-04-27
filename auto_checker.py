import ast
import asyncio
import logging
import utils
from datetime import datetime


def users_sampleSelections_generator(exams, num_of_users=2):
    samples_list = []

    for exam_id in exams:
        users_sampleSelection = {}

        for region in utils.regions_table.rows:
            users_ids = []
            region_id = region["region"]
            users_init_table = utils.db_users.execute_returning_dicts(f"SELECT * FROM users WHERE exams IS NOT NULL AND region={region_id} ORDER BY RANDOM()")

            sampled_users_counter = 0

            for user in users_init_table:
                user_exams = ast.literal_eval(user["exams"])
                if exam_id in user_exams and utils.user_check_logged(user["chat_id"]):
                    users_ids.append(user["chat_id"])
                    sampled_users_counter += 1

                if sampled_users_counter >= num_of_users:
                    break

            users_sampleSelection[region_id] = users_ids
        samples_list.append(users_sampleSelection)

    return samples_list


async def check_thread_runner(exams, bot):
    logging.log(logging.INFO, "Checker: started")
    samples_age = datetime.now().timestamp()
    samples_need_to_regenarate = False

    samples_list = users_sampleSelections_generator(exams)

    while exams:
        time_loop = datetime.now().timestamp()
        try:
            for sampleSelection in samples_list:
                for region in sampleSelection:
                    for user_id in sampleSelection[region]:
                        if utils.user_check_logged(user_id):
                            response = await utils.handle_get_results_json(user_id, logs=False)
                            await asyncio.sleep(0.5)

                            if not response[0] and len(response[1]):
                                utils.check_results_updates(user_id, response[1], callback_bot=bot,
                                                            is_user_request=False)
                        else:
                            samples_need_to_regenarate = True

            time_stop = datetime.now().timestamp()
            logging.log(logging.INFO,
                        "Checker: loop with %d regions, time %f" % (len(samples_list), time_stop - time_loop))

            if datetime.now().timestamp() - samples_age > 600 or samples_need_to_regenarate:
                samples_age = datetime.now().timestamp()
                samples_list = users_sampleSelections_generator(exams)
        except:
            logging.log(logging.WARNING, "Checker: an unexpected error happen")


async def auto_checker(bot):
    logging.log(logging.INFO, "Checker v2: started")
