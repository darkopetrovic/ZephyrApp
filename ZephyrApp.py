from guidata import qapplication
import gui

def main():
    app = qapplication()
    window = gui.MainWindow()
    window.show()
    app.exec_()
 
if __name__ == "__main__":
    main()