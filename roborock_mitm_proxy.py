#!/usr/bin/env python3
"""
Roborock MitM Transparent Proxy (TCP 58867)
Intercepts local traffic transparently to enable offline camera functionality.
Uses python-roborock library to handle ALL protocols (1.0, A01, B01, L01).
Uses SO_ORIGINAL_DST for dynamic routing (no hardcoded robot IP).

=============================================================================
INSTALLATION GUIDE (OpenWRT / GL.iNet)
=============================================================================

1. INSTALL DEPENDENCIES
   SSH into your router and run:
   $ opkg update
   $ opkg install python3 python3-pip
   $ pip3 install python-roborock

2. SETUP THE SCRIPT
   Copy this file to /root/roborock_mitm_proxy.py
   Make it executable:
   $ chmod +x /root/roborock_mitm_proxy.py

3. CONFIGURE FIREWALL (IPTABLES)
   Redirect traffic destined to the robot's port 58867 to this script.
   Add this to "Custom Rules" in LuCI (Network -> Firewall -> Custom Rules),
   or run manually:

   # Redirect all TCP 58867 traffic to local port 58867 (except traffic from the router itself)
   iptables -t nat -A PREROUTING -p tcp --dport 58867 -j REDIRECT --to-ports 58867

   (No IP address is needed thanks to REDIRECT + SO_ORIGINAL_DST magic)

4. RUN THE PROXY
   $ export ROBOROCK_LOCAL_KEY="your_device_token_here"
   $ export LOG_FILE="/tmp/mitm_proxy.log"  # Log to RAM (Safe)
   $ python3 /root/roborock_mitm_proxy.py

=============================================================================
"""

import asyncio
import socket
import logging
from logging.handlers import RotatingFileHandler
import json
import struct
import os
import time
import sys

# Import official library to handle L01 and other protocols automatically
from roborock.protocol import create_local_decoder, create_local_encoder, RoborockMessage

# --- CONFIGURATION ---
LISTEN_PORT = 58867         
LOCAL_KEY = os.environ.get("ROBOROCK_LOCAL_KEY", "YOUR_LOCAL_KEY_HERE")
FAKE_TURN_URL = f"turn:{os.environ.get('PROXY_IP', '192.168.8.1')}:3478"
FAKE_TURN_USER = "mitm_user"
FAKE_TURN_PWD = "mitm_password"
LOG_FILE = os.environ.get("LOG_FILE") # Example: /tmp/roborock_proxy.log

# Linux constant to retrieve original destination
SO_ORIGINAL_DST = 80

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


def get_original_dest(client_socket):
    """Asks the Linux Kernel for the original destination before IPTables redirection."""
    try:
        opt = client_socket.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
        port, ip_bytes = struct.unpack("!2xH4s8x", opt)
        return socket.inet_ntoa(ip_bytes), port
    except Exception as e:
        logger.warning(f"Unable to get ORIGINAL_DST: {e}")
        return None, None

class RoborockProxy:
    def __init__(self, local_key):
        self.local_key = local_key
        # Use library factories which handle internal buffering
        self.decoder = create_local_decoder(local_key)
        self.encoder = create_local_encoder(local_key)

    async def handle_client(self, client_reader, client_writer):
        """Handle incoming connection from the App (Phone)"""
        addr = client_writer.get_extra_info('peername')
        sock = client_writer.get_extra_info('socket')
        
        target_ip, target_port = get_original_dest(sock)
        
        if not target_ip:
            logger.error(f"❌ No target found for {addr}. Are you running with the correct iptables REDIRECT rule?")
            client_writer.close()
            return

        logger.info(f"⚡ Interception: {addr} -> {target_ip}:{target_port}")

        try:
            robot_reader, robot_writer = await asyncio.open_connection(target_ip, target_port)
        except Exception as e:
            logger.error(f"Failed to connect to robot {target_ip}: {e}")
            client_writer.close()
            return

        await asyncio.wait(
            [
                asyncio.create_task(self.forward_client_to_robot(client_reader, robot_writer, client_writer)),
                asyncio.create_task(self.pipe_stream(robot_reader, client_writer))
            ],
            return_when=asyncio.FIRST_COMPLETED
        )

        client_writer.close()
        robot_writer.close()

    async def forward_client_to_robot(self, reader, robot_writer, client_writer):
        """Read, decrypt (L01/1.0/...), intercept, re-encrypt."""
        while True:
            try:
                # Read chunks
                data = await reader.read(4096)
                if not data:
                    break
                
                # The library decoder accumulates data and returns a list of complete messages
                # It automatically handles packet boundaries and L01/1.0 protocols
                try:
                    messages = self.decoder(data)
                except Exception as e:
                    logger.warning(f"Decoding error (unknown protocol or invalid key?): {e}")
                    # In case of error, forward raw data to avoid breaking connection
                    robot_writer.write(data)
                    await robot_writer.drain()
                    continue

                if not messages:
                    # Not enough data for a complete message, continue reading
                    continue

                for msg in messages:
                    # msg is a decrypted RoborockMessage object
                    if not msg.payload:
                        self.send_msg(robot_writer, msg)
                        continue

                    try:
                        # Payload is bytes, decode to JSON
                        json_str = msg.payload.decode('utf-8')
                        payload = json.loads(json_str)
                        
                        # --- INTERCEPTION LOGIC ---
                        if await self.intercept_logic(payload, msg, client_writer):
                            continue # Message processed and answered, do not send to robot
                        
                        # If not intercepted, forward to robot
                        # Note: We re-encode the original (or modified) message
                        # The encoder automatically handles the correct protocol (based on msg.protocol/version)
                        self.send_msg(robot_writer, msg)

                    except Exception as e:
                        logger.debug(f"Non-JSON payload or error: {e}")
                        self.send_msg(robot_writer, msg)

            except Exception as e:
                logger.error(f"Client stream error: {e}")
                break

    async def intercept_logic(self, payload, original_msg, client_writer):
        """Detects and blocks get_turn_server"""
        inner = payload
        is_wrapped = False
        
        # Handle "dps" encapsulation (Tuya style)
        if "dps" in payload:
            for k, v in payload["dps"].items():
                if isinstance(v, str) and "method" in v:
                    try:
                        inner = json.loads(v)
                        is_wrapped = True
                    except: pass
        
        method = inner.get("method")
        msg_id = inner.get("id")

        if method == "get_turn_server":
            logger.warning(f"🛑 BLOCKED: get_turn_server (ID {msg_id})")
            
            fake_resp = {
                "id": msg_id,
                "result": {
                    "url": FAKE_TURN_URL,
                    "user": FAKE_TURN_USER,
                    "pwd": FAKE_TURN_PWD
                }
            }
            
            final_payload = fake_resp
            if is_wrapped:
                # Try to respect wrapped format if present
                final_payload = {"dps": {"102": json.dumps(fake_resp)}, "t": int(time.time())}
            
            # Create response
            # Use same version/protocol as original message to stay consistent (L01 or 1.0)
            resp_msg = RoborockMessage(
                version=original_msg.version,
                seq=original_msg.seq + 1, # Incrementing seq is good practice
                random=original_msg.random,
                timestamp=int(time.time()),
                protocol=original_msg.protocol,
                payload=json.dumps(final_payload).encode('utf-8')
            )
            
            self.send_msg(client_writer, resp_msg)
            return True

        return False

    def send_msg(self, writer, msg):
        """Encode (encrypt) and write"""
        data = self.encoder(msg)
        writer.write(data)

    async def pipe_stream(self, reader, writer):
        """Simple return relay (Robot -> App)"""
        try:
            while True:
                data = await reader.read(4096)
                if not data: break
                writer.write(data)
                await writer.drain()
        except: pass

async def main():
    logger.info(f"Starting MitM Proxy (L01/1.0 compatible)...")
    if LOG_FILE:
        logger.info(f"Logging to {LOG_FILE} (Max 1MB)")
        
    proxy = RoborockProxy(LOCAL_KEY)
    
    server = await asyncio.start_server(
        proxy.handle_client, '0.0.0.0', LISTEN_PORT, family=socket.AF_INET
    )
    
    logger.info(f"🚀 Transparent Proxy listening on {LISTEN_PORT}")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
