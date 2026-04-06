"""
Sega Channel ROM Editor — WYSIWYG menu editor

Provides a visual editor for Sega Channel menu ROMs.
The user uploads a ROM, sees the menu structure (categories + games),
and can edit entries, assign server games, and export patched ROMs.

Serves as a Flask blueprint added to the main web_app.
"""

import struct
import json
import os
from pathlib import Path
from flask import Blueprint, render_template_string, request, jsonify, send_file

rom_editor = Blueprint('rom_editor', __name__)

# Store uploaded ROM in memory
editor_state = {
    'rom_data': None,
    'rom_name': None,
    'entries': [],
}


def find_entries(rom):
    """Find all $0428 entries with their title locations in the ROM."""
    marker_0428 = bytes([0x04, 0x28])
    marker_name = bytes([0x04, 0x1C, 0x03, 0x08])

    entries = []
    idx = 0x100000

    while True:
        idx = rom.find(marker_0428, idx, len(rom))
        if idx < 0:
            break

        name_marker = rom.find(marker_name, idx, idx + 0x200)
        if name_marker < 0:
            idx += 2
            continue

        title_start = name_marker + 4
        title_end = rom.find(b'\x00', title_start, title_start + 32)
        if title_end < 0:
            title_end = title_start + 24

        title = rom[title_start:title_end].decode('ascii', errors='replace').strip()

        field_end = title_end
        while field_end < name_marker + 0x40 and rom[field_end] == 0x00:
            field_end += 1
        for check in range(title_end, min(title_end + 8, len(rom)), 2):
            w = struct.unpack('>H', rom[check:check+2])[0]
            if w == 0x0010 or w == 0x0000:
                field_end = check
                break

        title_field_size = field_end - title_start

        next_0428 = rom.find(marker_0428, idx + 2, idx + 0x2000)
        entry_size = next_0428 - idx if next_0428 > 0 else 0

        entries.append({
            'index': len(entries),
            'offset': idx,
            'title_offset': title_start,
            'title_field_size': title_field_size,
            'entry_size': entry_size,
            'title': title,
            'type': 'category' if len(entries) < 10 else 'game',
            'server_id': 0,
        })

        idx += 2

    return entries


EDITOR_PAGE = '''
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sega Channel ROM Editor</title>
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
  .container { max-width: 1400px; margin: 0 auto; padding: 24px 32px; }
  .card { background: #12122a; border: 1px solid #222255; border-radius: 8px; padding: 24px; margin-bottom: 20px; }
  .card h2 { color: #66aaff; margin-bottom: 16px; font-size: 18px; }
  .btn { display: inline-block; padding: 8px 20px; border: none; border-radius: 4px; font-size: 14px; cursor: pointer; text-decoration: none; transition: background 0.2s; }
  .btn-primary { background: #3366cc; color: white; }
  .btn-primary:hover { background: #4477dd; }
  .btn-success { background: #33aa55; color: white; }
  .btn-success:hover { background: #44bb66; }
  .btn-danger { background: #cc3333; color: white; }
  .btn-sm { padding: 4px 12px; font-size: 12px; }

  .editor-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .menu-preview { background: #1a1a3a; border: 1px solid #333366; border-radius: 8px; padding: 16px; }
  .menu-preview h3 { color: #ffcc00; margin-bottom: 12px; font-size: 16px; }

  .entry-list { list-style: none; }
  .entry-item { padding: 8px 12px; margin: 4px 0; border-radius: 4px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
  .entry-item:hover { background: #222255; }
  .entry-item.selected { background: #2a2a5a; border: 1px solid #4466aa; }
  .entry-item.category { border-left: 3px solid #ffcc00; }
  .entry-item.game { border-left: 3px solid #44cc44; }
  .entry-item .title { font-size: 14px; }
  .entry-item .meta { font-size: 11px; color: #667799; }
  .entry-item .index { color: #556677; font-size: 11px; margin-right: 8px; }

  .edit-panel { background: #1a1a3a; border: 1px solid #333366; border-radius: 8px; padding: 16px; }
  .edit-panel h3 { color: #66aaff; margin-bottom: 12px; }
  .form-group { margin-bottom: 12px; }
  .form-group label { display: block; color: #8899bb; margin-bottom: 4px; font-size: 13px; }
  .form-group input, .form-group select { background: #0a0a1a; border: 1px solid #333366; color: #e0e0e0; padding: 8px 12px; border-radius: 4px; width: 100%; font-size: 14px; }
  .form-group input:focus, .form-group select:focus { border-color: #5588cc; outline: none; }
  .char-count { font-size: 11px; color: #556677; float: right; }

  .upload-zone { border: 2px dashed #333366; border-radius: 8px; padding: 32px; text-align: center; color: #667799; }
  .flash { padding: 12px 16px; border-radius: 4px; margin-bottom: 16px; }
  .flash-success { background: #1a3a2a; border: 1px solid #33aa55; color: #66dd88; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 12px; }
  .tag-cat { background: #3a3a1a; color: #ccaa44; }
  .tag-game { background: #1a3a1a; color: #44cc44; }
</style>
</head>
<body>
<div class="header">
  <h1><span>SEGA</span> CHANNEL <span>ROM EDITOR</span></h1>
  <div class="subtitle">Visual Menu Editor</div>
</div>
<nav>
  <a href="/">Dashboard</a>
  <a href="/library">ROM Library</a>
  <a href="/catalog">Catalog Editor</a>
  <a href="/generator">Menu Generator</a>
  <a href="/editor" class="active">ROM Editor</a>
</nav>
<div class="container">

{% if not rom_loaded %}
<div class="card">
  <h2>Upload Sega Channel ROM</h2>
  <form method="POST" action="/editor/upload" enctype="multipart/form-data">
    <div class="upload-zone">
      <p>Select a Sega Channel menu ROM (.bin)</p>
      <input type="file" name="rom" accept=".bin,.BIN" style="margin: 12px 0;">
      <br>
      <button class="btn btn-primary" type="submit">Load ROM</button>
    </div>
  </form>
</div>
{% else %}

{% if flash %}
<div class="flash flash-success">{{ flash }}</div>
{% endif %}

<div class="card" style="margin-bottom: 12px;">
  <div style="display: flex; justify-content: space-between; align-items: center;">
    <div>
      <strong>{{ rom_name }}</strong>
      <span style="color: #667799; margin-left: 12px;">{{ entries|length }} entries ({{ categories }} categories, {{ games }} games)</span>
    </div>
    <div>
      <a href="/editor/export" class="btn btn-success btn-sm">Export Patched ROM</a>
      <form method="POST" action="/editor/upload" enctype="multipart/form-data" style="display: inline;">
        <input type="file" name="rom" accept=".bin" style="display:none;" id="reupload"
               onchange="this.form.submit();">
        <button class="btn btn-primary btn-sm" type="button"
                onclick="document.getElementById('reupload').click();">Load Different ROM</button>
      </form>
    </div>
  </div>
</div>

<div class="editor-layout">
  <div class="menu-preview">
    <h3>Menu Structure</h3>
    <ul class="entry-list" id="entry-list">
      {% for entry in entries %}
      <li class="entry-item {{ entry.type }} {% if entry.index == selected %}selected{% endif %}"
          onclick="selectEntry({{ entry.index }})">
        <div>
          <span class="index">[{{ entry.index }}]</span>
          <span class="title">{{ entry.title or '(empty)' }}</span>
        </div>
        <div>
          <span class="tag tag-{{ entry.type[:3] }}">{{ entry.type }}</span>
          {% if entry.server_id > 0 %}
          <span class="tag" style="background:#1a2a4a; color:#6699cc;">ID:{{ entry.server_id }}</span>
          {% endif %}
        </div>
      </li>
      {% endfor %}
    </ul>
  </div>

  <div class="edit-panel" id="edit-panel">
    <h3>Edit Entry</h3>
    {% if selected is not none and selected_entry %}
    <form method="POST" action="/editor/update">
      <input type="hidden" name="index" value="{{ selected }}">

      <div class="form-group">
        <label>Type</label>
        <input type="text" value="{{ selected_entry.type }}" disabled>
      </div>

      <div class="form-group">
        <label>Title <span class="char-count">{{ selected_entry.title|length }}/{{ selected_entry.title_field_size }} chars</span></label>
        <input type="text" name="title" value="{{ selected_entry.title }}"
               maxlength="{{ selected_entry.title_field_size }}">
      </div>

      {% if selected_entry.type == 'game' %}
      <div class="form-group">
        <label>Server Game ID</label>
        <select name="server_id">
          <option value="0">-- Not assigned --</option>
          {% for game in server_games %}
          <option value="{{ game.id }}" {{ 'selected' if game.id == selected_entry.server_id }}>{{ game.id }}. {{ game.title }}</option>
          {% endfor %}
        </select>
      </div>
      {% endif %}

      <div class="form-group">
        <label>ROM Offset</label>
        <input type="text" value="${{ '%06X' % selected_entry.offset }}" disabled>
      </div>

      <button class="btn btn-success" type="submit">Save Changes</button>
    </form>
    {% else %}
    <p style="color: #667799;">Click an entry on the left to edit it.</p>
    {% endif %}
  </div>
</div>

{% endif %}
</div>

<script>
function selectEntry(index) {
  window.location.href = '/editor?selected=' + index;
}
</script>
</body>
</html>
'''


@rom_editor.route('/editor')
def editor():
    selected = request.args.get('selected', None)
    selected_entry = None
    flash_msg = request.args.get('flash', '')

    if selected is not None:
        selected = int(selected)
        for e in editor_state['entries']:
            if e['index'] == selected:
                selected_entry = e
                break

    # Get server games for the dropdown
    server_games = []
    try:
        import urllib.request
        resp = urllib.request.urlopen('http://localhost:8080/api/games')
        server_games = json.loads(resp.read())
    except Exception:
        pass

    categories = sum(1 for e in editor_state['entries'] if e['type'] == 'category')
    games = sum(1 for e in editor_state['entries'] if e['type'] == 'game')

    return render_template_string(EDITOR_PAGE,
        rom_loaded=editor_state['rom_data'] is not None,
        rom_name=editor_state['rom_name'],
        entries=editor_state['entries'][:60],  # Show first 60 (categories + games)
        categories=categories,
        games=games,
        selected=selected,
        selected_entry=selected_entry,
        server_games=server_games[:200],  # Limit dropdown
        flash=flash_msg,
    )


@rom_editor.route('/editor/upload', methods=['POST'])
def editor_upload():
    f = request.files.get('rom')
    if f and f.filename:
        editor_state['rom_data'] = bytearray(f.read())
        editor_state['rom_name'] = f.filename
        editor_state['entries'] = find_entries(editor_state['rom_data'])
        return editor()
    return editor()


@rom_editor.route('/editor/update', methods=['POST'])
def editor_update():
    index = int(request.form.get('index', -1))
    title = request.form.get('title', '')
    server_id = int(request.form.get('server_id', 0))

    if editor_state['rom_data'] and 0 <= index < len(editor_state['entries']):
        entry = editor_state['entries'][index]

        # Patch the title in the ROM data
        new_title = title.strip()
        offset = entry['title_offset']
        field_size = entry['title_field_size']

        # Center the title
        if len(new_title) < field_size:
            padding = (field_size - len(new_title)) // 2
            padded = ' ' * padding + new_title + ' ' * (field_size - len(new_title) - padding)
        else:
            padded = new_title[:field_size]

        for i, ch in enumerate(padded.encode('ascii', errors='replace')):
            if offset + i < len(editor_state['rom_data']):
                editor_state['rom_data'][offset + i] = ch

        # Update entry
        entry['title'] = new_title
        entry['server_id'] = server_id

    from flask import redirect, url_for
    return redirect(f'/editor?selected={index}&flash=Entry updated!')


@rom_editor.route('/editor/export')
def editor_export():
    if editor_state['rom_data']:
        import tempfile
        out_name = (editor_state['rom_name'] or 'SegaChannel').replace('.bin', '_Patched.bin').replace('.BIN', '_Patched.bin')
        out_path = os.path.join(tempfile.gettempdir(), out_name)
        with open(out_path, 'wb') as f:
            f.write(editor_state['rom_data'])
        return send_file(out_path, as_attachment=True, download_name=out_name)
    return 'No ROM loaded', 400


@rom_editor.route('/editor/entries')
def editor_entries_api():
    """API endpoint returning entries as JSON."""
    return jsonify(editor_state['entries'][:60])
