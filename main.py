import sys
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow
from version import __version__


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KYRiE")
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
