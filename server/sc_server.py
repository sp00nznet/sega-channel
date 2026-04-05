"""
Sega Channel Backend Server

Replaces the cable TV headend for the Sega Channel adapter.
Serves game ROMs to the emulator over a simple TCP protocol.

Protocol (all multi-byte values are big-endian):

  Client → Server:
    CMD_CATALOG  (0x01)              → Server sends game catalog
    CMD_FETCH    (0x02) + game_id(2) → Server streams ROM data
    CMD_MENUDATA (0x03)              → Server sends SCMENU.BIN
    CMD_PING     (0xFF)              → Server sends PONG

  Server → Client:
    RSP_CATALOG  (0x01) + count(2) + [id(2) + title_len(1) + title + size(4)] * count
    RSP_ROMDATA  (0x02) + size(4) + data[size]
    RSP_MENUDATA (0x03) + size(4) + data[size]
    RSP_ERROR    (0xFE) + msg_len(1) + msg
    RSP_PONG     (0xFF)

Usage:
    python sc_server.py [--port PORT] [--roms ROMS_DIR] [--menudata SCMENU.BIN]
"""

import os
import sys
import json
import struct
import socket
import threading
import argparse
import hashlib
import zipfile
from pathlib import Path

# Protocol constants
CMD_CATALOG  = 0x01
CMD_FETCH    = 0x02
CMD_MENUDATA = 0x03
CMD_PING     = 0xFF

RSP_CATALOG  = 0x01
RSP_ROMDATA  = 0x02
RSP_MENUDATA = 0x03
RSP_ERROR    = 0xFE
RSP_PONG     = 0xFF

CMD_QUEUE    = 0x04  # Query queued game ID

RSP_QUEUE    = 0x04

DEFAULT_PORT = 7654

# Queued game ID (set by web UI, read by emulator)
queued_game_id = 0


class GameLibrary:
    """Manages the collection of Genesis ROMs available to serve."""

    def __init__(self, roms_dir, menudata_path=None):
        self.roms_dir = Path(roms_dir)
        self.menudata_path = Path(menudata_path) if menudata_path else None
        self.games = {}  # id → {title, path, size, checksum}
        self.scan_roms()

    def scan_roms(self):
        """Scan the ROM directory and build the game catalog.
        Supports both bare ROM files and zipped ROMs."""
        self.games = {}
        game_id = 1

        if not self.roms_dir.exists():
            print(f"[WARN] ROM directory does not exist: {self.roms_dir}")
            return

        rom_extensions = {'.bin', '.gen', '.md', '.smd'}
        files = sorted(self.roms_dir.iterdir())

        for fpath in files:
            if not fpath.is_file():
                continue

            if fpath.suffix.lower() == '.zip':
                # Zipped ROM — find the ROM file inside
                info = self._scan_zip(fpath)
                if info:
                    self.games[game_id] = info
                    game_id += 1
            elif fpath.suffix.lower() in rom_extensions:
                size = fpath.stat().st_size
                if size < 0x200 or size > 0x400000:
                    continue
                title = self._read_rom_title_from_data(self._read_header_bytes(fpath))
                if not title:
                    title = fpath.stem
                self.games[game_id] = {
                    'title': title,
                    'path': fpath,
                    'zip_entry': None,
                    'size': size,
                }
                game_id += 1

        print(f"[INFO] Loaded {len(self.games)} games from {self.roms_dir}")
        for gid, info in list(self.games.items())[:20]:
            try:
                print(f"  [{gid:3d}] {info['title']} ({info['size'] / 1024:.0f} KB)")
            except (UnicodeEncodeError, UnicodeDecodeError):
                print(f"  [{gid:3d}] (title has special chars) ({info['size'] / 1024:.0f} KB)")
        if len(self.games) > 20:
            print(f"  ... and {len(self.games) - 20} more")

    def _scan_zip(self, zip_path):
        """Scan a zip file for a Genesis ROM and return its info."""
        rom_extensions = {'.bin', '.gen', '.md', '.smd'}
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for entry in zf.namelist():
                    ext = os.path.splitext(entry)[1].lower()
                    if ext in rom_extensions:
                        info = zf.getinfo(entry)
                        if info.file_size < 0x200 or info.file_size > 0x400000:
                            continue
                        # Read header to get title
                        with zf.open(entry) as rf:
                            header_data = rf.read(0x200)
                        title = self._read_rom_title_from_data(header_data)
                        if not title:
                            title = os.path.splitext(os.path.basename(entry))[0]
                        return {
                            'title': title,
                            'path': zip_path,
                            'zip_entry': entry,
                            'size': info.file_size,
                        }
        except Exception:
            pass
        return None

    def _read_header_bytes(self, path):
        """Read the first 0x200 bytes from a file."""
        try:
            with open(path, 'rb') as f:
                return f.read(0x200)
        except Exception:
            return b''

    def _read_rom_title_from_data(self, header_data):
        """Extract the domestic title from Genesis ROM header bytes."""
        if len(header_data) < 0x150:
            return None
        console = header_data[0x100:0x110].decode('ascii', errors='replace').strip()
        if 'SEGA' not in console.upper():
            return None
        title = header_data[0x120:0x150].decode('ascii', errors='replace').strip('\x00').strip()
        return title if title else None

    def get_catalog(self):
        """Return the game catalog as a list of (id, title, size) tuples."""
        return [(gid, info['title'], info['size'])
                for gid, info in sorted(self.games.items())]

    def get_rom_data(self, game_id):
        """Read and return the ROM data for a given game ID."""
        if game_id not in self.games:
            return None
        info = self.games[game_id]
        if info.get('zip_entry'):
            # Read from zip
            try:
                with zipfile.ZipFile(info['path'], 'r') as zf:
                    return zf.read(info['zip_entry'])
            except Exception:
                return None
        else:
            with open(info['path'], 'rb') as f:
                return f.read()

    def get_menudata(self):
        """Read and return the SCMENU.BIN data."""
        if self.menudata_path and self.menudata_path.exists():
            with open(self.menudata_path, 'rb') as f:
                return f.read()
        return None


class ClientHandler:
    """Handles a single client connection."""

    def __init__(self, conn, addr, library):
        self.conn = conn
        self.addr = addr
        self.library = library
        self.running = True

    def handle(self):
        """Main client loop — read commands, send responses."""
        print(f"[CONN] Client connected from {self.addr}")

        try:
            while self.running:
                # Read command byte
                cmd_byte = self._recv_exact(1)
                if not cmd_byte:
                    break

                cmd = cmd_byte[0]

                if cmd == CMD_PING:
                    self._handle_ping()
                elif cmd == CMD_CATALOG:
                    self._handle_catalog()
                elif cmd == CMD_FETCH:
                    self._handle_fetch()
                elif cmd == CMD_MENUDATA:
                    self._handle_menudata()
                elif cmd == CMD_QUEUE:
                    self._handle_queue()
                else:
                    self._send_error(f"Unknown command: 0x{cmd:02X}")

        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            print(f"[ERR]  Client {self.addr}: {e}")
        finally:
            print(f"[DISC] Client disconnected: {self.addr}")
            self.conn.close()

    def _handle_ping(self):
        """Respond to a ping with a pong."""
        self.conn.sendall(bytes([RSP_PONG]))

    def _handle_catalog(self):
        """Send the game catalog."""
        catalog = self.library.get_catalog()
        count = len(catalog)

        # Build response: RSP_CATALOG + count(2) + entries
        resp = bytearray([RSP_CATALOG])
        resp += struct.pack('>H', count)

        for game_id, title, size in catalog:
            title_bytes = title.encode('ascii', errors='replace')[:255]
            resp += struct.pack('>H', game_id)
            resp += struct.pack('B', len(title_bytes))
            resp += title_bytes
            resp += struct.pack('>I', size)

        self.conn.sendall(resp)
        print(f"[CMD]  CATALOG → {count} games to {self.addr}")

    def _handle_fetch(self):
        """Fetch and stream a game ROM."""
        id_bytes = self._recv_exact(2)
        if not id_bytes:
            return

        game_id = struct.unpack('>H', id_bytes)[0]
        rom_data = self.library.get_rom_data(game_id)

        if rom_data is None:
            self._send_error(f"Game ID {game_id} not found")
            return

        # Send: RSP_ROMDATA + size(4) + data
        header = struct.pack('>BI', RSP_ROMDATA, len(rom_data))
        self.conn.sendall(header)

        # Stream ROM data in chunks
        chunk_size = 16384
        offset = 0
        while offset < len(rom_data):
            end = min(offset + chunk_size, len(rom_data))
            self.conn.sendall(rom_data[offset:end])
            offset = end

        game_info = self.library.games.get(game_id, {})
        print(f"[CMD]  FETCH game {game_id} ({game_info.get('title', '?')}) "
              f"→ {len(rom_data)} bytes to {self.addr}")

    def _handle_menudata(self):
        """Send SCMENU.BIN data."""
        data = self.library.get_menudata()
        if data is None:
            self._send_error("No menu data available")
            return

        header = struct.pack('>BI', RSP_MENUDATA, len(data))
        self.conn.sendall(header)
        self.conn.sendall(data)
        print(f"[CMD]  MENUDATA → {len(data)} bytes to {self.addr}")

    def _handle_queue(self):
        """Return the queued game ID."""
        global queued_game_id
        resp = struct.pack('>BH', RSP_QUEUE, queued_game_id)
        self.conn.sendall(resp)
        if queued_game_id > 0:
            print(f"[CMD]  QUEUE -> game {queued_game_id} to {self.addr}")

    def _send_error(self, msg):
        """Send an error response."""
        msg_bytes = msg.encode('ascii', errors='replace')[:255]
        resp = struct.pack('>BB', RSP_ERROR, len(msg_bytes)) + msg_bytes
        self.conn.sendall(resp)
        print(f"[ERR]  {msg} (to {self.addr})")

    def _recv_exact(self, n):
        """Receive exactly n bytes, or return None on disconnect."""
        data = b''
        while len(data) < n:
            chunk = self.conn.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data


class SegaChannelServer:
    """Main server — listens for emulator connections."""

    def __init__(self, port, library):
        self.port = port
        self.library = library
        self.server_socket = None
        self.running = False

    def start(self):
        """Start the server."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', self.port))
        self.server_socket.listen(5)
        self.running = True

        print(f"[INFO] Sega Channel server listening on port {self.port}")
        print(f"[INFO] {len(self.library.games)} games available")
        print()

        try:
            while self.running:
                conn, addr = self.server_socket.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                handler = ClientHandler(conn, addr, self.library)
                thread = threading.Thread(target=handler.handle, daemon=True)
                thread.start()
        except KeyboardInterrupt:
            print("\n[INFO] Server shutting down")
        finally:
            self.server_socket.close()


def main():
    parser = argparse.ArgumentParser(description='Sega Channel Backend Server')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'TCP port to listen on (default: {DEFAULT_PORT})')
    parser.add_argument('--roms', type=str, default='./roms',
                        help='Directory containing Genesis ROM files (default: ./roms)')
    parser.add_argument('--menudata', type=str, default=None,
                        help='Path to SCMENU.BIN file (optional)')
    args = parser.parse_args()

    library = GameLibrary(args.roms, args.menudata)
    server = SegaChannelServer(args.port, library)
    server.start()


if __name__ == '__main__':
    main()
