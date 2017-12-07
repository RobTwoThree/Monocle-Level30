import sys, os
from datetime import datetime
from crontab import CronTab
from argparse import ArgumentParser
from logging.handlers import RotatingFileHandler
from logging import getLogger, basicConfig, WARNING, INFO
from monocle import cleanup as Cleanup
from monocle.accounts import Account
        
if not os.path.exists("logs"):
    os.makedirs("logs")

this_file = os.path.realpath(__file__)
root_dir = os.path.dirname(this_file)
log = getLogger('cleanup')
handlers = (RotatingFileHandler("{}/logs/cron.log".format(root_dir), maxBytes=500000, backupCount=5),)
basicConfig(
    format='[{asctime}][{levelname:>8s}][{name}] {message}',
    datefmt='%Y-%m-%d %X',
    style='{',
    level=INFO,
    handlers=handlers
)

tag = "Monocle/Monkey-Cleanup {}".format(root_dir)

def parse_args():
    parser = ArgumentParser()
    parser.add_argument(
        '-sh, --show-cron',
        dest='show_cron',
        help='Show the cron commands to be added.',
        action='store_true'
    )
    parser.add_argument(
        '-sc, --set-cron',
        dest='set_cron',
        help='Write cleanup jobs to crontab of current user.',
        action='store_true'
    )
    parser.add_argument(
        '-uc, --unset-cron',
        dest='unset_cron',
        help='Remove cleanup jobs from crontab of current user.',
        action='store_true'
    )
    parser.add_argument(
        '--light',
        dest='light',
        help='Run cleanups for sightings, fort_sightings, mystery_sightings and raids. Recommended to run this once a minute',
        action='store_true'
    )
    #parser.add_argument(
    #    '--heavy',
    #    dest='heavy',
    #    help='Run cleanup for spawnpoints. Recommended to run every hour.',
    #    action='store_true'
    #)
    parser.add_argument(
        '--swapin',
        dest='swapin',
        help='Run swap-in for hibernated accounts. Set ACCOUNTS_HIBERNATE_DAYS in config to change hibernation day. If not set, default would be 7.0 days.',
        action='store_true'
    )
    return parser.parse_args()

def cron_jobs():
    command = "cd {} && {} {}".format(root_dir, sys.executable, this_file)
    
    cron = CronTab(user=True)
    jobs = []
    
    job_light = cron.new(command="{} --light >> {}/logs/cron.log 2>&1".format(command, root_dir),comment="{} --light".format(tag))
    jobs.append(job_light)
    
    #job_heavy = cron.new(command="{} --heavy >> {}/logs/cron.log 2>&1".format(command, root_dir),comment="{} --heavy".format(tag))
    #job_heavy.minute.on(5)
    #jobs.append(job_heavy)

    job_swapin = cron.new(command="{} --swapin >> {}/logs/cron.log 2>&1".format(command, root_dir),comment="{} --swapin".format(tag))
    job_swapin.minute.every(5)
    jobs.append(job_swapin)

    return cron, jobs

def remove_jobs():
    cron = CronTab(user=True)
    for job in cron:
        if job.comment.startswith(tag+" "):
            cron.remove(job)
    cron.write()


def main():
    args = parse_args()

    if args.show_cron:
        cron, jobs = cron_jobs()
        print("-" * 53)
        print("The following cron jobs will be added to your crontab")
        print("-" * 53)
        for job in jobs:
            print(job)
        print("")
    elif args.set_cron:
        remove_jobs()
        cron, jobs = cron_jobs()
        cron.write()
        print("Crontab changed. Cron jobs added.")
    elif args.unset_cron:
        remove_jobs()
        print("Crontab changed. Cron jobs removed.")
    elif args.light:
        log.info("Performing light cleanup.")
        Cleanup.light()
    #elif args.heavy:
    #    log.info("Performing heavy cleanup.")
    #    Cleanup.heavy()
    elif args.swapin:
        log.info("Performing swap-in of hibernated accounts.")
        Account.swapin()
    else:
        print("Set --help for available commands.")

if __name__ == '__main__':
    main()
