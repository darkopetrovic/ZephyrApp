#Zephyr Integration
import zephyr
from zephyr.testing import TimedVirtualSerial, simulation_workflow
from PyQt4.QtGui import QWidget
from PyQt4.QtCore import QThread, SIGNAL
import platform
import serial

# Set to FALSE to use the real data coming from the device
USE_TEST_DATA = True

zephyr.configure_root_logger()

if USE_TEST_DATA is True:
    test_data_dir = "A:\\Projects\\ecgmuzbak\\sft\\py\\zephyr-bt\\test_data"
    ser = TimedVirtualSerial(test_data_dir + "/120-second-bt-stream.dat",
                                test_data_dir + "/120-second-bt-stream-timing.csv")
else:
    serial_port_dict = {"Darwin": "/dev/cu.BHBHT001931-iSerialPort1",
                        "Windows": 4}
    serial_port = serial_port_dict[platform.system()]
    ser = serial.Serial(serial_port)
    
class ZephyrConnect( QThread ):
    ''' Send QT signal whenever the selected packet is received
        from the device
    '''
    def __init__( self ):
        QThread.__init__(self)
        self.prev_val = 0
       
    def run(self):
        while True:
            simulation_workflow( [self.callback], ser )

    def callback(self, value_name, value):    
        if value_name is 'rr' and value != self.prev_val:
            rri_ms = int(abs(value)*1000)
            self.prev_val = value
            self.emit( SIGNAL( 'newRRI' ), rri_ms )

        if value_name is 'breathing':
            self.emit( SIGNAL( 'newBW' ), value )

        if value_name is 'heart_rate':
            self.emit( SIGNAL( 'newHR' ), value )
