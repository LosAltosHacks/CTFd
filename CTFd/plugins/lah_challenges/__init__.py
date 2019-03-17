from __future__ import division  # Use floating point for math calculations
from CTFd.plugins.challenges import BaseChallenge, CHALLENGE_CLASSES
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.flags import get_flag_class
from CTFd.models import db, Solves, Fails, Flags, Challenges, ChallengeFiles, Tags, Teams, Hints
from CTFd import utils
from CTFd.utils.migrations import upgrade
from CTFd.utils.user import get_ip
from CTFd.utils.uploads import upload_file, delete_file
from CTFd.utils.modes import get_model
from flask import Blueprint

from CTFd.utils.dates import ctftime
from sqlalchemy import func
import logging
import datetime
import time
from random import randrange
import atexit
from apscheduler.schedulers.background import BackgroundScheduler

class LahChallengeClass(BaseChallenge):
    id = "lah"  # Unique identifier used to register challenges
    name = "lah unlocking"  # Name of a challenge type
    templates = {  # Handlebars templates used for each aspect of challenge editing & viewing
        'create': '/plugins/lah_challenges/assets/create.html',
        'update': '/plugins/lah_challenges/assets/update.html',
        'view': '/plugins/lah_challenges/assets/view.html',
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        'create': '/plugins/lah_challenges/assets/create.js',
        'update': '/plugins/lah_challenges/assets/update.js',
        'view': '/plugins/lah_challenges/assets/view.js',
    }
    # Route at which files are accessible. This must be registered using register_plugin_assets_directory()
    route = '/plugins/lah_challenges/assets/'
    # Blueprint used to access the static_folder directory.
    blueprint = Blueprint('lah_challenges', __name__, template_folder='templates', static_folder='assets')

    @staticmethod
    def create(request):
        """
        This method is used to process the challenge creation request.

        :param request:
        :return:
        """
        data = request.form or request.get_json()
        challenge = LahChallenge(**data)

        db.session.add(challenge)
        db.session.commit()

        return challenge

    @staticmethod
    def read(challenge):
        """
        This method is in used to access the data of a challenge in a format processable by the front end.

        :param challenge:
        :return: Challenge object, data dictionary to be returned to the user
        """
        challenge = LahChallenge.query.filter_by(id=challenge.id).first()
        data = {
            'id': challenge.id,
            'name': challenge.name,
            'value': challenge.value,
            'unlock_order': challenge.unlock_order,
            'is_unlocked': challenge.is_unlocked,
            'description': challenge.description,
            'category': challenge.category,
            'state': challenge.state,
            'max_attempts': challenge.max_attempts,
            'type': challenge.type,
            'type_data': {
                'id': LahChallengeClass.id,
                'name': LahChallengeClass.name,
                'templates': LahChallengeClass.templates,
                'scripts': LahChallengeClass.scripts,
            }
        }
        return data

    @staticmethod
    def update(challenge, request):
        """
        This method is used to update the information associated with a challenge. This should be kept strictly to the
        Challenges table and any child tables.

        :param challenge:
        :param request:
        :return:
        """
        data = request.form or request.get_json()
        do_lock = challenge.unlock_order == 0 and int(data['unlock_order']) > 0
        for attr, value in data.items():
            setattr(challenge, attr, value)

        if do_lock:
            challenge.is_unlocked = False
        # for some reason challenge.unlock_order doesn't work here
        if int(data['unlock_order']) <= 0:
            challenge.is_unlocked = True
        db.session.commit()
        return challenge

    @staticmethod
    def delete(challenge):
        """
        This method is used to delete the resources used by a challenge.

        :param challenge:
        :return:
        """
        Fails.query.filter_by(challenge_id=challenge.id).delete()
        Solves.query.filter_by(challenge_id=challenge.id).delete()
        Flags.query.filter_by(challenge_id=challenge.id).delete()
        files = ChallengeFiles.query.filter_by(challenge_id=challenge.id).all()
        for f in files:
            delete_file(f.id)
        ChallengeFiles.query.filter_by(challenge_id=challenge.id).delete()
        Tags.query.filter_by(challenge_id=challenge.id).delete()
        Hints.query.filter_by(challenge_id=challenge.id).delete()
        LahChallenge.query.filter_by(id=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()
        db.session.commit()

    @staticmethod
    def attempt(challenge, request):
        """
        This method is used to check whether a given input is right or wrong. It does not make any changes and should
        return a boolean for correctness and a string to be shown to the user. It is also in charge of parsing the
        user's input from the request itself.

        :param challenge: The Challenge object from the database
        :param request: The request the user submitted
        :return: (boolean, string)
        """
        chal = LahChallenge.query.filter_by(id=challenge.id).first()
        if not chal.is_unlocked:
            return False, 'Not unlocked yet'
        data = request.form or request.get_json()
        submission = data['submission'].strip()
        flags = Flags.query.filter_by(challenge_id=challenge.id).all()
        for flag in flags:
            if get_flag_class(flag.type).compare(flag, submission):
                return True, 'Correct'
        return False, 'Incorrect'

    @staticmethod
    def solve(user, team, challenge, request):
        """
        This method is used to insert Solves into the database in order to mark a challenge as solved.

        :param team: The Team object from the database
        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """
        chal = LahChallenge.query.filter_by(id=challenge.id).first()
        if not chal.is_unlocked:
            raise RuntimeError("Attempted to solve a locked lah challenge.")
        data = request.form or request.get_json()
        submission = data['submission'].strip()
        solve = Solves(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(req=request),
            provided=submission
        )
        db.session.add(solve)
        db.session.commit()
        db.session.close()

    @staticmethod
    def fail(user, team, challenge, request):
        """
        This method is used to insert Fails into the database in order to mark an answer incorrect.

        :param team: The Team object from the database
        :param challenge: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """
        data = request.form or request.get_json()
        submission = data['submission'].strip()
        wrong = Fails(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(request),
            provided=submission
        )
        db.session.add(wrong)
        db.session.commit()
        db.session.close()


class LahChallenge(Challenges):
    __mapper_args__ = {'polymorphic_identity': 'lah'}
    id = db.Column(None, db.ForeignKey('challenges.id'), primary_key=True)
    unlock_order = db.Column(db.Integer, default=99)
    is_unlocked = db.Column(db.Boolean, default=False)

    def __init__(self, *args, **kwargs):
        super(LahChallenge, self).__init__(**kwargs)
        self.is_unlocked = int(kwargs['unlock_order']) == 0


RAND_UNLOCK_MINUTES = [i for i in range(0, 60, 2)]
RAND_UNLOCK_QUESTIONS = 1



def log(logger, format, **kwargs):
    logger = logging.getLogger(logger)
    props = {
        'date': time.strftime("%m/%d/%Y %X"),
    }
    props.update(kwargs)
    msg = format.format(**props)
    print(msg)
    logger.info(msg)

APP_REF = None

def rand_unlock_callback():
    with APP_REF.app_context():
        if not ctftime():
            log('lah', "[{date}] unlocking did not run because ctf has not started")
            return
        if datetime.datetime.now().minute not in RAND_UNLOCK_MINUTES:
            log('lah', "[{date}] unlocking did not run because minute is not aligned")
            return
        for i in range(RAND_UNLOCK_QUESTIONS):
            # Unlock one random question, that is visible, not unlocked, and of the lowest available unlock_order
            min_order = db.session.query(
                            func.min(LahChallenge.unlock_order).label("min_order"),
                            func.count().label("count")
                        ).filter(
                            LahChallenge.state == "visible",
                            LahChallenge.is_unlocked == False,
                            LahChallenge.unlock_order > 0,
                        ).one()
            count = min_order.count
            order = min_order.min_order
            if not min_order or count == 0:
                log('lah', "[{date}] unlocking finished early because no locked challenges were found.")
                return
            rand_offset = randrange(count)
            challenge = LahChallenge.query.filter_by(unlock_order=order, is_unlocked=False, state="visible").order_by(LahChallenge.id).offset(rand_offset).first()
            if not challenge:
                log('lah', "[{date}] encountered invalid state: randomly selected challenge was None.")
            challenge.is_unlocked = True
            db.session.commit()
            log('lah', "[{date}] unlocked challenge '{chal}'", chal=challenge.name)

scheduler = BackgroundScheduler()
scheduler.add_job(func=rand_unlock_callback, trigger="interval", seconds=10)


def load(app):
    # upgrade()
    app.db.create_all()
    CHALLENGE_CLASSES['lah'] = LahChallengeClass
    register_plugin_assets_directory(app, base_path='/plugins/lah_challenges/assets/')
    global APP_REF
    APP_REF = app
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
