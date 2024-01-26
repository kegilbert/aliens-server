import sqlite3
import json
import datetime
import random
import string
import logging

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

import GameEngine

###############################################################################
#   Local Database Management Globals
###############################################################################
lobbies = [{
            'lobbyId':'123456',
            'lobbyName': 'penis',
            'numPlayers': 1,
            'players': [{'playerName': 'Kebin', 'playerReady': False}],
            'host': 'Kebin',
            'mapLabel': '',
            'private': False,
        }]
lobbyPWs = {}
users = {}

def lobby_lookup_by_id(request_id):
    lobby = None
    
    try:
        idx, lobby = next((idx, _l) for (idx, _l) in enumerate(lobbies) if _l['lobbyId'] == request_id)
    except:
        print(f'[ERROR] Could not locate lobby ID {request_id}')
        pass

    return idx, lobby


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


# # Old method, not really sure why I would store lobbies in the DB though as they're pretty transient...
# @socketio.on('getLobbiesDB')
# def get_lobbies(data):
#     # lobbies_list.append({
#     #     'lobbyId': lobby['lobbyID'],
#     #     'lobbyName': lobby['name'],
#     #     'numPlayers': len(lobby['playerList'].split(',')),
#     #     'players': [{'playerName': player, 'playerReady': False} for player in lobby['playerList'].split(',')],
#     #     'private': lobby['password'] != '',
#     #     #'password': lobby['password']
#     # })

#     emit('lobbiesList', lobies)


@socketio.on('getLobbies')
def get_lobbies(data):
    emit('lobbiesList', lobbies)


# @socketio.on('createLobby')
# def create_lobby(data):
#     db = sqlite3.connect('aliens.db')
#     db.row_factory = row_to_dict
#     db_cursor = db.cursor()   

#     curr_time = datetime.datetime.now().timestamp()
#     lobby_df = pd.DataFrame(data={
#       'lobbyID': data['lobbyId'],
#       'name': data['lobbyName'],
#       'password': data['lobbyPW'],
#       'map': '',
#       'playerList': f'{data["creatorPlayer"]}',
#       'timestamp': curr_time
#     }, index=[0])

#     lobby_df.to_sql(f'Lobbies', db, if_exists='append', index=False)

#     get_lobbies({})


@socketio.on('setLobbyMap')
def set_lobby_map(data):
    lobby_idx, lobby = lobby_lookup_by_id(data['lobbyId'])

    lobbies[lobby_idx]['mapLabel'] = data['mapLabel']

    pprint(lobbies)
    socketio.emit('lobbiesList', lobbies, broadcast=True, room=data['lobbyId'])   


@socketio.on('registerUsername')
def register_username(data):
    new_user = data['username']
    if new_user in users.keys():
        emit('usernameUnavailable', {})
    else:
        users[new_user] = {'user': new_user}
        emit('usernameRegistered', {})


@socketio.on('registerPlayerReadyState')
def register_player_ready_state(data):
    lobby_idx, lobby = lobby_lookup_by_id(data['lobbyId'])

    player_idx = None

    for idx, player in enumerate(lobbies[lobby_idx]['players']):
        if player['playerName'] == data['playerName']:
            player_idx = idx
            lobbies[lobby_idx]['players'][idx]['playerReady'] = data['playerReady']

    #emit('lobbyPlayerReadyUpdate', {'playerIdx': player_idx, 'playerReady': data['playerReady']})
    pprint(lobbies)
    socketio.emit('lobbiesList', lobbies, include_self=True, broadcast=True, room=data['lobbyId'])


###############################################################################
#   Static HTTP Endpoints
###############################################################################
@app.route('/check_lobby_password', methods=['POST'])
@cross_origin()
def check_lobby_pw():
    data = request.json  
    # db = sqlite3.connect('aliens.db')
    # db.row_factory = row_to_dict
    # db_cursor = db.cursor()  

    # lobby = db.execute(f'SELECT password from Lobbies WHERE lobbyID = "{data["lobbyId"]}"').fetchone()
    # try:
    #     lobby = next(lobby for lobby in lobbies if lobby['lobbyId'] == data['lobbyId'])
    # except:
    #     print('[ERROR] Lobby ID Not found')
    #     lobby = {'lobbyPW': ''}
    #     pass

    if data['lobbyId'] in lobbyPWs.keys():
        pw = lobbyPWs[data['lobbyId']]

    return jsonify(status=pw == data['pw']), 200


if __name__ == '__main__':
    logging.getLogger('socketio').setLevel(logging.ERROR)
    logging.getLogger('engineio').setLevel(logging.ERROR)
    logging.getLogger('werkzeug').disabled = True

    socketio.run(app, '0.0.0.0', port=5069, debug=False)
