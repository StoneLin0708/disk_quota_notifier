import datetime as dt
import json
import logging
import os
import shutil
import signal
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging.handlers import TimedRotatingFileHandler
from smtplib import SMTP
from subprocess import getoutput

from schedule import every, run_pending


def get_du_homes():
    o = getoutput('sudo ./du_homes.sh')
    du = []
    for l in o.split('\n'):
        d, u = l.split('\t')
        du.append((int(d), u[6:]))
    return sorted(du, reverse=True)


class MailForwarder:

    def __init__(self, config, members, logger):
        self.config = config
        self.users = members['users']
        self.managers = members['managers']
        self.logger = logger

    def _get_user_emails(self):
        return self.users.values()

    def _get_manager_emails(self):
        return self.managers.values()

    def _create_error_mail(self, subject, error_text):
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.config['smtp_user']
        msg['To'] = ','.join(self._get_manager_emails())
        msg.attach(MIMEText(error_text, 'plain'))
        return msg

    def _create_notification_mail(self, du_homes):
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Home Directory Usage Notification'
        msg['From'] = self.config['smtp_user']
        msg['To'] = ','.join(self._get_user_emails())
        du_msg = '\n'.join(
            [f'{u:12}:{d / 2**20: 8.2f} GB' for d, u in du_homes])
        msg.attach(
            MIMEText(f'Home Directory Usage Notification\n\n{du_msg}', 'plain'))
        return msg

    def _send_mail_to(self, mail, to_addrs):
        with SMTP(self.config['host'], port=self.config['smtp_port']) as server:
            server.starttls()
            l = server.login(self.config['smtp_user'], self.config['smtp_pw'])
            ret = server.sendmail(self.config['smtp_user'], to_addrs,
                                  mail.as_string())
            if len(ret) > 0:
                self.logger.error(f'`{mail["subject"]}` sending failed')
                for address, err in ret.items():
                    self.logger.error(f'{address}: {err}')

    def _send_du_notification(self):
        du_homes = get_du_homes()
        du_notification = self._create_notification_mail(du_homes)
        self._send_mail_to(du_notification, self._get_user_emails())
        self.logger.info('Home Directory Usage Notification sent')

    def update(self):
        try:
            total, used, free = shutil.disk_usage('/home')
            if used / total > self.config['notify_threshold']:
                self._send_du_notification()
        except Exception as e:
            self.logger.error(f'update failed: {e}')
            self._send_mail_to(
                self._create_error_mail(
                    f'{dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} : Sending Mail Failed',
                    str(e)), self._get_manager_emails())
            exit(1)


def create_logger(logname, console=False):
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    if console:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    if not os.path.exists(os.path.dirname(logname)):
        os.mkdir(os.path.dirname(logname))

    handler = TimedRotatingFileHandler(logname, when="midnight", interval=1)
    handler.suffix = "%Y%m%d"
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger


def main():
    logger = create_logger('log/forward.log')
    logger.info('Start')

    forwarder = MailForwarder(
        config=json.load(open('config.json')),
        members=json.load(open('members.json')),
        logger=logger,
    )

    stop = False

    def signal_handler(sig, frame):
        nonlocal stop
        stop = True
        logger.info('Shutdown')

    def is_running():
        nonlocal stop
        return not stop

    signal.signal(signal.SIGINT, signal_handler)

    every().monday.do(forwarder.update)
    # every(3).seconds.do(forwarder.update)

    while is_running():
        run_pending()
        time.sleep(60)
        # time.sleep(1)


if __name__ == '__main__':
    main()
