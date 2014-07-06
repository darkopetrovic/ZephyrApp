import platform
import time
import numpy as np
from datetime import datetime

from guidata.qt.QtGui import (QWidget, QMainWindow, QVBoxLayout, qApp, QTextEdit,
                               QFont, QColor, QLabel, QAction, QIcon, QHBoxLayout,
                               QLineEdit, QSizePolicy, QMessageBox, QPushButton,
                               QDialog, QDialogButtonBox, QGridLayout, QGroupBox,
                               QRadioButton, QComboBox, QSound
                            )
from guidata.qtwidgets import DockableWidget
from guidata.qt.QtCore import (Qt, QThread, QSettings, QTimer, QSize, SIGNAL, QT_VERSION_STR, PYQT_VERSION_STR)
from guidata.configtools import get_icon
from guidata.qthelpers import create_action, add_actions, get_std_icon
from guidata.dataset.datatypes import (DataSet, BeginGroup, EndGroup, ValueProp)
from guidata.dataset.dataitems import (ChoiceItem, MultipleChoiceItem, BoolItem, StringItem, DirectoryItem)
from guidata.dataset.qtwidgets import DataSetShowGroupBox, DataSetEditGroupBox
from guiqwt.plot import CurveWidget, CurvePlot, CurveDialog
from guiqwt.shapes import RectangleShape
from guiqwt.styles import ShapeParam
from guiqwt.builder import make
from guiqwt.config import _
from PyQt4.Qwt5 import (QwtPlot, QwtScaleDraw, QwtText)

# From own files:
#sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from common.hrv import TimeSeriesContainer, ProcessBreathingWave
from common.device_zephyr import ZephyrConnect, VIRTUAL_SERIAL, list_serial_ports
from common.data_storage import DataStorage
import zephyr.message
#from noise import MakeNoise


APP_NAME = _("Zephyr Biofeedback")
VERSION = '1.0.0'

# Activate settings with a checkbox
DataStorage_database    = ValueProp(False)
DataStorage_files       = ValueProp(False)

class AppSettings( DataSet ):
    serialports = list_serial_ports()
    ports = []
    for s in serialports:
        # windows port is only a number
        if isinstance(s,int):
            port = s
            label = 'COM%d' % (port+1)
        else:
            port = label = s
        ports.append( (port, '%s' % label) )

    # 'ports' must be a tuble, like (0,'COM1') for windows
    serialport = ChoiceItem("Serial Port", ports)
    bh_packets = MultipleChoiceItem("Enable BioHarness Packets",
                                  ["RR Data", "Breathing", "ECG (not implemented yet)",
                                   "Accelerometer (not implemented yet)"],
                                       [0,1]).vertical(1).set_pos(col=0)
    timedsession = ChoiceItem("Timed Session",
                              [(5, "5 minutes"), (10, "10 minutes"),
                               (15, "15 minutes"), (20, "20 minutes"),
                               (30, "30 minutes")]
                            )

    g1 = BeginGroup("Data Storage")
    # Database storage:
    enable_database = BoolItem(u"Enable database storage",
                       help=u"If disabled, the following parameters will be ignored",
                       default=False).set_prop("display", store=DataStorage_database)
    db_host = StringItem(u"Host", notempty=True).set_prop("display", active=DataStorage_database)
    db_user = StringItem(u"User", notempty=True).set_prop("display", active=DataStorage_database)
    db_pwd = StringItem(u"Password", notempty=True).set_prop("display", active=DataStorage_database)
    db_dbname = StringItem(u"Database", notempty=True).set_prop("display", active=DataStorage_database)

    # Files storage
    enable_files = BoolItem(u"Enable files storage",
                               help=u"If disabled, the following parameters will be ignored",
                               default=False).set_prop("display", store=DataStorage_files)
    directory_storage = DirectoryItem("Directory").set_prop("display", active=DataStorage_files)

    _g1 = EndGroup("Data Storage")
 
class MainWindow( QMainWindow ):
    def __init__(self):
        QMainWindow.__init__(self)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(get_icon('python.png'))
        self.timeout = None

        # Welcome message in statusbar:
        status = self.statusBar()
        status.showMessage(_("Zephyr BioHarness 3.0"), 5000)

        self._setup_layout()
        self._setup_menu()
        self._load_settings()
        self._init_objects()
        self.show()

    def _setup_menu(self):
        # File menu
        file_menu = self.menuBar().addMenu(_("File"))
        settings_action = create_action(self, _("Settings"),
                                   icon=get_icon('settings.png'),
                                   tip=_("Settings"),
                                   triggered=self.edit_settings)
        quit_action = create_action(self, _("Quit"),
                                    shortcut="Ctrl+Q",
                                    icon=get_std_icon("DialogCloseButton"),
                                    tip=_("Quit application"),
                                    triggered=self.close)
        add_actions(file_menu, (settings_action, None, quit_action))

        # View menu
        view_menu = self.createPopupMenu()
        view_menu.setTitle(_(u"&View"))
        self.menuBar().addMenu(view_menu)

        # Help menu
        help_menu = self.menuBar().addMenu("?")
        about_action = create_action(self, _("About..."),
                                     icon=get_std_icon('MessageBoxInformation'),
                                     triggered=self.about)
        add_actions(help_menu, (about_action,))

        # Base toolbar
        self.connectAction = QAction(QIcon('common/disconnected.png'), 'Connect', self)
        self.connectAction.triggered.connect( self.connect_button )
        self.playAction = QAction(QIcon('common/play.png'), 'Play free', self)
        self.playAction.triggered.connect( self.start_free_session_button )
        self.stopAction = QAction(QIcon('common/stop.png'), 'Stop', self)
        self.stopAction.triggered.connect( self.stop_button )
        self.timedAction = QAction(QIcon('common/timed.png'), 'Start', self)
        self.timedAction.triggered.connect( self.start_timed_session_button )

        self.toolbar = self.addToolBar('Controls')
        self.toolbar.addAction( self.connectAction )
        self.toolbar.addAction( self.playAction )
        self.toolbar.addAction( self.stopAction )
        self.toolbar.addAction( self.timedAction )
        self.toolbar.setObjectName('Controls')

        # Time toolbar
        self.timer = Timer( self )
        self.connect( self.timer, SIGNAL( 'SessionStop' ), self.session_stop )

    def _setup_layout(self):
        # Allow dockable widgets to be side by side
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks)
        self.setGeometry(300,100,1500,900)

        self.rrplot         = RealTimePlot( self, 'RR-Interval', 'ms', QColor( 255, 0, 0 ) )
        self.bwplot         = RealTimePlot( self, 'Breathing','', QColor( 0, 0, 255 ) )
        self.logarea        = myDockableWidget(self, QTextEdit)
        self.infobox        = myDockableWidget(self, QWidget)
        self.bwpsd          = RealTimePSD( self, 'Breathing PSD', inity=25000 )
        self.rrpsd          = RealTimePSD( self, 'RR-Interval PSD')
        self.rrsdnn         = RealTimePlot( self, 'RRI SDNN','ms', QColor( 0, 0, 255 ) )

        self.logarea.widget.setReadOnly( True )
        self.logarea.widget.setFont( QFont("Courier", 8) )
        self.logarea.widget.setMinimumHeight(150)

        # self.rrpsd.plot.set_axis_limits(QwtPlot.yLeft,0,1)

        self.lbl_sdnn = QLabel( self.infobox.widget )
        self.lbl_sdnn.setText("SDNN: %3.1f ms    " % 0.0)
        self.lbl_sdnn.move(20, 40)
        self.lbl_sdnn.setFont(QFont("Arial", 20))
        self.bhcmdinput = QLineEdit( self.infobox.widget )
        self.bhcmdinput.move(20,80)
        self.bhcmdbutton = QPushButton('Send', self.infobox.widget )
        self.bhcmdbutton.move(20,100)
        self.infobox.widget.connect(self.bhcmdbutton, SIGNAL("clicked()"), self.sendbhcmd)
        #self.bhcmdbutton.clicket.connect( self.sendbhcmd )

        # Add the DockWidget to the main window
        self.info_dock = self.add_dockwidget( self.infobox, _("Infobox") , position=Qt.LeftDockWidgetArea)
        self.rrcurve_dock = self.add_dockwidget( self.rrplot.dockwidget, _("RR-Intervals Plot") )
        self.rrpsd_dock = self.add_dockwidget( self.rrpsd.dockwidget, _("RRI PSD"))
        self.bwcurve_dock = self.add_dockwidget( self.bwplot.dockwidget, _("Breathing Plot") )
        self.bwpsd_dock = self.add_dockwidget( self.bwpsd.dockwidget, _("Breathing PSD") )
        self.splitDockWidget(self.rrcurve_dock, self.rrpsd_dock, Qt.Horizontal)
        self.splitDockWidget(self.bwcurve_dock, self.bwpsd_dock, Qt.Horizontal)
        self.log_dock = self.add_dockwidget( self.logarea, _("Messages"),  position=Qt.BottomDockWidgetArea)
        self.rrsdnn_dock = self.add_dockwidget( self.rrsdnn.dockwidget, _("SDNN on RR-Intervals") )
        self.splitDockWidget(self.rrcurve_dock, self.rrsdnn_dock, Qt.Horizontal)

        # setting the name of the dock widget is required to save correclty
        # the postion of the widget when the application close
        self.info_dock.setObjectName('info_dock')
        self.rrcurve_dock.setObjectName('rrcurve_dock')
        self.rrpsd_dock.setObjectName('rrpsd_dock')
        self.bwcurve_dock.setObjectName('bwcurve_dock')
        self.bwpsd_dock.setObjectName('bwpsd_dock')
        self.log_dock.setObjectName('log_dock')
        self.rrsdnn_dock.setObjectName('rrsdnn_dock')

        self.log_dock.setMinimumHeight( 100 )
        self.log_dock.setMaximumHeight( 300 )
        self.info_dock.setFixedWidth( 220 )

        self.rrcurve_dock.setMinimumSize( 400, 200 )
        self.bwcurve_dock.setMinimumSize( 400, 200 )
        self.rrpsd_dock.setMinimumSize( 400, 200 )
        self.bwpsd_dock.setMinimumSize( 400, 200 )

        # self.rrsdnn.curve.curveparam.curvestyle = 'Dots'
        # self.rrsdnn.curve.curveparam.symbol.marker = 'Ellipse'
        # self.rrsdnn.curve.curveparam.line.width = 3.0
        # self.rrsdnn.curve.update_params()

    def _load_settings(self):
        self.appsettings = DataSetShowGroupBox("Settings",
                                             AppSettings, comment='',
                                             title=_("Application settings"))

        self.settings_storage = QSettings('settings.ini', QSettings.IniFormat)

        self.restoreGeometry( self.settings_storage.value('docksGeometry').toByteArray() )
        self.restoreState( self.settings_storage.value('docksState').toByteArray() )

        # load settings:
        self.settings_storage.beginGroup('BioHarnessPackets')
        rrdata = self.settings_storage.value('rrdata', True).toBool()
        breathing = self.settings_storage.value('breathing', True).toBool()
        ecg = self.settings_storage.value('ecg', False).toBool()
        accelerometer = self.settings_storage.value('accelerometer', False).toBool()
        self.settings_storage.endGroup()
        self.appsettings.dataset.bh_packets = []
        if rrdata: self.appsettings.dataset.bh_packets.append(0)
        if breathing: self.appsettings.dataset.bh_packets.append(1)
        if ecg: self.appsettings.dataset.bh_packets.append(2)
        if accelerometer: self.appsettings.dataset.bh_packets.append(3)

        self.settings_storage.beginGroup('Misc')
        self.appsettings.dataset.timedsession = self.settings_storage.value('TimedDuration', 5).toInt()[0]
        # handle windows and linux serial port name
        portname = self.settings_storage.value('Serial_Port').toString()
        if str(portname).isdigit() is True:
            self.appsettings.dataset.serialport = int(portname)
        else:
             self.appsettings.dataset.serialport = str(portname)
        self.settings_storage.endGroup()

        self.settings_storage.beginGroup('Storage')
        self.appsettings.dataset.enable_database = self.settings_storage.value('db_enable', False).toBool()
        self.appsettings.dataset.db_host = self.settings_storage.value('db_host').toString()
        self.appsettings.dataset.db_user = self.settings_storage.value('db_user').toString()
        self.appsettings.dataset.db_pwd = self.settings_storage.value('db_pwd').toString()
        self.appsettings.dataset.db_dbname = self.settings_storage.value('db_dbname').toString()
        self.appsettings.dataset.enable_files = self.settings_storage.value('files_enable', False).toBool()
        self.appsettings.dataset.directory_storage = self.settings_storage.value('directory').toString()
        self.settings_storage.endGroup()

    def _init_objects(self):
        # The time series container hold the data of the heart beat and breathing signal
        self.timeseriescontainer = TimeSeriesContainer()
        self.process_breathing = ProcessBreathingWave( self.timeseriescontainer )

        self.sessiontype = 'free'

        self.zephyr_connect = ZephyrConnect()
        self.connect( self.zephyr_connect, SIGNAL( 'Message' ), self.printmessage )
        self.connect( self.zephyr_connect, SIGNAL( 'newRRI' ), self.update_RR_plot )
        self.connect( self.zephyr_connect, SIGNAL( 'newBW' ), self.update_BW_plot )
        #self.connect( self.zephyr_connect, SIGNAL( 'newBW' ), self.process_breathing.calculateMinMax )

        # the button are disabled by default
        # they are enabled if the connection to the device is successfull
        self.stopAction.setEnabled( False )
        self.playAction.setEnabled( False )
        self.timedAction.setEnabled( False )

        # Data storage configuration
        # Data storage need the application settings for db credentials
        # and the container where time series are stored
        self.datastorage = DataStorage()
        if self.appsettings.dataset.enable_database is True:
            self.datastorage.enableDbStorage( self.appsettings.dataset )
        self.datastorage.timeseries = self.timeseriescontainer

        self.sound_alerts = SoundAlerts()
        # self.sound_alerts.interval = 1

        # Add the min/max points on the breathing plot
        self.bw_minmax_curve = make.curve( [ ], [ ], 'Min Max Points', QColor( 250, 170, 250 ) )
        self.bw_minmax_curve.curveparam.curvestyle = 'Dots'
        self.bw_minmax_curve.curveparam.symbol.marker = 'Ellipse'
        self.bw_minmax_curve.curveparam.line.width = 3.0
        self.bw_minmax_curve.update_params()

        self.bwplot.plot.add_item( self.bw_minmax_curve )

    def sendbhcmd( self ):
        cmd =  int(str(self.bhcmdinput.text()), 16)
        self.zephyr_connect.sendmessage(cmd, [])

    #------?
    def about( self ):
        QMessageBox.about( self, _("About ")+APP_NAME,
              """<b>%s</b> v%s<p>%s Darko Petrovic
              <br>(Lisence goes here)
              <p>Python %s, Qt %s, PyQt %s %s %s""" % \
              (APP_NAME, VERSION, _("Developped by"), platform.python_version(),
               QT_VERSION_STR, PYQT_VERSION_STR, _("on"), platform.system()) )

    def edit_settings( self ):
        ok = self.appsettings.dataset.edit()

        # save settings in the .ini file
        if ok == 1:
            # Application settings (window position, view, ...):
            # ...
            # User settings:
            rrdata = breathing = ecg = accelerometer = False
            for a in self.appsettings.dataset.bh_packets:
                if a == 0: rrdata = True
                elif a == 1: breathing = True
                elif a == 2: ecg = True
                elif a == 3: accelerometer = True

            self.settings_storage.beginGroup('BioHarnessPackets')
            self.settings_storage.setValue('rrdata', str(rrdata) )
            self.settings_storage.setValue('breathing', str(breathing) )
            self.settings_storage.setValue('ecg', str(ecg) )
            self.settings_storage.setValue('accelerometer', str(accelerometer) )
            self.settings_storage.endGroup()

            self.settings_storage.beginGroup('Misc')
            self.settings_storage.setValue('TimedDuration', self.appsettings.dataset.timedsession )
            self.settings_storage.setValue('Serial_Port', self.appsettings.dataset.serialport )
            self.settings_storage.endGroup()

            self.settings_storage.beginGroup('Storage')
            self.settings_storage.setValue('db_enable', str(self.appsettings.dataset.enable_database) )
            self.settings_storage.setValue('db_host', self.appsettings.dataset.db_host )
            self.settings_storage.setValue('db_user', str(self.appsettings.dataset.db_user) )
            self.settings_storage.setValue('db_pwd', str(self.appsettings.dataset.db_pwd) )
            self.settings_storage.setValue('db_dbname', str(self.appsettings.dataset.db_dbname) )
            self.settings_storage.setValue('files_enable', str(self.appsettings.dataset.enable_files) )
            self.settings_storage.setValue('directory', str(self.appsettings.dataset.directory_storage) )
            self.settings_storage.endGroup()

        if ok==1 and self.appsettings.dataset.enable_database:
            result, message = self.datastorage.test_db_connection()

            if result:
                self.logmessage("Connection to the database '%s established'." % message)
            else:
                self.logmessage("Connection to the database failed: %s" % message, 'error')


    #------GUI refresh/setup
    def add_dockwidget( self, child, title, orientation = Qt.Vertical, position=None ):
        """Add a QDockWidget to the main window."""
        dockwidget, location = child.create_dockwidget( title )
        if position is not None:
            location = position
        self.addDockWidget( location, dockwidget, orientation )
        return dockwidget

    def logmessage( self, text, msgtype='info' ):
        """ Print a message in the message window
        """
        if msgtype == 'error':
            self.logarea.widget.setTextColor( QColor( 255, 0, 0 ) )
        else:
            self.logarea.widget.setTextColor( QColor( 0, 0, 0 ) )

        self.logarea.widget.insertPlainText( text + "\n" )
        sb = self.logarea.widget.verticalScrollBar()
        sb.setValue( sb.maximum() )

    def update_RR_plot( self, value ):
        # Store value in the data-set. We store every value in the dataset
        # but we display only a certain duration specified by 'self.rrplot.window_length'
        self.timeseriescontainer.ts_rri.add_rrinterval( value )
        # Set the data to the curve with values from the time series and update the plot
        # TODO: maybe calculate the start array index with the specified plot window length ?
        self.rrplot.startIdx = self.timeseriescontainer.ts_rri.getSampleIndex( self.rrplot.window_length )
        self.rrplot.update( self.timeseriescontainer.ts_rri.realtime, self.timeseriescontainer.ts_rri.series )

        # Wait minimum 10 samples
        if len(self.timeseriescontainer.ts_rri.series) > 10:
            self.timeseriescontainer.ts_rri.computeLombPeriodogram()
            #self.timeseriescontainer.ts_rri.computeSDNN()
            # if self.psdplot.running is False:
            #         self.psdplot.plot = self.rrpsd
            #         self.psdplot.ts_rri = self.timeseriescontainer.ts_rri
            #         self.psdplot.start()
            # if len(self.timeseriescontainer.ts_rri.series) > 11:
            #     self.psdplot.calculate_intermediate()

            self.rrpsd.update(self.timeseriescontainer.ts_rri.psd_freq, self.timeseriescontainer.ts_rri.psd_mag)
            #self.rrsdnn.startIdx = self.timeseriescontainer.ts_rri.getSampleIndex( self.rrsdnn.window_length )
            #self.rrsdnn.update( self.timeseriescontainer.ts_rri.realtime, self.timeseriescontainer.ts_rri.sdnn )
            # self.logmessage( "PSD nb smpl: %i, SERIES nb smpl %i " %
            #                  (len(self.timeseriescontainer.ts_rri.psd_freq), len(self.timeseriescontainer.ts_rri.series[self.rrplot.startIdx:-1])) )
                #sdnn = float("%3.1f" % self.timeseriescontainer.ts_rri.compute_SDNN())
                #self.lbl_sdnn.setText( "SDNN: %3.1f ms" % sdnn )


    def update_BW_plot( self, value ):
        """ Update the breathing wave plot.

        """
        # Store value in the data-set. We store every value in the dataset
        # but we display only a certain duration specified by 'self.rrplot.window_length'
        self.timeseriescontainer.ts_bw.add_breath( value )

        # Set the data to the curve with values from the data-set and update the plot 
        self.bwplot.startIdx = self.timeseriescontainer.ts_bw.getSampleIndex( self.bwplot.window_length )
        self.bwplot.update( self.timeseriescontainer.ts_bw.realtime, self.timeseriescontainer.ts_bw.series )


        # if len(self.timeseriescontainer.ts_bw.series) > 50:
        #
        #
        #     # ibwtime, ibwval = self.timeseriescontainer.ts_bw.interpolateSignal()
        #     # self.timeseriescontainer.ts_bw.calculateMinMax( ibwtime, ibwval )
        #     #
        #     # idx_start = np.where( self.timeseriescontainer.ts_bw.minmax_time >
        #     #                            self.timeseriescontainer.ts_bw.minmax_time[-1]
        #     #                            -self.bwplot.window_length )[0][0]
        #     #
        #     # print "%f - %f" % (self.timeseriescontainer.ts_bw.minmax_time[-1], self.bwplot.window_length*1000)
        #     # self.bw_minmax_curve.set_data(  self.timeseriescontainer.ts_bw.minmax_time[idx_start:-1],
        #     #                                 self.timeseriescontainer.ts_bw.minmax_val[idx_start:-1] )
        #
        #     # ---- Compute and display the Power Spectral Density of breathing signal
        #     self.timeseriescontainer.ts_bw.computeWelchPeriodogram()
        #     self.bwpsd.update(self.timeseriescontainer.ts_bw.psd_freq, self.timeseriescontainer.ts_bw.psd_mag)

    def printmessage( self, message ):
        if message == 'connected':
            self.logmessage( "Successfully connected to the device %s." % self.zephyr_connect.SerialNumber )
            self._toggle_connect_button()
            if self.timeout:
                self.timeout.stop()
                del self.timeout

        if isinstance(message, zephyr.message.BatteryStatus):
            self.logmessage("Battery charge is %d%%" % message.Charge )

    def _toggle_connect_button(self):
        if self.zephyr_connect.connected is True:
            self.connectAction.setIcon(QIcon('common/connected.png'))
            self.connectAction.setToolTip("Disconnect")
            self.connectAction.triggered.disconnect( self.connect_button )
            self.connectAction.triggered.connect( self.disconnect_button )
            self.playAction.setEnabled( True )
            self.timedAction.setEnabled( True )
        else:
            self.connectAction.setIcon(QIcon('common/disconnected.png'))
            self.connectAction.setToolTip("Connect")
            self.connectAction.triggered.disconnect( self.disconnect_button )
            self.connectAction.triggered.connect( self.connect_button )
            self.playAction.setEnabled( False )
            self.timedAction.setEnabled( False )

    def connect_button(self):
        # The connect button is first trying to open the com port. If the port can be opened,
        # the zephyr protocol functions are instancied and a message is send to the device
        # (the thread is started for this purpose and to let the reception of the response).
        # The device has 3 seconds to respond (a timeout is started to close the serial
        # and terminate the thread in case of no response). When the device responds a signal 'Message'
        # is sent to the GUI (the message is the Serial Number of the device).
        if self.zephyr_connect.connectTo( self.appsettings.dataset.serialport ):
            self.zephyr_connect.start()
            if VIRTUAL_SERIAL is False:
                self.timeout = QTimer( self )
                self.connect( self.timeout, SIGNAL( 'timeout()' ), self.connectionTimeout )
                self.timeout.setSingleShot(True)
                self.timeout.start(3000)
            else:
                self.logmessage("Serial virtualization in use.")
                self._toggle_connect_button()
        else:
            self.logmessage( "Fail to open port '%s' !" % self.appsettings.dataset.serialport, 'error' )

    def disconnect_button(self):
        self.zephyr_connect.terminate()
        if self.zephyr_connect.wait():
            self._toggle_connect_button()
            self.logmessage( "Successfully disconnected from the device." )

    def connectionTimeout(self):
        self.logmessage("Unable to connected to the device on %s." % self.appsettings.dataset.serialport, 'error' )
        self.zephyr_connect.terminate()
        if self.timeout:
            del self.timeout

    def start_free_session_button( self ):
        self.sessiontype = 'free'
        self.timer.initialize( 0 )
        self.session_start()

    def start_timed_session_button(self):
        self.sessiontype = 'timed'
        self.timer.initialize( self.appsettings.dataset.timedsession * 60 )
        self.session_start()

    def stop_button( self ):
        sel = 0
        if self.sessiontype == 'timed':
            sel = QMessageBox.warning( self, "Timed Session",
                                       "A Timed Session is currently active!\nIf you stop the session "
                                       "the session will be stored as a free session.", "OK", "Cancel")
        if sel == 0:
            self.session_stop()

    def session_start( self ):
        self.timeseriescontainer.clearContainer()

        if VIRTUAL_SERIAL is True:
            self.zephyr_connect.resume()

        for a in self.appsettings.dataset.bh_packets:
            if a == 0:
                self.zephyr_connect.enablePacket('RRDATA')
                self.timeseriescontainer.ts_rri.setStartTime()
                self.zephyr_connect.enablePacket('SUMMARY')
            elif a == 1:
                self.zephyr_connect.enablePacket('BREATHING')
                self.timeseriescontainer.ts_bw.setStartTime()

        self.timer.start()
        #self.sound_alerts.start()
        #self.process_breathing.start()
        # handle graphical change:
        self.playAction.setEnabled( False )
        self.timedAction.setEnabled( False )
        self.stopAction.setEnabled( True )
        self.connectAction.setEnabled( False )

    def session_stop(self):
        if VIRTUAL_SERIAL is True:
            self.zephyr_connect.pause()

        for a in self.appsettings.dataset.bh_packets:
            if a == 0: self.zephyr_connect.disablePacket('RRDATA')
            elif a == 1: self.zephyr_connect.disablePacket('BREATHING')
        self.zephyr_connect.disablePacket('SUMMARY')

        self.timer.stop()
        #self.sound_alerts.stop()
        self.process_breathing.stop()
        # handle graphical change:
        self.playAction.setEnabled( True )
        self.timedAction.setEnabled( True )
        self.stopAction.setEnabled( False )
        self.connectAction.setEnabled( True )

        # store the current session?
        if self.appsettings.dataset.enable_database or self.appsettings.dataset.enable_files:
            self.infosdialog = SessionInfos( self, self.datastorage )
            self.connect(self.infosdialog, SIGNAL('accepted()'), self.session_store )
            self.infosdialog.exec_()

            # sel = QMessageBox.question(self, "Save Session", "Store the current session?", "Yes", "No")
            # if sel == 0:
            #
            #


    def session_store(self):
        minutes,seconds = self.timer.getRunningTime()
        duration = str(minutes) + ":" + str(seconds)

        for i, r in enumerate(self.infosdialog.sessiontypes):
            if r.isChecked():
                sessiontype = i+1

        sessiondict = { 'duration':duration,
                        'sessiontype':sessiontype,
                        'breathing_zone': self.infosdialog.breathzone.currentIndex()+1,
                        'note': str(self.infosdialog.note.toPlainText()),
                        'alerts': self.sound_alerts.alerts
        }

        self.datastorage.store_session( sessiondict )
        self.logmessage("Session stored in database.")

    def closeEvent(self, event):
        self.settings_storage.setValue( 'docksGeometry', self.saveGeometry() )
        self.settings_storage.setValue( 'docksState', self.saveState() )
        QMainWindow.closeEvent(self, event)

class PSDThread(QThread):
    def __init__(self):
        QThread.__init__(self)
        self.running=False
        self.plot=None
        self.ts_rri = None
        self.godisplay = False
        self.old_psd_freq = np.array([])
        self.old_psd_mag = np.array([])
    def run(self):
        self.old_psd_mag = self.ts_rri.psd_mag
        self.running=True
        while self.running is True:
            if self.godisplay is True:
                for i in xrange(0,5):
                    self.plot.update(self.ts_rri.psd_freq, self.intermediate[i])
                    time.sleep(0.2)
                self.godisplay = False

    def calculate_intermediate(self):
        self.intermediate = []
        remaining=len(self.ts_rri.psd_mag)-len(self.old_psd_mag)
        for i, f in enumerate(self.old_psd_mag):
            self.intermediate.append( np.linspace(self.old_psd_mag[i], self.ts_rri.psd_mag[i], 5) )
        for x in range(remaining):
            self.intermediate.append(self.ts_rri.psd_mag[i+1+x])
        self.godisplay = True

class myDockableWidget( DockableWidget ):
    LOCATION = Qt.RightDockWidgetArea
    def __init__(self, parent, widgetclass, toolbar = None):
        super(myDockableWidget, self).__init__(parent)
        self.toolbar = toolbar
        layout = QVBoxLayout()
        self.widget = widgetclass()
        layout.addWidget(self.widget)
        self.setLayout(layout)

    def get_plot(self):
        return self.widget.get_plot()

    def sizeHint(self):
        return QSize(500, 300)

class RealTimePlot():
    """ Real time Qwt plot object. 
    """
    def __init__(self, parent, ytitle="Y", yunit='', color=QColor( 255, 0, 0 )):
        self.curve = make.curve( [ ], [ ], '(Curve Name)', color )
        self.dockwidget    = myDockableWidget(parent, CurveWidget, toolbar=True )
        # widget class: CurveWidget
        # plot class: CurvePlot
        # curve class: CurveItem
        self.plot = self.dockwidget.widget.plot
        self.plot.add_item( self.curve )
        self.plot.set_antialiasing( True )
        self.plot.set_axis_title( QwtPlot.xBottom, 'Time' )
        self.plot.set_axis_unit( QwtPlot.xBottom, 's' )
        self.plot.set_axis_title( QwtPlot.yLeft, ytitle )
        self.plot.set_axis_unit( QwtPlot.yLeft, yunit )
        self.plot.setAxisScaleDraw( QwtPlot.xBottom, DateTimeScaleDraw() )
        #self.toolbar = QToolBar(_("Tools"))
        #self.curvewidget.widget.add_toolbar(self.toolbar, "default")
        #self.curvewidget.widget.register_tools()
        self.startIdx = 0
        self.window_length = 60 # seconds

    def set_data( self, x, y ):
        self.curve.set_data( x, y )

    def update( self, x, y ):
        self.curve.set_data( x[self.startIdx:-1], y[self.startIdx:-1] )
        self.plot.do_autoscale()
        #self.plot.replot()




class RealTimePSD():
    """ Real time Qwt plot object.
    """
    def __init__(self, parent, ytitle="Y", inity=1000):
        # self.curve_vlf = make.curve( [ ], [ ], '(Curve Name)', QColor( 255, 0, 0 ), shade=0.5 )
        # self.curve_lf = make.curve( [ ], [ ], '(Curve Name)', QColor( 0, 255, 0 ), shade=0.5 )
        # self.curve_hf = make.curve( [ ], [ ], '(Curve Name)', QColor( 0, 0, 255 ), shade=0.5 )
        self.psdcurve = make.curve( [ ], [ ], '(Curve Name)', QColor( 160, 160, 160 ), shade=0.2 )

        def buildrect(x1, x2, filler):
            rect = RectangleShape(x1, 0., x2, inity)
            rect.brush.setStyle( Qt.SolidPattern )
            rect.brush.setColor( filler )
            rect.pen.setStyle( Qt.NoPen )
            return rect

        self.dockwidget    = myDockableWidget(parent, CurveWidget, toolbar=True )
        # self.plot = self.curvewidget.get_plot()
        self.plot = self.dockwidget.widget.plot
        # self.plot.add_item( self.curve_vlf )
        # self.plot.add_item( self.curve_lf )
        # self.plot.add_item( self.curve_hf )
        alpha = 100
        self.plot.add_item( buildrect(0.,0.04, QColor(255,178,178,alpha)) )
        self.plot.add_item( buildrect(0.04,0.15, QColor(178,178,255,alpha)) )
        self.plot.add_item( buildrect(0.15,0.5, QColor(255,255,178,alpha)) )
        self.plot.add_item( self.psdcurve )

        self.plot.set_antialiasing( True )
        self.plot.set_axis_title( QwtPlot.xBottom, 'Frequency' )
        self.plot.set_axis_unit( QwtPlot.xBottom, 'Hz' )
        self.plot.set_axis_title( QwtPlot.yLeft, ytitle )
        self.plot.set_axis_unit( QwtPlot.yLeft, 's^2/Hz' )

        #self.plot.setAxisScale(QwtPlot.xBottom, 0, 0.5)
        self.plot.set_axis_limits( QwtPlot.xBottom, 0, 0.5 )
        #self.plot.set_axis_limits( QwtPlot.yLeft, 0, inity )

    def set_data( self, x, y ):
        self.psdcurve.set_data( x, y )

    def update( self, x, y ):


        # vlf_idx_min = 0
        # lf_idx_min = np.where(x >= 0.04)[0][0]
        # hf_idx_min = np.where(x >= 0.15)[0][0]


        # for i, f in enumerate( x ):
        #     if 0 < f <= 0.04:
        #
        #         self.VLFpwr += self.psd_mag[i]
        #     elif 0.04 > f <= 0.15:
        #         self.LFpwr += self.psd_mag[i]
        #     elif 0.15 > f <= 0.4:
        #         self.HFpwr += self.psd_mag[i]


        # self.curve_vlf.set_data( x[vlf_idx_min], y[lf_idx_min-1] )
        # self.curve_lf.set_data( x[lf_idx_min], y[hf_idx_min-1] )
        # self.curve_hf.set_data( x[hf_idx_min], y[-1] )

        # self.curve_vlf.set_data( x[vlf_idx_min:lf_idx_min+1], y[vlf_idx_min:lf_idx_min+1] )
        # self.curve_lf.set_data( x[lf_idx_min:hf_idx_min+1], y[lf_idx_min:hf_idx_min+1] )
        # self.curve_hf.set_data( x[hf_idx_min:-1], y[hf_idx_min:-1] )

        self.psdcurve.set_data( x, y )


        #self.plot.do_autoscale()
        self.plot.replot()

    # def sizeHint(self):
    #     return QSize(500, 300)

class DateTimeScaleDraw( QwtScaleDraw ):
    """Class used to draw a datetime axis on the plot.
    """
    def __init__( self, *args ):
        QwtScaleDraw.__init__( self, *args )

    def label(self, value ):
        """ Function used to create the text of each label
        used to draw the axis.
        """
        try:
            dt = datetime.fromtimestamp( value )
            return QwtText( '%s' % dt.strftime( '%H:%M:%S' ) )
        except:
            pass

class Timer( QThread ):
    def __init__( self, parent ):
        QThread.__init__(self, parent)
        self.currsecond = 0
        self.asc = True
        self.initseconds = 0
        self.stopped = True

        self.toolbar_time = parent.addToolBar( 'Time' )
        self.toolbar_time.setMovable( False )
        self.toolbar_time.setObjectName('Time')
        self.timer = QLineEdit()
        self.timer.setStyleSheet("QLineEdit { font-size: 19px; font-family: Courier New; \
                                border-style: outset; border-radius: 10px; \
                                font-weight:bold; text-align:center}")
        self.timer.setFixedWidth( 80 )
        self.timer.setReadOnly( True )
        self.timer.setAlignment( Qt.AlignHCenter )

        left_spacer = QWidget()
        left_spacer.setSizePolicy( QSizePolicy.Expanding, QSizePolicy.Expanding )
        self.toolbar_time.addWidget( left_spacer )
        self.toolbar_time.addWidget( self.timer )

        self.initialize(0)

    def run( self ):
        self.stopped = False
        while not self.stopped:
            time.sleep(1)
            if self.asc is True:
                self.currsecond += 1
            else :
                if self.currsecond > 0:
                    self.currsecond -= 1
                else:
                    self.emit( SIGNAL( 'SessionStop' ) )
            self.update_timer_display( self.currsecond )

    def stop( self ):
        self.stopped = True

    def initialize( self, nbseconds ):
        self.currsecond = nbseconds
        self.initseconds = nbseconds
        self.update_timer_display( nbseconds )
        if nbseconds > 0:
            self.asc = False
        else:
            self.asc = True

    @staticmethod
    def _convertInMinutes( nbseconds ):
        minutes = nbseconds / 60
        seconds = nbseconds - minutes * 60
        return minutes, seconds

    def update_timer_display( self, nbseconds ):
        minutes, seconds = self._convertInMinutes( nbseconds )
        timer_string = "%02d:%02d" % ( minutes, seconds )
        self.timer.setText( timer_string )

    def getRunningTime( self ):
        """ Return the duration of the session.
        """
        if self.asc is False:
            totalsecs = self.initseconds - self.currsecond
        else:
            totalsecs = self.currsecond

        minutes, seconds = self._convertInMinutes( totalsecs )
        return  minutes, seconds

class SoundAlerts( QThread ):
    def __init__( self ):
        QThread.__init__(self )
        self.interval = 0
        self.running = False
        self.sound = QSound('common/notification.wav')
        self.alerts = []

    def run(self):
        self.running = True
        while self.running is True:
            # time.sleep( self.interval * 60 )
            time.sleep( 20 )
            if self.running is True:
                self.sound.play()
                self.alerts.append( datetime.now().strftime("%Y-%m-%d %H:%M:%S") )

    def stop( self ):
        self.running = False

class SessionInfos( QDialog ):
    def __init__(self, parent, appdata):
        super(SessionInfos, self).__init__(parent)
        self.appdata = appdata
        self.setWindowTitle( 'Information for the session' )
        self.setFixedSize(250, 300)

        self.buttonBox = QDialogButtonBox( self )
        self.buttonBox.setOrientation( Qt.Horizontal )
        self.buttonBox.setStandardButtons( QDialogButtonBox.Cancel|QDialogButtonBox.Ok )

        labelcombo = QLabel( 'Breathing Zone:' )
        self.breathzone = QComboBox()
        zones = self.appdata.get_breathing_zones()
        for z in zones:
            self.breathzone.addItem( z[1], z[0] )

        self.breathzone.move(10, 10)

        labelnote = QLabel( 'Note:' )
        self.note = QTextEdit()

        layout = QVBoxLayout()
        layout.addWidget( self.create_SessionType_Group() )
        layout.addWidget( labelcombo )
        layout.addWidget( self.breathzone )
        layout.addWidget( labelnote )
        layout.addWidget( self.note )
        layout.addWidget( self.buttonBox )

        self.setLayout( layout )

        self.buttonBox.accepted.connect( self.accept )
        self.buttonBox.rejected.connect( self.reject )

    # def accept(self):
    #     print "voila"
    #
    # def reject(self):
    #     pass

    def create_SessionType_Group( self ):
        groupBox = QGroupBox(' Session Type' )
        vbox = QVBoxLayout()
        self.sessiontypes = []
        types = self.appdata.get_session_types()
        for t in types:
            self.sessiontypes.append( QRadioButton( t[1] ) )
            vbox.addWidget( self.sessiontypes[-1] )
        self.sessiontypes[0].setChecked(True)
        vbox.addStretch(1)
        groupBox.setLayout(vbox)
        return groupBox
