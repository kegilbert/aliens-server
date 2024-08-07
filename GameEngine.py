import sqlite3
import json
import datetime
import random
import string
#import threading
import random
import math
import pprint

import pandas as pd

from pprint import pprint
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, send, emit, join_room, close_room
from flask_cors import CORS, cross_origin

from time import sleep

import __main__ as App


#################################################################
#       Globals
#################################################################
active_lobby_ids = []
active_user_ids  = []
game_sessions = {}


#################################################################
#       Internal Methods
#################################################################
def register_room(room_id, id_type):
    global active_lobby_ids, active_user_ids
    
    join_room(room_id)
    lobby_list = active_user_ids if id_type == 'user' else active_lobby_ids
    lobby_list.append(room_id)

    print(f'=== [{id_type}] ===')
    pprint(lobby_list)


def unregister_room(room_id, id_type):
    global active_lobby_ids, active_user_ids
    
    close_room(room_id)
    lobby_list = active_user_ids if id_type == 'user' else active_lobby_ids
    lobby_list.remove(room_id)

    print(f'=== [{id_type}] ===')
    pprint(lobby_list)

#################################################################
#       Lobby Socket Endpoints
#################################################################
@App.socketio.on('createLobby')
def new_lobby(data):
    print('=== NEW LOBBY ===')
    register_room(data['lobbyId'], 'lobby')
    register_room(data['creatorPlayer'], 'user')


    App.lobbies.append({
            'lobbyId':data['lobbyId'],
            'lobbyName': data['lobbyName'],
            'numPlayers': 1,
            'players': [{'playerName': data['creatorPlayer'], 'playerReady': False}],
            'host': data['creatorPlayer'],
            'mapLabel': '',
            'private': data['lobbyPW'] != ''
        })

    if data['lobbyPW'] != '':
        App.lobbyPWs[data['lobbyId']] = data['lobbyPW']

    #App.socketio.emit('lobbiesList', App.lobbies, include_self=True, broadcast=True )
    App.socketio.emit('lobbiesList', App.lobbies)
    App.socketio.emit('joinCreatorToLobby', {'lobbyId': data['lobbyId']}, to=data['creatorPlayer'])


@App.socketio.on('joinLobby')
def join_lobby(data):
    #join_room(data['roomCode'])
    #join_room(data['userID'])
    register_room(data['roomCode'], 'lobby')
    register_room(data['userID'], 'user')

    lobbyID = data['roomCode']
    lobby_idx, lobby = App.lobby_lookup_by_id(lobbyID)
    
    App.lobbies[lobby_idx]['players'].append({'playerName': data['userID'], 'playerReady': False})
    App.lobbies[lobby_idx]['numPlayers'] = len(App.lobbies[lobby_idx]['players'])

    App.socketio.emit('lobbiesList', App.lobbies)
    #App.socketio.emit('lobbyPlayerJoin', {'playerName': data['userID']})


@App.socketio.on('leaveLobby')
def leave_lobby(data):
    unregister_room(data['player']['playerName'], 'user')

    lobbyID = data['roomCode']
    lobby_idx, lobby = App.lobby_lookup_by_id(lobbyID)
    
    App.lobbies[lobby_idx]['players'].remove(data['player'])
    App.lobbies[lobby_idx]['numPlayers'] = len(App.lobbies[lobby_idx]['players'])

    App.socketio.emit('lobbiesList', App.lobbies)
    #App.socketio.emit('lobbyPlayerLeave', {'playerName': data['player']['playerName']})    


@App.socketio.on('gameStart')
def game_start(data):
    global game_sessions

    print('=== GAME START ===')
    print(data)

    join_room(data['roomCode'])

    #t = threading.Thread(target=game_engine, args=(data['roomCode'], data['players']))
    #t.start()
    App.socketio.start_background_task(game_engine, room_id=data['roomCode'], players=data['players'])

    #App.socketio.emit('gameStartResp', broadcast=True, include_self=True, room=data['roomCode'])
    App.socketio.emit('gameStartResp', to=data['roomCode'])



#################################################################
#       User Session Endpoints
#################################################################
@App.socketio.on('disconnect')
def disconnect():
    user_name = App.users.inverse[request.sid]

    print(f'User {user_name} Disconnecting')
    unregister_room(user_name, 'user')

    for lobby_idx, lobby in enumerate(App.lobbies):
        players = [player['playerName'] for player in lobby['players']]
        if user_name in players:
            player_idx = players.index(user_name)
            del App.lobbies[lobby_idx]['players'][player_idx]

    del App.users.inverse[request.sid]
    App.socketio.emit('lobbiesList', App.lobbies)


#################################################################
#       Game Session Endpoints
#################################################################
@App.socketio.on('tileClick')
def on_tile_click(data):
    App.socketio.emit('playerEvent', {'event': f'YOU CLICKED ON {data["tile"]}'}, to=data['playerId'])
    App.socketio.emit('playerEvent', {'event': f'PLAYER {data["playerId"]} CLICKED ON <REDACTED>'}, to=data['lobbyId'])
    #App.socketio.emit('playerEvent', {'event': f'PLAYER {data["playerId"]} CLICKED ON <REDACTED>'}, room=data['lobbyId'], broadcast=True)


@App.socketio.on('turnSubmit')
def turn_submit(data):
    print(data)
    #App.socketio.emit('playerEvent', {'state': 'Private message just for you!'}, broadcast=False)
    #App.socketio.emit('roomEvent', {'state': f'{data["player"]} has moved'}, broadcast=True, room=data['roomCode'])


def game_engine(room_id, players):
    try:
        global game_sessions

        # Randomize turn order
        random.shuffle(players)
        num_players = len(players)
        role_div = math.floor(num_players / 2) + (num_players % 2)

        # Assign roles to players
        # 50/50 aliens/humans, majority aliens in case of odd number of players
        roles = ['alien' if i < role_div else 'human' for i in range(0, num_players)]
        random.shuffle(roles)

        lobby_idx, lobby = App.lobby_lookup_by_id(room_id)
        map_label = lobby['mapLabel']
        db = sqlite3.connect('aliens.db')
        db.row_factory = App.row_to_dict
        db_cursor = db.cursor()
        map_info = db_cursor.execute(f'SELECT * FROM maps WHERE name="{map_label}" ORDER BY timestamp DESC').fetchone()

        tiles = db_cursor.execute(f'SELECT * FROM "{map_info["name"]}_tiles"').fetchall()
        map_tiles = {tiles[i]['tile']: {k: tiles[i][k] for k in tiles[i].keys() - {'tile'}} for i in range(0, len(tiles))}

        aspawn = [key for key, value in map_tiles.items() if value['tileType'] == 'aspawn'][0]
        hspawn = [key for key, value in map_tiles.items() if value['tileType'] == 'hspawn'][0]

        for player in players:
            role = roles.pop()
            player['role'] = role
            player['pos'] = aspawn if role == 'alien' else hspawn
            #player['status'] = 'alive'

            App.socketio.emit('roleAssignment', {'player': player}, to=player['playerName'])

        game_sessions[room_id] = {
            'map': {
                'info': map_info,
                'tiles': map_tiles,
                'aspawn': aspawn,
                'hspawn': hspawn
            },
            'players': players
            # 'players': [{
            #     'id':  player['playerName'],
            #     'pos': aspawn if player['role'] == 'alien' else hspawn,
            #     'status': 'alive'
            # } for player in players]
        }

        pprint(game_sessions)

        # Start
        pprint(players)
        print('=======================')
        pprint(App.socketio.server.rooms)

        while True:
            # Individual game, game start kicks off new thread running this function loop
            print(f'[{room_id}] PING')
            sleep(30)
    except KeyboardInterrupt:
        exit(0)


