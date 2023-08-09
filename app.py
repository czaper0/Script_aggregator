# app.py
import os
import json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import asyncio
import subprocess

app = Flask(__name__)
socketio = SocketIO(app)

scripts_path = os.path.join(app.root_path, 'scripts')
scripts = []
running_scripts = []
script_results = {}

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
    output = []

    def capture_output(line):
        output.append(line)
        socketio.emit('update_script_output', {'script': script, 'output': line})

    try:
        script_path = os.path.join(scripts_path, script)
        process = await asyncio.create_subprocess_shell(f'python {script_path}',
                                                        stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT)
        async for line in process.stdout:
            capture_output(line.strip())
        await process.wait()
    except Exception as e:
        capture_output(f'Error during script execution: {str(e)}')

    script_results[script] = output
    socketio.emit('script_executed', script)
    socketio.emit('update_scripts', scripts)
    save_data()

@app.route('/')
def index():
    available_scripts = get_available_scripts()
    load_data()
    return render_template('index.html', available_scripts=available_scripts, scripts=scripts, running_scripts=running_scripts)


@app.route('/script_result/<script>')
def script_result(script):
    result_output = script_results.get(script, [])
    return render_template('script_result.html', script=script, result_output=result_output)

@socketio.on('execute_script')
def execute_script(script):
    if script not in running_scripts:
        asyncio.run(run_script(script))
        running_scripts.append(script)
        socketio.emit('update_running_scripts', running_scripts)

if __name__ == '__main__':
    socketio.run(app, debug=True)
