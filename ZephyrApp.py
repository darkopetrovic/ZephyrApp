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

from guidata import qapplication
import gui

def main():
    app = qapplication()
    window = gui.MainWindow()
    window.show()
    app.exec_()
 
if __name__ == "__main__":
    main()