from apscheduler.schedulers.blocking import BlockingScheduler
from app import db, slack
from blocks import get_base_blocks, get_match_blocks, get_evaluation_blocks, get_invitation_blocks
from models import User, Match, user_identifier, Evaluation, Activity
from random import sample
import json
from datetime import datetime, timedelta
from pytz import timezone, utc


def create_evaluations_for(match):
    evaluations = []
    for i, user in enumerate(match.users):
        if i == 0:
            mate = match.users[1]
        else:
            mate = match.users[0]
        evaluation = Evaluation(match, user, mate)
        evaluations.append(evaluation)
    return evaluations


def create_evaluations(matches):
    total_evaluations = []
    for match in matches:
        evaluations = create_evaluations_for(match=match)
        total_evaluations += evaluations
    return total_evaluations


def is_match_enable_day(unmatched_users):
    if unmatched_users and len(unmatched_users) >= 2:
        return True
    return False


def get_matched_group(unmatched_users):
    user = unmatched_users[0]
    unmatched_users.remove(user)
    for i in range(len(unmatched_users)):
        mate = sample(unmatched_users, 1)[0]
        match_history = Evaluation.query.filter_by(user=user, mate=mate).first()
        if not match_history or (i == len(unmatched_users) - 1):
            unmatched_users.remove(mate)
            matched_group = [user, mate]
            return matched_group


def get_matched_groups(unmatched_users):
    count_unmatched_users = len(unmatched_users)
    matched_groups = []
    while count_unmatched_users >= 2:
        matched_groups += [get_matched_group(unmatched_users)]
        count_unmatched_users -= 2
    return matched_groups


def create_match(matched_group, activities):
    activity = sample(activities, 1)[0]
    match = Match(
        user1=matched_group[0],
        user2=matched_group[1],
        activity=activity
    )
    return match


def create_matches_of(matched_groups):
    matches = []
    activities = Activity.query.all()
    for matched_group in matched_groups:
        matches += [create_match(matched_group, activities)]
    return matches


def update_user_field(unmatched_users):
    for user in unmatched_users:
        user.joined = False
        user.match_count += 1


def let_matched_users_meet(matches):
    print("MATCH_SUCCESSED_HANDLING")
    for match in matches:
        slack_id = [match.users[0].slack_id, match.users[1].slack_id]
        print("_SLACK_ID: " + str(slack_id[0]) + " & " + str(slack_id[1]))
        response = slack.conversations.open(users=slack_id, return_im=True)
        channel = response.body['channel']['id']
        blocks = get_match_blocks(match)
        slack.chat.post_message(channel=channel, blocks=json.dumps(blocks))


def send_match_fail_message(unmatched_user):
    print("MATCH_FAILED_HANDLING")
    slack_id = unmatched_user.slack_id
    print("_SLACK_ID: " + str(slack_id))
    intra_id = unmatched_user.intra_id
    response = slack.conversations.open(users=slack_id, return_im=True)
    channel = response.body['channel']['id']
    blocks = get_base_blocks("앗, 이를 어쩌죠? 오늘은 *" + intra_id + "* 님과 만날 메이트가 없네요:thinking_face:\n"
                             + "42메이트를 주변에 알려주시면 메이트를 만날 확률이 올라가요!:thumbsup_all:")
    slack.chat.post_message(channel=channel, blocks=json.dumps(blocks))


def make_match_and_evaluation_schedule():
    print("MAKE_MATCH_AND_EVALUATION_SCHEDULE_START")
    unmatched_users = db.session.query(User).filter_by(joined=True).order_by('match_count').all()
    update_user_field(unmatched_users)
    if is_match_enable_day(unmatched_users):
        matched_groups = get_matched_groups(unmatched_users)
        matches = create_matches_of(matched_groups=matched_groups)
        let_matched_users_meet(matches)
        db.session.add_all(matches)
        evaluations = create_evaluations(matches)
        db.session.add_all(evaluations)
    if unmatched_users:
        send_match_fail_message(unmatched_users[0])
        unmatched_users[0].match_count -= 1
    print("MATCH_MAKE_SCHEDULE_ADD_AND_COMMIT_START")
    db.session.commit()
    print("MATCH_MAKE_SCHEDULE_END")


def get_today_start_dt():
    now_dt_kst = datetime.now(timezone('Asia/Seoul'))
    today_start_dt_kst = now_dt_kst.replace(hour=00, minute=00, second=00)
    today_start_dt_utc = today_start_dt_kst.astimezone(utc)
    return today_start_dt_utc


def get_target_matches():
    today_start_dt = get_today_start_dt()
    yesterday_start_dt = today_start_dt - timedelta(days=1)
    target_matches = db.session.query(Match).filter(Match.match_day >= yesterday_start_dt,
                                             Match.match_day < today_start_dt).all()
    return target_matches


def send_evaluation_message(evaluation):
    blocks = get_evaluation_blocks(evaluation)
    slack_id = evaluation.user.slack_id
    response = slack.conversations.open(users=slack_id, return_im=True)
    channel = response.body['channel']['id']
    slack.chat.post_message(channel=channel, blocks=json.dumps(blocks))


def send_evaluation_schedule():
    target_matches = get_target_matches()
    if target_matches is None:
        return
    for match in target_matches:
        for evaluation in match.evaluations:
            send_evaluation_message(evaluation)
            evaluation.send_time = datetime.now(utc)
    db.session.commit()


def send_join_invitation_schedule():
    blocks = get_invitation_blocks()
    unjoined_users = db.session.query(User).filter(User.register == True, User.joined == False).all()
    for user in unjoined_users:
        slack_id = user.slack_id
        response = slack.conversations.open(users=slack_id, return_im=True)
        channel = response.body['channel']['id']
        slack.chat.post_message(channel=channel, blocks=json.dumps(blocks))


if __name__ == "__main__":
    # make_match_and_evaluation_schedule()
    send_evaluation_schedule()
    # send_join_invitation_schedule()
    # sched = BlockingScheduler()
    # sched.add_job(send_evaluation_schedule, 'cron', hour=1)
    # sched.add_job(send_join_invitation_schedule, 'cron', hour=9)
    # sched.add_job(match_make_schedule, 'cron', hour=15, minute=1)
    # sched.start()