#Zephyr Integration
import zephyr
from zephyr.collector import MeasurementCollector
from zephyr.bioharness import BioHarnessSignalAnalysis, BioHarnessPacketHandler
from zephyr.delayed_stream import DelayedRealTimeStream
from zephyr.message import MessagePayloadParser
from zephyr.protocol import Protocol, BioHarnessProtocol, MessageFrameParser
from zephyr.testing import TimedVirtualSerial, simulation_workflow
from PyQt4.QtGui import QWidget
from PyQt4.QtCore import QThread, SIGNAL
import platform
import serial
import glob
import time

# Set to FALSE to use the real data coming from the device
USE_TEST_DATA = False

if USE_TEST_DATA is True:
    test_data_dir = "A:\\Projects\\ecgmuzbak\\sft\\py\\zephyr-bt\\test_data"
    ser = TimedVirtualSerial(test_data_dir + "/120-second-bt-stream.dat",
                                test_data_dir + "/120-second-bt-stream-timing.csv")
else:
    serial_port_dict = {"Darwin": "/dev/cu.BHBHT001931-iSerialPort1",
                        "Windows": 4}
    serial_port = serial_port_dict[platform.system()]
    #ser = serial.Serial(serial_port)

# A function that tries to list serial ports on most common platforms
def list_serial_ports():
    system_name = platform.system()
    if system_name == "Windows":
        # Scan for available ports.
        available = []
        for i in range(256):
            try:
                s = serial.Serial(i)
                available.append(i)
                s.close()
            except serial.SerialException:
                pass
        return available
    elif system_name == "Darwin":
        # Mac
        return glob.glob('/dev/tty*') + glob.glob('/dev/cu*')
    else:
        # Assume Linux or something else
        return glob.glob('/dev/ttyS*') + glob.glob('/dev/ttyUSB*')


class ZephyrConnect( QThread ):
    """ Send QT signal whenever the selected packet is received
        from the device
    """
    def __init__( self ):
        QThread.__init__(self)
        self.prev_val = 0
        self.SerialNumber = ''
        self.connected = False
        self.PacketType = {'BREATHING':0x15,
                           'ECG':0x16,
                           'RRDATA':0x19,
                           'ACC':0x1E}

    def connectTo(self, comport):
        try:
            self.ser = serial.Serial( comport )
            self.ser.close()
            self.ser.open() # in case the port is already in use
            self.initialize_device()
            return True
        except serial.SerialException:
            return False

    def initialize_device(self):
        zephyr.configure_root_logger()

        collector = MeasurementCollector()

        rr_signal_analysis = BioHarnessSignalAnalysis([], [collector.handle_event])

        signal_packet_handler_bh = BioHarnessPacketHandler([collector.handle_signal, rr_signal_analysis.handle_signal],
                                                           [collector.handle_event])

        # Handle the payload of the message.
        # We don't treat the message payload at this time. The MessagePayloadParser class, when its method
        # handle_message() is executed (after the MessageFrameParser has verified the frame), will callbacks
        # the function specified in the list below with a correct message format.
        payload_parser = MessagePayloadParser([signal_packet_handler_bh.handle_packet, self.anyotherpackets])

        # handle the frame: verify STX, DLC, CRC and execute callback with the message in parameter
        message_parser = MessageFrameParser([payload_parser.handle_message])

        self.delayed_stream_thread = DelayedRealTimeStream(collector, [self.callback], 1.2)

        self.protocol = BioHarnessProtocol(self.ser, [message_parser.parse_data])
        self.protocol.add_initilization_message( 0x0B, []) # get Serial Number
        #self.connect( self, SIGNAL( 'Message' ), self._callback_serial_test )

        # by default disable every packet:
        self.protocol.add_initilization_message(self.PacketType['BREATHING'], [0]) # disable breathing waveform
        self.protocol.add_initilization_message(self.PacketType['ECG'], [0]) # disable ecg waveform
        self.protocol.add_initilization_message(self.PacketType['RRDATA'], [0]) # disable rr data
        self.protocol.add_initilization_message(self.PacketType['ACC'], [0]) # disable accelerometer waveform

    def _callback_serial_test(self, message ):
       # Message is the serial number
       print message.Number
       if message.Number != '':
           self.SerialNumber = message.Number
           self.connected = True

    def run(self):
        self.running = True
        while self.running:
            self.delayed_stream_thread.start()
            try:
                self.protocol.run()
            except EOFError:
                pass
    
            self.delayed_stream_thread.terminate()
            self.delayed_stream_thread.join()

    def terminate(self):
        self.running = False
        self.protocol.terminate()

    def callback(self, value_name, value):    
        if value_name is 'rr' and value != self.prev_val:
            rri_ms = int(abs(value)*1000)
            self.prev_val = value
            self.emit( SIGNAL( 'newRRI' ), rri_ms )

        if value_name is 'breathing':
            self.emit( SIGNAL( 'newBW' ), value )

        if value_name is 'heart_rate':
            self.emit( SIGNAL( 'newHR' ), value )

    def anyotherpackets( self, message ):
        self.emit( SIGNAL( 'Message' ), message )
        #print message

    def sendmessage(self, message_id, payload):
        self.protocol.add_initilization_message(message_id, payload)

    def enablePacket( self, packet_type ):
        try:
            self.sendmessage(self.PacketType[packet_type], [1])
            return True
        except:
            return False

    def disablePacket( self, packet_type ):
        try:
            self.sendmessage(self.PacketType[packet_type], [0])
            return True
        except:
            return False

