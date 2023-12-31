# app.py
import os, re
import json
from flask import Flask, render_template, request,jsonify
from flask_socketio import SocketIO, emit
import asyncio
import subprocess
from datetime import datetime
import threading
from jinja2 import Environment, FileSystemLoader, select_autoescape
from urllib.parse import quote_plus, unquote_plus
from werkzeug.urls import url_encode
import shutil

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
    global scripts
    results_dir = os.path.join(app.root_path, 'results')
    scripts = []
    if os.path.exists(results_dir):
        for filename in os.listdir(results_dir):
            match = re.match(r'(.+)_(\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})\.txt', filename)
            if match:
                script_name, timestamp = match.groups()
                scripts.append([script_name, timestamp.replace('_', ' ').replace('-', ':')])
    scripts.sort(key=lambda x: x[1], reverse=True)  # Sortuj według daty i godziny

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
            decoded_line = line.decode('utf-8').strip()
            capture_output(decoded_line)
        exit_code = await process.wait()
        if exit_code != 0:
            raise Exception(f"Script exited with code {exit_code}")
        print(f"Finished running {script_path}")
    except Exception as e:
        capture_output(f'Error during script execution: {str(e)}')
        # Dodajemy skrypt do historii wywołań z informacją o błędzie
        scripts.append([script_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S') + " (Error)"])
    finally:
        # Usuń skrypt z listy "Lista wywołań skryptów"
        if script_path in running_scripts:
            running_scripts.remove(script_path)
            socketio.emit('update_running_scripts', running_scripts)
        # Dodaj skrypt do historii wywołań (jeśli nie było błędu)
        if not any(script[0] == script_path and "Error" in script[1] for script in scripts):
            scripts.append([script_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        socketio.emit('script_executed', {'script': script_path, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        socketio.emit('update_scripts', scripts)

    script_results[script_path] = output
    # zapisz wynik do pliku txt
    results_dir = os.path.join(app.root_path, 'results')
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
    # Zmieniony sposób tworzenia nazwy pliku
    timestamp_str = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
    safe_script_name = re.sub(r'\W+', '_', os.path.splitext(script_path)[0])
    result_file_name = f"{safe_script_name}_{timestamp_str}.txt"
    result_file_path = os.path.join(results_dir, result_file_name)


    with open(result_file_path, 'w') as f:
        for line in output:
            f.write(line + '\n')




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

@app.route('/view_result/<string:script_name>')
def view_result(script_name):
    results_dir = os.path.join(app.root_path, 'results')
    
    # Zmieniony sposób tworzenia nazwy pliku
    decoded_script_name = urllib.parse.unquote(script_name)
    safe_script_name = re.sub(r'\W+', '_', os.path.splitext(decoded_script_name)[0])
    result_file_path = os.path.join(results_dir, f"{safe_script_name}.txt")
    
    with open(result_file_path, 'r') as f:
        content = f.read()
    return render_template('view_result.html', content=content)


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
    socketio.emit('history_cleared')
    
    # Usuwanie plików z katalogu results
    results_dir = os.path.join(app.root_path, 'results')
    for filename in os.listdir(results_dir):
        file_path = os.path.join(results_dir, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")

    return jsonify(success=True)

if __name__ == '__main__':
    socketio.run(app, debug=True)
