import sqlite3
import json
import datetime

import pandas as pd

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, send, emit
from flask_cors import CORS


###############################################################################
#   Flask SocketIO Globals
###############################################################################
app = Flask(__name__)
app.config['SECRET_KEY'] = 'aliens'
CORS(app)
socketio = SocketIO(app, ping_interval=60, cors_allowed_origins="*")

###############################################################################
#   Local Database Management Globals
###############################################################################
def row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]
    return data



@socketio.on('message')
def handle_message(data):
    print('received message: ' + data)


@socketio.on('json')
def handle_json(json):
    print('received json: ' + str(json))


@socketio.on('incoming')
def handle_incoming(data):
    print(f'Incoming: {data}')
    emit('responseMessage', data, broadcast=True)


@socketio.on('save')
def handle_incoming(data):
    print(f'Save: {data}')
    db = sqlite3.connect('aliens.db')
    db_cursor = db.cursor()
    map_name = data['mapName']
    tTiles = data['tiles']
    tile_table_data = {'tile': [], 'tileType': [], 'color': []}

    for tile, info in tTiles.items():
        tile_table_data['tile'].append(tile)
        tile_table_data['tileType'].append(info['tileType'])
        tile_table_data['color'].append(info['color'])

    curr_time = datetime.datetime.now().timestamp()
    tiles_df = pd.DataFrame(data=tile_table_data)
    tiles_df.to_sql(f'{map_name}_tiles', db, if_exists='replace', index=False)
    map_df   = pd.DataFrame(data={'name': [map_name], 'tiles': [f'{map_name}_tiles'], **data['meta'], 'user': data['user'], 'timestamp': curr_time})
    print(map_df)
    print(tiles_df)

    map_df.to_sql('maps', db, if_exists='append', index=False)

    db_cursor.execute(f'''
        DELETE FROM maps
        WHERE
            name = "{map_name}" AND timestamp < {curr_time}
    ''')


    db.commit()



@socketio.on('client_disconnecting')
def disconnect_details(data):
    print(f'{data["username"]} user disconnected.')


@socketio.on('getMapList')
def get_map_list(data):
    db = sqlite3.connect('aliens.db')
    db.row_factory = row_to_dict
    db_cursor = db.cursor()
    maps = db_cursor.execute('SELECT * FROM maps ORDER BY timestamp DESC').fetchall()

    map_list = []

    for _map in maps:
        meta = {k: _map[k] for k in _map.keys() - {'name', 'tiles'}}
        tiles = db_cursor.execute(f'SELECT * FROM "{_map["name"]}_tiles"').fetchall()
        map_list.append({
            'label': _map['name'],
            'value': {
                'tiles': {tiles[i]['tile']: {k: tiles[i][k] for k in tiles[i].keys() - {'tile'}} for i in range(0, len(tiles))},
                'meta': meta
            }
        })

    print(map_list)
    emit('emitMapList', map_list)


if __name__ == '__main__':
    socketio.run(app, '0.0.0.0', port=5000)
