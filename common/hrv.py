import numpy as np
import lomb
import time
import MySQLdb as mdb

STORE_ALL_ELEMENTS = True


class TimeSeriesContainer():
    """ Container to store and perform operations
        on all times series.
    """
    def __init__( self ):
        self.ts_rri = RRIntervals()
        self.ts_bw = BreathingWave()

    def isNotEmpty(self):
        if self.ts_rri.series.size or self.ts_bw.series.size:
            return True
        else:
            return False

    def clearContainer(self):
        self.ts_rri.clear()
        self.ts_bw.clear()


class TimeSeries():
    """ Class for general functions on times series objects.
    """
    def __init__( self ):
        self.clear()

    def clear(self):
        self.series = np.array([])
        self.smpltime = np.array([])
        self.realtime = np.array([])
        self.start_time = 0
        self.cumultime = 0
        self.idx_start = 0

    def setStartTime( self ):
        self.start_time = time.time()

    def add( self, value, sampltime_ms ):
        self.series = np.append( self.series, value )
        self.smpltime = np.append( self.smpltime, self.cumultime )
        self.realtime = np.append( self.realtime, self.start_time+float(self.cumultime)/1000 )
        self.cumultime += sampltime_ms

    def getSampleIndex( self, window_size ):
        """ Get the index in the sample time array where the value
         correspond to a number of 'seconds' back from the last element """
        self.idx_start = np.where( self.smpltime > self.smpltime[-1]-window_size*1000 )[0][0]
        return self.idx_start


class RRIntervals( TimeSeries ):
    def __init__( self ):
        TimeSeries.__init__( self )

    def add_rrinterval( self, rri_ms ):
        self.add( rri_ms, rri_ms )

class BreathingWave( TimeSeries ):
    def __init__( self ):
        TimeSeries.__init__( self )

    def add_breath( self, value ):
        # The breathing data are sampled at 18 Hz (56ms)
        self.add( value, 56 )


class RRI_BW_Data():
    '''
    '''
    def __init__( self ):

        self.prev_val = self.prev_rri = 0
        self.rri_series = np.array([])
        self.rri_smpltime = np.array([])
        self.rri_realtime = np.array([])
        self.rri_cumulativeTime = 0

        self.rri_psd_mag = np.array([])
        self.rri_psd_freq = np.array([])

        self.bw_series = np.array([])
        self.bw_realtime = np.array([])

        self.sdnn_max = 0
        self.VLFpwr = 0
        self.LFpwr = 0
        self.HFpwr = 0

        self.idx_start = 0
        
    def setStartTime(self, starttime):
        self.rri_realtime = np.append( self.rri_realtime, starttime )
        self.bw_realtime = np.append( self.bw_realtime, starttime )

    def add_rrinterval( self, rri_ms ):
        self.rri_cumulativeTime += rri_ms
        self.rri_series = np.append( self.rri_series, rri_ms )
        self.rri_smpltime = np.append( self.rri_smpltime, self.rri_cumulativeTime )
        self.rri_realtime = np.append( self.rri_realtime, self.rri_realtime[-1]+float(rri_ms)/1000 )

    def add_breathing( self, value ):
        self.bw_series = np.append( self.bw_series, value )
        # The breathing data are sampled at 18 Hz (56ms)
        self.bw_realtime = np.append( self.bw_realtime, self.bw_realtime[-1]+float(56)/1000 )

    def getSampleIndex( self, window_size ):
        """ Get the index in the sample time array where the value
         correspond to a number of 'seconds' back from the last element """
        self.idx_start = np.where( self.rri_smpltime > self.rri_smpltime[-1]-window_size*1000 )[0][0]
        return self.idx_start

    def setAnalysisWindow( self, seconds ):
        self.window_duration = seconds

    def compute_SDNN( self ):
        if len(self.rri_series) > 2:
            return self.rri_series[self.idx_start:-1].std(ddof=1)
        else:
            return 0.0

    def computePSD( self ):
        if len(self.rri_series) > 10:
            
            fx, fy, nout, jmax, prob = lomb.fasper( self.rri_smpltime[self.idx_start:-1]/1000, 
                                                   self.rri_series[self.idx_start:-1]/1000, 
                                                   4., 1.)
            pwr = ( ( self.rri_series[self.idx_start:-1]/1000-(self.rri_series[self.idx_start:-1]/1000).mean())**2).sum() \
                    /(len(self.rri_series[self.idx_start:-1])-1)
            fy = fy/(nout/(4.0*pwr))*1000
            self.rri_psd_mag = fy
            self.rri_psd_freq = fx

            # Calculate frequencies power components VLF, LF and HF
            self.VLFpwr = 0
            self.LFpwr = 0
            self.HFpwr = 0
            for i, f in enumerate( self.rri_psd_freq ):
                if f > 0 and f <= 0.04:
                    self.VLFpwr += self.rri_psd_mag[i]
                elif f > 0.04 and f <= 0.15:
                    self.LFpwr += self.rri_psd_mag[i]
                elif f > 0.15 and f <= 0.4:
                    self.HFpwr += self.rri_psd_mag[i]
            
            self.VLFpwr *= 1000
            self.LFpwr *= 1000
            self.HFpwr *= 1000