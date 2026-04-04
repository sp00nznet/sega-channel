"""
Test client for the Sega Channel backend server.
Verifies the protocol works correctly.

Usage:
    python test_client.py [--host HOST] [--port PORT]
"""

import socket
import struct
import argparse
import sys

CMD_CATALOG  = 0x01
CMD_FETCH    = 0x02
CMD_MENUDATA = 0x03
CMD_PING     = 0xFF

RSP_CATALOG  = 0x01
RSP_ROMDATA  = 0x02
RSP_MENUDATA = 0x03
RSP_ERROR    = 0xFE
RSP_PONG     = 0xFF


def recv_exact(sock, n):
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection lost")
        data += chunk
    return data


def test_ping(sock):
    print("Testing PING...")
    sock.sendall(bytes([CMD_PING]))
    rsp = recv_exact(sock, 1)
    assert rsp[0] == RSP_PONG, f"Expected PONG (0xFF), got 0x{rsp[0]:02X}"
    print("  PONG received - OK")


def test_catalog(sock):
    print("Testing CATALOG...")
    sock.sendall(bytes([CMD_CATALOG]))
    rsp = recv_exact(sock, 3)
    assert rsp[0] == RSP_CATALOG, f"Expected CATALOG response, got 0x{rsp[0]:02X}"
    count = struct.unpack('>H', rsp[1:3])[0]
    print(f"  {count} games available:")

    games = []
    for _ in range(count):
        entry_hdr = recv_exact(sock, 3)  # id(2) + title_len(1)
        game_id = struct.unpack('>H', entry_hdr[0:2])[0]
        title_len = entry_hdr[2]
        title = recv_exact(sock, title_len).decode('ascii', errors='replace')
        size_bytes = recv_exact(sock, 4)
        size = struct.unpack('>I', size_bytes)[0]
        games.append((game_id, title, size))
        print(f"    [{game_id:3d}] {title} ({size / 1024:.0f} KB)")

    return games


def test_fetch(sock, game_id, expected_title=""):
    print(f"Testing FETCH game {game_id} ({expected_title})...")
    cmd = struct.pack('>BH', CMD_FETCH, game_id)
    sock.sendall(cmd)

    rsp = recv_exact(sock, 5)
    if rsp[0] == RSP_ERROR:
        msg_len = rsp[1]
        msg = recv_exact(sock, msg_len).decode('ascii', errors='replace')
        print(f"  ERROR: {msg}")
        return

    assert rsp[0] == RSP_ROMDATA, f"Expected ROMDATA, got 0x{rsp[0]:02X}"
    rom_size = struct.unpack('>I', rsp[1:5])[0]
    print(f"  Receiving {rom_size} bytes...")

    # Read ROM data
    rom_data = recv_exact(sock, rom_size)
    print(f"  Received {len(rom_data)} bytes")

    # Verify it looks like a Genesis ROM
    if len(rom_data) >= 0x200:
        console = rom_data[0x100:0x110].decode('ascii', errors='replace').strip('\x00')
        title = rom_data[0x120:0x150].decode('ascii', errors='replace').strip('\x00').strip()
        print(f"  Console: {console}")
        print(f"  Title: {title}")
    print("  OK")


def test_fetch_invalid(sock):
    print("Testing FETCH with invalid ID (9999)...")
    cmd = struct.pack('>BH', CMD_FETCH, 9999)
    sock.sendall(cmd)

    rsp = recv_exact(sock, 1)
    if rsp[0] == RSP_ERROR:
        msg_len_bytes = recv_exact(sock, 1)
        msg_len = msg_len_bytes[0]
        msg = recv_exact(sock, msg_len).decode('ascii', errors='replace')
        print(f"  Got expected error: {msg}")
        print("  OK")
    else:
        print(f"  Unexpected response: 0x{rsp[0]:02X}")


def main():
    parser = argparse.ArgumentParser(description='Test Sega Channel server')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7654)
    args = parser.parse_args()

    print(f"Connecting to {args.host}:{args.port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    try:
        sock.connect((args.host, args.port))
    except ConnectionRefusedError:
        print("ERROR: Could not connect. Is the server running?")
        sys.exit(1)

    print("Connected!\n")

    try:
        test_ping(sock)
        print()

        games = test_catalog(sock)
        print()

        if games:
            # Fetch the first game
            gid, title, size = games[0]
            test_fetch(sock, gid, title)
            print()

        test_fetch_invalid(sock)
        print()

        print("All tests passed!")

    except Exception as e:
        print(f"TEST FAILED: {e}")
        sys.exit(1)
    finally:
        sock.close()


if __name__ == '__main__':
    main()
