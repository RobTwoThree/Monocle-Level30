#!/usr/bin/env python3

from datetime import datetime, timedelta
from pkg_resources import resource_filename

import time
import argparse

from flask import Flask, render_template

from monocle import db, sanitized as conf
from monocle.names import POKEMON
from monocle.web_utils import get_args
from monocle.bounds import area


app = Flask(__name__, template_folder=resource_filename('monocle', 'templates'))

CACHE = {
    'data': None,
    'generated_at': None,
}


def get_stats():
    cache_valid = (
        CACHE['data'] and
        CACHE['generated_at'] > datetime.now() - timedelta(minutes=15)
    )
    if cache_valid:
        return CACHE['data']
    with db.session_scope() as session:
        forts = db.get_forts(session)
    count = {t.value: 0 for t in db.Team}
    guardians = {t.value: {} for t in db.Team}
    top_guardians = {t.value: None for t in db.Team}
    percentages = {}
    last_date = 0
    pokemon_names = POKEMON
    for fort in forts:
        if fort['last_modified'] > last_date:
            last_date = fort['last_modified']
        team = fort['team']
        count[team] += 1
        if team != 0:
            # Guardians
            guardian_value = guardians[team].get(pokemon_id, 0)
            guardians[team][pokemon_id] = guardian_value + 1
    for team in db.Team:
        percentages[team.value] = (
            count.get(team.value) / len(forts) * 100
        )
        if guardians[team.value]:
            pokemon_id = sorted(
                guardians[team.value],
                key=guardians[team.value].__getitem__,
                reverse=True
            )[0]
            top_guardians[team.value] = pokemon_names[pokemon_id]
    CACHE['generated_at'] = datetime.now()
    CACHE['data'] = {
        'order': sorted(count, key=count.__getitem__, reverse=True),
        'count': count,
        'total_count': len(forts),
        'percentages': percentages,
        'last_date': last_date,
        'top_guardians': top_guardians,
        'generated_at': CACHE['generated_at'],
    }
    return CACHE['data']


@app.route('/')
def index():
    stats = get_stats()
    team_names = {k.value: k.name.title() for k in db.Team}
    styles = {1: 'primary', 2: 'danger', 3: 'warning'}
    return render_template(
        'gyms.html',
        area_name=conf.AREA_NAME,
        area_size=area,
        minutes_ago=int((datetime.now() - stats['generated_at']).seconds / 60),
        last_date_minutes_ago=int((time.time() - stats['last_date']) / 60),
        team_names=team_names,
        styles=styles,
        **stats
    )


if __name__ == '__main__':
    args = get_args()
    app.run(debug=args.debug, host=args.host, port=args.port)
