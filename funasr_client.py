import asyncio
import websockets
import ssl
import json
import uuid

class FunasrClient:
    def __init__(self, uri, chunk_size=[5, 10, 5], mode = '2pass', audio_fs=16000, hotwords = None, itn = True, handler = None):
        if uri.startswith("wss://"):
            ssl_context = ssl.SSLContext()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        elif uri.startswith("ws://"):
            ssl_context = None
        else:
            raise ValueError("Invalid URI")
        self.uri = uri
        self.ssl_context = ssl_context
        self.ws_connection = None
        self.send_queue = asyncio.Queue()
        self.handler = handler
        self.event_loop = None
        self.base_msg = {
            "mode": mode,
            "is_speaking": True,
            "wav_format": "pcm",
            "chunk_size": chunk_size,
            "audio_fs": audio_fs,
            "hotwords": hotwords,
            "itn": itn,
        }

    async def _recv_task(self):
        print("start recv task")
        while True:
            try:
                msg = await self.ws_connection.recv()
            except websockets.ConnectionClosed:
                print("Connection closed, stop recv message.")
                break
            if not msg:
                continue
            if not self.handler:
                continue
            msg = json.loads(msg)
            self.handler(msg)

    async def _send_task(self):
        print("start send task")
        while True:
            msg = await self.send_queue.get()
            if msg is None:
                break
            if not msg:
                continue
            try:
                await self.ws_connection.send(msg)
            except websockets.ConnectionClosed:
                print("Connection closed, stop send message.")
                break

    async def connect(self):
        self.event_loop = asyncio.get_event_loop()
        self.ws_connection = await websockets.connect(self.uri, ssl=self.ssl_context, subprotocols=["binary"], ping_interval=10,)
        asyncio.create_task(self._recv_task())
        asyncio.create_task(self._send_task())

    async def close(self):
        await self.send_queue.put(None)
        if self.ws_connection:
            await self.ws_connection.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _send_message(self, msg):
        self.event_loop.call_soon_threadsafe(self.send_queue.put_nowait, msg)

    def start_task(self, wav_name = None, handler = None):
        if handler:
            self.handler = handler
        if not wav_name:
            wav_name = uuid.uuid4().hex
        msg = dict(self.base_msg, wav_name=wav_name)
        msg = json.dumps(msg)
        self._send_message(msg)

    def send_audio_chunk(self, audio_chunk):
        self._send_message(audio_chunk)

    def final_task(self):
        self._send_message('{"is_speaking": false}')
