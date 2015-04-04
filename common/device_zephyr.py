"""
ZephyrApp, a real-time plotting software for the Bioharness 3.0 device.
Copyright (C) 2015  Darko Petrovic

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import zephyr
from zephyr.collector import MeasurementCollector
from zephyr.bioharness import BioHarnessSignalAnalysis, BioHarnessPacketHandler
from zephyr.delayed_stream import DelayedRealTimeStream
from zephyr.message import MessagePayloadParser
from zephyr.protocol import BioHarnessProtocol, MessageFrameParser, MessageDataLogger
from zephyr.testing import TimedVirtualSerial
from PyQt4.QtCore import QThread, SIGNAL
import platform
import serial
import glob
import logging
import time

# Create test data and use it for the virtual serial (self.virtual_serial must be False!)
CREATE_TEST_DATA = False
test_data_dir = "./testdata"

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
        return glob.glob('/dev/ttyS*') + glob.glob('/dev/rfcomm*')


class ZephyrDevice( QThread ):
    """ Send QT signal whenever the selected packet is received
        from the device
    """
    def __init__( self ):
        QThread.__init__(self)
        self.prev_val = 0
        self.SerialNumber = ''
        self.connected = False
        self.paused = False
        self.running = False
        self.create_test_data = False
        self.PacketType = { 'GENERAL':0x14,
                            'BREATHING':0x15,
                            'ECG':0x16,
                            'RRDATA':0x19,
                            'ACC':0x1E,
                            'SUMMARY':0xBD,}
        
        self.virtual_serial = False

        zephyr.configure_root_logger()
        if CREATE_TEST_DATA is True and self.virtual_serial is False:
            self.testdata_writer = MessageDataLogger(test_data_dir + "/5-minutes-zephyr-stream-03")

    def connectTo(self, serialport, virtual=False):
        try:
            if virtual is True:
                self.ser = TimedVirtualSerial(test_data_dir + "/5-minutes-zephyr-stream-03.dat",
                                         test_data_dir + "/5-minutes-zephyr-stream-03-timing.csv")
                self.connected = True
                self.virtual_serial = True
            else:
                self.ser = serial.Serial( serialport )
                self.virtual_serial = False
            self.ser.close() # in case the port is already in use
            self.ser.open()
            self.initialize_device()
            return True
        except serial.SerialException:
            return False

    def initialize_device(self):

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

        # The delayed stream is useful to synchronize the data coming from the device
        # and provides an easy reading by sending tuples like (signal name, sample value)
        self.delayed_stream_thread = DelayedRealTimeStream(collector, [self.callback], 1)

        self.protocol = BioHarnessProtocol(self.ser, [message_parser.parse_data, self.create_test_data_function])

        if self.virtual_serial is False :
            self.protocol.add_initilization_message( 0x0B, []) # get Serial Number
            self.connect( self, SIGNAL( 'Message' ), self._callback_serial_test )
            # by default disable every packet:
            self.protocol.add_initilization_message(self.PacketType['SUMMARY'], [0]) # disable summary packet
            self.protocol.add_initilization_message(self.PacketType['BREATHING'], [0]) # disable breathing waveform
            self.protocol.add_initilization_message(self.PacketType['ECG'], [0]) # disable ecg waveform
            self.protocol.add_initilization_message(self.PacketType['RRDATA'], [0]) # disable rr data
            self.protocol.add_initilization_message(self.PacketType['ACC'], [0]) # disable accelerometer waveform

    def _callback_serial_test( self, message ):
        if hasattr(message, 'Number'):
            # Message is the serial number
            self.disconnect(self, SIGNAL( 'Message' ), self._callback_serial_test)
            if message.Number != '':
                self.SerialNumber = message.Number.strip()
                self.connected = True
                self.emit( SIGNAL( 'Message' ), "connected" )

    def run(self):
        self.running = True
        self.delayed_stream_thread.start()
        self.protocol.start()
        while self.running:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                self.terminate()
        logging.debug("ZephyrDevice QThread is out of the while loop.")

    def terminate(self):
        self.protocol.terminate()
        self.protocol.join()
        self.delayed_stream_thread.terminate()
        self.delayed_stream_thread.join()
        self.ser.close()
        self.running = False
        self.connected = False
        del self.protocol

    def resume(self):
        self.ser.paused = False

    def pause(self):
        self.ser.paused = True

    def callback(self, value_name, value):    
        if value_name is 'rr' and value != self.prev_val:
            rri_ms = int(abs(value)*1000)
            self.prev_val = value
            self.emit( SIGNAL( 'rrinterval' ), rri_ms )

        # if value_name is 'breathing':
        #     self.emit( SIGNAL( 'breathing_wave' ), value )

        # if value_name is 'ecg':
        #     self.emit( SIGNAL( 'ecg' ), value )

        if value_name is 'heart_rate':
            self.emit( SIGNAL( 'heart_rate' ), value )

        if value_name is 'respiration_rate':
            self.emit( SIGNAL( 'respiration_rate' ), value )

        if value_name is 'breathing_wave_amplitude':
            self.emit( SIGNAL( 'breathing_wave_amplitude' ), value )
            print value

        if value_name is 'activity':
            self.emit( SIGNAL( 'activity' ), value )

        if value_name is 'posture':
            if value > 180:
                # convert two's complement to decimal
                posture = value-(1<<16)
            else:
                posture = value
            self.emit( SIGNAL( 'posture' ), posture )

    def anyotherpackets( self, message ):
        self.emit( SIGNAL( 'Message' ), message )

        if type(message) is zephyr.message.SignalPacket and message.type == 'ecg':
            self.emit( SIGNAL( 'ecg' ), message.samples )

        if type(message) is zephyr.message.SignalPacket and message.type == 'breathing':
            self.emit( SIGNAL( 'breathing_wave' ), message.samples )

    def sendmessage(self, message_id, payload):
        self.protocol.add_initilization_message(message_id, payload)

    def enablePacket( self, packet_type ):
        try:
            data = [1]
            if packet_type == 'SUMMARY':
                data = [1, 0]
            self.sendmessage(self.PacketType[packet_type], data)
            return True
        except:
            return False

    def disablePacket( self, packet_type ):
        try:
            data = [0]
            if packet_type == 'SUMMARY':
                data = [0, 0]
            self.sendmessage(self.PacketType[packet_type], data)
            return True
        except:
            return False

    def create_test_data_function(self, stream_data):
        if CREATE_TEST_DATA is True and self.virtual_serial is False:
            self.testdata_writer( stream_data )

