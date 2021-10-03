from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, send, emit
from flask_cors import CORS

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
CORS(app)
socketio = SocketIO(app, ping_interval=60, cors_allowed_origins="*")


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


@socketio.on('client_disconnecting')
def disconnect_details(data):
    print(f'{data["username"]} user disconnected.')


@app.route('/test', methods=['GET'])
def test():
    print('test')
    # socketio.send('responseMessage', {'test': 'test1'})
    # socketio.emit('responseMessage', {'test': 'test2'}, json=True)

    return jsonify(status='OK'), 200


if __name__ == '__main__':
    socketio.run(app)
