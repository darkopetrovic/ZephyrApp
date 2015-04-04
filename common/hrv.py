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

import numpy as np
import lomb
import time
from scipy.sparse import spdiags, eye
from scipy.signal import welch
from scipy import interpolate
from numpy.linalg import inv
from PyQt4.QtCore import QThread
import MySQLdb as mdb

STORE_ALL_ELEMENTS = True


class TimeSeriesContainer():
    """ Container to store and perform operations
        on all times series.
    """
    def __init__( self ):
        self.ts_rri = RRIntervals()
        self.ts_bw = BreathingWave()
        self.ts_ecg = ECG()
        self.heart_rate = np.array([])
        self.respiration_rate = np.array([])
        self.posture = np.array([])
        self.activity = np.array([])
        self.breathwave_ampltitude = np.array([])

    def isNotEmpty(self):
        if self.ts_rri.series.size or self.ts_bw.series.size:
            return True
        else:
            return False

    def clearContainer(self):
        self.ts_rri.clear()
        self.ts_bw.clear()
        self.heart_rate = np.array([])
        self.respiration_rate = np.array([])
        self.posture = np.array([])
        self.activity = np.array([])
        self.breathwave_ampltitude = np.array([])


class TimeSeries():
    """ Class for general functions on times series objects.
    """
    def __init__( self ):
        self.clear()

    def clear(self):
        self.series = np.array([])
        self.smpltime = np.array([])
        self.realtime = np.array([])
        self.psd_mag = np.array([])
        self.psd_freq = np.array([])
        self.sdnn = np.array([])
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

    def computeSDNN( self ):
        if len(self.series) > 2:
            self.sdnn = np.append(self.sdnn, self.series[self.idx_start:-1].std(ddof=1))
        else:
            return 0.0

    def computePSD( self ):
        if len(self.series) > 10:

            fx, fy, nout, jmax, prob = lomb.fasper( self.smpltime[self.idx_start:-1]/1000,
                                                   self.series[self.idx_start:-1]/1000,
                                                   4., 2.)
            pwr = ( ( self.series[self.idx_start:-1]/1000-(self.series[self.idx_start:-1]/1000).mean())**2).sum() \
                    /(len(self.series[self.idx_start:-1])-1)
            fy = fy/(nout/(4.0*pwr))*1000
            self.psd_mag = fy
            self.psd_freq = fx

            # Calculate frequencies power components VLF, LF and HF
            self.VLFpwr = 0
            self.LFpwr = 0
            self.HFpwr = 0
            for i, f in enumerate( self.psd_freq ):
                if 0 < f <= 0.04:
                    self.VLFpwr += self.psd_mag[i]
                elif 0.04 < f <= 0.15:
                    self.LFpwr += self.psd_mag[i]
                elif 0.15 < f <= 0.4:
                    self.HFpwr += self.psd_mag[i]

            self.VLFpwr *= 1000
            self.LFpwr *= 1000
            self.HFpwr *= 1000


class RRIntervals( TimeSeries ):
    def __init__( self ):
        TimeSeries.__init__( self )

    def add_rrinterval( self, rri_ms ):
        self.add( rri_ms, rri_ms )

    def detrendRRI(self, lbda=50):
        z = self.series
        T = len(z)
        lambdaa = lbda
        I = eye(T)
        D2 = spdiags( (np.ones((T,1), dtype=np.int)*np.array([1,-2,1])).T,np.arange(0,3),T-2,T)
        z_stat = (I.toarray()-inv((I+lambdaa**2*D2.H*D2).toarray()))*np.asmatrix(z.reshape(T,1))
        return z_stat

    def computeLombPeriodogram( self ):
        detrend = False

        lombx = self.smpltime[self.idx_start:-1]/1000
        if detrend is True:
            # static component (we remove the dynamic component of the signal -> detrending)
            z_stat = self.detrendRRI()
            lomby = np.asarray(z_stat.H)[0][self.idx_start:-1]/1000
        else:
            lomby = self.series[self.idx_start:-1]

        fx, fy, nout, jmax, prob = lomb.fasper(lombx,lomby, 4., 2.)
        pwr = ((lomby-lomby.mean())**2).sum()/(len(lomby)-1)
        fy_smooth = np.array([])
        fx_smooth = np.array([])
        maxout = int(nout/2)
        for i in xrange(0,maxout,4):
            fy_smooth = np.append(fy_smooth, (fy[i]+fy[i+1]+fy[i+2]+fy[i+3])/(nout/(2.0*pwr)))
            fx_smooth = np.append(fx_smooth, fx[i])
        fy_smooth = fy_smooth/4*1e3

        # pwr = ( ( self.series[self.idx_start:-1]/1000-(self.series[self.idx_start:-1]/1000).mean())**2).sum() \
        #         /(len(self.series[self.idx_start:-1])-1)
        # fy = fy/(nout/(4.0*pwr))*1000

        self.psd_mag = fy
        self.psd_freq = fx

        # Calculate frequencies power components VLF, LF and HF
        self.VLFpwr = 0
        self.LFpwr = 0
        self.HFpwr = 0
        for i, f in enumerate( self.psd_freq ):
            if 0 < f <= 0.04:
                self.VLFpwr += self.psd_mag[i]
            elif 0.04 < f <= 0.15:
                self.LFpwr += self.psd_mag[i]
            elif 0.15 < f <= 0.4:
                self.HFpwr += self.psd_mag[i]

        self.VLFpwr *= 1000
        self.LFpwr *= 1000
        self.HFpwr *= 1000

    def computeSDNN( self ):
        if len(self.series) > 2:
            z_stat = self.detrendRRI()
            rri_series_detrended = np.asarray(z_stat.H)[0]
            self.sdnn = np.append( self.sdnn, rri_series_detrended[self.idx_start:-1].std(ddof=1) )
        else:
            return 0.0


class BreathingWave( TimeSeries ):
    def __init__( self ):
        TimeSeries.__init__( self )
        self.min = np.array([])
        self.max = np.array([])
        self.minmax_time = np.array([])
        self.minmax_val = np.array([])
        self.amplitude = np.array([])
        self.last_index_of_minmax = 0

    def add_breath( self, values ):
        # The breathing data are sampled at 18 Hz (56ms)
        for value in values:
            self.add( value, 56 )

    def computeWelchPeriodogram(self, window=60):
        """
        Compute the Power Spectral Density of the breathing.
        """
        # Since the breahing signal is sampled at 18Hz, the start index is calculated as follow
        # for a window length defined by the variable window_length in seconds: window_length*18
        startindex = window*18
        f, Pxx_den = welch(self.series[-startindex:], 18, nperseg=len(self.series[-startindex:]))
        self.psd_mag = Pxx_den
        self.psd_freq = f

    def interpolateSignal(self, smoothing=20):
        """ Interpolate the breathing wave signal.
            Used to find the amplitude of the signal with the min/max value.
        """
        tck = interpolate.splrep(self.realtime[-50:], self.series[-50:], s=smoothing)
        xmin = self.realtime[-50]
        xmax = self.realtime[-1]
        step = 1.0/16.0
        smpltime_inter = np.arange(xmin, xmax, step)
        smplvalue_inter = interpolate.splev(smpltime_inter, tck, der=0)
        return smpltime_inter, smplvalue_inter

    def calculateMinMax( self, x, y ):
        """ Store in the numpy arrays 'minmax_time' and 'minmax_val' the
            peaks of the curve.

            :param array x:    x axis
            :param array y:    y axis
        """

        # Return an array of index of the min/max values.
        index_of_minmax = np.diff(np.sign(np.diff(y))).nonzero()[0] + 1 # local min+max
        # index_of_min = (np.diff(np.sign(np.diff(self.series[self.idx_start:-1]))) > 0).nonzero()[0] + 1 # local min
        # index_of_max = (np.diff(np.sign(np.diff(self.series[self.idx_start:-1]))) < 0).nonzero()[0] + 1 # local max

        if self.minmax_time.size == 0:
            for i in index_of_minmax:
                self.minmax_time = np.append( self.minmax_time, x[i] )
                self.minmax_val = np.append( self.minmax_val, y[i] )
            self.last_time = self.minmax_time[-1]
        else:
            for i in index_of_minmax:
                # the new min/max must be 1 second earlier that the last
                if x[i] > self.last_time+1:
                    self.minmax_time = np.append( self.minmax_time, x[i] )
                    self.minmax_val = np.append( self.minmax_val, y[i] )
                    self.last_time = self.minmax_time[-1]

class ECG( TimeSeries ):
    def __init__( self ):
        TimeSeries.__init__( self )
        self.rpeaks_time = np.array([])
        self.rpeaks_value = np.array([])
        self.tpeaks_time = np.array([])
        self.tpeaks_value = np.array([])

    def add_ecg( self, values ):
        #  Each ECG Waveform sample is 4ms later than the previous one.
        for value in values:
            self.add( value, 4 )