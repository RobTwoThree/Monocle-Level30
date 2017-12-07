import csv
import sys
from argparse import ArgumentParser, ArgumentTypeError
from datetime import datetime
from pathlib import Path

monocle_dir = Path(__file__).resolve().parents[1]
sys.path.append(str(monocle_dir))

from monocle.accounts import Account

def parse_args():
    def check_level(value):
        ivalue = int(value)
        if ivalue < 0 or ivalue > 40:
             raise ArgumentTypeError("%s should be between 0 and 40 inclusive" % value)
        return ivalue

    parser = ArgumentParser()
    parser.add_argument(
        'filename',
        help='File to import. Supports Monocle accounts.csv, Goman, Kinan and Selly formats.',
    )
    parser.add_argument(
        '--level',
        dest='level',
        help='Update to this level if not found in pickles. Must be between 0 and 40 inclusive',
	type=check_level,
    )
    parser.add_argument(
        '--set-instance-id',
        dest='assign_instance',
        help='Assign accounts to this instance. If not set, accounts will be avilable to all instances using the same DB.',
        action='store_true',
    )
    return parser.parse_args()

def main():
    args = parse_args()
    Account.import_file(args.filename, level=args.level, assign_instance=args.assign_instance)

if __name__ == '__main__':
    main()
