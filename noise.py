import pyaudio
import random
from PyQt4.QtCore import QThread

class MakeNoise( QThread ):
    """docstring for MakeNoise"""
    def __init__(self):
        QThread.__init__(self)
        p = pyaudio.PyAudio()
        self.value = 0.01
        self.stream = p.open(format=pyaudio.paInt8,
                        channels=1,
                        rate=22050,
                        output=True)
    def run(self):
        while 1:
            self.stream.write(chr(int(random.random()*256*self.value)))

    def setValue(self, value):
        if value > 0.3:
            value = 0.3
        self.value = value
