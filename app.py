# app.py
import os
import json
from flask import Flask, render_template, request,jsonify
from flask_socketio import SocketIO, emit
import asyncio
import subprocess
from datetime import datetime
import threading
from jinja2 import Environment, FileSystemLoader, select_autoescape
from urllib.parse import quote_plus
from werkzeug.urls import url_encode

env = Environment(
    loader=FileSystemLoader('templates'),
    autoescape=select_autoescape(['html', 'xml']),
    extensions=['jinja2.ext.loopcontrols']
)
env.filters['urlencode'] = url_encode
app = Flask(__name__)
app.jinja_env.filters['urlencode'] = quote_plus
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
    categories = {}
    for root, dirs, files in os.walk(scripts_path):
        for file in files:
            if file.endswith('.py'):
                relative_path = os.path.relpath(root, scripts_path)
                if relative_path == ".":
                    category = "ogólne"
                else:
                    category = relative_path.replace(os.sep, '/')  # Użyj separatora '/' niezależnie od systemu
                if category not in categories:
                    categories[category] = []
                full_path = os.path.join(relative_path, file).replace(os.sep, '/') if category != "ogólne" else file
                categories[category].append(full_path)
    return categories


async def run_script(script_path):
    global scripts
    output = []
    def capture_output(line):
        output.append(line)
        socketio.emit('update_script_output', {'script': script_path, 'output': line})
    print(f"Attempting to run {script_path}")
    try:
        full_script_path = os.path.join(scripts_path, script_path)
        process = await asyncio.create_subprocess_shell(f'python "{full_script_path}"',
                                                        stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT)
        script_processes[script_path] = process
        async for line in process.stdout:
            capture_output(line.strip())
        await process.wait()
        print(f"Finished running {script_path}")
        # Usuń skrypt z listy "Lista wywołań skryptów"
        if script_path in running_scripts:
            running_scripts.remove(script_path)
            save_data()
            socketio.emit('update_running_scripts', running_scripts)
        # Dodaj skrypt do historii wywołań
        scripts.append([script_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        save_data()
        socketio.emit('script_executed', {'script': script_path, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        socketio.emit('update_scripts', scripts)
    except Exception as e:
        capture_output(f'Error during script execution: {str(e)}')
    script_results[script_path] = output



@app.route('/')
def index():
    available_scripts = get_available_scripts()
    load_data()
    return render_template('index.html', available_scripts=available_scripts, scripts=scripts, running_scripts=running_scripts)


import urllib
@app.route('/script_result/<string:encoded_script>')
def script_result(encoded_script):
    script = urllib.parse.unquote(encoded_script)
    result_output = script_results.get(script, [])
    return render_template('script_result.html', script=script, result_output=result_output)



@socketio.on('execute_script')
def execute_script(script_path):
    if script_path not in running_scripts:
        threading.Thread(target=asyncio.run, args=(run_script(script_path),)).start()
        running_scripts.append(script_path)
        socketio.emit('update_running_scripts', running_scripts)


@app.route('/kill_all_scripts', methods=['POST'])
def kill_all_scripts():
    for script_path, process in script_processes.items():
        process.terminate()
        if script_path in running_scripts:
            running_scripts.remove(script_path)
    script_processes.clear()
    socketio.emit('update_running_scripts', running_scripts)
    return jsonify(success=True)


@app.route('/clear_history', methods=['POST'])
def clear_history():
    global scripts
    scripts = []
    save_data()
    socketio.emit('history_cleared')
    return jsonify(success=True)

if __name__ == '__main__':
    socketio.run(app, debug=True)
