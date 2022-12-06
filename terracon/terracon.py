#!/usr/bin/python3

import sys
from PyQt5 import QtCore, QtWidgets
from enum import Enum


class ScreenType(Enum):
    UNDEFINED = 0
    LCD_1024_600 = 1


APP_NAME = 'TerraCon'
APP_VERSION = '1.0.0'


dark_style_sheet = """
QWidget { color: white; background-color: rgb(53, 53, 53) }
QLabel { font-size: 24px; font-family: Arial; color: lightgray; background-color: rgb(53, 53, 53) }
QPushButton { font-size: 24px; font-family: Arial; color: lightgray; background-color: rgb(53, 53, 53) }
QFrame {
    border: 2px solid rgb(178, 178, 178);
    border-radius: 10px;
    margin-top: 6px;
    padding-top: 8px;
}
QGroupBox {
    border: 2px solid rgb(80, 80, 80);
    border-radius: 5px;
    font-size: 24px; font-family: Arial;
    margin: 10px 0px 0px 3px;
}
QGroupBox::title {
    subcontrol-origin:  margin;
    subcontrol-position: top;
    padding: -8px 0px 0px 3px;
}
"""


def set_style_sheet(item, style_sheet):
    if isinstance(item, QtWidgets.QWidget):
        item.setStyleSheet(style_sheet)
    for child in item.children():
        if isinstance(child, QtWidgets.QWidget):
            set_style_sheet(child, style_sheet)
        elif isinstance(child, QtWidgets.QLayout):
            set_style_sheet(child, style_sheet)


class TerraconWindow(QtWidgets.QWidget):
    def __init__(self, windowed=False):
        super().__init__()
        self.screen_type = ScreenType.LCD_1024_600  # задаем жестко, т.к. пишем скрипт под конкретный дисплей

        self.setWindowTitle(APP_NAME)
        self.mainLayout = QtWidgets.QVBoxLayout()
        self.setLayout(self.mainLayout)

        self.light_percent = 0

        light_group = QtWidgets.QGroupBox("Свет")
        self.mainLayout.addWidget(light_group)

        light_layout = QtWidgets.QHBoxLayout()
        light_group.setLayout(light_layout)

        self.light_label = QtWidgets.QFrame()
        sz = self.width() * 0.2
        self.light_label.setFixedSize(sz, sz)
        light_layout.addWidget(self.light_label)

        self.light_full_button = QtWidgets.QPushButton('100%')
        self.light_full_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding
        )
        light_layout.addWidget(self.light_full_button)
        self.light_off_button = QtWidgets.QPushButton('Выкл')
        light_layout.addWidget(self.light_off_button)
        self.light_off_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding
        )

        self.exitButton = QtWidgets.QPushButton('Выход')
        self.exitButton.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding
        )
        self.mainLayout.addWidget(self.exitButton)

        self.light_full_button.clicked.connect(self.light_full)
        self.light_off_button.clicked.connect(self.light_off)
        self.exitButton.clicked.connect(QtWidgets.QApplication.quit)

        if windowed:
            if self.screen_type == ScreenType.LCD_1024_600:
                self.setFixedSize(1024, 600)

        set_style_sheet(self, dark_style_sheet)

    def light_full(self):
        self.light_percent = 100
        self.update_state()

    def light_off(self):
        self.light_percent = 0
        self.update_state()

    def update_state(self):
        minval = 53
        val = minval + (255 - minval) * (self.light_percent / 100.0)
        style_str = "QWidget {{ color: lightgray; background-color: rgb({}, {}, {}) }}".format(val, val, val)
        self.light_label.setStyleSheet(style_str)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    parser = QtCore.QCommandLineParser()
    parser.addHelpOption()
    parser.addVersionOption()
    windowed_option = QtCore.QCommandLineOption(["w", "windowed"], "Run in windowed mode")
    parser.addOption(windowed_option)

    parser.process(app)

    is_windowed = False
    if parser.isSet(windowed_option):
        is_windowed = True

    mainwnd = TerraconWindow(windowed=is_windowed)
    mainwnd.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()

