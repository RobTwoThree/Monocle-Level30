#!/usr/bin/env python3

import sys
import pickle

from pathlib import Path

monocle_dir = Path(__file__).resolve().parents[1]
sys.path.append(str(monocle_dir))

from monocle.landmarks import Landmarks

pickle_dir = monocle_dir / 'pickles'
pickle_dir.mkdir(exist_ok=True)

LANDMARKS = Landmarks(query_suffix='Salt Lake City')

# replace the following with your own landmarks
LANDMARKS.add('Rice Eccles Stadium', hashtags={'Utes'})
LANDMARKS.add('the Salt Lake Temple', hashtags={'TempleSquare'})
LANDMARKS.add('City Creek Center', points=((40.769210, -111.893901), (40.767231, -111.888275)), hashtags={'CityCreek'})
LANDMARKS.add('the State Capitol', query='Utah State Capitol Building')
LANDMARKS.add('the University of Utah', hashtags={'Utes'}, phrase='at', is_area=True)
LANDMARKS.add('Yalecrest', points=((40.750263, -111.836502), (40.750377, -111.851108), (40.751515, -111.853833), (40.741212, -111.853909), (40.741188, -111.836519)), is_area=True)

pickle_path = pickle_dir / 'landmarks.pickle'
with pickle_path.open('wb') as f:
    pickle.dump(LANDMARKS, f, pickle.HIGHEST_PROTOCOL)


print('\033[94mDone. Now add the following to your config:\n\033[92m',
      'import pickle',
      "with open('pickles/landmarks.pickle', 'rb') as f:",
      '    LANDMARKS = pickle.load(f)',
      sep='\n')
