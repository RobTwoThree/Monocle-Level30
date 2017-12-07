import sys, os
from pathlib import Path
from argparse import ArgumentParser

monocle_dir = Path(__file__).resolve().parents[1]
sys.path.append(str(monocle_dir))

from monocle.db import Base, _engine



def parse_args():
    parser = ArgumentParser()
    parser.add_argument(
        '--for-real',
        dest='for_real',
        help='Run the create_db.py script from stock Monocle.',
        action='store_true'
    )
    return parser.parse_args()

def main():
    args = parse_args()

    if args.for_real:
        Base.metadata.create_all(_engine)
        print('Done!')
    else:
        print('')
        print('DEPRECATION WARNING: script/create_db.py is deprecated in Monocle/Monkey.')
        print('')
        print('Run `{}/alembic upgrade head` instead.'.format(os.path.dirname(sys.executable)))
        print('')
        print('Alembic is introduced to ease db migration and to enforce DB consistency.\nDoing changes to your DB schema manually can introduce unecessary human error.')
        print('If you still want to run create_db.py (and you know what you are doing!),\nrerun this script with the flag `--for-real`.')
        print('For help, use the flag `--help`.')
        print('')

if __name__ == '__main__':
    main()
