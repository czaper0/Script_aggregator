# app.py
import os
import json
from flask import Flask, render_template, request,jsonify
from flask_socketio import SocketIO, emit
import asyncio
import subprocess
from datetime import datetime
import threading

app = Flask(__name__)
socketio = SocketIO(app)

scripts_path = os.path.join(app.root_path, 'scripts')
scripts = []
running_scripts = []
script_results = {}
script_processes = {}

def load_data():
    global scripts, running_scripts
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
            scripts = data.get('scripts', [])
            running_scripts = data.get('running_scripts', [])
    except FileNotFoundError:
        pass

def save_data():
    with open('data.json', 'w') as f:
        data = {'scripts': scripts, 'running_scripts': running_scripts}
        json.dump(data, f)

def get_available_scripts():
    script_files = [f for f in os.listdir(scripts_path) if f.endswith('.py')]
    return script_files

async def run_script(script):
    global scripts
    output = []

    def capture_output(line):
        output.append(line)
        socketio.emit('update_script_output', {'script': script, 'output': line})

    print(f"Attempting to run {script}")  # Dodane do diagnozy

    try:
        script_path = os.path.join(scripts_path, script)
        process = await asyncio.create_subprocess_shell(f'python {script_path}',
                                                        stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT)
        script_processes[script] = process
        async for line in process.stdout:
            capture_output(line.strip())
        await process.wait()

        print(f"Finished running {script}")  # Dodane do diagnozy
        print(f"Current running scripts: {running_scripts}")  # Dodane do diagnozy

        # Usuń skrypt z listy "Lista wywołań skryptów"
        if script in running_scripts:
            print(f"Removing {script} from running_scripts")  # Dodane do diagnozy
            running_scripts.remove(script)
            save_data()
            socketio.emit('update_running_scripts', running_scripts)

        # Dodaj skrypt do historii wywołań
        scripts.append([script, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        save_data()
        socketio.emit('script_executed', script)
        socketio.emit('update_scripts', scripts)

    except Exception as e:
        capture_output(f'Error during script execution: {str(e)}')

    script_results[script] = output





@app.route('/')
def index():
    available_scripts = get_available_scripts()
    load_data()
    return render_template('index.html', available_scripts=available_scripts, scripts=scripts, running_scripts=running_scripts)


@app.route('/script_result/<script>')
def script_result(script):
    result_output = script_results.get(script, [])
    return render_template('script_result.html', script=script, result_output=result_output)

@app.route('/kill_all_scripts', methods=['POST'])
def kill_all_scripts():
    for script, process in script_processes.items():
        process.terminate()
        if script in running_scripts:
            running_scripts.remove(script)
    script_processes.clear()
    socketio.emit('update_running_scripts', running_scripts)  # Aktualizuj listę w czasie rzeczywistym
    return jsonify(success=True)


@socketio.on('execute_script')
def execute_script(script):
    if script not in running_scripts:
        running_scripts.append(script)  # Przenieś tę linię przed uruchomieniem skryptu w osobnym wątku
        threading.Thread(target=asyncio.run, args=(run_script(script),)).start()
        socketio.emit('update_running_scripts', running_scripts)



@app.route('/clear_history', methods=['POST'])
def clear_history():
    global scripts
    scripts = []
    save_data()
    socketio.emit('history_cleared')
    return jsonify(success=True)

if __name__ == '__main__':
    socketio.run(app, debug=True)
