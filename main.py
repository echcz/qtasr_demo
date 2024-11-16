import sys
import numpy as np
import pyqtgraph as pg
import sounddevice as sd
from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QTextEdit
from funasr_client import FunasrClient
import asyncio
import json
import util

class AsrWorker(QThread):
    connect_sig = Signal(FunasrClient)
    message_sig = Signal(dict)
    def __init__(self, uri, chunk_size=[5, 10, 5], sample_rate=16000,):
        super().__init__()
        self.uri = uri
        self.chunk_size = chunk_size
        self.sample_rate = sample_rate
        self.running_flag = asyncio.Queue(1)
        self.event_loop = None

    async def start_asr(self):
        self.event_loop = asyncio.get_event_loop()
        async with FunasrClient(self.uri, chunk_size=self.chunk_size, audio_fs=self.sample_rate, handler=self.handle_message) as asr_client:
            self.connect_sig.emit(asr_client)
            await self.running_flag.get()

    def handle_message(self, msg):
        self.message_sig.emit(msg)

    def run(self):
        asyncio.run(self.start_asr())

    def stop(self):
        if self.event_loop:
            self.event_loop.call_soon_threadsafe(self.running_flag.put_nowait, None)
        self.quit()
        self.wait()

class MicrophoneReader(QMainWindow):
    def __init__(self, asr_uri, chunk_size=[5, 10, 5], sample_rate=16000):
        super().__init__()
        self.asr_client = None
        self.chunk_size = chunk_size
        self.sample_rate = sample_rate
        self.asr_worker = AsrWorker(asr_uri, chunk_size=self.chunk_size, sample_rate=self.sample_rate)
        self.asr_worker.connect_sig.connect(self.handle_asr_connect)
        self.asr_worker.message_sig.connect(self.handle_asr_message)
        self.initUI()
        self.initAudio()
        self.initPlot()
        self.show_waveform()
        self.asr_worker.start()

    def initUI(self):
        self.setWindowTitle('qtasr')
        # 创建一个按钮用于开始/停止录音
        self.button = QPushButton('开始录音', self)
        self.button.clicked.connect(self.toggle_recording)
        # 创建一个标签显示波形图
        self.wave_widget = pg.PlotWidget()
        self.wave_widget.setYRange(np.iinfo(np.int16).min, np.iinfo(np.int16).max)
        self.wave_widget.setBackground('w')
        self.wave_widget.setAlignment(Qt.AlignCenter)
        self.wave_widget.setMinimumHeight(100)
        self.wave_widget.setMaximumHeight(200)
        # 创建一个文本域，显示识别结果
        self.asr_text_box = QTextEdit()
        self.asr_text_box.setReadOnly(True)
        self.asr_text_box.setAlignment(Qt.AlignLeft)
        self.asr_text_box.setStyleSheet("padding: 10px;")
        # 设置布局
        layout = QVBoxLayout()
        layout.addWidget(self.button)
        layout.addWidget(self.wave_widget)
        layout.addWidget(self.asr_text_box)
        # 将布局设置为主窗口的布局
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def initAudio(self):
        self.recording = False
        self.stream = None
        # 音频流参数
        self.channels = 1
        self.blocksize = 60 * self.chunk_size[1] * self.sample_rate // 1000
        # 缓存的音频数据，用于绘制波形图
        self.audio_seg_len = self.sample_rate // 100
        self.audio_segments = 500  # 最大显示的样本数
        self.audio_data = np.zeros(self.audio_segments, dtype=np.int16)
        self.audio_secs = np.arange(self.audio_segments, dtype=np.float32) / 100

    def initPlot(self):
        self.wave_line = self.wave_widget.plot(self.audio_secs, self.audio_data, pen=pg.mkPen('b', width=2))

    @Slot(FunasrClient)
    def handle_asr_connect(self, asr_client):
        self.asr_client = asr_client

    @Slot(dict)
    def handle_asr_message(self, message):
        if message.get("mode") == "2pass-offline":
            text = message.get("text", "")
            timestamps = message.get("timestamp")
            if timestamps:
                timestamps = json.loads(timestamps)
                start_time = timestamps[0][0]
                end_time = timestamps[-1][-1]
            else:
                start_time = 0
                end_time = 0
            start_time = util.milliseconds_to_hmsms(start_time)
            end_time = util.milliseconds_to_hmsms(end_time)
            self.asr_text_box.append(f"[{start_time} - {end_time}]: {text}")
            self.asr_text_box.ensureCursorVisible()

    def handle_audio_data(self, data):
        if self.asr_client:
            audio_chunk = data.tobytes(order='C')
            self.asr_client.send_audio_chunk(audio_chunk)

    def update_audio_data(self, indata, frames):
        data = indata.reshape(-1)[::self.audio_seg_len]
        data_len = len(data)
        self.audio_data[:-data_len] = self.audio_data[data_len:]
        self.audio_data[-data_len:] = data

    def show_waveform(self):
        self.wave_line.setData(self.audio_secs, self.audio_data)

    def recording_callback(self, indata, frames, time, status):
        self.handle_audio_data(indata)
        self.update_audio_data(indata, frames)
        self.show_waveform()

    def start_audio_stream(self):
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            channels=self.channels,
            dtype=np.int16,
            callback=self.recording_callback)
        self.stream.start()

    def stop_audio_stream(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
    
    def toggle_recording(self):
        if not self.recording:
            self.start_audio_stream()
            self.button.setText('停止录音')
            self.recording = True
            if self.asr_client:
                self.asr_client.start_task()
        else:
            self.stop_audio_stream()
            self.button.setText('开始录音')
            self.recording = False
            if self.asr_client:
                self.asr_client.final_task()
    
    def closeEvent(self, event):
        self.stop_audio_stream()
        self.asr_worker.stop()
        event.accept()

if __name__ == '__main__':
    asr_uri = 'wss://localhost:10095'
    chunk_size = [5, 10, 5]
    sample_rate = 16000
    app = QApplication(sys.argv)
    window = MicrophoneReader(asr_uri, chunk_size=chunk_size, sample_rate=sample_rate)
    window.show()
    sys.exit(app.exec())