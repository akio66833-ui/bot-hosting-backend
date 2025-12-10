"""
Free Bot Hosting Backend - Flask API
Deploy this on Render.com (free tier)

Features:
- Upload bot files (.py, .js)
- Start/stop bots
- View logs
- Monitor CPU/memory
- Per-user bot management
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import subprocess
import psutil
import json
import time
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = '/tmp/bots'  # Free tier uses /tmp
ALLOWED_EXTENSIONS = {'py', 'js'}
MAX_BOTS_PER_USER = 3  # Free tier limit

# In-memory storage (use database in production)
bots_db = {}
running_processes = {}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_bot_id(username, bot_name):
    timestamp = int(time.time())
    return f"{username}_{bot_name}_{timestamp}"

def get_process_stats(pid):
    """Get CPU and memory usage for a process"""
    try:
        process = psutil.Process(pid)
        cpu = process.cpu_percent(interval=0.1)
        memory = process.memory_info().rss / (1024 * 1024)  # MB
        return {'cpu': round(cpu, 2), 'memory': round(memory, 2)}
    except:
        return {'cpu': 0, 'memory': 0}

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.route('/api/bots/<username>', methods=['GET'])
def get_user_bots(username):
    """Get all bots for a user"""
    user_bots = []
    
    for bot_id, bot_data in bots_db.items():
        if bot_data['username'] == username:
            bot_info = bot_data.copy()
            
            # Update stats if running
            if bot_id in running_processes:
                pid = running_processes[bot_id]['pid']
                stats = get_process_stats(pid)
                bot_info['cpu'] = stats['cpu']
                bot_info['memory'] = stats['memory']
                bot_info['status'] = 'running'
            else:
                bot_info['cpu'] = 0
                bot_info['memory'] = 0
                bot_info['status'] = 'stopped'
            
            user_bots.append(bot_info)
    
    return jsonify({'success': True, 'bots': user_bots})

@app.route('/api/bot/upload', methods=['POST'])
def upload_bot():
    """Upload a new bot file"""
    if 'bot_file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    
    file = request.files['bot_file']
    username = request.form.get('username')
    bot_name = request.form.get('bot_name')
    
    if not username or not bot_name:
        return jsonify({'success': False, 'message': 'Missing username or bot_name'}), 400
    
    # Check user bot limit
    user_bot_count = sum(1 for b in bots_db.values() if b['username'] == username)
    if user_bot_count >= MAX_BOTS_PER_USER:
        return jsonify({
            'success': False, 
            'message': f'Free tier limit: {MAX_BOTS_PER_USER} bots per user'
        }), 403
    
    if file and allowed_file(file.filename):
        bot_id = generate_bot_id(username, bot_name)
        filename = secure_filename(f"{bot_id}.{file.filename.rsplit('.', 1)[1]}")
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        file.save(filepath)
        
        # Store bot metadata
        bots_db[bot_id] = {
            'id': bot_id,
            'name': bot_name,
            'username': username,
            'filepath': filepath,
            'file_type': file.filename.rsplit('.', 1)[1],
            'created_at': datetime.now().isoformat(),
            'status': 'stopped'
        }
        
        return jsonify({
            'success': True, 
            'message': 'Bot uploaded successfully',
            'bot_id': bot_id
        })
    
    return jsonify({'success': False, 'message': 'Invalid file type'}), 400

@app.route('/api/bot/start/<bot_id>', methods=['POST'])
def start_bot(bot_id):
    """Start a bot"""
    if bot_id not in bots_db:
        return jsonify({'success': False, 'message': 'Bot not found'}), 404
    
    if bot_id in running_processes:
        return jsonify({'success': False, 'message': 'Bot already running'}), 400
    
    bot = bots_db[bot_id]
    filepath = bot['filepath']
    file_type = bot['file_type']
    
    try:
        # Determine how to run the bot
        if file_type == 'py':
            cmd = ['python3', filepath]
        elif file_type == 'js':
            cmd = ['node', filepath]
        else:
            return jsonify({'success': False, 'message': 'Unsupported file type'}), 400
        
        # Start the process
        log_file = os.path.join(UPLOAD_FOLDER, f"{bot_id}.log")
        with open(log_file, 'w') as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=UPLOAD_FOLDER
            )
        
        running_processes[bot_id] = {
            'pid': process.pid,
            'process': process,
            'log_file': log_file,
            'started_at': datetime.now().isoformat()
        }
        
        return jsonify({
            'success': True, 
            'message': 'Bot started successfully',
            'pid': process.pid
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to start bot: {str(e)}'}), 500

@app.route('/api/bot/stop/<bot_id>', methods=['POST'])
def stop_bot(bot_id):
    """Stop a running bot"""
    if bot_id not in running_processes:
        return jsonify({'success': False, 'message': 'Bot is not running'}), 400
    
    try:
        process = running_processes[bot_id]['process']
        process.terminate()
        process.wait(timeout=5)
        
        del running_processes[bot_id]
        
        return jsonify({'success': True, 'message': 'Bot stopped successfully'})
    
    except subprocess.TimeoutExpired:
        process.kill()
        del running_processes[bot_id]
        return jsonify({'success': True, 'message': 'Bot force-stopped'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to stop bot: {str(e)}'}), 500

@app.route('/api/bot/delete/<bot_id>', methods=['DELETE'])
def delete_bot(bot_id):
    """Delete a bot"""
    if bot_id not in bots_db:
        return jsonify({'success': False, 'message': 'Bot not found'}), 404
    
    # Stop if running
    if bot_id in running_processes:
        try:
            process = running_processes[bot_id]['process']
            process.terminate()
            process.wait(timeout=5)
            del running_processes[bot_id]
        except:
            pass
    
    # Delete files
    bot = bots_db[bot_id]
    try:
        if os.path.exists(bot['filepath']):
            os.remove(bot['filepath'])
        
        log_file = os.path.join(UPLOAD_FOLDER, f"{bot_id}.log")
        if os.path.exists(log_file):
            os.remove(log_file)
    except:
        pass
    
    # Remove from database
    del bots_db[bot_id]
    
    return jsonify({'success': True, 'message': 'Bot deleted successfully'})

@app.route('/api/bot/logs/<bot_id>', methods=['GET'])
def get_bot_logs(bot_id):
    """Get bot logs"""
    if bot_id not in bots_db:
        return jsonify({'success': False, 'message': 'Bot not found'}), 404
    
    log_file = os.path.join(UPLOAD_FOLDER, f"{bot_id}.log")
    
    if not os.path.exists(log_file):
        return jsonify({'success': True, 'logs': 'No logs available yet'})
    
    try:
        with open(log_file, 'r') as f:
            logs = f.read()
        
        # Return last 1000 lines to avoid huge responses
        lines = logs.split('\n')
        if len(lines) > 1000:
            logs = '\n'.join(lines[-1000:])
        
        return jsonify({'success': True, 'logs': logs})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to read logs: {str(e)}'}), 500

@app.route('/api/bot/status/<bot_id>', methods=['GET'])
def get_bot_status(bot_id):
    """Get detailed bot status"""
    if bot_id not in bots_db:
        return jsonify({'success': False, 'message': 'Bot not found'}), 404
    
    bot = bots_db[bot_id].copy()
    
    if bot_id in running_processes:
        pid = running_processes[bot_id]['pid']
        stats = get_process_stats(pid)
        bot['status'] = 'running'
        bot['cpu'] = stats['cpu']
        bot['memory'] = stats['memory']
        bot['started_at'] = running_processes[bot_id]['started_at']
    else:
        bot['status'] = 'stopped'
        bot['cpu'] = 0
        bot['memory'] = 0
    
    return jsonify({'success': True, 'bot': bot})

if __name__ == '__main__':
    # For Render deployment
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
