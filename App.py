import sqlite3
import json
import datetime
import random
import string

import pandas as pd

from pprint import pprint
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, send, emit
from flask_cors import CORS, cross_origin


###############################################################################
#   Flask SocketIO Globals
###############################################################################
app = Flask(__name__)
app.config['SECRET_KEY'] = 'aliens'
CORS(app)
socketio = SocketIO(app, ping_interval=60, cors_allowed_origins="*", engineio_logger=False)

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

    emit('emitMapList', map_list)


@socketio.on('getLobbies')
def get_lobbies(data):
    db = sqlite3.connect('aliens.db')
    db.row_factory = row_to_dict
    db_cursor = db.cursor()

    lobbies = db_cursor.execute('SELECT * FROM Lobbies ORDER BY timestamp DESC').fetchall()
    lobbies_list = []

    for lobby in lobbies:
        lobbies_list.append({
            'lobbyId': lobby['lobbyID'],
            'lobbyName': lobby['name'],
            'numPlayers': len(lobby['playerList'].split(',')),
            'players': [{'playerName': player, 'playerReady': False} for player in lobby['playerList'].split(',')],
            'private': lobby['password'] != '',
            #'password': lobby['password']
        })

    emit('lobbiesList', lobbies_list)


@socketio.on('createLobby')
def create_lobby(data):
    db = sqlite3.connect('aliens.db')
    db.row_factory = row_to_dict
    db_cursor = db.cursor()   

    curr_time = datetime.datetime.now().timestamp()
    lobby_df = pd.DataFrame(data={
      'lobbyID': data['lobbyId'],
      'name': data['lobbyName'],
      'password': data['lobbyPW'],
      'map': '',
      'playerList': f'{data["creatorPlayer"]}',
      'timestamp': curr_time
    }, index=[0])

    lobby_df.to_sql(f'Lobbies', db, if_exists='append', index=False)

    get_lobbies({})


@socketio.on('setLobbyMap')
def set_lobby_map(data):
    db = sqlite3.connect('aliens.db')
    db.row_factory = row_to_dict
    db_cursor = db.cursor()

    db.execute(f'UPDATE Lobbies SET map = "{data["map"]["label"]}" WHERE lobbyID = "{data["lobbyId"]}"')
    db.commit()


###############################################################################
#   Static HTTP Endpoints
###############################################################################
@app.route('/check_lobby_password', methods=['POST'])
@cross_origin()
def check_lobby_pw():
    data = request.json  
    db = sqlite3.connect('aliens.db')
    db.row_factory = row_to_dict
    db_cursor = db.cursor()  

    lobby = db.execute(f'SELECT password from Lobbies WHERE lobbyID = "{data["lobbyId"]}"').fetchone()

    return jsonify(status=lobby['password'] == data['pw']), 200


if __name__ == '__main__':
    socketio.run(app, '0.0.0.0', port=5069)
