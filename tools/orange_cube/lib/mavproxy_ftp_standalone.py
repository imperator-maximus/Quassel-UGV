#!/usr/bin/env python3
"""
MAVProxy FTP Standalone Implementation
Extrahierte und angepasste Version der MAVProxy FTP-Funktionalität
ohne MAVProxy-Dependencies für direkten pymavlink-Einsatz

Basiert auf: MAVProxy.modules.mavproxy_ftp
Angepasst für: Orange Cube Lua Script Upload via WiFi Bridge

Usage:
    from mavproxy_ftp_standalone import MAVProxyFTP
    
    connection = mavutil.mavlink_connection('udpout:192.168.178.134:14550')
    ftp = MAVProxyFTP(connection)
    ftp.put("hello.lua", "/APM/scripts/hello.lua")
"""

import io
import time
import os
import sys
import struct
import random
from pymavlink import mavutil

try:
    # py2
    from StringIO import StringIO as SIO
except ImportError:
    # py3
    from io import BytesIO as SIO

# ============================================================================
# FTP PROTOCOL CONSTANTS (from MAVProxy)
# ============================================================================

# opcodes
OP_None = 0
OP_TerminateSession = 1
OP_ResetSessions = 2
OP_ListDirectory = 3
OP_OpenFileRO = 4
OP_ReadFile = 5
OP_CreateFile = 6
OP_WriteFile = 7
OP_RemoveFile = 8
OP_CreateDirectory = 9
OP_RemoveDirectory = 10
OP_OpenFileWO = 11
OP_TruncateFile = 12
OP_Rename = 13
OP_CalcFileCRC32 = 14
OP_BurstReadFile = 15
OP_Ack = 128
OP_Nack = 129

# error codes
ERR_None = 0
ERR_Fail = 1
ERR_FailErrno = 2
ERR_InvalidDataSize = 3
ERR_InvalidSession = 4
ERR_NoSessionsAvailable = 5
ERR_EndOfFile = 6
ERR_UnknownCommand = 7
ERR_FileExists = 8
ERR_FileProtected = 9
ERR_FileNotFound = 10

HDR_Len = 12
MAX_Payload = 239

# ============================================================================
# FTP OPERATION CLASS (from MAVProxy)
# ============================================================================

class FTP_OP:
    def __init__(self, seq, session, opcode, size, req_opcode, burst_complete, offset, payload):
        self.seq = seq
        self.session = session
        self.opcode = opcode
        self.size = size
        self.req_opcode = req_opcode
        self.burst_complete = burst_complete
        self.offset = offset
        self.payload = payload

    def pack(self):
        '''pack message'''
        ret = struct.pack("<HBBBBBBI", self.seq, self.session, self.opcode, self.size, 
                         self.req_opcode, self.burst_complete, 0, self.offset)
        if self.payload is not None:
            ret += self.payload
        ret = bytearray(ret)
        return ret

    def __str__(self):
        plen = 0
        if self.payload is not None:
            plen = len(self.payload)
        ret = "OP seq:%u sess:%u opcode:%d req_opcode:%u size:%u bc:%u ofs:%u plen=%u" % (
            self.seq, self.session, self.opcode, self.req_opcode, self.size, 
            self.burst_complete, self.offset, plen)
        if plen > 0:
            ret += " [%u]" % self.payload[0]
        return ret

class WriteQueue:
    def __init__(self, ofs, size):
        self.ofs = ofs
        self.size = size
        self.last_send = 0

# ============================================================================
# FTP SETTINGS CLASS (simplified)
# ============================================================================

class FTPSettings:
    def __init__(self):
        self.debug = 0
        self.pkt_loss_tx = 0
        self.pkt_loss_rx = 0
        self.max_backlog = 5
        self.burst_read_size = 80
        self.write_size = 80
        self.write_qsize = 5
        self.retry_time = 0.5

# ============================================================================
# STANDALONE MAVPROXY FTP CLASS
# ============================================================================

class MAVProxyFTP:
    """
    Standalone MAVProxy FTP Implementation
    Extrahiert aus MAVProxy für direkten pymavlink-Einsatz
    """
    
    def __init__(self, connection, debug=False):
        """
        Initialize MAVProxy FTP
        
        Args:
            connection: pymavlink connection object
            debug (bool): Enable debug output
        """
        self.connection = connection
        self.target_system = connection.target_system or 1
        self.target_component = connection.target_component or 1
        
        # FTP Settings (ESP32-optimiert)
        self.ftp_settings = FTPSettings()
        self.ftp_settings.debug = 1 if debug else 0
        self.ftp_settings.write_size = 80  # MAVProxy Standard
        self.ftp_settings.write_qsize = 5  # MAVProxy Standard
        
        # FTP State
        self.seq = 0
        self.session = 0
        self.network = 0
        self.last_op = None
        self.fh = None
        self.filename = None
        
        # Write state
        self.write_list = None
        self.write_block_size = 0
        self.write_acks = 0
        self.write_total = 0
        self.write_file_size = 0
        self.write_idx = 0
        self.write_recv_idx = -1
        self.write_pending = 0
        self.write_last_send = None
        
        # Timing
        self.op_start = None
        self.last_op_time = time.time()
        self.rtt = 0.5
        
        print(f"✅ MAVProxy FTP initialisiert")
        print(f"   Target: System {self.target_system}, Component {self.target_component}")
        print(f"   Settings: write_size={self.ftp_settings.write_size}, write_qsize={self.ftp_settings.write_qsize}")

    def send(self, op):
        '''send a request'''
        op.seq = self.seq
        payload = op.pack()
        plen = len(payload)
        if plen < MAX_Payload + HDR_Len:
            payload.extend(bytearray([0]*((HDR_Len+MAX_Payload)-plen)))
        
        self.connection.mav.file_transfer_protocol_send(
            self.network, self.target_system, self.target_component, payload)
        self.seq = (self.seq + 1) % 256
        self.last_op = op
        now = time.time()
        if self.ftp_settings.debug > 1:
            print("> %s dt=%.2f" % (op, now - self.last_op_time))
        self.last_op_time = time.time()

    def terminate_session(self):
        '''terminate current session'''
        self.send(FTP_OP(self.seq, self.session, OP_TerminateSession, 0, 0, 0, 0, None))
        self.fh = None
        self.filename = None
        self.write_list = None
        self.session = (self.session + 1) % 256
        if self.ftp_settings.debug > 0:
            print("Terminated session")

    def list_directory(self, path="/APM/scripts"):
        """
        List directory contents

        Args:
            path (str): Directory path to list

        Returns:
            bool: Success status
        """
        print(f"📋 Listing {path}")
        enc_dname = bytearray(path, 'ascii')
        self.total_size = 0
        self.dir_offset = 0
        op = FTP_OP(self.seq, self.session, OP_ListDirectory, len(enc_dname), 0, 0, self.dir_offset, enc_dname)
        self.send(op)

        # Wait for response - schneller für lokale Operationen
        return self._wait_for_completion("list", timeout=3)

    def put(self, local_file, remote_file):
        """
        Upload file to remote system

        Args:
            local_file (str): Local file path
            remote_file (str): Remote file path

        Returns:
            bool: Success status
        """
        if self.write_list is not None:
            print("❌ Put already in progress")
            return False

        try:
            self.fh = open(local_file, 'rb')
        except Exception as ex:
            print(f"❌ Failed to open {local_file}: {ex}")
            return False

        self.filename = remote_file
        print(f"📤 Putting {local_file} as {remote_file}")

        # Get file size
        self.fh.seek(0, 2)
        file_size = self.fh.tell()
        self.fh.seek(0)

        # Setup write list
        self.write_block_size = self.ftp_settings.write_size
        self.write_file_size = file_size

        write_blockcount = file_size // self.write_block_size
        if file_size % self.write_block_size != 0:
            write_blockcount += 1

        self.write_list = set(range(write_blockcount))
        self.write_acks = 0
        self.write_total = write_blockcount
        self.write_idx = 0
        self.write_recv_idx = -1
        self.write_pending = 0
        self.write_last_send = None

        self.op_start = time.time()
        enc_fname = bytearray(self.filename, 'ascii')
        op = FTP_OP(self.seq, self.session, OP_CreateFile, len(enc_fname), 0, 0, 0, enc_fname)
        self.send(op)

        # Wait for completion - schneller für kleine Dateien
        return self._wait_for_completion("put", timeout=10)

    def _wait_for_completion(self, operation, timeout=10):
        """
        Wait for FTP operation to complete

        Args:
            operation (str): Operation name for logging
            timeout (int): Timeout in seconds

        Returns:
            bool: Success status
        """
        start_time = time.time()
        message_count = 0

        print(f"🔍 Warte auf {operation}...")

        while time.time() - start_time < timeout:
            # Schnellerer Message-Empfang für bessere Performance
            msg = self.connection.recv_match(timeout=0.05)
            if msg:
                message_count += 1
                msg_type = msg.get_type()

                # Nur FTP Messages zeigen für bessere Performance
                if msg_type == 'FILE_TRANSFER_PROTOCOL':
                    print(f"📤 FTP Message received!")
                    self._handle_ftp_message(msg)

            # Check if operation completed
            if operation == "list":
                # List completes when we get EndOfFile
                if hasattr(self, '_list_complete') and self._list_complete:
                    print(f"✅ List completed")
                    return True
            elif operation == "put":
                # Put completes when write_list is empty
                if self.write_list is not None and len(self.write_list) == 0:
                    print(f"✅ Upload completed: {self.write_file_size} bytes")
                    self.terminate_session()
                    return True

            # Send more writes if needed
            if operation == "put" and self.write_list is not None:
                self._send_more_writes()

            time.sleep(0.01)  # Kürzere Delays für bessere Performance

        print(f"⏰ {operation} timeout after {timeout}s")
        if message_count == 0:
            print("❌ Keine MAVLink Messages empfangen")
        self.terminate_session()
        return False

    def _handle_ftp_message(self, msg):
        """Handle FILE_TRANSFER_PROTOCOL message"""
        if (msg.target_system != self.connection.source_system or
            msg.target_component != self.connection.source_component):
            return

        op = self._parse_ftp_message(msg)
        now = time.time()
        dt = now - self.last_op_time
        if self.ftp_settings.debug > 1:
            print("< %s dt=%.2f" % (op, dt))
        self.last_op_time = now

        # Handle different operation types
        if op.req_opcode == OP_ListDirectory:
            self._handle_list_reply(op)
        elif op.req_opcode == OP_CreateFile:
            self._handle_create_file_reply(op)
        elif op.req_opcode == OP_WriteFile:
            self._handle_write_reply(op)
        else:
            if self.ftp_settings.debug > 0:
                print(f"FTP Unknown: {op}")

    def _parse_ftp_message(self, msg):
        """Parse FILE_TRANSFER_PROTOCOL message"""
        hdr = bytearray(msg.payload[0:12])
        (seq, session, opcode, size, req_opcode, burst_complete, pad, offset) = struct.unpack("<HBBBBBBI", hdr)
        payload = bytearray(msg.payload[12:])[:size]
        return FTP_OP(seq, session, opcode, size, req_opcode, burst_complete, offset, payload)

    def _handle_list_reply(self, op):
        """Handle OP_ListDirectory reply"""
        if op.opcode == OP_Ack:
            dentries = sorted(op.payload.split(b'\x00'))
            for d in dentries:
                if len(d) == 0:
                    continue
                try:
                    if sys.version_info.major >= 3:
                        d = str(d, 'ascii')
                    else:
                        d = str(d)
                except Exception:
                    continue
                if d[0] == 'D':
                    print(" D %s" % d[1:])
                elif d[0] == 'F':
                    (name, size) = d[1:].split('\t')
                    size = int(size)
                    print("   %s\t%u" % (name, size))
                else:
                    print(d)
        elif op.opcode == OP_Nack and len(op.payload) == 1 and op.payload[0] == ERR_EndOfFile:
            print("Directory listing complete")
            self._list_complete = True
        else:
            print('LIST: %s' % op)

    def _handle_create_file_reply(self, op):
        """Handle OP_CreateFile reply"""
        if self.fh is None:
            self.terminate_session()
            return
        if op.opcode == OP_Ack:
            if self.ftp_settings.debug > 0:
                print("✅ File created, starting write")
            self._send_more_writes()
        else:
            print("❌ Create failed")
            self.terminate_session()

    def _handle_write_reply(self, op):
        """Handle OP_WriteFile reply"""
        if self.fh is None:
            self.terminate_session()
            return
        if op.opcode != OP_Ack:
            print("❌ Write failed")
            self.terminate_session()
            return

        # Process write acknowledgment
        idx = op.offset // self.write_block_size
        count = (idx - self.write_recv_idx) % self.write_total

        self.write_pending = max(0, self.write_pending - count)
        self.write_recv_idx = idx
        self.write_list.discard(idx)
        self.write_acks += 1

        if self.ftp_settings.debug > 0:
            progress = self.write_acks / float(self.write_total) * 100
            print(f"📊 Write progress: {progress:.1f}% ({self.write_acks}/{self.write_total})")

        self._send_more_writes()

    def _send_more_writes(self):
        """Send more write operations"""
        if len(self.write_list) == 0:
            # All done
            print(f"✅ All writes completed: {self.write_file_size} bytes")
            return

        now = time.time()
        if self.write_last_send is not None:
            if now - self.write_last_send > max(min(10*self.rtt, 1), 0.2):
                # Lost replies, reduce pending count
                self.write_pending = max(0, self.write_pending-1)

        n = min(self.ftp_settings.write_qsize - self.write_pending, len(self.write_list))
        for i in range(n):
            # Send in round-robin
            idx = self.write_idx
            while idx not in self.write_list:
                idx = (idx + 1) % self.write_total
            ofs = idx * self.write_block_size
            self.fh.seek(ofs)
            data = self.fh.read(self.write_block_size)
            write = FTP_OP(self.seq, self.session, OP_WriteFile, len(data), 0, 0, ofs, bytearray(data))
            self.send(write)
            self.write_idx = (idx + 1) % self.write_total
            self.write_pending += 1
            self.write_last_send = now
