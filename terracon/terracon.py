#!/usr/bin/python3

import sys
from PyQt5 import QtWidgets


def main():
	app = QtWidgets.QApplication(sys.argv)

	mainwnd = QtWidgets.QWidget()
	#w.resize(250, 150)
	#w.move(300, 300)
	mainwnd.setWindowTitle('TerraCon')
	mainwnd.show()

	sys.exit(app.exec())


if __name__ == '__main__':
	main()

