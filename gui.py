import sys, os, platform
import datetime
import time

from guidata.qt.QtGui import (QWidget, QMainWindow, QVBoxLayout, qApp, QTextEdit,\
                               QFont, QColor, QLabel, QAction, QIcon, QHBoxLayout, \
                               QLineEdit, QSizePolicy, QMessageBox, QPushButton, \
                            )
from guidata.qtwidgets import DockableWidget
from guidata.qt.QtCore import (Qt, QThread, QSettings, QTimer, SIGNAL, QT_VERSION_STR, PYQT_VERSION_STR)
from guidata.configtools import get_icon
from guidata.qthelpers import create_action, add_actions, get_std_icon
from guidata.dataset.datatypes import (DataSet, BeginGroup, EndGroup, ValueProp)
from guidata.dataset.dataitems import (ChoiceItem, MultipleChoiceItem, BoolItem, StringItem, DirectoryItem)
from guidata.dataset.qtwidgets import DataSetShowGroupBox, DataSetEditGroupBox
from guiqwt.plot import CurveWidget, CurvePlot
from guiqwt.builder import make
from guiqwt.config import _
from PyQt4.Qwt5.Qwt import QwtPlot, QwtScaleDraw, QwtText

# From own files:
#sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from common.hrv import RRI_BW_Data, RRIntervals, BreathingWave
from common.device_zephyr import ZephyrConnect, USE_TEST_DATA, list_serial_ports
from common.data_storage import DataStorage
import zephyr
#from noise import MakeNoise
  
APP_NAME = _("Zephyr Biofeedback")
VERSION = '1.0.0'

DataStorage_database    = ValueProp(False)
DataStorage_files       = ValueProp(False)

class AppSettings( DataSet ):

    comports = list_serial_ports()

    ports = []
    for p in comports:
        ports.append((p, 'COM%d' % (p+1)) )

    comport = ChoiceItem("COM Port", ports)
    bh_packets = MultipleChoiceItem("Enable BioHarness Packets",
                                  ["RR Data", "Breathing", "ECG (not implemented yet)",
                                   "Accelerometer (not implemented yet)"], \
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

        self.appsettings = DataSetShowGroupBox("Settings",
                                             AppSettings, comment='', 
                                             title=_("Application settings"))

        self.settings_storage = QSettings('settings.ini', QSettings.IniFormat)

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

        # Welcome message in statusbar:
        status = self.statusBar()
        status.showMessage(_("Zephyr BioHarness 3.0"), 5000)

        # Layout Setup --------------------------------------------------------------------------------------------
        # ---------------------------------------------------------------------------------------------------------

        # Allow dockable widgets to be side by side
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks)  
        self.setGeometry(300,100,1000,900)

        self.rrplot         = RealTimePlot( self, 'RR-Interval [ms]', QColor( 255, 0, 0 ) )
        self.bwplot         = RealTimePlot( self, 'Breathing', QColor( 0, 0, 255 ) )
        self.logarea        = DockablePlotWidget(self, QTextEdit)
        self.infobox        = DockablePlotWidget(self, QWidget)

        self.logarea.widget.setReadOnly( True )
        self.logarea.widget.setFont( QFont("Courier", 8) )
        self.logarea.widget.setMinimumHeight(200)
        self.logarea.widget.setMinimumWidth(500)
        self.infobox.widget.setMinimumHeight(200)
        self.infobox.widget.setMinimumWidth(200)
    
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
        self.rrcurve_dock = self.add_dockwidget( self.rrplot.curvewidget, _("RR-Intervals Plot"),
                                                 Qt.Vertical, position=Qt.TopDockWidgetArea )
        self.bwcurve_dock = self.add_dockwidget( self.bwplot.curvewidget, _("Breathing Plot"),
                                                 Qt.Vertical, position=Qt.TopDockWidgetArea )
        self.log_dock = self.add_dockwidget( self.logarea, _("Messages"), Qt.Horizontal, Qt.RightDockWidgetArea)
        self.info_dock = self.add_dockwidget( self.infobox, _("Infobox"), Qt.Horizontal, Qt.LeftDockWidgetArea )        

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
        self.stopAction.setEnabled( False )
        self.timedAction = QAction(QIcon('common/timed.png'), 'Start', self)
        self.timedAction.triggered.connect( self.start_timed_session_button )

        self.toolbar = self.addToolBar('Controls')
        self.toolbar.addAction( self.connectAction )
        self.toolbar.addAction( self.playAction )
        self.toolbar.addAction( self.stopAction )
        self.toolbar.addAction( self.timedAction )

        # Time toolbar
        self.timer = Timer( self )
        self.connect( self.timer, SIGNAL( 'SessionStop' ), self.session_stop )
 
        self.show()
        # After this call the widget will be visually in front of any 
        # overlapping sibling widgets.
        self.rrcurve_dock.raise_()

        # Objects setup -------------------------------------------------------------------------------------------
        # ---------------------------------------------------------------------------------------------------------

        self.ds_rri = RRIntervals()
        self.ds_bw = BreathingWave()
        self.sessiontype = 'free'
        self.zephyr_connect = ZephyrConnect()
        self.connect( self.zephyr_connect, SIGNAL( 'Message' ), self.printmessage )

        # the button are disabled by default
        # they are enabled if the connection to the device is successfull
        if USE_TEST_DATA is False:
            self.playAction.setEnabled( False )
            self.timedAction.setEnabled( False )

        # the connection to the device is automatically tested
        # self.zephyr_connect = ZephyrConnect()
        # # we connect to the device immediately if real data is used
        # # otherwise, the thread is started once we click the 'start' button
        # #if USE_TEST_DATA is False:
        #     #self.zephyr_connect.start()
        #
        # #if self.zephyr_connect.connected:
        #
        # self.connect( self.zephyr_connect, SIGNAL( 'newRRI' ), self.update_RR_plot )
        # self.connect( self.zephyr_connect, SIGNAL( 'newBW' ), self.update_BW_plot )

        #
        # self.logmessage("BioHarness 3.0 with serial number '%s' connected." % self.zephyr_connect.SerialNumber )
        # self.playAction.setEnabled( True )
        # self.timedAction.setEnabled( True )

        # Data storage configuration
        self.datastorage = DataStorage( self.appsettings.dataset )

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
    def add_dockwidget(self, child, title, orientation = Qt.Vertical, position=None ):
        """Add QDockWidget and toggleViewAction"""
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
        self.ds_rri.add_rrinterval( value )
        # Set the data to the curve with values from the data-set (ds_*) and update the plot 
        self.rrplot.startIdx = self.ds_rri.getSampleIndex( self.rrplot.window_length )
        self.rrplot.update( self.ds_rri.realtime, self.ds_rri.series )

        #self.logmessage( "Incoming RRI: %i ms" % value )
        #sdnn = float("%3.1f" % self.ds_rri.compute_SDNN())
        #self.lbl_sdnn.setText( "SDNN: %3.1f ms" % sdnn )

    def update_BW_plot( self, value ):
        # Store value in the data-set. We store every value in the dataset
        # but we display only a certain duration specified by 'self.rrplot.window_length'
        self.ds_bw.add_breath( value )
        # Set the data to the curve with values from the data-set and update the plot 
        self.bwplot.startIdx = self.ds_bw.getSampleIndex( self.bwplot.window_length )
        self.bwplot.update( self.ds_bw.realtime, self.ds_bw.series )

    def printmessage( self, message ):

        if isinstance(message, zephyr.message.SerialNumber):
            self.logmessage("Successfully connected to the device %s." % message.Number )
            self.timeout.stop()
            del self.timeout

        if isinstance(message, zephyr.message.BatteryStatus):
            self.logmessage("Battery charge is %d%%" % message.Charge )

    def connect_button(self):
        if self.zephyr_connect.connectTo( self.appsettings.dataset.comport ):
            self.zephyr_connect.start()
            self.timeout = QTimer( self )
            self.connect( self.timeout, SIGNAL( 'timeout()' ), self.connectionTimeout )
            self.timeout.setSingleShot(True)
            self.timeout.start(3000)
        else:
            self.logmessage( "Fail to open port COM%d!" % (self.appsettings.dataset.comport+1), 'error' )

    def connectionTimeout(self):
        self.logmessage("Unable to connected to the device on COM%d." % (self.appsettings.dataset.comport+1), 'error' )
        self.zephyr_connect.ser.close()
        self.zephyr_connect.terminate()

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
                                       "A Timed Session is currently active!\nIf you stop the session " \
                                       "the session will be stored as a free session.", "OK", "Cancel")
        if sel == 0:
            self.session_stop()

    def session_start( self ):
        if USE_TEST_DATA is True:
            self.zephyr_connect.start()
        for a in self.appsettings.dataset.bh_packets:
            if a == 0: self.zephyr_connect.enablePacket('RRDATA')
            elif a == 1: self.zephyr_connect.enablePacket('BREATHING')

        self.timer.start()
        # dataset time start:
        self.ds_rri.setStartTime()
        self.ds_bw.setStartTime()
        # handle graphical change:
        self.playAction.setEnabled( False )
        self.timedAction.setEnabled( False )
        self.stopAction.setEnabled( True )

    def session_stop(self):
        if USE_TEST_DATA is True:
            self.zephyr_connect.running = False # doesn't work yet!
            self.zephyr_connect.terminate()     # doesn't work yet!
        for a in self.appsettings.dataset.bh_packets:
            if a == 0: self.zephyr_connect.disablePacket('RRDATA')
            elif a == 1: self.zephyr_connect.disablePacket('BREATHING')
        self.timer.stop()
        # handle graphical change:
        self.playAction.setEnabled( True )
        self.timedAction.setEnabled( True )
        self.stopAction.setEnabled( False )

        # store the current session?
        if self.appsettings.dataset.enable_database or self.appsettings.dataset.enable_files:
            sel = QMessageBox.question(self, "Save Session", "Store the current session?", "Yes", "No")
            if sel == 0:
                self.datastorage.store_session()


class DockablePlotWidget( DockableWidget ):
    LOCATION = Qt.RightDockWidgetArea
    def __init__(self, parent, widgetclass, toolbar = None):
        super(DockablePlotWidget, self).__init__(parent)
        self.toolbar = toolbar
        layout = QVBoxLayout()
        self.widget = widgetclass()
        layout.addWidget(self.widget)
        self.setLayout(layout)

    def get_plot(self):
        return self.widget.plot

class RealTimePlot():
    """ Real time Qwt plot object. 
    """
    def __init__(self, parent, ytitle="Y", color=QColor( 255, 0, 0 )):
        self.curve = make.curve( [ ], [ ], '(Curve Name)', color )
        self.curvewidget    = DockablePlotWidget(parent, CurveWidget)
        self.curvewidget.widget.plot.add_item( self.curve )
        self.curvewidget.widget.plot.set_antialiasing( True )
        self.curvewidget.widget.plot.setAxisTitle( QwtPlot.xBottom, 'Time [s]' )
        self.curvewidget.widget.plot.setAxisTitle( QwtPlot.yLeft, ytitle )
        self.curvewidget.widget.plot.setAxisScaleDraw( QwtPlot.xBottom, DateTimeScaleDraw() )
        self.startIdx = 0
        self.window_length = 20 # seconds

    def set_data( self, x, y ):
        self.curve.set_data( x, y )

    def update( self, x, y ):
        self.curve.set_data( x[self.startIdx:-1], y[self.startIdx:-1] )
        self.curvewidget.widget.plot.do_autoscale()
        self.curvewidget.widget.plot.replot()

class DateTimeScaleDraw( QwtScaleDraw ):
    """Class used to draw a datetime axis on the plot.
    """
    def __init__( self, *args ):
        QwtScaleDraw.__init__( self, *args )

    def label( self, value ):
        """ Function used to create the text of each label
        used to draw the axis.
        """
        dt = datetime.datetime.fromtimestamp( value )
        return QwtText( '%s' % dt.strftime( '%H:%M:%S' ) )

class Timer( QThread ):
    def __init__( self, parent ):
        QThread.__init__(self, parent)
        self.stopped = False
        self.currsecond = 0
        self.asc = True

        self.toolbar_time = parent.addToolBar('Time')
        self.toolbar_time.setMovable( False )
        self.timer = QLineEdit()
        self.timer.setStyleSheet("QLineEdit { font-size: 19px; font-family: Courier New; \
                                border-style: outset; border-radius: 10px; \
                                font-weight:bold; text-align:center}")
        self.timer.setFixedWidth(80)
        self.timer.setReadOnly( True )
        self.timer.setAlignment( Qt.AlignHCenter )

        left_spacer = QWidget()
        left_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar_time.addWidget( left_spacer )
        self.toolbar_time.addWidget( self.timer )

        self.initialize(0)

    def run( self ):
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

    def stop(self):
        self.stopped = True

    def initialize( self, nbseconds ):
        self.currsecond = nbseconds
        self.update_timer_display( nbseconds )
        if nbseconds > 0:
            self.asc = False

    def update_timer_display( self, nbseconds ):
        minutes = nbseconds/60
        seconds = nbseconds-minutes*60
        timer_string = "%02d:%02d" % ( minutes, seconds )
        self.timer.setText(timer_string)
            