import MySQLdb as mdb
from datetime import datetime

class DataStorage():
    def __init__( self, settings = None, timeseries = None ):
        self.settings = settings
        self.timeseries = timeseries

    def db_connect(self):
        return mdb.connect(str(self.settings.db_host), str(self.settings.db_user),
                            str(self.settings.db_pwd), str(self.settings.db_dbname))

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


    def store_session( self, sessiondata ):

        # store in database
        if self.settings.enable_database and self.timeseries.isNotEmpty():
            # connection
            con = self.db_connect()

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
            data = (today, sessiondata['duration'], rriseries_txt, bwseries_txt, sessiondata['sessiontype'],
            sessiondata['breathing_zone'], sessiondata['note'])
            with con:
                cur = con.cursor()
                cur.execute("INSERT INTO records_record(create_datetime, duration, rrintervals, breathingwave, "
                            "session_type, breathing_zone, note) "
                            "VALUE(%s, %s, %s, %s, %s, %s, %s)", data)
                lastinsertid = con.insert_id()
                alerts = '\n'.join( sessiondata['alerts'] )
                cur.execute( "INSERT INTO sound_alerts(record_id, alerts) VALUE(%s, %s)", (lastinsertid,alerts) )




    def get_session_types(self):
        con = self.db_connect()
        with con:
            cur = con.cursor()
            cur.execute("SELECT * FROM session_type")
            types = cur.fetchall()
            return types

    def get_breathing_zones(self):
        con = self.db_connect()
        with con:
            cur = con.cursor()
            cur.execute("SELECT * FROM breathing_zone")
            rows = cur.fetchall()
            return rows