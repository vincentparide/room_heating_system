# main.py
import sys
from PyQt5 import QtWidgets
from ui_main import MainWindow

def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        app.quit()
        sys.exit(0)

if __name__ == "__main__":
    main()
