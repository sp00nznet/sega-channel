"""
Sega Channel Web Management Interface

Flask web app that provides:
- Server status and control (start/stop TCP game server)
- ROM library management (browse, upload, delete)
- SCMENU.BIN generator (catalog editor, build custom menu data)
- Live game catalog view

Runs the TCP game server in a background thread alongside the web UI.

Usage:
    python web_app.py [--port 8080] [--roms ./roms] [--menudata SCMENU.BIN]
"""

import os
import sys
import json
import struct
import threading
import argparse
import time
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify, send_file, redirect, url_for

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from sc_server import GameLibrary, SegaChannelServer

app = Flask(__name__)

# Global state
server_state = {
    'library': None,
    'tcp_server': None,
    'tcp_thread': None,
    'running': False,
    'roms_dir': './roms',
    'menudata_path': None,
    'tcp_port': 7654,
    'template_path': None,
}

# ─── HTML Templates ───────────────────────────────────────────────

LAYOUT = '''
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sega Channel Server</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0a1a; color: #e0e0e0; }
  .header { background: linear-gradient(135deg, #1a1a4e 0%, #0d2847 100%); padding: 20px 32px; border-bottom: 3px solid #3366cc; }
  .header h1 { font-size: 28px; color: #66aaff; }
  .header h1 span { color: #ffcc00; }
  .header .subtitle { color: #8899bb; font-size: 14px; margin-top: 4px; }
  nav { background: #111133; padding: 0 32px; display: flex; gap: 0; border-bottom: 1px solid #222255; }
  nav a { color: #8899bb; text-decoration: none; padding: 14px 20px; font-size: 14px; border-bottom: 2px solid transparent; transition: all 0.2s; }
  nav a:hover { color: #aabbdd; background: #1a1a44; }
  nav a.active { color: #66aaff; border-bottom-color: #66aaff; }
  .container { max-width: 1100px; margin: 0 auto; padding: 24px 32px; }
  .card { background: #12122a; border: 1px solid #222255; border-radius: 8px; padding: 24px; margin-bottom: 20px; }
  .card h2 { color: #66aaff; margin-bottom: 16px; font-size: 18px; }
  .card h3 { color: #99bbdd; margin: 16px 0 8px; font-size: 15px; }
  .status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
  .status-dot.on { background: #44cc44; box-shadow: 0 0 6px #44cc44; }
  .status-dot.off { background: #cc4444; }
  .btn { display: inline-block; padding: 8px 20px; border: none; border-radius: 4px; font-size: 14px; cursor: pointer; text-decoration: none; transition: background 0.2s; }
  .btn-primary { background: #3366cc; color: white; }
  .btn-primary:hover { background: #4477dd; }
  .btn-danger { background: #cc3333; color: white; }
  .btn-danger:hover { background: #dd4444; }
  .btn-success { background: #33aa55; color: white; }
  .btn-success:hover { background: #44bb66; }
  .btn-sm { padding: 4px 12px; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #1a1a3a; }
  th { color: #8899bb; font-weight: 600; font-size: 13px; text-transform: uppercase; }
  tr:hover { background: #1a1a3a; }
  input[type="text"], input[type="number"], textarea, select { background: #0a0a1a; border: 1px solid #333366; color: #e0e0e0; padding: 8px 12px; border-radius: 4px; width: 100%; font-size: 14px; }
  input:focus, textarea:focus, select:focus { border-color: #5588cc; outline: none; }
  textarea { font-family: monospace; min-height: 200px; resize: vertical; }
  .form-group { margin-bottom: 16px; }
  .form-group label { display: block; color: #8899bb; margin-bottom: 6px; font-size: 13px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .stat-box { text-align: center; padding: 16px; }
  .stat-box .num { font-size: 36px; color: #66aaff; font-weight: 700; }
  .stat-box .label { color: #667799; font-size: 13px; margin-top: 4px; }
  .flash { padding: 12px 16px; border-radius: 4px; margin-bottom: 16px; }
  .flash-success { background: #1a3a2a; border: 1px solid #33aa55; color: #66dd88; }
  .flash-error { background: #3a1a1a; border: 1px solid #cc3333; color: #ff6666; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 12px; background: #1a2a4a; color: #6699cc; }
  .upload-zone { border: 2px dashed #333366; border-radius: 8px; padding: 32px; text-align: center; color: #667799; }
  .upload-zone:hover { border-color: #5588cc; color: #8899bb; }
  code { background: #0a0a2a; padding: 2px 6px; border-radius: 3px; font-size: 13px; color: #99bbdd; }
</style>
</head>
<body>
<div class="header">
  <h1><span>SEGA</span> CHANNEL <span>SERVER</span></h1>
  <div class="subtitle">Game Streaming Backend</div>
</div>
<nav>
  <a href="/" class="{{ 'active' if page == 'dashboard' }}">Dashboard</a>
  <a href="/library" class="{{ 'active' if page == 'library' }}">ROM Library</a>
  <a href="/catalog" class="{{ 'active' if page == 'catalog' }}">Catalog Editor</a>
  <a href="/generator" class="{{ 'active' if page == 'generator' }}">Menu Generator</a>
</nav>
<div class="container">
{% block content %}{% endblock %}
</div>
</body>
</html>
'''

DASHBOARD_PAGE = LAYOUT.replace('{% block content %}{% endblock %}', '''
{% if flash %}
<div class="flash flash-{{ flash_type }}">{{ flash }}</div>
{% endif %}

<div class="grid-2">
  <div class="card">
    <h2>Server Status</h2>
    <p style="font-size: 18px; margin-bottom: 16px;">
      <span class="status-dot {{ 'on' if running else 'off' }}"></span>
      {{ 'Running' if running else 'Stopped' }}
    </p>
    <p style="color: #667799; margin-bottom: 16px;">
      TCP Port: <code>{{ tcp_port }}</code><br>
      ROMs Dir: <code>{{ roms_dir }}</code>
    </p>
    {% if running %}
    <form method="POST" action="/server/stop" style="display:inline;">
      <button class="btn btn-danger" type="submit">Stop Server</button>
    </form>
    {% else %}
    <form method="POST" action="/server/start" style="display:inline;">
      <button class="btn btn-success" type="submit">Start Server</button>
    </form>
    {% endif %}
    <form method="POST" action="/library/rescan" style="display:inline; margin-left: 8px;">
      <button class="btn btn-primary" type="submit">Rescan ROMs</button>
    </form>
  </div>

  <div class="card">
    <div class="grid-2">
      <div class="stat-box">
        <div class="num">{{ game_count }}</div>
        <div class="label">Games Available</div>
      </div>
      <div class="stat-box">
        <div class="num">{{ total_size_mb }}</div>
        <div class="label">Total Size (MB)</div>
      </div>
    </div>
  </div>
</div>

<div class="card">
  <h2>Quick Connect</h2>
  <p style="color: #667799; margin-bottom: 12px;">Point your emulator at this server:</p>
  <code style="font-size: 16px; display: block; padding: 12px; background: #0a0a2a; border-radius: 4px;">
    SC_SERVER_HOST=127.0.0.1 SC_SERVER_PORT={{ tcp_port }}
  </code>
</div>

<div class="card">
  <h2>Game Library</h2>
  <table>
    <tr><th>#</th><th>Title</th><th>Size</th></tr>
    {% for game in games %}
    <tr>
      <td>{{ game.id }}</td>
      <td>{{ game.title }}</td>
      <td><span class="tag">{{ game.size_kb }} KB</span></td>
    </tr>
    {% endfor %}
    {% if not games %}
    <tr><td colspan="3" style="color: #667799; text-align: center; padding: 24px;">
      No ROMs found. Add ROM files to <code>{{ roms_dir }}</code> and click Rescan.
    </td></tr>
    {% endif %}
  </table>
</div>

<div class="card">
  <h2>Queue Game for Play</h2>
  <p style="color: #667799; margin-bottom: 12px;">Select a game here, then choose any game in the Sega Channel menu to load it.</p>
  <form method="POST" action="/queue">
    <select name="game_id" style="width: 400px;">
      {% for game in games %}
      <option value="{{ game.id }}" {{ 'selected' if game.id == queued_id }}>{{ game.id }}. {{ game.title }}</option>
      {% endfor %}
    </select>
    <button class="btn btn-success" type="submit">Queue</button>
    {% if queued_id > 0 %}
    <span style="color: #44cc44; margin-left: 12px;">Queued: #{{ queued_id }}</span>
    {% endif %}
  </form>
</div>
''')

LIBRARY_PAGE = LAYOUT.replace('{% block content %}{% endblock %}', '''
{% if flash %}
<div class="flash flash-{{ flash_type }}">{{ flash }}</div>
{% endif %}

<div class="card">
  <h2>Upload ROMs</h2>
  <form method="POST" action="/library/upload" enctype="multipart/form-data">
    <div class="upload-zone">
      <p>Select Genesis ROM files (.bin, .gen, .md)</p>
      <input type="file" name="roms" multiple accept=".bin,.gen,.md,.smd" style="margin: 12px 0;">
      <br>
      <button class="btn btn-primary" type="submit">Upload</button>
    </div>
  </form>
</div>

<div class="card">
  <h2>ROM Files ({{ games|length }})</h2>
  <table>
    <tr><th>#</th><th>Title</th><th>File</th><th>Size</th><th>Actions</th></tr>
    {% for game in games %}
    <tr>
      <td>{{ game.id }}</td>
      <td>{{ game.title }}</td>
      <td><code>{{ game.filename }}</code></td>
      <td><span class="tag">{{ game.size_kb }} KB</span></td>
      <td>
        <form method="POST" action="/library/delete/{{ game.id }}" style="display:inline;">
          <button class="btn btn-danger btn-sm" type="submit">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
''')

CATALOG_PAGE = LAYOUT.replace('{% block content %}{% endblock %}', '''
{% if flash %}
<div class="flash flash-{{ flash_type }}">{{ flash }}</div>
{% endif %}

<div class="card">
  <h2>Game Catalog Editor</h2>
  <p style="color: #667799; margin-bottom: 16px;">
    Edit the JSON catalog that defines menu categories and game assignments.
    This catalog is used to generate SCMENU.BIN files and is served to the emulator.
  </p>
  <form method="POST" action="/catalog/save">
    <div class="form-group">
      <label>Catalog JSON</label>
      <textarea name="catalog_json" id="catalog_json">{{ catalog_json }}</textarea>
    </div>
    <button class="btn btn-primary" type="submit">Save Catalog</button>
    <button class="btn btn-success" type="button" onclick="autoGenerate()">Auto-Generate from Library</button>
  </form>
</div>

<script>
function autoGenerate() {
  fetch('/catalog/auto-generate').then(r => r.json()).then(data => {
    document.getElementById('catalog_json').value = JSON.stringify(data, null, 2);
  });
}
</script>
''')

GENERATOR_PAGE = LAYOUT.replace('{% block content %}{% endblock %}', '''
{% if flash %}
<div class="flash flash-{{ flash_type }}">{{ flash }}</div>
{% endif %}

<div class="card">
  <h2>SCMENU.BIN Generator</h2>
  <p style="color: #667799; margin-bottom: 16px;">
    Generate a custom SCMENU.BIN menu data file from the current catalog.
    Requires a template SCMENU.BIN for graphical assets.
  </p>

  <form method="POST" action="/generator/build" enctype="multipart/form-data">
    <div class="grid-2">
      <div class="form-group">
        <label>Template SCMENU.BIN (for graphics/tiles)</label>
        {% if template_available %}
        <p style="color: #44cc44;">Using: <code>{{ template_path }}</code></p>
        {% else %}
        <input type="file" name="template" accept=".bin,.BIN">
        <p style="color: #cc9944; margin-top: 4px; font-size: 12px;">Upload an original SCMENU.BIN as the graphics template</p>
        {% endif %}
      </div>
      <div class="form-group">
        <label>Output Filename</label>
        <input type="text" name="output_name" value="SCMENU_CUSTOM.BIN">
      </div>
    </div>
    <button class="btn btn-success" type="submit">Generate SCMENU.BIN</button>
  </form>
</div>

{% if generated_files %}
<div class="card">
  <h2>Generated Files</h2>
  <table>
    <tr><th>File</th><th>Size</th><th>Created</th><th>Actions</th></tr>
    {% for f in generated_files %}
    <tr>
      <td><code>{{ f.name }}</code></td>
      <td><span class="tag">{{ f.size_kb }} KB</span></td>
      <td>{{ f.created }}</td>
      <td><a href="/generator/download/{{ f.name }}" class="btn btn-primary btn-sm">Download</a></td>
    </tr>
    {% endfor %}
  </table>
</div>
{% endif %}
''')


# ─── Routes ───────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    lib = server_state['library']
    games = []
    total_size = 0
    if lib:
        for gid, info in sorted(lib.games.items()):
            games.append({
                'id': gid,
                'title': info['title'],
                'size_kb': info['size'] // 1024,
            })
            total_size += info['size']

    flash_msg = request.args.get('flash', '')
    flash_type = request.args.get('flash_type', 'success')

    import sc_server
    return render_template_string(DASHBOARD_PAGE,
        page='dashboard',
        running=server_state['running'],
        tcp_port=server_state['tcp_port'],
        roms_dir=server_state['roms_dir'],
        game_count=len(games),
        total_size_mb=f"{total_size / 1048576:.1f}",
        games=games,
        queued_id=sc_server.queued_game_id,
        flash=flash_msg,
        flash_type=flash_type,
    )

@app.route('/queue', methods=['POST'])
def queue_game():
    import sc_server
    game_id = int(request.form.get('game_id', 0))
    sc_server.queued_game_id = game_id
    return redirect(url_for('dashboard', flash=f'Queued game #{game_id}', flash_type='success'))

@app.route('/server/start', methods=['POST'])
def server_start():
    if not server_state['running']:
        _start_tcp_server()
    return redirect(url_for('dashboard', flash='TCP server started', flash_type='success'))

@app.route('/server/stop', methods=['POST'])
def server_stop():
    if server_state['running']:
        _stop_tcp_server()
    return redirect(url_for('dashboard', flash='TCP server stopped', flash_type='success'))

@app.route('/library')
def library():
    lib = server_state['library']
    games = []
    if lib:
        for gid, info in sorted(lib.games.items()):
            fname = info.get('zip_entry', None) or info['path'].name
            games.append({
                'id': gid,
                'title': info['title'],
                'filename': fname if isinstance(fname, str) else info['path'].name,
                'size_kb': info['size'] // 1024,
            })

    flash_msg = request.args.get('flash', '')
    flash_type = request.args.get('flash_type', 'success')

    return render_template_string(LIBRARY_PAGE,
        page='library',
        games=games,
        flash=flash_msg,
        flash_type=flash_type,
    )

@app.route('/library/upload', methods=['POST'])
def library_upload():
    roms_dir = Path(server_state['roms_dir'])
    roms_dir.mkdir(parents=True, exist_ok=True)

    files = request.files.getlist('roms')
    count = 0
    for f in files:
        if f.filename:
            dest = roms_dir / f.filename
            f.save(str(dest))
            count += 1

    if server_state['library']:
        server_state['library'].scan_roms()

    return redirect(url_for('library', flash=f'Uploaded {count} file(s)', flash_type='success'))

@app.route('/library/delete/<int:game_id>', methods=['POST'])
def library_delete(game_id):
    lib = server_state['library']
    if lib and game_id in lib.games:
        path = lib.games[game_id]['path']
        title = lib.games[game_id]['title']
        try:
            path.unlink()
            lib.scan_roms()
            return redirect(url_for('library', flash=f'Deleted {title}', flash_type='success'))
        except Exception as e:
            return redirect(url_for('library', flash=f'Error: {e}', flash_type='error'))

    return redirect(url_for('library', flash='Game not found', flash_type='error'))

@app.route('/library/rescan', methods=['POST'])
def library_rescan():
    if server_state['library']:
        server_state['library'].scan_roms()
    return redirect(url_for('dashboard', flash='ROM library rescanned', flash_type='success'))

@app.route('/catalog')
def catalog():
    catalog_path = Path(server_state['roms_dir']) / 'catalog.json'
    catalog_json = '{}'
    if catalog_path.exists():
        catalog_json = catalog_path.read_text()
    else:
        # Auto-generate from current library
        catalog_json = json.dumps(_auto_generate_catalog(), indent=2)

    flash_msg = request.args.get('flash', '')
    flash_type = request.args.get('flash_type', 'success')

    return render_template_string(CATALOG_PAGE,
        page='catalog',
        catalog_json=catalog_json,
        flash=flash_msg,
        flash_type=flash_type,
    )

@app.route('/catalog/save', methods=['POST'])
def catalog_save():
    catalog_json = request.form.get('catalog_json', '{}')
    try:
        # Validate JSON
        json.loads(catalog_json)
        catalog_path = Path(server_state['roms_dir']) / 'catalog.json'
        catalog_path.write_text(catalog_json)
        return redirect(url_for('catalog', flash='Catalog saved', flash_type='success'))
    except json.JSONDecodeError as e:
        return redirect(url_for('catalog', flash=f'Invalid JSON: {e}', flash_type='error'))

@app.route('/catalog/auto-generate')
def catalog_auto_generate():
    return jsonify(_auto_generate_catalog())

@app.route('/generator')
def generator():
    # Check for generated files
    output_dir = Path(server_state['roms_dir']) / 'generated'
    generated_files = []
    if output_dir.exists():
        for f in sorted(output_dir.iterdir()):
            if f.suffix.upper() == '.BIN':
                stat = f.stat()
                generated_files.append({
                    'name': f.name,
                    'size_kb': stat.st_size // 1024,
                    'created': time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime)),
                })

    template_path = server_state.get('template_path', '')
    template_available = template_path and Path(template_path).exists()

    flash_msg = request.args.get('flash', '')
    flash_type = request.args.get('flash_type', 'success')

    return render_template_string(GENERATOR_PAGE,
        page='generator',
        template_available=template_available,
        template_path=template_path,
        generated_files=generated_files,
        flash=flash_msg,
        flash_type=flash_type,
    )

@app.route('/generator/build', methods=['POST'])
def generator_build():
    output_name = request.form.get('output_name', 'SCMENU_CUSTOM.BIN')
    output_dir = Path(server_state['roms_dir']) / 'generated'
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name

    # Get template
    template_path = server_state.get('template_path', '')
    if not template_path or not Path(template_path).exists():
        # Check if uploaded
        template_file = request.files.get('template')
        if template_file and template_file.filename:
            template_path = str(output_dir / 'TEMPLATE_SCMENU.BIN')
            template_file.save(template_path)
            server_state['template_path'] = template_path
        else:
            return redirect(url_for('generator', flash='No template file provided', flash_type='error'))

    # Load catalog
    catalog_path = Path(server_state['roms_dir']) / 'catalog.json'
    if catalog_path.exists():
        with open(catalog_path) as f:
            catalog_data = json.load(f)
    else:
        catalog_data = _auto_generate_catalog()

    # Build SCMENU.BIN
    try:
        from scmenu_build import ScMenuBuilder
        builder = ScMenuBuilder(template_path)
        builder.build(catalog_data, str(output_path))
        return redirect(url_for('generator', flash=f'Generated {output_name}', flash_type='success'))
    except Exception as e:
        return redirect(url_for('generator', flash=f'Build error: {e}', flash_type='error'))

@app.route('/generator/download/<filename>')
def generator_download(filename):
    output_dir = Path(server_state['roms_dir']) / 'generated'
    file_path = output_dir / filename
    if file_path.exists():
        return send_file(str(file_path.resolve()), as_attachment=True)
    return "File not found", 404


# ─── API endpoints ────────────────────────────────────────────────

@app.route('/api/status')
def api_status():
    lib = server_state['library']
    return jsonify({
        'running': server_state['running'],
        'tcp_port': server_state['tcp_port'],
        'game_count': len(lib.games) if lib else 0,
    })

@app.route('/api/games')
def api_games():
    lib = server_state['library']
    if not lib:
        return jsonify([])
    return jsonify([
        {'id': gid, 'title': info['title'], 'size': info['size']}
        for gid, info in sorted(lib.games.items())
    ])


# ─── Helper functions ─────────────────────────────────────────────

def _auto_generate_catalog():
    """Generate a catalog from the current ROM library."""
    lib = server_state['library']
    if not lib or not lib.games:
        return {"categories": [{"name": "All Games", "games": []}]}

    # Simple: put all games in one category
    games_list = []
    for gid, info in sorted(lib.games.items()):
        games_list.append({
            "id": gid,
            "title": info['title'],
            "description": f"Play {info['title']}!"
        })

    # Split into categories of ~10 games each
    categories = []
    cat_names = ["The Arcade", "Sports Arena", "Strategy Room", "Family Room",
                 "The Dungeon", "The Speedway", "Prize-O-Rama"]
    chunk_size = max(1, (len(games_list) + len(cat_names) - 1) // len(cat_names))

    for i in range(0, len(games_list), chunk_size):
        cat_idx = i // chunk_size
        cat_name = cat_names[cat_idx] if cat_idx < len(cat_names) else f"Category {cat_idx + 1}"
        categories.append({
            "name": cat_name,
            "games": games_list[i:i + chunk_size]
        })

    if not categories:
        categories = [{"name": "All Games", "games": []}]

    return {"categories": categories}

def _start_tcp_server():
    """Start the TCP game server in a background thread."""
    if server_state['running']:
        return

    lib = server_state['library']
    tcp = SegaChannelServer(server_state['tcp_port'], lib)
    server_state['tcp_server'] = tcp
    server_state['running'] = True

    def run_server():
        try:
            tcp.start()
        except Exception:
            pass
        finally:
            server_state['running'] = False

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    server_state['tcp_thread'] = t

def _stop_tcp_server():
    """Stop the TCP game server."""
    tcp = server_state.get('tcp_server')
    if tcp and tcp.server_socket:
        tcp.running = False
        try:
            tcp.server_socket.close()
        except Exception:
            pass
    server_state['running'] = False
    server_state['tcp_server'] = None


# ─── Main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Sega Channel Web Management')
    parser.add_argument('--port', type=int, default=8080,
                        help='Web UI port (default: 8080)')
    parser.add_argument('--tcp-port', type=int, default=7654,
                        help='TCP game server port (default: 7654)')
    parser.add_argument('--roms', type=str, default='./roms',
                        help='ROM directory (default: ./roms)')
    parser.add_argument('--menudata', type=str, default=None,
                        help='Path to SCMENU.BIN template')
    parser.add_argument('--auto-start', action='store_true',
                        help='Automatically start TCP server on launch')
    args = parser.parse_args()

    # Create roms directory if needed
    Path(args.roms).mkdir(parents=True, exist_ok=True)

    # Initialize library
    server_state['roms_dir'] = args.roms
    server_state['tcp_port'] = args.tcp_port
    server_state['template_path'] = args.menudata
    server_state['library'] = GameLibrary(args.roms, args.menudata)

    if args.auto_start:
        _start_tcp_server()

    print(f"\n  Sega Channel Web UI: http://localhost:{args.port}")
    print(f"  TCP Game Server:     port {args.tcp_port} ({'running' if server_state['running'] else 'stopped'})")
    print(f"  ROM Directory:       {args.roms}")
    print()

    app.run(host='0.0.0.0', port=args.port, debug=False)


if __name__ == '__main__':
    main()
