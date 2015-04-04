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

from influxdb import client as influxdb
from pandas import DataFrame
from requests.exceptions import ConnectionError
import time

class DataStorage():
    def __init__( self ):
        self.settings = None

    def db_init(self, settings = None):
        if hasattr(settings, 'enable_database') is True:
            self.settings = settings
        elif isinstance(settings, dict):
            # create object from the dictionary
            self.settings = type('Settings', (object,), settings)
            self.settings.enable_database = True

    def db_connection(self):
        dbname =  str(self.settings.db_dbname)
        result = True
        try:
            self.db = influxdb.InfluxDBClient(str(self.settings.db_url), str(self.settings.db_port),
                                          str(self.settings.db_user), str(self.settings.db_pwd),
                                          str(self.settings.db_dbname))
            dblist = self.db.get_database_list()
        except (influxdb.InfluxDBClientError, ConnectionError) as e:
            return False, e.args[0]

        if not any([db['name'] == dbname for db in dblist]):
            self.db.create_database( dbname )
            message = "The InfluxDB database '%s' was created." % dbname
        else:
            message = "Successfully connected to the InfluxDB database '%s'." % dbname

        return result, message

    @staticmethod
    def _result2dataframe(r):
        return DataFrame(r[0]['points'], columns=r[0]['columns'])

    def create_session(self):
        # get the last session id
        last_session = self._result2dataframe( self.db.query('select * from all_sessions limit 1') )
        lastid = int(last_session['id'])

        data = [{
                    "name": "all_sessions",
                    "columns":["time", "id", "duration_sec", "session_type", "breathing_zone", "note"],
                    "points":[[time.time(), lastid+1, "", "", "", ""]]
                }]

        self.db.write_points(data)

    def update_duration(self, duration):
        r = self.db.query('select time, sequence_number from all_sessions limit 1 order desc')
        data = [{
                    "name": "all_sessions",
                    "columns":["time", "sequence_number", "duration_sec"],
                    "points":[[r[0]['points'][0][0], r[0]['points'][0][1], duration]]
                }]
        self.db.write_points(data)

    def add_informations( self, sessiondata ):
        if self.settings.enable_database:
            r = self.db.query('select time, sequence_number from all_sessions limit 1 order desc')
            data = [{
                        "name": "all_sessions",
                        "columns":["time", "sequence_number", "session_type", "breathing_zone", "note"],
                        "points":[[r[0]['points'][0][0], r[0]['points'][0][1],
                                   sessiondata['session_type'], sessiondata['breathing_zone'], sessiondata['note']]]
                    }]
            self.db.write_points(data)

    def write_points(self, series, value, timestamp=None, precision='s'):

        if timestamp is not None:
            columns = ["time", "value"]

            if isinstance(value, list):
                points = [[timestamp[i], val] for i, val in enumerate(value)]
            else:
                points = [[timestamp, value]]
        else:
            columns = ["value"]
            points = [[value]]

        pass

        data = [{
                    "name": series,
                    "columns": columns,
                    "points": points
                }]
        self.db.write_points_with_precision(data, precision)