#!/usr/bin/env python3
"""
Roborock Cloud Keep-Alive Emulator (UDP/TCP 8053)
Based on Rust implementation.
Simulates the Cloud Heartbeat server to prevent the robot from disconnecting Wi-Fi when offline.

PROTOCOL:
  Header: 0x21 0x31 (2 bytes)
  Length: 2 bytes (Big Endian)
  ... Payload ...

BEHAVIOR:
  - Responds to "Client Hello" (full 0xFF payload) with timestamp.
  - Responds to "Ping" (32 bytes) by echoing the message.
  - Ignores other messages.

INSTALLATION (OpenWRT):
  1. Copy to router.
  2. Run: export LOG_FILE="/tmp/keepalive.log" && python3 roborock_keepalive_server.py
  3. Redirect traffic:
     iptables -t nat -A PREROUTING -p udp --dport 8053 -j REDIRECT --to-ports 8053
     iptables -t nat -A PREROUTING -p tcp --dport 8053 -j REDIRECT --to-ports 8053
"""

import socket
import struct
import time
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import os
import sys

LISTEN_PORT = 8053
MAGIC = b'\x21\x31'
LOG_FILE = os.environ.get("LOG_FILE")

# --- LOGGING SETUP ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 1. Console Handler (Stdout)
c_handler = logging.StreamHandler(sys.stdout)
c_handler.setFormatter(formatter)
logger.addHandler(c_handler)

# 2. File Handler (Optional with Rotation)
if LOG_FILE:
    # Max 1MB, 1 Backup file.
    f_handler = RotatingFileHandler(LOG_FILE, maxBytes=1024*1024, backupCount=1)
    f_handler.setFormatter(formatter)
    logger.addHandler(f_handler)

def get_timestamp_bytes():
    # 4 bytes Big Endian timestamp
    return struct.pack(">I", int(time.time()))

def process_message(data):
    if len(data) < 32:
        return None

    # Validate Magic
    if data[0:2] != MAGIC:
        logger.debug(f"Bad Magic: {data[0:2].hex()}")
        return None

    # Validate Length
    length = struct.unpack(">H", data[2:4])[0]
    if length != len(data):
        logger.debug(f"Bad Length: header={length}, actual={len(data)}")
        return None

    # Extract Device ID (bytes 8-12)
    did = struct.unpack(">I", data[8:12])[0]

    # Check for Client Hello (0xFF...)
    # Bytes 4-12 (8 bytes) should be FF? Rust code says: &msg[4..12]
    if data[4:12] == b'\xff' * 8:
        logger.info(f"Client Hello received from DID {did}")
        # Response: Copy input, replace bytes 12-16 with timestamp
        resp = bytearray(data[:32])
        ts = get_timestamp_bytes()
        resp[12:16] = ts
        return bytes(resp)

    # Check for Ping (Length 32)
    if length == 32:
        logger.info(f"Ping received from DID {did}")
        # Response: Echo back
        return data[:32]

    logger.info(f"Real message from DID {did}, ignoring")
    return None

class KeepAliveServer:
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        resp = process_message(data)
        if resp:
            self.transport.sendto(resp, addr)
            # logger.debug(f"UDP Sent to {addr}")

    def data_received(self, data):
        # TCP handling (simplified, assumes 1 packet = 1 message for now)
        resp = process_message(data)
        if resp:
            self.transport.write(resp)

async def run_udp_server():
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: KeepAliveServer(),
        local_addr=('0.0.0.0', LISTEN_PORT)
    )
    logger.info(f"UDP Server listening on {LISTEN_PORT}")
    return transport

async def handle_tcp_client(reader, writer):
    addr = writer.get_extra_info('peername')
    # logger.info(f"TCP Connection from {addr}")
    try:
        while True:
            # Read header (4 bytes)
            header = await reader.read(4)
            if not header: break
            
            if header[0:2] != MAGIC:
                break
            
            length = struct.unpack(">H", header[2:4])[0]
            if length < 4: break

            # Read rest of message
            body = await reader.read(length - 4)
            if len(body) != length - 4: break
            
            full_msg = header + body
            resp = process_message(full_msg)
            
            if resp:
                writer.write(resp)
                await writer.drain()
            else:
                # If we ignore it, maybe we should close?
                # Rust code ignores real messages but keeps connection open
                pass
    except Exception as e:
        logger.error(f"TCP Error: {e}")
    finally:
        writer.close()

async def main():
    logger.info(f"Starting KeepAlive Server...")
    if LOG_FILE:
        logger.info(f"Logging to {LOG_FILE}")
        
    # Start UDP
    await run_udp_server()
    
    # Start TCP
    server = await asyncio.start_server(handle_tcp_client, '0.0.0.0', LISTEN_PORT)
    logger.info(f"TCP Server listening on {LISTEN_PORT}")
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())