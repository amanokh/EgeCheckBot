import asyncio
import logging
import os

import asyncpg

import config
import utils
from datetime import datetime

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOGLEVEL", logging.DEBUG))


async def select_random_users_by_region_and_exam(conn, region, exam_id, num_of_users=2):
    user_ids = set()
    users_fetched = await conn.fetch(
        "select * from %s where $1 = any(exams) and region = $2 order by random()" % config.db_table_users,
        exam_id,
        region)

    amount_of_users = 0
    for user in users_fetched:
        if amount_of_users < num_of_users:
            user_ids.add(user["chat_id"])
            amount_of_users += 1
        else:
            break

    return user_ids


async def select_random_users_by_exams(conn, exams):
    user_ids = set()
    region_rows = await conn.fetch("select * from %s" % config.db_table_regions)

    for exam_id in exams:
        fetched_regions_count = 0
        notified_regions_count = 0

        for region_row in region_rows:
            region = region_row["region"]
            region_exams = region_row["exams"]
            region_notified_exams = region_row["notified_exams"]

            if exam_id in region_exams and exam_id not in region_notified_exams:
                users_fetched = await select_random_users_by_region_and_exam(conn, region, exam_id)
                if users_fetched:
                    user_ids.update(users_fetched)
                    fetched_regions_count += 1
            elif exam_id in region_notified_exams:
                notified_regions_count += 1

        logger.info("Checker regeneration: exam_id: %d, fetched regions count: %d, notified regions: %d",
                    exam_id, fetched_regions_count, notified_regions_count)

    return user_ids


async def select_near_exams(conn):
    exams_rows = await conn.fetch(
        "select * from %s where exam_date > current_date - 30 and (exam_date <= current_date - 7 or res_date_official <= current_date + 7)" % config.db_table_examsinfo)

    exams = [exam["exam_id"] for exam in exams_rows]

    logger.info("Will check %d exams:", len(exams))
    for exam in exams_rows:
        logger.info("%d %s", exam["exam_id"], exam["title"])

    return exams


async def check_thread_runner(bot):
    logger.info("Checker: started")
    samples_age = datetime.now().timestamp()
    samples_need_to_regenerate = False

    db_conn = await asyncpg.connect(dsn=config.db_url)

    exams = await select_near_exams(db_conn)
    users_samples = await select_random_users_by_exams(db_conn, exams)

    while True:
        if exams:
            time_loop = datetime.now().timestamp()
            try:
                for user_id in users_samples:
                    if await utils.user_check_logged(user_id):
                        e, response = await utils.handle_get_results_json(user_id, from_auto_checker=True)
                        await asyncio.sleep(config.relax_checker)

                        if response:
                            await utils.check_results_updates(user_id, response, callback_bot=bot,
                                                              is_user_request=False)
                    else:
                        samples_need_to_regenerate = True
            except:
                logger.warning("Checker: an unexpected error happened")

            time_stop = datetime.now().timestamp()
            logger.info("Checker: loop time %f secs", time_stop - time_loop)

            if datetime.now().timestamp() - samples_age > 600 or samples_need_to_regenerate:
                samples_age = datetime.now().timestamp()
                users_samples = await select_random_users_by_exams(db_conn, exams)

        else:
            logger.warning("Checker: exams list is empty, waiting for 2 hours...")
            await asyncio.sleep(60 * 60 * 2)
