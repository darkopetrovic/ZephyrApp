import numpy as np
import lomb

STORE_ALL_ELEMENTS = False

class RRI_BW_Data():
    '''
    '''
    def __init__( self ):
        self.window_duration = 10    # default 30 secs window

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
        
    def setStartTime(self, starttime):
        self.rri_realtime = np.append(self.rri_realtime, starttime)
        self.bw_realtime = np.append( self.bw_realtime, starttime )

    def add_rrinterval( self, rri_ms ):
        self.rri_cumulativeTime += rri_ms
        self.rri_series = np.append( self.rri_series, rri_ms )
        self.rri_smpltime = np.append( self.rri_smpltime, self.rri_cumulativeTime )
        self.rri_realtime = np.append( self.rri_realtime, self.rri_realtime[-1]+float(rri_ms)/1000 )

        if STORE_ALL_ELEMENTS is not True:
            self._getSampleIndex()
            # remove the first element in the array
            if self.idx_start != 0:
                self.rri_series = np.delete(self.rri_series, 0)
                self.rri_smpltime = np.delete( self.rri_smpltime, 0)
                self.rri_realtime = np.delete( self.rri_realtime, 0)

    def add_breathing( self, value ):
        self.bw_series = np.append(self.bw_series, value)
        # The breathing data are sampled at 18 Hz (56ms)
        self.bw_realtime = np.append(self.bw_realtime, self.bw_realtime[-1]+float(56)/1000)

    def _getSampleIndex( self ):
        """ Get the index in the sample time array where the value
         correspond to a number of 'seconds' back from the last element """
        self.idx_start = np.where(self.rri_smpltime > self.rri_smpltime[-1]-self.window_duration*1000)[0][0]

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