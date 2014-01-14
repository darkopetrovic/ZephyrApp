import MySQLdb as mdb
from datetime import datetime

class DataStorage():
    def __init__( self, settings = None, timeseries = None ):
        self.settings = settings
        self.timeseries = timeseries

    def db_connect(self):
        return mdb.connect(self.settings.db_host, self.settings.db_user,
                          self.settings.db_pwd, self.settings.db_dbname)

    def test_db_connection(self):
        con = None
        try:
            con = self.db_connect()
            cur = con.cursor()
            cur.execute("SELECT VERSION()")
            ver = cur.fetchone()
            return True, ver

        except mdb.Error, e:
            return False, e.args[1]

        finally:
            if con:
                con.close()


    def store_session( self, duration ):

        # store in database
        if self.settings.enable_database and self.timeseries.isNotEmpty():
            # connection
            con = mdb.connect(str(self.settings.db_host), str(self.settings.db_user),
                              str(self.settings.db_pwd), str(self.settings.db_dbname))

            rriseries_txt = bwseries_txt = ''
            if self.timeseries.ts_rri.series.size:
                for i, value in enumerate(self.timeseries.ts_rri.series):
                    rriseries_txt += str(int(self.timeseries.ts_rri.smpltime[i])) + ':' + str(int(value))
                    rriseries_txt += '\n'

            if self.timeseries.ts_bw.series.size:
                for i, value in enumerate(self.timeseries.ts_bw.series):
                    bwseries_txt += str(int(self.timeseries.ts_bw.smpltime[i])) + ':' + str(int(value))
                    bwseries_txt += '\n'

            today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data = (today, duration, rriseries_txt, bwseries_txt)
            with con:
                cur = con.cursor()
                cur.execute("INSERT INTO records(datetime, duration, rrintervals, breathingwave) "
                            "VALUE(%s, %s, %s, %s)", data)
