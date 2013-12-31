import MySQLdb as mdb

class DataStorage():
    def __init__( self, settings = None ):
        self.settings = settings

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


    def store_session( self ):

        if self.settings.enable_database:
            # connection
            con = mdb.connect(self.settings.db_host, self.settings.db_user,
                              self.settings.db_pwd, self.settings.db_dbname)
            with con:

                cur = con.cursor()
                cur.execute("INSERT INTO records(datetime, duration) VALUE(NOW(), 5)")
