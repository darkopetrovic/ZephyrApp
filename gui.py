import sys, os
import datetime
import time

from guidata.qt.QtGui import QWidget, QMainWindow, QVBoxLayout, qApp, QTextEdit,\
                               QFont, QColor, QLabel
from guidata.qtwidgets import DockableWidget
from guidata.qt.QtCore import Qt, QThread, SIGNAL
from guiqwt.plot import CurveWidget, CurvePlot
from guiqwt.builder import make
from guiqwt.config import _
from PyQt4.Qwt5.Qwt import QwtPlot, QwtScaleDraw, QwtText

# From own files:
#sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from common.hrv import RRI_BW_Data
from common.device_zephyr import ZephyrConnect
from noise import MakeNoise
  
APP_NAME = _("Very simple heart rate monitor")
 
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
 
class MainWindow(QMainWindow):
    def __init__(self):
        QMainWindow.__init__(self)
        # Allow dockable widgets to be side by side
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks)  
        self.setGeometry(300,200,1000,600)

        self.curvewidget    = DockablePlotWidget(self, CurveWidget)
        self.logarea        = DockablePlotWidget(self, QTextEdit)
        self.infobox        = DockablePlotWidget(self, QWidget)
        self.curveplot      = self.curvewidget.get_plot()
        self.logarea.widget.setReadOnly( True )
        self.logarea.widget.setFont( QFont("Courier", 8) )
        self.logarea.widget.setMinimumHeight(200)
        self.logarea.widget.setMinimumWidth(500)
        self.infobox.widget.setMinimumHeight(200)
        self.infobox.widget.setMinimumWidth(200)
     
        self.rri_curve = make.curve( [ ], [ ], 'RRI', QColor( 255, 0, 0 ) )
        self.curvewidget.widget.plot.add_item( self.rri_curve )
        self.curvewidget.widget.plot.set_antialiasing( True )
        self.curvewidget.widget.plot.setAxisTitle( QwtPlot.xBottom, 'Time [s]' )
        self.curvewidget.widget.plot.setAxisTitle( QwtPlot.yLeft, 'RR-Interval [ms]' )
        self.curvewidget.widget.plot.setAxisScaleDraw( QwtPlot.xBottom, DateTimeScaleDraw() )

        self.lbl_sdnn = QLabel( self.infobox.widget )
        self.lbl_sdnn.setText("SDNN: %3.1f ms    " % 0.0)
        self.lbl_sdnn.move(20, 40)
        self.lbl_sdnn.setFont(QFont("Arial", 20))

        # Add the DockWidget to the main window
        self.curve_dock = self.add_dockwidget( self.curvewidget, _("RR-Intervals Plot"), Qt.Vertical, position=Qt.TopDockWidgetArea )        
        self.log_dock = self.add_dockwidget( self.logarea, _("Logs"), Qt.Horizontal, Qt.RightDockWidgetArea)
        self.info_dock = self.add_dockwidget( self.infobox, _("Infobox"), Qt.Horizontal, Qt.LeftDockWidgetArea )        
 
        self.show()
        # After this call the widget will be visually in front of any 
        # overlapping sibling widgets.
        self.curve_dock.raise_()

        self.start_time = time.time()
        self.dh = RRI_BW_Data()  
        self.dh.setStartTime( self.start_time )

        self.zephyr_connect = ZephyrConnect()
        self.connect( self.zephyr_connect, SIGNAL( 'newRRI' ), self.update_RR_plot )
        self.zephyr_connect.start()

        self.logmessage("BioHarness 3.0 connected.")

        self.noise = MakeNoise()
        self.noise.start()
 
     #------GUI refresh/setup
    def add_dockwidget(self, child, title, orientation = Qt.Vertical, position=None ):
        """Add QDockWidget and toggleViewAction"""
        dockwidget, location = child.create_dockwidget( title )
        if position is not None:
            location = position
        self.addDockWidget( location, dockwidget, orientation )
        return dockwidget

    def logmessage( self, text, type='info' ):

        if type == 'error':
            self.logarea.widget.setTextColor( QColor( 255, 0, 0 ) )
        else:
            self.logarea.widget.setTextColor( QColor( 0, 0, 0 ) )

        self.logarea.widget.insertPlainText( text + "\n" )
        sb = self.logarea.widget.verticalScrollBar()
        sb.setValue( sb.maximum() )

    def update_RR_plot( self, value ):
        # Store value in the array
        self.dh.add_rrinterval( value )
        # Set the data to the curve with values from the array
        self.rri_curve.set_data( self.dh.rri_realtime, self.dh.rri_series )
        # Update the plot 
        self.curvewidget.widget.plot.do_autoscale()
        self.curveplot.replot()
        self.logmessage( "Incoming RRI: %i ms" % value )
        sdnn = float("%3.1f" % self.dh.compute_SDNN())
        self.lbl_sdnn.setText( "SDNN: %3.1f ms" % sdnn )
        
        # we considere that a SDNN of 150 is very good
        if int(sdnn) >= 100:
            noisegain=0
        elif int(sdnn) < 100 and int(sdnn) >= 80:
            noisegain=0.02
        elif int(sdnn) < 80 and int(sdnn) >= 60:
            noisegain=0.04
        elif int(sdnn) < 60 and int(sdnn) >= 40:
            noisegain=0.08
        elif int(sdnn) < 40:
            noisegain=0.3

        self.noise.setValue( noisegain )

class DateTimeScaleDraw( QwtScaleDraw ):
    '''Class used to draw a datetime axis on the plot.
    '''
    def __init__( self, *args ):
        QwtScaleDraw.__init__( self, *args )

    def label( self, value ):
        '''Function used to create the text of each label
        used to draw the axis.
        '''
        dt = datetime.datetime.fromtimestamp( value )
        return QwtText( '%s' % dt.strftime( '%H:%M:%S' ) )

