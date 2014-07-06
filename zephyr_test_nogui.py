from guidata import qapplication
from common.device_zephyr import ZephyrConnect
from guidata.qt.QtGui import (QWidget, QMainWindow, QPushButton, QHBoxLayout)
from guidata.qt.QtCore import QThread, SIGNAL
import time
from common.hrv import TimeSeriesContainer
from common.data_storage import DataStorage
import zephyr
import numpy as np

class MainWindow(QWidget):
    def __init__(self):
        QWidget.__init__(self)

        self.setWindowTitle( 'Biofeedback' )

        self.button_start = QPushButton()
        self.button_start.setText("START")
        self.button_stop = QPushButton()
        self.button_stop.setText("STOP")

        layout = QHBoxLayout(self)
        layout.addWidget(self.button_start)
        layout.addWidget(self.button_stop)

        self.connect(self.button_start, SIGNAL("clicked(bool)"), self.start_session)
        self.connect(self.button_stop, SIGNAL("clicked(bool)"), self.stop_session)

        self.setLayout(layout)
        self.setGeometry(300,100,250,100)
        self.show()

        self.datastorage = DataStorage()
        settings = {'db_host':'amber','db_user':'root','db_pwd':'dbrootpass','db_dbname':'biodb'}
        self.datastorage.enableDbStorage(settings)

        self.thread = ConnectionThread()


    def start_session(self):
        self.datastorage.timeseries = self.thread.tsc
        self.thread.start()

    def stop_session(self):
        self.thread.stop()
        self.store_session()

    def store_session(self):
        sessiondict = { 'duration':3,
                        'sessiontype':0,
                        'breathing_zone': 1,
                        'note': "",
                        'alerts': []
        }

        self.datastorage.store_session( sessiondict )




class ConnectionThread(QThread):
    def __init__(self):
        QThread.__init__(self)
        self.running = False
        self.tsc = TimeSeriesContainer()

        self.zephyr_connect = ZephyrConnect()
        self.zephyr_connect.connectTo(4)
        
        self.connect( self.zephyr_connect, SIGNAL( 'Message' ), self.printmessage )
        self.connect( self.zephyr_connect, SIGNAL( 'newRRI' ), self.addRR )
        self.connect( self.zephyr_connect, SIGNAL( 'newBW' ), self.addBW )
        self.connect( self.zephyr_connect, SIGNAL( 'heart_rate' ), self.add_heart_rate )
        self.connect( self.zephyr_connect, SIGNAL( 'respiration_rate' ), self.add_respiration_rate )
        self.connect( self.zephyr_connect, SIGNAL( 'breathing_wave_amplitude' ), self.add_breathing_wave_amplitude )
        self.connect( self.zephyr_connect, SIGNAL( 'activity' ), self.add_activity )
        self.connect( self.zephyr_connect, SIGNAL( 'posture' ), self.add_posture )


    def addRR(self, value):
        self.tsc.ts_rri.add_rrinterval( value )

    def addBW(self, value):
        self.tsc.ts_bw.add_breath( value )

    def add_heart_rate(self, value):
        self.tsc.heart_rate = np.append(self.tsc.heart_rate, value)

    def add_respiration_rate(self, value):
        self.tsc.respiration_rate = np.append(self.tsc.respiration_rate, value)

    def add_breathing_wave_amplitude(self, value):
        self.tsc.breathwave_ampltitude = np.append(self.tsc.breathwave_ampltitude,value)

    def add_activity(self, value):
        self.tsc.activity = np.append(self.tsc.activity, value)

    def add_posture(self, value):
        self.tsc.posture = np.append(self.tsc.posture, value)

    @staticmethod
    def printmessage( message ):

        # if isinstance(message, zephyr.message.SummaryMessage):
        #     self.tsc.heart_rate = np.append(self.tsc.heart_rate, message.heart_rate)
        #     self.tsc.respiration_rate = np.append(self.tsc.respiration_rate, message.respiration_rate)
        #     self.tsc.posture = np.append(self.tsc.posture, message.posture)
        #     self.tsc.activity = np.append(self.tsc.activity, message.activity)
        #     self.tsc.breathwave_ampltitude = np.append(self.tsc.breathwave_ampltitude,
        #                                                    message.breathing_wave_amplitude)

        print message

    def run(self):
        self.running = True
        self.zephyr_connect.enablePacket('SUMMARY')
        self.zephyr_connect.enablePacket('RRDATA')
        self.zephyr_connect.enablePacket('BREATHING')
        self.zephyr_connect.start()
        while self.running is True:
            time.sleep(2)

    def stop(self):
        self.zephyr_connect.disablePacket('SUMMARY')
        self.zephyr_connect.disablePacket('RRDATA')
        self.zephyr_connect.disablePacket('BREATHING')
        self.zephyr_connect.terminate()
        self.running = False

    def closeEvent(self, event):
        QMainWindow.closeEvent(self, event)

def main():
    app = qapplication()
    window = MainWindow()
    window.show()
    app.exec_()

if __name__ == "__main__":
    main()