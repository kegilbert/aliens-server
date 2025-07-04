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

from collections import OrderedDict
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
            'private': data['lobbyPW'] != '',
            'inProgress': False
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
    
    lobby_idx, lobby = App.lobby_lookup_by_id(data['roomCode'])
    App.lobbies[lobby_idx]['inProgress'] = True

    App.socketio.start_background_task(game_engine, room_id=data['roomCode'], players=data['players'])
    App.socketio.emit('gameStartResp', to=data['roomCode'])
    App.socketio.emit('lobbiesList', App.lobbies)



#################################################################
#       User Session Endpoints
#################################################################
@App.socketio.on('disconnect')
def disconnect():
    try:
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
    except Exception as e:
        print(f'[disconnect handler] Failed to handle disconnect event: {e}')
        pass


#################################################################
#       Game Session Endpoints
#################################################################
@App.socketio.on('tileClick')
def on_tile_click(data):
    return
    #App.socketio.emit('playerEvent', {'event': f'YOU CLICKED ON {data["tile"]}'}, to=data['playerId'])
    #App.socketio.emit('playerEvent', {'event': f'PLAYER {data["playerId"]} CLICKED ON <REDACTED>'}, to=data['lobbyId'])
    #App.socketio.emit('playerEvent', {'event': f'PLAYER {data["playerId"]} CLICKED ON <REDACTED>'}, room=data['lobbyId'], broadcast=True)


@App.socketio.on('turnSubmit')
def turn_submit(data):
    global game_sessions
    attack_flag = False
    game = game_sessions[data['lobbyId']]

    pprint(data)

    # TODO: Check if this movement is an attack. Do not try tile card on attack
    playerId = data['playerId']
    lobbyId  = data['lobbyId']
    tile     = data['tile']
    tileType = data['tileType']
    
    game['players'][playerId]['pos'] = tile

    for player, meta in game['players'].items():
        if player != playerId and meta['pos'] == tile and game['players'][playerId]['role'] == 'alien' and meta['status'] == 'alive':
            # Attack sequence
            game['players'][player]['status'] = 'dead'

            App.socketio.emit('roomEvent', {
                'card': 'attack',
                'tile': tile,
                'playerNumHeldCards': game['players'][playerId]['numHeldCards'],
                'playerId': playerId,
                'targetPlayer': player
            }, room=lobbyId, to=lobbyId, include_self=True)
            App.socketio.sleep(0)   # Flush events

            attack_flag = True

    if not attack_flag:
        if (tileType == 'escapepod') and game['players'][playerId]['role'] == 'human':
            card = game['escapepod_cards'].pop()

            if card == 'successful_escape':
                game['players'][player]['status'] = 'escaped'
        elif (tileType == 'dangerous'):
            if len(game['danger_cards']) == 0:
                game['danger_cards'] = ['noise', 'any'] * 27
                random.shuffle(game['danger_cards'])
                App.socketio.emit('roomEvent', {'state': 'deckShuffled'}, room=lobbyId, to=lobbyId)

            card = game['danger_cards'].pop()
            if 'silence' in card:
                game['players'][playerId]['numHeldCards'] += 1
        else:
            card = 'silence'

        App.socketio.emit('playerEvent', {
            'card': card,
            'tile': tile if card != 'any' else '',
            'playerNumHeldCards': game['players'][playerId]['numHeldCards'],
            'playerId': playerId
        }, room=lobbyId, to=playerId)
    #App.socketio.emit('roomEvent', {'state': 'noise' if 'silence' not in card else 'silence', 'player': data["playerId"], 'playerNumHeldCards': game['players']['playerId']['numHeldCards']}, broadcast=True, room=data['lobbyId'], to=data['lobbyId'])


def set_next_player(lobbyId):
    session = game_sessions[lobbyId]
    player_list = list(session['players'])
    session['current_player_idx'] = (session['current_player_idx'] + 1) % len(player_list)
    session['current_player'] = player_list[session['current_player_idx']]
    while session['players'][session['current_player']]['status'] != 'alive':
        session['current_player_idx'] = (session['current_player_idx'] + 1) % len(player_list)
        session['current_player'] = player_list[session['current_player_idx']]  
    return session['current_player']


@App.socketio.on('noiseInSector')
def broadcast_noise_in_sector(data):
    currPlayer = set_next_player(data['lobbyId'])
    App.socketio.emit('roomEvent', {
        'card': data['state'],
        'tile': data['tile'],
        'playerId': data['playerId'],
        'playerNumHeldCards': data['numHeldCards']
    }, room=data['lobbyId'], to=data['lobbyId'], include_self=data['includeSelf'])
    App.socketio.emit('updateCurrentPlayer', {
        'currPlayer': currPlayer
    }, room=data['lobbyId'], to=data['lobbyId'], include_self=True)

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

        # Generate and shuffle tile deck
        # 27 Noise in any sector
        # 27 Noise in your sector
        # 6  Silence
        # TODO: 17 Item cards (silence)
        #       - 3 Adrenaline
        #       - 1 Teleport
        #       - 2 Attack
        #       - 3 Sedatives
        #       - 1 Defence
        #       - 2 Cats
        #       - 1 Mutation
        #       - 1 Sensor
        #       - 1 Clone
        #       - 2 Spotlights
        # Rule book specifies only shuffling the noise danger cards back into the pile after running out. 
        # Silence/Item cards are kept in front of players, noise cards are discarded. Used item cards are flipped and kept in front of you
        dangerous_tile_deck = (
            (['noise', 'any'] * 27)        +
            (['silence'] * 6)              + 
            (['silence - adrenaline'] * 3) +
            (['silence - teleport'])       +
            (['silence - attack'] * 2)     +
            (['silence - sedative'] * 3)   +
            (['silence - defense'])        +
            (['silence - cat'] * 2)        +
            (['silence - mutation'])       +
            (['silence - sensor'])         +
            (['silence - clone'])          +
            (['silence - spotlight'] * 2)  
        )
        random.shuffle(dangerous_tile_deck)

        escapepod_tile_deck = (
            (['successful_escape'] * 4)  +
            (['damaged_escapepod'])
        )
        random.shuffle(escapepod_tile_deck)

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

        players_dict = OrderedDict()

        random.shuffle(players)
        for player in players:
            role = roles.pop()
            player['role'] = role
            player['pos'] = aspawn if role == 'alien' else hspawn
            player['maxMovement'] = 2 if role == 'alien' else 1
            player['kills'] = 0
            player['numHeldCards'] = 0
            player['status'] = 'alive'

            players_dict[player['playerName']] = player
            App.socketio.emit('roleAssignment', {'player': player}, to=player['playerName'])

        game_sessions[room_id] = {
            'map': {
                'info': map_info,
                'tiles': map_tiles,
                'aspawn': aspawn,
                'hspawn': hspawn
            },
            'players': players_dict, #players,
            'current_player': next(iter(players_dict)),  # Returns first key (playerID in this case)
            'current_player_idx': 0,
            'danger_cards': dangerous_tile_deck,
            'escapepod_cards': escapepod_tile_deck
        }
        App.socketio.emit('turnOrder',
            {'turnOrder': list(players_dict.keys()), 'currPlayer': game_sessions[room_id]['current_player']},
            room=room_id, to=room_id
        )

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


